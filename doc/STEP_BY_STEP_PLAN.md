# High School Student OS — Step-by-Step Implementation Plan v5.0

Updated: 2026-11-05 (Firestore emulator suite run: 8/8 pass; M5 backend redeployed to staging). Previously 2026-11-04 (M5 Steps 34–38 implemented ahead of the pilot gate at the owner's request; Step 30 deployed to staging on 2026-11-03). Previously 2026-11-01 (v5.0: M3 redefined from Calc→SAT transfer to a course platform; see M3). Previously 2026-10-31. Python/FastAPI backend. This plan builds on [the architecture recommendations](STUDENT_OS_ARCHITECTURE_RECOMMENDATIONS.md) and implements [API v0.3](API.md), [backend v0.4](BACKEND.md), and [the milestone plan](IMPLEMENTATION_PLAN.md). Checked boxes mark sub-tasks implemented in the working tree; each step's **Status** line records what was actually verified.

The product is a **course platform with one shared runtime**: third parties add courses as data (skills, question bank, rubrics and criteria, course requirements, completion criteria) and every course runs the same loop: **practice → supported assessment → saved evidence → in-course follow-up → an explained plan across enrolled courses**. Courses are independent; there is no cross-course inference. Calc BC is the first-party reference course. M0–M4 deliver the pilot (Calc BC plus one course authored through the package path); M5 contains independently selectable extensions.

## Current state

### Implementation status (as of 2026-11-05)

| Milestone | Steps | Status |
|---|---|---|
| M0 Contracts and baseline | 1–7 | **Implemented; verification partial**: emulator suite run (`make test-emulator` passed 8/8 on 2026-11-05); content not yet human-reviewed |
| M1 Reliable foundation | 8–15 | **Implemented; verified over the in-memory backend and on the Firestore emulator** (`make test-emulator` passed 8/8 on 2026-11-05); Cloud Tasks/OIDC verified in staging (Step 30) |
| M2 Calculus learning loop | 16–21 | **Implemented; verified with a scripted model over the in-memory backend**: first real-model evaluation run with OpenAI (Step 21, draft content, 1 false credit for review); Anthropic smoke test pending a key; emulator suite passed 2026-11-05 |
| M3 Course platform | 22–27 | **Redefined 2026-11-01.** Calc→SAT mapping layer removed (Step 22.4); course-agnostic parts kept (consumer infrastructure, planner, `choice-scoring`, task controls); Digital SAT is an independent course and the chosen second course. **Steps 26–27 implemented 2026-11-01** (package contract v1 + validator, author/reviewer roles, review gate, version pinning, retire; Digital SAT rebuilt as an authored package; course-driven frontend). Not started: ability catalog contract (23), course-internal follow-up rules (24.2), package-sourced deadlines (25.4), re-expressing Calc BC as a package (22.3). |
| M4 Proactive planning and pilot | 28–33 | **Steps 28, 29, 31 implemented 2026-11-01; verified over the in-memory backend** (scheduled planning, student controls + opt-in reminders, structured logs/metrics/alerts, backup/restore/delete, event retention). **Step 30 deployed to staging 2026-11-03** (project `hs-student-os`; real Firebase Auth + Firestore + Cloud Tasks + worker + model smoke test passed, see [OPERATIONS.md](OPERATIONS.md) §5; the deployed image predates M5). **Step 32** now unblocked, not yet run. **Step 33 gate recorded as not passed** ([PILOT_GATE.md](PILOT_GATE.md)). |
| M5 Optional expansion | 34–43 | **Steps 34–38 implemented 2026-11-04 over the in-memory backend, at the owner's request before the pilot gate passed** (M5 is formally "after pilot evidence"; M3 Steps 22.3, 23, 24.2, 25.4 are still open). 34: author portal page + student-view preview, platform ability `source-analysis`, APUSH as an authored package (submitted, awaiting review), aggregate author metrics with small-cohort suppression. 35: admissions interview → proposed facts → student confirmation → outline/feedback runs, sourced deadlines, confirmed-fact activities (API only; no student UI yet). 36: parent identity, student-created invites, revocation, `summary:read` projection (API only). 37: calibration pipeline + prediction gate; predictions stay `unavailable` (no real outcomes exist). 38: assessment written, no optional infrastructure adopted. 41 (reviewer screen `web/review.html`): implemented 2026-11-07, locally verified in the browser, not deployed. 39 (author import from PDF and photos), 40 (conversational authoring agent), 42 (admin course-access tool) and 43 (review assistant agent; workflow and skills to be defined by reviewers): planned 2026-11-07, not started. Not deployed to staging. Browser check (2026-11-04, `make server-memory` + `make web`): author portal sign-in as `author_hsos`, package list, APUSH student-view preview with both source documents, suppressed metrics; no console errors (upload/submit buttons not clicked in the browser). |

Last local verification (`make check`, 2026-11-01, after M4 Steps 28–31): ruff lint/format clean, `mypy app/` (strict) clean, backend pytest **561 passed, 9 skipped** (8 emulator tests skip without emulators; 1 opt-in real-provider smoke test), web `node --test` **34 passed**. Docker image built and smoke-checked locally. Browser check over `make server-memory` + `make web`: Beth locked a task date, turned reminders off, and skipped a task with a reason; no console errors.

Open items before M0–M2 can be called complete:
- **Real-model evaluation (Steps 16, 21):** first run done 2026-11-01 with OpenAI `gpt-5.5` (`content/evaluation/calc_bc/report-v1.md`): 17/18 criteria, 6/6 statuses. One false credit (parametric `second-derivative-method`) awaits the reviewer's decision. Not yet run against Anthropic. These are draft-content results only, so they don't measure quality until content review is done and thresholds are set.
- ~~**Emulator verification (Steps 5, 9, 14, 15)**~~ — done 2026-11-05: `make test-emulator` (openjdk 21) passed 8/8: seed idempotence and isolation, a Firestore transaction round trip, isolation and twin concurrency, enrollment → session → command → worker, the atomic and fenced assessment commit, consumer effect + receipt + offset in one transaction with a no-op replay, the atomic PLANNING commit, and export → delete → restore. The first run failed one test written in M3 that assumed the test probe was the only consumer; M5's `course-metrics` consumer is registered by default, so the test now selects the probe's receipt and checks that `course-metrics` recorded its own.
- **Content review (Steps 4, 7, 26):** questions, rubrics and evaluation cases are `draft` with no named reviewer. Evaluation thresholds in `dimensions.json` are unset until a content reviewer sets them. From M3 on, review happens through the platform review gate (Step 26), which applies to first-party courses too.

### Checkout contents

- `doc/` — architecture, API, backend design, competitive review, implementation plan (this file)
- `server/` — FastAPI skeleton (`/api/health`, error envelope, request IDs, environment config that rejects emulator hosts and mock providers in staging/production), Pydantic v2 schemas, domain types and repository protocols, content/fixture/evaluation registries, Firebase adapter, emulator seed script, synthetic fixtures, Calc BC content pack, evaluation baseline, and tests
- `Makefile` — `install`, `dev`, `server`, `server-memory`, `web`, `emulators`, `seed`, `typecheck`, `lint`, `format`, `test*`, `check`
- `web/` — vanilla JS frontend. The async `data-provider.js` (Bearer auth, Idempotency-Key, request states, event dedupe) is the new seam; `?demo=true` loads `web/fixtures/demo.json` (validated against backend schemas). Predictions show "unavailable", and Task/Session/Run are kept as separate state. `window.HSData` now holds display metadata only.
- M1: Firebase token auth → `ActorContext`; Firestore repositories on a `DocTxn` seam with an in-memory test backend; twin, course catalog/enrollment/agent, task, session, message/submission, and run routes; transactional command acceptance with idempotency and outbox; outbox dispatcher, local queue, Cloud Tasks adapter, a lease/fencing-token run worker with its own HTTP service, a stalled-run recovery scan, and a labeled synthetic executor
- M2: LLM gateway with budgets and tier routing, Socratic and rubric-assessment skills, math-verify tool, atomic AssessmentService commit with mastery projection, session complete, durable event feed with SSE, frontend wired to the real API (sign-in, sessions, submissions, assessments), evaluation runner
- M3 so far: outbox-woken replay-safe consumer infrastructure (receipts + offsets + wake recovery; no production consumer yet), PLANNING runs with planner-rules-v1 and plan API, task skip reasons and reschedule-locks, `choice-scoring` in the shared runtime, Digital SAT as an independent course, plan view. The Calc→SAT mappings, findings API/card and `prerequisite.*` events were removed (Step 22.4)
- M4 so far: timezone-aware scheduled planning, task controls in the UI, opt-in reminders (fake sender only), structured JSON logs with redaction, log-based metrics, alert checks, per-student backup/restore/verify/delete, event retention, Dockerfile, staging provisioning (applied 2026-11-03) and Firebase Hosting deploy script
- M5: `source-analysis` ability and `sourceMaterialIds`; APUSH package; author portal (`web/author.html`) with preview and aggregate metrics (`course-metrics` consumer — the first production consumer); parent links and summaries; admissions workspace with two session-less Run kinds; calibration pipeline (`scripts/run_calibration.py`) and prediction gate; optional-infrastructure assessment ([OPTIONAL_INFRASTRUCTURE.md](OPTIONAL_INFRASTRUCTURE.md))
- Not built yet: file upload/OCR, regrade trigger, a real reminder channel, student-facing admissions UI, parent UI, admissions deadlines in the planner

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
- [x] 4.9 Create `content/mappings/calc-to-sat-prerequisites.json` — versioned mapping candidates with source AP skill, target SAT skill, conditions, counterexamples *(superseded 2026-11-01: cross-course mappings are removed in Step 22.4)*
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

**Status:** ✅ Done. `firebase.json`, `.firebaserc`, `firestore.rules`, the seed script, and the Makefile targets exist; the unit tests (`test_firebase_adapter.py`, `test_config.py`) pass, and `make test-emulator` passed 8/8 on 2026-11-05 (`tests/emulator/test_seed_emulator.py` included).

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

**Verify:** Each evaluation case has a reviewable expected outcome with provenance. Counterexamples exist for prerequisite mappings *(the prerequisite cases are retired with the mappings in Step 22.4; each course package now carries its own evaluation set)*. This is a content gate — no model quality evaluation yet.

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

**Status:** 🟡 Implemented; verified over the in-memory backend. Repositories live in `app/adapters/firestore/` on a `DocTxn` seam (Firestore SDK in production, in-memory store for tests and Java-free local runs). `tests/contract/test_twin_routes.py` covers isolation, 409/428, forbidden fields, and preferences ≠ entitlements, plus restart over a retained store. Emulator: `tests/emulator/test_firestore_flows.py` passes (`make test-emulator` passed 8/8 on 2026-11-05).

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

**Status:** ✅ Done (in-memory backend). `tests/contract/test_command_routes.py`: atomic write set, replay/conflict, 4 concurrent submits giving 1×202 and 3×409 `RUN_IN_PROGRESS`, foreign question/file/superseded refs rejected, stale run input rejected, cancel racing enqueue, and an injected commit failure leaving the store byte-identical with the retry succeeding. Emulator: `tests/emulator/test_firestore_flows.py` passes (`make test-emulator` passed 8/8 on 2026-11-05).

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

**Status:** 🟡 Implemented; verified over the in-memory backend. `tests/unit/test_run_worker.py` covers each crash window, duplicate delivery, live-lease retry, lease expiry and requeue, stale fencing-token commit, both cancel/commit orderings, retry exhaustion, lost enrollment, worker HTTP auth (a student token → 401), and synthetic labeling. A real `uvicorn` run (`make server-memory`) went enroll → session → message → local worker → SUCCEEDED, with a labeled synthetic reply. Gaps: (1) execution is a single bounded step per attempt, so checkpoints inside a step arrive with the LLM gateway (Step 16); (2) the Cloud Tasks adapter and Google OIDC worker auth are unit-tested against fakes only, and need verifying in staging (Step 30); (3) emulator: `tests/emulator/test_firestore_flows.py` and `test_assessment_commit.py` pass (`make test-emulator` passed 8/8 on 2026-11-05).

---

## M2 — Calculus Learning Loop (Steps 16–21)

**M2 review (2026-11-01).** Code review of Steps 16–21 against the CLAUDE.md integrity rules found four gaps, now fixed with tests:
- *Repeated questions counted as independent evidence.* `priorAttemptCount` is per session, so answering one question correctly in three fresh sessions made a skill `proficient` with coverage 1. Mastery rules are now `mastery-rules-v2`: independent evidence counts each question once, and only when its first graded attempt was correct and unassisted (`tests/unit/test_mastery.py`).
- *Student display name in the system prompt.* The name is student-editable (60 chars) and was interpolated verbatim. `prompt_safe_name` keeps only name-like characters, max 40.
- *Answer delimiter escape.* A submission could close `</student_answer>` in the grading message. The answer is now fenced with its tags neutralized (evidence is still located in the stored answer).
- *Regrade stacking.* Two regrades superseding the same assessment would both count. `commit_assessment` rejects `superseded_assessment_already_replaced` (`tests/contract/test_assessment_flow.py`).

Reviewed without changes: gateway retry/budget accounting, lease/fencing commit, transactional event sequence, SSE cursor handling, course-scoped context and skill-prefix validation. Still open for M2: 20.7 browser checks with a real model; the reviewer's decision on the parametric false credit in report-v1 §5.

### Step 16 — Implement LLMGateway with static routing and budgets

**Goal:** A controlled interface for model calls with usage tracking and budget enforcement.

- [x] 16.1 Create `app/adapters/llm/gateway.py` — `LLMGateway`:
  - Provider abstraction with typed input (system, context, messages, schema) and output (content, usage, modelVersion)
  - Start with one provider (Anthropic Claude); OpenAI added behind the same provider seam, selected per deployment
  - Capture model version and workflow version on every call
- [x] 16.2 Create `app/adapters/llm/router.py` — static `ModelRouter`:
  - Route by skill tier (fast/balanced/strong) from pack manifest
  - No decision model needed; rules-based routing
- [x] 16.3 Implement usage budgets:
  - Per-Run token budget
  - Per-Session cumulative budget
  - Per-student daily budget (including retries)
  - Budget exhaustion → pause/reject with explanation, not silent degradation
- [x] 16.4 Implement retry logic:
  - Finite retries with backoff for transient failures
  - Schema validation on output; failed validation may retry within budget
  - Never silently downgrade grading to an unevaluated model to fit budget
- [x] 16.5 Write tests:
  - Provider timeout → graceful failure
  - Schema validation failure → retry then fail
  - Budget exhaustion → clear rejection
  - Usage logging captures model version and tokens
  - Separately labeled real-provider smoke test (when configured)

**Verify:** Model calls are tracked, budgeted, and retried safely. No secrets or raw student work in logs.

**Status: ✅ implemented, verified with a scripted provider.** `app/adapters/llm/` (gateway, router, Anthropic and OpenAI providers), `app/domain/budget.py`. `tests/unit/test_llm_gateway.py` covers routing floors, timeout→backoff→graceful failure, invalid output→retry→`MODEL_OUTPUT_INVALID`, refusal/permanent errors not retried, run/session/day budget refusal before the provider is called, expiring reservations, and logs with model/tokens but no content. `tests/unit/test_llm_providers.py` drives both real SDKs over a fake HTTP transport (request shape, refusal/truncation/error mapping, no SDK retries). The real-provider smoke test (`tests/evaluation/test_real_provider_smoke.py`, opt-in `HSOS_RUN_REAL_LLM_SMOKE=1`) **passed against OpenAI** on 2026-10-31; not yet run against Anthropic (no key). Server-side refusal fallbacks are deliberately off (they would answer with an unevaluated model).

---

### Step 17 — Implement Calculus skills: Socratic guidance and rubric assessment

**Goal:** The first real learning skills — Socratic prompting and FRQ rubric assessment for calc_bc.

- [x] 17.1 Create `app/registries/subject_pack_registry.py`:
  - Load and validate pack manifests from `content/packs/`
  - Only activate packs with `availability: "active"` and verified content
  - Pin question/rubric/workflow versions per Run
- [x] 17.2 Create `app/domain/skills/socratic_guidance.py`:
  - Load minimal relevant student context (current mastery, session history)
  - Generate Socratic hints that guide without giving answers
  - Record each server-issued hint for dependency tracking
- [x] 17.3 Create `app/domain/skills/rubric_assessment.py`:
  - Load fixed rubric version for the question
  - Evaluate student answer against each rubric criterion
  - Generate evidence references (which part of student answer supports each criterion)
  - Distinguish assisted success (hints used) from independent evidence
  - Return `accepted` or `insufficient_evidence` status with reasons
- [x] 17.4 Create `app/registries/tool_registry.py`:
  - Internal tool interface: `execute(name, input, context)`
  - First tool: mathematical expression verification (optional SymPy adapter)
  - Whitelist per skill, parameter schema, scope constraints
- [x] 17.5 Create `app/domain/context_loader.py`:
  - Load reviewed material sets with source references
  - Filter by studentId/courseId/ACL before retrieval
  - Return material-not-found when index is insufficient
- [x] 17.6 Write tests using evaluation cases from Step 7:
  - Correct answer → appropriate rubric scores and evidence
  - Incorrect answer → identifies specific rubric failures
  - Hint-assisted answer → tracked as assisted, not independent
  - Irrelevant source material → rejected
  - Tool failure → handled gracefully (not fabricated success)

**Verify:** Skills produce rubric-backed assessments with evidence references. Hint dependency tracked. No fabricated tool success.

**Status: ✅ implemented; pipeline verified, model quality not yet measured.** `app/registries/subject_pack_registry.py`, `app/domain/skills/`, `app/domain/context_loader.py`, `app/domain/skill_executor.py`, `app/registries/tool_registry.py` + `app/adapters/tools/math_verify.py` (SymPy, sanitized input). Added: `answerCheck` on three questions, three draft reference materials, per-criterion `assessable` (found via the partial-parametric case: a downstream zero must not become `incorrect` evidence for another skill). `tests/unit/test_skills.py` replays all six Step 7 cases through the real pipeline with a scripted model and checks evidence refs, derived skill evidence and hint handling, plus verifier agreement/disagreement, tool unavailable, ACL-filtered retrieval and material-not-found, version pinning. Production withholds draft content (`HSOS_REQUIRE_REVIEWED_CONTENT`).

---

### Step 18 — Implement AssessmentService: atomic evidence commit

**Goal:** Assessment results, mastery updates, events, and Run completion happen in one transaction.

- [x] 18.1 Create `app/domain/assessment_service.py` — `commit_assessment()`:
  - Validate evidence semantically (not just JSON shape): question ownership, rubric version, evidence references, student answer, tool results, hint records
  - In one transaction: save Assessment + mastery projection + Run terminal state + domain events + outbox entries
  - `insufficient_evidence` → can show limited feedback but does NOT update mastery
  - Use unique evidence application ID — same evidence cannot be applied twice
  - Regrade: `supersedesAssessmentId` replaces earlier evidence contribution
  - Consecutive corrections after hints are NOT counted as independent evidence
- [x] 18.2 Create `app/domain/mastery_service.py`:
  - Project mastery from accepted assessments
  - Track: skill level, independent evidence count, coverage, uncertainty
  - Mastery is derivable from assessments (can be rebuilt)
- [x] 18.3 Create `app/domain/assessment_service.py` — `complete_session()`:
  - Check: no active Run, accepted assessment exists, task completion rules met
  - In one transaction: Session → COMPLETED, Task → COMPLETED, events
  - Does NOT re-apply mastery (summary only, no double-counting)
  - `abandon()`: Session → ABANDONED, Task back to PLANNED; requires no active Run
- [x] 18.4 Create API routes:
  - `GET /api/assessments/:assessmentId`
  - `GET /api/assessments?sessionId=...&cursor=...`
  - `GET /api/mastery?courseId=...&cursor=...`
  - `POST /api/sessions/:sessionId/complete` + Idempotency-Key
  - `POST /api/sessions/:sessionId/abandon` + Idempotency-Key
- [x] 18.5 Write tests:
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

**Status: ✅ implemented, verified over the in-memory backend.** `app/domain/assessment_service.py`, `app/domain/mastery_service.py`, `app/domain/types/mastery.py`, routes in `app/api/routes/assessments.py` + `POST /sessions/:id/complete`. `tests/contract/test_assessment_flow.py` covers the full loop, crash at commit (nothing written, recovery finishes once), stale fencing token, replayed commit, cancellation during grading, insufficient_evidence, complete idempotency / `RUN_IN_PROGRESS` / `COMPLETION_REQUIREMENTS_NOT_MET`, isolation, budget exhaustion, invalid output, rejected drafts, correction after feedback, prediction still `unavailable`. `tests/unit/test_mastery.py` covers idempotent apply, regrade replacement and rebuild = incremental. Regrade exists at the domain level only (no public trigger yet). `tests/emulator/test_assessment_commit.py` passes (`make test-emulator` passed 8/8 on 2026-11-05).

---

### Step 19 — Implement durable event feed (SSE + polling)

**Goal:** Frontend receives real-time updates from persistent events, with reconnection and replay.

- [x] 19.1 Create `app/adapters/firestore/event_repository.py`:
  - Per-student monotonic sequence assignment (in transaction)
  - `listEvents(actor, afterSequence, limit)` — paginated, ordered by sequence
  - Filtered projection: exclude internal outbox, raw model reasoning, credentials, private tool params
- [x] 19.2 Create `app/api/routes/events.py`:
  - `GET /api/events?after=...&limit=50` → paginated events
  - `GET /api/events/stream?after=...` → SSE stream:
    - Replay persisted events from `after` sequence
    - Continue with new events
    - Heartbeat at configured interval
    - Close before deployment timeout; client reconnects
    - `Last-Event-ID` supported; inconsistency with `after` → 400
    - Expired cursor → 410 `EVENT_CURSOR_EXPIRED`
- [x] 19.3 Use `Authorization: Bearer` header for SSE (not token in URL)
- [x] 19.4 Support polling fallback using same sequence/dedup logic
- [x] 19.5 Write tests:
  - Events arrive in sequence order
  - Reconnect replays missed events
  - Expired cursor → 410, client re-fetches snapshot
  - Cross-student event access → 404
  - Heartbeat sent within timeout
  - Duplicate event IDs deduplicated by client

**Verify:** Events are durable, ordered, and replayable. SSE reconnect works. Polling fallback works. Cross-student isolation enforced.

**Status: ✅ implemented, verified over the in-memory backend.** `app/domain/event_feed.py`, `app/api/routes/events.py`. `tests/contract/test_event_routes.py`: ordering/pagination/replay, filtered payload projection, 410 expired cursor (purge floor `eventState.oldestRetainedSequence`; no purge job yet — M4 Step 31), foreign cursor 400, isolation, SSE replay + heartbeat + close, `Last-Event-ID` precedence/conflict, Bearer-only auth, close at token expiry. Client dedupe is the existing `mergeEvents` test. SSE was exercised through httpx's ASGI transport (buffered), not a real long-lived connection behind Cloud Run.

---

### Step 20 — Connect frontend to real API with course-driven workspace

**Goal:** The web frontend uses the real API for the Calculus learning flow, end-to-end. The workspace is driven by enrolled courses.

- [x] 20.1 Implement the async data providers defined in Step 6:
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
- [x] 20.2 Implement the course-driven workspace:
  1. Login → fetch twin, entitlements, enrolled courses
  2. Show enrolled courses in sidebar; each course shows its agent
  3. Course catalog available for browsing/enrolling new courses
  4. Selecting a course opens the per-course agent chat view
- [x] 20.3 Implement the per-course agent learning flow:
  1. Open course → see agent chat + course tasks
  2. Select task → create session (agent conversation begins)
  3. Chat with agent → ask questions, get Socratic guidance
  4. Type answer → submit → see "grading..." (Run QUEUED → RUNNING)
  5. Receive assessment feedback (Run SUCCEEDED, assessment displayed)
  6. Complete session when eligible
- [x] 20.4 Handle all Run states visually: QUEUED, RUNNING, WAITING_INPUT, SUCCEEDED, FAILED, CANCELLED
- [x] 20.5 Implement SSE event subscription with reconnect and polling fallback
- [x] 20.6 API errors show truthful state (not demo data substitution)
- [ ] 20.7 Test in browser:
  - Submit answer → see real feedback
  - Close/reopen browser during grading → state recovered
  - Network error → retry with same Idempotency-Key
  - SSE reconnect after disconnect

**Verify:** End-to-end Calculus flow works in browser. Grading produces rubric-backed feedback. State survives browser refresh and network interruption.

**Status: 🟡 implemented; browser-verified with synthetic execution only.** `web/js/auth.js` (Firebase Auth or labeled localhost emulator sign-in for synthetic students), provider commands with per-action Idempotency-Keys, `createEventSubscription` (SSE over fetch + Bearer, `Last-Event-ID`, polling fallback, 410 → reload), `web/js/agents/course_session.js`, real enroll/unenroll. `web/tests/api-flow.test.js` (10 tests) covers key reuse on retry, answers-only bodies, SSE parsing, reconnect cursor, polling fallback, expired cursor, auth modes. In Chrome against `make server-memory`: sign-in → start session → submit → Run QUEUED→RUNNING→SUCCEEDED with the labeled synthetic reply and live events → reload restores the session, Complete stays blocked (no accepted assessment). **Not yet seen in a browser:** real rubric feedback (a model key is now available for OpenAI), network-error retry and SSE reconnect (unit-tested only).

---

### Step 21 — Run Calculus evaluation; add file upload only after text works

**Goal:** Measure learning quality against evaluation baseline. Optionally add file/OCR support.

- [x] 21.1 Run the evaluation cases from Step 7 through the real system:
  - Compare rubric assessment output against human annotations
  - Track: false acceptance rate, false insufficient rate, evidence quality, feedback usefulness, per-assessment cost
- [x] 21.2 Record results in `content/evaluation/calc_bc/report-v1.md`:
  - Per-case comparison with expected outcome
  - Aggregate metrics for each evaluation dimension
  - Identified weaknesses and improvement areas
- [ ] 21.3 (Optional) Implement file upload if included in pilot:
  - `POST /api/files` → signed upload URL
  - `POST /api/files/:fileId/complete` → validation
  - `GET /api/files/:fileId` → status
  - `GET /api/files/:fileId/download` → scoped download URL
  - OCR: preserve original + recognized text; ambiguous text → student confirmation before assessment
- [x] 21.4 If file/OCR deferred: document that pilot is text-only; disable upload UI

**Verify M2:** Full Calculus loop works with evaluated skill. No unsupported progression, false official score, duplicate evidence, or unauthorized file access. Evaluation report records quality with sample sizes and identified limitations.

**Status: 🟡 first real-model run done (draft content); reviewer sign-off pending.** On 2026-11-01 `scripts/run_calc_evaluation.py` ran all 6 cases against OpenAI `gpt-5.5-2026-04-23` through the production pipeline and wrote `content/evaluation/calc_bc/report-v1.md`. Two consecutive runs gave the same results: rubric accuracy 17/18; status 6/6 correct (0/2 false acceptance, 0/4 false insufficient); hint tracking 1/1; ~1.7–1.8k tokens per case. **The one miss repeats in both runs:** `eval-calc-partial-parametric` gets credit on `second-derivative-method` (expected 0, got 1) even though the student never divided by dx/dt. This is a false credit on a method criterion, which math-verify cannot catch because it checks only the final answer. Whether to fix the prompt or rubric, narrow scope, or accept it is the reviewer's call in report §5. The runner now names mismatched criteria in the notes. The thresholds are unset, content is still `draft` and n = 6, so these figures are indicative only. The run used OpenAI, not Anthropic (no key). File upload/OCR is deferred: the pilot is text-only and has no upload UI.

---

## M3 — Course Platform: Package Contract and Course-Agnostic Loop (Steps 22–27)

**Direction change (2026-11-01).** The platform no longer infers weaknesses in one course from evidence in another. Cross-course prerequisite mappings (Calc BC → Digital SAT), `prerequisite.*` events and the findings view are dropped. The goal is now a platform on which **third parties add courses as data** (skills, question bank, rubrics and criteria, course requirements, completion criteria), choosing from abilities the platform provides. Every course runs on the same runtime. Courses are independent: evidence in one course never changes another course's record or tasks.

Decisions behind this milestone:
- **Data only.** A course package contains no code. New ability types (e.g. code grading, essay feedback) are platform work, added once and then available to every course.
- **Platform review gate.** A package is validated automatically, then approved by a platform reviewer before it can become `active`. Authors cannot self-publish.
- **Keep the generic M3 work.** The M3 change built consumers, outbox wakes, the planner, key-scored choice items and task fields that are course-agnostic; those stay. The cross-course mapping layer is removed in Step 22.
- **Pilot:** Calc BC (first-party reference course) plus **Digital SAT** as the second course, rebuilt only through the authoring path (Step 27).

### Step 22 — Define the course package contract v1 and remove cross-course mappings

**Goal:** One versioned, documented, data-only format that fully describes a course, and a validator that accepts or rejects a package with actionable errors.

- [~] 22.1 Contract first (package format v1 done for authored packages, see Step 26; course requirements and completion-rule types still missing): write the package schema in `app/schemas/` and document it (new `doc/COURSE_PACKAGE.md`; update API.md/BACKEND.md). A package contains:
  - Manifest: courseId, version, title/description, publisher (author org), content license, availability, model tier ceiling, abilities used and their settings, tool whitelist (from the platform catalog only)
  - Skill taxonomy: skill IDs, names, optional prerequisite edges **within the course**
  - Question bank: versioned questions with source/license, skills tagged, answer format (free response / choice items), rubric or answer-key reference
  - Rubrics and criteria: criterionId, maxPoints, evidence requirements, skill per criterion, version
  - Course requirements: e.g. recommended weekly minutes, known exam/assignment dates with a source, enrollment eligibility
  - Completion and mastery criteria: what counts as an accepted assessment and when a task or the course is complete, expressed with platform-defined rule types and parameters (no expressions or code)
  - Evaluation set: annotated cases the course must pass before review
- [~] 22.2 Validator (done for authored packages: all errors with paths, cross-course references, ability data, license, unknown fields; `app/registries/package_validator.py`): schema check plus cross-reference checks (every question's skills and rubric exist, criteria map to skills, abilities have the data they need, answer keys never in student-facing fields, license present, no unknown fields). Returns all errors with paths, not just the first.
- [ ] 22.3 Re-express `calc_bc` in the v1 format; the runtime loads only through the validated contract. (`dsat` is rebuilt through the authoring path in Step 27.)
- [x] 22.4 Remove the cross-course layer: `content/mappings/`, the mapping registry, `prerequisite_service` mapping rules, the `prerequisite-mapper` consumer's cross-course logic, `prerequisite.*` events and payloads, `/api/prerequisites`, the findings card, and the prerequisite evaluation cases. Keep the event feed contract backward compatible where events were already stored (or document the cut, since no real student data exists).
- [ ] 22.5 Tests: valid packages load; each class of invalid package is rejected with the right error path; a package cannot reference another course's skills or content; contract parity between schema, domain types and docs.

**Verify:** Calc BC runs end to end from a validated v1 package. No code path depends on a specific courseId. No cross-course effect remains.

**Status: 🟡 22.4 done (2026-11-01); 22.1–22.3 and 22.5 not started.** Removed: mapping content and registry, prerequisite rules/service/types/repository, the three cross-course consumers, `/api/prerequisites`, `prerequisite.*` events and payloads, `PREREQUISITE_*` task reasons, the planner's `confirmed_prerequisite` priority, prerequisite evaluation cases and the `prerequisite-precision` dimension, and the web findings card. API.md §6.2 and BACKEND.md updated first. Kept and made generic: the consumer infrastructure (subscriptions now come from the consumers registered at startup — none in production yet), the planner, and answer-key scoring, renamed `sat-diagnostic` → `choice-scoring`. Digital SAT became an independent course: four choice sets (`q_dsat_equiv_001/002`, `q_dsat_nonlin_001/002`, still draft), new task type `PRACTICE`, Alex enrolled with two seeded practice tasks. Tests: `tests/contract/test_dsat_course.py` (key-scored loop, no model call, no answer key to the client, no cross-course effect, access/isolation, removed route 404), `tests/contract/test_event_consumers.py` (consumer guarantees with a test-only consumer), `tests/unit/test_choice_scoring.py`, `tests/unit/test_content.py` (no cross-course content). Groundwork for 22.1–22.2: pack manifests and question/rubric registries with cross-checks (`app/registries/content.py`).

---

### Step 23 — Platform ability catalog

**Goal:** The runtime offers a fixed, versioned set of abilities that any course package can select and configure; nothing is course-specific.

- [ ] 23.1 Define the catalog: each ability's ID, version, the package data it requires, its settings, model tier floor and the evidence it produces. Initial abilities (`choice-scoring` already exists as a generic ability):
  - `socratic-guidance` (hints, records hint usage)
  - `rubric-assessment` (model grading against the course rubric, evidence validated by AssessmentService)
  - `choice-scoring` (answer-key scoring, no model) — generalizes the M3 `sat-diagnostic` key scoring
  - `diagnostic` (short skill check with course-defined thresholds → supported / unsupported / inconclusive for a skill **in the same course**)
- [ ] 23.2 Abilities read only the package's data and the student's record for that course. Course text in prompts is treated as content, not instructions (prompt-injection checks on author-supplied text).
- [ ] 23.3 Per-course model budget and tier ceiling from the manifest, enforced by the LLM gateway.
- [ ] 23.4 Tests: each ability on two different courses with no code change; missing required data → package rejected at validation, not at runtime; author text cannot change grading rules or reveal answer keys.

**Verify:** Two courses that select the same ability behave identically apart from their data.

**Status: 🟡 partly implemented.** Socratic guidance, rubric assessment and `choice-scoring` exist (`app/domain/skill_executor.py`, `app/domain/skills/`); the catalog contract, the in-course `diagnostic` ability, per-course budget and injection checks are not built.

---

### Step 24 — Replay-safe domain event consumers (course-internal)

**Goal:** Events drive follow-up actions atomically and idempotently, using rules each course declares as data.

- [x] 24.1 Consumer infrastructure: `publish()` writes a `kind=consumers` outbox wake in the same transaction as the event; per-consumer offsets; receipts `(consumer, eventId, target)` written with the effect; one subscribed event per transaction; stale-wake recovery
- [ ] 24.2 Replace the cross-course consumers with course-internal ones driven by the package's follow-up rules: e.g. repeated independent errors on a skill → a diagnostic for that skill or its in-course prerequisite; supported diagnostic → follow-up practice; unsupported/inconclusive → reason recorded, no practice
- [ ] 24.3 Domain dedupe per (course, skill): repeated observations do not flood active diagnostics or practice
- [x] 24.4 Reliability tests for the infrastructure (`tests/contract/test_event_consumers.py`, test-only consumer): crash before commit → retry applies exactly once; duplicate wakes and full-log replay → no change; lost wake → recovery; two-student isolation; no consumer registered → no wake
- [ ] 24.5 Tests for the course-internal rules, run on two courses with different rule parameters

**Verify:** Exactly one intended task per dedupe scope; no effect ever crosses into another course.

**Status: 🟡 infrastructure implemented (M3); no production consumer.** `app/workers/consumers/` (runner, receipts, offsets), `EventPublisher`, outbox `kind`, `/internal/consumers/process` and `RecoveryService.reissue_stalled_wakes` are kept; the Calc→SAT consumers were removed (Step 22.4). Course-internal rules (24.2) are next. Emulator variant: `tests/emulator/test_consumers_and_planning_emulator.py` passes (`make test-emulator` passed 8/8 on 2026-11-05), alongside the `course-metrics` consumer (Step 34.4).

---

### Step 25 — Evidence-aware incremental planning across enrolled courses

**Goal:** One planner schedules tasks from every enrolled course within the student's time, respecting student controls and each course's requirements.

- [x] 25.1 `planner_service.build_plan` (planner-rules-v1): 7-day horizon, weekly minutes / 7 per day; priority deadline > diagnosed need > evidence gap > practice; fixed/kept/moved/deferred/over-budget placements, each with an explanation citing real events
- [x] 25.2 `POST /api/plans/replan` + Idempotency-Key → 202 PLANNING run; `GET /api/plans/latest|{id}`
- [x] 25.3 Student controls: reschedule (implies lock unless the same patch says otherwise), lock, skip with reason
- [ ] 25.4 Read course requirements from packages: dated items (exams, assignments) with their source become deadlines; recommended weekly minutes inform the split
- [ ] 25.5 Fair split across courses when the week is full, explained to the student
- [x] 25.6 Tests: full week defers, conflicting deadlines, locks preserved, conservative without evidence, concurrent replans consistent, crash at commit leaves nothing
- [ ] 25.7 Tests for multi-course balancing and package-sourced deadlines
- [x] 25.8 Practice top-up (2026-11-07): packages may declare a `practiceSequence`; in every planning commit and when a session completes, each enrolled student is kept at 2 unfinished tasks per course with the next sets in the package's order they have never had (reason `NEXT_PRACTICE`); students enrolled before an upgrade receive the new version's sets. `app/domain/practice_queue.py`; tests `tests/contract/test_practice_sequence.py`

**Verify:** Planning is incremental, respects time budgets and student choices, and explains every placement.

**Status: 🟡 core implemented (M3); practice top-up (25.8) added 2026-11-07, verified locally (633 tests, emulator 8/8) and on staging with Digital SAT 2.0.1 ([OPERATIONS.md](OPERATIONS.md) §5).** Found on staging: students only ever received a course's starter tasks, so 10 of Digital SAT 2.0.0's 12 sets reached no one. Known: an in-progress task dated before today is not listed in the 7-day plan. Not built: package-sourced deadlines (no due dates are set by any flow yet) and cross-course balancing. The `confirmed_prerequisite` priority was removed (Step 22.4); priorities are now deadline > evidence gap > practice.

---

### Step 26 — Author role, review gate and publishing

**Goal:** A third-party author can submit a course; only platform-approved versions reach students.

- [x] 26.1 Identities and roles: `platformMembers/{uid}` → `PlatformActor` (role `author` with an `orgId`, or `platform_reviewer`), a separate type from `ActorContext` with no `studentId`; permissions `packages:author` / `packages:review`. Students get 403 on authoring/review routes; platform members get 403 on student routes.
- [x] 26.2 Submission: `POST /api/authoring/packages` → validator report → `draft`; `.../submit` → `submitted` (409 `PACKAGE_INVALID` if the report has errors). Other organizations' packages return 404; a courseId owned by another organization or a bundled course → 409 `COURSE_ID_TAKEN`.
- [x] 26.3 Review workflow: `draft → submitted → approved → active` (+ `rejected`, `superseded`, `retired`). Approval records reviewer, time, notes, license and model-evaluation attestations; requires a valid report and every key-scored evaluation case passing. Only active versions appear in the catalog. Every transition is in the version's `history`.
- [x] 26.4 Versioning: Sessions pin `contextVersion.pack`; the registry serves pinned versions (`superseded`/`retired`) for open sessions and past assessments; an older version cannot replace a newer active one. Retire stops new enrollments, sessions and commands (409 `COURSE_NOT_AVAILABLE`) and keeps all records readable.
- [x] 26.5 Entitlements stay platform-managed and are now per courseId (`apCourses` + new `courses`, replacing the `dsat` flag): a package's category never grants access. Package records live outside student subtrees.
- [x] 26.6 Tests: `tests/contract/test_package_review.py` (gate end to end with audit trail, org isolation, role enforcement, invalid package, approval requirements, rejection and immutability, idempotency, version pinning across an upgrade, retire with an open session, no student data in author views), `tests/unit/test_package_validator.py`.

**Verify:** A package goes from upload to `active` only through validation plus reviewer approval, and every state change is auditable.

**Status: ✅ implemented and verified over the in-memory backend (2026-11-01).** Contract: [COURSE_PACKAGE.md](COURSE_PACKAGE.md), API.md §6.3, BACKEND.md §2–3. Code: `app/schemas/package.py`, `app/registries/package_validator.py`, `app/registries/package_sync.py`, `app/domain/package_service.py`, `app/adapters/firestore/package_repository.py`, `app/api/routes/packages.py`. The validator covers what the gate needs from Step 22.1–22.2 (manifest incl. publisher/license, skills, rubrics, questions, materials, starter tasks, evaluation set; all errors with paths); course requirements (dated items, weekly minutes) and completion-rule types are not in the contract yet. Not done: emulator run (no emulator verification on this machine), an admin entitlement tool (tests write the access document directly), author-facing UI (API only), prompt-injection checks on author text beyond the template-variable whitelist (Step 23.2). Multi-instance freshness relies on a 30 s refresh window (`HSOS_PACKAGE_REFRESH_SECONDS`).

---

### Step 27 — Prove the shared runtime with an authored Digital SAT course; course-driven frontend

**Goal:** Evidence that a new course needs data only.

- [x] 27.1a Second course chosen (2026-11-01): **Digital SAT**. Its current draft content (four choice sets) was converted by hand in Step 22.4 and does not count as authored.
- [x] 27.1 Digital SAT rebuilt as `server/content/authored/dsat/package.json` (v1.0.0, owned by `org_hsos_content`); `content/packs/dsat` removed. No Digital SAT code in `server/app/` or `web/js/` (the old `PACK_META.dsat` entry was removed; it renders from course data).
- [x] 27.2 `tests/contract/test_authored_course_loop.py`: from a platform with no Digital SAT, the package file goes through upload → report (12/12 evaluation cases) → submit → approve → activate over the API; a synthetic student gets access, enrolls (starter tasks created), runs a Digital SAT set (key-scored, no model) and a Calc BC answer (model-graded) side by side; mastery stays per course; one plan covers both. Follow-up (24.2) is not built, so the loop stops at the plan.
- [x] 27.3 Frontend: skill names from `GET /api/courses/{id}/agent` `skills` (assessment card, mastery list with course label), plan entries labelled per course, generic "Exam prediction" label, course events show course names, choice vs free-response answer forms from the session activity. Findings card already removed. Criterion descriptions are not in the assessment API yet, so rubric lines show criterion ids. Demo-mode preview panels (`agents/dsat.js`) are untouched.
- [x] 27.4 Authoring record: converting the existing draft content took one script plus writing 12 evaluation cases; first validation passed. Platform gaps found and fixed as platform/contract changes, not course code: (1) nothing created tasks for a newly enrolled course → `starterTasks` in the contract; (2) category-based SAT entitlement let an author's category choice grant access → per-courseId grants; (3) the client could not name skills → `skills` on the agent view; (4) one loaded version per course → versioned registry for pinning.
- [x] 27.5 Browser check (2026-11-01, `make server-memory` + `make web`, Chrome): Alex opened a Digital SAT task, answered the choice set, saw an accepted assessment with package skill names, and replanned; the plan listed both courses; no console errors. Enrollment-through-completion for a *newly* authored course in the browser was not exercised (no admin UI to grant access); the API test covers it.

**Verify M3:** The second course reaches `active` and works end to end with no platform code change made for it; Calc BC still passes its regression and evaluation cases; isolation and replay checks pass for both courses.

**Status: ✅ 27.1–27.5 implemented (2026-11-01).** Digital SAT content is still `draft` (no named content reviewer), so `HSOS_REQUIRE_REVIEWED_CONTENT` would withhold it. Local seeding installs the package as active with an audit trail labelled `seed:local-dev`, not a platform review. M3 overall still needs Steps 22.3, 23, 24.2–24.5 and 25.4–25.7.

---

## M4 — Proactive Planning and Pilot (Steps 28–33)

### Step 28 — Implement timezone-aware scheduled planning

**Goal:** Daily planning runs automatically for each student at the right local time.

- [x] 28.1 Create `app/workers/scheduler/planning_scheduler.py`:
  - Cloud Scheduler trigger → scan students with `dueAt` ≤ now
  - Calculate local date using student's IANA timezone
  - Deduplicate: `studentId + localDate + planningReason`
  - Handle DST transitions correctly
- [x] 28.2 Persist `nextDueAt` per student
- [x] 28.3 Use the same Planner for scheduled and event-driven updates
- [x] 28.4 `GET /api/tasks` has no hidden mutation (read-only)
- [x] 28.5 Write tests:
  - DST boundary (spring forward / fall back)
  - Timezone change by student
  - Duplicate scheduler invocations → no duplicate planning
  - API/worker downtime → catch-up on recovery
  - Overlapping assessment-driven and scheduled replanning → consistent

**Verify:** Scheduled planning respects timezones and DST. No duplicate plans from duplicate triggers.

**Status:** ✅ Implemented 2026-11-01, verified over the in-memory backend. `app/domain/planning_schedule.py`, `app/domain/local_time.py`, `app/workers/scheduler/planning_scheduler.py`, worker route `POST /internal/planning/schedule`. The schedule lives on `planState/current` (`nextDueAt`, `timezone`, `lastScheduledLocalDate`); it starts at first enrollment (and in the seed), and a timezone change recomputes it. Dedupe is per local date and the scheduled run id is per student and date. `tests/contract/test_scheduled_planning.py` (14 tests) covers one pass per local day in two timezones, concurrent and duplicate invocations, catch-up after three missed days, crash after queueing, spring-forward and fall-back days, travel across timezones without planning a day twice, coalescing with a pending student replan, 409 for a student replan during a scheduled run, GETs never planning, and service-only auth. Writing these tests caught a real bug: the first deterministic run id did not include the student, so two students' scheduled runs would have collided on the Cloud Tasks task name. `Plan.trigger` and `plan.updated.reason=scheduled` were added to the contract. Firestore collection-group index on `planState.nextDueAt` is declared but untested until staging.

---

### Step 29 — Implement student controls and opt-in reminders

**Goal:** Students can defer/skip/lock tasks and opt into one reminder channel.

- [x] 29.1 Implement task controls in UI:
  - Defer: change scheduledDate via PATCH
  - Skip: set status to SKIPPED (only from PLANNED)
  - Lock: set studentLocked = true (preserved during replanning)
- [x] 29.2 Create `app/domain/reminder_service.py`:
  - Record consent, quiet hours, frequency caps
  - Delivery dedupe keys per channel/task/time-window
  - Check consent again immediately before sending (queued reminder can become ineligible)
  - Default: no parent notification
- [x] 29.3 Create fake delivery adapter for tests; real delivery only to designated test recipients
- [x] 29.4 Write tests:
  - Opt-out after enqueue → reminder not sent
  - Quiet hours → reminder deferred
  - Repeated delivery → deduplicated
  - Changed deadline → reminder updated
  - Completed task → no reminder
  - Student control persistence across restarts

**Verify:** Student controls work correctly. Reminders respect consent, quiet hours, and frequency caps.

**Status:** ✅ Implemented 2026-11-01, verified over the in-memory backend. UI: lock/unlock and skip-with-reason next to the existing reschedule control; a reminder opt-in card (one channel, quiet hours). Design choice: one daily digest reminder per student, channel and local date, worded at send time, rather than one per task. `app/domain/reminder_service.py`, consent record `consents/notifications` written by the twin patch, `app/adapters/notifications/senders.py` (fake sender + test-recipient guard), worker route `POST /internal/reminders/deliver`. The contract now allows at most one channel. `tests/contract/test_reminders.py` (15 tests) covers delivered once, opt-out after creation, consent re-check, quiet hours (deferred, skipped if they last until the day ends, never created inside them), crash after send with no second message, retries then give up, a task moved to another day and a completed task (no reminder), expiry after downtime, weekly cap, test-recipient guard, off without a sender, consent recording, and controls surviving a restart. Gap: there is no real delivery channel. Staging uses the fake sender behind the test-recipient guard, and production refuses the fake.

---

### Step 30 — Deploy to staging (Cloud Run, Firestore, Cloud Tasks)

**Goal:** The application runs in a real cloud environment, not just emulators.

- [~] 30.1 Create deployment configuration:
  - Cloud Run service for API
  - Cloud Run service for worker
  - Firestore database (separate from other projects)
  - Cloud Tasks queues
  - Cloud Scheduler jobs
  - Cloud Storage bucket
  - Secret Manager for credentials
- [~] 30.2 Configure service identities and IAM:
  - API and worker have separate service accounts
  - Worker invocation requires OIDC with correct audience
  - Students cannot call worker endpoints
- [x] 30.3 Remove emulator hosts and synthetic providers from production config
- [~] 30.4 Configure timeouts, retries, and SSE reconnect for cloud environment
- [x] 30.5 Record which infrastructure checks ran and which resources were unavailable

**Verify:** Real Cloud Tasks OIDC works. Cross-instance recovery works. Request timeout handling correct. Finite cost limits configured.

**Status:** ✅ **Deployed 2026-11-03** to project `hs-student-os` (Firestore `nam5`; Cloud Run, Tasks, Scheduler in `us-central1`; OpenAI key in Secret Manager; web on Firebase Hosting). A smoke test with synthetic users passed end to end through real Firebase Auth, Firestore, Cloud Tasks (OIDC), the private worker and the model (record in [OPERATIONS.md](OPERATIONS.md) §5). Deploying exposed four bugs no local test could catch, all fixed: missing composite indexes (neither the in-memory store nor the emulator enforces indexes), the OpenAI SDK failing at construction in the key-less API service, the worker needing its own URL before its first deploy, and alert policies needing gcloud alpha. Scheduler job execution logs, alert delivery and a managed-backup restore are not yet checked. The deployed image predates M5. Original configuration notes: `server/Dockerfile` (one image, API or worker by `HSOS_ASGI_APP`, non-root, no fixtures) was built and smoke-checked locally. `deploy/staging/provision.sh` covers APIs, Firestore and daily managed backups, separate service accounts and IAM, secrets, buckets, the queue, both Cloud Run services, six OIDC Scheduler jobs, log-based metrics, alert policies and a billing budget. It is a dry run unless `APPLY=1` and refuses `demo-*` projects. `tests/unit/test_deploy_config.py` checks that the staging env files pass the deployed-config checks and that every Scheduler job targets an existing worker route. Finding: the default run lease (120 s) was shorter than the worst model call (60 s × 3), so deployed configs now must have lease > timeout × attempts (staging uses 300 s). The Verify criteria need a real staging project; the record of what ran is in [OPERATIONS.md](OPERATIONS.md) §5.

---

### Step 31 — Add operations monitoring and backup/restore

**Goal:** The system is observable and recoverable.

- [x] 31.1 Implement structured logging:
  - Actor/run ID, model tier, latency, tokens, retries, error codes
  - Exclude: raw student answers, drafts, tokens, private tool payloads
- [x] 31.2 Implement metrics:
  - Assessment latency and cost
  - Worker failures and outbox backlog
  - Duplicate suppression count
  - Learning quality regressions
- [x] 31.3 Set up alerts for: worker failure rate, outbox backlog growth, budget overruns
- [x] 31.4 Create and test backup/restore procedure:
  - Backup synthetic student with linked files, assessments, and event state
  - Restore into separate test environment
  - Verify all linked data is consistent after restore
- [x] 31.5 Verify delete/retention effects on indexes, artifacts, and future backup expiry

**Verify:** Simulated alerts fire correctly. Restore produces consistent state. Data deletion is clean.

**Status:** ✅ Implemented 2026-11-01, verified over the in-memory backend. `app/adapters/observability.py`: JSON logs whose strings pass only under allowlisted keys and whose exceptions log type and frames only; log-based `LogMetrics`; request metrics. `app/domain/ops_monitor.py` covers outbox backlog, worker failures and budget overruns (route `/internal/ops/check`). `app/domain/retention.py` purges events and raises the purge floor (route `/internal/retention/events`). `app/adapters/firestore/backup.py` + `scripts/student_data.py` do export, restore (refuses deleted students and foreign documents), link-consistency verify, and delete with a tombstone. Delete support was added to the `DocTxn` seam. Tests: `tests/unit/test_observability.py`, `tests/contract/test_operations.py`: alerts fire and clear; a full learning flow is exported, restored into a separate store, verified, and read back identically through the API; deletion leaves nothing for any service scan; retention expires old cursors with 410 and keeps the record. Not verified: the Firestore SDK path (`tests/emulator/test_backup_emulator.py` skips without Java), managed backup restore, and real alert delivery. There is no online learning-quality metric; quality is measured offline by the evaluation set.

---

### Step 32 — Full integration testing in staging

**Goal:** All M0–M3 acceptance chains, including authoring and publishing, run in the cloud environment.

- [x] 32.1 Run the complete Calculus learning loop in staging
- [ ] 32.2 Run the authored pilot course end to end in staging, side by side with Calc BC, including in-course follow-up chains (supported + unsupported + inconclusive) — side by side done; follow-up chains blocked on Step 24.2
- [x] 32.2a Run the authoring path in staging: upload → validation report → review → active → version upgrade with an open session
- [x] 32.3 Test SSE reconnection across Cloud Run instances
- [x] 32.4 Test worker crash recovery in cloud
- [ ] 32.5 Test cross-student isolation for all resources: sessions, events, files, assessments — done except files (not implemented)
- [x] 32.6 Verify: no duplicated progress, restart recovery, truthful failed/waiting states

**Verify:** All chains pass in staging with real infrastructure. Cloud-specific issues (OIDC, timeouts, instance rotation) handled.

**Status:** 🟡 Run on 2026-11-07 against `61dfda6` plus two fixes (image `61dfda6-dirty-20261107`), with synthetic users through real Firebase Auth, Firestore, Cloud Tasks, Scheduler and OpenAI `gpt-5.5-2026-04-23`. Record in [OPERATIONS.md](OPERATIONS.md) §5. Passed: 32.1, 32.2a, 32.3 (four instances, contiguous resume), 32.5 (no files), 32.6, and the 32.2 side-by-side part. Not run: 32.2 follow-up chains (Step 24.2 not built), files (not implemented), Cloud Run request timeout. 32.4 passed: a Run left RUNNING with an expired lease and no queue task was requeued by the Scheduler recovery job and finished once (attempt 2, 89 s); a worker revision rollover mid-run also finished once. Staging found two defects no local test caught, both fixed with regression tests: (1) a worker whose package copy predated an activation failed Runs as non-retryable `SESSION_NOT_OPEN` for up to 30 s (`ensure_version` was never called); (2) re-running `seed_staging` reset per-student event sequences, duplicating sequence numbers and making `course-metrics` skip events (staging counters repaired, nothing deleted). Open observations: SSE streams outlive client disconnects behind Cloud Run (to the 300 s cap), and requests in the ~30 s after a revision rollover can get a front-end 5xx.

---

### Step 33 — Apply the external pilot gate

**Goal:** Decide whether the system is ready for real students.

- [ ] 33.1 Quality gate:
  - Reviewed rubric feedback accuracy
  - Unsupported-answer behavior (no false acceptance)
  - Each pilot course package approved through the review gate, with its evaluation set passing
  - In-course follow-up rules checked (supported + unsupported cases)
  - Independent follow-up performance measurement
  - Plan explanations are comprehensible
- [ ] 33.2 Reliability gate:
  - No duplicated progress
  - Restart recovery confirmed
  - Events are replayable
  - Failed/waiting states are truthful
- [ ] 33.3 Access gate:
  - Auth and student isolation verified across all resources
  - Entitlements cannot be self-granted (by students or authors)
  - Authors cannot see student data or other organizations' packages
  - No default parent access to private material
- [ ] 33.4 Operations gate:
  - Model budget limits enforced
  - Opt-in reminders with working consent controls
  - Cloud authentication and timeouts configured
  - Backup/restore tested
- [ ] 33.5 Record: sample sizes, thresholds, reviewer sign-off, unresolved limitations
- [ ] 33.6 If scope is text-only (no file/OCR), document explicitly

**Status:** ❌ Gate recorded as **not passed** in [PILOT_GATE.md](PILOT_GATE.md), with evidence and gaps for every item; the pilot is text-only (33.6). No real students.

**Verify M4:** All gates pass or have documented exceptions. Real students enter only after gates pass. Documentation updates alone never mark these steps complete.

---

## M5 — Optional Expansion After Pilot Evidence (Steps 34–43)

Each extension is independently selected and verified. None are prerequisites for the pilot.

**2026-11-04:** all five steps were implemented at the owner's request, before the pilot gate passed and while M3 Steps 22.3, 23, 24.2 and 25.4 are still open. Everything below is verified over the in-memory backend with synthetic data and, where a model is involved, a scripted provider. Nothing in M5 is deployed to staging yet, and nothing here is evidence of learning quality. `make check` after M5: ruff clean, `mypy app/` strict clean, backend **620 passed, 9 skipped**, web **39 passed**.

### Step 34 — Grow the course catalog through the authoring path

- [x] 34.1 Author-facing web portal: upload, validator report, preview as a student, submission status and reviewer notes (M3 ships the API only)
- [x] 34.2 New platform abilities when courses need them, added once for all courses (e.g. document-based writing feedback for APUSH, sandboxed code grading for CSA); never course-specific code
- [x] 34.3 Onboard further courses (APUSH first) as packages through review; each is evaluated before `active`
- [x] 34.4 Privacy-safe aggregate course metrics for authors (no individual student data)
- [x] 34.5 Verify existing courses' regression and evaluation cases still pass after each new ability

**Status:** ✅ Implemented 2026-11-04; 🟡 content unreviewed. **2026-11-07:** Digital SAT 2.0.0 (29 skills, 8 new sets) and 2.0.1 (adds `practiceSequence`) published through the gate on staging; fixed on staging: the hint tutor now sees a choice set's items and choices (never answer keys or the expected answer), test `test_hints_see_the_items_but_never_the_answer_key`. End-to-end example: [examples/DIGITAL_SAT_WALKTHROUGH.md](examples/DIGITAL_SAT_WALKTHROUGH.md). **34.1** `web/author.html` + `web/js/portal/` (upload/replace drafts, validator report and evaluation results, submit, reviewer notes and history, student-view preview, metrics); new API `GET /api/authoring/packages/{c}/versions/{v}/preview` (also for reviewers) that never includes answer keys, expected answers, rubrics, the system prompt or the evaluation set. The portal cannot approve or activate. Tests: `tests/contract/test_author_portal.py`, `web/tests/portal.test.js`. **34.2** platform ability `source-analysis` (document-based writing graded against the question's `sourceMaterialIds`: sources fenced as untrusted content, per-criterion `documentsCited` checked against the question's sources, evidence still quoted from the student's own text; routing floor strong). Validator rules: sourced questions need the ability, the ability needs a sourced question, materials must exist, choice sets cannot have sources. No course-specific code. Sandboxed code grading (CSA) was not built: no course needs it yet. **34.3** APUSH 1.0.0 as an authored package (`content/authored/apush`): short answer, a DBQ-style question on two public-domain excerpts, and a source-analysis choice set; evaluation set 3 key-scored cases (pass) + 4 model-graded cases. The bundled planned placeholder was removed (as for Digital SAT); local seeding installs the package as **submitted**, so it reaches students only after a reviewer approves it (with `modelEvaluationAttested`) and activates it. The excerpts' wording must be checked against the originals at content review. Tests: `tests/contract/test_apush_course.py`. **34.4** `GET /api/authoring/courses/{c}/metrics`: distinct students, assessments by status and per-criterion averages, maintained exactly once per `assessment.completed` by the `course-metrics` consumer (the first production consumer); fewer than 5 students → `suppressed`; no student id anywhere in the aggregate. **34.5** `tests/unit/test_platform_abilities.py` re-validates every authored package and its key-scored cases and checks bundled courses after the ability change. Browser-checked 2026-11-04: sign-in, list, preview, metrics (no console errors); the upload and submit buttons were not exercised in the browser. Not done: a named content reviewer for APUSH, running its model-graded cases with a real model.

### Step 35 — Add admissions interviews and sourced planning

- [x] 35.1 Implement interview → student-confirmed facts → outline/feedback workflow
- [x] 35.2 Track school deadline sources with verification dates and uncertainty
- [x] 35.3 Keep authored essay text with student; no one-click ghostwriting
- [x] 35.4 Activity edits require student fact confirmation before saving

**Status:** ✅ Implemented 2026-11-04 (API only), verified with a scripted model over the in-memory backend. Requires `entitlements.admissions` (403 `ADMISSIONS_ACCESS_REQUIRED`). **35.1** interview prompt set `content/admissions/interview-v1.json` (draft); each answer enqueues an `ADMISSIONS_FACTS` Run (session-less, `subjectId`), and the worker stores only proposals whose quote is found verbatim in the answer; the student confirms (optionally rewording) or rejects; only confirmed facts are given to the outline model, and outline points must cite them. **35.2** deadlines with an https source and the date the student last checked it, labeled `verified` (≤30 days) / `stale` / `unverified` / `unsourced` with an uncertainty note; not yet fed into the planner ("sourced planning" stops at tracking). **35.3** drafts are written only by the student; `ADMISSIONS_FEEDBACK` returns capped items (outline points ≤25 words, comments ≤40 words, ≤250 words total); over-long output is rejected as `MODEL_OUTPUT_INVALID`; drafts cannot change while a feedback run is active. **35.4** activities save only with `studentConfirmed: true` and confirmed facts (409 `FACTS_NOT_CONFIRMED`), re-checked on every edit. Tests: `tests/contract/test_admissions.py` (access, quoted proposals, confirm/reject finality, confirmed-only outline, ghostwriting rejection, own-draft feedback, activities, deadlines, isolation, idempotency, no synthetic admissions output under `mock`). Not done: student-facing admissions UI (the web panel is still the demo preview), a real-model evaluation of fact extraction and feedback, content review of the prompts.

### Step 36 — Add scoped parent summaries

- [x] 36.1 Separate parent identity with explicit student relationship
- [x] 36.2 Implement `summary:read` scope — excludes private chats, original answers, essay drafts
- [x] 36.3 Implement consent and revocation; verify on every access
- [x] 36.4 Test parent A/B isolation, revoked authorization, field-level projection

**Status:** ✅ Implemented 2026-11-04 (API only), verified over the in-memory backend. Parents are `parents/{uid}` accounts resolved to `ParentActor` (no student id). A student creates an invite (code shown once, stored hashed, 7-day expiry, `summary:read` only, at most 4 live links); the parent redeems it; the student can revoke. Every parent read re-checks the student-side link and scope in the same transaction before building a scoped `ActorContext.for_parent`; the parent's own index is never trusted alone. The summary is built field by field (courses, skill levels, prediction `unavailable`, this week's task counts, upcoming task titles) and excludes chats, answers, feedback, essays and admissions data. Deleting a student removes the parent index entries and invites. Tests: `tests/contract/test_parent_summaries.py` (A/B isolation, role separation, revocation incl. a stale index entry, single-use and expiring codes, idempotency, field-level projection, deletion). Not done: parent UI, parent account provisioning outside fixtures, and a policy decision on whether a minor's parent consent is also required.

### Step 37 — Calibrate mastery and exam predictions

- [x] 37.1 Compare mastery estimates against independent held-out responses
- [x] 37.2 Exam prediction requires representative coverage and independent outcomes
- [x] 37.3 Keep practice performance, self-reported records, and predictions distinct
- [x] 37.4 Without sufficient evidence, prediction stays `unavailable`

**Status:** ✅ Pipeline and gate implemented 2026-11-04; ❌ no calibration has been performed, because no real held-out responses or exam outcomes exist. `app/domain/calibration.py`: calibration uses only independent held-out responses (practice, self-reported and hint-assisted responses, and other courses, are counted and excluded), and requires ≥30 responses per mastery level, ≥20 students, ≥80% skill coverage and accuracy that rises with level; synthetic data is never evidence. `decide_prediction` is the only producer of prediction status (the twin reads it for every enrolled course) and returns `unavailable` on every path, with the first missing requirement as the reason — including when all evidence exists, because no validated score model exists. `scripts/run_calibration.py` writes a report and refuses identifying fields. Tests: `tests/unit/test_calibration.py`.

### Step 38 — Evaluate optional infrastructure

- [x] 38.1 Assess Jev, MCP adapters, Temporal, semantic indexes as needed
- [ ] 38.2 Verify actual vendor availability, interfaces, quality, and costs
- [x] 38.3 Confirm core workflows remain functional without optional dependencies

**Status:** 🟡 Assessment written ([OPTIONAL_INFRASTRUCTURE.md](OPTIONAL_INFRASTRUCTURE.md)): none of the four is adopted, and each has an adoption trigger. 38.2 is deliberately not done: vendor availability, pricing and quality are only checked when a trigger is met, since today's figures would be stale by then. `tests/unit/test_optional_infrastructure.py` checks that no optional package is a runtime dependency and that the app plus a full learning loop run with those modules made unimportable.

### Step 39 — Import questions from PDFs and photos in the author portal (future)

**Goal:** Authors can bring existing question material (PDF files, photos of printed pages) into a draft package without writing JSON. The platform proposes items; the author confirms every item before it can enter a package; the existing validator and review gate are unchanged.

```
Upload PDF / photos ─► extraction Run (text layer, or OCR + vision-capable model)
  ─► proposed items (passage, question, choices, answer key, skill, difficulty, figure crop)
  ─► author review screen (original page | extracted item): edit, confirm or discard
  ─► confirmed items ─► draft package (rubric criteria + basic evaluation cases generated)
  ─► existing path: validator report → submit → platform reviewer → active
```

- [ ] 39.1 Contract first: `ImportJob`, `ProposedItem` (with a link back to the source page and region), author confirmation; API.md and COURSE_PACKAGE.md updated before handlers
- [ ] 39.2 Upload: signed Cloud Storage uploads scoped to the author's organization; size, page and type limits; files never shown to students and never readable by other organizations (404)
- [ ] 39.3 Source and license attestation per uploaded file, shown to the reviewer; official College Board or commercial test-prep material is refused without recorded permission
- [ ] 39.4 Extraction as a worker Run through the LLM gateway (no external calls inside transactions), with per-organization token budgets; output validated against the `ProposedItem` schema, invalid output rejected
- [ ] 39.5 Proposals are never content: only items the author confirms (and whose answer key the author enters or confirms) can be added to a draft. Handwritten marks on scanned pages are never used as answer keys, and photos are not kept as student data
- [ ] 39.6 Author portal review screen: side-by-side page and item, edit/confirm/discard, bulk confirm only after each item has been opened
- [ ] 39.7 Build the draft package from confirmed items (rubric criterion per item, all-correct / one-wrong / unreadable evaluation cases), then hand off to the existing upload and validator
- [ ] 39.8 Tests: organization isolation of uploads and proposals, idempotent import commands, unconfirmed proposals never reaching a package, extraction failure leaves no partial draft, attestation required, budget exhaustion; an evaluation set of annotated sample pages measuring extraction accuracy (separate from deterministic tests)

**Prerequisites:** item figures and math rendering. Today item prompts and choices are text only, so questions that depend on a diagram, graph or table image cannot be represented; the package contract, validator, storage and student view need image attachments (and formula rendering) first. An offline helper (PDF/photos → spreadsheet → package file) can serve authors in the meantime without platform changes.

**Verify:** An author uploads a sample PDF and a photo, confirms the extracted items, and submits a draft that passes the validator; no unconfirmed item, other organization's file, or student-visible upload exists at any point.

**Status:** ⏳ Planned 2026-11-07 (Option B of the import discussion); not started.

### Step 40 — Conversational authoring agent (future)

**Goal:** Authors build a course package by talking with an authoring agent instead of writing JSON. The agent asks for what the package needs (course basics, skills, practice-set design, questions and answer keys, rubric criteria and skill tags, the starter plan), proposes changes to a server-side draft, and the author accepts, rejects or adjusts each change in conversation. The package JSON becomes an artifact the agent maintains; submission and the platform review gate are unchanged.

```
Author ⇄ authoring agent (chat in the author portal)
  ─► agent proposes a typed edit (add skill, add set, update item, set answer key, tag criterion …)
  ─► validator runs on the resulting draft; problems explained in plain language, fixes offered
  ─► author accepts / rejects / asks for a change
  ─► server-side draft package (outline, validation report, student preview always available)
  ─► author presses Submit ─► existing path: platform reviewer → approved → active
```

Conversation stages (the author can move between them at any time): course basics → manifest; skills (agent suggests from the exam outline or standards, author edits); practice-set design (size, difficulty mix, passages) → abilities and rubric shape; questions (author-written, pasted, imported via Step 39, or agent-drafted on request); rubric criteria and skill tag per item; starter tasks; evaluation cases (generated and run); review walkthrough of the student preview and the submit checklist.

- [ ] 40.1 Contract first: `AuthoringSession`, server-side `DraftPackage`, a closed set of typed edit operations (no free-form JSON writes), proposal/accept/reject records, per-item provenance (`author`, `agent-drafted`, `imported`); API.md and COURSE_PACKAGE.md updated before handlers
- [ ] 40.2 Draft store scoped to the author's organization (other organizations → 404); every applied operation is idempotent, versioned (concurrent edits → 409) and recorded with actor and time; the draft can be exported as package JSON, and an uploaded JSON can seed a draft
- [ ] 40.3 Authoring agent as a platform ability: each turn is a worker Run through the LLM gateway (no external calls inside transactions) with per-organization token budgets; its only tools are the edit operations, the validator, the student preview and `math-verify`; model output is validated against the operation schema and invalid proposals are rejected
- [ ] 40.4 Author confirmation rules: a proposal changes the draft only when the author accepts it; every answer key must be confirmed by the author (agent-proposed keys for math items are checked with `math-verify`); items whose key is unconfirmed block Submit
- [ ] 40.5 Content integrity: agent-drafted items are recorded as such in `source` and shown to the reviewer; the agent asks for the source and license of pasted material and refuses to reproduce College Board or commercial test-prep items; package text the author pastes is treated as content, never as instructions to the agent
- [ ] 40.6 Boundaries: the agent cannot submit, approve, activate, retire, grant entitlements, read other organizations' packages, or read any student data; Submit stays an explicit author action through the existing endpoint
- [ ] 40.7 Author portal: chat panel beside a live draft view (outline, validation report, student preview, diff of each proposal with accept/reject); the JSON upload/download path remains for authors who prefer files
- [ ] 40.8 Tests: organization isolation of sessions and drafts, idempotent and conflicting edits, rejected proposals leave the draft unchanged, unconfirmed answer keys block Submit, the agent cannot call review or entitlement routes, budget exhaustion, a failed Run leaves no partial edit; an evaluation set of scripted authoring sessions (separate from deterministic tests) measuring proposal quality and key correctness against reviewed packages

**Relationship to other steps:** builds on the author portal (Step 34) and the review gate (Step 26); Step 39's PDF/photo import becomes one way to give the agent questions; figures and math rendering (Step 39 prerequisite) apply here too. Replaces the spreadsheet-converter idea as the main authoring path.

**Verify:** An author with no JSON knowledge builds a small course (skills, two practice sets, rubrics, starter tasks) entirely in conversation; the resulting draft passes the validator and every evaluation case, every answer key was confirmed by the author, agent-drafted items are labeled for the reviewer, and nothing reaches students until the platform reviewer approves and activates it.

**Status:** ⏳ Planned 2026-11-07; not started.

### Step 41 — Reviewer screen in the portal

**Goal:** Platform reviewers review, approve, reject, activate and retire course packages in a web screen instead of API calls. Found while publishing Digital SAT 2.0.0 on staging (2026-11-07): every reviewer action was a `curl` call with a hand-obtained ID token.

- [x] 41.1 Reuse the existing review API (`GET /api/review/packages`, version detail, preview, `approve`, `reject`, `activate`, `retire`); no new authority. Only the `platform_reviewer` role sees the screen; authors and students get 403 from the API as today
- [x] 41.2 Review queue: submitted versions with course, version, organization, submitted-at, and a flag when the course already has an active version (upgrade)
- [x] 41.3 Version view: validator report and evaluation results; status history; the student preview; the full content with answer keys, rubrics, sources and review status per item; for upgrades, a comparison with the active version (added, removed and changed questions and skills, with a warning when a question or skill ID still used by existing tasks or mastery is removed)
- [x] 41.4 Decisions: approve with the license attestation (and the model-evaluation attestation when the package has model-graded cases), reject with required notes, activate an approved version, retire a course with notes; each action asks for confirmation, sends an Idempotency-Key, and shows the server's error (`REVIEW_REQUIREMENTS_NOT_MET`, `INVALID_STATE_TRANSITION`) in plain language
- [x] 41.5 A per-item checklist the reviewer can work through (answer key, single defensible answer, skill tag, source and license); kept in the reviewer's browser only, not stored as review evidence
- [x] 41.6 Tests: role gating, every action through the existing endpoints, error display, the upgrade comparison on Digital SAT 1.0.0 → 2.0.0, no answer keys or review data on author or student screens

**Verify:** A reviewer takes a submitted package from the queue to active (and another to rejected) entirely in the browser, and the version history matches the actions taken.

**Status:** ✅ Implemented 2026-11-07 (local; not yet deployed to staging). `web/review.html` + `web/js/portal/review_portal.js` (UI) and `web/js/portal/review-api.js` (client and pure helpers: queue, upgrade comparison, plain-language errors, checklist). Components shared with the author portal moved to `web/js/portal/portal_ui.js`. No API change: the screen calls only the existing `/api/review/*` endpoints. Notes:
- 41.1: the page has no role logic of its own; when the API answers 403, it shows "not a platform reviewer" and nothing else.
- 41.2: the queue shows submitted, then approved versions, oldest first. Each is marked as an upgrade of the active version, as older than it (activation would be refused), or as a new course.
- 41.3: the "still used" warning is conservative. Reviewers cannot see which students use an ID, so every question or skill ID removed from the active version is a warning, and so is a question changed without a new question version.
- 41.5: the checklist is kept in `localStorage`, per reviewer and package version.
- 41.6 tests: `web/tests/review.test.js` (11) and `server/tests/contract/test_review_screen.py` (3); the existing role tests are in `test_package_review.py`.

Verified in Chrome against a local in-memory API with `dsat` 2.0.0 and 2.0.1 submitted:
- `author_hsos` sees "not a platform reviewer".
- As `reviewer_platform`: the queue showed both versions as upgrades of 1.0.0. The 2.0.1 comparison showed 8 questions and 25 skills added, none removed. Its content showed the keys, and a checklist tick survived a reload.
- 2.0.1 was approved (Approve stays disabled until the license is attested; a confirmation step follows), then activated; 1.0.0 became superseded. 2.0.0 was rejected with notes, which the author portal shows. The course was then retired.
- The server's status history for each version matched these actions. No console errors.
- Found and fixed during the check: a pending version older than the active one was labelled "upgrade of".

### Step 42 — Admin tool for student course access (future)

**Goal:** Platform admins grant and revoke a student's access to courses with an audited tool instead of editing `students/{id}/access/current` in Firestore by hand. Found on staging (2026-11-07): giving a student access to Digital SAT required a direct database write. Entitlements stay platform-managed (CLAUDE.md §1.4); authors and students can never change them.

- [ ] 42.1 Contract first: admin endpoints to read a student's access, and to grant or revoke one `courseId` (`apCourses` for AP courses, `courses` for others) with a reason; Idempotency-Key required; API.md updated before handlers
- [ ] 42.2 Authorization: the existing `admin` role (`ActorRole.ADMIN`) gets an explicit `entitlements:manage` permission; platform admins are platform members like reviewers, with no student record; every other role gets 403; unknown students 404
- [ ] 42.3 Atomic write of the access record and an audit entry (who, when, student, course, grant or revoke, reason) in one transaction; the student's events show a filtered `access.changed` notice without the admin's identity or reason
- [ ] 42.4 Revocation semantics: the student keeps their records (sessions, assessments, mastery) readable; new enrollments, sessions and submissions return `COURSE_ACCESS_REQUIRED`; open sessions can still be abandoned; a Run already queued is re-checked at execution (as today)
- [ ] 42.5 Admin screen: find a student by ID, see current access and enrollments, grant or revoke with a reason, see the audit history; no access to the student's answers or chats
- [ ] 42.6 Bulk grant for a class or pilot cohort (list of student IDs, one course), each grant audited individually, partial failures reported per student
- [ ] 42.7 Tests: role gating (author, reviewer, student, parent all 403), idempotency, grant then enroll, revoke blocks new work but keeps records, audit entry written in the same transaction (crash leaves neither), bulk partial failure, isolation (one student's change never touches another)

**Verify:** An admin grants Beth Digital SAT access in the tool, she enrolls; the admin revokes it, she can no longer start a session but still sees her past results; the audit history shows both changes with reasons.

**Status:** ⏳ Planned 2026-11-07; not started. Until then, access is changed by a direct Firestore edit recorded in OPERATIONS.md.

### Step 43 — Review assistant agent (future; workflow and skills to be defined by reviewers)

**Goal:** Platform reviewers use an agent to help review submitted course packages: it prepares findings, the reviewer decides. **The review workflow and the agent's skills are to be defined by the platform reviewers later**; this step only records the intent and the rules any design must keep.

**To be defined by reviewers (open):**
- The review workflow: which checks the agent runs, in what order, and what the reviewer must look at personally.
- The agent's skills (for example, re-solving answer keys, checking that each item has one defensible answer, checking skill tags, spotting likely copyrighted or official test material, reading the upgrade comparison from Step 41, summarizing rubric clarity), each defined as a platform ability with its own evaluation set.
- What a finding looks like (severity, the item and field it refers to, evidence) and how the reviewer records agreeing or disagreeing with it.

**Rules any design must keep:**
- The agent advises; it never approves, rejects, activates or retires, and never makes the license or model-evaluation attestations. Those stay explicit reviewer actions through the existing endpoints.
- Findings are stored with the version as advisory notes, labeled as agent output, with the model and skill version that produced them; they are never presented as the reviewer's own conclusion.
- Package text is content, not instructions: an author cannot steer the review agent through question text, passages or the system prompt.
- It runs on the shared runtime (worker Run through the LLM gateway, usage budgets, no external calls inside transactions), with read-only tools: the package, the validator, the preview, the Step 41 comparison and `math-verify`. No access to student data or to other organizations' drafts.
- Its own quality is measured offline on annotated packages with known problems (missed issues and false alarms) before reviewers rely on it.

**Relationship to other steps:** builds on the reviewer screen (Step 41), where findings would appear beside each item; mirrors the authoring agent (Step 40) on the author side.

**Status:** ⏳ Intent recorded 2026-11-07; workflow and skills to be defined by reviewers; not started.

---

## Delivery Map

| Milestone | Steps | Key Exit Criteria | Status |
|---|---|---|---|
| M0 Contracts and baseline | 1–7 | Buildable skeleton, schemas, fixtures, evaluation cases, Firebase emulators, frontend contract | Implemented; emulator run 2026-11-05; content review pending |
| M1 Reliable foundation | 8–15 | Independent auth, Firestore repos, course enrollment, Task/Session/Run lifecycle, queue/outbox/worker, two-student isolation | Implemented; emulator run 2026-11-05; staging smoke test passed; Step 32 pending |
| M2 Calculus learning loop | 16–21 | LLM gateway, Calculus skills, atomic assessment, events/SSE, course-driven frontend, evaluation report | Implemented; emulator run 2026-11-05; real-model evaluation review and Step 32 pending |
| M3 Course platform | 22–27 | Course package contract + validator, ability catalog, course-internal consumers, multi-course planner, author role + review gate, a second course built with data only | Redefined 2026-11-01; course-agnostic parts implemented |
| M4 Proactive planning and pilot | 28–33 | Scheduled planning, reminders, staging deploy, monitoring, integration tests, pilot gate (Calc BC + Digital SAT, authored) | 28, 29, 31 implemented (local); 30 deployed to staging 2026-11-03; 32 not yet run; 33 not passed |
| M5 Optional expansion | 34–43 | Individually validated extensions (authoring portal and more courses, admissions, parent, predictions, infrastructure, author import from PDF/photos, conversational authoring agent, reviewer screen, admin course-access tool, review assistant agent) | 34–38 implemented 2026-11-04 (in-memory, synthetic); APUSH awaiting review; admissions/parent API only; predictions stay unavailable; 38.2 deferred; 39–43 planned, not started |

## Superseded patterns

The following old patterns are replaced and must not be carried forward:
- Task/Session merged into one record → separate persistent resources
- In-memory sessions → Firestore with transactions
- Client-submitted scoreDelta → server-side assessment only
- `X-User-Email` identity → Firebase ID token with verified studentId
- Public event POST → server-generated events from typed commands
- Uncalibrated predictions (4.5/4.8) → `unavailable` until calibrated
- Jev/MCP as M0–M4 prerequisites → optional M5 evaluation
- Cross-course prerequisite mappings (Calc BC → SAT suspected/confirmed findings, `/api/prerequisites`, `prerequisite.*` events) → independent course packages; follow-up rules act only inside their own course
- Course-specific runtime code → course packages as data, platform abilities shared by all courses
