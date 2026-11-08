# Business Review — High School Student OS

Date: 2026-11-07. Basis: full inspection of the current Mac project
(`/Users/jeffren/Documents/education/hs-student-os`, 757 files), README.md,
doc/PILOT_GATE.md, doc/COURSE_PACKAGE.md, and the deployed architecture.
This review supersedes the framing of the 2026-10-29 COMPETITIVE_REVIEW.md
where the two differ — the product has changed category since then.

---

## 0. What the platform actually is now (the Oct 29 review is out of date)

In ten days the project moved from "multi-agent prototype, backend paused"
to a **deployed course-package platform**:

- **Courses are data, not code.** A course package = skills, question bank,
  rubrics, course requirements, completion/follow-up rules, and an
  evaluation set, running on one shared runtime. Calc BC is the first-party
  reference course; Digital SAT was rebuilt *purely through the authoring
  path* — proof the packaging works.
- **A publishing pipeline, not just an app.** Author portal (upload,
  validator + evaluation reports, preview, metrics) → reviewer screen
  (approve/reject with answer keys and version diffs) → admin publishes to
  the catalog. Versions are pinned per Run; retire/supersede semantics exist.
- **Production-grade backend, already on GCP staging.** FastAPI + Firestore
  + Firebase Auth, two Cloud Run services (API + private worker), Cloud
  Tasks/Scheduler, outbox + lease/fencing + idempotency, SSE event feed,
  LLM gateway with tier routing and token budgets. Staging deployed and
  smoke-tested (Nov 3–5).
- **Integrity guarantees as design law.** No client authority; exam
  predictions stay `unavailable` (no fabricated scores);
  `insufficient_evidence` never updates mastery; hint-assisted success is
  not independent evidence.
- **The honest blocker:** PILOT_GATE.md (Step 33) is **not passed**. No
  named reviewer has signed off, thresholds are unset, Calc BC is not yet
  converted to a reviewed package, follow-up rules (Step 24.2) are
  unimplemented, and there is no real reminder channel. Real students are
  correctly barred until this closes. **Every business question below is
  downstream of this gate.**

## 1. Uniqueness audit

### Genuinely unique (sell these)

1. **A reviewed course-package runtime — an "app store" architecture for
   courses.** Khanmigo, Photomath, Duolingo Max, Riiid/Santa are all
   single-vendor content baked into one app. Nobody in US high-school test
   prep ships: third-party-authorable course packages + validator +
   mandatory evaluation set + human review gate + version pinning on one
   runtime. This is the platform asset; everything else is a feature.
2. **The evaluation set as a quality gate.** A course cannot go `active`
   without passing its own eval set, and every version is re-evaluated.
   Competitors A/B test on students; you regression-test on eval sets
   first. For parents and schools this is a *safety/quality* story no
   chatbot wrapper can copy quickly.
3. **Evidence integrity.** "We never show a predicted score we can't
   support; a hinted answer doesn't count as mastery." In a market full of
   inflated score predictions, this is a trust brand — and it's enforced
   by the architecture (server-side assessment, atomic mastery commits),
   not by marketing copy.
4. **One student record, cross-course weekly plan.** The core loop
   (evidence → record → next task → weekly plan spanning all enrolled
   courses, courses never contaminating each other) remains differentiated
   vs. per-subject apps. It is the retention mechanism: the plan is why a
   student comes back daily.

### Not unique (don't sell these)

- Socratic AI tutoring, rubric-graded FRQs, adaptive SAT practice: table
  stakes in 2026. Khan Academy/Khanmigo and a dozen startups cover them.
- The tech stack itself (agents, LLM routing, Firestore): copyable in
  weeks. **The moat is not the runtime — it is the reviewed content
  library, the eval sets, and the accumulated per-student evidence data,
  all of which compound and none of which a competitor can download.**

### The strategic consequence

You are not building "a better SAT app." You are building **course
infrastructure with two first-party courses as proof**. Price and pitch
accordingly: the long-term asset is the catalog + author pipeline, and
every first-party course should be produced *through* the authoring path
(as DSAT was) so the pipeline stays the product.

## 2. Business model

Four models, ranked by fit to what exists today:

| Model | Who pays | Price anchor | Fit now |
|---|---|---|---|
| A. B2C subscription (parents) | Parents of 10th–11th graders on 3 fronts (3+ APs + SAT + Top-50) | $39–49/mo all-access; $19–29 single course | Good, after pilot gate |
| B. Exam-season pass | Same parents, seasonal | $149–199 per AP season (Feb–May) or SAT cycle | Good — matches how parents actually budget |
| C. B2B2C license | Tutoring centers / after-school programs / small schools | $8–15 per student/mo, min. seats | **Best margin-per-effort**: they bring students (zero CAC) and can publish *their own* courses via the author portal |
| D. Author marketplace | Third-party course authors | 70/30 revenue share | Later — needs catalog demand first; the pipeline is already built |

**Recommended sequence (hybrid, in this order):**

1. **Paid founding cohort (Dec 2026–Jan 2027).** 20–30 families from your
   own parent network, founding price ($29/mo or $149 to June), concierge
   onboarding. Purpose is not revenue — it is willingness-to-pay evidence
   and reference outcomes before the AP season.
2. **B2C all-access + season pass for the AP window (Feb–May 2027).** May
   AP exams and March/May/June SATs are the revenue calendar of this
   industry; launch pricing and the free diagnostic funnel (from the Oct
   review's P0 list) should land in January, not after.
3. **One or two tutoring-center licenses (summer 2027).** Pitch: "your
   curriculum, our runtime — your teachers author packages, our reviewer
   pipeline keeps quality, your students get the planner." This is the
   only channel where your package architecture is itself the sales pitch.
4. **Marketplace (2028, if at all).** Open authoring only after the
   catalog has paying demand; a marketplace with no buyers is a cost.

**One design tension you must resolve before charging parents:** the
current design deliberately gives parents *no access* (PILOT_GATE 33.3:
"default no parent access ✅"). But in Model A/B the parent is the payer.
Payers who see nothing churn. Compromise that preserves the student-trust
design: a **weekly parent digest** (email: plan adherence, mastery deltas,
courses active — no answer content, no surveillance) as a paid-tier
feature. Decide this before the founding cohort, not after the first
churn.

## 3. Profitability math (why this can actually make money)

- **Marginal cost per student is structurally low.** Choice-scored courses
  (Digital SAT) are graded by answer key in the worker — *zero model
  calls*. Model spend concentrates in rubric/Socratic courses (Calc BC
  FRQs). With the gateway's token budgets enforced, a realistic blended
  COGS is **~$3–8 per active student/month** at moderate use.
- **Infra is near-zero at pilot scale.** Cloud Run + Firestore +
  Scheduler on a dedicated project; staging budget alert is set at $20.
  Fixed cost is essentially your time plus content production.
- **Break-even is small.** At $39–49/mo and ~$5 COGS, contribution is
  ~$35–44/student. **~60–120 paying families cover infra, model spend,
  payment fees, and a modest content budget** — i.e., profitable as a
  side business at cohort scale, long before "startup scale."
- **The real cost center is content, not compute.** Converting Calc BC to
  a reviewed package, setting thresholds, and reviewing are human-hours.
  The author-kit + AI-assisted authoring path is your cost lever: DSAT
  proved a course can be produced through the pipeline; measure
  *hours per course* and drive it down each course.
- **CAC is the swing factor.** Paid ads for SAT/AP keywords will eat the
  margin. Your unfair channels are free: parent communities at your own
  school, Chinese-American parent networks, and (later) tutoring-center
  partners who supply students at $0 CAC under Model C.

## 4. How to iterate (four loops, in priority order)

### Loop 1 — Pilot-gate loop (now → December)
The gate list *is* the backlog. Named reviewer + thresholds → re-run
evals on the chosen provider (Anthropic) → Step 24.2 follow-up rules →
Calc BC through the review gate (Step 22.3) → pick a real reminder
channel (or formally disable reminders for the pilot) → Step 32 cloud
verification. Nothing else matters until real students are legal.

### Loop 2 — Course quality loop (continuous, already architected)
Evaluation sets are regression tests for teaching. Iterate per course:
eval pass rate by criterion → fix the worst rubric/prompt → new package
version → re-eval → activate. Because Runs pin versions, you can compare
mastery-delta-per-hour between versions on real students later. Target
metric: **eval false-credit rate = 0** (the one known Calc BC false-credit
is the first item to close).

### Loop 3 — Learning/product loop (from first pilot students)
Instrument what the event stream already emits:
- Activation: diagnostic → first completed task within 24h.
- Plan adherence: % of weekly-plan tasks completed (the core promise).
- Mastery delta per study hour, per course (your outcome evidence).
- W2/W4 retention by course; parent-digest open rate (payer health).
Review weekly; the planner's rules (not the models) are the cheapest
thing to tune and the highest-leverage for adherence.

### Loop 4 — Business loop (from founding cohort)
Per cohort: conversion (diagnostic → paid), churn aligned to the exam
calendar (expect and design for post-exam churn — season passes price it
in), hours-per-new-course, and support minutes per family. Kill or fix
any course whose mastery delta doesn't beat its content cost.

### Sequenced roadmap
- **Nov–Dec 2026:** Close pilot gate (Loop 1). Parent-digest decision.
  Free diagnostic funnel build (three-front gap map) — it is both the
  top of funnel and the cohort recruiting tool.
- **Jan 2027:** Founding cohort live (Calc BC + DSAT only). Pricing page
  with season-pass option.
- **Feb–May 2027:** AP season = first real revenue window. Add APUSH or
  Physics C package only if hours-per-course from DSAT/Calc says you can
  do it without dropping quality gates.
- **Summer 2027:** B2B2C pilot with 1–2 tutoring centers; admissions
  package (content already stubbed in `server/content/admissions`)
  becomes the third front for the fall application season.
- **Fall 2027:** Admissions season pass; evaluate marketplace opening.

## 5. Risks that can kill it (watch list)

- **Reviewer bottleneck.** The quality gate needs a named human reviewer;
  today that's you. Every course and version queues behind one person —
  recruit one trusted educator-reviewer before the catalog grows.
- **Payer invisibility** (see §2): unresolved, it caps B2C retention.
- **Content IP discipline.** Red lines already set (no College Board real
  items, self-authored only) — keep them; one takedown ends the trust
  brand that is your main differentiator.
- **Minor-privacy compliance.** Real students = COPPA/state student
  privacy laws and school-district expectations; the pre-production
  checklist (CLAUDE.md §7.3) must be part of the gate, not an afterthought.
- **Calendar risk.** Miss the January launch and you miss the AP revenue
  window until 2028. The schedule in §4 is built backwards from May 2027.

## 6. Decisions needed from you (one word each is fine)

1. **Parent digest**: build the weekly payer digest (recommended) or keep
   zero parent visibility?
2. **First revenue motion**: founding cohort first (recommended) or go
   straight to a tutoring-center license?
3. **Reviewer**: who is the named reviewer for the pilot gate — you, or a
   recruited educator?
4. **Pricing anchor**: all-access $39/mo + $149 season pass (recommended
   starting point) or your own number?
