from __future__ import annotations

from typing import Annotated, Self

from pydantic import Field, StringConstraints, field_validator, model_validator

from app.domain.types.student import MasteryLevel, NotificationChannel, PredictionStatus
from app.schemas.common import ApiModel, CourseId, IanaTimezone, LocalTime, RequestModel, SkillId

DisplayName = Annotated[str, StringConstraints(min_length=1, max_length=60)]
ShortText = Annotated[str, StringConstraints(min_length=1, max_length=120)]
Grade = Annotated[int, Field(ge=9, le=12)]
SatScore = Annotated[int, Field(ge=400, le=1600, multiple_of=10)]
ApScore = Annotated[int, Field(ge=1, le=5)]
WeeklyMinutes = Annotated[int, Field(ge=0, le=3000)]


def _unique[T](values: list[T]) -> list[T]:
    if len(set(values)) != len(values):
        raise ValueError("values must be unique")
    return values


class Profile(ApiModel):
    display_name: DisplayName
    grade: Grade
    school: ShortText | None = None
    target_major: ShortText | None = None
    target_schools: list[ShortText] = Field(default_factory=list, max_length=30)


class Goals(ApiModel):
    sat_target: SatScore | None = None
    ap_targets: dict[CourseId, ApScore] = Field(default_factory=dict, max_length=20)


class QuietHours(ApiModel):
    start: LocalTime
    end: LocalTime


class NotificationPreferences(ApiModel):
    enabled: bool = False
    channels: list[NotificationChannel] = Field(default_factory=list, max_length=2)
    quiet_hours: QuietHours | None = None

    _unique_channels = field_validator("channels")(_unique)

    @model_validator(mode="after")
    def _channels_require_opt_in(self) -> Self:
        if self.channels and not self.enabled:
            raise ValueError("channels require notifications.enabled=true (opt-in)")
        return self


class Preferences(ApiModel):
    timezone: IanaTimezone
    weekly_available_minutes: WeeklyMinutes
    selected_courses: list[CourseId] = Field(default_factory=list, max_length=12)
    notifications: NotificationPreferences = Field(default_factory=NotificationPreferences)

    _unique_courses = field_validator("selected_courses")(_unique)


class Entitlements(ApiModel):
    """Response only. There is deliberately no request model that accepts entitlements."""

    ap_courses: list[CourseId]
    dsat: bool
    admissions: bool


class MasteryEntry(ApiModel):
    level: MasteryLevel
    independent_evidence_count: int = Field(ge=0)


class PredictionEntry(ApiModel):
    status: PredictionStatus
    reason: Annotated[str, StringConstraints(max_length=64)]


class TwinSummary(ApiModel):
    """`GET /api/twin` — bounded summary; full history is paginated elsewhere."""

    student_id: str
    version: int = Field(ge=1)
    profile: Profile
    goals: Goals
    preferences: Preferences
    mastery_summary: dict[SkillId, MasteryEntry]
    prediction_summary: dict[CourseId, PredictionEntry]
    latest_event_sequence: int = Field(ge=0)


# ---- PATCH /api/twin ---------------------------------------------------------------------
# Every level forbids unknown fields, so studentId, entitlements, mastery, predictions,
# version, email and the legacy `subscriptions` field are all rejected by construction.


class ProfilePatch(RequestModel):
    display_name: DisplayName | None = None
    grade: Grade | None = None
    school: ShortText | None = None
    target_major: ShortText | None = None
    target_schools: list[ShortText] | None = Field(default=None, max_length=30)


class GoalsPatch(RequestModel):
    sat_target: SatScore | None = None
    ap_targets: dict[CourseId, ApScore] | None = Field(default=None, max_length=20)


class PreferencesPatch(RequestModel):
    timezone: IanaTimezone | None = None
    weekly_available_minutes: WeeklyMinutes | None = None
    selected_courses: list[CourseId] | None = Field(default=None, max_length=12)
    notifications: NotificationPreferences | None = None

    @field_validator("selected_courses")
    @classmethod
    def _unique_selected(cls, value: list[str] | None) -> list[str] | None:
        return None if value is None else _unique(value)


class TwinPatch(RequestModel):
    profile: ProfilePatch | None = None
    goals: GoalsPatch | None = None
    preferences: PreferencesPatch | None = None

    @model_validator(mode="after")
    def _not_empty(self) -> Self:
        if not self.model_fields_set:
            raise ValueError("patch must change at least one field")
        return self
