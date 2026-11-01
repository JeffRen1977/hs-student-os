"""Step 24: the replay-safe consumer infrastructure, exercised with a test-only consumer.

No production consumer is registered (the Calc→SAT consumers were removed; course-defined
follow-up rules arrive with Step 24.2). `ProbeConsumer` stands in for one: on every
accepted `assessment.completed` it adds one follow-up task in the *same course*, guarded
by a receipt. The tests prove the guarantees any real consumer will rely on.
"""

from __future__ import annotations

import dataclasses
from datetime import datetime
from typing import Any

import pytest

from app.domain.planner_service import all_tasks, local_today, place_new_task
from app.domain.ports.repositories import Tx
from app.domain.run_execution import ProcessResult
from app.domain.types.actor import ActorContext
from app.domain.types.consumer import ReceiptOutcome
from app.domain.types.event import DomainEvent, EventType
from app.domain.types.outbox import Delivery, OutboxKind
from app.domain.types.task import TaskReason, TaskReasonCode
from app.workers.consumers.base import has_receipt, write_receipt
from tests.support import Harness, build_harness, make_task

ALEX, BETH = "stu_alex", "stu_beth"
PROBE = "probe-follow-up"


class ProbeConsumer:
    name = PROBE
    subscribes = frozenset({EventType.ASSESSMENT_COMPLETED})

    async def handle(self, tx: Tx, actor: ActorContext, event: DomainEvent, now: datetime) -> None:
        target = str(event.payload["assessmentId"])
        if await has_receipt(tx, actor, self.name, event.event_id, target):
            return
        session = await tx.sessions.get(actor, event.session_id or "")
        student = await tx.students.get(actor)
        assert session is not None and student is not None
        placement = place_new_task(
            local_today(now, student.preferences.timezone),
            student.preferences.weekly_available_minutes,
            await all_tasks(tx, actor),
            10,
        )
        task = dataclasses.replace(
            make_task(actor.student_id, f"follow_{event.event_id}", course_id=session.course_id),
            scheduled_date=placement.scheduled_date,
            duration_min=10,
            reason=TaskReason(code=TaskReasonCode.REVIEW_DUE, source_event_ids=(event.event_id,)),
        )
        tx.tasks.save(actor, task, now=now)
        write_receipt(
            tx, actor, consumer=self.name, event=event, target_skill_id=target,
            outcome=ReceiptOutcome.APPLIED, reason="follow_up_added", now=now,
            task_id=task.task_id,
        )  # fmt: skip


@pytest.fixture
def h(clean_env: pytest.MonkeyPatch) -> Harness:
    return build_harness(clean_env, consumers=[ProbeConsumer()])


def follow_ups(h: Harness, sid: str = ALEX) -> list[dict[str, Any]]:
    docs = [h.store.raw(p) for p in h.store.paths(f"students/{sid}/tasks/")]
    return [d for d in docs if d["taskId"].startswith("follow_")]


def receipts(h: Harness, sid: str = ALEX) -> list[dict[str, Any]]:
    return [h.store.raw(p) for p in h.store.paths(f"students/{sid}/consumerReceipts/")]


async def answer_dsat(h: Harness, *, settle: bool = True) -> None:
    """A key-scored DSAT answer: produces assessment.completed with no model."""
    r = await h.client.post(
        "/api/sessions", json={"taskId": "task_alex_dsat_01"}, headers=h.cmd(ALEX)
    )
    r = await h.client.post(
        f"/api/sessions/{r.json()['sessionId']}/submissions",
        json={"questionId": "q_dsat_equiv_001", "questionVersion": "1",
              "answer": {"text": "1: A\n2: C\n3: B", "fileIds": []}},
        headers=h.cmd(ALEX),
    )  # fmt: skip
    assert r.status_code == 202, r.text
    if settle:
        await h.settle()


async def test_effect_receipt_and_offset_commit_once_in_the_same_course(h: Harness) -> None:
    await answer_dsat(h)
    [task] = follow_ups(h)
    assert task["courseId"] == "dsat"  # never another course
    [receipt] = receipts(h)
    assert receipt["consumer"] == PROBE and receipt["taskId"] == task["taskId"]
    offset = h.store.raw(f"students/{ALEX}/consumerState/{PROBE}")
    assert offset["processedSequence"] > 0
    wakes = [h.store.raw(p) for p in h.store.paths(f"students/{ALEX}/outbox/") if "wake." in p]
    assert wakes and all(w["status"] == "completed" for w in wakes)


async def test_duplicate_wakes_and_full_replay_change_nothing(h: Harness) -> None:
    await answer_dsat(h)
    before = (len(follow_ups(h)), len(receipts(h)))
    wake = Delivery(delivery_id="wake.dup", student_id=ALEX, run_id=None, kind=OutboxKind.CONSUMERS)
    for _ in range(2):
        assert await h.services.deliveries.process(wake) is ProcessResult.DONE
    h.store.put(
        f"students/{ALEX}/consumerState/{PROBE}",
        {"consumer": PROBE, "processedSequence": 0, "updatedAt": h.clock.now()},
    )
    await h.services.deliveries.process(wake)
    assert (len(follow_ups(h)), len(receipts(h))) == before


async def test_crash_before_consumer_commit_retries_and_applies_exactly_once(h: Harness) -> None:
    await answer_dsat(h, settle=False)
    assert await h.drain() == 1  # the run commits; its consumer wake is now pending
    await h.services.dispatcher.dispatch_pending()
    h.store.fail_next_commits = 1
    [pending] = h.queue.pending()
    assert await h.services.deliveries.process(pending) is ProcessResult.RETRY
    assert follow_ups(h) == [] and receipts(h) == []  # rolled back together
    await h.settle()
    assert len(follow_ups(h)) == 1 and len(receipts(h)) == 1


async def test_lost_wake_is_reissued_by_recovery(h: Harness) -> None:
    await answer_dsat(h, settle=False)
    await h.drain()
    await h.services.dispatcher.dispatch_pending()
    h.queue._pending.clear()  # the queue loses the wake after it was marked dispatched
    await h.settle()
    assert follow_ups(h) == []
    assert await h.services.recovery.reissue_stalled_wakes() == 0  # not stale yet
    h.clock.advance(seconds=h.services.settings.run_requeue_after_seconds + 1)
    assert await h.services.recovery.reissue_stalled_wakes() == 1
    await h.settle()
    assert len(follow_ups(h)) == 1


async def test_wake_for_another_student_touches_only_that_student(h: Harness) -> None:
    await answer_dsat(h)
    snapshot = {p: h.store.raw(p) for p in h.store.paths(f"students/{ALEX}/")}
    wake = Delivery(delivery_id="wake.x", student_id=BETH, run_id=None, kind=OutboxKind.CONSUMERS)
    await h.services.deliveries.process(wake)
    assert {p: h.store.raw(p) for p in h.store.paths(f"students/{ALEX}/")} == snapshot
    assert receipts(h, BETH) == [] and follow_ups(h, BETH) == []


async def test_without_consumers_no_wake_is_written(clean_env: pytest.MonkeyPatch) -> None:
    h = build_harness(clean_env)  # production wiring: no consumer registered
    await answer_dsat(h)
    assert not [p for p in h.store.paths(f"students/{ALEX}/outbox/") if "wake." in p]
    assert receipts(h) == []
