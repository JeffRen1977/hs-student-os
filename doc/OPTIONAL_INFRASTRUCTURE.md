# Optional infrastructure assessment (Step 38)

Updated: 2026-11-04. **Decision: adopt none of these now.** Each section says what problem the
option would solve, why the current system does not have that problem yet, and the trigger that
would reopen the decision. CLAUDE.md §3.5 already rules out MCP servers, Jev integration and
Temporal "until explicitly justified in M5"; this document is that justification check, and
the answer today is no.

Scope of the evidence: the codebase as of M5 (in-memory and staging smoke tests, synthetic data
only). There is no pilot traffic yet, so no option can be justified by measured load or by
observed failures.

## Summary

| Option | Would replace / add | Today | Adopt when |
|---|---|---|---|
| Jev | An external agent/knowledge layer from the reference projects | Not adopted | Never as a dependency of the core loop; only as an optional, separately reviewed integration with its own contract |
| MCP adapters | A protocol for exposing tools/content to models | Not adopted | A second model-facing consumer (e.g. an IDE or partner agent) needs the same tools under the same authorization |
| Temporal | Durable workflow engine | Not adopted | A workflow needs multi-step, long-running human waits that the Run/outbox model cannot express without a hand-written state machine |
| Semantic index (vector search) | Embedding retrieval over course materials | Not adopted | A course's materials exceed what deterministic, skill-tagged retrieval fits in the context budget, shown by an evaluation |

## Jev

- **What it would do:** a shared agent or knowledge service from the reference projects.
- **Why not:** CLAUDE.md §1.1 forbids depending on the reference projects (`ai-college-advisor`,
  `sat-tutor-app`) or sharing their credentials, data or ports. The platform must build, test and
  run with those directories removed. A hard dependency would also reintroduce the earlier design
  that BACKEND.md v0.4 replaced (a mandatory Jev dependency).
- **Trigger:** none for the core loop. If an integration is ever wanted, it goes behind a port in
  `app/domain/ports/` with its own contract, review and kill switch, and the core loop keeps
  working without it (this test enforces that: `tests/unit/test_optional_infrastructure.py`).

## MCP adapters

- **What it would do:** expose the tool registry (math-verify, content retrieval) and course
  content to model clients through the Model Context Protocol.
- **Why not:** there is exactly one model-facing consumer, the platform's own `LlmGateway`, and
  tools are already whitelisted per skill *and* per course package (`ToolRegistry`). An MCP
  server would add a second authorization path that must reproduce `ActorContext`, per-student
  isolation and the per-package tool whitelist; a mismatch there is a data-exposure risk with no
  current benefit. Course packages must not be able to widen tool access (CLAUDE.md §6.2).
- **Trigger:** a concrete second consumer that needs the same tools (for example a partner
  authoring assistant). Even then, the adapter would call the existing registry and domain
  services rather than read storage directly, and authors would still never see student data.

## Temporal

- **What it would do:** durable, long-running workflows with timers and human waits.
- **Why not:** every workflow so far fits the existing pattern: one transaction writes the
  command, a QUEUED Run and an outbox entry; a lease + fencing-token worker executes; recovery
  scans re-queue stalled work; consumers replay from offsets with receipts. M5 added two new run
  kinds (admissions) and a production consumer (course metrics) without new infrastructure.
  Temporal would add a second source of truth for execution state next to Firestore, a new
  service to operate, and a migration of every Run.
- **Trigger:** a workflow that needs several dependent steps with long human waits between them
  and compensation on failure (for example a multi-reviewer, multi-week content approval with
  deadlines), where expressing it as Runs would mean writing a custom workflow engine — which
  CLAUDE.md §3.5 also forbids.

## Semantic index

- **What it would do:** embedding-based retrieval of course materials for tutoring and grading.
- **Why not:** retrieval today is deterministic: reviewed materials tagged with skills, filtered
  by course (and by student for a student's own material), within the package's context budget.
  That is auditable — a reviewer can see exactly which passages a run could use — and grading
  with `source-analysis` uses the question's named sources, not search results. Courses are
  small (tens of passages). An index would add an embedding provider, a store to keep in sync
  with package versions (pinned per Run), and a new place where student materials would have
  to be deleted.
- **Trigger:** an evaluation showing that answers suffer because relevant reviewed material did
  not fit the context budget under deterministic retrieval. Any index would be per course and
  per package version, rebuilt on activation, and student materials would stay out of shared
  indexes.

## Step 38.2 (vendor verification): deferred

Availability, interfaces, pricing and quality of specific vendors are deliberately **not**
recorded here: none is being adopted, and such figures go stale quickly. When a trigger is
met, the check must use current vendor documentation and a small evaluation on synthetic data
before any decision.

## Step 38.3: core workflows without optional dependencies

`tests/unit/test_optional_infrastructure.py`:

1. no optional package (Temporal, MCP, Jev, LangChain/LlamaIndex, common vector stores) is a
   runtime dependency in `server/pyproject.toml`;
2. with those modules made unimportable, the app imports, `/api/health` answers, and a full
   learning loop (session → submission → run → assessment) completes.
