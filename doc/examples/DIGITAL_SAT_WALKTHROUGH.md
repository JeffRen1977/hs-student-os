# Digital SAT: author → reviewer → admin → student

Current workflow, revised 2026-11-07. This describes the local implementation; it is not
an assertion that the revised publication policy has been deployed or run on staging.
Earlier staging runs used individual student grants; that policy is superseded.

| Role | Synthetic account | Responsibility | Page |
|---|---|---|---|
| Author | `author_hsos` | Create, validate, preview and submit a package | `/author.html` |
| Reviewer | `reviewer_platform` | Check correctness, sources, rubrics and evaluations; approve or reject | `/review.html` |
| Admin | `admin_platform` | Publish an approved course to the catalog for everyone; retire courses | `/admin.html` |
| Student | `stu_beth` | Choose a published course, enroll and learn | `/` |

## 1. The author creates the course package

Use [Digital SAT 2.0.1](../../server/content/authored/dsat/package-2.0.1.json), or begin with
[the author-kit template](../author-kit/templates/blank-package.json).

The Digital SAT example contains 29 skills, 12 practice sets with 52 multiple-choice items,
answer keys and item-to-skill rubric mappings, tutor instructions, two starter sets, ten
subsequent sets in `practiceSequence`, and 36 deterministic scoring evaluation cases.
The selected abilities are `socratic-guidance` and `choice-scoring`.

Authors independently check keys and record sources and licenses. Automatic scoring tests
verify the behavior of the supplied keys, not whether those keys are factually correct.

## 2. The author uploads, previews and submits

Sign in at `/author.html` as `author_hsos`. Upload the JSON, inspect validation and evaluation
results, and inspect the student preview. Fix and replace a draft as needed. Submit when
ready. Submitted versions are immutable; corrections require a new version.

The student preview excludes answer keys, rubrics, internal tutor instructions and evaluation
answers. Authors cannot approve or publish their own content.

## 3. The reviewer approves content quality

At `/review.html`, sign in as `reviewer_platform` and open the submitted version. Inspect:

- Every question's wording, answer key, distractors and skill mapping.
- Original authorship or appropriate licensing.
- Validation and evaluation results; any model-graded cases require explicit attestation.
- Student preview and changes against the active version, especially removed IDs.

Reject with notes, or approve with the required attestations. Approval records the reviewer's
identity and decision and sends the version to the admin publication queue. It does not make
the course available to students. Reviewers cannot activate or retire courses.

The per-item checklist is local to the reviewer's browser, not durable review evidence.
Item-level reviewed-content requirements still apply in production. This example's draft
content needs named content review before real student use.

## 4. The admin publishes the course for everyone

At `/admin.html`, sign in as `admin_platform`. The page lists reviewed versions, including
Digital SAT 2.0.1 after approval. Inspect the review decision, validator report and history.
Select **Publish to catalog**, then confirm.

The server accepts publication only for an approved version. The transition to `active`,
active-version pointer, audit history and idempotency record commit together. The admin's
identity is recorded separately from the reviewer's identity.

**No student lookup, individual grant or cohort grant is needed.** Every student can now
choose Digital SAT from the catalog. Publication does not enroll anyone automatically.
A previous active version becomes superseded; open sessions retain their pinned version.

API: `POST /api/admin/packages/dsat/versions/2.0.1/activate`, body `{}`, admin token and
`Idempotency-Key` required.

## 5. Beth enrolls

Beth signs in at `/`, opens the catalog and selects **Digital SAT → Add course**. She can do
this even if her legacy entitlement lists do not contain `dsat`.

Enrollment creates two starter tasks, placed according to available study time:

- Reading and Writing: information and ideas, set 1 (20 minutes).
- Math: algebra, set 1 (20 minutes).

Enrolling and unenrolling are Beth's choices. Another student's tasks and learning records
remain private even though both students can enroll in the same course.

## 6. Beth studies and receives feedback

Beth opens a practice set, reads passages and questions, selects choices, and can ask for
Socratic hints. Hints are recorded. The tutor receives student-visible item content without
answer keys; scoring uses the server's keys, without a model call.

On submission, feedback identifies correct and incorrect items. Skill evidence follows the
rubric mappings. Hint-assisted success is distinguished from independent evidence; unreadable
or incomplete submissions produce insufficient evidence and do not update mastery. There are
no SAT score predictions.

Beth completes the session. The platform offers the next unassigned sets in the author's
practice order, maintaining up to two unfinished sets until the sequence runs out. The weekly
planner fits tasks around her available time and explains placements.

Today this order does not select remediation based on mistakes. Targeted follow-up, delayed
review, full-length timed tests, and figures/formatted math remain future work.

## 7. The admin retires a course when necessary

An admin can retire a published course with a reason. This stops new enrollments and new
learning activity for everyone while preserving existing records for reading. Authors and
reviewers cannot retire courses. A queued learning run rechecks availability and enrollment.

## 8. The author observes aggregate results

The author portal provides course aggregates, suppressed below the minimum cohort threshold
of five students with work. Authors never see Beth's individual answers, chats or mastery.

## Try locally

In separate terminals:

```bash
make server-memory
```

```bash
make web
```

1. Open <http://localhost:8000/author.html>, sign in as `author_hsos`, upload the 2.0.1 file,
   validate, preview and submit.
2. Open <http://localhost:8000/review.html>, sign in as `reviewer_platform`, review and approve.
3. Open <http://localhost:8000/admin.html>, sign in as `admin_platform`, publish 2.0.1.
4. Open <http://localhost:8000/>, sign in as `stu_beth`, enroll in Digital SAT and complete a set.

The local fixture starts with Digital SAT 1.0.0 active for demonstration. The 2.0.1 upgrade
exercises the revised gate. Mock mode produces synthetic tutor replies; choice scoring works
without a real model. In-memory state resets when the API stops.
