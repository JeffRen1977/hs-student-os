"""Translate synthetic fixtures into Firestore documents (BACKEND.md §3 layout).

Pure function so it can be unit-tested without an emulator.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime
from typing import Any

from app.registries.fixtures import SeedStudent


def student_paths(student_id: str) -> dict[str, str]:
    base = f"students/{student_id}"
    return {
        "student": base,
        "access": f"{base}/access/current",
        "eventState": f"{base}/eventState/current",
        "enrollments": f"{base}/enrollments",
        "tasks": f"{base}/tasks",
    }


def build_seed_documents(
    seeds: Sequence[SeedStudent], *, now: datetime
) -> dict[str, dict[str, Any]]:
    """Return {documentPath: data}. Paths are always scoped under students/{studentId}."""
    docs: dict[str, dict[str, Any]] = {}
    for seed in seeds:
        fx = seed.student
        sid = fx.student_id
        if seed.entitlements.student_id != sid:
            raise ValueError("entitlement fixture belongs to a different student")
        paths = student_paths(sid)
        docs[paths["student"]] = {
            "studentId": sid,
            "synthetic": True,
            "contactEmail": fx.email,
            "version": 1,
            "profile": fx.profile.model_dump(mode="json", by_alias=True),
            "goals": fx.goals.model_dump(mode="json", by_alias=True),
            "preferences": fx.preferences.model_dump(mode="json", by_alias=True),
            "predictionSummary": {
                cid: p.model_dump(mode="json", by_alias=True)
                for cid, p in fx.prediction_summary.items()
            },
            "createdAt": now,
            "updatedAt": now,
        }
        docs[paths["access"]] = {
            **seed.entitlements.entitlements.model_dump(mode="json", by_alias=True),
            "updatedAt": now,
            "updatedBy": "seed-script",
        }
        docs[paths["eventState"]] = {"nextSequence": 1}
        for enrollment in fx.enrollments:
            docs[f"{paths['enrollments']}/{enrollment.course_id}"] = {
                "courseId": enrollment.course_id,
                "status": enrollment.status.value,
                "enrolledAt": enrollment.enrolled_at,
                "unenrolledAt": None,
            }
        for task in seed.tasks:
            if task.student_id != sid:
                raise ValueError("task fixture belongs to a different student")
            docs[f"{paths['tasks']}/{task.task_id}"] = {
                **task.model_dump(mode="json", by_alias=True),
                "openSessionId": None,
                "updatedAt": now,
            }
    return docs
