"""Seed a development organization's question bank from a local bank (Step 45.6).

Usage (from server/, with emulators running and the platform seeded — `make seed`):

    uv run python -m scripts.seed_bank [--bank content/private/bank] [--org-member author_hsos]
                                       [--verified-as-draft] [--limit N]

Development only: refuses to run unless both emulator hosts are set and the project id is
`demo-*`. The default input, `server/content/private/bank`, is git-ignored local test
content; nothing it contains is ever committed or published.

Every record goes through `BankService.create` — the same call the Step 39 import uses — so
the bank's own rules apply (shape checks, answer-key sources, organization scope). Items
arrive as `extracted` (agent/import output that an author must still confirm); with
`--verified-as-draft`, records transcribed from page images (`vision-verified`) arrive as
`draft` instead. Re-running is safe: each record's command key is derived from its bank id,
so an unchanged record replays the item created before, and a record whose content changed
is reported and skipped (its key was already used with different content).

Answer keys keep their origin: an official key becomes `source-key`, a third-party key
`compiled-key`, and a key that was worked out (not printed in the source) becomes
`agent-suggested`, which the content reviewer must confirm before approval.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import sys
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from app.domain.bank_service import BankService, CreateItemInput
from app.domain.commands import CommandKey
from app.domain.errors import DomainError, ErrorCode
from app.domain.types.actor import ActorRole, PlatformActor
from app.domain.types.bank import (
    CHOICE_KEYS,
    MAX_CHOICE_CHARS,
    MAX_PASSAGE_CHARS,
    MAX_STEM_CHARS,
    AnswerSource,
    BankItemState,
    FigureMode,
    ItemContent,
    ItemType,
    Provenance,
    ProvenanceKind,
)

DEFAULT_BANK = Path(__file__).resolve().parents[1] / "content" / "private" / "bank"
ITEM_SCOPE = "seed:bank-jsonl:item"
PASSAGE_SCOPE = "seed:bank-jsonl:passage"
ANSWER_SOURCES = {
    "official-key": AnswerSource.SOURCE_KEY,
    "compiled-key": AnswerSource.COMPILED_KEY,
    "solved": AnswerSource.AGENT_SUGGESTED,
}
MAX_TEXT = 200  # provenance reference/region and answers
MAX_FLAGS = 50


@dataclass(slots=True)
class SeedReport:
    passages_created: int = 0
    passages_replayed: int = 0
    items_created: int = 0
    items_replayed: int = 0
    skipped: list[tuple[str, str]] = field(default_factory=list)  # (bank id, reason)

    def summary(self) -> str:
        lines = [
            f"passages: {self.passages_created} created, {self.passages_replayed} already present",
            f"items:    {self.items_created} created, {self.items_replayed} already present, "
            f"{len(self.skipped)} skipped",
        ]
        lines += [f"  skipped {bid}: {why}" for bid, why in self.skipped[:20]]
        if len(self.skipped) > 20:
            lines.append(f"  … and {len(self.skipped) - 20} more")
        return "\n".join(lines)


def _digest(data: Any) -> str:
    return hashlib.sha256(json.dumps(data, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def _clip(text: str | None, limit: int) -> str | None:
    if text is None:
        return None
    return text if len(text) <= limit else text[: limit - 1] + "…"


def passage_input(record: Mapping[str, Any]) -> tuple[str, str, Provenance, list[str]]:
    """(title, text, provenance, flags) for a local passage record."""
    flags = [str(f) for f in record.get("flags", [])]
    text = str(record.get("text") or "")
    if len(text) > MAX_PASSAGE_CHARS:
        text, flags = text[:MAX_PASSAGE_CHARS], [*flags, "text-truncated"]
    title = _clip(str(record.get("title") or record["passageId"]), MAX_TEXT) or record["passageId"]
    provenance = Provenance(
        kind=ProvenanceKind.IMPORTED,
        page=record.get("page"),
        region=_clip(str(record["passageId"]), MAX_TEXT),
        reference=_clip(str(record.get("sourceId", "")), MAX_TEXT) or None,
    )
    return title, text, provenance, flags


def item_input(
    record: Mapping[str, Any], passage_ids: Mapping[str, str], *, verified_as_draft: bool
) -> tuple[CreateItemInput, BankItemState]:
    """Map one local bank record onto a bank item. Problems that the bank would reject are
    repaired conservatively and recorded as flags rather than dropped silently."""
    flags = [str(f) for f in record.get("flags", [])]
    status = record.get("status")
    if status:
        flags.append(f"seed-status:{status}")
    item_type = ItemType.SPR if record.get("type") == "spr" else ItemType.MC

    stem = str(record.get("stem") or "")
    if len(stem) > MAX_STEM_CHARS:
        stem, flags = stem[:MAX_STEM_CHARS], [*flags, "stem-truncated"]

    choices: dict[str, str] | None = None
    raw_choices = record.get("choices")
    if item_type is ItemType.MC and isinstance(raw_choices, Mapping):
        choices = {}
        for k in CHOICE_KEYS:
            if k in raw_choices:
                value = str(raw_choices[k] or "")
                if len(value) > MAX_CHOICE_CHARS:
                    value, flags = value[:MAX_CHOICE_CHARS], [*flags, "choice-truncated"]
                choices[k] = value

    answer = record.get("answer")
    source = ANSWER_SOURCES.get(str(record.get("answerSource")))
    if answer is not None:
        answer = str(answer).strip()
        if not answer or source is None:
            answer, source = None, None
        elif item_type is ItemType.MC and answer not in CHOICE_KEYS:
            flags.append(f"seed-answer-not-a-choice:{_clip(answer, 60)}")
            answer, source = None, None
        elif len(answer) > MAX_TEXT:
            flags.append("seed-answer-too-long")
            answer, source = None, None
    compiled = record.get("compiledKey")
    if compiled is not None and str(compiled) != str(answer):
        flags.append(f"compiled-key:{_clip(str(compiled), 60)}")

    local_passage = record.get("passageId")
    passage_id = passage_ids.get(local_passage) if local_passage else None
    if local_passage and passage_id is None:
        flags.append("passage-missing")

    content = ItemContent(
        section=_clip(record.get("section"), MAX_TEXT),
        stem=stem,
        item_type=item_type,
        choices=choices,
        answer=answer,
        answer_source=source if answer is not None else None,
        figure=FigureMode.DESCRIBED if "figure-described" in flags else FigureMode.NONE,
        passage_id=passage_id,
        flags=tuple(dict.fromkeys(f[:120] for f in flags))[:MAX_FLAGS],
    )
    provenance = Provenance(
        kind=ProvenanceKind.IMPORTED,
        page=record.get("page") if isinstance(record.get("page"), int) else None,
        region=_clip(str(record["id"]), MAX_TEXT),
        reference=_clip(str(record.get("sourceFile") or record.get("sourceId") or ""), MAX_TEXT)
        or None,
    )
    tags = [t for t in (record.get("sourceId"), record.get("section"), record.get("format")) if t]
    state = (
        BankItemState.DRAFT
        if verified_as_draft and "vision-verified" in flags
        else BankItemState.EXTRACTED
    )
    return (
        CreateItemInput(
            content=content, tags=tuple(str(t)[:60] for t in tags), provenance=provenance
        ),
        state,
    )


async def seed_bank(
    bank: BankService,
    actor: PlatformActor,
    questions: Iterable[Mapping[str, Any]],
    passages: Iterable[Mapping[str, Any]],
    *,
    verified_as_draft: bool = False,
) -> SeedReport:
    report = SeedReport()
    questions = list(questions)
    wanted = {q.get("passageId") for q in questions if q.get("passageId")}
    passage_ids: dict[str, str] = {}
    for record in passages:
        local = record.get("passageId")
        if local not in wanted:
            continue
        title, text, provenance, flags = passage_input(record)
        if not text.strip():
            continue
        cmd = CommandKey(scope=PASSAGE_SCOPE, key=str(local), request_digest=_digest(record))
        try:
            made = await bank.create_passage(actor, title, text, provenance, cmd, flags=flags)
        except DomainError as exc:
            report.skipped.append((str(local), f"passage: {exc.code.value}: {exc.message}"))
            continue
        passage_ids[str(local)] = made.value.passage_id
        if made.replayed:
            report.passages_replayed += 1
        else:
            report.passages_created += 1

    for record in questions:
        bid = str(record["id"])
        inp, state = item_input(record, passage_ids, verified_as_draft=verified_as_draft)
        cmd = CommandKey(scope=ITEM_SCOPE, key=bid, request_digest=_digest([record, state.value]))
        try:
            out = await bank.create(actor, inp, cmd, initial_state=state)
        except DomainError as exc:
            reason = (
                "content changed since an earlier seed (key already used)"
                if exc.code is ErrorCode.IDEMPOTENCY_CONFLICT
                else f"{exc.code.value}: {exc.message}"
            )
            report.skipped.append((bid, reason))
            continue
        if out.replayed:
            report.items_replayed += 1
        else:
            report.items_created += 1
    return report


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    with path.open(encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


async def _run(args: argparse.Namespace) -> int:
    from app.adapters.firebase import resolve_target
    from app.bootstrap import build_services
    from app.config import ConfigError, Settings, StorageProvider

    settings = Settings()
    if settings.storage_provider is StorageProvider.MEMORY:
        raise ConfigError("seed_bank writes to the Firestore emulator; unset HSOS_STORAGE_PROVIDER")
    target = resolve_target(settings)
    if not target.uses_emulators or not target.project_id.startswith("demo-"):
        raise ConfigError(
            "seed_bank is development-only: it needs FIRESTORE_EMULATOR_HOST, "
            "FIREBASE_AUTH_EMULATOR_HOST and a demo-* project id"
        )
    services = build_services(settings)
    member = await services.platform_members.resolve(args.org_member)
    if member is None or member.org_id is None:
        raise ConfigError(
            f"{args.org_member} is not an author of an organization (run `make seed`)"
        )
    actor = PlatformActor.for_member(member.uid, ActorRole(member.role), member.org_id)
    bank_dir = Path(args.bank)
    questions = read_jsonl(bank_dir / "questions.jsonl")
    if args.limit:
        questions = questions[: args.limit]
    passages = read_jsonl(bank_dir / "passages.jsonl")
    print(f"seeding {len(questions)} questions into {member.org_id} as {member.uid} …")
    report = await seed_bank(
        services.bank, actor, questions, passages, verified_as_draft=args.verified_as_draft
    )
    print(report.summary())
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--bank", default=str(DEFAULT_BANK), help="folder with questions.jsonl")
    parser.add_argument("--org-member", default="author_hsos", help="uid of an org author")
    parser.add_argument("--verified-as-draft", action="store_true")
    parser.add_argument("--limit", type=int, default=0, help="seed only the first N questions")
    return asyncio.run(_run(parser.parse_args(argv)))


if __name__ == "__main__":
    sys.exit(main())
