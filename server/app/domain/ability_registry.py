"""The one lookup of platform abilities (Step 44).

Built from an explicit, typed list at import time, so a conflict stops startup. Nothing here
loads code by name, and package data can only refer to abilities already in the list.
"""

from __future__ import annotations

from collections.abc import Iterable, Iterator, Mapping, Sequence

from app.domain.skills.ability import AbilityDataRule, AbilityDefinition, QuestionShape
from app.domain.types.run import RunKind


class AbilityRegistryError(ValueError):
    pass


class AbilityRegistry:
    def __init__(self, definitions: Sequence[AbilityDefinition]) -> None:
        self._by_id: dict[str, AbilityDefinition] = {}
        self._by_route: dict[tuple[RunKind, QuestionShape], AbilityDefinition] = {}
        self._rules: dict[QuestionShape, AbilityDefinition] = {}
        for d in definitions:
            if d.ability_id in self._by_id:
                raise AbilityRegistryError(f"duplicate ability {d.ability_id}")
            self._by_id[d.ability_id] = d
            for route in ((k, s) for k in d.run_kinds for s in d.question_shapes):
                other = self._by_route.setdefault(route, d)
                if other is not d:
                    raise AbilityRegistryError(
                        f"{d.ability_id} and {other.ability_id} both handle "
                        f"{route[0].value} on {route[1].value} questions"
                    )
            if d.data_rule is not None:
                owner = self._rules.setdefault(d.data_rule.shape, d)
                if owner is not d:
                    raise AbilityRegistryError(
                        f"{d.ability_id} and {owner.ability_id} both require "
                        f"{d.data_rule.shape.value} questions"
                    )

    def __iter__(self) -> Iterator[AbilityDefinition]:
        return iter(self._by_id.values())

    def __contains__(self, ability_id: object) -> bool:
        return ability_id in self._by_id

    def get(self, ability_id: str) -> AbilityDefinition | None:
        return self._by_id.get(ability_id)

    def for_run(self, kind: RunKind, shape: QuestionShape) -> AbilityDefinition | None:
        return self._by_route.get((kind, shape))

    def owner_of_shape(self, shape: QuestionShape) -> AbilityDefinition | None:
        return self._rules.get(shape)

    def data_rules(self) -> list[tuple[str, AbilityDataRule]]:
        return [(d.ability_id, d.data_rule) for d in self._by_id.values() if d.data_rule]

    def versions_for(self, ability_ids: Iterable[str]) -> Mapping[str, str]:
        """What a new Session pins for the abilities its course selected."""
        return {a: self._by_id[a].version for a in ability_ids if a in self._by_id}
