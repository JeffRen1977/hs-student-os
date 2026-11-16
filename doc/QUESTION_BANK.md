# Organization question bank, authoring agents and content review — contract v1

Status: **approved by the owner 2026-11-15.** Implemented 2026-11-15: roles, items and their review (45.1–45.3).
Also implemented: passages (version 1, read endpoint), development seeding (45.6), selections and the
builder (45.4), and the portal screen `web/bank.html` (45.5). Not yet: sources and imports (Step 39). This document is the contract for the
question bank. API.md §6.5.7, BACKEND.md §2–3, COURSE_PACKAGE.md §7 and CLAUDE.md summarize it and point here;
where they differ, this document wins until the code exists.

## 1. Goal

Authors bring question material in any form (photos, PDFs, pasted text, links). An authoring agent extracts it
into the organization's **question bank**. The author checks and edits the extracted questions. A **content
reviewer of the same organization** decides which questions go into the course package and supplies answer keys
and solutions where the source has none. The package built from that selection then goes through the existing
platform review gate unchanged.

```
Author supplies inputs ─► ImportJob ─► extraction Run (authoring agent, LLM gateway, worker)
  (images, PDF, text, links)              │
                                          ▼
                              BankItem v1  state: extracted   (agent output, never content)
                                          │ author opens, edits, confirms
                                          ▼
                                     state: draft ──► author submits ──► state: in_review
                                                                              │
                         content reviewer (same org): fix text, set key + solution, approve / reject
                                          ┌───────────────────────────────────┴──────────┐
                                          ▼                                              ▼
                                  state: approved                              state: rejected (notes → author)
                                          │
                 content reviewer builds a Selection (which approved items, grouped into sets)
                                          ▼
                     package builder ─► draft package version ─► validator ─► submit
                                          ▼
                     existing gate: platform reviewer approve/reject ─► admin publishes
```

## 2. Owner decisions (2026-11-15)

| Decision | Choice |
|---|---|
| Who selects the questions for the package and supplies missing keys/solutions | A **content reviewer in the author's own organization** (new role). The platform reviewer stays an independent approve/reject gate and never edits content. |
| Can the content reviewer also be the author | **Yes.** The content reviewer role includes all author permissions, and a person may approve items they wrote or submitted (no four-eyes rule); submitter and approver are recorded. |
| License and copyright enforcement in the bank | **Deferred.** Source and license fields are recorded on every item but not enforced at import or selection. Enforcement (refusing official/commercial test material without recorded permission, blocking selection of unlicensed items) is added later behind the same fields. The existing platform-review license attestation is unchanged. |

## 3. Roles and permissions

| Role | Scope | Can | Cannot |
|---|---|---|---|
| `author` (existing) | one organization | create import jobs; edit, confirm, discard and submit items for review; read the org bank and selections; view validator report and preview | set or change the approved answer key; approve items; change a selection; approve/publish packages |
| `content_reviewer` (**new**) | one organization | everything an author can read; edit item text in review; set answer key and solution; approve or reject items; create and edit selections; build a package version from a selection and submit it to platform review | approve or publish packages (platform gate); see other organizations; see student data |
| `platform_reviewer` (existing) | platform | unchanged: approve/reject submitted package versions | edit items, keys or selections |
| `admin` (existing) | platform | unchanged: publish/retire | — |

New permissions: `bank:author`, `bank:review`. `author` gets `packages:author` + `bank:author`;
`content_reviewer` gets `packages:author` + `bank:author` + `bank:review`, so **a content reviewer is also an
author** (owner decision 2026-11-15): one person may import, edit, submit, key, approve and select their own
items. There is no four-eyes rule inside the organization; instead every version records who submitted it and who
approved it (`submittedBy`, `review.reviewer`), and both are shown to the platform reviewer with the package.
Other organizations' sources, jobs, items and selections return 404.

## 4. Data model (Firestore, all under `orgs/{orgId}/`)

### 4.1 `sources/{sourceId}` — one supplied input
`kind` (`image` | `pdf` | `text` | `link`), `storagePath` (files, org-scoped bucket prefix) or `url` + `fetchedAt` +
`contentHash` (links) or inline `text`; `title`; `uploadedBy`; `createdAt`; `pageCount`;
`license` / `attribution` (free text, **recorded, not enforced** — §2). Never visible to students.

### 4.2 `imports/{jobId}` — one extraction job
`sourceIds[]`, `courseHint` (optional courseId), `status` (`QUEUED` → `RUNNING` → `SUCCEEDED` | `FAILED`),
`runId`, `itemCount`, `errors[]` (per page, plain language), `usage` (tokens), `createdBy`, timestamps.
Created with Idempotency-Key; same key + same body replays the job.

### 4.3 `bankItems/{itemId}` + `bankItems/{itemId}/versions/{n}` — the question bank
Item header: `itemId`, `courseId` (target course, optional until selection), `state`, `currentVersion`,
`approvedVersion` (latest approved version or null), `revision` (write counter for optimistic concurrency),
`tags[]`, `flags[]` (copy of the current version's flags, for filtering), `history[]` (every command: action,
version, actor, time, from/to state, notes), `createdBy`, timestamps.

Item version (records `submittedBy`; never changes once decided — approved or rejected — or discarded/retired;
while `in_review` only the content reviewer may change it, e.g. text fixes or the key):

| Field | Notes |
|---|---|
| `section`, `skillIds[]`, `difficulty` | skill IDs must exist in the target course's skill list at selection time |
| `passageId` | optional reference to `bankPassages/{passageId}` (shared stimulus; also versioned) |
| `stem` | plain text; underlined portions marked `[[...]]`; math in linear notation |
| `type` | `mc` (choices A–D, one key) or `spr` (student-produced response, accepted values) |
| `choices` | `{A,B,C,D}` for `mc` |
| `answer` | `mc`: one letter; `spr`: accepted values separated by `|` (e.g. `29/3|9.66|9.67`) |
| `answerSource` | `source-key` (key found in the supplied material) · `compiled-key` (third-party key) · `reviewer` (entered by the content reviewer) · `agent-suggested` (never approvable as-is; see §5) |
| `solution` | optional worked explanation, required when `answerSource = reviewer` and the item is `spr` |
| `figure` | `none` · `described` (figure written as text in the stem) · `image` (after the image prerequisite, §8) |
| `provenance` | `{ sourceId, page, region, importJobId }` or `{ by: "author" }` or `{ by: "agent-drafted" }` |
| `flags[]` | extraction warnings: `ocr-uncertain`, `figure-missing`, `choices-incomplete`, `number-uncertain`, `key-disputed`, `duplicate-of:<itemId>` … |
| `review` | `{ reviewer, decidedAt, decision, notes }` on approved/rejected versions |

States: `extracted` → `draft` → `in_review` → `approved` | `rejected`; `rejected` → `draft` (author revises);
any → `discarded` (author, before approval) or `retired` (reviewer, after approval). Editing an approved item
creates a new version in `draft`; the approved version stays usable until the new one is approved.

### 4.4 `selections/{selectionId}` — what goes into a package
`courseId`, `name`, `sets[]`: `{ setId, title, taskTitle, durationMin, items: [{itemId, version}], skillIds[],
difficulty }` (≤10 items per set, ≤150 sets; items sharing a passage stay in one set; `skillIds` apply to items
without skills of their own), `starterSetIds[]`, `sequenceSetIds[]`, `sourceType` (original | licensed),
`sourceAuthor`, `sourceLicense` (become each built question's `source`; default: the course's publisher and
license), `revision`, `builtPackageVersion`, `builtBy`, `builtAt`. Only `approved`, unretired item versions may be
referenced (409 `ITEM_NOT_APPROVED`); references pin a version. Only `content_reviewer` writes and builds.

## 5. Answer keys and solutions

- An item version can be approved only with a final `answer` whose `answerSource` is `source-key`,
  `compiled-key` or `reviewer`. `agent-suggested` keys are shown to the reviewer as a suggestion and become
  `reviewer` only when the reviewer confirms them.
- For math items the agent's suggested key is checked with `math-verify` where the answer is closed-form; the
  result is shown, never applied automatically.
- A reviewer who disagrees with a `source-key`/`compiled-key` replaces it (`answerSource: reviewer`) and records the
  original in `review.notes`; this is how disputed keys (e.g. a compiler's reference answer) are resolved.
- Items without a key can live in the bank indefinitely (state `draft`/`in_review`); they just cannot be approved
  or selected.

## 6. Package builder (selection → package version)

Deterministic, no model calls:

- Each set → one package `Question` with `items` (choice set) for `mc` items. **`spr` items are not buildable
  yet** (409 `SELECTION_INVALID` when selected): the package's `answerCheck` takes a SymPy expression with
  variables, which does not fit plain numeric answers; numeric free response needs its own platform ability.
- Passages → the set question's prompt ("Read the passage, then answer each question." + title + text).
- One rubric per set (criterion per item); evaluation cases: every set all correct, then one-wrong cases while
  the 200-case package limit allows, plus one unreadable case. Starter tasks and practice sequence from the
  selection. Manifest, tutor prompt and skills come from the latest package version of the course in the
  organization; materials are dropped and `rubric-assessment`/`source-analysis` are removed from the abilities
  (a selection cannot supply their data), `choice-scoring` is added. Question ids are `q_{courseId}_{setId}`;
  question and rubric versions are a hash of the set's item versions, title, skills and difficulty.
- Every built package question records `source.bankItems[] = [{itemId, version}]`, so the platform reviewer and
  later audits can trace each question back to its bank item, source page and reviewer.
- The result goes through the existing upload path: validator report, preview, submit, platform review.

## 7. Authoring agent (extraction and editing)

- Runs as a platform ability on the shared runtime: a worker Run per import job or chat turn, through the LLM
  gateway with per-organization token budgets; no external calls inside transactions.
- Inputs it may read: the job's sources only. Supplied text, page content and fetched pages are **content, never
  instructions** to the agent.
- Its only outputs are typed proposals validated against the BankItem schema (create extracted item, propose edit,
  propose key with `answerSource: agent-suggested`, flag); invalid output is rejected, never partially written.
- Link fetching is done by the platform, not the model: http(s) only, no private/loopback/link-local addresses
  (checked after DNS resolution), redirects re-checked, size and content-type limits, timeout; the fetched copy is
  stored as the source so extraction is reproducible.
- It cannot change states beyond `extracted`, approve, select, build, submit, or read student data or other
  organizations.

## 8. Prerequisites and known gaps

- **Figures:** package questions are text only today. Until image attachments and formula rendering exist,
  figures are written out as text (`figure: described`), as in the local SAT bank. Image figures are a separate
  platform step.
- **Student-produced responses:** need the free-response + `math-verify` path described in §6; non-numeric
  answers stay unbuildable until a platform ability covers them.
- **Seeding for local testing (45.6, implemented):** `make seed-bank` (`scripts/seed_bank.py`) loads the
  git-ignored local bank in `server/content/private/bank` into `org_hsos_content`, emulator + `demo-*` project
  only. Every record goes through `BankService.create` (the call the Step 39 import uses), arriving as
  `extracted` (or `draft` for page-image-verified records with `--verified-as-draft`), with provenance
  (`imported`, source file, page, local id as `region`), its flags plus `seed-status:*`, and key origin
  (`official-key` → `source-key`, compiled → `compiled-key`, worked out → `agent-suggested`). Shared passages
  become `bankPassages`. Items get `courseId: dsat` (`--course`, `''` for none) so the selection editor
  offers them for the Digital SAT package. Re-running replays; a locally changed record is reported and skipped. The ImportJob
  record (`kind: bank-jsonl`) is not created yet; it arrives with Step 39.

## 9. API (summarized in API.md §6.5.7)

All POSTs require Idempotency-Key; all routes are org-scoped by the caller's membership (other orgs → 404).

| Method & path | Role | Purpose |
|---|---|---|
| `POST /api/bank/sources` | author+ | register an upload (signed URL), pasted text or link |
| `POST /api/bank/imports` | author+ | start an extraction job over sources |
| `GET /api/bank/imports/:jobId` | author+ | job status, errors, item count |
| `GET /api/bank/items?state=&courseId=&flag=&approvedOnly=` | author+ | list items (paged); `approvedOnly=true` includes items with a prior approved version even while a new draft is open |
| `GET /api/bank/items/:itemId` | author+ | item with versions and provenance |
| `POST /api/bank/items` | author+ | create an item by hand (`provenance.by = author`) |
| `PATCH /api/bank/items/:itemId` | author+ | edit (`expectedRevision` → 409 `VERSION_CONFLICT` when stale; see API.md §6.5.7) |
| `POST /api/bank/items/:itemId/confirm` | author+ | `extracted` → `draft` |
| `POST /api/bank/items/:itemId/submit` | author+ | `draft` → `in_review` |
| `POST /api/bank/items/:itemId/discard` | author+ | → `discarded` (before approval) |
| `POST /api/bank/items/:itemId/key` | content_reviewer | set answer + solution (`answerSource: reviewer`) |
| `POST /api/bank/items/:itemId/approve` / `reject` | content_reviewer | decide the `in_review` version (reject needs notes; the submitter may approve their own item) |
| `POST /api/bank/items/:itemId/retire` | content_reviewer | stop future selection |
| `GET/POST/PATCH /api/bank/selections[/:id]` | read: author+; write: content_reviewer | manage selections |
| `POST /api/bank/selections/:id/build` | content_reviewer | build a draft package version (then existing submit) |

New error codes: `ITEM_NOT_APPROVED`, `ITEM_KEY_REQUIRED`, `SELECTION_INVALID`,
`IMPORT_SOURCE_REJECTED` (link/file guard failures). Existing: `IDEMPOTENCY_CONFLICT`, `INVALID_STATE_TRANSITION`,
`VERSION_CONFLICT`, `FORBIDDEN`.

## 10. Changes to existing rules (applied 2026-11-15)

- CLAUDE.md "Course packages and authoring": add the bank and the content reviewer; "Reviewers approve or reject
  only" becomes "Platform reviewers approve or reject only; content reviewers (same organization) select items and
  supply keys"; §6.1/§6.2 license enforcement noted as deferred for the bank (fields recorded, not enforced),
  publication still requires the platform reviewer's license attestation.
- STEP_BY_STEP_PLAN.md: new Step 45 (this bank and role), Steps 39/40 re-scoped onto the bank (done in this
  draft), Step 43 unchanged except a note.

## 11. Tests (each step, per CLAUDE.md §4)

Isolation (other org → 404 for sources, jobs, items, selections); role gating (author cannot key/approve/select;
platform reviewer cannot edit items; students 403); idempotency of every POST; state machine (invalid transitions
409; approved versions immutable; edit-after-approval creates a new version); a content reviewer can approve an item
they submitted, with submitter and approver both recorded; selection only of
approved versions; builder determinism (same selection → identical package JSON) and passes the validator;
extraction Run failure leaves no partial items; budget exhaustion; link guard (private IPs, redirects, size);
agent output schema rejection. Extraction quality is measured separately on an annotated evaluation set of pages
(the local SAT bank's page-image transcriptions can serve as the first reference set).
