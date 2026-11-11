> Current course publication policy (2026-11-07): author submits → reviewer approves
> → admin publishes to the platform catalog → any student can enroll. Admins do not
> grant courses to individual students or cohorts. Reviewer publication endpoints and
> the old student-grant API are removed; this guide follows the policy. See
> [API contract](API.md) and the Digital SAT walkthrough.

# Publishing a course package: internal guide

> **Audience: the platform team and platform reviewers.** Course authors get the
> [author kit](author-kit/README.md) instead (author guide, field reference, blank template, and
> example). This guide adds what authors do not need: the reviewer's approve step, the admin's publish step, the
> local walkthrough, and platform limits. The kit's example
> (`author-kit/examples/digital-sat-2.0.1.json`) is a copy of
> `server/content/authored/dsat/package-2.0.1.json`; copy it again whenever that file changes.
> The end-to-end example across every role is in [examples/DIGITAL_SAT_WALKTHROUGH.md](examples/DIGITAL_SAT_WALKTHROUGH.md).

This guide shows how a course is published on High School Student OS. It uses
**Digital SAT 2.0.0** ([`server/content/authored/dsat/package-2.0.0.json`](../server/content/authored/dsat/package-2.0.0.json))
as the worked example. The formal contract is [COURSE_PACKAGE.md](COURSE_PACKAGE.md); this guide
is the practical walkthrough.

## 1. What a course package is

A course package is **one JSON document of data**. It describes the course's skills, practice
content, how answers are scored, and the cases that prove scoring works. It never contains
code. Every course runs on the same platform runtime; your package only *selects* platform
abilities and *configures* them.

| You can | You cannot |
|---|---|
| Define skills, practice sets, rubrics, a tutor prompt, starter tasks, an evaluation set | Upload code, add tools, or add abilities (ask the platform team for a new ability instead) |
| Upload and replace drafts, read the validator report, preview the student view | Approve or publish your own package (a platform reviewer approves; a platform admin publishes) |
| See aggregate course metrics (hidden below 5 students) | See any individual student's data |
| Submit new versions of courses your organization owns | Choose which students get the course (every student can enroll once it is published) |

Package text is treated as **content, not instructions**: it cannot change grading rules,
reveal answer keys, or widen tool access.

## 2. The worked example at a glance

| Part | Digital SAT 2.0.0 |
|---|---|
| Course | `dsat`, owned by `org_hsos_content` (author `author_hsos`); upgrades 1.0.0 |
| Abilities | `socratic-guidance` (hints), `choice-scoring` (scored by answer key, no model) |
| Skills | 29: the public Digital SAT skill list across 8 domains |
| Practice sets | 8 new sets × 5 items (one per domain) + the 4 sets carried over from 1.0.0 |
| Evaluation set | 36 automatic cases (3 per set) |
| Starter tasks | 2 (one Reading and Writing set, one Math set) |
| Size | ~63 KB (limit 900 KB) |
| Content status | Original; `review.status: "draft"` on every item until a content reviewer signs off |

## 3. Building the package, part by part

### 3.1 Manifest

```json
"manifest": {
  "courseId": "dsat",
  "version": "2.0.0",
  "name": "Digital SAT",
  "description": "Digital SAT practice across both sections, ... No SAT score predictions.",
  "category": "SAT",
  "agentType": "DSAT",
  "supportedTaskTypes": ["PRACTICE"],
  "supportedModes": ["ADAPTIVE"],
  "abilities": ["socratic-guidance", "choice-scoring"],
  "tools": ["content-retrieval"],
  "modelTier": "balanced",
  "contextBudgetTokens": 8000,
  "workflowVersion": "dsat-practice-v2",
  "publisher": {"name": "HS Student OS content team"},
  "license": "Original work; internal use (synthetic draft, pending content review)"
}
```

- `courseId`: lowercase letters, digits, underscores. Other organizations' course IDs and the
  platform's built-in courses (`calc_bc`, `physics_c`) are refused with `COURSE_ID_TAKEN`.
- `version`: `MAJOR.MINOR.PATCH`, and it must be higher than every version you have submitted.
- `category` is a catalog label only. It never grants access.
- Every ability you list must have matching content (`choice-scoring` needs at least one choice
  set), and every kind of content must have its ability. The validator checks both directions.
- `modelTier` must meet the floor of every ability you select.

Platform abilities you can select. A running session keeps the ability version it started with.

| Ability | Version | Handles | Needs a model | Minimum tier | Evidence | Content it needs |
|---|---|---|---|---|---|---|
| `socratic-guidance` | 1 | Hints on any question or open chat | Yes | fast | Hint usage (never independent evidence) | None |
| `choice-scoring` | 1 | Assessment of choice sets | No | None | Answer key | At least one choice set |
| `rubric-assessment` | 1 | Assessment of free-response questions | Yes | fast | Rubric criteria | At least one free-response question |
| `source-analysis` | 1 | Assessment of source-based writing | Yes | fast | Rubric criteria | At least one question with `sourceMaterialIds` |

### 3.2 Skills

```json
{"skillId": "dsat.craft-structure.words-in-context", "name": "Words in context",
 "description": "Determine the meaning of a word or choose the most precise word for a context."}
```

- Every skill ID starts with `{courseId}.`, then dot-separated lowercase segments.
- **Never rename or drop a skill ID in a new version.** Students' mastery is stored per skill ID.
  2.0.0 keeps the four 1.0.0 IDs (`dsat.algebra.linear-equations`,
  `dsat.advanced-math.equivalent-expressions`, `dsat.advanced-math.nonlinear-functions`,
  `dsat.problem-solving.rates-ratios`) and adds 25 more.

### 3.3 Practice sets (choice sets)

A choice set is a question with up to 10 `items`; each item has 2–4 choices (`A`–`D`), one
`answerKey`, and a `criterionId` that points to its rubric criterion.

```json
{
  "questionId": "q_dsat_conv_001",
  "version": "1",
  "courseId": "dsat",
  "topic": "Standard English Conventions: set 1",
  "skillIds": ["dsat.conventions.boundaries", "dsat.conventions.form-structure-sense"],
  "difficulty": "easy",
  "prompt": "Five items on punctuation at sentence boundaries ... Choose one answer for each item. ...",
  "expectedAnswer": "1: A, 2: B, 3: D, 4: B, 5: C",
  "rubricRef": {"rubricId": "dsat-conv-001", "version": "1"},
  "items": [
    {"itemId": "1",
     "prompt": "The hikers packed three essentials for the ______ water, a map, and a first-aid kit.\n\nWhich choice completes the text so that it conforms to the conventions of Standard English?",
     "choices": [{"key": "A", "text": "trip:"}, {"key": "B", "text": "trip, and"},
                 {"key": "C", "text": "trip;"}, {"key": "D", "text": "trip, which"}],
     "answerKey": "A", "criterionId": "item-1"}
  ],
  "source": {"type": "original", "author": "HS Student OS content team", "license": "Original work; ..."},
  "review": {"status": "draft", "reviewer": null, "reviewedAt": null}
}
```

- **Reading and Writing passages go inside each item's `prompt`**, followed by a blank line and
  the question. Choice sets cannot attach `materials` (materials are for source-based writing).
- Answer keys never reach the student: the session view and the preview drop them.
- Students answer one line per item: `1: A`, `2) c`, `item 3 - B` all work. Anything the scorer
  cannot read becomes `insufficient_evidence` and never changes mastery.
- ID patterns: question IDs are opaque (`q_dsat_conv_001`); **rubric IDs use only lowercase
  letters, digits and hyphens** (`dsat-conv-001`). An underscore in a rubric ID is a validator
  error.

### 3.4 Rubrics: one criterion per item, tagged with the item's skill

```json
{"rubricId": "dsat-psda-001", "version": "1", "courseId": "dsat", "criteria": [
  {"criterionId": "item-1", "description": "Item 1: selects the correct choice.", "maxPoints": 1,
   "evidenceRequirements": ["Selects choice B for item 1"],
   "skillIds": ["dsat.problem-solving.rates-ratios", "dsat.problem-solving.percentages"]}
]}
```

The criterion's `skillIds` decide which mastery records an item updates. Tag each item with the
skill it actually tests, not the whole set's skills. Tag two skills only when the item genuinely
needs both (item 1 above needs a unit rate *and* a 20% discount).

### 3.5 Tutor prompt

`systemPrompt` sets the tutor's teaching style for the course. Only three template variables are
allowed: `{{studentName}}`, `{{currentMode}}`, `{{masteryContext}}`. The example tells the tutor
to guide with questions, never name the correct choice before submission, and never predict SAT
scores.

### 3.6 Starter tasks

```json
{"questionId": "q_dsat_info_001", "taskType": "PRACTICE", "mode": "ADAPTIVE",
 "title": "Reading and Writing: information and ideas, set 1", "durationMin": 20}
```

Created once, when a student first enrolls and has no tasks in the course.

### 3.6a Practice order (`practiceSequence`, added in 2.0.1)

Same shape as `starterTasks`. The course's practice order is the starter tasks followed by the
practice sequence. The platform keeps each enrolled student at 2 unfinished sets per course: when
a session completes, and in every planning pass, it gives the next sets in this order the student
has never had (task reason `NEXT_PRACTICE`). Digital SAT 2.0.1 lists the other ten sets,
alternating Reading and Writing with Math, then the four 1.0.0 sets.

### 3.7 Evaluation set

Every package needs one. For a choice set, write at least these three cases. They run
automatically at upload, and approval is blocked unless all pass.

```json
{"caseId": "conv-001-all-correct", "questionId": "q_dsat_conv_001",
 "answerText": "1: A\n2: B\n3: D\n4: B\n5: C", "expectedStatus": "accepted",
 "expectedEarned": {"item-1": 1, "item-2": 1, "item-3": 1, "item-4": 1, "item-5": 1}},
{"caseId": "conv-001-first-wrong", "questionId": "q_dsat_conv_001",
 "answerText": "1) b\n2) b\n3) d\n4) b\n5) c", "expectedStatus": "accepted",
 "expectedEarned": {"item-1": 0, "item-2": 1, "item-3": 1, "item-4": 1, "item-5": 1}},
{"caseId": "conv-001-unreadable", "questionId": "q_dsat_conv_001",
 "answerText": "I picked the second option for most of these, I think.",
 "expectedStatus": "insufficient_evidence", "expectedEarned": {}}
```

`expectedEarned` must list every criterion of the rubric (or be empty for
`insufficient_evidence`).

> The evaluation set proves **scoring works**, not that **your answer keys are right**. Check every
> key independently before submitting. For 2.0.0, every math key was recomputed with a computer
> algebra system, and each Reading and Writing key was checked against the text.

## 4. Publishing a new version without breaking students

- **Keep every question ID that existing tasks use.** A student's planned task points to a
  question ID, and a new session loads that question from the active version. If 2.0.0 had
  dropped `q_dsat_equiv_001`, Alex's planned task would fail with `COURSE_NOT_AVAILABLE`. 2.0.0
  keeps all four 1.0.0 sets unchanged.
- **Keep skill IDs** (section 3.2).
- To change an existing question, give it a new `version` rather than reusing the old one.
- Sessions already open stay on the version they started with (their content and answer key).
  New sessions use the active version.
- **New sets reach students already enrolled** through the practice order (section 3.6a): as
  they finish their current sets, they get the new version's sets they have not had. Before
  2026-11-07 they did not (starter tasks only), which is why 2.0.0 was followed by 2.0.1.

## 5. Publishing locally (walkthrough)

```bash
make install
make server-memory        # terminal 1: API + local worker on :8787, synthetic users seeded
make web                  # terminal 2: web on :8000
```

1. **Upload (author).** Open <http://localhost:8000/author.html>, sign in with local development
   sign-in as `author_hsos`, and upload `server/content/authored/dsat/package-2.0.0.json`.
2. **Read the report.** Expect `valid` with 36/36 automatic cases. Fix any error at the `path`
   it names and upload again (a draft can be replaced).
3. **Preview** the student view: 12 sets, 29 skills, no answer keys.
4. **Submit** for review. From this point the version is immutable.
5. **Review (platform reviewer).** Open <http://localhost:8000/review.html> and
   sign in as `reviewer_platform`. The version is under **Waiting for review**:
   - Check the report, the content (answer keys highlighted), the student preview and, for an
     upgrade, **compare** (removed question or skill IDs are warnings).
   - Optionally work through the per-item **checklist** (kept in your browser only).
   - Attest the license, then **Approve**. It asks you to confirm first. Reviewers cannot
     activate or retire.

   Then **publish (platform admin)**: open <http://localhost:8000/admin.html>, sign in as
   `admin_platform`, and click **Publish to catalog** for the approved version, then **Confirm**.

   The same decisions through the API (for scripts). Locally, an emulator-format token for
   `reviewer_platform` is accepted:

   ```bash
   cd server
   TOKEN=$(uv run python -c "
   import base64, json, time
   b = lambda d: base64.urlsafe_b64encode(json.dumps(d).encode()).decode().rstrip('=')
   n = int(time.time())
   print(b({'alg': 'none', 'typ': 'JWT'}) + '.' + b({'iss': 'https://securetoken.google.com/demo-hs-student-os',
     'aud': 'demo-hs-student-os', 'auth_time': n, 'user_id': 'reviewer_platform', 'sub': 'reviewer_platform',
     'iat': n, 'exp': n + 3600, 'firebase': {'identities': {}, 'sign_in_provider': 'password'}}) + '.')")
   API=http://127.0.0.1:8787
   R=$API/api/review/packages/dsat/versions/2.0.0

   curl -s -H "Authorization: Bearer $TOKEN" $API/api/review/packages          # review queue
   curl -s -X POST $R/approve -H "Authorization: Bearer $TOKEN" -H "Idempotency-Key: $(uuidgen)" \
     -H 'Content-Type: application/json' \
     -d '{"notes": "Validator clean, 36/36 cases, original content.", "licenseAttested": true}'
   # Publishing needs an admin token: build TOKEN as above with 'admin_platform', then
   curl -s -X POST $API/api/admin/packages/dsat/versions/2.0.0/activate \
     -H "Authorization: Bearer $TOKEN" -H "Idempotency-Key: $(uuidgen)" \
     -H 'Content-Type: application/json' -d '{}'
   ```

   Approval requires: no validator errors, all automatic cases passing, `licenseAttested: true`
   (and `modelEvaluationAttested: true` if the package has model-graded cases). Rejecting needs
   notes, which the author sees.
6. **Check as a student.** Sign in to <http://localhost:8000> as `stu_alex`: Digital SAT shows the
   2.0.0 description, 1.0.0 is `superseded`, and a new session uses 2.0.0.

The same flow, verified on 2026-11-07: upload → report (36/36) → preview → submit → the author
cannot approve their own package (403) → reviewer approves and activates → an open 1.0.0 session
is still scored with its 1.0.0 key → a 1.0.0-era task starts on 2.0.0 → a student without access
gets 403 → a newly enrolled student gets the 2.0.0 starter tasks, and mastery updates per skill.
(That run used the old policy, where reviewers activated and students needed a grant. Today an
admin publishes and every student can enroll; see
[examples/DIGITAL_SAT_WALKTHROUGH.md](examples/DIGITAL_SAT_WALKTHROUGH.md).)

## 6. Publishing on staging

Same steps against the deployed services (see [README](../README.md) §4):

- Author: `https://<project>.web.app/author.html`, signing in with the author's email and password.
- Reviewer: `https://<project>.web.app/review.html` (once Step 41 is deployed), or get an ID
  token with Firebase Auth email/password sign-in
  (`identitytoolkit.googleapis.com/v1/accounts:signInWithPassword?key=<web API key>`) and call
  the same `approve` endpoint on the `hsos-api` URL.
- Admin: `https://<project>.web.app/admin.html`, or the `activate` endpoint under `/api/admin`.
- After activation, any worker instance loads the new version before running a session that
  needs it. (This relies on the worker fix from commit `0c643ca`, found in staging on
  2026-11-07, see [OPERATIONS.md](OPERATIONS.md) §5; without it, runs in the first ~30 s after
  an activation could fail.)

## 7. Content checklist (before submitting)

- [ ] Every question and rubric has `source` (type, author, license) and `review` fields.
- [ ] Content is original or clearly licensed. **No College Board questions** or commercial
      test-prep questions (including photos or transcriptions of them) without explicit permission.
- [ ] No real student names, answers, essays, or photos of student work.
- [ ] Every answer key checked independently; each item has exactly one defensible answer.
- [ ] Each rubric criterion is tagged with the skill its item tests.
- [ ] No score predictions or "estimated SAT score" wording anywhere.
- [ ] Skill IDs and the question IDs that live tasks use are unchanged from the previous version.
- [ ] Before real students: a named content reviewer sets each item's `review.status` to
      `reviewed` (production withholds draft content).

## 8. What this example does not cover

These need platform abilities first; a package cannot add them:

- Timed, full-length tests with adaptive module routing.
- In-course follow-up rules (repeated errors → diagnostic → practice), Step 24.2.
- Course requirements such as official test dates.
- Importing questions from PDFs or photos. Today the package file is written directly; an import
  flow in the author portal (upload → proposed items → author confirms each one) is planned as
  Step 39 in [STEP_BY_STEP_PLAN.md](STEP_BY_STEP_PLAN.md).
- Figures and formatted math in items (prompts and choices are plain text).
- Building a package by conversation with an authoring agent: planned as Step 40 in
  [STEP_BY_STEP_PLAN.md](STEP_BY_STEP_PLAN.md).
- Publishing an approved version to every student is a platform admin's job, not the author's:
  `web/admin.html`. There are no per-student grants.
- A review assistant agent that prepares findings for the reviewer (the reviewer still decides);
  its workflow and skills are to be defined by reviewers: Step 43.
- Student-produced-response (grid-in) math items. The platform can already grade free responses
  with `rubric-assessment` + `math-verify` (see Calculus BC), but this example uses multiple
  choice only.
