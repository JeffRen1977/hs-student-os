"""Step 8: Firebase ID token verification and actor construction."""

from __future__ import annotations

from datetime import timedelta

import pytest

from app.adapters.auth import FirebaseTokenVerifier, check_claims
from app.domain.errors import DomainError, ErrorCode
from app.domain.types.actor import ActorContext, ActorRole, Permission
from tests.support import PROJECT, START, FakeClock, emulator_token, harness_settings


@pytest.fixture
def verifier(clean_env: pytest.MonkeyPatch) -> FirebaseTokenVerifier:
    return FirebaseTokenVerifier(harness_settings(clean_env), FakeClock())


async def test_valid_emulator_token_yields_uid(verifier: FirebaseTokenVerifier) -> None:
    identity = await verifier.verify(emulator_token("stu_alex"))
    assert identity.uid == "stu_alex"


@pytest.mark.parametrize(
    "claims",
    [
        # The SDK skips lifetime checks in emulator mode; ours must still reject these.
        {"exp": int((START - timedelta(minutes=5)).timestamp())},
        {"iat": int((START + timedelta(hours=1)).timestamp())},
        {"aud": "some-other-project"},
        {"iss": "https://securetoken.google.com/some-other-project"},
        {"sub": ""},
    ],
    ids=["expired", "future-iat", "wrong-audience", "wrong-issuer", "no-subject"],
)
async def test_bad_claims_are_unauthenticated(
    verifier: FirebaseTokenVerifier, claims: dict[str, object]
) -> None:
    with pytest.raises(DomainError) as err:
        await verifier.verify(emulator_token("stu_alex", **claims))
    assert err.value.code is ErrorCode.UNAUTHENTICATED


@pytest.mark.parametrize("token", ["", "not-a-jwt", "a.b.c", "x" * 9000])
async def test_malformed_tokens_are_unauthenticated(
    verifier: FirebaseTokenVerifier, token: str
) -> None:
    with pytest.raises(DomainError) as err:
        await verifier.verify(token)
    assert err.value.code is ErrorCode.UNAUTHENTICATED


async def test_without_emulator_unsigned_tokens_are_rejected(
    clean_env: pytest.MonkeyPatch,
) -> None:
    """Outside emulator mode (always the case when deployed) an emulator token is refused."""
    settings = harness_settings(clean_env)
    clean_env.delenv("FIREBASE_AUTH_EMULATOR_HOST")
    verifier = FirebaseTokenVerifier(settings, FakeClock())
    with pytest.raises(DomainError) as err:
        await verifier.verify(emulator_token("stu_alex"))
    assert err.value.code is ErrorCode.UNAUTHENTICATED


def test_check_claims_allows_small_clock_skew() -> None:
    ts = int(START.timestamp())
    claims = {
        "exp": ts - 10,  # within the 30s skew allowance
        "iat": ts + 10,
        "aud": PROJECT,
        "iss": f"https://securetoken.google.com/{PROJECT}",
        "sub": "stu_alex",
    }
    assert check_claims(claims, project_id=PROJECT, now=START) == "stu_alex"


def test_service_actor_is_distinct_from_students() -> None:
    actor = ActorContext.for_service("run-worker", "stu_alex")
    assert actor.role is ActorRole.SERVICE
    assert actor.actor_id == "svc:run-worker"
    assert actor.can(Permission.RUN_EXECUTE)
    assert not actor.can(Permission.TWIN_WRITE)
    with pytest.raises(ValueError, match="svc:"):
        ActorContext(actor_id="run-worker", student_id="stu_alex", role=ActorRole.SERVICE)
    with pytest.raises(ValueError, match="service prefix"):
        ActorContext.for_student("svc:stu_alex")
    student = ActorContext.for_student("stu_alex")
    assert not student.can(Permission.RUN_EXECUTE)
    with pytest.raises(DomainError):
        student.require(Permission.RUN_EXECUTE)
