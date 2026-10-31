"""Firebase Admin SDK + Firestore client initialization with explicit emulator detection.

Emulator use is allowed only in local/test environments and only for `demo-*` projects,
which the Firebase emulators guarantee never touch real cloud resources.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import firebase_admin
from google.cloud import firestore

from app.config import ConfigError, Settings

FIREBASE_APP_NAME = "hs-student-os"


@dataclass(frozen=True, slots=True)
class FirebaseTarget:
    project_id: str
    firestore_emulator_host: str | None
    auth_emulator_host: str | None

    @property
    def uses_emulators(self) -> bool:
        return bool(self.firestore_emulator_host or self.auth_emulator_host)


def resolve_target(settings: Settings) -> FirebaseTarget:
    target = FirebaseTarget(
        project_id=settings.gcp_project_id,
        firestore_emulator_host=settings.firestore_emulator_host,
        auth_emulator_host=settings.firebase_auth_emulator_host,
    )
    if target.uses_emulators:
        if settings.is_deployed:  # Settings already rejects this; defense in depth.
            raise ConfigError("emulator hosts are not allowed in deployed environments")
        if not (target.firestore_emulator_host and target.auth_emulator_host):
            raise ConfigError(
                "set both FIRESTORE_EMULATOR_HOST and FIREBASE_AUTH_EMULATOR_HOST, or neither"
            )
        if not target.project_id.startswith("demo-"):
            raise ConfigError("emulator mode requires a demo-* project id")
    return target


def init_firebase_app(settings: Settings) -> Any:
    """Return the named Firebase Admin app, initializing it once."""
    target = resolve_target(settings)
    try:
        return firebase_admin.get_app(FIREBASE_APP_NAME)
    except ValueError:
        pass
    # In emulator mode the Admin SDK reads FIREBASE_AUTH_EMULATOR_HOST from the process
    # environment and needs no real credentials. Otherwise it uses Application Default
    # Credentials (the Cloud Run service account).
    return firebase_admin.initialize_app(
        options={"projectId": target.project_id}, name=FIREBASE_APP_NAME
    )


def create_async_firestore_client(settings: Settings) -> Any:
    target = resolve_target(settings)
    return firestore.AsyncClient(project=target.project_id)


def create_sync_firestore_client(settings: Settings) -> Any:
    target = resolve_target(settings)
    return firestore.Client(project=target.project_id)
