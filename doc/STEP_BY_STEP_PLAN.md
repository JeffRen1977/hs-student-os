# High School Student OS — Step-by-Step Implementation Plan v4.0

Updated: 2026-10-31. Python/FastAPI backend. This plan builds on [the architecture recommendations](STUDENT_OS_ARCHITECTURE_RECOMMENDATIONS.md) and implements [API v0.3](API.md), [backend v0.4](BACKEND.md), and [the milestone plan](IMPLEMENTATION_PLAN.md). Checked boxes mark sub-tasks implemented in the working tree; each step's **Status** line records what was actually verified.

The first product slice is **Calculus practice → supported assessment → saved evidence → SAT prerequisite diagnostic → justified follow-up → an explained plan**. M0–M4 deliver the pilot; M5 contains independently selectable extensions.

## Current state

### Implementation status (as of 2026-10-31)

| Milestone | Steps | Status |
|---|---|---|
| M0 Contracts and baseline | 1–7 | **Implemented; verification partial**: emulator tests not yet run, content not yet human-reviewed |
| M1 Reliable foundation | 8–15 | **Implemented; verified over the in-memory backend**: Firestore-emulator run pending (no Java), Cloud Tasks/OIDC verified in staging (Step 30) |
| M2 Calculus learning loop | 16–21 | Not started |
| M3 Validated SAT transfer | 22–27 | Not started |
| M4 Proactive planning and pilot | 28–33 | Not started |
| M5 Optional expansion | 34–38 | Not started |

Last local verification (`make check`, after M1): ruff lint/format clean, `mypy app/` (strict) clean, backend pytest **369 passed, 4 skipped** (all 4 are emulator tests, which skip without emulators), web `node --test` **19 passed**.

Open items before M0 and M1 can be called complete:
- **Emulator verification (Steps 5, 9, 14, 15):** `make emulators` / `make test-emulator` have not been run on this machine (no Java runtime installed; Firebase emulators need Java 11+). `tests/emulator/test_seed_emulator.py` and `tests/emulator/test_firestore_flows.py` are written but currently skip. M1 transaction behaviour is proven only over the in-memory store until they run.
- **Content review (Steps 4, 7):** questions, rubrics, and evaluation cases are `draft`; prerequisite mappings are `candidate`. None has a named reviewer yet. Evaluation thresholds in `dimensions.json` are unset until a content reviewer sets them.

### Checkout contents

- `doc/` — architecture, API, backend design, competitive review, implementation plan (this file)
- `server/` — FastAPI skeleton (`/api/health`, error envelope, request IDs, environment config that rejects emulator hosts and mock providers in staging/production), Pydantic v2 schemas, domain types and repository protocols, content/fixture/evaluation registries, Firebase adapter, emulator seed script, synthetic fixtures, Calc BC content pack, evaluation baseline, and tests
- `Makefile` — `install`, `dev`, `server`, `server-memory`, `web`, `emulators`, `seed`, `typecheck`, `lint`, `format`, `test*`, `check`
- `web/` — vanilla JS frontend. The async `data-provider.js` (Bearer auth, Idempotency-Key, request states, event dedupe) is the new seam; `?demo=true` loads `web/fixtures/demo.json` (validated against backend schemas). Predictions show "unavailable", and Task/Session/Run are kept as separate state. `window.HSData` now holds display metadata only.
- M1: Firebase token auth → `ActorContext`; Firestore repositories on a `DocTxn` seam with an in-memory test backend; twin, course catalog/enrollment/agent, task, session, message/submission, and run routes; transactional command acceptance with idempotency and outbox; outbox dispatcher, local queue, Cloud Tasks adapter, a lease/fencing-token run worker with its own HTTP service, a stalled-run recovery scan, and a labeled synthetic executor
- Not built yet: LLM gateway, assessments/mastery, event feed/SSE, planner, frontend wired to the real API

Each step below is a reviewable change with verification criteria.

## Working rules

- Work only in the Student OS checkout. Preserve existing changes; do not delete unknown code.
- Do not use LOGIQ code, credentials, services, or API compatibility layers.
- Other education projects (`ai-college-advisor`, `sat-tutor-app`) are read-only references only. No shared JWT, databases, ports, or filesystem dependencies.
- Use Python 3.12+, FastAPI, Pydantic v2, Firebase Auth/Firestore emulators. JSON is fixture data, not production persistence.
- Each step is a reviewable change with relevant verification. Update contracts before implementation if a step reveals a necessary change.
- Tests must exercise meaningful contracts, authorization, recovery, or learning behavior.

---

## M0 — Contracts and Baseline (Steps 1–7)

### Step 1 — Initialize the project and Python backend skeleton

**Goal:** Establish a runnable, type-checked backend project from scratch.

- [x] 1.1 Create `server/pyproject.toml` with Python 3.12+ requirement, dependencies: fastapi, uvicorn, pydantic v2, firebase-admin, google-cloud-firestore, google-cloud-tasks, anthropic; dev dependencies: pytest, pytest-asyncio, httpx (for TestClient), mypy, ruff
- [x] 1.2 Create the directory structure:
  ```
  server/
    app/
      __init__.py
      main.py         # FastAPI application entry point
      api/            # FastAPI routers, auth dependencies, request/response schemas
      domain/         # twin, tasks, sessions, runs, assessments, planner
      workers/        # run worker, outbox dispatcher, consumers, scheduler
      adapters/       # firestore, auth, queue, storage, llm, tools
      registries/     # validated manifests and versions
      schemas/        # Pydantic v2 models for API/domain contracts
    content/          # reviewed packs, questions, rubrics, mappings
    fixtures/         # synthetic data only
    tests/            # unit, contract, emulator, e2e, evaluation
  ```
- [x] 1.3 Implement a minimal FastAPI application (`app/main.py`) with:
  - Health route `GET /api/health` → `{ "status": "ok", "version": "0.1.0" }`
  - Pydantic error formatting
  - Environment config loader (via pydantic-settings) that rejects mock providers/emulator hosts in production mode
- [x] 1.4 Add development commands via `pyproject.toml` scripts or Makefile: `dev` (uvicorn --reload), `typecheck` (mypy), `lint` (ruff), `test` (pytest)
- [x] 1.5 Create `server/.env.example` with placeholder variable names (no real credentials)
- [x] 1.6 Create a root-level script or Makefile to run both server and web dev locally

**Verify:** `mypy app/` passes. `uvicorn app.main:app --reload` starts FastAPI and responds to `GET /api/health`. Production config rejects emulator hosts. All test commands exist (some may have zero tests).

**Status:** ✅ Done. `make typecheck`, `make lint`, and `make test` pass; `tests/contract/test_app.py` covers `/api/health`; `tests/unit/test_config.py` covers rejecting emulator hosts and mock providers in production.

---

### Step 2 — Define Pydantic models for core domain entities

**Goal:** Establish the API contract as Pydantic v2 models with validation before writing any handlers.

- [x] 2.1 Define `app/schemas/student.py` — Student, Profile, Goals, Preferences, Entitlements with field-level constraints (str max_length, int ge/le, Literal enums)
- [x] 2.2 Define `app/schemas/task.py` — Task with TaskStatus literal (`PLANNED`, `IN_PROGRESS`, `COMPLETED`, `SKIPPED`), required fields, reason structure
- [x] 2.3 Define `app/schemas/session.py` — Session with SessionStatus literal (`OPEN`, `COMPLETED`, `ABANDONED`), contextVersion, completion eligibility
- [x] 2.4 Define `app/schemas/run.py` — Run with RunStatus literal (`QUEUED`, `RUNNING`, `WAITING_INPUT`, `SUCCEEDED`, `FAILED`, `CANCELLED`), kind, inputRequest, result
- [x] 2.5 Define `app/schemas/submission.py` — immutable submission with questionId, questionVersion, answer, supersedesSubmissionId
- [x] 2.6 Define `app/schemas/assessment.py` — assessment with rubricResults, skillEvidence, hintUsage, uncertainty, provenance, status (`accepted`, `insufficient_evidence`)
- [x] 2.7 Define `app/schemas/event.py` — event with sequence, schemaVersion, type enum, causationId, typed payloads
- [x] 2.8 Define `app/schemas/error.py` — standard error envelope with code, message, requestId, retryable
- [x] 2.9 Define `app/schemas/common.py` — shared types: pagination (cursor/limit), idempotency key, If-Match version, ISO 8601 datetime, IANA timezone
- [x] 2.10 Write schema validation tests: valid examples parse; invalid inputs (client score fields, entitlement edits, forged assessment status, arbitrary event publication, malformed relationships, extra fields) fail via Pydantic `model_config = ConfigDict(extra="forbid")`

**Verify:** All Pydantic models compile. Valid API examples from API.md pass validation. Forbidden client mutations (scoreDelta, entitlement writes, direct mastery writes, event POST) are rejected by Pydantic.

**Status:** ✅ Done. `tests/contract/test_schemas.py` validates the API.md examples (`tests/contract/api_examples.py`) and rejects forbidden client fields.

---

### Step 3 — Define Python domain types and repository protocols

**Goal:** Define typed domain models and repository interfaces using dataclasses, enums, and Protocol classes.

- [x] 3.1 Create `app/domain/types/student.py` — Student, Profile, Goals, Preferences, Entitlements, MasterySummary, PredictionSummary (as dataclasses or Pydantic BaseModel)
- [x] 3.2 Create `app/domain/types/task.py` — Task, TaskStatus (StrEnum), TaskReason, TaskPatch
- [x] 3.3 Create `app/domain/types/session.py` — Session, SessionStatus (StrEnum), CompletionEligibility
- [x] 3.4 Create `app/domain/types/run.py` — Run, RunStatus (StrEnum), RunKind, InputRequest, RunResult
- [x] 3.5 Create `app/domain/types/submission.py` — Submission, SubmissionInput
- [x] 3.6 Create `app/domain/types/assessment.py` — Assessment, AssessmentStatus, RubricResult, SkillEvidence, HintUsage, Uncertainty, Provenance
- [x] 3.7 Create `app/domain/types/event.py` — DomainEvent, EventType (StrEnum), typed event payloads
- [x] 3.8 Create `app/domain/types/actor.py` — ActorContext (actor_id, student_id, role, permissions scope)
- [x] 3.9 Create `app/domain/types/course.py` — CourseEnrollment, EnrollmentStatus, CourseCatalogEntry (availability + entitlement status for this student), AgentConfig (skills, modes, description)
- [x] 3.10 Create `app/domain/types/common.py` — PaginatedResponse[T] (generic), IdempotencyRecord, VersionedResource
- [x] 3.11 Create repository protocols in `app/domain/ports/` — StudentRepository, TaskRepository, SessionRepository, RunRepository, SubmissionRepository, AssessmentRepository, EventRepository, IdempotencyRepository, CourseRepository (using `typing.Protocol`)

**Verify:** `mypy app/` passes. Types match the Pydantic schemas from Step 2. Repository protocols use ActorContext for all operations.

**Status:** ✅ Done. Also added `app/domain/types/transitions.py` (state-machine transition tables). `tests/contract/test_schema_domain_parity.py` checks that types and schemas match; `tests/unit/test_domain_types.py` covers transitions.

---

### Step 4 — Seed two synthetic students and versioned content

**Goal:** Create fixture data for two isolated test students and the first content pack.

- [x] 4.1 Create `fixtures/students/student-a.json` — studentId `stu_alex`, grade 11, timezone `America/Los_Angeles`, calc_bc selected, prediction `unavailable`
- [x] 4.2 Create `fixtures/students/student-b.json` — studentId `stu_beth`, grade 10, timezone `America/New_York`, calc_bc selected, different preferences
- [x] 4.3 Create `fixtures/entitlements/` — student A has `calc_bc` + `dsat`; student B has only `calc_bc`
- [x] 4.4 Create `content/packs/calc_bc/manifest.json` — courseId, name, version `1.0.0`, availability `active`, supported task types, supported modes
- [x] 4.5 Create `content/packs/calc_bc/questions/` — 5–8 original/reusable Calculus questions with:
  - questionId, version, topic, difficulty, prompt text, expected answer, rubric reference
- [x] 4.6 Create `content/packs/calc_bc/rubrics/` — rubric definitions with criterionId, description, maxPoints, evidence requirements
- [x] 4.7 Create `content/packs/apush/manifest.json` — availability `planned` (cannot open sessions)
- [x] 4.8 Create `content/packs/physics_c/manifest.json` — availability `planned`
- [x] 4.9 Create `content/mappings/calc-to-sat-prerequisites.json` — versioned mapping candidates with source AP skill, target SAT skill, conditions, counterexamples
- [x] 4.10 Write fixture validation tests: all fixtures pass their JSON schemas; student IDs are isolated; planned packs are recognized but cannot be treated as active

**Verify:** Fixture schemas pass validation. No real student information. Exam predictions are `unavailable`. Entitlements are separate from selectedCourses. Planned packs are distinct from active packs.

**Status:** ✅ Implemented, tests pass (`tests/unit/test_fixtures.py`, `tests/unit/test_content.py`). Also added a planned `dsat` pack manifest with `skills.json`, plus `calc_bc/skills.json` and `system_prompt.md`. ⚠️ Questions and rubrics are `draft` and mappings are `candidate`, with no named reviewer yet. They need content review before Step 17 relies on them.

---

### Step 5 — Set up Firebase emulators for local development

**Goal:** Configure Firebase Auth and Firestore emulators so all subsequent backend work uses real transaction semantics.

- [x] 5.1 Create `server/firebase.json` with Auth and Firestore emulator configuration (ports, project ID)
- [x] 5.2 Create `server/.firebaserc` with local dev project alias
- [x] 5.3 Create a seed script (`server/scripts/seed_emulator.py`) that:
  - Creates Auth emulator users for student A and B with known UIDs
  - Writes fixture data into Firestore emulator collections following the data model from BACKEND.md §3
- [x] 5.4 Create `app/adapters/firebase.py` — Firebase Admin SDK initialization with explicit emulator detection
- [x] 5.5 Add Makefile target or script `make emulators` to launch Firebase emulators
- [x] 5.6 Add Makefile target or script `make seed` to run the seed script against running emulators
- [x] 5.7 Verify that production startup rejects emulator environment variables

**Verify:** `make emulators` launches Auth + Firestore. `make seed` populates two students. Firestore data is queryable. Production config check rejects `FIRESTORE_EMULATOR_HOST`.

**Status:** 🟡 Implemented, not verified against live emulators. `firebase.json`, `.firebaserc`, `firestore.rules`, the seed script, and the Makefile targets exist; the unit tests (`test_firebase_adapter.py`, `test_config.py`) pass. `tests/emulator/test_seed_emulator.py` skips because no Java runtime is installed. Next: install Java 11+ and run `make test-emulator`.

---

### Step 6 — Update the frontend data provider contract

**Goal:** Prepare the web frontend to consume the new API contract without breaking the existing demo.

- [x] 6.1 Document the current `window.HSData` interface: `getPacks()`, `getSessions()`, `getStudent()`, `getEvents()`
- [x] 6.2 Define new async data-provider signatures in `web/js/data-provider.js`:
  - `fetchTwin()`, `fetchEntitlements()`, `fetchPacks()`, `fetchTasks()`, `fetchSession(sessionId)`, `fetchRun(runId)`, `fetchEvents(afterSequence)`
- [x] 6.3 Add request states: `loading`, `error`, `success` — components must handle all three
- [x] 6.4 Add an explicit demo mode flag that uses fixtures only when `?demo=true` is set
  - API errors must never silently substitute demo data for real student data
- [x] 6.5 Map old data shapes to new API shapes:
  - Remove `predicted`/`target` score fields (replace with `unavailable`)
  - Separate Task from Session in the UI state
  - Show queued/running/waiting/failed Run states
- [x] 6.6 Add Idempotency-Key generation utility for retrying the same user action
- [x] 6.7 Add event deduplication by eventId/sequence in the client store

**Verify:** Demo mode works with `?demo=true`. Normal mode shows a clear "not connected" state. No prediction scores displayed. Component tests cover offline draft, API failure, and explicit demo states.

**Status:** ✅ Done. `web/tests/data-provider.test.js` (19 tests, `make test-web`) covers demo flag, NOT_CONNECTED with no demo fallback, offline drafts, idempotency keys, event dedupe, and Run states. Old interface documented in `web/README.md`. `server/tests/contract/test_web_demo_fixtures.py` validates `web/fixtures/demo.json` against backend schemas. Not yet checked by hand in a browser.

---

### Step 7 — Create the learning evaluation baseline

**Goal:** Establish reviewed test cases that will judge whether the AI grading is acceptable.

- [x] 7.1 Create `content/evaluation/calc_bc/` with annotated answer examples:
  - Correct answer (full marks, independent)
  - Incorrect answer (specific rubric failures)
  - Partially correct answer (some criteria met)
  - Assisted answer (correct after hints — must track hint dependency)
  - Ambiguous answer (evidence unclear, expected: `insufficient_evidence`)
  - Answer with insufficient work shown
- [x] 7.2 For each example, record: content source, permission/license, reviewer, rubric version, expected assessment output, expected skill evidence
- [x] 7.3 Create counterexamples for prerequisite mappings:
  - AP calc error that does NOT imply a SAT prerequisite weakness (e.g., L'Hôpital-specific error)
  - AP calc error that DOES suggest a shared prerequisite issue (e.g., basic algebraic manipulation)
- [x] 7.4 Define evaluation dimensions: rubric accuracy, evidence quality, false acceptance rate, false insufficient rate, hint-dependency tracking, feedback usefulness
- [x] 7.5 Create `content/evaluation/report-template.md` — versioned evaluation report template with columns for each dimension, reviewer sign-off, and pass/fail thresholds (thresholds TBD by content reviewer, not inferred from examples)

**Verify:** Each evaluation case has a reviewable expected outcome with provenance. Counterexamples exist for prerequisite mappings. This is a content gate — no model quality evaluation yet.

**Status:** 🟡 Structure done, review pending. 6 Calc BC cases, 4 prerequisite cases (2 counterexamples), `dimensions.json` (7 dimensions), and `report-template.md` are in `server/content/evaluation/`; `tests/unit/test_evaluation_content.py` passes. The content gate stays open until a reviewer signs off each case and sets the thresholds.

---

## M1 — Reliable Foundation (Steps 8–15)

### Step 8 — Implement authentication middleware and ActorContext

**Goal:** Every API request is authenticated; every domain operation knows who is asking.

- [x] 8.1 Create `app/adapters/auth.py` — Firebase Admin SDK ID token verification:
  - Validate issuer, audience, signature, expiry
  - Extract `sub` (UID) from verified token
  - Map UID to stable `student_id` via Firestore lookup (or create mapping on first login)
- [x] 8.2 Create `app/api/dependencies/auth.py` — FastAPI dependency (Depends):
  - Extract `Authorization: Bearer <token>` header
  - Reject missing/malformed tokens with 401
  - Reject expired tokens with 401
  - Reject wrong audience with 401
  - Build ActorContext and return it as an injected dependency
- [x] 8.3 Configure explicit Auth emulator usage in local development
- [x] 8.4 Reject `X-User-Email` header and body-provided studentId — identity comes only from verified tokens
- [x] 8.5 Create service/admin ActorContext for internal workers (separate from student tokens)
- [x] 8.6 Write auth tests:
  - Valid emulator token → accepted with correct studentId
  - Expired token → 401
  - Wrong audience → 401
  - Missing token → 401
  - Student B's token cannot access student A's resources

**Verify:** Auth emulator tokens work locally. Production config rejects emulator tokens. No shared secret or runtime dependency on reference products.

**Status:** ✅ Done (offline). `tests/unit/test_auth.py` and `tests/contract/test_auth_routes.py` run real `firebase_admin` verification in emulator mode: valid → correct studentId; expired, future-iat, wrong audience/issuer, malformed → 401; without emulator mode unsigned tokens are rejected; `X-User-Email`/`studentId` → 400; unprovisioned uid → 403; B → A resources → 404. Finding: in emulator mode the SDK skips expiry checks, so `app/adapters/auth.py` re-checks exp/iat/aud/iss itself. Not yet tried against a running Auth emulator.

---

### Step 9 — Implement Firestore repositories for Twin and profile

**Goal:** Students can read their profile and update allowed fields, with isolation enforced.

- [x] 9.1 Create `app/adapters/firestore/student_repository.py` implementing `StudentRepository` protocol:
  - `getTwin(actor)` — returns bounded summary with profile, goals, preferences, masterySummary, predictionSummary, latestEventSequence
  - `patchProfile(actor, patch, expectedVersion)` — field-level allowlist, optimistic concurrency with version check
  - `getEntitlements(actor)` — admin-set access rights
- [x] 9.2 Enforce per-student isolation: all queries filter by `actor.studentId`; cross-student requests return 404
- [x] 9.3 Implement field-level patch allowlist:
  - Allowed: displayName, grade, school, targetMajor, targetSchools, satTarget, apTargets, timezone, weeklyAvailableMinutes, selectedCourses, notifications
  - Forbidden: studentId, entitlements, mastery, assessments, predictionSummary, version
- [x] 9.4 Implement optimistic concurrency: `If-Match` version check in transactions; version conflict returns 409; missing If-Match returns 428
- [x] 9.5 Store histories in subcollections (not an unbounded Twin document)
- [x] 9.6 Write repository tests against Firestore emulator:
  - Two-student isolation (A cannot read B)
  - Concurrent version conflict detection
  - Unknown/forbidden field rejection
  - Profile preferences don't grant access (selecting a course ≠ entitlement)
  - Restart app against retained emulator data → same state

**Verify:** Isolation enforced. Version conflicts detected. Forbidden fields rejected. Data survives restart.

**Status:** 🟡 Implemented; verified over the in-memory backend. Repositories live in `app/adapters/firestore/` on a `DocTxn` seam (Firestore SDK in production, in-memory store for tests and Java-free local runs). `tests/contract/test_twin_routes.py` covers isolation, 409/428, forbidden fields, and preferences ≠ entitlements, plus restart over a retained store. Emulator run pending: `tests/emulator/test_firestore_flows.py` is written but skips (no Java on this machine).

---

### Step 10 — Implement Twin, Entitlements, and Course Catalog API routes

**Goal:** Wire up the REST endpoints for reading/patching student data and browsing available courses.

- [x] 10.1 `GET /api/twin` — returns bounded summary with ETag (version)
- [x] 10.2 `PATCH /api/twin` — validates patch against allowlist and schema, requires `If-Match`, returns updated twin
- [x] 10.3 `GET /api/me/entitlements` — returns backend-managed entitlements
- [x] 10.4 `GET /api/courses/catalog` — returns all packs with per-student availability status:
  - `active` + entitled → `available` (student can enroll)
  - `active` + not entitled → `locked` (needs access grant)
  - `planned` → `coming_soon` (cannot enroll)
  - Each entry includes: courseId, name, description, icon, availability, agent skills summary
- [x] 10.5 `GET /api/courses/:courseId` — single course detail; 404 for unknown courseId
- [x] 10.6 Wire FastAPI route response_model and request body validation using Pydantic models from Step 2
- [x] 10.7 Write route tests using httpx.AsyncClient with FastAPI TestClient (no external server needed):
  - GET twin returns correct shape with ETag
  - PATCH with valid fields and correct version → success
  - PATCH with forbidden field → 400
  - PATCH with stale version → 409
  - PATCH without If-Match → 428
  - Entitlements are read-only for students
  - Catalog returns correct availability per student entitlements
  - Planned course shows `coming_soon`

**Verify:** All routes respond correctly. Schema validation catches bad input. Catalog reflects entitlement status per student.

**Status:** ✅ Done. Routes in `app/api/routes/twin.py` and `courses.py`. Contract addition: catalog entries carry a derived `status` (`enrolled`/`available`/`locked`/`coming_soon`) and an `agent` summary (API.md §1.7, `web/fixtures/demo.json` updated). No icon field: icons stay frontend display metadata.

---

### Step 11 — Implement course enrollment and per-course agent activation

**Goal:** Students can enroll in available courses; each enrolled course activates a per-course agent in their workspace.

- [x] 11.1 Create `app/domain/course_service.py`:
  - `enrollCourse(actor, courseId, idempotencyKey)`:
    - Validate pack is `active` (not `planned`) → 409 `COURSE_NOT_AVAILABLE` if planned
    - Validate student has entitlement → 403 `COURSE_ACCESS_REQUIRED` if not entitled
    - Check not already enrolled → return existing enrollment if duplicate
    - In transaction: add to enrolledCourses, create `course.enrolled` event
  - `unenrollCourse(actor, courseId, idempotencyKey)`:
    - Check no OPEN sessions for this course → 409 `ACTIVE_SESSION_EXISTS` if open
    - In transaction: remove from enrolledCourses, create `course.unenrolled` event
    - Does NOT delete mastery/assessments/history (preserved for potential re-enrollment)
  - `getEnrolledCourses(actor)`:
    - Returns enrolled courses with agent config, mastery summary, active task count
  - `getCourseAgent(actor, courseId)`:
    - Returns agent config for the enrolled course: skills, modes, description, current session (if any)
    - 404 if not enrolled
- [x] 11.2 Create `app/adapters/firestore/course_repository.py`:
  - Store enrollments in `students/{studentId}/enrollments/{courseId}`
  - Query enrolled courses with agent config joined from SubjectPack registry
- [x] 11.3 Create API routes:
  - `POST /api/courses/enroll` + Idempotency-Key → `{ courseId }` → 201 enrollment
  - `POST /api/courses/unenroll` + Idempotency-Key → `{ courseId }` → 200
  - `GET /api/courses/enrolled` → list enrolled courses with agent summaries
  - `GET /api/courses/:courseId/agent` → agent config for enrolled course
- [x] 11.4 Create Firestore data for enrollment:
  ```
  students/{studentId}/enrollments/{courseId}
    enrolledAt: timestamp
    status: "active"
  ```
- [x] 11.5 Write tests:
  - Enroll in active + entitled course → success, course visible in workspace
  - Enroll in planned course → 409 `COURSE_NOT_AVAILABLE`
  - Enroll without entitlement → 403 `COURSE_ACCESS_REQUIRED`
  - Duplicate enrollment → idempotent, returns existing
  - Unenroll with no open sessions → success, course removed from workspace
  - Unenroll with open session → 409 `ACTIVE_SESSION_EXISTS`
  - GET enrolled → only enrolled courses returned
  - GET agent for non-enrolled course → 404
  - Cross-student: A cannot see B's enrollments
  - Unenroll + re-enroll → history preserved

**Verify:** Course enrollment lifecycle works. Entitlements enforced. Unenrollment is safe. Agent config only accessible for enrolled courses. Cross-student isolation confirmed.

**Status:** ✅ Done (in-memory backend). `tests/contract/test_course_routes.py`. Enroll returns 200 as API.md specifies (this plan said 201). The open-session conflict code is `OPEN_SESSION_EXISTS` per API.md (this plan said `ACTIVE_SESSION_EXISTS`). Unenroll/re-enroll keeps tasks and mastery. `POST /api/sessions/:id/abandon` (API.md §2.5) was added here so open sessions can be closed before unenrolling.

---

### Step 12 — Implement persistent Task lifecycle

**Goal:** Tasks can be created, read, listed, and updated with proper state transitions. Tasks are scoped to enrolled courses.

- [x] 12.1 Create `app/adapters/firestore/task_repository.py` implementing `TaskRepository` protocol:
  - `listTasks(actor, filters)` — by date, status, course; paginated; date uses student timezone
  - `getTask(actor, taskId)` — ownership check
  - `patchTask(actor, taskId, patch, expectedVersion)` — allowed: scheduledDate, studentLocked, status=SKIPPED (only from PLANNED)
- [x] 12.2 Create `app/domain/task_service.py`:
  - Validate course enrollment, availability, and entitlements before any Task interaction
  - Tasks belong to an enrolled course; unenrolled course tasks are not returned
  - Status transitions: PLANNED → IN_PROGRESS (via Session start), IN_PROGRESS → COMPLETED (via Session complete), PLANNED → SKIPPED
  - Student cannot directly PATCH to COMPLETED
- [x] 12.3 Create API routes:
  - `GET /api/tasks?date=...&status=...&courseId=...&cursor=...&limit=50`
  - `GET /api/tasks/:taskId`
  - `PATCH /api/tasks/:taskId` + `If-Match`
- [x] 12.4 Write tests:
  - List tasks filters by date, student timezone, and enrolled course
  - Tasks for unenrolled courses not returned
  - PATCH to SKIPPED only from PLANNED
  - PATCH to COMPLETED directly → rejected
  - Cross-student task → 404
  - Version conflict → 409

**Verify:** Tasks are persistent, isolated, course-scoped, and follow state machine rules. GET does not trigger replanning.

**Status:** ✅ Done (in-memory backend). `tests/contract/test_task_routes.py`. `date=today` is resolved in the student's timezone, and a test asserts that GETs write nothing. Patching a task in an unenrolled course returns 409 `COURSE_NOT_ENROLLED`, a new error code added to the contract. Firestore composite indexes are in `server/firestore.indexes.json` but are unvalidated until Step 30.

---

### Step 13 — Implement Session creation and lifecycle

**Goal:** Sessions tie to Tasks, enforce one-OPEN-per-Task, and support idempotent creation. Sessions are the per-course agent conversation boundary.

- [x] 13.1 Create `app/adapters/firestore/session_repository.py` implementing `SessionRepository` protocol
- [x] 13.2 Create `app/domain/session_service.py`:
  - `createSession(actor, taskId, idempotencyKey)`:
    - Derive course/agent/mode from stored Task (not client input)
    - Validate course enrollment, availability, and entitlement
    - One OPEN Session per Task (transactionally)
    - Repeated start returns existing OPEN Session
    - Repeated idempotency key returns original result
  - Session carries the agent context (courseId, SubjectPack version, skill set)
  - Session status: OPEN → COMPLETED / ABANDONED
- [x] 13.3 Create API routes:
  - `POST /api/sessions` + Idempotency-Key → 201 (new) or 200 (existing)
  - `GET /api/sessions?taskId=...&courseId=...&cursor=...`
  - `GET /api/sessions/:sessionId`
  - `GET /api/sessions/:sessionId/messages?cursor=...`
  - `GET /api/sessions/:sessionId/submissions?cursor=...`
- [x] 13.4 Write tests:
  - Create session for enrolled active course with entitlement → success
  - Create session for planned course → 409 `COURSE_NOT_AVAILABLE`
  - Create session for active course without entitlement → 403 `COURSE_ACCESS_REQUIRED`
  - Create session for non-enrolled course → 409 `COURSE_NOT_ENROLLED`
  - Create second OPEN session for same task → returns existing
  - Same idempotency key → returns original
  - Cross-student task → 404
  - COMPLETED/SKIPPED task → 409 `TASK_NOT_OPEN`
  - Refresh after restart → session persists

**Verify:** Session lifecycle enforced. Enrollment checked. Idempotency works. Cross-student isolation confirmed.

**Status:** ✅ Done (in-memory backend). `tests/contract/test_session_routes.py`, including 5 concurrent starts producing exactly one session, and restart persistence. The Task document (`openSessionId`) is the uniqueness guard, so correctness does not depend on query locking in Firestore. `POST /sessions/:id/complete` is deferred to Step 18 because it needs accepted assessments.

---

### Step 14 — Accept commands with Run and outbox (transactional)

**Goal:** Student commands (messages, submissions) create Runs atomically with outbox entries.

- [x] 14.1 Create `app/adapters/firestore/run_repository.py` implementing `RunRepository` protocol
- [x] 14.2 Create `app/adapters/firestore/submission_repository.py` implementing `SubmissionRepository` protocol
- [x] 14.3 Create `app/adapters/firestore/idempotency_repository.py` implementing `IdempotencyRepository` protocol
- [x] 14.4 Create `app/adapters/firestore/outbox_repository.py` — outbox entries for dispatching to workers
- [x] 14.5 Create `app/domain/command_service.py`:
  - `submitAnswer(actor, sessionId, submission, idempotencyKey)`:
    - Validate session ownership, question/file references
    - In one Firestore transaction: create Submission + Run(QUEUED) + idempotency record + outbox entry
    - No external calls inside transaction
    - Same key/same body → returns original IDs
    - Same key/different body → 409 `IDEMPOTENCY_CONFLICT`
  - `sendMessage(actor, sessionId, message, idempotencyKey)`:
    - Same transactional pattern
  - Enforce: at most one nonterminal Run per Session → 409 `RUN_IN_PROGRESS`
- [x] 14.6 Create API routes:
  - `POST /api/sessions/:sessionId/submissions` + Idempotency-Key → 202
  - `POST /api/sessions/:sessionId/messages` + Idempotency-Key → 202
  - `GET /api/runs/:runId`
  - `POST /api/runs/:runId/input` + Idempotency-Key → 202 (only WAITING_INPUT)
  - `POST /api/runs/:runId/cancel` + Idempotency-Key → 202
- [x] 14.7 Write tests:
  - Duplicate submission (same idempotency key) → same result
  - Conflicting body with same key → 409
  - Concurrent commands to same session → 409 `RUN_IN_PROGRESS`
  - Foreign question/file → rejected
  - Stale input response → rejected
  - Cancel racing with enqueue
  - Transaction failure → no orphan Run, no lost command

**Verify:** Atomic command acceptance. Idempotency enforced. At-most-one active Run per Session. Transaction failures leave clean state.

**Status:** ✅ Done (in-memory backend). `tests/contract/test_command_routes.py`: atomic write set, replay/conflict, 4 concurrent submits giving 1×202 and 3×409 `RUN_IN_PROGRESS`, foreign question/file/superseded refs rejected, stale run input rejected, cancel racing enqueue, and an injected commit failure leaving the store byte-identical with the retry succeeding. Emulator run pending: `tests/emulator/test_firestore_flows.py` is written but skips (no Java on this machine).

---

### Step 15 — Implement queue adapter and recoverable job execution

**Goal:** Outbox entries are dispatched to workers; workers execute with leases and fencing tokens.

- [x] 15.1 Create `app/adapters/queue/local_queue.py` — local durable queue for development:
  - Poll outbox for undispatched entries
  - Immediate best-effort delivery after transaction commit
  - Reconciliation scan for missed entries
- [x] 15.2 Create `app/adapters/queue/cloud_tasks_adapter.py` — Cloud Tasks adapter interface (implementation deferred to staging)
- [x] 15.3 Create `app/workers/run_worker.py`:
  - Authenticate worker invocations (OIDC in production, service token locally)
  - Transactionally acquire lease and increment fencing token; skip if already terminal
  - Execute in bounded steps with checkpoints
  - On completion: verify fencing token still valid before committing result
  - Expired lease → can requeue the same Run
  - Old fencing token → cannot commit (stale worker protection)
- [x] 15.4 Create `app/workers/outbox_dispatcher.py`:
  - Scan outbox for pending entries
  - Dispatch to queue with deterministic delivery IDs
  - Mark as dispatched; handle crash between enqueue and mark
- [x] 15.5 Create synthetic execution mode for internal tests — runs a deterministic stub instead of calling LLM, clearly labeled
- [x] 15.6 Write tests:
  - Restart after API commit before dispatch → outbox scan picks up
  - Restart after queue enqueue before outbox acknowledgement → duplicate dispatch handled
  - Duplicate delivery → idempotent (same result)
  - Crash during worker execution → lease expires → requeue
  - Stale worker commit (old fencing token) → rejected
  - Cancel/commit race → consistent terminal state

**Verify M1:** Restart recovery works across crash windows. Duplicate deliveries don't cause duplicate effects. Synthetic outputs are clearly labeled. Two-student isolation holds across all new resources. Course enrollment flow works end-to-end.

**Status:** 🟡 Implemented; verified over the in-memory backend. `tests/unit/test_run_worker.py` covers each crash window, duplicate delivery, live-lease retry, lease expiry and requeue, stale fencing-token commit, both cancel/commit orderings, retry exhaustion, lost enrollment, worker HTTP auth (a student token → 401), and synthetic labeling. A real `uvicorn` run (`make server-memory`) went enroll → session → message → local worker → SUCCEEDED, with a labeled synthetic reply. Gaps: (1) execution is a single bounded step per attempt, so checkpoints inside a step arrive with the LLM gateway (Step 16); (2) the Cloud Tasks adapter and Google OIDC worker auth are unit-tested against fakes only, and need verifying in staging (Step 30); (3) Emulator run pending: `tests/emulator/test_firestore_flows.py` is written but skips (no Java on this machine).

---

## M2 — Calculus Learning Loop (Steps 16–21)

### Step 16 — Implement LLMGateway with static routing and budgets

**Goal:** A controlled interface for model calls with usage tracking and budget enforcement.

- [ ] 16.1 Create `app/adapters/llm/gateway.py` — `LLMGateway`:
  - Provider abstraction with typed input (system, context, messages, schema) and output (content, usage, modelVersion)
  - Start with one provider (Anthropic Claude)
  - Capture model version and workflow version on every call
- [ ] 16.2 Create `app/adapters/llm/router.py` — static `ModelRouter`:
  - Route by skill tier (fast/balanced/strong) from pack manifest
  - No decision model needed; rules-based routing
- [ ] 16.3 Implement usage budgets:
  - Per-Run token budget
  - Per-Session cumulative budget
  - Per-student daily budget (including retries)
  - Budget exhaustion → pause/reject with explanation, not silent degradation
- [ ] 16.4 Implement retry logic:
  - Finite retries with backoff for transient failures
  - Schema validation on output; failed validation may retry within budget
  - Never silently downgrade grading to an unevaluated model to fit budget
- [ ] 16.5 Write tests:
  - Provider timeout → graceful failure
  - Schema validation failure → retry then fail
  - Budget exhaustion → clear rejection
  - Usage logging captures model version and tokens
  - Separately labeled real-provider smoke test (when configured)

**Verify:** Model calls are tracked, budgeted, and retried safely. No secrets or raw student work in logs.

---

### Step 17 — Implement Calculus skills: Socratic guidance and rubric assessment

**Goal:** The first real learning skills — Socratic prompting and FRQ rubric assessment for calc_bc.

- [ ] 17.1 Create `app/registries/subject_pack_registry.py`:
  - Load and validate pack manifests from `content/packs/`
  - Only activate packs with `availability: "active"` and verified content
  - Pin question/rubric/workflow versions per Run
- [ ] 17.2 Create `app/domain/skills/socratic_guidance.py`:
  - Load minimal relevant student context (current mastery, session history)
  - Generate Socratic hints that guide without giving answers
  - Record each server-issued hint for dependency tracking
- [ ] 17.3 Create `app/domain/skills/rubric_assessment.py`:
  - Load fixed rubric version for the question
  - Evaluate student answer against each rubric criterion
  - Generate evidence references (which part of student answer supports each criterion)
  - Distinguish assisted success (hints used) from independent evidence
  - Return `accepted` or `insufficient_evidence` status with reasons
- [ ] 17.4 Create `app/registries/tool_registry.py`:
  - Internal tool interface: `execute(name, input, context)`
  - First tool: mathematical expression verification (optional SymPy adapter)
  - Whitelist per skill, parameter schema, scope constraints
- [ ] 17.5 Create `app/domain/context_loader.py`:
  - Load reviewed material sets with source references
  - Filter by studentId/courseId/ACL before retrieval
  - Return material-not-found when index is insufficient
- [ ] 17.6 Write tests using evaluation cases from Step 7:
  - Correct answer → appropriate rubric scores and evidence
  - Incorrect answer → identifies specific rubric failures
  - Hint-assisted answer → tracked as assisted, not independent
  - Irrelevant source material → rejected
  - Tool failure → handled gracefully (not fabricated success)

**Verify:** Skills produce rubric-backed assessments with evidence references. Hint dependency tracked. No fabricated tool success.

---

### Step 18 — Implement AssessmentService: atomic evidence commit

**Goal:** Assessment results, mastery updates, events, and Run completion happen in one transaction.

- [ ] 18.1 Create `app/domain/assessment_service.py` — `commit_assessment()`:
  - Validate evidence semantically (not just JSON shape): question ownership, rubric version, evidence references, student answer, tool results, hint records
  - In one transaction: save Assessment + mastery projection + Run terminal state + domain events + outbox entries
  - `insufficient_evidence` → can show limited feedback but does NOT update mastery
  - Use unique evidence application ID — same evidence cannot be applied twice
  - Regrade: `supersedesAssessmentId` replaces earlier evidence contribution
  - Consecutive corrections after hints are NOT counted as independent evidence
- [ ] 18.2 Create `app/domain/mastery_service.py`:
  - Project mastery from accepted assessments
  - Track: skill level, independent evidence count, coverage, uncertainty
  - Mastery is derivable from assessments (can be rebuilt)
- [ ] 18.3 Create `app/domain/assessment_service.py` — `complete_session()`:
  - Check: no active Run, accepted assessment exists, task completion rules met
  - In one transaction: Session → COMPLETED, Task → COMPLETED, events
  - Does NOT re-apply mastery (summary only, no double-counting)
  - `abandon()`: Session → ABANDONED, Task back to PLANNED; requires no active Run
- [ ] 18.4 Create API routes:
  - `GET /api/assessments/:assessmentId`
  - `GET /api/assessments?sessionId=...&cursor=...`
  - `GET /api/mastery?courseId=...&cursor=...`
  - `POST /api/sessions/:sessionId/complete` + Idempotency-Key
  - `POST /api/sessions/:sessionId/abandon` + Idempotency-Key
- [ ] 18.5 Write tests:
  - Partial transaction failure → no orphan assessment, mastery unchanged
  - Replayed commit → returns existing result
  - Stale lease (old fencing token) → rejected
  - Concurrent cancellation → consistent state
  - Regrade → replaces earlier contribution
  - `insufficient_evidence` → mastery NOT updated
  - Repeated complete → idempotent
  - Complete with active Run → 409 `RUN_IN_PROGRESS`
  - Complete without accepted assessment → 409 `COMPLETION_REQUIREMENTS_NOT_MET`
  - Prediction remains `unavailable`

**Verify:** Atomic commit. No double-counting. Insufficient evidence handled correctly. State consistent after failures.

---

### Step 19 — Implement durable event feed (SSE + polling)

**Goal:** Frontend receives real-time updates from persistent events, with reconnection and replay.

- [ ] 19.1 Create `app/adapters/firestore/event_repository.py`:
  - Per-student monotonic sequence assignment (in transaction)
  - `listEvents(actor, afterSequence, limit)` — paginated, ordered by sequence
  - Filtered projection: exclude internal outbox, raw model reasoning, credentials, private tool params
- [ ] 19.2 Create `app/api/routes/events.py`:
  - `GET /api/events?after=...&limit=50` → paginated events
  - `GET /api/events/stream?after=...` → SSE stream:
    - Replay persisted events from `after` sequence
    - Continue with new events
    - Heartbeat at configured interval
    - Close before deployment timeout; client reconnects
    - `Last-Event-ID` supported; inconsistency with `after` → 400
    - Expired cursor → 410 `EVENT_CURSOR_EXPIRED`
- [ ] 19.3 Use `Authorization: Bearer` header for SSE (not token in URL)
- [ ] 19.4 Support polling fallback using same sequence/dedup logic
- [ ] 19.5 Write tests:
  - Events arrive in sequence order
  - Reconnect replays missed events
  - Expired cursor → 410, client re-fetches snapshot
  - Cross-student event access → 404
  - Heartbeat sent within timeout
  - Duplicate event IDs deduplicated by client

**Verify:** Events are durable, ordered, and replayable. SSE reconnect works. Polling fallback works. Cross-student isolation enforced.

---

### Step 20 — Connect frontend to real API with course-driven workspace

**Goal:** The web frontend uses the real API for the Calculus learning flow, end-to-end. The workspace is driven by enrolled courses.

- [ ] 20.1 Implement the async data providers defined in Step 6:
  - `fetchTwin()` → `GET /api/twin`
  - `fetchCatalog()` → `GET /api/courses/catalog`
  - `enrollCourse(courseId)` → `POST /api/courses/enroll`
  - `fetchEnrolledCourses()` → `GET /api/courses/enrolled`
  - `fetchCourseAgent(courseId)` → `GET /api/courses/:courseId/agent`
  - `fetchTasks(courseId)` → `GET /api/tasks?courseId=...`
  - `createSession(taskId)` → `POST /api/sessions`
  - `submitAnswer(sessionId, submission)` → `POST /api/sessions/:id/submissions`
  - `sendMessage(sessionId, message)` → `POST /api/sessions/:id/messages`
  - `completeSession(sessionId)` → `POST /api/sessions/:id/complete`
  - `fetchEvents(afterSequence)` → `GET /api/events` or SSE stream
- [ ] 20.2 Implement the course-driven workspace:
  1. Login → fetch twin, entitlements, enrolled courses
  2. Show enrolled courses in sidebar; each course shows its agent
  3. Course catalog available for browsing/enrolling new courses
  4. Selecting a course opens the per-course agent chat view
- [ ] 20.3 Implement the per-course agent learning flow:
  1. Open course → see agent chat + course tasks
  2. Select task → create session (agent conversation begins)
  3. Chat with agent → ask questions, get Socratic guidance
  4. Type answer → submit → see "grading..." (Run QUEUED → RUNNING)
  5. Receive assessment feedback (Run SUCCEEDED, assessment displayed)
  6. Complete session when eligible
- [ ] 20.4 Handle all Run states visually: QUEUED, RUNNING, WAITING_INPUT, SUCCEEDED, FAILED, CANCELLED
- [ ] 20.5 Implement SSE event subscription with reconnect and polling fallback
- [ ] 20.6 API errors show truthful state (not demo data substitution)
- [ ] 20.7 Test in browser:
  - Submit answer → see real feedback
  - Close/reopen browser during grading → state recovered
  - Network error → retry with same Idempotency-Key
  - SSE reconnect after disconnect

**Verify:** End-to-end Calculus flow works in browser. Grading produces rubric-backed feedback. State survives browser refresh and network interruption.

---

### Step 21 — Run Calculus evaluation; add file upload only after text works

**Goal:** Measure learning quality against evaluation baseline. Optionally add file/OCR support.

- [ ] 21.1 Run the evaluation cases from Step 7 through the real system:
  - Compare rubric assessment output against human annotations
  - Track: false acceptance rate, false insufficient rate, evidence quality, feedback usefulness, per-assessment cost
- [ ] 21.2 Record results in `content/evaluation/calc_bc/report-v1.md`:
  - Per-case comparison with expected outcome
  - Aggregate metrics for each evaluation dimension
  - Identified weaknesses and improvement areas
- [ ] 21.3 (Optional) Implement file upload if included in pilot:
  - `POST /api/files` → signed upload URL
  - `POST /api/files/:fileId/complete` → validation
  - `GET /api/files/:fileId` → status
  - `GET /api/files/:fileId/download` → scoped download URL
  - OCR: preserve original + recognized text; ambiguous text → student confirmation before assessment
- [ ] 21.4 If file/OCR deferred: document that pilot is text-only; disable upload UI

**Verify M2:** Full Calculus loop works with evaluated skill. No unsupported progression, false official score, duplicate evidence, or unauthorized file access. Evaluation report records quality with sample sizes and identified limitations.

---

## M3 — Validated SAT Transfer (Steps 22–27)

### Step 22 — Implement reviewed prerequisite mappings

**Goal:** AP assessment evidence can suggest (not confirm) related SAT skill weaknesses.

- [ ] 22.1 Create `app/domain/prerequisite_service.py`:
  - Load versioned mappings from `content/mappings/`
  - Only eligible `accepted` assessments trigger `prerequisite.suspected` events
  - Retain source assessment ID and mapping version
  - `suspected` is a recommendation for diagnosis, not a confirmed SAT weakness
- [ ] 22.2 Implement mapping rules:
  - Mathematical topic overlap alone is insufficient
  - Suppress unrelated calculus-only errors (e.g., L'Hôpital-specific issues don't map to SAT)
  - Only errors involving shared prerequisite skills (e.g., algebraic manipulation) are candidates
- [ ] 22.3 Write tests using evaluation cases from Step 7:
  - Positive mapping: calc error with shared prerequisite → `prerequisite.suspected`
  - Negative mapping: calc-only error → no event
  - Missing evidence → no event
  - Unknown mapping version → rejected
  - Repeated source evidence → deduplicated
  - Student sees uncertainty (suspected, not confirmed)

**Verify:** Reviewed mapping cases pass. False positives from counterexamples are suppressed. Uncertainty is visible.

---

### Step 23 — Add SAT short diagnostic workflow

**Goal:** A short SAT diagnostic that independently tests a suspected prerequisite skill.

- [ ] 23.1 Create `content/packs/dsat/manifest.json` — DSAT pack with diagnostic capability for selected prerequisites
- [ ] 23.2 Create `content/packs/dsat/questions/` — reviewed SAT-style diagnostic questions targeting specific prerequisite skills
- [ ] 23.3 Create `app/domain/skills/sat_diagnostic.py`:
  - Require DSAT entitlement and available diagnostic content
  - Record independent performance (no hints from the AP session)
  - Use the same AssessmentService for evidence commit
  - Outcomes: `supported` (weakness confirmed), `unsupported` (no weakness found), `insufficient` (not enough evidence)
  - Do NOT convert short diagnostic into a SAT exam score
- [ ] 23.4 Wire into Task/Session/Run lifecycle (shared runtime, not a separate service)
- [ ] 23.5 Write tests:
  - Correct answers → `unsupported` (no weakness)
  - Incorrect answers → `supported` (weakness confirmed)
  - Hints used → tracked
  - Insufficient evidence → appropriate outcome
  - No DSAT entitlement → 403
  - No diagnostic content for this prerequisite → appropriate error

**Verify:** SAT diagnostic works through the same Task/Session/Run pipeline. No separate service needed. No SAT score generated from a few questions.

---

### Step 24 — Implement replay-safe domain event consumers

**Goal:** Events drive follow-up actions atomically and idempotently.

- [ ] 24.1 Create `app/workers/consumers/prerequisite_consumer.py`:
  - Consume `assessment.completed` events → evaluate prerequisite mappings → emit `prerequisite.suspected`
  - Consumer receipt: `(consumerName, eventId, targetSkill)` — written in same transaction as target Task
- [ ] 24.2 Create `app/workers/consumers/diagnostic_consumer.py`:
  - Consume `prerequisite.suspected` → create diagnostic Task (if DSAT entitled and content available)
  - Atomically write Task + receipt; deduplicate by consumer/event/targetSkill
- [ ] 24.3 Create `app/workers/consumers/reinforcement_consumer.py`:
  - Consume `prerequisite.confirmed` → create reinforcement Task
  - `unsupported`/`insufficient` → no reinforcement created; record reason
- [ ] 24.4 Implement consumer infrastructure:
  - Per-consumer offset tracking
  - At-least-once delivery; idempotent with receipt checks
  - Domain-level dedupe key (in addition to event dedupe): repeated related observations don't flood existing active diagnostics
- [ ] 24.5 Write tests:
  - Crash before receipt commit → replay creates task on retry
  - Crash after receipt commit → no duplicate task
  - Replayed events → idempotent
  - Repeated observations for same skill → single diagnostic
  - Two-student isolation
  - Unsupported outcome → no reinforcement task created

**Verify:** Exactly one intended Task per dedupe scope. Crash-safe across all windows. No orphan tasks.

---

### Step 25 — Implement evidence-aware incremental planning

**Goal:** The Planner updates the schedule based on new evidence, respecting time budgets and student controls.

- [ ] 25.1 Create `app/domain/planner_service.py`:
  - Rank learning needs: deadlines > diagnosed prerequisites > evidence gaps > new practice
  - Place tasks within student's available weekly minutes
  - Preserve IN_PROGRESS, COMPLETED, and student-locked tasks
  - Defer suggestions if time budget is full
  - Explain each task placement with real assessment/mapping/schedule references
- [ ] 25.2 Implement `POST /api/plans/replan` + Idempotency-Key → 202 (PLANNING Run)
- [ ] 25.3 Implement student controls:
  - `PATCH /api/tasks/:taskId` — scheduledDate, studentLocked, status=SKIPPED
  - Locked tasks are preserved during replanning
  - Skipped tasks record reason
- [ ] 25.4 Write tests:
  - Full schedule → defer new suggestions
  - Conflicting deadlines → prioritize correctly
  - Manual locks preserved during replan
  - No reliable assessment data → conservative suggestions
  - Concurrent plan updates → consistent (no duplicated/disappearing tasks)
  - Explanations reference real events

**Verify:** Planning is incremental, respects time budgets, preserves student choices, and explains decisions.

---

### Step 26 — Verify the complete cross-domain transfer slice

**Goal:** End-to-end evidence that the first product differentiator works.

- [ ] 26.1 Test the positive chain:
  1. Calculus answer reveals eligible prerequisite issue
  2. Student sees why a SAT diagnostic is proposed
  3. Diagnostic confirms weakness → reinforcement task created in plan
  4. Student can explain the recommendation and change its timing
- [ ] 26.2 Test the negative chain:
  1. Calculus error is calc-specific (no SAT implication)
  2. No diagnostic proposed
- [ ] 26.3 Test the unsupported chain:
  1. Diagnostic is taken but weakness not confirmed
  2. No reinforcement task created; reason recorded
- [ ] 26.4 Test reliability:
  - Restarts during each step → consistent state
  - Duplicate event deliveries → no duplicate tasks
  - SSE reconnection → events replayed correctly
- [ ] 26.5 Test isolation:
  - Cross-student access at every step → 404

**Verify M3:** Both positive and negative chains work with reviewed content. Cross-student and replay checks pass. Mapping mistakes identified and content revised before widening coverage.

---

### Step 27 — Display cross-domain flow in the frontend

**Goal:** The UI shows prerequisite suggestions, diagnostics, and reinforcement with clear explanations.

- [ ] 27.1 Show `prerequisite.suspected` events as diagnostic suggestions with:
  - Source assessment reference ("Based on your Calculus answer about...")
  - Explanation of what the diagnostic will test
  - Clear label: suspected, not confirmed
- [ ] 27.2 Show diagnostic Task in task list with context
- [ ] 27.3 After diagnostic completion, show outcome:
  - Supported → reinforcement task appears with explanation
  - Unsupported → "No SAT weakness found for this skill" message
- [ ] 27.4 Show plan explanations: why each task was added, source events, time allocation
- [ ] 27.5 Test in browser: complete the full cross-domain flow visually

**Verify:** Student can understand the full flow from AP assessment to SAT diagnostic to reinforcement/no-reinforcement.

---

## M4 — Proactive Planning and Pilot (Steps 28–33)

### Step 28 — Implement timezone-aware scheduled planning

**Goal:** Daily planning runs automatically for each student at the right local time.

- [ ] 28.1 Create `app/workers/scheduler/planning_scheduler.py`:
  - Cloud Scheduler trigger → scan students with `dueAt` ≤ now
  - Calculate local date using student's IANA timezone
  - Deduplicate: `studentId + localDate + planningReason`
  - Handle DST transitions correctly
- [ ] 28.2 Persist `nextDueAt` per student
- [ ] 28.3 Use the same Planner for scheduled and event-driven updates
- [ ] 28.4 `GET /api/tasks` has no hidden mutation (read-only)
- [ ] 28.5 Write tests:
  - DST boundary (spring forward / fall back)
  - Timezone change by student
  - Duplicate scheduler invocations → no duplicate planning
  - API/worker downtime → catch-up on recovery
  - Overlapping assessment-driven and scheduled replanning → consistent

**Verify:** Scheduled planning respects timezones and DST. No duplicate plans from duplicate triggers.

---

### Step 29 — Implement student controls and opt-in reminders

**Goal:** Students can defer/skip/lock tasks and opt into one reminder channel.

- [ ] 29.1 Implement task controls in UI:
  - Defer: change scheduledDate via PATCH
  - Skip: set status to SKIPPED (only from PLANNED)
  - Lock: set studentLocked = true (preserved during replanning)
- [ ] 29.2 Create `app/domain/reminder_service.py`:
  - Record consent, quiet hours, frequency caps
  - Delivery dedupe keys per channel/task/time-window
  - Check consent again immediately before sending (queued reminder can become ineligible)
  - Default: no parent notification
- [ ] 29.3 Create fake delivery adapter for tests; real delivery only to designated test recipients
- [ ] 29.4 Write tests:
  - Opt-out after enqueue → reminder not sent
  - Quiet hours → reminder deferred
  - Repeated delivery → deduplicated
  - Changed deadline → reminder updated
  - Completed task → no reminder
  - Student control persistence across restarts

**Verify:** Student controls work correctly. Reminders respect consent, quiet hours, and frequency caps.

---

### Step 30 — Deploy to staging (Cloud Run, Firestore, Cloud Tasks)

**Goal:** The application runs in a real cloud environment, not just emulators.

- [ ] 30.1 Create deployment configuration:
  - Cloud Run service for API
  - Cloud Run service for worker
  - Firestore database (separate from other projects)
  - Cloud Tasks queues
  - Cloud Scheduler jobs
  - Cloud Storage bucket
  - Secret Manager for credentials
- [ ] 30.2 Configure service identities and IAM:
  - API and worker have separate service accounts
  - Worker invocation requires OIDC with correct audience
  - Students cannot call worker endpoints
- [ ] 30.3 Remove emulator hosts and synthetic providers from production config
- [ ] 30.4 Configure timeouts, retries, and SSE reconnect for cloud environment
- [ ] 30.5 Record which infrastructure checks ran and which resources were unavailable

**Verify:** Real Cloud Tasks OIDC works. Cross-instance recovery works. Request timeout handling correct. Finite cost limits configured.

---

### Step 31 — Add operations monitoring and backup/restore

**Goal:** The system is observable and recoverable.

- [ ] 31.1 Implement structured logging:
  - Actor/run ID, model tier, latency, tokens, retries, error codes
  - Exclude: raw student answers, drafts, tokens, private tool payloads
- [ ] 31.2 Implement metrics:
  - Assessment latency and cost
  - Worker failures and outbox backlog
  - Duplicate suppression count
  - Learning quality regressions
- [ ] 31.3 Set up alerts for: worker failure rate, outbox backlog growth, budget overruns
- [ ] 31.4 Create and test backup/restore procedure:
  - Backup synthetic student with linked files, assessments, and event state
  - Restore into separate test environment
  - Verify all linked data is consistent after restore
- [ ] 31.5 Verify delete/retention effects on indexes, artifacts, and future backup expiry

**Verify:** Simulated alerts fire correctly. Restore produces consistent state. Data deletion is clean.

---

### Step 32 — Full integration testing in staging

**Goal:** All M0–M3 acceptance chains run in the cloud environment.

- [ ] 32.1 Run the complete Calculus learning loop in staging
- [ ] 32.2 Run the cross-domain transfer slice (positive + negative + unsupported chains) in staging
- [ ] 32.3 Test SSE reconnection across Cloud Run instances
- [ ] 32.4 Test worker crash recovery in cloud
- [ ] 32.5 Test cross-student isolation for all resources: sessions, events, files, assessments
- [ ] 32.6 Verify: no duplicated progress, restart recovery, truthful failed/waiting states

**Verify:** All chains pass in staging with real infrastructure. Cloud-specific issues (OIDC, timeouts, instance rotation) handled.

---

### Step 33 — Apply the external pilot gate

**Goal:** Decide whether the system is ready for real students.

- [ ] 33.1 Quality gate:
  - Reviewed rubric feedback accuracy
  - Unsupported-answer behavior (no false acceptance)
  - Validated prerequisite mapping (positive + negative cases)
  - Independent follow-up performance measurement
  - Plan explanations are comprehensible
- [ ] 33.2 Reliability gate:
  - No duplicated progress
  - Restart recovery confirmed
  - Events are replayable
  - Failed/waiting states are truthful
- [ ] 33.3 Access gate:
  - Auth and student isolation verified across all resources
  - Entitlements cannot be self-granted
  - No default parent access to private material
- [ ] 33.4 Operations gate:
  - Model budget limits enforced
  - Opt-in reminders with working consent controls
  - Cloud authentication and timeouts configured
  - Backup/restore tested
- [ ] 33.5 Record: sample sizes, thresholds, reviewer sign-off, unresolved limitations
- [ ] 33.6 If scope is text-only (no file/OCR), document explicitly

**Verify M4:** All gates pass or have documented exceptions. Real students enter only after gates pass. Documentation updates alone never mark these steps complete.

---

## M5 — Optional Expansion After Pilot Evidence (Steps 34–38)

Each extension is independently selected and verified. None are prerequisites for the pilot.

### Step 34 — Expand AP coverage, starting with APUSH

- [ ] 34.1 Create reviewed APUSH content: questions, rubrics (DBQ, LEQ, SAQ, MCQ)
- [ ] 34.2 Add APUSH-specific skills (document analysis, argumentative writing feedback)
- [ ] 34.3 Add necessary UI for APUSH answer formats
- [ ] 34.4 Evaluate APUSH quality before changing `planned` → `active`
- [ ] 34.5 Verify existing Calculus regression cases still pass

### Step 35 — Add admissions interviews and sourced planning

- [ ] 35.1 Implement interview → student-confirmed facts → outline/feedback workflow
- [ ] 35.2 Track school deadline sources with verification dates and uncertainty
- [ ] 35.3 Keep authored essay text with student; no one-click ghostwriting
- [ ] 35.4 Activity edits require student fact confirmation before saving

### Step 36 — Add scoped parent summaries

- [ ] 36.1 Separate parent identity with explicit student relationship
- [ ] 36.2 Implement `summary:read` scope — excludes private chats, original answers, essay drafts
- [ ] 36.3 Implement consent and revocation; verify on every access
- [ ] 36.4 Test parent A/B isolation, revoked authorization, field-level projection

### Step 37 — Calibrate mastery and exam predictions

- [ ] 37.1 Compare mastery estimates against independent held-out responses
- [ ] 37.2 Exam prediction requires representative coverage and independent outcomes
- [ ] 37.3 Keep practice performance, self-reported records, and predictions distinct
- [ ] 37.4 Without sufficient evidence, prediction stays `unavailable`

### Step 38 — Evaluate optional infrastructure

- [ ] 38.1 Assess Jev, MCP adapters, Temporal, semantic indexes as needed
- [ ] 38.2 Verify actual vendor availability, interfaces, quality, and costs
- [ ] 38.3 Confirm core workflows remain functional without optional dependencies

---

## Delivery Map

| Milestone | Steps | Key Exit Criteria | Status |
|---|---|---|---|
| M0 Contracts and baseline | 1–7 | Buildable skeleton, schemas, fixtures, evaluation cases, Firebase emulators, frontend contract | Implemented; emulator + content review pending |
| M1 Reliable foundation | 8–15 | Independent auth, Firestore repos, course enrollment, Task/Session/Run lifecycle, queue/outbox/worker, two-student isolation | Implemented; emulator + staging verification pending |
| M2 Calculus learning loop | 16–21 | LLM gateway, Calculus skills, atomic assessment, events/SSE, course-driven frontend, evaluation report | Not started |
| M3 Validated SAT transfer | 22–27 | Prerequisite mappings, SAT diagnostic, event consumers, planner, cross-domain E2E, frontend display | Not started |
| M4 Proactive planning and pilot | 28–33 | Scheduled planning, reminders, staging deploy, monitoring, integration tests, pilot gate | Not started |
| M5 Optional expansion | 34–38 | Individually validated extensions (APUSH, admissions, parent, predictions, infrastructure) | Not started |

## Superseded patterns

The following old patterns are replaced and must not be carried forward:
- Task/Session merged into one record → separate persistent resources
- In-memory sessions → Firestore with transactions
- Client-submitted scoreDelta → server-side assessment only
- `X-User-Email` identity → Firebase ID token with verified studentId
- Public event POST → server-generated events from typed commands
- Uncalibrated predictions (4.5/4.8) → `unavailable` until calibrated
- Jev/MCP as M0–M4 prerequisites → optional M5 evaluation
