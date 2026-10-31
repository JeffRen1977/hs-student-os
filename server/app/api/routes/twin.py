"""Twin and entitlements (Step 10)."""

from __future__ import annotations

from fastapi import APIRouter
from fastapi.responses import JSONResponse

from app.api import presenters
from app.api.dependencies.auth import Actor, ServicesDep
from app.api.dependencies.commands import IfMatchHeader, expected_version
from app.api.responses import respond
from app.domain.twin_service import TwinChanges
from app.domain.types.student import NotificationChannel, NotificationPreferences, QuietHours
from app.schemas import student as st

router = APIRouter(prefix="/api", tags=["twin"])


def _domain_value(name: str, value: object) -> object:
    if isinstance(value, st.NotificationPreferences):
        return NotificationPreferences(
            enabled=value.enabled,
            channels=tuple(NotificationChannel(c) for c in value.channels),
            quiet_hours=(
                QuietHours(start=value.quiet_hours.start, end=value.quiet_hours.end)
                if value.quiet_hours
                else None
            ),
        )
    if isinstance(value, list):
        return tuple(value)
    if isinstance(value, dict):
        return dict(value)
    return value


def to_changes(patch: st.TwinPatch) -> TwinChanges:
    """Only fields the client actually sent become changes (explicit null included)."""
    sections: dict[str, dict[str, object]] = {"profile": {}, "goals": {}, "preferences": {}}
    for section in ("profile", "goals", "preferences"):
        sub = getattr(patch, section)
        if section in patch.model_fields_set and sub is not None:
            for name in sub.model_fields_set:
                sections[section][name] = _domain_value(name, getattr(sub, name))
    return TwinChanges(**sections)


@router.get("/twin", response_model=st.TwinSummary)
async def get_twin(actor: Actor, services: ServicesDep) -> JSONResponse:
    student = await services.twin.get_twin(actor)
    return respond(presenters.twin(student), etag=student.version)


@router.patch("/twin", response_model=st.TwinSummary)
async def patch_twin(
    body: st.TwinPatch, actor: Actor, services: ServicesDep, if_match: IfMatchHeader = None
) -> JSONResponse:
    version = expected_version(if_match)
    student = await services.twin.patch_twin(actor, to_changes(body), expected_version=version)
    return respond(presenters.twin(student), etag=student.version)


@router.get("/me/entitlements", response_model=st.Entitlements)
async def get_entitlements(actor: Actor, services: ServicesDep) -> JSONResponse:
    # Read-only for students: there is deliberately no write route for entitlements.
    return respond(presenters.entitlements(await services.twin.get_entitlements(actor)))
