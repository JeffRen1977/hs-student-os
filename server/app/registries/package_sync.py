"""Keep the runtime registry in step with the package store (Step 26.4).

Servable versions (active, superseded, retired) are revalidated and installed into the
`ContentRegistry` as one snapshot. The instance that activates or retires a version
refreshes at once; other instances (API replicas, the worker) refresh when their copy is
older than `max_age_seconds`, and immediately when a Run is pinned to a version they have
not loaded yet.
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from collections.abc import Callable, Sequence

from app.domain.ports.packages import PackageTx, PackageUnitOfWork
from app.domain.types.package import SERVABLE_STATUSES, PackageStatus, PackageVersion
from app.registries.content import AuthoredVersion, ContentRegistry, Pack
from app.registries.package_validator import validate_package

logger = logging.getLogger(__name__)


def authored_versions(
    versions: Sequence[PackageVersion], cache: dict[str, Pack] | None = None
) -> list[AuthoredVersion]:
    """Revalidate each servable version (cached by content hash: versions are immutable
    once submitted) and mark which one is its course's current version."""
    cache = {} if cache is None else cache
    out: list[AuthoredVersion] = []
    for v in versions:
        if v.status not in SERVABLE_STATUSES:
            continue
        pack = cache.get(v.content_hash)
        if pack is None:
            checked = validate_package(json.loads(v.package_json))
            if checked.pack is None or checked.content_hash != v.content_hash:
                # Never serve content that differs from what the reviewer approved.
                logger.error("package_not_servable", extra={"package": v.key})
                continue
            pack = cache[v.content_hash] = checked.pack
        out.append(
            AuthoredVersion(
                pack=pack,
                current=v.status in (PackageStatus.ACTIVE, PackageStatus.RETIRED),
                retired=v.status is PackageStatus.RETIRED,
            )
        )
    return out


class PackageContentSync:
    def __init__(
        self,
        registry: ContentRegistry,
        uow: PackageUnitOfWork,
        *,
        max_age_seconds: float = 30.0,
        monotonic: Callable[[], float] = time.monotonic,
    ) -> None:
        self._registry = registry
        self._uow = uow
        self._max_age = max_age_seconds
        self._monotonic = monotonic
        self._loaded_at: float | None = None
        self._lock = asyncio.Lock()
        self._cache: dict[str, Pack] = {}

    async def refresh(self) -> None:
        async with self._lock:

            async def read(tx: PackageTx) -> Sequence[PackageVersion]:
                return await tx.versions.list_by_status(sorted(SERVABLE_STATUSES))

            versions = await self._uow.transaction(read)
            self._registry.install_authored(authored_versions(versions, self._cache))
            self._loaded_at = self._monotonic()

    async def ensure_fresh(self) -> None:
        loaded = self._loaded_at
        if loaded is None or self._monotonic() - loaded >= self._max_age:
            await self.refresh()

    async def ensure_version(self, course_id: str, version: str) -> None:
        """A Run pinned to a version this instance has not loaded yet: reload once."""
        if self._registry.pack_version(course_id, version) is None:
            await self.refresh()
