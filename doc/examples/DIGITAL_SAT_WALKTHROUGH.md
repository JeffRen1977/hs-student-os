# Digital SAT, end to end: from authoring to a student studying

This walkthrough follows one course, **Digital SAT**, through every role on the platform: the
author writes it, the platform reviewer approves it, an admin gives a student access, and the
student enrolls and studies with the course's tutor. Everything below was run on the staging
environment on 2026-11-07 with synthetic users; the tutor replies and results are real output
from that run (model: OpenAI `gpt-5.5`).

| Role | Synthetic account | Does | Tool today |
|---|---|---|---|
| Author | `author_hsos` (organization `org_hsos_content`) | Writes and uploads the course package, submits it | Author portal (`/author.html`) |
| Platform reviewer | `reviewer_platform` | Reviews, approves, activates | Review API (reviewer screen planned, Step 41) |
| Platform admin | — | Grants a student access to the course | Firestore edit (admin tool planned, Step 42) |
| Student | `stu_beth` (new to the course), `stu_alex` (enrolled since 1.0.0) | Enrolls, studies, gets feedback and a plan | Student app (`/`) |

## 1. The author builds the course

The course is one JSON file: [`server/content/authored/dsat/package-2.0.1.json`](../../server/content/authored/dsat/package-2.0.1.json)
(a copy ships in the [author kit](../author-kit/examples/digital-sat-2.0.1.json)).

| Part | Content |
|---|---|
| Skills | 29: the public Digital SAT skills. Reading and Writing: Information and Ideas, Craft and Structure, Expression of Ideas, Standard English Conventions. Math: Algebra, Advanced Math, Problem-Solving and Data Analysis, Geometry and Trigonometry |
| Practice sets | 12 multiple-choice sets: 8 sets of 5 items (one per domain, original content) + the 4 sets from 1.0.0. Each Reading and Writing item carries its own short passage |
| Scoring | One rubric per set, one line per item, each tagged with the skill that item tests; scored by answer key (`choice-scoring`), no AI involved |
| Tutor | `socratic-guidance`: hints by questions; never confirms an answer before submission; never predicts scores |
| Practice order | 2 starter sets (one Reading and Writing, one Math), then a `practiceSequence` of the other 10, alternating sections |
| Test cases | 36 (all correct / one wrong / unreadable, for every set), run automatically at upload |

History of versions: 1.0.0 (4 Math sets) → 2.0.0 (both sections, 29 skills, kept every 1.0.0
question and skill ID so existing students are unaffected) → 2.0.1 (adds the practice order).
How each part is written is explained in the [author kit](../author-kit/README.md).

Before uploading, every answer key was checked independently: all Math keys recomputed with a
computer algebra system, each Reading and Writing key checked against its text.

## 2. The author uploads and submits

In the author portal, `author_hsos` uploads the file and gets the validation report at once:

- **valid**, no errors; **36/36** test cases pass;
- the **student preview** shows 12 sets and 29 skills, with no answer keys, rubrics, tutor
  instructions or test cases;
- for 2.0.1, the preview also lists the practice order (2 starters + 10 in sequence).

The author presses **Submit**. From now on this version cannot change.

## 3. The platform reviewer reviews and publishes

The reviewer finds the version in the review queue and checks:

| Check | Result for Digital SAT |
|---|---|
| Validation report and test cases | Valid, 36/36 |
| History | Uploaded and submitted by `author_hsos` |
| Rights | Every question and rubric is `original`; no College Board or prep-book material |
| Content | Answer keys, one defensible answer per item, skill tags, wording |
| Upgrade safety | All question and skill IDs that students already use are kept |
| Student preview | Reads well; nothing secret is shown |

Then **approve** (with the license attestation) and **activate**. The previous version becomes
`superseded`: a student in the middle of a set finishes it on the old version and its answer
key; new practice uses the new version. Past results never change.

```bash
# Reviewer, against the staging API (the reviewer screen in Step 41 will replace this)
V=$API/api/review/packages/dsat/versions/2.0.1
curl -s -X POST $V/approve  -H "Authorization: Bearer $TOKEN" -H "Idempotency-Key: $(uuidgen)" \
  -H 'Content-Type: application/json' -d '{"notes":"Checked keys, sources and preview.","licenseAttested":true}'
curl -s -X POST $V/activate -H "Authorization: Bearer $TOKEN" -H "Idempotency-Key: $(uuidgen)" \
  -H 'Content-Type: application/json' -d '{}'
```

The items are still marked `draft`. Staging serves draft content; production withholds it until
a named content reviewer marks each item `reviewed`.

## 4. An admin gives the student access

The course is now in the catalog, but Beth cannot enroll yet:

> `POST /api/courses/enroll {"courseId":"dsat"}` → **403 `COURSE_ACCESS_REQUIRED`**

Access is managed by the platform, never by authors. Today an admin adds `"dsat"` to `courses` in
`students/stu_beth/access/current` (Firestore); Step 42 plans an audited admin tool for this.

## 5. The student enrolls

Beth opens the catalog, chooses **Digital SAT → Add course**, and receives the two starter sets:

```
PLANNED  2026-11-07  Reading and Writing: information and ideas, set 1   [INITIAL_PRACTICE]
PLANNED  2026-11-08  Math: algebra, set 1                                 [INITIAL_PRACTICE]
```

## 6. The student studies

### Getting a hint

Beth opens *Information and Ideas, set 1* and asks about item 3 (choose the quotation that
supports a claim about the novelist's characters):

> **Beth:** I'm stuck on item 3. Which quote should I pick?
>
> **Tutor:** Look for the quote that shows both parts of the claim at once: a period of
> uncertainty and a daily routine that brings comfort. Which choice includes a repeated habit
> and also shows that the habit calms the character?
>
> **Beth:** Just tell me: is item 3 C?
>
> **Tutor:** I can't confirm a choice before you submit it. Check which quote shows a routine
> during a difficult situation and explicitly suggests that the routine is comforting—what
> phrase in one option shows that effect?

The tutor sees each item's passage, question and choices, but never the answer keys, so it
cannot give them away. Every hint is recorded on the session.

### Submitting and feedback

Beth answers one line per item (`1: A`, `2: B`, …). The set is scored by its answer key in a
moment:

> Item 1: correct. Item 2: correct. Item 3: correct. Item 4: not correct. Item 5: correct.

She completes the session. **The next sets in the course's practice order appear right away**:
the platform keeps her at two unfinished sets.

```
COMPLETED  2026-11-07  Reading and Writing: information and ideas, set 1   [INITIAL_PRACTICE]
COMPLETED  2026-11-08  Math: algebra, set 1                                 [INITIAL_PRACTICE]
COMPLETED  2026-11-09  Reading and Writing: craft and structure, set 1      [NEXT_PRACTICE]
PLANNED    2026-11-10  Math: advanced math, set 1                           [NEXT_PRACTICE]
PLANNED    2026-11-11  Reading and Writing: expression of ideas, set 1      [NEXT_PRACTICE]
```

On *Craft and Structure* she asked about a word's meaning:

> **Beth:** For item 1, what does 'economy' mean in that sentence?
>
> **Tutor:** Look at the context clue after the colon: the engineers "used half as much steel"
> but the bridge was still stronger. Which choice means using resources efficiently?

She then scored 5/5, recorded as **hint-assisted**.

### Progress per skill

Each item updates the skill it tests. Work done after a hint counts as evidence but not as
independent evidence, so those skills stay at `emerging`:

```
dsat.algebra.linear-equations                  developing   evidence 1, independent 1
dsat.algebra.linear-functions                  developing   evidence 1, independent 1
...
dsat.craft-structure.words-in-context          emerging     evidence 1, independent 0
dsat.information-ideas.command-of-evidence     emerging     evidence 1, independent 0
```

There is **no SAT score prediction**: `{"status": "unavailable", "reason": "not_calibrated"}`.

### The weekly plan

The planner fits the sets into Beth's weekly time (180 minutes, 26 per day) and explains each
placement:

```
2026-11-10  dsat  Math: advanced math, set 1                          20 min  Little independent
            evidence yet for Equivalent expressions, Nonlinear equations and systems, Nonlinear
            functions. Kept on 2026-11-10: fits your 26-minute daily budget.
2026-11-11  dsat  Reading and Writing: expression of ideas, set 1     20 min  Little independent
            evidence yet for Rhetorical synthesis, Transitions. Kept on 2026-11-11: ...
```

The plan covers all of a student's enrolled courses, but a course's evidence never changes
another course's tasks or progress.

## 7. A student who joined before the update

Alex enrolled when the course was 1.0.0 and had two 1.0.0 sets in progress. After 2.0.1 was
activated, he finished one of them, and received the first set in the new order he had never had:

```
COMPLETED    2026-11-04  Equivalent expressions: set 1                        [INITIAL_PRACTICE]
IN_PROGRESS  2026-11-05  Function composition: set 1                          [INITIAL_PRACTICE]
PLANNED      2026-11-10  Reading and Writing: information and ideas, set 1   [NEXT_PRACTICE]
```

## 8. The author sees results

The author portal shows aggregate results per course (students, graded answers by status, the
average score on each rubric line). With fewer than 5 students they are hidden
(`"suppressed": true`), as they were here. Authors never see an individual student's work.

## 9. Repeat it yourself

**Locally** (synthetic users, nothing to deploy):

```bash
make server-memory     # API + worker; Digital SAT 1.0.0 is seeded active, Alex enrolled
make web
```

1. <http://localhost:8000/author.html>, local sign-in as `author_hsos`: upload
   `server/content/authored/dsat/package-2.0.1.json`, check the report and preview, submit.
2. Approve and activate as `reviewer_platform` with the commands in
   [AUTHORING_GUIDE.md](../AUTHORING_GUIDE.md) §5 (local token snippet included).
3. <http://localhost:8000>, local sign-in as `stu_alex`: open Digital SAT, finish a set, see the
   next one appear. (Beth has no Digital SAT access locally; granting it needs an edit to the
   in-memory store, so use Alex.) The tutor replies are labeled synthetic unless
   `HSOS_LLM_PROVIDER` is set to a real model (see the root README).

**On staging** (https://hs-student-os.web.app): the same flow, signing in with the synthetic
accounts' staging password; the reviewer and admin steps use the API and Firestore as in
sections 3–4.

## 10. What is still manual or open

- Reviewer screen (Step 41) and admin access tool (Step 42): today the API and a Firestore edit.
- Content review: every item is `draft`; a named reviewer must sign off before production.
- Figures and formatted math in items (needed for many real SAT Math questions).
- Evidence-driven follow-up (Step 24.2): repeated errors on a skill → a targeted diagnostic and
  practice. Today the next set follows the package's order, not the student's mistakes.
- Timed, full-length tests.
