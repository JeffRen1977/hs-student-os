from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from enum import StrEnum


class MasteryLevel(StrEnum):
    INSUFFICIENT_EVIDENCE = "insufficient_evidence"
    EMERGING = "emerging"
    DEVELOPING = "developing"
    PROFICIENT = "proficient"


class PredictionStatus(StrEnum):
    # Only "unavailable" exists until an independent calibration pipeline ships (M5).
    UNAVAILABLE = "unavailable"


class NotificationChannel(StrEnum):
    EMAIL = "email"
    PUSH = "push"


@dataclass(frozen=True, slots=True, kw_only=True)
class Profile:
    display_name: str
    grade: int
    school: str | None = None
    target_major: str | None = None
    target_schools: Sequence[str] = ()


@dataclass(frozen=True, slots=True, kw_only=True)
class Goals:
    sat_target: int | None = None
    ap_targets: Mapping[str, int] = field(default_factory=dict)


@dataclass(frozen=True, slots=True, kw_only=True)
class QuietHours:
    start: str  # "HH:MM" local time
    end: str


@dataclass(frozen=True, slots=True, kw_only=True)
class NotificationPreferences:
    enabled: bool = False
    channels: Sequence[NotificationChannel] = ()
    quiet_hours: QuietHours | None = None


@dataclass(frozen=True, slots=True, kw_only=True)
class Preferences:
    timezone: str
    weekly_available_minutes: int
    selected_courses: Sequence[str] = ()
    notifications: NotificationPreferences = field(default_factory=NotificationPreferences)


@dataclass(frozen=True, slots=True, kw_only=True)
class Entitlements:
    """Backend-managed access grants. Never writable by the student."""

    ap_courses: Sequence[str] = ()
    dsat: bool = False
    admissions: bool = False


@dataclass(frozen=True, slots=True, kw_only=True)
class MasterySummary:
    level: MasteryLevel
    independent_evidence_count: int


@dataclass(frozen=True, slots=True, kw_only=True)
class PredictionSummary:
    status: PredictionStatus = PredictionStatus.UNAVAILABLE
    reason: str = "not_calibrated"


@dataclass(frozen=True, slots=True, kw_only=True)
class Student:
    student_id: str
    version: int
    profile: Profile
    goals: Goals
    preferences: Preferences
    mastery_summary: Mapping[str, MasterySummary] = field(default_factory=dict)
    prediction_summary: Mapping[str, PredictionSummary] = field(default_factory=dict)
    latest_event_sequence: int = 0
