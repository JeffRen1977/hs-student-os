"""Deterministic splitting of pasted text and CSV into proposed bank questions (Step 39A).

Pure functions, no I/O and no model: the same input always gives the same proposals. The
author sees every proposal and its problems before anything is written (QUESTION_BANK.md
§7.1). The splitter is also used for clean PDF text layers in import jobs (Step 39B) and as
an authoring-assistant tool (Step 40).

Text layout understood:
- questions numbered `1.` or `1)` at the start of a line; numbers must increase;
- choices `A)`, `(A)`, `A.` or `A:` on their own lines or several on one line;
- a per-question key line (`Answer: B`, `Key - 7/2`) and an optional solution line
  (`Explanation:` / `Solution:` / `Rationale:` and the lines after it);
- an answer block anywhere after the questions (`Answers`/`Answer key` heading, or lines of
  pairs such as `1. B  2. D` or `1-B`);
- passages introduced by "Questions 3-5 refer to / are based on …", linked to that range only;
- underlined text as `[[…]]`, kept as is.
"""

from __future__ import annotations

import csv
import io
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field, replace

from app.domain.types.bank import CHOICE_KEYS

MAX_QUESTIONS = 300
MAX_TEXT_CHARS = 200_000

_QUESTION = re.compile(r"^\s*(\d{1,3})\s*[.)]\s*(\S.*)?$")
_CHOICE = re.compile(r"^\s*\(?([A-D])\s*[).:]\s*(.*)$")
_INLINE_CHOICE = re.compile(r"(?:^|\s)\(?([A-D])[).:]\s+")
_KEY_LINE = re.compile(
    r"^\s*(?:correct\s+answer|answer|ans|key)\s*[:\-–]\s*(\S.*?)\s*$", re.IGNORECASE
)
_SOLUTION_LINE = re.compile(r"^\s*(?:explanation|solution|rationale)\s*[:\-–]\s*(.*)$", re.I)
_ANSWER_HEADING = re.compile(r"^\s*(?:answer\s*key|answers|key)\s*:?\s*$", re.IGNORECASE)
_PAIR = re.compile(r"(\d{1,3})\s*[.):\-–]?\s*([A-D])\b")
_PAIR_LINE = re.compile(r"^\s*(?:\d{1,3}\s*[.):\-–]?\s*[A-D]\b[\s,;]*)+$")
_PASSAGE_INTRO = re.compile(
    r"^\s*questions?\s+(\d{1,3})\s*(?:-|–|—|to|through|and)\s*(\d{1,3})\b.*"
    r"(?:refer|based|relate|use|following)",
    re.IGNORECASE,
)
_MAX_GAP = 5  # a number further ahead than this is passage text, not a new question


@dataclass(frozen=True, slots=True, kw_only=True)
class ProposedPassage:
    ref: str  # "p1", "p2", … (local to one parse)
    title: str
    text: str
    range_from: int
    range_to: int


@dataclass(frozen=True, slots=True, kw_only=True)
class ProposedQuestion:
    number: int
    stem: str
    choices: Mapping[str, str] | None
    answer: str | None = None
    solution: str | None = None
    passage_ref: str | None = None
    section: str | None = None
    skill_ids: Sequence[str] = ()
    difficulty: str | None = None
    item_type: str = "mc"  # mc | spr
    problems: Sequence[str] = ()


@dataclass(frozen=True, slots=True, kw_only=True)
class ParseResult:
    questions: Sequence[ProposedQuestion]
    passages: Sequence[ProposedPassage]
    problems: Sequence[str] = ()  # about the whole input
    answer_key: Mapping[int, str] = field(default_factory=dict)  # from an answer block


@dataclass(slots=True)
class _Draft:
    number: int
    stem: list[str] = field(default_factory=list)
    choices: dict[str, list[str]] = field(default_factory=dict)
    answer: str | None = None
    solution: list[str] | None = None
    passage_ref: str | None = None
    last: str = "stem"  # where continuation lines go: stem | A-D | solution


def _clean(lines: Sequence[str]) -> str:
    return "\n".join(line.rstrip() for line in lines).strip()


def _split_inline_choices(text: str) -> list[tuple[str, str]] | None:
    """`A) 1 B) 2 C) 4 D) 8` → [("A","1"), …] when the keys appear in order from A."""
    marks = list(_INLINE_CHOICE.finditer(text))
    keys = [m.group(1) for m in marks]
    if len(marks) < 2 or keys != list(CHOICE_KEYS[: len(keys)]) or marks[0].start() > 1:
        return None
    out = []
    for i, m in enumerate(marks):
        end = marks[i + 1].start() if i + 1 < len(marks) else len(text)
        out.append((m.group(1), text[m.end() : end].strip()))
    return out


def _answer_block(lines: list[str]) -> tuple[list[str], dict[int, str]]:
    """Remove a trailing answer block; return (remaining lines, number → key)."""
    keys: dict[int, str] = {}
    start = None
    for i, line in enumerate(lines):
        if _ANSWER_HEADING.match(line):
            start = i
            break
    if start is None:  # a trailing run of pair-only lines
        i = len(lines)
        while i > 0 and (not lines[i - 1].strip() or _PAIR_LINE.match(lines[i - 1])):
            i -= 1
        if i < len(lines) and any(_PAIR_LINE.match(x) for x in lines[i:]):
            start = i
    if start is None:
        return lines, keys
    for line in lines[start:]:
        for n, letter in _PAIR.findall(line):
            keys[int(n)] = letter
    if not keys:
        return lines, {}
    return lines[:start], keys


def parse_text(text: str) -> ParseResult:
    if len(text) > MAX_TEXT_CHARS:
        too_long = f"The text is longer than {MAX_TEXT_CHARS} characters; split it."
        return ParseResult(questions=(), passages=(), problems=(too_long,))
    lines = text.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    lines, block_keys = _answer_block(lines)

    drafts: list[_Draft] = []
    passages: list[ProposedPassage] = []
    problems: list[str] = []
    open_passage: tuple[str, int, int, list[str]] | None = None  # title, from, to, text lines
    pending_ref: tuple[str, int, int] | None = None

    def close_passage() -> None:
        nonlocal open_passage, pending_ref
        if open_passage is None:
            return
        title, lo, hi, body = open_passage
        ref = f"p{len(passages) + 1}"
        passages.append(
            ProposedPassage(ref=ref, title=title, text=_clean(body), range_from=lo, range_to=hi)
        )
        pending_ref = (ref, lo, hi)
        open_passage = None

    current: _Draft | None = None
    for line in lines:
        intro = _PASSAGE_INTRO.match(line)
        if intro:
            close_passage()
            lo, hi = int(intro.group(1)), int(intro.group(2))
            if hi < lo:
                lo, hi = hi, lo
            open_passage = (line.strip(), lo, hi, [])
            current = None
            continue
        q = _QUESTION.match(line)
        if q:
            n = int(q.group(1))
            prev = drafts[-1].number if drafts else None
            expected = open_passage[1] if open_passage else None
            starts = (
                (prev is None and (expected is None or n == expected))
                or (prev is not None and prev < n <= prev + _MAX_GAP)
                or (expected is not None and n == expected)
            )
            if starts:
                close_passage()
                current = _Draft(number=n)
                if pending_ref and pending_ref[1] <= n <= pending_ref[2]:
                    current.passage_ref = pending_ref[0]
                rest = q.group(2) or ""
                inline = _split_inline_choices(rest)
                if inline:
                    current.choices = {k: [v] for k, v in inline}
                    current.last = inline[-1][0]
                elif rest:
                    current.stem.append(rest)
                drafts.append(current)
                continue
        if open_passage is not None:
            open_passage[3].append(line)
            continue
        if current is None:
            if line.strip():
                problems.append(
                    f"Text before the first question was ignored: “{line.strip()[:60]}”"
                )
            continue
        key = _KEY_LINE.match(line)
        if key:
            current.answer = key.group(1).strip().rstrip(".")
            current.last = "stem"
            continue
        sol = _SOLUTION_LINE.match(line)
        if sol:
            current.solution = [sol.group(1)] if sol.group(1) else []
            current.last = "solution"
            continue
        inline = _split_inline_choices(line.strip())
        if inline and (not current.choices or inline[0][0] == "A"):
            for k, v in inline:
                current.choices[k] = [v]
            current.last = inline[-1][0]
            continue
        choice = _CHOICE.match(line)
        if choice and (choice.group(1) not in current.choices) and current.last != "solution":
            current.choices[choice.group(1)] = [choice.group(2)]
            current.last = choice.group(1)
            continue
        if current.last == "solution" and current.solution is not None:
            current.solution.append(line)
        elif current.last in CHOICE_KEYS and line.strip():
            current.choices[current.last].append(line.strip())
        else:
            current.stem.append(line)
    close_passage()

    if len(drafts) > MAX_QUESTIONS:
        problems.append(f"Only the first {MAX_QUESTIONS} questions are shown; split the text.")
        drafts = drafts[:MAX_QUESTIONS]
    if not drafts and not block_keys:
        problems.append("No numbered questions were found (expected lines like “1. …”).")

    questions: list[ProposedQuestion] = []
    previous: int | None = None
    for d in drafts:
        answer = d.answer or block_keys.get(d.number)
        if d.answer and block_keys.get(d.number) and d.answer != block_keys[d.number]:
            problems.append(
                f"Question {d.number}: the answer line says {d.answer}, the answer block says "
                f"{block_keys[d.number]}; the answer line was used."
            )
        questions.append(
            finish_question(
                d.number,
                _clean(d.stem),
                {k: _clean(v) for k, v in d.choices.items()} or None,
                answer,
                _clean(d.solution) if d.solution else None,
                d.passage_ref,
                gap_after=previous,
            )
        )
        previous = d.number
    for p in passages:
        if not any(q.passage_ref == p.ref for q in questions):
            problems.append(
                f"“{p.title[:60]}”: no questions {p.range_from}–{p.range_to} follow it."
            )
    return ParseResult(
        questions=questions, passages=passages, problems=problems, answer_key=dict(block_keys)
    )


def finish_question(
    number: int,
    stem: str,
    choices: Mapping[str, str] | None,
    answer: str | None,
    solution: str | None,
    passage_ref: str | None,
    *,
    gap_after: int | None = None,
    item_type: str | None = None,
    extra: Sequence[str] = (),
) -> ProposedQuestion:
    problems = list(extra)
    kind = item_type or ("mc" if choices else ("spr" if answer else "mc"))
    if gap_after is not None and number != gap_after + 1:
        problems.append(f"follows question {gap_after} (numbers skipped)")
    if not stem:
        problems.append("the stem is empty")
    if kind == "mc":
        found = sorted(choices or {})
        if found != list(CHOICE_KEYS):
            problems.append(
                "choices A–D incomplete" + (f" (found {', '.join(found)})" if found else "")
            )
        if answer is not None and answer.upper() in CHOICE_KEYS:
            answer = answer.upper()
        elif answer is not None:
            problems.append(f"the key “{answer}” is not one of A–D")
            answer = None
    if answer is None:
        problems.append("no answer key")
    return ProposedQuestion(
        number=number,
        stem=stem,
        choices=dict(choices) if (choices and kind == "mc") else None,
        answer=answer,
        solution=solution,
        passage_ref=passage_ref,
        item_type=kind,
        problems=tuple(problems),
    )


# ---- CSV ------------------------------------------------------------------------------------

CSV_COLUMNS = (
    "number", "passage", "stem", "A", "B", "C", "D", "answer", "solution",
    "skills", "difficulty", "section", "type",
)  # fmt: skip
_DIFFICULTIES = {"easy", "medium", "hard"}


def csv_template() -> str:
    return ",".join(CSV_COLUMNS) + "\n"


def parse_csv(text: str) -> ParseResult:
    if len(text) > MAX_TEXT_CHARS:
        return ParseResult(
            questions=(), passages=(), problems=("The file is too large; split it.",)
        )
    rows = list(csv.reader(io.StringIO(text.lstrip("﻿"))))
    rows = [r for r in rows if any(c.strip() for c in r)]
    if not rows:
        return ParseResult(questions=(), passages=(), problems=("The file is empty.",))
    header = [h.strip() for h in rows[0]]
    lookup = {h.lower(): i for i, h in enumerate(header)}
    problems: list[str] = []
    unknown = [h for h in header if h and h.lower() not in {c.lower() for c in CSV_COLUMNS}]
    if unknown:
        problems.append("Unknown columns ignored: " + ", ".join(unknown))
    if "stem" not in lookup:
        return ParseResult(
            questions=(), passages=(),
            problems=(*problems, "The first row must be the header; a “stem” column is required."),
        )  # fmt: skip

    def cell(row: list[str], name: str) -> str:
        i = lookup.get(name.lower())
        return row[i].strip() if i is not None and i < len(row) else ""

    passages: list[ProposedPassage] = []
    passage_refs: dict[str, int] = {}  # passage text → index in `passages`
    questions: list[ProposedQuestion] = []
    used: set[int] = set()
    for line_no, row in enumerate(rows[1 : MAX_QUESTIONS + 1], start=2):
        extra: list[str] = []
        raw_number = cell(row, "number")
        number = (
            int(raw_number)
            if raw_number.isdigit()
            else (questions[-1].number + 1 if questions else 1)
        )
        if raw_number and not raw_number.isdigit():
            extra.append(f"number “{raw_number}” is not a whole number")
        if number in used:
            extra.append(f"number {number} is used twice")
        used.add(number)
        kind = (cell(row, "type") or "").lower() or None
        if kind not in (None, "mc", "spr"):
            extra.append(f"type “{kind}” is not mc or spr")
            kind = None
        choices = {k: cell(row, k) for k in CHOICE_KEYS if cell(row, k)}
        passage_text = cell(row, "passage")
        ref = None
        if passage_text:
            idx = passage_refs.get(passage_text)
            if idx is None:
                idx = len(passages)
                passage_refs[passage_text] = idx
                passages.append(
                    ProposedPassage(
                        ref=f"p{idx + 1}",
                        title=passage_text.split("\n", 1)[0][:80],
                        text=passage_text,
                        range_from=number,
                        range_to=number,
                    )
                )
            else:
                p = passages[idx]
                passages[idx] = replace(
                    p, range_from=min(p.range_from, number), range_to=max(p.range_to, number)
                )
            ref = passages[idx].ref
        difficulty = cell(row, "difficulty").lower() or None
        if difficulty is not None and difficulty not in _DIFFICULTIES:
            extra.append(f"difficulty “{difficulty}” is not easy, medium or hard")
            difficulty = None
        q = finish_question(
            number,
            cell(row, "stem"),
            choices or None,
            cell(row, "answer") or None,
            cell(row, "solution") or None,
            ref,
            item_type=kind,
            extra=extra,
        )
        skills = [s.strip() for s in re.split(r"[;,]", cell(row, "skills")) if s.strip()]
        questions.append(
            replace(
                q,
                section=cell(row, "section") or None,
                skill_ids=tuple(skills),
                difficulty=difficulty,
                problems=tuple(f"row {line_no}: {p}" for p in q.problems),
            )
        )
    if len(rows) - 1 > MAX_QUESTIONS:
        problems.append(f"Only the first {MAX_QUESTIONS} rows were read; split the file.")
    return ParseResult(questions=questions, passages=passages, problems=problems)
