# High School Student OS — Development Rules

This file governs all development work in this repository. Read it before making any change.

## Project overview

An AI-powered **course platform** for US high school students. Courses (AP subjects, test prep, and more) are added as **course packages**: data that defines the course's skills, question bank, rubrics and criteria, course requirements and completion criteria. First-party and third-party authors publish packages through a platform review gate, and every course runs on **one shared runtime** using abilities the platform provides. Courses are independent: there is no cross-course inference. Calculus BC is the first-party reference course; the pilot's second course is **Digital SAT**, rebuilt only through the authoring path. Core loop, per course: **learning evidence → student record → next study task → updated weekly plan** (the plan spans all enrolled courses).

Architecture docs live in `doc/`. Implementation follows `doc/STEP_BY_STEP_PLAN.md` milestones M0–M4 (pilot) and M5 (extensions).

## High-level architecture

### System diagram

```
┌─────────────────────────────────────────────────────────────────────┐
│  BROWSER (web/)                                                     │
│  ┌──────────────┐  ┌─────────────────────────────────────────────┐  │
│  │ Course       │  │  Active Course Agent View                   │  │
│  │ Catalog      │  │  ┌───────────────────┐ ┌────────────────┐  │  │
│  │ (browse/add) │  │  │ Chat / Tutoring   │ │ Tasks & Plan   │  │  │
│  │              │  │  │ (per-course agent) │ │ (per-course)   │  │  │
│  │ ┌──────────┐ │  │  └───────────────────┘ └────────────────┘  │  │
│  │ │ Enrolled │ │  │  ┌───────────────────┐ ┌────────────────┐  │  │
│  │ │ Courses  │ │  │  │ Submit Answers    │ │ Mastery /      │  │  │
│  │ │ (sidebar)│ │  │  │ (text / file)     │ │ Progress       │  │  │
│  │ └──────────┘ │  │  └───────────────────┘ └────────────────┘  │  │
│  └──────────────┘  └─────────────────────────────────────────────┘  │
│                          │ data-provider seam                       │
│                  ┌───────┴────────┐                                 │
│                  │ API Client     │ ◄── Idempotency-Key, Bearer JWT │
│                  │ + SSE/Polling  │                                  │
│                  └───────┬────────┘                                  │
└──────────────────────────┼──────────────────────────────────────────┘
                           │ HTTPS
┌──────────────────────────┼──────────────────────────────────────────┐
│  API SERVER (Cloud Run)  │                                          │
│                  ┌───────┴────────┐                                  │
│                  │ FastAPI        │                                  │
│                  │ Auth Depends   │ ◄── Firebase ID token verify     │
│                  │ Pydantic v2    │                                  │
│                  └───────┬────────┘                                  │
│                          │ ActorContext                              │
│          ┌───────────────┼───────────────┐                          │
│          ▼               ▼               ▼                          │
│  ┌──────────────┐ ┌────────────┐ ┌──────────────┐                  │
│  │ Twin Service │ │ Session &  │ │ Event Feed   │                  │
│  │ Profile/Goal │ │ Command    │ │ SSE + Poll   │                  │
│  │ Entitlements │ │ Service    │ │              │                  │
│  └──────┬───────┘ └─────┬──────┘ └──────┬───────┘                  │
│         │               │               │                          │
│         └───────────────┼───────────────┘                          │
│                         ▼                                          │
│                  ┌─────────────┐    ┌──────────────┐               │
│                  │  Firestore  │───►│   Outbox     │               │
│                  │ (transaction│    │  (in same tx)│               │
│                  │  boundary)  │    └──────┬───────┘               │
│                  └─────────────┘           │                       │
└────────────────────────────────────────────┼───────────────────────┘
                                             │ dispatch
┌────────────────────────────────────────────┼───────────────────────┐
│  WORKER (Cloud Run — separate service)     │                       │
│                                    ┌───────┴────────┐              │
│                                    │ Queue Adapter   │              │
│                                    │ (Cloud Tasks)   │              │
│                                    └───────┬────────┘              │
│                                            │ lease + fencing token │
│                          ┌─────────────────┼──────────────┐        │
│                          ▼                 ▼              ▼        │
│                  ┌──────────────┐  ┌──────────────┐ ┌──────────┐  │
│                  │ Context      │  │ Skill        │ │ Tool     │  │
│                  │ Loader       │  │ Executor     │ │ Registry │  │
│                  │ (SubjectPack │  │ (Socratic,   │ │ (math,   │  │
│                  │  + student)  │  │  Rubric,     │ │  search, │  │
│                  │              │  │  Diagnostic) │ │  OCR)    │  │
│                  └──────────────┘  └──────┬───────┘ └──────────┘  │
│                                           │                        │
│                                    ┌──────┴───────┐                │
│                                    │ LLM Gateway  │                │
│                                    │ (Anthropic   │                │
│                                    │  Claude)     │                │
│                                    └──────┬───────┘                │
│                                           │                        │
│                                    ┌──────┴───────┐                │
│                                    │ Assessment   │                │
│                                    │ Service      │◄── atomic commit│
│                                    │ (evidence +  │    assessment + │
│                                    │  mastery +   │    mastery +    │
│                                    │  events)     │    events       │
│                                    └──────┬───────┘                │
│                                           │                        │
│                  ┌────────────────────────┼───────────────┐        │
│                  ▼                        ▼               ▼        │
│          ┌──────────────┐  ┌──────────────────┐  ┌────────────┐   │
│          │ Domain Event │  │ Course Package   │  │ Planner    │   │
│          │ Consumers    │  │ Registry +       │  │ (schedule, │   │
│          │ (in-course   │  │ Validator        │  │  rank,     │   │
│          │ follow-up:   │  │ (data only,      │  │  explain   │   │
│          │  diagnostic →│  │  reviewed,       │  │  across    │   │
│          │  practice)   │  │  version-pinned) │  │  courses)  │   │
│          └──────────────┘  └──────────────────┘  └────────────┘   │
└────────────────────────────────────────────────────────────────────┘

INFRASTRUCTURE (Google Cloud)
┌────────────────────────────────────────────────────────────────────┐
│  Firebase Auth        — student identity, ID token issuance        │
│  Firestore            — all persistent state (per-student docs)    │
│  Cloud Tasks          — durable job queue (outbox dispatch)        │
│  Cloud Scheduler      — daily planning trigger (per-timezone)      │
│  Cloud Storage        — file uploads (answers, OCR images)         │
│  Secret Manager       — API keys, model credentials               │
└────────────────────────────────────────────────────────────────────┘
```

### Technology stack

| Layer | Technology | Purpose |
|---|---|---|
| **Runtime** | Python 3.12+ with type hints + mypy | Type-safe backend |
| **API framework** | FastAPI + Pydantic v2 | Async HTTP, automatic validation and OpenAPI docs |
| **Authentication** | Firebase Authentication | ID token issuance and verification |
| **Database** | Cloud Firestore | Transactional document storage, per-student isolation |
| **Job queue** | Cloud Tasks + outbox pattern | Durable async execution with at-least-once delivery |
| **Scheduler** | Cloud Scheduler | Timezone-aware daily planning triggers |
| **File storage** | Cloud Storage | Signed upload/download URLs for student files |
| **AI model** | Anthropic Claude (via LLMGateway) | Socratic guidance, rubric assessment, diagnostics |
| **Deployment** | Cloud Run (2 services: API + Worker) | Serverless containers with auto-scaling |
| **Observability** | Structured logs + OpenTelemetry | Latency, tokens, errors (no raw student data) |
| **Frontend** | Vanilla JS (existing prototype) | Student workspace, task list, agent panels |
| **Local dev** | Firebase emulators + pytest | Offline-capable development and testing |

### Key components and responsibilities

| Component | What it does | Where it lives |
|---|---|---|
| **Auth Dependency** | Verifies Firebase ID tokens, builds ActorContext via FastAPI Depends | `app/api/dependencies/` |
| **Twin Service** | Reads/patches student profile, goals, preferences; returns bounded summary | `app/domain/` |
| **Session & Command Service** | Creates sessions from tasks, accepts submissions/messages, enforces one-active-Run | `app/domain/` |
| **Run Worker** | Acquires lease, loads context + skill, calls LLM, produces assessment | `app/workers/` |
| **LLM Gateway** | Provider abstraction, static routing, usage budgets, retry logic | `app/adapters/llm/` |
| **Course Package Registry** | Loads validated, approved course packages (skills, questions, rubrics, requirements, criteria); pins versions per Run | `app/registries/` |
| **Package Validator & Publishing** | Validates submitted packages; author → platform reviewer → active workflow; retire/version | `app/domain/`, `app/registries/` |
| **Skill Executor** | Platform ability catalog: Socratic guidance, rubric assessment, choice (answer-key) scoring, diagnostic — selected and configured by each package | `app/domain/skills/` |
| **Tool Registry** | Math verification, content retrieval, OCR (whitelisted per skill) | `app/registries/` |
| **Assessment Service** | Validates evidence, atomic commit of assessment + mastery + events | `app/domain/` |
| **Event Feed** | Per-student monotonic sequence, SSE stream + polling fallback | `app/api/routes/`, `app/adapters/firestore/` |
| **Domain Event Consumers** | React to events with the course's own follow-up rules (e.g. repeated errors → in-course diagnostic → practice); never across courses | `app/workers/consumers/` |
| **Planner Service** | Ranks tasks from all enrolled courses by deadline/evidence/budget, incremental replan, explains changes | `app/domain/` |
| **Reminder Service** | Opt-in notifications with consent, quiet hours, frequency caps | `app/domain/` |
| **Outbox Dispatcher** | Scans outbox, dispatches to Cloud Tasks, reconciles missed entries | `app/workers/` |

### Data flow — a single learning interaction

```
Student types answer
       │
       ▼
POST /api/sessions/:id/submissions + Idempotency-Key
       │
       ▼
┌──────────────────────────────────────────────┐
│ Firestore Transaction                        │
│  • Save Submission (immutable)               │
│  • Create Run (QUEUED)                       │
│  • Write idempotency record                  │
│  • Write outbox entry                        │
│  (no external calls inside tx)               │
└──────────────────────┬───────────────────────┘
       │               │
       ▼               ▼
  Return 202      Outbox dispatcher → Cloud Tasks
  {runId}                    │
                             ▼
                     Worker picks up Run
                      • Acquire lease + fencing token
                      • Load SubjectPack + rubric + student context
                      • Call LLM Gateway (Socratic or Assessment skill)
                      • Validate output against rubric schema
                             │
                             ▼
                ┌────────────────────────────┐
                │ AssessmentService           │
                │ commitAssessment()          │
                │  Firestore Transaction:     │
                │  • Save Assessment          │
                │  • Update Mastery           │
                │  • Set Run → SUCCEEDED      │
                │  • Emit domain events       │
                │  • Write outbox for         │
                │    downstream consumers     │
                └─────────────┬──────────────┘
                              │
              ┌───────────────┼───────────────┐
              ▼               ▼               ▼
    SSE to browser    Follow-up        Planner updates
    (assessment.      Consumer         task schedule
     completed)       (course rules:   if needed
                       same course)
```

### Course enrollment and per-course agent model

The student's workspace is **driven by their enrolled courses**. A course is invisible until the student adds it. Each enrolled course activates a dedicated conversational agent.

```
┌─────────────────────────────────────────────────────────────────┐
│  STUDENT EXPERIENCE                                             │
│                                                                 │
│  1. Browse Course Catalog                                       │
│     ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌───────────────┐   │
│     │ Calc BC  │ │ APUSH    │ │Physics C │ │ AP Lang       │   │
│     │ ✅ active│ │ ✅ active│ │ 🔒 coming│ │ 🔒 coming     │   │
│     └──────────┘ └──────────┘ └──────────┘ └───────────────┘   │
│          │            │                                         │
│          ▼            ▼                                         │
│  2. Add Course (enrolls → backend validates entitlement)        │
│          │            │                                         │
│          ▼            ▼                                         │
│  3. My Workspace (only enrolled courses visible)                │
│     ┌─────────────────────────────────────────────────────┐     │
│     │  ┌─────────────┐    ┌─────────────┐                │     │
│     │  │ 📐 Calc BC  │    │ 📜 APUSH    │                │     │
│     │  │   Agent     │    │   Agent     │                │     │
│     │  │             │    │             │                │     │
│     │  │ 💬 Chat     │    │ 💬 Chat     │                │     │
│     │  │ 📋 Tasks    │    │ 📋 Tasks    │                │     │
│     │  │ 📊 Progress │    │ 📊 Progress │                │     │
│     │  └─────────────┘    └─────────────┘                │     │
│     └─────────────────────────────────────────────────────┘     │
│                                                                 │
│  4. Open a course → conversational agent for tutoring           │
│     ┌─────────────────────────────────────────────────────┐     │
│     │  Calc BC Agent                          📊 Progress │     │
│     │  ┌───────────────────────────────────┐ ┌──────────┐│     │
│     │  │ Agent: Let's work on implicit     │ │ Today's  ││     │
│     │  │ differentiation. Try this:        │ │ Tasks    ││     │
│     │  │ Find dy/dx for x²y + y³ = 7      │ │          ││     │
│     │  │                                   │ │ □ FRQ #3 ││     │
│     │  │ Student: dy/dx = -2xy/(x²+3y²)   │ │ □ Review ││     │
│     │  │                                   │ │ ✓ Quiz   ││     │
│     │  │ Agent: Good work! Let me check    │ │          ││     │
│     │  │ your derivation step by step...   │ │          ││     │
│     │  │                                   │ │          ││     │
│     │  │ [Grading... ██████░░ ]            │ │          ││     │
│     │  └───────────────────────────────────┘ └──────────┘│     │
│     │  ┌───────────────────────────────────┐             │     │
│     │  │ Type your answer...          Send │             │     │
│     │  └───────────────────────────────────┘             │     │
│     └─────────────────────────────────────────────────────┘     │
└─────────────────────────────────────────────────────────────────┘
```

**Course lifecycle and visibility rules:**

| State | Visibility | What the student can do |
|---|---|---|
| `active` + entitled + enrolled | **Visible with full agent** | Chat, practice, get assessed, see progress |
| `active` + entitled + NOT enrolled | In catalog only | Browse description, add to workspace |
| `active` + NOT entitled | In catalog, locked | See description, cannot add (needs access grant) |
| `planned` | In catalog, "coming soon" | See description only, cannot add |
| Not in catalog | Invisible | — |

**Per-course agent behavior:**

Each enrolled course activates an agent powered by that course's `SubjectPack`. The agent:

- Has its own **chat thread** (Session) where the student converses, asks questions, and submits answers
- Follows the course's **skill set** — Socratic guidance, rubric assessment, diagnostic, etc.
- Tracks **course-specific mastery** — evidence from this agent updates only this course's skills
- Has access to **course-scoped content** — questions, rubrics, materials filtered by courseId/ACL
- Generates **course-scoped tasks** — practice, review, diagnostic tasks appear in the student's plan

**How it maps to the backend:**

```
Student adds "calc_bc"
       │
       ▼
PATCH /api/twin  { selectedCourses: ["calc_bc"] }
       │
       ▼
Backend validates:
  ├── Is pack "calc_bc" active?              → yes
  ├── Does student have entitlement?         → yes (entitlements.apCourses includes "calc_bc")
  └── Save to preferences.selectedCourses
       │
       ▼
GET /api/courses/enrolled  →  returns enrolled courses with agent config
       │
       ▼
Frontend shows Calc BC agent in workspace
       │
       ▼
Student opens Calc BC → loads agent chat view
       │
       ▼
Planner generates initial tasks for calc_bc
       │
       ▼
Student picks a task → POST /api/sessions { taskId }
  → Session OPEN, agent begins conversation
  → student submits answer → Run → Assessment → feedback
```

**Enrollment API:**

```
GET  /api/courses/catalog          → all packs with availability + entitlement status for this student
POST /api/courses/enroll           → { courseId } + Idempotency-Key → enroll (validates active + entitled)
POST /api/courses/unenroll         → { courseId } + Idempotency-Key → remove from workspace
GET  /api/courses/enrolled         → list enrolled courses with agent config, mastery summary, active tasks
GET  /api/courses/:courseId/agent  → agent config, skills, modes, current session if any
```

**Key constraint:** Enrolling in a course is a student action. But enrollment alone does not grant access — the backend checks `entitlements` (admin-managed). A student selecting "APUSH" in the catalog when they have no APUSH entitlement gets a clear "access required" response, not a silent failure.

### Course packages and authoring (the platform model)

A course is **data, not code**. Authors (first-party or third-party organizations) submit a versioned course package; the platform validates it, a platform reviewer approves it, and only then does it become `active` in the catalog.

```
  Author org builds a course package (data only)
    • manifest: courseId, version, publisher, license, abilities used + settings, tool whitelist
    • skill taxonomy (+ optional prerequisite edges within the course)
    • question bank (versioned, licensed, skill-tagged; free response or choice items)
    • rubrics / criteria (criterionId, maxPoints, evidence requirements, skill)
    • course requirements (recommended time, sourced exam/assignment dates)
    • completion + follow-up criteria (platform rule types + parameters, no code)
    • evaluation set (annotated cases the course must pass)
         │
         ▼
  Upload (author role) → Validator report → submitted
         │
         ▼
  Platform reviewer: evaluation results, license, content → approved / rejected
         │
         ▼
  active in catalog → students enroll (entitlements still platform-managed)
         │
         ▼
  Same runtime for every course: Task → Session → Run → AssessmentService
  → mastery → course-internal follow-up → Planner across enrolled courses
```

Rules:
- A package selects abilities from the platform catalog; it cannot add code, prompts that override grading rules, or new tools. A missing capability becomes a platform ability available to every course.
- Each Run pins the package version; a new version never changes open sessions or past assessments. Retiring a course stops new work without deleting student records.
- Evidence in one course never creates findings, tasks or mastery changes in another course.
- Authors never see individual student data and cannot grant entitlements. Another organization's packages return 404.

## 1. Boundaries — what you must not do

### 1.1 No external dependencies on reference projects
- `ai-college-advisor` and `sat-tutor-app` are **read-only references only**.
- Never share JWT secrets, databases, local ports, filesystem paths, or credentials between projects.
- Never import, copy, or adapt LOGIQ code, services, or API formats.
- This project must build, test, and run independently after removing all reference directories.

### 1.2 No real student data
- All development uses synthetic fixtures (`fixtures/`) and Firebase Auth emulator users.
- Never commit real student names, emails, answers, essays, or school records.
- Never seed emulators with production data exports.

### 1.3 No fabricated academic facts
- Exam predictions stay `unavailable` until an independent calibration pipeline exists.
- Old demo values like `predicted: 4.5` / `target: 4.8` must not be migrated as real grades.
- A single corrected answer does not justify an AP score prediction change.
- Internal AP estimates do not automatically reclassify college reach/match/safety.

### 1.4 No client-side authority over learning data
- The browser submits **commands and answers only** — never scores, mastery deltas, assessment status, tool results, or domain events.
- Entitlements are backend-managed; `selectedCourses` is a student preference, not an access grant.
- Identity comes from verified Firebase ID tokens only — reject `X-User-Email` and body-provided `studentId`.

## 2. Architecture rules

### 2.1 Dependency direction
```
api/ → domain/ ← adapters/
        ↑
     workers/
```
- **Domain** (`app/domain/`) defines types, protocols (ports), and business logic. It has zero infrastructure imports.
- **Adapters** (`app/adapters/`) implement domain protocols for Firestore, Firebase Auth, Cloud Tasks, LLM providers, etc.
- **API** (`app/api/`) is a thin FastAPI layer: authentication dependencies, Pydantic validation, and delegation to domain services.
- **Workers** (`app/workers/`) consume queue messages and call domain services.
- Never import from `api/` into `domain/`. Never import infrastructure SDKs into `domain/`.

### 2.2 ActorContext everywhere
Every domain operation receives an `ActorContext` (actorId, studentId, role, permissions). No function silently assumes "the current user." Ownership checks happen in domain/repository code, not only in route handlers.

### 2.3 One shared runtime, per-course agents
Each enrolled course activates a **per-course agent** — but all agents run through **one shared runtime**. A "Calc BC agent" and an "APUSH agent" are different SubjectPack configurations (skills, rubrics, content, tools), not separate services. Do not build separate microservices or autonomous agents that talk to each other. The runtime loads the right SubjectPack based on the course, and the student interacts with a course-specific chat experience. A SubjectPack is the loaded form of a validated **course package**, which may come from a third-party author: never add course-specific branches to runtime code — if a course needs something new, add a platform ability every course can select.

### 2.4 Transactions and atomicity
- Commands that create a Run must atomically write: command record + Run(QUEUED) + idempotency record + outbox entry — in a single Firestore transaction.
- `commitAssessment()` must atomically write: Assessment + mastery update + Run terminal state + domain events + outbox — in a single transaction.
- **No external calls inside transactions** (no LLM, no queue, no storage).
- If the transaction fails, nothing is partially written.

### 2.5 State machines are strict
| Entity | Valid transitions |
|---|---|
| Task | PLANNED → IN_PROGRESS → COMPLETED; PLANNED → SKIPPED |
| Session | OPEN → COMPLETED; OPEN → ABANDONED |
| Run | QUEUED → RUNNING → SUCCEEDED/FAILED/CANCELLED; RUNNING → WAITING_INPUT → QUEUED |

Student cannot directly PATCH a Task to COMPLETED. Session COMPLETED requires accepted assessment and no active Run. Run SUCCEEDED means the execution finished — it does not mean the student completed the task.

### 2.6 Idempotency
- All POST commands require `Idempotency-Key` header.
- Same key + same body → return original result.
- Same key + different body → 409 `IDEMPOTENCY_CONFLICT`.
- At most one nonterminal Run per Session; concurrent new command → 409 `RUN_IN_PROGRESS`.

### 2.7 Events are server-generated
- Domain events are created inside transactions, assigned monotonic per-student sequences.
- Clients cannot POST events. Events exposed to the client are filtered projections (no internal outbox, raw model reasoning, or credentials).
- Event consumers use per-consumer receipts with transactional Task creation to guarantee exactly-once business effects.

## 3. Coding conventions

### 3.1 Language and tools
- **Python 3.12+** with type hints, **mypy** for static type checking, **FastAPI**, **Pydantic v2** for validation.
- **Firestore** for persistence (emulator in dev), **Cloud Tasks** for job queue, **Cloud Scheduler** for cron, **Cloud Storage** for files.
- **pytest** + **pytest-asyncio** for tests. **httpx.AsyncClient** with FastAPI TestClient for route tests (no external server needed).
- **ruff** for linting and formatting. **uv** for dependency management.

### 3.2 File organization
```
server/
  app/
    __init__.py
    main.py            # FastAPI application entry point
    api/               # FastAPI routers, auth dependencies, request/response schemas
    domain/            # Business logic, types, service protocols (ports)
    workers/           # Run worker, outbox dispatcher, event consumers
    adapters/          # Firestore, auth, queue, storage, LLM, tools
    registries/        # Pack/skill manifest loading and validation
    schemas/           # Pydantic v2 models for API/domain contracts
  content/             # Reviewed packs, questions, rubrics, mappings
  fixtures/            # Synthetic test data only
  tests/               # All test files
  pyproject.toml       # Dependencies, scripts, tool config
web/                   # Frontend (vanilla JS, existing prototype)
doc/                   # Architecture and planning documents
```

### 3.3 Naming
- Files and modules: `snake_case.py` (e.g., `task_service.py`, `student_repository.py`)
- Classes and type aliases: `PascalCase` (e.g., `TaskStatus`, `StudentRepository`)
- Repository protocols placed in `app/domain/ports/` (using `typing.Protocol`)
- Functions, methods, and variables: `snake_case`
- Constants: `UPPER_SNAKE_CASE`
- Database collection paths follow `BACKEND.md` §3 layout (e.g., `students/{studentId}/tasks/{taskId}`)

### 3.4 Error handling
- Use typed error codes from API.md (e.g., `RUN_IN_PROGRESS`, `COURSE_NOT_AVAILABLE`, `IDEMPOTENCY_CONFLICT`).
- Domain functions throw or return typed errors — never swallow failures silently.
- Cross-student resource access returns 404 (not 403) to avoid leaking existence.
- Production startup must reject emulator environment variables and mock providers.

### 3.5 What not to build
- No code plugin/extension frameworks. Course packages are validated **data** against a fixed contract; third parties never upload code. New capabilities are added as platform abilities, specifically and as needed.
- No ORM or query builder — use Firestore SDK directly in adapters.
- No custom workflow engine or JSON-based execution language — use typed Python code.
- No MCP server, Jev integration, or Temporal until explicitly justified in M5.
- No compatibility layers for Anthropic Managed Agents API.

## 4. Testing rules

### 4.1 What to test
Every step must have tests covering:
- **Isolation**: Student A cannot access Student B's resources (returns 404).
- **Idempotency**: Same key + same body → same result; same key + different body → 409.
- **State machine**: Invalid transitions are rejected.
- **Authorization**: Missing/expired/wrong-audience tokens → 401; no entitlement → 403.
- **Recovery**: Restart app → pending work resumes; crash in any window → no partial state.
- **Concurrency**: Version conflicts → 409; race conditions → consistent terminal state.

### 4.2 Test categories
| Category | Location | Runs with | Purpose |
|---|---|---|---|
| Unit | `tests/unit/` | `pytest tests/unit/` | Domain logic, schema validation, pure functions |
| Contract | `tests/contract/` | `pytest tests/contract/` | API schema compliance, request/response shapes |
| Emulator | `tests/emulator/` | `pytest tests/emulator/` | Firestore transactions, auth, isolation, recovery |
| E2E | `tests/e2e/` | `pytest tests/e2e/` | Full API flow with emulators |
| Evaluation | `tests/evaluation/` | `pytest tests/evaluation/` | Learning quality against annotated examples |

### 4.3 Testing principles
- **Emulator tests > mocks** for anything involving Firestore transactions, auth, or isolation. A passing mock does not prove a real transaction works.
- **Synthetic execution** for internal pipeline tests — returns deterministic stub results, clearly labeled. Never accepted as real grading evidence.
- **Evaluation tests are separate** from unit/integration tests. They measure learning quality, not code correctness. They require reviewed content and possibly real model calls.
- **Cloud and model evaluations** are separate from deterministic local tests. A separately labeled real-provider smoke test runs only when credentials are configured.

### 4.4 Test hygiene
- Each test creates its own data; never depend on ordering between tests.
- Clean up emulator state between test suites (or use unique student IDs per test).
- Never hard-code emulator ports — read from environment or config.

## 5. Workflow rules

### 5.1 Step-by-step execution
- Follow `doc/STEP_BY_STEP_PLAN.md` in order. Each step is a reviewable change.
- **Verify before moving on.** Run the step's verification criteria. Do not mark a step complete based on documentation updates alone.
- If a step reveals a necessary contract change, update the contract (schemas, types, API doc) **before** implementing the change in handlers.

### 5.2 Commit discipline
- Each step (or meaningful sub-task within a step) gets its own commit.
- Commit messages describe what changed and why, not just "implement step N."
- Never commit credentials, secrets, `.env` files, or real student data.
- Run `mypy app/` and `pytest` before committing. Fix failures before moving on.

### 5.3 Contract-first development
1. Define or update Pydantic models (`app/schemas/`)
2. Define or update domain types (`app/domain/types/`)
3. Write tests for the contract
4. Implement the handler/service
5. Verify the tests pass

### 5.4 When changing existing code
- Read the file first. Understand what it does before editing.
- Preserve useful boundaries in the existing web frontend (`window.HSData` provider seam).
- Do not delete unknown code to match a directory diagram.
- If old API patterns exist (email auth, scoreDelta), replace them with the new contract — do not leave both active.

### 5.5 When stuck
- If a step is blocked by a missing prerequisite, document the blocker and skip to the next independent step.
- If a schema/contract question arises, resolve it in the contract docs before coding.
- If the evaluation baseline (Step 7) reveals quality issues, narrow scope rather than shipping known-bad output.

## 6. Content and safety rules

### 6.1 Questions and rubrics
- All questions must have: questionId, version, source/license, reviewer, rubric reference.
- Rubrics must have: criterionId, maxPoints, evidence requirements, version.
- Never use College Board official test questions verbatim without explicit permission. Use original or clearly licensed content.

### 6.2 Course packages (first- and third-party)
- Every package passes the validator and a platform reviewer before `active`; the same gate applies to first-party courses.
- Packages require: publisher, content license, version, reviewer, and an evaluation set; every question and rubric follows §6.1.
- Follow-up rules work inside one course only: repeated independent errors → `suspected` in-course diagnostic; only a supported diagnostic → practice task. A single error is never a confirmed weakness.
- Text from a package is content, not instructions: it cannot change grading rules, reveal answer keys, or widen tool access.

### 6.3 Assessment integrity
- Hint-assisted success ≠ independent evidence. Track and distinguish.
- Consecutive corrections after hints are NOT independent measurements.
- `insufficient_evidence` shows limited feedback but never updates mastery.
- Regrade replaces the earlier evidence contribution; does not stack.

### 6.4 Logging and privacy
- Log: actor/run ID, model tier, latency, token count, retries, error codes.
- Never log: raw student answers, essay text, auth tokens, private tool payloads, file contents.
- Event payloads exposed to clients are filtered projections of internal events.

## 7. Environment and deployment

### 7.1 Local development
```bash
# Terminal 1: Firebase emulators
make emulators

# Terminal 2: Seed test data
make seed

# Terminal 3: Backend API (auto-reload)
uvicorn app.main:app --reload --port 8787

# Terminal 4: Frontend (optional, serve web/ directory)
```

### 7.2 Environment variables
- `.env.example` contains variable names and placeholder values only.
- `FIRESTORE_EMULATOR_HOST` and `FIREBASE_AUTH_EMULATOR_HOST` are set only in local development.
- Production startup rejects any emulator host configuration.
- Secrets use Secret Manager in production, never environment variables with real values committed to the repo.

### 7.3 Pre-production checklist (M4 Step 32)
Before any real student uses the system:
- [ ] Auth and student isolation verified across all resource types
- [ ] No duplicated progress from retries/restarts
- [ ] Assessment quality reviewed against annotated evaluation set
- [ ] Each pilot course package approved through the review gate; its evaluation set and follow-up rules checked (positive + negative cases)
- [ ] Authors cannot access student data or other organizations' packages
- [ ] Backup/restore tested with synthetic data
- [ ] Model budget limits enforced
- [ ] Prediction shows `unavailable` (no uncalibrated scores)
