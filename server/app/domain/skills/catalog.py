"""The platform ability catalog: the only place an ability is registered (Step 44)."""

from __future__ import annotations

from app.domain.ability_registry import AbilityRegistry
from app.domain.skills import choice_scoring, rubric_assessment, socratic_guidance
from app.domain.skills.ability import AbilityDefinition

PLATFORM_ABILITIES: tuple[AbilityDefinition, ...] = (
    socratic_guidance.DEFINITION,
    choice_scoring.DEFINITION,
    rubric_assessment.DEFINITION,
    rubric_assessment.SOURCE_ANALYSIS_DEFINITION,
)
PLATFORM_ABILITY_REGISTRY = AbilityRegistry(PLATFORM_ABILITIES)
