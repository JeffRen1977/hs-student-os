"""Step 39A: the deterministic splitter for pasted text and CSV (synthetic questions only)."""

from __future__ import annotations

from app.domain.question_splitter import CSV_COLUMNS, csv_template, parse_csv, parse_text
from app.domain.types.bank import content_hash

PASTE = """Questions 1-2 refer to the following passage.
Tide pools form where the sea meets rock.
They hold many small animals.

1. What does the passage mainly describe?
A) storms
B) tide pools
C) ships
D) rivers
2. Which word best describes the animals?
A) small B) huge C) loud D) fast
3. What is 2 + 2?
(A) 3
(B) 4
(C) 5
(D) 6
Answer: B
Explanation: Add the numbers.
2 + 2 = 4.
4) If 3x = 12, what is x?
Answer: 4

Answer key
1. B  2. A
"""


def test_text_layouts_passages_keys_and_solutions() -> None:
    r = parse_text(PASTE)
    q1, q2, q3, q4 = r.questions
    assert [q.number for q in r.questions] == [1, 2, 3, 4]
    assert q1.choices == {"A": "storms", "B": "tide pools", "C": "ships", "D": "rivers"}
    assert q2.choices == {"A": "small", "B": "huge", "C": "loud", "D": "fast"}  # one line
    assert (q1.answer, q2.answer) == ("B", "A")  # answer block
    assert q3.answer == "B" and q3.solution == "Add the numbers.\n2 + 2 = 4."
    assert q4.item_type == "spr" and q4.answer == "4" and q4.choices is None
    (p,) = r.passages
    assert (p.range_from, p.range_to) == (1, 2) and "small animals" in p.text
    assert q1.passage_ref == q2.passage_ref == p.ref and q3.passage_ref is None
    assert all(not q.problems for q in r.questions) and not r.problems


def test_a_passage_links_only_to_its_stated_range() -> None:
    text = (
        "Questions 1 and 2 are based on the following information.\nA table of costs.\n"
        + "".join(f"{n}. Question {n}?\nA) a\nB) b\nC) c\nD) d\nAnswer: A\n" for n in (1, 2, 3))
    )
    q1, q2, q3 = parse_text(text).questions
    assert q1.passage_ref == q2.passage_ref == "p1" and q3.passage_ref is None


def test_problems_are_reported_not_hidden() -> None:
    r = parse_text(
        "Some heading\n1. First?\nA) x\nB) y\nAnswer: E\n4. Fourth?\nA) a\nB) b\nC) c\nD) d\n"
    )
    q1, q4 = r.questions
    assert "choices A–D incomplete (found A, B)" in q1.problems
    assert "the key “E” is not one of A–D" in q1.problems and q1.answer is None
    assert "follows question 1 (numbers skipped)" in q4.problems and "no answer key" in q4.problems
    assert r.problems == ["Text before the first question was ignored: “Some heading”"]
    assert parse_text("no numbers here").problems == [
        "Text before the first question was ignored: “no numbers here”",
        "No numbered questions were found (expected lines like “1. …”).",
    ]


def test_conflicting_keys_prefer_the_answer_line_and_say_so() -> None:
    r = parse_text("1. Q?\nA) a\nB) b\nC) c\nD) d\nAnswer: C\n\nAnswers\n1. D\n")
    assert r.questions[0].answer == "C"
    assert "the answer line says C, the answer block says D" in r.problems[0]


def test_csv_rows_passages_and_row_numbered_problems() -> None:
    assert csv_template().strip().split(",") == list(CSV_COLUMNS)
    text = (
        "number,passage,stem,A,B,C,D,answer,skills,difficulty,section\n"
        "1,Shared text,First?,a,b,c,d,b,dsat.x;dsat.y,easy,math\n"
        "2,Shared text,Second?,a,b,c,,E,,hard,\n"
        "3,,What is 7/2?,,,,,3.5,,,\n"
    )
    r = parse_csv(text)
    q1, q2, q3 = r.questions
    assert (q1.answer, q1.skill_ids, q1.difficulty, q1.section) == (
        "B",
        ("dsat.x", "dsat.y"),
        "easy",
        "math",
    )
    assert q2.problems == (
        "row 3: choices A–D incomplete (found A, B, C)",
        "row 3: the key “E” is not one of A–D",
        "row 3: no answer key",
    )
    assert q3.item_type == "spr" and q3.answer == "3.5"
    (p,) = r.passages
    assert q1.passage_ref == q2.passage_ref == p.ref and (p.range_from, p.range_to) == (1, 2)
    assert (
        parse_csv("question,A\nx,y\n").problems[-1].startswith("The first row must be the header")
    )


def test_content_hash_ignores_case_spacing_and_underline_markers() -> None:
    a = content_hash("What  is [[2 + 2]]?", {"B": "4", "A": "3"})
    assert a == content_hash("what is 2 + 2?", {"A": "3", "B": "4"})
    assert a != content_hash("What is 2 + 3?", {"A": "3", "B": "4"})


def test_the_portal_csv_template_parses_cleanly() -> None:
    """The bank screen's downloadable template (web/js/portal/bank-api.js) must stay in step
    with the server's CSV columns."""
    import json
    import re
    from pathlib import Path

    js = (Path(__file__).parents[3] / "web/js/portal/bank-api.js").read_text()
    columns = json.loads(re.search(r"const CSV_COLUMNS = (\[[^\]]*\])", js, re.S)[1])  # type: ignore[index]
    assert columns == list(CSV_COLUMNS)
    rows = re.findall(r"'(\d,[^']*)\\n'", js)
    r = parse_csv(",".join(columns) + "\n" + "\n".join(rows) + "\n")
    assert [q.number for q in r.questions] == [1, 2] and not r.problems
    assert all(not q.problems for q in r.questions), [q.problems for q in r.questions]
