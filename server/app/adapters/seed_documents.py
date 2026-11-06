"""Translate synthetic fixtures into Firestore documents (BACKEND.md §3 layout).

Pure function so it can be unit-tested without an emulator.
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from datetime import datetime
from pathlib import Path
from typing import Any

from app.adapters.firestore.package_repository import (
    course_path,
    course_to_doc,
    member_path,
    version_path,
    version_to_doc,
)
from app.adapters.firestore.parent_repository import parent_path
from app.domain.planning_schedule import PlanningSchedulePolicy
from app.domain.types.package import (
    CourseState,
    PackageCourse,
    PackageStatus,
    PackageVersion,
    ReviewDecision,
    StatusChange,
)
from app.domain.types.reminder import CONSENT_POLICY_VERSION
from app.registries.content import DEFAULT_CONTENT_ROOT
from app.registries.fixtures import SeedStudent
from app.registries.package_validator import validate_package
from app.schemas.fixtures import PlatformFixture

SEED_REVIEWER = "seed:local-dev"
SEED_NOTE = (
    "Synthetic local seed, not a platform review. Real packages are approved through "
    "POST /api/review/packages/{courseId}/versions/{version}/approve."
)


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
        if any(e.status.value == "active" for e in fx.enrollments):
            # Enrolled students are on the daily planning schedule (Step 28).
            tz = fx.preferences.timezone
            docs[f"{paths['student']}/planState/current"] = {
                "studentId": sid,
                "activeRunId": None,
                "activeTrigger": None,
                "latestPlanId": None,
                "nextDueAt": PlanningSchedulePolicy().first_due(now, tz),
                "timezone": tz,
                "lastScheduledLocalDate": None,
                "version": 1,
            }
        notifications = fx.preferences.notifications
        if notifications.enabled and notifications.channels:
            # Synthetic opt-in: the fixture says this student opted in (Step 29).
            docs[f"{paths['student']}/consents/notifications"] = {
                "granted": True,
                "channels": [c.value for c in notifications.channels],
                "policyVersion": CONSENT_POLICY_VERSION,
                "grantedAt": now,
                "revokedAt": None,
                "updatedAt": now,
            }
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


def build_platform_documents(
    platform: PlatformFixture,
    *,
    now: datetime,
    authored_root: Path = DEFAULT_CONTENT_ROOT / "authored",
) -> dict[str, dict[str, Any]]:
    """Platform members, and the seed packages (installed as active, or waiting in the
    review queue as submitted).

    Each seed package must pass the same validator (and its evaluation set) as an upload;
    its audit trail says plainly that the approval is a local seed, not a review.
    """
    docs: dict[str, dict[str, Any]] = {}
    for m in platform.members:
        docs[member_path(m.uid)] = {"uid": m.uid, "role": m.role, "orgId": m.org_id}
    for parent in platform.parents:
        docs[parent_path(parent.uid)] = {
            "uid": parent.uid, "role": "parent", "displayName": parent.display_name,
        }  # fmt: skip
    for seed in platform.seed_packages:
        raw = json.loads((authored_root / seed.path / "package.json").read_text("utf-8"))
        checked = validate_package(raw)
        if not checked.report.valid or not checked.report.evaluation.auto_all_passed:
            raise ValueError(f"seed package {seed.path} does not validate: {checked.report}")
        assert checked.course_id and checked.version
        active = seed.status == "active"
        steps = [
            (None, PackageStatus.DRAFT, seed.uploaded_by, "uploaded"),
            (PackageStatus.DRAFT, PackageStatus.SUBMITTED, seed.uploaded_by, ""),
        ]
        if active:
            steps += [
                (PackageStatus.SUBMITTED, PackageStatus.APPROVED, SEED_REVIEWER, SEED_NOTE),
                (PackageStatus.APPROVED, PackageStatus.ACTIVE, SEED_REVIEWER, SEED_NOTE),
            ]
        history = tuple(
            StatusChange(from_status=a, to_status=b, actor_id=who, at=now, notes=note)
            for a, b, who, note in steps
        )
        version = PackageVersion(
            course_id=checked.course_id,
            version=checked.version,
            org_id=seed.org_id,
            status=PackageStatus.ACTIVE if active else PackageStatus.SUBMITTED,
            title=checked.title,
            package_json=checked.canonical_json,
            content_hash=checked.content_hash,
            report=checked.report,
            uploaded_by=seed.uploaded_by,
            created_at=now,
            updated_at=now,
            review=ReviewDecision(
                reviewer_id=SEED_REVIEWER,
                decision=PackageStatus.APPROVED,
                decided_at=now,
                notes=SEED_NOTE,
            )
            if active
            else None,
            history=history,
        )
        docs[version_path(version.course_id, version.version)] = version_to_doc(version)
        docs[course_path(version.course_id)] = course_to_doc(
            PackageCourse(
                course_id=version.course_id,
                org_id=seed.org_id,
                state=CourseState.ACTIVE if active else CourseState.DRAFTING,
                active_version=version.version if active else None,
                created_at=now,
                updated_at=now,
            )
        )
    return docs
