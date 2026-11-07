# Course package field reference (`course-package/v1`)

Every field a course package may contain, its limits, and the rules that connect fields. Field
names are case-sensitive; **fields not listed here are rejected**. See [README.md](README.md)
for the steps and [`templates/blank-package.json`](templates/blank-package.json) for a valid
starting point.

## ID formats

| Kind | Format | Example |
|---|---|---|
| Course ID | starts with a lowercase letter; lowercase letters, digits, `_`; 2–32 characters | `ap_biology` |
| Skill ID | `{courseId}` then one or more `.segment` parts (lowercase letters, digits, `-`) | `ap_biology.cells.membrane-transport` |
| Question ID, material ID | letters, digits, `_ - : .`; up to 128 characters | `q_bio_cells_001` |
| Rubric ID, criterion ID, case ID, workflow version | lowercase letters, digits, `-` only (**no underscores**) | `bio-cells-001`, `item-1` |
| Version (package) | `MAJOR.MINOR.PATCH` | `1.0.0` |

## Top level

| Field | Required | Limits | Notes |
|---|---|---|---|
| `schemaVersion` | yes | exactly `"course-package/v1"` | |
| `manifest` | yes | | Course identity and settings |
| `systemPrompt` | yes | 1–8,000 characters | The tutor's instructions |
| `skills` | yes | 1–200 | |
| `rubrics` | yes | 1–500 | |
| `questions` | yes | 1–500 | |
| `materials` | no | up to 200 | Only for writing from sources |
| `starterTasks` | no | up to 20 | Sets a student gets on first joining the course |
| `practiceSequence` | no | up to 200 | Sets offered next, in order (see below) |
| `evaluationSet` | yes | 1–200 cases | |

The whole file may be at most **900 KB**.

## `manifest`

| Field | Required | Allowed values / limits | Notes |
|---|---|---|---|
| `courseId` | yes | see ID formats | Cannot be a course another organization owns, or a platform course |
| `version` | yes | `MAJOR.MINOR.PATCH` | Must be higher than every version you have submitted before |
| `name` | yes | 1–120 characters | Shown in the catalog |
| `description` | yes | 1–500 characters | Shown in the catalog |
| `category` | yes | `AP`, `SAT`, `ADMISSIONS` | A catalog label only; it gives no access |
| `agentType` | yes | `AP_BASE`, `DSAT`, `ADMISSIONS` | The kind of study agent; use `AP_BASE` for AP-style courses, `DSAT` for SAT-style practice |
| `supportedTaskTypes` | yes | one or more of `PRACTICE`, `SOCRATIC_STUDY`, `FRQ_PRACTICE`, `DIAGNOSTIC`, `REINFORCEMENT` | Starter tasks must use one of these |
| `supportedModes` | yes | one or more of `ADAPTIVE`, `EXAM_CRUNCH`, `GPA_SYNC` | Starter tasks must use one of these |
| `abilities` | yes | from `socratic-guidance`, `choice-scoring`, `rubric-assessment`, `source-analysis` | See "Abilities and content must match" |
| `tools` | no | from `math-verify`, `content-retrieval` | `math-verify` is required if any question has an `answerCheck` |
| `modelTier` | yes | `fast`, `balanced`, `strong` | How capable a model the tutor uses |
| `contextBudgetTokens` | no | 1,000–200,000 (default 8,000) | How much course context the tutor sees per reply |
| `workflowVersion` | yes | rubric-ID format | A label recorded with every result, e.g. `bio-practice-v1` |
| `publisher.name` | yes | 1–120 characters | Display name; ownership comes from your author account |
| `license` | yes | 1–300 characters | The package's overall content license |

## `skills[]`

| Field | Required | Notes |
|---|---|---|
| `skillId` | yes | Starts with `{courseId}.`; unique |
| `name` | yes | Shown to students |
| `description` | yes | What a student with this skill can do |

## `questions[]`

A question is one of three kinds, decided by which fields it has.

| Field | Required | Limits / values | Notes |
|---|---|---|---|
| `questionId` | yes | question-ID format; unique | Keep it stable across versions |
| `version` | yes | any text, e.g. `"1"` | Change it when you change the question |
| `courseId` | yes | your course ID | |
| `topic` | yes | text | Shown as the set's title |
| `skillIds` | yes | 1 or more known skills | All skills the question touches |
| `difficulty` | yes | `easy`, `medium`, `hard` | |
| `prompt` | yes | text | Instructions shown above the items |
| `expectedAnswer` | yes | text | For reviewers (never shown to students), e.g. `"1: B, 2: D"` |
| `rubricRef` | yes | `{"rubricId", "version"}` | Must match a rubric in the package |
| `items` | multiple-choice only | 1–10 items | See below |
| `answerCheck` | free response only, optional | see below | Lets `math-verify` check a final answer |
| `sourceMaterialIds` | source-based writing only | 1–8 material IDs | Each must be a material in this package |
| `source` | yes | see "Source and review" | |
| `review` | yes | see "Source and review" | |

**Kinds of question:**

| Kind | Has | Ability needed | Graded by |
|---|---|---|---|
| Multiple-choice set | `items` | `choice-scoring` | Your answer key, instantly (no AI) |
| Free response | neither `items` nor `sourceMaterialIds` | `rubric-assessment` | AI grader against your rubric |
| Writing from sources | `sourceMaterialIds` | `source-analysis` | AI grader; may cite only the listed materials |

A question cannot have both `items` and `answerCheck`, or both `items` and `sourceMaterialIds`.

### `questions[].items[]` (multiple-choice sets)

| Field | Required | Limits | Notes |
|---|---|---|---|
| `itemId` | yes | `"1"`–`"99"`; unique in the set | Students answer by this number |
| `prompt` | yes | text | Passage (if any), a blank line, then the question |
| `choices` | yes | 2–4 of `{"key": "A"–"D", "text"}`; unique keys | |
| `answerKey` | yes | one of the choice keys | Never sent to students |
| `criterionId` | yes | a criterion in the set's rubric | |

Each criterion of the rubric must be used by exactly one item, and every item must point to a
criterion: the item list and the criteria list must match one to one.

**How students answer:** one line per item, such as `1: A`, `2) c`, or `item 3 - B`. The answer
must cover every item in the set. An answer that skips an item, repeats one, or cannot be read is
recorded as `insufficient_evidence`: the student sees limited feedback, and no progress changes.
An item earns its criterion's `maxPoints` when correct, 0 otherwise.

### `questions[].answerCheck` (free response, optional)

| Field | Notes |
|---|---|
| `tool` | `"math-verify"` (also list it in `manifest.tools`) |
| `criterionId` | The rubric criterion for the final answer |
| `expression` | The correct final answer in SymPy syntax, e.g. `"-2*x*y/(x**2 + 3*y**2)"` (up to 200 characters) |
| `variables` | Single lowercase letters used in the expression, e.g. `["x", "y"]` |

## `rubrics[]`

| Field | Required | Notes |
|---|---|---|
| `rubricId` | yes | rubric-ID format (no underscores) |
| `version` | yes | Matches the question's `rubricRef.version` |
| `courseId` | yes | Your course ID |
| `criteria` | yes | 1 or more; `criterionId` unique within the rubric |
| `source`, `review` | yes | See "Source and review" |

### `rubrics[].criteria[]`

| Field | Required | Limits | Notes |
|---|---|---|---|
| `criterionId` | yes | rubric-ID format | For multiple choice, conventionally `item-1`, `item-2`, … |
| `description` | yes | text | |
| `maxPoints` | yes | 1–10 | |
| `evidenceRequirements` | yes | 1 or more lines | What earns the points, e.g. `"Selects choice B for item 1"` |
| `skillIds` | yes | 1 or more known skills | The skills this criterion is evidence for. Tag the skill the item really tests |

## `materials[]` (writing from sources only)

| Field | Required | Limits |
|---|---|---|
| `materialId` | yes | question-ID format; unique |
| `version` | yes | text |
| `courseId` | yes | your course ID |
| `skillIds` | yes | 1 or more known skills |
| `title` | yes | text |
| `text` | yes | 1–4,000 characters |
| `source`, `review` | yes | see below |

Materials are shown to the student next to the question and given to the grader as reference
documents. Multiple-choice sets cannot use materials; put short passages in the item prompt.

## Source and review (questions, rubrics, materials)

| Field | Values | Rules |
|---|---|---|
| `source.type` | `original`, `licensed` | Material whose author is the College Board must be `licensed` |
| `source.author` | text | Who wrote it |
| `source.license` | text | The license under which you use it |
| `review.status` | `draft`, `reviewed` | `draft` has `reviewer: null`; `reviewed` needs `reviewer` and `reviewedAt` (`YYYY-MM-DD`) |

The platform's production service withholds `draft` content from students; have a content
reviewer sign off each item before launch.

## `starterTasks[]`

| Field | Required | Limits | Notes |
|---|---|---|---|
| `questionId` | yes | a question in the package; one task per question | |
| `taskType` | yes | listed in `manifest.supportedTaskTypes` | |
| `mode` | yes | listed in `manifest.supportedModes` | |
| `title` | yes | 1–120 characters | Shown in the student's task list |
| `durationMin` | yes | 5–120 | Estimated minutes |

## `practiceSequence[]` (the order of further practice)

Same fields and rules as `starterTasks[]`. Your course's **practice order** is the starter tasks
followed by the practice sequence; each question may appear in it only once (`duplicate`).

How the platform uses it: whenever a student has fewer than **2 unfinished sets** in your course
(for example, right after completing one, or at the daily planning pass), it gives them the next
sets in this order that they have never had, until they have 2 again. A set a student completed
or skipped is never offered again. When you publish a new version, students who were already
enrolled receive its sets that they have not had yet, in the new order. With no practice
sequence, students get only the starter tasks.

Tip: alternate topics or sections (as the Digital SAT example alternates Reading and Writing
with Math), and put any sets you add in a new version where you want students to meet them.

## `evaluationSet[]`

| Field | Required | Limits | Notes |
|---|---|---|---|
| `caseId` | yes | rubric-ID format; unique | |
| `questionId` | yes | a question in the package | |
| `answerText` | yes | 1–4,000 characters | A sample student answer |
| `expectedStatus` | no | `accepted` (default), `insufficient_evidence` | |
| `expectedEarned` | for `accepted` | `{criterionId: points}` listing **every** criterion of the question's rubric, each within 0–`maxPoints` | Empty `{}` for `insufficient_evidence` |

Cases on multiple-choice sets run automatically when you upload, and all must pass before
approval. Cases on free-response or source-based questions need AI grading; the reviewer runs
them and confirms the results at approval.

## Abilities and content must match

| If `abilities` includes | The package must contain |
|---|---|
| `choice-scoring` | at least one multiple-choice set |
| `rubric-assessment` | at least one free-response question |
| `source-analysis` | at least one question with `sourceMaterialIds` |

And the other way round: every multiple-choice set needs `choice-scoring`, every free-response
question needs `rubric-assessment`, and every source-based question needs `source-analysis`.
`socratic-guidance` (the hint tutor) can be added to any course.

## The tutor's instructions (`systemPrompt`)

Plain text (Markdown is fine). Placeholders filled in by the platform: `{{studentName}}`,
`{{currentMode}}`, `{{masteryContext}}`. Any other `{{...}}` is an error. The instructions guide
teaching style; they cannot change how answers are graded, reveal answer keys, or give the tutor
new tools.

## Validation errors

Each error has a **path** (where), a **code** (what), and a message. Common codes:

| Code | Meaning | Usual fix |
|---|---|---|
| `missing` | A required field is absent | Add the field named in the path |
| `extra_forbidden` | A field that is not part of the format | Remove it, or fix its spelling or capitalization |
| `string_pattern_mismatch` | An ID or version in the wrong format | Check "ID formats" (often an `_` in a rubric or criterion ID) |
| `literal_error`, `enum` | A value not in the allowed list | Use one of the listed values |
| `string_too_long`, `too_long`, `too_short`, `less_than_equal`, `greater_than_equal` | A length, count, or number outside its limits | See the limits above |
| `too_large` | File over 900 KB | Split the course or shorten passages |
| `duplicate` | The same ID used twice | Make IDs unique |
| `skill_prefix` | A skill ID not starting with `{courseId}.` | Rename the skill |
| `unknown_skill` | A skill ID not in `skills` | Add the skill, or fix the reference |
| `course_mismatch` | A `courseId` different from the manifest's | Use your course ID everywhere |
| `missing_rubric` | `rubricRef` names no rubric in the package | Fix the ID or version, or add the rubric |
| `items_criteria_mismatch` | Items and rubric criteria do not match one to one | One criterion per item, same IDs |
| `unknown_criterion` | An `answerCheck` criterion not in the rubric | Fix the criterion ID |
| `ability_not_selected` | Content that needs an ability you did not list | Add the ability to `manifest.abilities` |
| `ability_without_data` | An ability listed with no content that uses it | Remove the ability, or add the content |
| `tool_not_selected` | `answerCheck` without `math-verify` in `manifest.tools` | Add the tool |
| `unknown_ability`, `unknown_tool` | Not in the platform catalog | Use a listed ability or tool |
| `unknown_material` | `sourceMaterialIds` names no material | Add the material, or fix the ID |
| `unknown_question` | A starter task or test case names no question | Fix the question ID |
| `unsupported_task_type`, `unsupported_mode` | A starter task uses a type or mode the manifest does not list | Add it to the manifest, or change the task |
| `criteria_mismatch` | `expectedEarned` does not list exactly the rubric's criteria | List every criterion, and nothing else |
| `out_of_range` | Points outside 0–`maxPoints` | Fix the points |
| `unknown_template_variable` | A `{{...}}` other than the three allowed | Remove it |
| `value_error` | A rule inside one object failed (for example, an `answerKey` that is not one of its choices, or `reviewed` content without a reviewer) | Read the message |

If the file's structure has errors, the reference checks (unknown skills, rubrics, and so on)
are reported after you fix them and upload again.

**Evaluation failures** list the `caseId`s whose result differed from what you expected: check
the answer key, the item numbers in `answerText`, and `expectedEarned`.
