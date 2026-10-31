# High School Student OS — backend

Python 3.12 · FastAPI · Pydantic v2 · Firestore/Firebase Auth (emulators locally) · uv.

```bash
make install          # uv sync (from repo root)
make server           # uvicorn app.main:app --reload --port 8787
curl localhost:8787/api/health
make check            # ruff + mypy --strict + pytest + web tests
```

Emulators (need Firebase CLI and **Java 11+**):

```bash
make emulators        # terminal 1: Auth :9099, Firestore :8080, UI :4000
make seed             # terminal 2: two synthetic students (stu_alex, stu_beth)
make test-emulator    # or: start, seed-test, and stop emulators in one command
```

Copy `.env.example` to `.env` for local settings. `staging`/`production` refuse to start with
emulator hosts, mock providers, a local queue, or a `demo-*` project.

| Path | Contents |
|---|---|
| `app/schemas/` | Pydantic API contract (API.md v0.3), content and fixture schemas |
| `app/domain/types/`, `app/domain/ports/` | Pure-Python domain types, state machines, repository protocols |
| `app/registries/` | Content, fixture, and evaluation-set loaders with cross-reference checks |
| `app/adapters/` | Firebase/Firestore initialization, seed document builder |
| `content/` | Versioned packs, questions, rubrics, mappings, evaluation baseline (all `draft` until reviewed) |
| `fixtures/` | Synthetic students and entitlements only |
| `scripts/seed_emulator.py` | Emulator-only seeding (refuses non-`demo-*` projects) |
