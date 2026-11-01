"""Static, rules-based model routing (Step 16.2). No decision model.

The route is the higher of the pack's manifest tier and the skill's minimum tier, so a pack
can raise quality but a cheap pack tier can never pull grading below its floor.
"""

from __future__ import annotations

from collections.abc import Mapping

from app.domain.ports.content import TIER_ORDER, ModelTier

# Grading must not be downgraded to fit a budget (CLAUDE.md, BACKEND.md §7).
SKILL_MINIMUM_TIERS: Mapping[str, ModelTier] = {
    "socratic-guidance": ModelTier.FAST,
    "rubric-assessment": ModelTier.STRONG,
}


class ModelRouter:
    def __init__(
        self,
        models: Mapping[ModelTier, str],
        minimum_tiers: Mapping[str, ModelTier] = SKILL_MINIMUM_TIERS,
    ) -> None:
        missing = [t for t in TIER_ORDER if not models.get(t)]
        if missing:
            raise ValueError(f"no model configured for tiers: {missing}")
        self._models = dict(models)
        self._minimum = dict(minimum_tiers)

    def route(self, purpose: str, pack_tier: ModelTier) -> tuple[ModelTier, str]:
        if purpose not in self._minimum:
            raise ValueError(f"unknown skill for routing: {purpose}")
        tier = max(pack_tier, self._minimum[purpose], key=TIER_ORDER.index)
        return tier, self._models[tier]
