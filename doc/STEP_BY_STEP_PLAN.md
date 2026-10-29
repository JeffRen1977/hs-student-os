# High School Student OS — Step-by-Step Implementation Plan v2.0

Updated: 2026-10-29. This plan adopts [the architecture recommendations](STUDENT_OS_ARCHITECTURE_RECOMMENDATIONS.md) and replaces the old 42-step sequence. It implements [API v0.2](API.md), [backend v0.3](BACKEND.md), and [the milestone plan](IMPLEMENTATION_PLAN.md). These are planned steps, not a report of completed implementation.

The first product slice is **Calculus practice → supported assessment → saved evidence → SAT prerequisite diagnostic → justified follow-up → an explained plan**. M0–M4 deliver the pilot; M5 contains independently selectable extensions.

## Working rules and dependencies

- Work only in the Student OS implementation checkout. First inspect what is actually present; a docs-only copy is not a runnable application. Preserve existing changes.
- Do not use LOGIQ code, credentials, services, or API compatibility layers. Build the Student OS contracts independently.
- Other education projects are read-only references. Do not share their JWT secrets, databases, local ports, or filesystem dependencies. Inventory provenance and permissions before adopting any eligible non-LOGIQ utility.
- Use a supported Node.js LTS, TypeScript, Fastify, JSON Schema/Ajv, Student OS Firebase Auth/Firestore, and queue/storage adapters. JSON is fixture data, not production persistence.
- Each step is a reviewable change with relevant verification. Update contracts before implementation if a step reveals a necessary change. Do not mechanically create a commit for every bullet or delete existing work to match a directory diagram.
- Tests must exercise meaningful contracts, authorization, recovery, or learning behavior. Cloud and model evaluations are separate from deterministic local tests; a passing mock does not prove a real provider works.

Target scripts to establish in Step 1: `npm run dev`, `npm run build`, `npm run typecheck`, `npm run lint`, `npm test`, `npm run test:emulator`, `npm run test:e2e`, and `npm run eval:learning`. Script names are a target, not a claim they already exist. Local scripts must explicitly use emulators and synthetic identities; external model evaluations require configured credentials and record actual usage.

## M0 — Contracts and baseline (Steps 1–5)

### Step 1 — Inventory the checkout and establish the TypeScript skeleton

**Deliver:** A baseline inventory, backend structure, supported runtime declaration, dependency lockfile, local setup instructions, and empty-but-runnable verification commands where appropriate. Missing suites must be labeled pending, not reported as passed.

- Inspect the actual web/server state and old API calls. Preserve useful UI/provider boundaries and user changes.
- Establish `src/api`, `src/domain`, `src/workers`, `src/adapters`, `src/registries`, `schemas`, `content`, `fixtures`, and `tests` as needed.
- Implement Fastify health/startup and schema loading. Add TypeScript checking and a test runner; route tests can use Fastify injection.
- Keep environment examples free of credentials. Production startup must reject mock providers and emulator configuration.

**Verify:** Build/typecheck, health route, and invalid configuration rejection. Record which application capabilities remain unimplemented.

### Step 2 — Define shared API and domain schemas

**Deliver:** Schemas matching API.md for Task, Session, Run, Submission, Assessment, events, profile patches, entitlements, and errors.

- Keep Task/Session/Run lifecycles separate. Model relationships explicitly.
- Require stable studentId internally, schemaVersion on events, resource versions where concurrency applies, and question/rubric versions on evidence.
- Reject unknown command fields; enforce ranges and string/file size bounds.
- Define idempotency scope, request canonicalization, and ETag behavior before handlers.

**Verify:** Valid examples parse; client score fields, entitlement edits, forged assessment status, arbitrary event publication, and malformed relationships fail validation. Schemas test format; domain checks later test ownership and evidence.

### Step 3 — Seed two synthetic students and versioned content

**Deliver:** Synthetic fixtures for students A/B, separate preferences/entitlements, one active calc_bc pack, and planned entries for future courses.

- Seed independent studentIds and auth emulator users; no live student information.
- Set exam prediction to unavailable. Keep self-reported exam records separate from practice results.
- Seed a small set of tasks, original/reusable-with-permission questions, rubric versions, and known answers.
- Never promote old demo prediction values to real academic facts.

**Verify:** Fixture schemas pass; identities and resource IDs are isolated; planned packs cannot be treated as executable content.

### Step 4 — Establish the frontend contract and explicit demo mode

**Deliver:** Async data-provider signatures for Twin, tasks, sessions, runs, submissions, assessments, and events.

- Separate input drafts from server-confirmed state. Show queued/running/waiting/failed states.
- Preserve idempotency keys for retrying the same user action.
- Demo fixtures run only through an explicit demo option; API errors never silently replace a real student with Alex.
- Define refresh recovery and event deduplication contracts even before wiring the API.

**Verify:** Provider contract tests and UI states for offline draft, real API failure, and explicit demo. Component changes are allowed where needed to represent the new states.

### Step 5 — Create the learning evaluation baseline

**Deliver:** Reviewed Calculus examples, answer/rubric annotations, prerequisite-mapping candidates and counterexamples, and a versioned evaluation report template.

- Include correct, incorrect, partially correct, assisted, ambiguous, and insufficient-evidence answers.
- Include AP errors that do not imply a SAT prerequisite weakness.
- Record content source, permission, reviewer, rubric version, and expected evidence.
- Define evaluation dimensions and who sets pilot thresholds; do not infer calibrated exam predictions from a few examples.

**Verify:** Each case has a reviewable expected outcome and provenance. This is a content gate, not a model quality pass yet.

## M1 — Reliable foundation (Steps 6–10)

### Step 6 — Implement independent authentication and actor context

**Deliver:** Student OS Firebase ID token verification and stable subject-to-studentId mapping.

- Validate issuer, audience, signature, and expiry; explicitly configure Auth emulator locally.
- Create ActorContext for student requests and separate service/admin actors.
- Ignore no identity boundary: reject untrusted user headers and body-selected identities.
- Use per-student ownership checks before returning resource details.

**Verify:** Expired/wrong-audience tokens rejected; emulator tokens rejected in production configuration; student B cannot select student A. No shared secret or runtime dependency on reference products.

### Step 7 — Implement Firestore repositories and controlled Twin access

**Deliver:** Emulator-backed repositories, Twin summary, profile patch, entitlements read, and course registry reads.

- Store histories in subcollections, not an unbounded Twin document.
- Apply field-level patch allowlists and expectedVersion transaction checks.
- Admin-only entitlement updates are separate from selectedCourses.
- Add required indexes and bounded pagination; enforce isolation in server code even with Admin SDK.

**Verify:** Two-student isolation, concurrent version conflict, unknown/forbidden fields, and profile preferences that do not grant access. Restart the app against retained emulator data and read the same state.

### Step 8 — Implement persistent Task and Session lifecycle

**Deliver:** Task reads/allowed updates and `POST /api/sessions`, Session reads and attempt listing.

- Derive course/agent/mode from the stored Task, not arbitrary client inputs.
- Validate course availability and entitlements. One OPEN Session per Task, transactionally.
- Repeated start returns the existing OPEN Session; repeated idempotency key returns its original result.
- Implement versioned task scheduling/skip rules and Session abandon preconditions.

**Verify:** Unknown course, planned course, active-but-unentitled course, cross-student Task, concurrent starts, and refresh after restart. Entitlement tests use active calc_bc with access removed, not a planned course whose error should be different.

### Step 9 — Accept commands transactionally with Run and outbox

**Deliver:** Message/submission commands, Run status/input/cancel APIs, idempotency records, and persistent outbox.

- Validate question/file references and Session ownership. Persist immutable submissions.
- Atomically create command, Run, request digest, event and outbox; no external calls inside the transaction.
- Same key/same body returns original IDs; changed body conflicts. Allow at most one nonterminal Run per Session.
- Persist cancelRequested and typed WAITING_INPUT requests; user answers match inputRequestId and schema.

**Verify:** Duplicate submission, conflicting body, concurrent commands, foreign file/question, stale input response, and cancellation racing with enqueue. A transaction failure leaves neither orphan Run nor lost accepted command.

### Step 10 — Execute recoverable jobs with a queue adapter

**Deliver:** Local durable dispatcher, Cloud Tasks adapter, worker leases/fencing, retry/timeout recovery, and synthetic execution for internal tests.

- Dispatch from outbox, with immediate best-effort delivery plus reconciliation scans.
- Authenticate production worker invocations using service OIDC and correct audience.
- Check terminal state and acquire a transactional lease; persist bounded-step checkpoints and tool-call ledger.
- Expired leases can requeue the same Run. Old fencing tokens cannot commit.
- Treat task delivery as at least once; terminal business effects are idempotent. Model calls can still incur duplicate cost after uncertain failure.

**Verify M1:** Restart after API commit before dispatch; restart after queue enqueue before outbox acknowledgement; duplicate deliveries; crash during work; stale worker commit; cancel/commit race. Synthetic outputs stay labeled and are never accepted as real grading evidence.

## M2 — Calculus learning loop (Steps 11–15)

### Step 11 — Implement LLMGateway, static routing, and budgets

**Deliver:** Provider abstraction with typed input/output, model/workflow version capture, usage accounting, and finite retries.

- Start with one model provider and static skill tiers. No Jev dependency.
- Budget Run, Session, and daily student usage, including retries.
- Validate output structure. Failed validation may retry within budget; otherwise return failure/insufficient evidence.
- Never silently downgrade grading to an unevaluated model just to fit a budget.

**Verify:** Provider timeout, schema failure, budget exhaustion, usage logging, and safe failure states. Run a separately labeled real-provider smoke test when configured; no secrets or raw student work in logs.

### Step 12 — Implement the first Calculus skills and tools

**Deliver:** Socratic guidance and rubric assessment for the reviewed calc_bc task family.

- Load fixed pack/question/rubric/workflow versions and minimal relevant student context.
- Retrieve from small reviewed material sets with source references and ACL filters.
- Use an internal ToolRegistry for necessary mathematical checks; a Python/SymPy adapter is optional when needed and must be genuinely executed and tested.
- Record server-issued hints. Distinguish assisted success from independent evidence.

**Verify:** Held-out examples from Step 5, irrelevant source rejection, invalid evidence references, and tool failure handling. No display of fabricated tool success or unsupported grader conclusions.

### Step 13 — Commit assessments and progress atomically

**Deliver:** `AssessmentService.commitAssessment()` and completion/abandon handlers matching API.md.

- Validate evidence semantically, not only JSON shape. Persist accepted or insufficient_evidence assessment status.
- In one transaction save accepted evidence contribution, affected mastery, Run result, events, and outbox. Insufficient evidence never changes mastery.
- Use unique evidence application IDs. A regrade supersedes the earlier contribution; repeated attempts on the same question are not counted as independent evidence.
- Session completion checks stored requirements and active Run state, then updates Task/Session and events without adding mastery again.
- Keep prediction unavailable.

**Verify:** Partial transaction failure, replayed commit, stale lease, concurrent cancellation, regrade replacement, insufficient evidence, and repeated complete. Saved results remain correct after restart.

### Step 14 — Connect the real workspace and durable event feed

**Deliver:** End-to-end typed answer → Run → feedback → completion UI, plus SSE and polling.

- Read the server's completion eligibility; never calculate academic truth in the browser.
- Fetch state snapshot with event watermark; replay subsequent events using sequence and deduplicate event IDs.
- Use authenticated fetch streaming, not access tokens in URLs. Support heartbeat, deployment timeout reconnect, expired cursor, and polling fallback.
- Drive SSE from persistent events across instances; in-process pub/sub is only an optimization.

**Verify:** Close/reopen browser while grading; reconnect to a different API instance; lost SSE message replay; expired cursor resync; permission expiry; repeated network submission. Real API errors retain truthful state instead of substituting demo data.

### Step 15 — Complete Calculus evaluation; add uploads only after text works

**Deliver:** A recorded learning-quality evaluation and, if included in the pilot, the file/OCR extension.

- Compare rubric criteria and evidence with independent human annotations, including assisted answers and counterexamples.
- Track false acceptance, refusal/insufficient rates, per-assessment cost, and feedback usefulness.
- For files: implement upload metadata, limited signed upload, readiness validation, scoped download, and submission ownership checks.
- For OCR: preserve original upload and recognized text; ambiguous text requests typed confirmation before assessment.
- If file/OCR work is deferred, declare the pilot text-only and keep upload capability disabled.

**Verify M2:** The full Calculus loop works with a real evaluated skill. No unsupported progression, false official score, duplicate evidence, or unauthorized file access. Passing a handful of smoke tests is not sufficient evidence to release calibrated predictions.

## M3 — Validated SAT transfer (Steps 16–20)

### Step 16 — Implement reviewed prerequisite mappings

**Deliver:** Versioned mappings with source AP observations, target SAT skills, conditions, and counterexamples.

- Only eligible accepted evidence generates prerequisite.suspected.
- Retain source assessment and mapping version. Suspected is a recommendation for diagnosis, not a confirmed SAT weakness.
- Mathematical topic overlap alone is insufficient. Suppress unrelated calculus-only errors.

**Verify:** Reviewed positive/negative mapping cases; missing evidence; unknown mapping version; repeated source evidence. Uncertainty is visible to the student.

### Step 17 — Add the SAT short diagnostic workflow

**Deliver:** DSAT capability for the selected prerequisite, using reviewed questions and the shared runtime.

- Require DSAT entitlement and available diagnostic content.
- Record independent performance, hint dependence, and relevant Assessment results.
- Use supported/unsupported/insufficient outcomes. Do not convert this short diagnostic into a SAT exam score.

**Verify:** Correct, incorrect, hinted, insufficient, and access-denied paths. Task/Session/Run persistence works without a separate DSAT service or reference-app login.

### Step 18 — Implement replay-safe domain consumers

**Deliver:** suspected → diagnostic Task and confirmed → reinforcement Task consumers.

- Consume durable events with per-consumer receipts.
- Atomically write the target Task and receipt keyed by consumer/event/targetSkill.
- Unsupported/insufficient outcomes do not create reinforcement; record the reason.
- Repeated related observations do not flood an existing active diagnostic. Maintain a domain-level dedupe key in addition to event dedupe.

**Verify:** Crash before/after receipt commit, replayed events, repeated observations, two-student isolation, and unsupported branch. Exactly one intended Task exists per dedupe scope.

### Step 19 — Implement evidence-aware incremental planning

**Deliver:** Versioned plan updates that place follow-up work within available time.

- Rank reviewed learning needs and diagnostics against deadlines and student preferences.
- Preserve IN_PROGRESS/COMPLETED tasks and student locks. Defer suggestions if budget is full.
- Keep explanations tied to real assessments, mappings, and schedule facts.
- Do not calculate speculative admissions leverage or modify a school category from an internal practice estimate.

**Verify:** Full schedule, conflicting deadlines, manual locks, no reliable assessment, and concurrent plan updates. No duplicated or disappearing task caused by full regeneration.

### Step 20 — Verify the complete transfer slice

**Deliver:** End-to-end evidence for the first product differentiator.

1. Calculus answer reveals an eligible possible prerequisite issue.
2. Student sees why a short SAT diagnostic is proposed.
3. Confirmed case creates reinforcement within the plan; unsupported case does not.
4. Restarts, duplicate deliveries and SSE reconnections preserve a single consistent result.
5. Student can explain the recommendation and change its timing.

**Verify M3:** Run both positive and negative chains with reviewed content, plus cross-student and replay checks. Report mapping mistakes and revise content before widening coverage.

## M4 — Proactive planning and pilot (Steps 21–25)

### Step 21 — Implement timezone-aware scheduled planning

**Deliver:** Cloud Scheduler trigger, dueAt scan, per-student local-day planning, and reconciliation.

- Deduplicate using studentId/localDate/reason or sourceEvent; persist next due time.
- Respect IANA timezones, DST changes, and updated preferences.
- Use the same Planner for scheduled and event-driven updates. GET tasks has no hidden mutation.

**Verify:** DST boundaries, timezone change, duplicate scheduler invocations, API/worker downtime, and overlapping assessment-driven replanning.

### Step 22 — Finish student controls and opt-in reminders

**Deliver:** Defer/skip/lock controls and one configured reminder channel.

- Record consent, quiet hours, frequency caps, and delivery dedupe keys.
- Check consent again immediately before sending. A queued reminder can become ineligible.
- Default to no parent notification; parent access is a separate later feature.
- Use a fake delivery adapter in tests. A live delivery check must use a designated test recipient.

**Verify:** Opt-out after enqueue, quiet hours, repeated delivery, changed deadline, completed task, and student control persistence.

### Step 23 — Deploy the owned infrastructure to staging

**Deliver:** Reproducible configuration for Cloud Run API/worker, Firestore, Cloud Tasks, Scheduler, Storage, and secrets.

- Use separate service identities and permissions, protected worker invocation and configured audience.
- Keep emulator hosts and synthetic model providers out of production startup.
- Configure timeouts, finite retries, task limits, and SSE reconnect behavior rather than assuming indefinitely open requests.
- Record which infrastructure checks ran and which credentials/resources were unavailable.

**Verify:** Real queue OIDC rejection/acceptance, cross-instance recovery, request timeout handling, private object access, and finite cost limits. Local emulator success is not a staging pass.

### Step 24 — Add operations and restore verification

**Deliver:** Metrics, alerts, data/file retention procedure, and tested backup/restore instructions.

- Measure accepted assessment latency/cost, worker failures, outbox backlog, duplicate suppression, and learning-quality regressions.
- Logs exclude raw student answers, drafts, tokens and private tool payloads.
- Restore a synthetic student with linked files, assessments and event state into a separate test environment.
- Verify delete/retention effects on indexes, artifacts and future backup expiry.

**Verify:** Simulated backlog/failed worker alert, actual restore consistency, and scoped data deletion. A backup script that has never been restored is not a completed check.

### Step 25 — Apply the external-pilot gate

**Deliver:** A recorded go/no-go result for the narrow product scope.

- Quality: reviewed rubric feedback, unsupported-answer behavior, validated mapping, independent follow-up performance, and comprehensible plan explanations.
- Reliability: no duplicated progress, restart recovery, replayable events, and truthful failed/waiting states.
- Access: auth and student isolation across records/files/retrieval; entitlements cannot be self-granted; no default parent access to private material.
- Operations: model budget, opt-in reminders, cloud authentication/timeouts, and tested restore.
- Record sample sizes, thresholds, reviewer sign-off and unresolved limitations. If scope is text-only, say so explicitly.

**Verify M4:** M0–M3 acceptance chains run in staging plus pilot usability checks. Real students enter only after the relevant gates pass; documentation updates alone never mark these steps complete.

## M5 — Optional expansion after pilot evidence (Steps 26–30)

### Step 26 — Expand AP coverage, starting with APUSH

**Deliver when selected:** Reviewed APUSH content/rubrics and appropriate UI, followed by other courses only as justified.

- Reuse the runtime and schemas, but add engineering for new answer formats/tools when required.
- Pin content versions and evaluate each course before changing planned to active.
- Grow MCQ/FRQ coverage intentionally; no blanket promise that adding a manifest implements a subject.

**Verify:** Course-specific evaluation, access checks, evidence storage and replay. Existing Calculus regression cases still pass.

### Step 27 — Add admissions interviews and sourced planning

**Deliver when selected:** Interview → student-confirmed facts → outline/feedback, with school-data provenance.

- Keep authored essay text with the student; no one-click complete essay generation.
- Track official deadline sources, verification dates and uncertainty. Internal practice estimates cannot silently reclassify schools.
- Activity edits require student confirmation of facts before saving.

**Verify:** Behavioral cases for fabricated facts, insufficient school data, conflicting dates, and requests for complete ghostwritten essays. Keyword scanning is not a substitute for output evaluation.

### Step 28 — Add scoped parent summaries

**Deliver when selected:** Separate parent identity, explicit student relationship, summary:read scope and revocation.

- Summary projection excludes private chats, original answers and essay drafts by default.
- Consent and relationship checks apply to every access and queued delivery.
- Counsellor access, payments and organization-wide visibility require their own later contracts.

**Verify:** Parent A/B relationship isolation, revoked authorization, field-level projection, and no private artifact URL leakage.

### Step 29 — Calibrate mastery and exam predictions separately

**Deliver when selected:** An evaluated estimation method, calibration report, and explicit release criteria.

- Compare mastery estimates against independent held-out responses; BKT is one candidate, not an automatic exam-score converter.
- Exam prediction requires representative assessment coverage and independent outcomes, with uncertainty and population limits.
- Keep practice performance, self-reported/verified exam records, and predictions distinct in storage and presentation.

**Verify:** Calibration and subgroup/coverage analysis with documented data limits. Without sufficient evidence, prediction stays unavailable rather than showing unsupported precision.

### Step 30 — Evaluate optional infrastructure and integrations

**Deliver only if justified:** A measured decision on Jev, MCP adapters, Temporal, semantic indexes or external product APIs.

- Verify actual vendor availability, interfaces, quality and costs before depending on claims in old documents.
- Jev must remain replaceable; static routing/rules keep core workflows usable.
- MCP adapts existing controlled tools. Temporal is considered when durable coordination requirements exceed the current bounded-job design.
- External integrations use independently authorized identity mapping; no reference-project secrets or local runtime dependencies.

**Verify:** Benefit against the current baseline, disabled-provider behavior, permission boundaries and quality/cost regressions. It is valid to keep all these options deferred.

## Delivery map

| Milestone | Steps | Exit |
|---|---|---|
| M0 Contracts and baseline | 1–5 | Checked baseline, schemas, fixtures, evaluation cases |
| M1 Reliable foundation | 6–10 | Independent identity, durable execution and replay |
| M2 Calculus learning loop | 11–15 | Supported feedback and evidence-backed progress |
| M3 Validated SAT transfer | 16–20 | Diagnostic-confirmed follow-up in the plan |
| M4 Proactive planning and pilot | 21–25 | Scheduled, recoverable and evaluated pilot |
| M5 Optional expansion | 26–30 | Individually validated extensions |

The old steps that accepted scoreDelta, stored sessions only in memory, exposed event publication, postponed identity/isolation to M5, or made Jev M4 prerequisites are superseded. Retain old data only through a reviewed migration; do not preserve unsafe semantics for compatibility.
