# High School Student OS — Step-by-Step Implementation Plan

Based on: `HIGH_SCHOOL_STUDENT_OS.md`, `API.md`, `BACKEND.md`, `IMPLEMENTATION_PLAN.md`, `web/README.md`.

Current state: frontend modular version (`web/`) complete with mock data via `HSData` seam; no `server/` directory exists yet.

Each step is a self-contained, testable commit. After completing each step, run the listed tests, verify they pass, then commit.

---

## M0: Scaffold & Baseline (Steps 1–5)

### Step 1 — Repository scaffold & package.json

**What to do:**
- Create `server/` directory structure:
  ```
  server/
    server.js          # empty placeholder (just a comment)
    lib/               # empty dir
    packs/             # empty dir
    skills/            # empty dir
    agents/            # empty dir
    workflows/         # empty dir
    data/              # empty dir, will hold runtime data
    data/seed/         # seed data
    __tests__/         # test directory
  ```
- Create `server/package.json`:
  ```json
  {
    "name": "hs-study-agent",
    "version": "0.1.0",
    "private": true,
    "type": "module",
    "engines": { "node": ">=18" },
    "scripts": {
      "start": "node server.js",
      "test": "node --test __tests__/**/*.test.js"
    }
  }
  ```
  Zero external dependencies. Uses Node's built-in test runner.
- Create `server/.gitignore`:
  ```
  data/
  !data/seed/
  node_modules/
  ```

**Test:** `cd server && node -e "import('./package.json', { assert: { type: 'json' } }).then(m => { const p = m.default; console.assert(p.name === 'hs-study-agent'); console.log('PASS: package.json valid'); })"` — or simpler: verify `npm test` runs (exits 0 with no test files found, or with a trivial smoke test).

**Commit message:** `scaffold: create server directory structure and package.json`

---

### Step 2 — Seed Twin data (alex)

**What to do:**
- Create `server/data/seed/twin-alex.json` — the canonical Alex Twin record that aligns field-by-field with `web/js/data.js` mock data and `API.md` §1.1 schema:
  ```json
  {
    "email": "alex@hs.edu",
    "version": 1,
    "profile": {
      "name": "Alex",
      "grade": 11,
      "school": "Lincoln High School",
      "gpa": 3.94,
      "targetMajor": "CS",
      "targetSchools": ["CMU", "UCSD", "Purdue"]
    },
    "goals": {
      "sat": { "target": 1550, "testDates": ["2027-03-13"] },
      "apTargets": { "calc_bc": 5, "apush": 5, "csa": 5, "phys_c": 5, "ap_lang": 5 }
    },
    "subscriptions": {
      "dsat": true,
      "admissions": true,
      "apCourses": ["calc_bc", "apush", "csa"]
    },
    "sat": {
      "current": 1510,
      "trajectory": [
        { "date": "2026-09-05", "total": 1450 },
        { "date": "2026-10-03", "total": 1510 }
      ]
    },
    "apState": {
      "calc_bc": {
        "currentMode": "GPA_SYNC",
        "predicted": 4.5,
        "target": 4.8,
        "stable": false,
        "schoolProgress": 74,
        "cbCoverage": 58,
        "currentUnit": "Unit 4: Contextual Applications of Differentiation",
        "weakSkills": ["implicit-differentiation", "related-rates"]
      },
      "apush": {
        "currentMode": "GPA_SYNC",
        "predicted": 4.0,
        "target": 4.5,
        "stable": false,
        "schoolProgress": 68,
        "cbCoverage": 62,
        "currentUnit": "Period 6 (1865–1898): Gilded Age",
        "weakSkills": ["contextualization", "sourcing"]
      },
      "csa": {
        "currentMode": "GPA_SYNC",
        "predicted": 4.8,
        "target": 5,
        "stable": true,
        "schoolProgress": 80,
        "cbCoverage": 75,
        "currentUnit": "Unit 7: ArrayList Algorithms",
        "weakSkills": ["array-boundary"]
      }
    },
    "mastery": {
      "sat-math.composite-functions": 0.62
    },
    "artifacts": {
      "essayOutlines": [],
      "activityList": [],
      "schoolMatrixVersion": 3
    },
    "timeline": {
      "satDates": ["2027-03-13"],
      "apExamMonth": "2027-05",
      "schoolExams": [],
      "weeklyHours": 15
    }
  }
  ```
- Verify every field matches between seed data, `data.js` mock, and `API.md` schema. Document any intentional differences in a comment at the top of the seed file.

**Test:** `node -e "import { readFile } from 'fs/promises'; const t = JSON.parse(await readFile('data/seed/twin-alex.json','utf8')); console.assert(t.email === 'alex@hs.edu'); console.assert(t.apState.calc_bc.predicted === 4.5); console.assert(t.sat.current === 1510); console.log('PASS: seed twin valid');"` (run from `server/`)

**Commit message:** `data: add seed Twin record for Alex aligned with frontend mock`

---

### Step 3 — Five subject pack manifests

**What to do:**
- Create five manifest files under `server/packs/`, each matching `API.md` §1.2:
  - `server/packs/calc_bc.json`
  - `server/packs/phys_c.json`
  - `server/packs/csa.json`
  - `server/packs/apush.json`
  - `server/packs/ap_lang.json`
- Each manifest contains: `courseId`, `name`, `shortName`, `icon`, `family`, `canvas`, `skills` (array of `{id, modes}`), `ragNamespaces`, `mcpServers`.
- Skills use the skill IDs from the design doc (e.g., `skill.tutor.socratic_step`, `skill.frq.stem_derivation_grader`), not the display names from `data.js`.

Example `calc_bc.json`:
```json
{
  "courseId": "calc_bc",
  "name": "AP Calculus BC",
  "shortName": "Calc BC",
  "icon": "📐",
  "family": "stem",
  "canvas": "calc",
  "skills": [
    { "id": "skill.tutor.socratic_step", "modes": ["GPA_SYNC"] },
    { "id": "skill.frq.stem_derivation_grader", "modes": ["EXAM_CRUNCH"] },
    { "id": "skill.vision.ocr_latex", "modes": ["GPA_SYNC", "EXAM_CRUNCH"] }
  ],
  "ragNamespaces": ["ced_calc_bc"],
  "mcpServers": ["sympy", "desmos", "twin-bus"]
}
```

**Test:** Write `server/__tests__/packs-valid.test.js`:
```js
import { describe, it } from 'node:test';
import assert from 'node:assert/strict';
import { readdir, readFile } from 'fs/promises';

describe('subject pack manifests', () => {
  const REQUIRED = ['calc_bc', 'phys_c', 'csa', 'apush', 'ap_lang'];
  const REQUIRED_FIELDS = ['courseId', 'name', 'shortName', 'icon', 'family', 'canvas', 'skills', 'ragNamespaces', 'mcpServers'];

  for (const id of REQUIRED) {
    it(`${id}.json exists and has required fields`, async () => {
      const raw = await readFile(new URL(`../packs/${id}.json`, import.meta.url), 'utf8');
      const pack = JSON.parse(raw);
      assert.equal(pack.courseId, id);
      for (const f of REQUIRED_FIELDS) {
        assert.ok(f in pack, `missing field: ${f}`);
      }
      assert.ok(pack.skills.length > 0, 'must have at least one skill');
      for (const s of pack.skills) {
        assert.ok(s.id, 'skill must have id');
        assert.ok(Array.isArray(s.modes), 'skill must have modes array');
      }
    });
  }
});
```
Run: `cd server && npm test`

**Commit message:** `data: add five subject pack manifests (calc_bc, phys_c, csa, apush, ap_lang)`

---

### Step 4 — Three agent manifests

**What to do:**
- Create three agent manifest files under `server/agents/`:
  - `server/agents/ap-base.json` — AP_BASE agent
  - `server/agents/dsat.json` — DSAT agent
  - `server/agents/admissions.json` — ADMISSIONS agent
- Each follows `BACKEND.md` §8 structure:
  ```json
  {
    "agentId": "AP_BASE",
    "runtime": "session",
    "skills": ["skill.tutor.socratic_step", "skill.frq.stem_derivation_grader", ...],
    "workflows": ["wf.ap_session"],
    "mcpAllowlist": ["sympy", "desmos", "twin-bus"],
    "ragNamespaces": ["ced_*", "user_{email}_{courseId}"],
    "modelPolicy": { "default": "balanced", "grader": "strong" }
  }
  ```

**Test:** Write `server/__tests__/agents-valid.test.js` — validate each JSON has `agentId`, `runtime`, `skills`, `modelPolicy`.
Run: `cd server && npm test`

**Commit message:** `data: add agent manifests for AP_BASE, DSAT, ADMISSIONS`

---

### Step 5 — Freeze frontend data contract

**What to do:**
- In `web/js/data.js`, add a docblock at the top documenting the `HSData` interface contract:
  ```
  // HSData interface contract (frozen for backend integration):
  //   getPacks()    → object keyed by courseId
  //   getSessions() → array of session/task objects
  //   getEvents()   → array of event objects
  //   getModeLabel() → object mapping mode string to display label
  //   getStudent()  → student identity object
  // Future (M1): all methods become async, returning Promises.
  ```
- Freeze `index.html` (root level) — add a note: `<!-- FROZEN: demo-only version. Active development is in web/ -->`
- No code logic changes.

**Test:** Open `web/index.html` via `python3 -m http.server 8000 -d web` — confirm it renders correctly with existing mock data, same as before.

**Commit message:** `docs: freeze HSData interface contract and root index.html`

---

## M1: Backend Core + Frontend Real Data (Steps 6–14)

### Step 6 — TwinStore: get() with JSON file persistence

**What to do:**
- Create `server/lib/twin-store.js`:
  - `async init(dataDir)` — sets data directory, loads seed if no twin file exists.
  - `async get(email)` → returns full Twin object. Reads from in-memory cache, falls back to `data/twin-{email}.json`, falls back to seed.
  - Internal: `_load(email)` reads file, caches in `Map`.
- On first `get("alex@hs.edu")`, copy seed to `data/twin-alex@hs.edu.json` if the runtime file doesn't exist.
- Export as `{ init, get }`.

**Test:** Write `server/__tests__/twin-store-get.test.js`:
```js
// 1. init with a temp dir
// 2. get("alex@hs.edu") returns valid Twin
// 3. get("nobody@hs.edu") throws or returns null
// 4. Repeated get() returns same object (cache)
```
Run: `cd server && npm test`

**Commit message:** `feat(twin-store): implement get() with JSON file persistence and seed fallback`

---

### Step 7 — TwinStore: patchProfile() with field whitelist

**What to do:**
- Add `async patchProfile(email, patch)` to `twin-store.js`:
  - Only allows keys under `profile`, `goals`, `subscriptions`. Rejects any other top-level key with `400 FIELD_NOT_ALLOWED`.
  - Deep-merges allowed fields into Twin.
  - Increments `version`.
  - Persists: write to temp file, then `rename()` atomically.
- Add `async _persist(email)` — serialize → write to `{dataDir}/twin-{email}.json.tmp` → `rename` to `.json`.

**Test:** Add to `server/__tests__/twin-store-patch.test.js`:
```
// 1. patchProfile({profile: {gpa: 3.95}}) → succeeds, gpa updated, version incremented
// 2. patchProfile({mastery: {...}}) → throws FIELD_NOT_ALLOWED
// 3. patchProfile({apState: {...}}) → throws FIELD_NOT_ALLOWED
// 4. After patch, get() returns updated value
// 5. After patch, file on disk has updated value (restart test)
```
Run: `cd server && npm test`

**Commit message:** `feat(twin-store): implement patchProfile with field whitelist and atomic persist`

---

### Step 8 — TwinStore: commitSettlement() and version conflict

**What to do:**
- Add `async commitSettlement(email, delta)`:
  - Accepts: `{ masteryDelta: {skill: number}, apPredicted: {courseId: number}, taskId, status }`.
  - Merges `masteryDelta` into `twin.mastery` (additive).
  - Updates `twin.apState[courseId].predicted` for each entry in `apPredicted`.
  - Increments `version`.
  - Persists atomically.
  - Returns `{ version, masteryDelta, apPredicted }`.
- Add optimistic locking: if caller passes `expectedVersion` and it doesn't match, throw `409 VERSION_CONFLICT`.

**Test:** `server/__tests__/twin-store-settle.test.js`:
```
// 1. commitSettlement updates mastery and predicted — get() reflects changes
// 2. commitSettlement with wrong expectedVersion → 409
// 3. mastery delta is additive (0.62 + 0.12 = 0.74)
// 4. patchProfile cannot write mastery (still enforced after settlement code added)
```
Run: `cd server && npm test`

**Commit message:** `feat(twin-store): implement commitSettlement with optimistic locking`

---

### Step 9 — SubjectPackRegistry

**What to do:**
- Create `server/lib/registry.js`:
  - `async init(packsDir, agentsDir)` — scans `packs/*.json` and `agents/*.json`, builds indexes (`courseId → pack`, `agentId → agent`).
  - `getPack(courseId)` → pack manifest or throws `PACK_NOT_FOUND`.
  - `getAllPacks()` → array of all pack manifests.
  - `getAgent(agentId)` → agent manifest or throws `AGENT_NOT_FOUND`.
  - `getAllAgents()` → array of all agent manifests.
  - `skillsFor(courseId, taskType, mode)` → filtered skill list for a given task type and mode. Logic: from pack's `skills` array, include skills whose `modes` includes the given mode.

**Test:** `server/__tests__/registry.test.js`:
```
// 1. init loads 5 packs and 3 agents
// 2. getPack("calc_bc") returns correct manifest
// 3. getPack("nonexistent") throws PACK_NOT_FOUND
// 4. skillsFor("calc_bc", "FRQ_PRACTICE", "EXAM_CRUNCH") includes stem_derivation_grader, excludes socratic_step
// 5. skillsFor("calc_bc", "SOCRATIC_STUDY", "GPA_SYNC") includes socratic_step, excludes stem_derivation_grader
// 6. getAllPacks() returns 5 items
// 7. getAgent("AP_BASE") returns valid manifest
```
Run: `cd server && npm test`

**Commit message:** `feat(registry): implement SubjectPackRegistry with pack and agent loading`

---

### Step 10 — Planner v1 (rule engine)

**What to do:**
- Create `server/lib/planner.js`:
  - `generate(twin, packs, options?)` → `{ date, tasks: Task[] }`.
  - Rule engine:
    1. **Gap calculation:**
       - SAT: `(twin.goals.sat.target - twin.sat.current)` → urgency based on days to next test date.
       - AP: For each subscribed course, `(target - predicted)` weighted by days to May exam (`twin.timeline.apExamMonth`).
       - Admissions: basic — check if artifacts are empty → generate interview/matrix tasks.
    2. **Weighting:** `weight = urgency × leverage`. Urgency = inverse of days remaining. Leverage = hardcoded per-agent (AP courses with big gaps > SAT near-target > stable courses).
    3. **Calendar pressure:** If `options.calendarPressure` is true (or detected from events), reduce SAT task count by 30%.
    4. **Bin packing:** Sort by weight descending, assign tasks until `weeklyHours` is filled. Each task has concrete `title`, `durationMin`, `desc`.
  - Task format matches `API.md` §1.3: `{ taskId, agent, courseId, taskType, mode, title, durationMin, desc, status: "PLANNED" }`.
  - `taskId` format: `task_{date}_{courseId}_{type}_{seq}`.

**Test:** `server/__tests__/planner.test.js`:
```
// 1. Given seed twin, generates tasks for all subscribed courses
// 2. Calc BC (gap 0.3, not stable) gets tasks
// 3. CSA (stable, gap 0.2) gets fewer/lower-priority tasks
// 4. SAT tasks present (subscribed, gap 40 points)
// 5. Admissions tasks present (subscribed, empty artifacts)
// 6. With calendarPressure, SAT task count decreases
// 7. Total duration ≤ weeklyHours
// 8. Every task has required fields (taskId, agent, courseId, taskType, mode, title, durationMin, desc, status)
```
Run: `cd server && npm test`

**Commit message:** `feat(planner): implement v1 rule-based task generation with gap and urgency weighting`

---

### Step 11 — HTTP server with read-only API endpoints

**What to do:**
- Implement `server/server.js`:
  - Use Node built-in `http` module. Zero framework.
  - Router: pattern-match on `req.method + req.url`.
  - Extract `X-User-Email` header (local dev auth).
  - Initialize TwinStore and Registry on startup.
  - Run Planner lazily on first `GET /api/tasks` for today (or if no tasks file exists for today).
  - Endpoints:
    - `GET /api/twin` → TwinStore.get(email) → 200 JSON
    - `PATCH /api/twin` → TwinStore.patchProfile(email, body) → 200 JSON
    - `GET /api/packs` → Registry.getAllPacks() → 200 JSON
    - `GET /api/packs/:courseId` → Registry.getPack(courseId) → 200 or 404
    - `GET /api/tasks` → Planner-generated tasks for today → 200 JSON
    - `GET /api/agents` → Registry.getAllAgents() → 200 JSON
    - `GET /api/agent/context` → Twin profile summary → 200 JSON
  - CORS: Allow `*` for local dev.
  - Error handling: consistent `{ error: { code, message } }` format.
  - Static file serving: serve `../web/` directory at root path (so `http://localhost:8787/` opens the frontend).
- Create `server/lib/router.js` (optional helper) — simple path matching and body parsing.

**Test:** `server/__tests__/api-read.test.js` — start server programmatically, make HTTP requests:
```
// 1. GET /api/twin with X-User-Email: alex@hs.edu → 200, has email/profile/sat/apState
// 2. GET /api/twin without X-User-Email → 401
// 3. GET /api/packs → 200, array of 5 packs
// 4. GET /api/packs/calc_bc → 200, has courseId "calc_bc"
// 5. GET /api/packs/nonexistent → 404 with PACK_NOT_FOUND
// 6. GET /api/tasks → 200, has date and tasks array
// 7. GET /api/agents → 200, array of 3 agents
// 8. GET /api/agent/context → 200, has profile summary
// 9. PATCH /api/twin with {profile:{gpa:3.95}} → 200, gpa updated
// 10. PATCH /api/twin with {mastery:{...}} → 400 FIELD_NOT_ALLOWED
```
Run: `cd server && npm test`

Also manually test: `cd server && node server.js`, then `curl http://localhost:8787/api/twin -H 'X-User-Email: alex@hs.edu'`

**Commit message:** `feat(server): implement HTTP server with read-only API endpoints and static file serving`

---

### Step 12 — Frontend: async data provider with fallback

**What to do:**
- Rewrite `web/js/data.js`:
  - `HSData` methods become async:
    - `HSData.ready()` → `Promise` that resolves when all initial data is loaded.
    - Internally: `fetch('/api/twin')`, `fetch('/api/packs')`, `fetch('/api/tasks')`, `fetch('/api/twin/events')` (events endpoint not yet implemented — will 404, use empty array as fallback).
  - On fetch failure (any endpoint), fall back to embedded mock data and set `HSData.online = false`.
  - On success, set `HSData.online = true`.
  - Add `X-User-Email` header to all requests (hardcoded to `alex@hs.edu` for now).
  - Synchronous methods still work (return cached data after `ready()` resolves) for backward compatibility during transition.
  - Keep all existing mock data embedded as fallback constants.

**Test:**
1. Start server (`cd server && node server.js`), open `http://localhost:8787/` → page loads with real data from server, no "offline" indicator.
2. Stop server, open `web/index.html` via `python3 -m http.server 8000 -d web` → page loads with mock data, shows "offline demo" indicator.
3. With server running, change seed twin's `sat.current` to `1520`, restart server, refresh browser → SAT score shows 1520.

**Commit message:** `feat(frontend): convert HSData to async provider with server/mock fallback`

---

### Step 13 — Frontend: async app startup with skeleton screen

**What to do:**
- Update `web/js/app.js`:
  - `App` component starts with a loading state.
  - Calls `HSData.ready()` on mount (useEffect).
  - Shows a skeleton/loading screen while data loads.
  - After data is loaded, renders normally.
- Update `web/js/store.js`:
  - Add `online` state (from `HSData.online`).
  - Add `loading` state.
- Changes should be confined to `data.js`, `store.js`, `app.js` only. If other files need changes, stop and fix the seam.

**Test:**
1. Server running → loads quickly, no skeleton visible (or very brief).
2. Server not running → skeleton briefly, then mock data renders with offline badge.
3. All existing interactions (select course, open session, toggle subscription, etc.) still work in both modes.

**Commit message:** `feat(frontend): async startup with skeleton screen and connection status indicator`

---

### Step 14 — M1 integration verification

**What to do:**
- Run the M1 acceptance criteria from `IMPLEMENTATION_PLAN.md` §2.3:
  1. **Backend not started:** Frontend = offline demo mode, behavior identical to pre-M1.
  2. **Backend started:** Refresh → task list, predicted scores, subscription status all come from `/api`. Change seed Twin's predicted score, restart server, refresh → score changes.
- Fix any integration issues found.
- Run all server tests: `cd server && npm test` — all pass.

**Test:** The acceptance criteria above are the test. Document results.

**Commit message:** `test: verify M1 acceptance — frontend reads from backend, falls back to mock`

---

## M2: Session Lifecycle (Steps 15–22)

### Step 15 — EventBus: in-process pub/sub + JSONL persistence

**What to do:**
- Create `server/lib/events.js`:
  - `init(dataDir)` — sets events file path (`data/events.jsonl`).
  - `emit(event)` — assigns `id` (uuid or incrementing), `ts` (ISO 8601), appends to JSONL file, then calls registered subscribers.
  - `on(eventType, handler)` — register a subscriber for a specific event type. `'*'` subscribes to all.
  - `list(options?)` — read events from JSONL, return in reverse chronological order. `options.limit` (default 50).
  - Event format matches `API.md` §1.4: `{ id, type, ts, from, to, payload, text }`.

**Test:** `server/__tests__/events.test.js`:
```
// 1. emit() writes to JSONL file, list() returns it
// 2. Subscriber is called when matching event emitted
// 3. '*' subscriber receives all events
// 4. list({limit: 2}) returns only 2 most recent
// 5. Events have auto-assigned id and ts
// 6. JSONL file is append-only (emit twice, file has 2 lines)
```
Run: `cd server && npm test`

**Commit message:** `feat(events): implement EventBus with in-process pub/sub and JSONL persistence`

---

### Step 16 — SessionRuntime: AP session start with subscription check

**What to do:**
- Create `server/lib/session.js`:
  - In-memory map of active sessions (`sessionId → session`).
  - `async startAP({ taskId, courseId, taskType }, email)`:
    1. Validate task exists (from Planner's task list).
    2. Check `twin.subscriptions.apCourses.includes(courseId)` → 403 `COURSE_NOT_SUBSCRIBED` if not.
    3. Load pack via Registry.
    4. Get skills via `Registry.skillsFor(courseId, taskType, mode)`.
    5. Create session: `{ sessionId, taskId, mode, activeSkills, ragNamespaces, mcpTools, studentMasteryContext, status: "ACTIVE" }`.
    6. Update task status to `ACTIVE`.
    7. Emit `session.started` event via EventBus.
    8. Return session.
  - `async startGeneric({ taskId }, email)`:
    - For DSAT and ADMISSIONS tasks — look up task, determine agent, build session with agent's built-in skills.
  - `getSession(sessionId)` → session object or null.
- Wire up task storage: Planner-generated tasks need to be queryable. Add a simple `TaskStore` (in-memory map + tasks file).

**Test:** `server/__tests__/session-start.test.js`:
```
// 1. startAP with subscribed course → 200, returns session with correct skills/rag/mcp
// 2. startAP with unsubscribed course (e.g., phys_c not in alex's subscriptions) → 403 COURSE_NOT_SUBSCRIBED
// 3. startAP with nonexistent taskId → 404
// 4. After start, task status changes to ACTIVE
// 5. session.started event was emitted
// 6. startGeneric for DSAT task → returns session with DSAT skills
// 7. startGeneric for ADMISSIONS task → returns session with ADMISSIONS skills
```
Run: `cd server && npm test`

**Commit message:** `feat(session): implement AP and generic session start with subscription check`

---

### Step 17 — Session settle: mastery update + event emission

**What to do:**
- Add `async settle(sessionId, outcome)` to session runtime:
  1. Get session. If not found or already SETTLED → 409 `ALREADY_SETTLED`.
  2. Build settlement delta from outcome:
     - `masteryDelta`: map of skill → delta (e.g., `{ "implicit-differentiation": 0.12 }`).
     - `apPredicted`: recalculated predicted score for the course (v1 rule: add `outcome.scoreDelta` to current predicted, cap at 5.0).
  3. Call `TwinStore.commitSettlement(email, delta)`.
  4. Set session/task status to `SETTLED`.
  5. Emit events:
     - `session.settled` always.
     - `ap.predicted` if AP course predicted changed.
     - `skill.weak` if outcome indicates weak skills (with `satTags` mapping).
  6. Trigger Planner incremental re-rank (call `Planner.generate()` again for today).
  7. Return: `{ taskId, status, masteryDelta, apPredicted, emittedEvents }`.

**Test:** `server/__tests__/session-settle.test.js`:
```
// 1. Settle after start → predicted updated, mastery updated, events emitted
// 2. Double settle → 409 ALREADY_SETTLED
// 3. Predicted score capped at 5.0
// 4. skill.weak event contains satTags mapping
// 5. ap.predicted event emitted with new score
// 6. After settle, Twin on disk reflects changes
```
Run: `cd server && npm test`

**Commit message:** `feat(session): implement settle with mastery update, event emission, and re-planning`

---

### Step 18 — Cross-domain event consumers

**What to do:**
- Register EventBus consumers in session or a new `server/lib/consumers.js`:
  - `skill.weak` → If payload has `satTags`, create a new DSAT task: `{ agent: "DSAT", taskType: "VARIANT_DRILL", title: "SAT Math: [satTag] variant", ... }`. Add to today's task list.
  - `vocab.context` → Create a DSAT vocab flashcard task.
  - `ap.predicted` → Mark admissions matrix as stale (optional flag on Twin, or just log for now).
  - `calendar.pressure` → Set a flag that Planner reads to reduce SAT task count.

**Test:** `server/__tests__/consumers.test.js`:
```
// 1. Emit skill.weak with satTags → new DSAT task appears in task list
// 2. Emit vocab.context → new vocab flashcard task appears
// 3. skill.weak without satTags → no DSAT task created
// 4. New tasks have correct format and status PLANNED
```
Run: `cd server && npm test`

**Commit message:** `feat(consumers): implement cross-domain event consumers (skill.weak → SAT tasks, vocab.context → flashcards)`

---

### Step 19 — API endpoints for session lifecycle and events

**What to do:**
- Add to `server/server.js`:
  - `POST /api/ap/session/start` → calls SessionRuntime.startAP().
  - `POST /api/session/start` → calls SessionRuntime.startGeneric() (DSAT/Admissions).
  - `POST /api/session/:sessionId/settle` → calls SessionRuntime.settle().
  - `POST /api/twin/events` → EventBus.emit() (for frontend-originated events like student.reply, vision.ocr).
  - `GET /api/twin/events?limit=50` → EventBus.list().

**Test:** `server/__tests__/api-session.test.js` — HTTP-level tests:
```
// 1. POST /api/ap/session/start with valid task → 200, returns session
// 2. POST /api/ap/session/start with unsubscribed course → 403
// 3. POST /api/session/:id/settle → 200, returns updated scores
// 4. POST /api/session/:id/settle again → 409
// 5. GET /api/twin/events → returns events array
// 6. POST /api/twin/events → event stored and retrievable
```
Run: `cd server && npm test`

**Commit message:** `feat(api): add session start, settle, and event endpoints`

---

### Step 20 — Frontend: wire session start and settle

**What to do:**
- Update `web/js/store.js`:
  - `openSession(s)` → if online, `POST /api/ap/session/start` (AP) or `POST /api/session/start` (others). On success, update local state with server response. On failure, show error (e.g., 403 → subscription modal).
  - Add `settleSession(sessionId, outcome)` → `POST /api/session/:id/settle`. On success, update predicted scores and events from response.
  - `pushEvent` → if online, also `POST /api/twin/events`. Local-first rendering (optimistic update), server is source of truth.

**Test:**
1. With server: click an AP task → session opens, server returns skills/rag. Check server logs for `session.started` event.
2. Click "settle" → predicted score updates in UI and on server.
3. Try to open a task for an unsubscribed course → 403 error shown as subscription prompt, not crash.

**Commit message:** `feat(frontend): wire session start and settle actions to backend API`

---

### Step 21 — Frontend: event feed from backend

**What to do:**
- Update event feed to read from `GET /api/twin/events` instead of local array.
- On initial load and after each action, refresh events from server.
- SSE deferred to M5 — for now, poll after actions.

**Test:**
1. Settle a session → event feed shows `session.settled` and `ap.predicted` events from server.
2. skill.weak cross-domain event visible in feed.
3. Offline mode: events still work locally.

**Commit message:** `feat(frontend): connect event feed to backend event API`

---

### Step 22 — M2 integration verification (three acceptance chains)

**What to do:**
- Run all three M2 acceptance chains from `IMPLEMENTATION_PLAN.md` §3.3:

**Chain 1: Unsubscribed course → 403**
1. Alex's subscriptions don't include `phys_c`.
2. Create a task for `phys_c` manually (or have one in the task list).
3. Try to open it → API returns 403 `COURSE_NOT_SUBSCRIBED`.
4. Frontend shows subscription guidance, not an error page.

**Chain 2: Calc FRQ settle → prediction update**
1. Open a Calc BC FRQ task → session starts.
2. Settle with `{ fixedStep: "chain-rule", scoreDelta: 0.3 }`.
3. Predicted score goes from 4.5 → 4.8.
4. Event feed shows `session.settled` and `ap.predicted`.
5. Twin file on disk has predicted 4.8.

**Chain 3: skill.weak → SAT variant task**
1. During chain 2, the settle emits `skill.weak` with satTags `["composite-functions"]`.
2. Task list now includes a new DSAT task: "Math: composite-functions variant".
3. Visible in today's tasks on the frontend.

**Test:** All server tests pass: `cd server && npm test`. Manual verification of all three chains.

**Commit message:** `test: verify M2 acceptance — three chains (403, settle+predict, cross-domain task)`

---

## M3: Intelligence Layer (Steps 23–30)

### Step 23 — LLMGateway interface + mock implementation

**What to do:**
- Create `server/lib/llm.js`:
  - `async chat({ tier, system, messages, schema })` → `{ content, usage: { promptTokens, completionTokens } }`.
  - `tier` is one of: `decision`, `fast`, `balanced`, `strong`.
  - If `schema` is provided, validate output against it. If validation fails, retry once. If still fails, return `{ content: rawText, degraded: true }`.
  - **Mock implementation** (default when no API key): returns canned responses based on the system prompt's skill ID. This lets all downstream code work without an API key.
  - **Real implementation**: reads `LLM_API_KEY` and `LLM_PROVIDER` (claude/openai) from env. Calls the API. Uses `models.yaml` for tier→model mapping.
- Create `server/models.yaml`:
  ```yaml
  tiers:
    decision:
      provider: jev
      model: jev-system-one
      fallback: { provider: claude, model: claude-haiku-5-5 }
    fast:
      provider: claude
      model: claude-haiku-5-5
    balanced:
      provider: claude
      model: claude-sonnet-5-5
    strong:
      provider: claude
      model: claude-opus-5-5
  limits:
    maxTokensPerSession: 8000
    maxTokensPerDay: 100000
  ```

**Test:** `server/__tests__/llm.test.js`:
```
// 1. Mock mode: chat() returns valid response
// 2. Schema validation: valid output passes, invalid triggers retry
// 3. After 2 failures, returns degraded:true
// 4. Usage tracking: tokens counted
```
Run: `cd server && npm test`

**Commit message:** `feat(llm): implement LLMGateway with mock and real implementations`

---

### Step 24 — ModelRouter

**What to do:**
- Create `server/lib/model-router.js`:
  - `route({ skillId, agentId, taskType, inputLength, previouslyDegraded })` → `tier` string.
  - Decision order (per `BACKEND.md` §9):
    1. Check skill/agent manifest for default tier.
    2. Apply upgrade rules (long input → bump to `balanced`, previously degraded → bump one tier).
    3. Jev decision placeholder (returns null for now, to be wired in M4).
    4. Cost guardrail: if session token count exceeds limit → downgrade one tier.
  - Reads `models.yaml` for tier→model mapping.

**Test:** `server/__tests__/model-router.test.js`:
```
// 1. Skill with "default": "balanced" → routes to balanced
// 2. Grader skill → routes to strong
// 3. Long input (>2000 tokens) with fast default → upgrades to balanced
// 4. Over session token limit → downgrades one tier
// 5. previouslyDegraded → upgrades one tier
```
Run: `cd server && npm test`

**Commit message:** `feat(model-router): implement tier routing with manifest defaults, upgrade rules, and cost guardrails`

---

### Step 25 — SkillExecutor: registration and execution framework

**What to do:**
- Create `server/lib/skills.js`:
  - `init(skillsDir)` — scans `skills/*.json`, builds `skillId → definition` map.
  - `async execute(skillId, { twin, session, input, pack })` → `{ output, tier, tokens, degraded }`.
  - Execution flow:
    1. Load skill definition (prompt template, input/output schema, tool whitelist, default tier).
    2. Route through ModelRouter to get tier.
    3. Render prompt template with context (twin state, pack info, student input).
    4. Call LLMGateway.chat().
    5. Validate output against skill's output schema.
    6. Return structured result.
- Create first skill definitions as JSON in `server/skills/`:
  - `skills/socratic-step.json` — shared across all subjects, parameterized by pack.
  - `skills/stem-frq-grader.json` — STEM FRQ grading.

**Test:** `server/__tests__/skills.test.js`:
```
// 1. init() loads skill definitions
// 2. execute("skill.tutor.socratic_step", ...) returns structured response
// 3. execute with mock LLM returns valid output matching schema
// 4. Unknown skill → throws SKILL_NOT_FOUND
// 5. Output schema mismatch → retry → degraded
```
Run: `cd server && npm test`

**Commit message:** `feat(skills): implement SkillExecutor with registration, template rendering, and schema validation`

---

### Step 26 — Core skill definitions (all families)

**What to do:**
- Create remaining skill definition files in `server/skills/`:
  - `socratic-step.json` — Universal Socratic tutor (parameterized by pack)
  - `stem-frq-grader.json` — STEM derivation grader (Calc BC, Physics C)
  - `ocr-latex.json` — OCR to LaTeX (STEM)
  - `dbq-rubric-grader.json` — DBQ 7-point rubric (APUSH, AP Euro)
  - `rhetoric-essay-grader.json` — Rhetoric essay grader (AP Lang)
  - `java-code-grader.json` — Java FRQ penalty checker (CSA)
  - `vocab-extractor.json` — Contextual vocab extractor (AP English/History → SAT)
  - `sat-variant-gen.json` — SAT error-driven variant question generator
  - `sat-vocab-flashcard.json` — Context vocabulary flashcard generator
  - `interview-followup.json` — Admissions interview follow-up
  - `activity-rewrite.json` — 150-character activity description rewriter
- Each file has: `id`, `name`, `family`, `promptTemplate` (with `{{placeholders}}`), `inputSchema`, `outputSchema`, `defaultTier`, `toolWhitelist`.

**Test:** `server/__tests__/skills-definitions.test.js`:
```
// 1. All skill JSON files parse correctly
// 2. Each has required fields: id, name, promptTemplate, inputSchema, outputSchema, defaultTier
// 3. Prompt templates have valid placeholders
// 4. Pack manifest skill references resolve to actual skill definitions
```
Run: `cd server && npm test`

**Commit message:** `data: add skill definitions for all families (STEM, humanities, SAT, admissions)`

---

### Step 27 — Wire skills into session flow

**What to do:**
- Update `session.js`:
  - When a session is active and receives a `student.reply` event (via `POST /api/twin/events`), invoke the appropriate skill:
    - Determine which skill to run based on session's `activeSkills` and the input type.
    - Call `SkillExecutor.execute()`.
    - Return skill output as part of the event response.
  - Add `POST /api/session/:id/interact` endpoint — accepts student input, runs skill, returns AI response.
- Add cost tracking per session: accumulate tokens, enforce `maxTokensPerSession` from `models.yaml`.

**Test:** `server/__tests__/session-interact.test.js`:
```
// 1. Start session → interact with student input → get Socratic response
// 2. FRQ session → interact with student FRQ answer → get grading response
// 3. Token count accumulates across interactions
// 4. Over token limit → response is degraded tier + warning
```
Run: `cd server && npm test`

**Commit message:** `feat(session): wire skill execution into session interact flow with cost tracking`

---

### Step 28 — RAG v1: local file retrieval

**What to do:**
- Create `server/lib/rag.js`:
  - `init(ragConfigPath)` — reads `server/rag.json` registry.
  - `async retrieve(namespaces, query, limit?)` → `{ chunks: [{text, source, score}] }`.
  - V1 implementation: simple keyword/substring match against local text files.
  - Namespace structure: `server/rag-data/{namespace}/` contains `.txt` or `.md` files. Each file is split into chunks by paragraph.
  - Interface is designed to swap for vector DB later without changing callers.
- Create `server/rag.json`:
  ```json
  {
    "implementation": "local-file",
    "basePath": "rag-data",
    "namespaces": {
      "ced_calc_bc": { "description": "AP Calculus BC CED structure and scoring" },
      "ced_apush": { "description": "AP US History 9-period framework and scoring" }
    }
  }
  ```
- Create minimal rag-data files for Calc BC and APUSH (exam structure, unit outlines, scoring guidelines — **not** copyrighted material, just structural outlines).

**Test:** `server/__tests__/rag.test.js`:
```
// 1. retrieve(["ced_calc_bc"], "chain rule") → returns relevant chunks
// 2. retrieve(["nonexistent"], "anything") → returns empty
// 3. Chunks have text, source, score
// 4. limit parameter respected
```
Run: `cd server && npm test`

**Commit message:** `feat(rag): implement local file RAG v1 with namespace-based retrieval`

---

### Step 29 — MCP v1: tool stubs

**What to do:**
- Create `server/lib/mcp.js`:
  - `init(mcpConfigPath)` — reads `server/mcp.json` registry.
  - `async invoke(toolName, input)` → `{ result, source: "stub"|"live" }`.
  - V1: all tools return structured stubs:
    - `sympy` — returns mock symbolic computation result.
    - `desmos` — returns mock graph data.
    - `twin-bus` — wraps EventBus (this one is real, not a stub).
    - `java-sandbox` — returns mock compilation result.
  - Interface designed for live tool replacement later.
- Create `server/mcp.json`:
  ```json
  {
    "servers": {
      "sympy": { "type": "stub", "description": "Symbolic math computation" },
      "desmos": { "type": "stub", "description": "Graphing calculator" },
      "twin-bus": { "type": "internal", "description": "Twin event bus bridge" },
      "java-sandbox": { "type": "stub", "description": "Java 17 JUnit sandbox" }
    }
  }
  ```

**Test:** `server/__tests__/mcp.test.js`:
```
// 1. invoke("sympy", {expr: "diff(x^2)"}) → returns structured result
// 2. invoke("twin-bus", {type: "skill.weak", ...}) → emits event via EventBus
// 3. invoke("unknown-tool") → throws TOOL_NOT_FOUND
// 4. All stubs return {source: "stub"}
```
Run: `cd server && npm test`

**Commit message:** `feat(mcp): implement MCP tool stubs with registry and twin-bus bridge`

---

### Step 30 — Frontend: render skill output + typewriter effect

**What to do:**
- Update `web/js/agents/ap.js` (and other agent panels as needed):
  - When session is active and user submits input, call `POST /api/session/:id/interact`.
  - Render skill output (Socratic response, FRQ grading, etc.) in the workspace.
  - Typewriter effect: display response incrementally (split by character/word with setTimeout).
  - Replace hardcoded mock content strings with server-returned content.
- Handle degraded/error states: show "AI is thinking..." → result or "AI temporarily limited, showing basic feedback" on degradation.

**Test:**
1. Open Calc BC session → type a question → get Socratic response rendered with typewriter effect.
2. Open FRQ session → submit answer → get grading feedback with rubric points.
3. Server down → graceful error message, not crash.
4. All existing UI interactions still work.

**Commit message:** `feat(frontend): render skill output from backend with typewriter effect and error handling`

---

### Step 31 — M3 integration verification

**What to do:**
- Verify M3 acceptance criteria from `IMPLEMENTATION_PLAN.md` §4.3:
  1. Same FRQ, grading result references real scoring rubric points and matches student's specific answer (not template text). Change the question → result changes.
  2. Each skill's tier and token consumption visible in server logs. Force token limit exceeded → tier downgrade actually occurs.
- Run all tests: `cd server && npm test`.

**Test:** Manual verification of above criteria plus all automated tests passing.

**Commit message:** `test: verify M3 acceptance — skill output is contextual, tier routing and cost guardrails work`

---

## M4: Jev Decision Layer (Steps 32–35)

### Step 32 — DecisionService interface + rule-based fallback

**What to do:**
- Create `server/lib/decision.js`:
  - `init({ jevApiKey, timeout })` — if no key, mark as disabled.
  - `async decide(question)` → `{ answer, confidence, source: "jev"|"rule" }`.
  - Question types (per `BACKEND.md` §10):
    - `Choice`: pick one from options. E.g., "Which model tier for this task?" → options: `[fast, balanced, strong]`.
    - `Score`: numeric 0–1. E.g., "How complex is this task?" → 0.7.
    - `Boolean`: yes/no. E.g., "Does this RAG chunk support the answer?" → true/false.
  - When Jev key is absent or call fails (timeout 800ms), fall back to rule-based decisions:
    - Complexity → use input length heuristic.
    - RAG relevance → keyword overlap score.
  - Circuit breaker: after 3 consecutive failures, disable Jev for 5 minutes.

**Test:** `server/__tests__/decision.test.js`:
```
// 1. Without API key: decide() returns rule-based answer with source:"rule"
// 2. Choice question returns valid option
// 3. Score question returns number 0–1
// 4. Boolean question returns true/false
// 5. Timeout simulation → falls back to rule
// 6. Circuit breaker: 3 failures → subsequent calls go straight to rule
```
Run: `cd server && npm test`

**Commit message:** `feat(decision): implement DecisionService with Jev interface and rule-based fallback`

---

### Step 33 — Wire Jev into ModelRouter

**What to do:**
- Update `server/lib/model-router.js`:
  - In the routing chain, after manifest default and before cost guardrail:
    - If manifest didn't specify a tier, call `DecisionService.decide({ type: "Score", question: "Task complexity", context: ... })`.
    - Map score to tier: <0.3 → fast, 0.3–0.7 → balanced, >0.7 → strong.
  - Log the decision source (jev vs rule) for auditability.

**Test:** `server/__tests__/model-router-jev.test.js`:
```
// 1. Without Jev key: routing still works (rule fallback)
// 2. With mock Jev returning 0.8: routes to strong
// 3. With mock Jev returning 0.2: routes to fast
// 4. Decision source logged in event
```
Run: `cd server && npm test`

**Commit message:** `feat(model-router): wire Jev decision into tier selection with fallback`

---

### Step 34 — Wire Jev into RAG relevance gating

**What to do:**
- Update `server/lib/rag.js`:
  - After retrieving chunks, pass each through `DecisionService.decide({ type: "Boolean", question: "Does this chunk support answering the student's question?", context: { chunk, query } })`.
  - Filter out chunks where answer is `false` (or confidence < threshold).
  - If all chunks filtered → return `{ chunks: [], insufficient: true }`.
  - When `insufficient: true`, the skill executor returns a "insufficient material" message instead of hallucinating.

**Test:** `server/__tests__/rag-gating.test.js`:
```
// 1. Relevant chunks pass through
// 2. Irrelevant chunks filtered out (with mock decision)
// 3. All chunks filtered → insufficient:true
// 4. Without Jev: keyword-overlap rule used as gating
```
Run: `cd server && npm test`

**Commit message:** `feat(rag): add Jev-powered relevance gating with keyword-overlap fallback`

---

### Step 35 — M4 verification: Jev bypass test

**What to do:**
- Verify M4 acceptance from `IMPLEMENTATION_PLAN.md` §5:
  1. **Jev disabled** (no key / simulated network down): all features work identically (rule fallback). Run full test suite with `JEV_API_KEY` unset.
  2. **Jev enabled** (if key available): routing and gating decisions visible in event stream. Can be audited.
- Run all tests: `cd server && npm test`

**Commit message:** `test: verify M4 acceptance — Jev bypass works, decisions auditable when enabled`

---

## M5: Production Hardening (Steps 36–42)

### Step 36 — JWT authentication

**What to do:**
- Create `server/lib/auth.js`:
  - `init({ jwtSecret, devMode })`.
  - `authenticate(req)` → `{ email }`.
  - Dev mode (`NODE_ENV !== 'production'`): accept `X-User-Email` header.
  - Production mode: verify JWT from `Authorization: Bearer <token>`, extract email. JWT secret shared with ai-college-advisor.
  - Middleware wrapper: `withAuth(handler)` → checks auth, injects email, returns 401 on failure.

**Test:** `server/__tests__/auth.test.js`:
```
// 1. Dev mode: X-User-Email header accepted
// 2. Dev mode: missing header → 401
// 3. Production mode: valid JWT → email extracted
// 4. Production mode: invalid JWT → 401
// 5. Production mode: expired JWT → 401
```
Run: `cd server && npm test`

**Commit message:** `feat(auth): implement JWT authentication with dev-mode X-User-Email fallback`

---

### Step 37 — TwinStore Firestore implementation

**What to do:**
- Create `server/lib/twin-store-firestore.js` — same interface as `twin-store.js`:
  - `get(email)` → reads `userProfiles/{email}` from Firestore.
  - `patchProfile(email, patch)` → same whitelist rules, writes to Firestore.
  - `commitSettlement(email, delta)` → same logic, Firestore transaction for atomicity.
- Create `server/lib/twin-store-factory.js` — returns JSON or Firestore implementation based on env var `STORAGE_BACKEND=json|firestore`.
- Update `server.js` to use the factory.

**Test:** All existing TwinStore tests must pass with both implementations:
```
// Run with STORAGE_BACKEND=json → existing tests pass
// Run with STORAGE_BACKEND=firestore (requires emulator or mock) → same tests pass
```
Run: `cd server && npm test`

**Commit message:** `feat(twin-store): add Firestore implementation with same interface, factory pattern for switching`

---

### Step 38 — Multi-user data isolation

**What to do:**
- Audit all data access paths:
  - TwinStore: already keyed by email ✓
  - EventBus: add email filtering — events are scoped to a user. JSONL file per user or filter on read.
  - TaskStore: scope tasks by email.
  - SessionRuntime: sessions scoped by email.
- Add integration test: two users' data never crosses.

**Test:** `server/__tests__/multi-user.test.js`:
```
// 1. User A's twin is not visible to User B
// 2. User A's events are not returned for User B
// 3. User A's session cannot be settled by User B
// 4. User A's tasks are not in User B's task list
```
Run: `cd server && npm test`

**Commit message:** `feat(isolation): enforce per-user data isolation across all stores`

---

### Step 39 — SSE for event stream

**What to do:**
- Add SSE endpoint: `GET /api/twin/events/stream`.
  - Sends `Content-Type: text/event-stream`.
  - When EventBus emits an event for this user, push it to the stream.
  - Heartbeat every 30 seconds.
  - Client reconnection via `Last-Event-ID`.
- Update `GET /api/twin/events` — still works for polling (backward compatible).
- Frontend: if SSE is available, use it; fall back to polling on error.

**Test:** `server/__tests__/sse.test.js`:
```
// 1. Connect to SSE → receive heartbeat
// 2. Emit event → appears in SSE stream
// 3. Reconnect with Last-Event-ID → missed events replayed
// 4. Polling endpoint still works
```
Run: `cd server && npm test`

**Commit message:** `feat(events): add SSE endpoint for real-time event streaming`

---

### Step 40 — CORS, deployment, and environment config

**What to do:**
- Tighten CORS:
  - Dev: allow `localhost:*` and `file://`.
  - Production: only allow configured domains.
- Create `server/.env.example`:
  ```
  NODE_ENV=development
  PORT=8787
  STORAGE_BACKEND=json
  LLM_API_KEY=
  LLM_PROVIDER=claude
  JEV_API_KEY=
  JWT_SECRET=
  CORS_ORIGINS=http://localhost:8787
  ```
- Create deployment script: `server/scripts/deploy.sh` (placeholder, documents steps).
- Data backup: `server/scripts/backup.sh` — exports Twin files daily.

**Test:** Manual verification:
1. Start with `.env` — server uses correct config.
2. CORS: cross-origin request from allowed domain → OK; from disallowed → blocked.

**Commit message:** `feat(deploy): add CORS config, env template, and deployment/backup scripts`

---

### Step 41 — Red-line compliance check

**What to do:**
- Create `server/__tests__/redlines.test.js` — automated checks for product red lines:
  ```
  // 1. No skill definition has a "generate_full_essay" or "write_essay" action
  // 2. No RAG namespace contains files with "Official College Board" in content
  // 3. School matrix output references only Twin fields (grep skill templates for Twin field references)
  // 4. No endpoint returns "admission probability" or "acceptance chance" text
  // 5. Activity rewrite skill requires student confirmation step
  ```
- Manual review checklist (document in the commit):
  - [ ] Essay skills only have outline/followup/feedback templates, no full-text generation
  - [ ] RAG data contains only structural outlines, not copyrighted exam content
  - [ ] School match output cites Twin scores, returns "insufficient data" when fields missing
  - [ ] No UI text promises admission outcomes

**Test:** Run `cd server && npm test` — redline tests pass.

**Commit message:** `test: add automated red-line compliance checks (no essay generation, no copyrighted content, no admission promises)`

---

### Step 42 — Final integration and M5 acceptance

**What to do:**
- Run full test suite: `cd server && npm test`
- Run all M0–M5 acceptance criteria end-to-end:
  1. External user can register (or be provisioned) and use the system.
  2. JWT auth works in production mode.
  3. Multi-user isolation holds.
  4. SSE events stream in real-time.
  5. Cost guardrails enforce limits.
  6. Red-line checks all pass.
  7. Jev bypass still works (disable key → full functionality).
- Frontend assessment: document which `web/` modules map 1:1 to React/Next.js components for future migration.

**Test:** All automated tests pass. Manual E2E walkthrough documented.

**Commit message:** `test: M5 final acceptance — auth, isolation, SSE, cost guardrails, red-lines all verified`

---

## Summary: 42 Steps across 5 Milestones

| Milestone | Steps | Key Deliverable |
|-----------|-------|-----------------|
| M0 Scaffold | 1–5 | Repo structure, seed data, manifests, frozen frontend contract |
| M1 Backend Core | 6–14 | TwinStore, Registry, Planner, HTTP API, frontend reads real data |
| M2 Session Lifecycle | 15–22 | EventBus, Session start/settle, cross-domain consumers, 3 acceptance chains |
| M3 Intelligence | 23–31 | LLM gateway, ModelRouter, SkillExecutor, RAG, MCP, real AI output |
| M4 Jev Decisions | 32–35 | DecisionService, model routing + RAG gating via Jev, full bypass |
| M5 Hardening | 36–42 | JWT, Firestore, multi-user, SSE, deployment, red-line compliance |

Each step is one commit. Each commit passes its tests before proceeding.
