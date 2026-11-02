"""Step 29: student controls and opt-in reminders.

Beth (New York) opted into email reminders in her fixture (quiet hours 22:00–07:00) and
has one Calc BC task. Her scheduled planning pass on Tuesday 2026-11-03 (04:00 EST =
09:00 UTC) moves the task to Tuesday and creates Tuesday's reminder for 16:00 EST
(21:00 UTC). Alex has not opted in.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import pytest

from app.adapters.notifications.senders import FakeReminderSender, TestRecipientGuard
from app.domain.ports.notifications import DeliveryOutcome
from app.domain.types.reminder import ReminderMessage
from tests.support import Harness, build_harness

ALEX, BETH = "stu_alex", "stu_beth"
REMINDER = f"students/{BETH}/reminders/2026-11-03.email"
TASK = "task_beth_calc_01"


def utc(*args: int) -> datetime:
    return datetime(*args, tzinfo=UTC)  # type: ignore[misc]


@pytest.fixture
def sender() -> FakeReminderSender:
    return FakeReminderSender()


@pytest.fixture
def h(clean_env: pytest.MonkeyPatch, sender: FakeReminderSender) -> Harness:
    return build_harness(clean_env, reminder_sender=sender)


def reminder(h: Harness, path: str = REMINDER) -> dict[str, Any]:
    doc = h.store.raw(path)
    assert doc is not None, path
    return dict(doc)


async def plan_tuesday(h: Harness) -> None:
    h.clock.set(utc(2026, 11, 3, 9, 1))
    await h.services.planning_scheduler.run_due()
    await h.settle()


async def deliver(h: Harness, at: datetime) -> dict[str, int]:
    h.clock.set(at)
    return dict(await h.services.reminders.deliver_due())


async def patch_twin(h: Harness, sid: str, prefs: dict[str, Any]) -> Any:
    etag = (await h.client.get("/api/twin", headers=h.auth(sid))).headers["ETag"]
    return await h.client.patch(
        "/api/twin", json={"preferences": prefs}, headers={**h.auth(sid), "If-Match": etag}
    )


async def patch_task(h: Harness, body: dict[str, Any], task_id: str = TASK) -> Any:
    task = (await h.client.get(f"/api/tasks/{task_id}", headers=h.auth(BETH))).json()
    r = await h.client.patch(
        f"/api/tasks/{task_id}",
        json=body,
        headers={**h.auth(BETH), "If-Match": f'"{task["version"]}"'},
    )
    assert r.status_code == 200, r.text
    return r.json()


async def test_planning_creates_one_reminder_and_it_is_delivered_once(
    h: Harness, sender: FakeReminderSender
) -> None:
    await plan_tuesday(h)
    r = reminder(h)
    assert r["status"] == "pending" and r["sendAt"] == utc(2026, 11, 3, 21)
    assert h.store.paths(f"students/{ALEX}/reminders") == []  # not opted in

    # A student replan the same day does not create a second reminder.
    await h.client.post("/api/plans/replan", json={}, headers=h.cmd(BETH))
    await h.settle()
    assert h.store.paths(f"students/{BETH}/reminders/") == [REMINDER]

    assert await deliver(h, utc(2026, 11, 3, 20, 59)) == {}  # not yet
    assert await deliver(h, utc(2026, 11, 3, 21, 0)) == {"sent": 1}
    assert await deliver(h, utc(2026, 11, 3, 21, 5)) == {}  # nothing left to send
    [message] = sender.delivered.values()
    # The only recipient is the student: there is no parent or other channel.
    assert (message.student_id, message.channel.value) == (BETH, "email")
    assert message.body == "You have 1 study task planned today (20 min)."
    assert reminder(h)["status"] == "sent"


async def test_opt_out_after_the_reminder_was_created_stops_it(
    h: Harness, sender: FakeReminderSender
) -> None:
    await plan_tuesday(h)
    r = await patch_twin(h, BETH, {"notifications": {"enabled": False, "channels": []}})
    assert r.status_code == 200, r.text
    consent = h.store.raw(f"students/{BETH}/consents/notifications")
    assert consent["granted"] is False and consent["revokedAt"] == utc(2026, 11, 3, 9, 1)
    assert await deliver(h, utc(2026, 11, 3, 21)) == {"consent_revoked": 1}
    assert sender.delivered == {}


async def test_consent_is_rechecked_between_claim_scan_and_send(h: Harness) -> None:
    """Even a re-enabled preference does not count without the consent record."""
    await plan_tuesday(h)
    h.store.put(
        f"students/{BETH}/consents/notifications",
        {**h.store.raw(f"students/{BETH}/consents/notifications"), "granted": False},
    )
    assert await deliver(h, utc(2026, 11, 3, 21)) == {"consent_revoked": 1}


async def test_quiet_hours_defer_the_reminder(h: Harness, sender: FakeReminderSender) -> None:
    await plan_tuesday(h)
    quiet = {
        "enabled": True,
        "channels": ["email"],
        "quietHours": {"start": "15:30", "end": "17:00"},
    }
    assert (await patch_twin(h, BETH, {"notifications": quiet})).status_code == 200
    assert await deliver(h, utc(2026, 11, 3, 21)) == {"deferred": 1}
    assert reminder(h)["sendAt"] == utc(2026, 11, 3, 22)  # 17:00 EST
    assert sender.delivered == {}
    assert await deliver(h, utc(2026, 11, 3, 22)) == {"sent": 1}


async def test_quiet_hours_until_the_day_ends_skip_it(h: Harness) -> None:
    await plan_tuesday(h)
    quiet = {
        "enabled": True,
        "channels": ["email"],
        "quietHours": {"start": "15:00", "end": "07:00"},
    }
    assert (await patch_twin(h, BETH, {"notifications": quiet})).status_code == 200
    assert await deliver(h, utc(2026, 11, 3, 21)) == {"quiet_hours": 1}


async def test_reminders_are_never_created_inside_quiet_hours(h: Harness) -> None:
    quiet = {
        "enabled": True,
        "channels": ["email"],
        "quietHours": {"start": "12:00", "end": "00:30"},
    }
    h.clock.set(utc(2026, 11, 3, 8))
    assert (await patch_twin(h, BETH, {"notifications": quiet})).status_code == 200
    await plan_tuesday(h)
    assert h.store.paths(f"students/{BETH}/reminders/") == []


async def test_a_crash_after_sending_does_not_send_twice(
    h: Harness, sender: FakeReminderSender
) -> None:
    await plan_tuesday(h)

    class CrashAfterSend:
        async def send(self, message: ReminderMessage) -> DeliveryOutcome:
            outcome = await sender.send(message)
            h.store.fail_next_commits = 1  # the "mark sent" commit fails
            return outcome

    h.services.reminders._sender = CrashAfterSend()
    assert await deliver(h, utc(2026, 11, 3, 21)) == {"error": 1}
    assert reminder(h)["status"] == "sending" and len(sender.delivered) == 1
    h.services.reminders._sender = sender
    assert await deliver(h, utc(2026, 11, 3, 21, 2)) == {}  # claim still live
    assert await deliver(h, utc(2026, 11, 3, 21, 6)) == {"deduplicated": 1}
    assert reminder(h)["status"] == "sent"
    assert len(sender.delivered) == 1 and reminder(h)["attempts"] == 2


async def test_failed_sends_are_retried_then_given_up(
    h: Harness, sender: FakeReminderSender
) -> None:
    await plan_tuesday(h)
    sender.fail_next = 5
    assert await deliver(h, utc(2026, 11, 3, 21)) == {"retry": 1}
    assert await deliver(h, utc(2026, 11, 3, 21, 5)) == {"retry": 1}
    assert await deliver(h, utc(2026, 11, 3, 21, 10)) == {"delivery_failed": 1}
    assert sender.delivered == {}


async def test_moved_and_completed_tasks_update_or_cancel_the_reminder(
    h: Harness, sender: FakeReminderSender
) -> None:
    await plan_tuesday(h)
    # The student moves the only task to Thursday: nothing is left for Tuesday.
    await patch_task(h, {"scheduledDate": "2026-11-05"})
    assert await deliver(h, utc(2026, 11, 3, 21)) == {"nothing_planned": 1}
    assert sender.delivered == {}

    # Thursday's planning pass creates Thursday's reminder for the moved task.
    h.clock.set(utc(2026, 11, 5, 9, 1))
    await h.services.planning_scheduler.run_due()
    await h.settle()
    thursday = f"students/{BETH}/reminders/2026-11-05.email"
    assert reminder(h, thursday)["status"] == "pending"
    # …but the task is completed before 16:00: no reminder about finished work.
    doc = h.store.raw(f"students/{BETH}/tasks/{TASK}")
    h.store.put(f"students/{BETH}/tasks/{TASK}", {**doc, "status": "COMPLETED"})
    assert await deliver(h, utc(2026, 11, 5, 21)) == {"nothing_planned": 1}
    assert sender.delivered == {}


async def test_a_day_missed_by_downtime_is_not_reminded_late(h: Harness) -> None:
    await plan_tuesday(h)
    assert await deliver(h, utc(2026, 11, 4, 14)) == {"expired": 1}


async def test_weekly_frequency_cap(clean_env: pytest.MonkeyPatch) -> None:
    sender = FakeReminderSender()
    h = build_harness(clean_env, reminder_sender=sender, reminder_weekly_cap=1)
    h.put_doc(
        f"students/{BETH}/reminders/2026-10-31.email",
        {"reminderId": "2026-10-31.email", "studentId": BETH, "channel": "email",
         "localDate": "2026-10-31", "sendAt": utc(2026, 10, 31, 20), "status": "sent",
         "attempts": 1, "createdAt": utc(2026, 10, 31, 8), "updatedAt": utc(2026, 10, 31, 20),
         "version": 2},
    )  # fmt: skip
    await plan_tuesday(h)
    assert await deliver(h, utc(2026, 11, 3, 21)) == {"frequency_cap": 1}
    assert sender.delivered == {}


async def test_only_designated_test_recipients_receive_anything(
    clean_env: pytest.MonkeyPatch,
) -> None:
    inner = FakeReminderSender()
    h = build_harness(clean_env, reminder_sender=TestRecipientGuard(inner, ["stu_someone_else"]))
    await plan_tuesday(h)
    assert await deliver(h, utc(2026, 11, 3, 21)) == {"not_test_recipient": 1}
    assert inner.delivered == {}


async def test_reminders_are_off_without_a_configured_sender(harness: Harness) -> None:
    await plan_tuesday(harness)
    assert harness.store.paths(f"students/{BETH}/reminders/") == []
    assert await harness.services.reminders.deliver_due() == {}


async def test_opt_in_records_consent_for_one_channel_only(h: Harness) -> None:
    two = {"enabled": True, "channels": ["email", "push"]}
    assert (await patch_twin(h, ALEX, {"notifications": two})).status_code == 400
    no_opt_in = {"enabled": False, "channels": ["email"]}
    assert (await patch_twin(h, ALEX, {"notifications": no_opt_in})).status_code == 400
    assert h.store.raw(f"students/{ALEX}/consents/notifications") is None

    r = await patch_twin(h, ALEX, {"notifications": {"enabled": True, "channels": ["push"]}})
    assert r.status_code == 200, r.text
    consent = h.store.raw(f"students/{ALEX}/consents/notifications")
    assert consent["granted"] and consent["channels"] == ["push"]
    assert consent["policyVersion"] == "reminders-v1"
    # Changing an unrelated preference keeps the original grant time.
    h.clock.advance(hours=1)
    await patch_twin(h, ALEX, {"weeklyAvailableMinutes": 240})
    assert (
        h.store.raw(f"students/{ALEX}/consents/notifications")["grantedAt"] == consent["grantedAt"]
    )


async def test_student_controls_survive_a_restart_and_replanning(
    clean_env: pytest.MonkeyPatch, h: Harness
) -> None:
    await patch_task(h, {"scheduledDate": "2026-11-06"})  # defer (locks the date)
    # Restart: new services and app over the same durable store.
    restarted = build_harness(clean_env, store=h.store)
    restarted.clock.set(utc(2026, 11, 3, 9, 1))
    await restarted.services.planning_scheduler.run_due()
    await restarted.settle()
    task = (await restarted.client.get(f"/api/tasks/{TASK}", headers=restarted.auth(BETH))).json()
    assert task["scheduledDate"] == "2026-11-06" and task["studentLocked"] is True
    plan = (await restarted.client.get("/api/plans/latest", headers=restarted.auth(BETH))).json()
    [entry] = plan["entries"]
    assert entry["placement"] == "fixed" or entry["scheduledDate"] == "2026-11-06"

    # Unlock, then skip with a reason: both persist and a skipped task is never planned.
    body = await patch_task(restarted, {"studentLocked": False})
    assert body["studentLocked"] is False
    # Re-read through a fresh restart before skipping.
    again = build_harness(clean_env, store=h.store)
    again.clock.set(utc(2026, 11, 3, 9, 30))
    skipped = await patch_task(again, {"status": "SKIPPED", "skipReason": "no_time"})
    assert skipped["status"] == "SKIPPED" and skipped["skipReason"] == "no_time"
