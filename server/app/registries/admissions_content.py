"""Load the admissions interview prompt set (Step 35). Platform content, versioned and
reviewed like course content; prompts ask the student about themselves and never ask the
model to write anything for them."""

from __future__ import annotations

from pathlib import Path
from typing import Annotated, Literal

from pydantic import Field, StringConstraints

from app.domain.admissions_service import PromptSet
from app.domain.types.admissions import FACT_CATEGORIES, InterviewPrompt
from app.registries.content import DEFAULT_CONTENT_ROOT, load_json
from app.schemas.common import ApiModel
from app.schemas.content import ContentSource, Review

DEFAULT_PROMPTS = DEFAULT_CONTENT_ROOT / "admissions" / "interview-v1.json"


class PromptFixture(ApiModel):
    prompt_id: Annotated[str, StringConstraints(pattern=r"^[a-z][a-z0-9_]{1,40}$")]
    category: Literal[FACT_CATEGORIES]  # type: ignore[valid-type]
    text: Annotated[str, StringConstraints(min_length=10, max_length=400)]


class PromptSetFile(ApiModel):
    prompt_set_version: Annotated[str, StringConstraints(pattern=r"^interview-v\d+$")]
    source: ContentSource
    review: Review
    prompts: list[PromptFixture] = Field(min_length=1, max_length=20)


def load_prompt_set(path: Path = DEFAULT_PROMPTS) -> PromptSet:
    raw = PromptSetFile.model_validate(load_json(path))
    ids = [p.prompt_id for p in raw.prompts]
    if len(ids) != len(set(ids)):
        raise ValueError(f"{path}: duplicate promptId")
    return PromptSet(
        version=raw.prompt_set_version,
        prompts=tuple(
            InterviewPrompt(prompt_id=p.prompt_id, text=p.text, category=p.category)
            for p in raw.prompts
        ),
    )
