# High School Student OS — backend

Python 3.12 · FastAPI · Pydantic v2 · Firestore/Firebase Auth (emulators locally) · uv.

```bash
make install          # uv sync (from repo root)
make server           # uvicorn app.main:app --reload --port 8787 (needs emulators, see below)
curl localhost:8787/api/health
make check            # ruff + mypy --strict + pytest + web tests
```

Emulators (need Firebase CLI and **Java 11+**):

```bash
make emulators        # terminal 1: Auth :9099, Firestore :8080, UI :4000
make seed             # terminal 2: two synthetic students (stu_alex, stu_beth) + tasks
make server           # terminal 3: API + in-process local worker loop
make test-emulator    # or: start, seed-test, and stop emulators in one command
```

Without Java, `HSOS_STORAGE_PROVIDER=memory` runs the API over an in-process store seeded
with the same fixtures (data is lost on restart; staging/production refuse it).

Copy `.env.example` to `.env` for local settings. `staging`/`production` refuse to start with
emulator hosts, mock providers, a local queue, memory storage, a local worker token, or a
`demo-*` project.

## Runtime shape (M1)

- **API** (`app.main:app`): verifies Firebase ID tokens → `ActorContext`; routes delegate to
  domain services. Commands write content + Run(QUEUED) + idempotency record + outbox entry
  + events in one transaction, then try an immediate dispatch.
- **Worker** (`app.workers.main:app`, separate Cloud Run service): `/internal/runs/execute`
  (Cloud Tasks, OIDC), `/internal/outbox/dispatch` and `/internal/runs/recover` (Scheduler).
  Leases + fencing tokens make duplicate/late deliveries harmless.
- **Local**: `HSOS_QUEUE_PROVIDER=local` runs recovery → outbox dispatch → worker in the API
  process every `HSOS_LOCAL_WORKER_POLL_SECONDS`.
- **Synthetic execution** (`HSOS_LLM_PROVIDER=mock`): deterministic, labeled agent replies
  (`synthetic: true`). It never produces an Assessment or mastery evidence.

## Learning loop (M2)

- **LLM gateway** (`app/adapters/llm/`): static tier routing, per-run/session/day token
  budgets (reserve → settle, retries charged), finite retries with backoff, output
  validation, usage logs without content. `HSOS_LLM_PROVIDER=anthropic` uses Claude
  (`ANTHROPIC_API_KEY`); `HSOS_LLM_PROVIDER=openai` uses the OpenAI Responses API
  (`OPENAI_API_KEY`, strict JSON schema, `store=false`). Keys may live in the gitignored `.env`.
- **Skills** (`app/domain/skills/`): Socratic guidance (every reply is a recorded hint) and
  rubric assessment (evidence quoted from the stored answer, per-criterion `assessable`,
  math-verify cross-check). One shared runtime, `SkillExecutor`, per-course packs.
- **AssessmentService**: semantic validation + Assessment + mastery + Run terminal state +
  events in the worker's commit transaction; `complete` closes Session/Task.
- **Event feed**: `GET /api/events` and SSE `GET /api/events/stream` (Bearer auth,
  `Last-Event-ID`, heartbeats, closes before the request timeout or token expiry).
- **Evaluation** (Step 21): `HSOS_LLM_PROVIDER=anthropic|openai uv run python -m
  scripts.run_calc_evaluation --out content/evaluation/calc_bc/report-v1.md` (real model,
  costs money). `tests/evaluation/test_real_provider_smoke.py` is opt-in via
  `HSOS_RUN_REAL_LLM_SMOKE=1`.
- The pilot is **text-only**: no file upload endpoints or UI yet.

| Path | Contents |
|---|---|
| `app/schemas/` | Pydantic API contract (API.md v0.3), content and fixture schemas |
| `app/domain/types/`, `app/domain/ports/` | Pure-Python domain types, state machines, ports (stores, unit of work, queue, executor) |
| `app/domain/*_service.py`, `run_execution.py`, `recovery.py` | Business rules: twin, courses, tasks, sessions, commands, leases, recovery |
| `app/api/` | Auth/idempotency/If-Match dependencies, presenters, routes |
| `app/adapters/firestore/` | Repositories over the `DocTxn` seam; Firestore and in-memory backends |
| `app/adapters/` | Firebase init, token verifier, queues (local, Cloud Tasks), synthetic executor |
| `app/workers/` | Worker HTTP app, outbox dispatcher, service auth, local loop |
| `app/bootstrap.py` | Composition root (the only place concrete adapters are chosen) |
| `content/` | Versioned packs, questions, rubrics, mappings, evaluation baseline (all `draft` until reviewed) |
| `fixtures/` | Synthetic students, entitlements, and tasks only |
| `scripts/seed_emulator.py` | Emulator-only seeding (refuses non-`demo-*` projects) |

Tests: `tests/unit` and `tests/contract` run everything over the in-memory store with real
(emulator-mode, offline) token verification. `tests/emulator` re-runs the transaction-critical
flows on real Firestore and is skipped unless the emulators are configured.
