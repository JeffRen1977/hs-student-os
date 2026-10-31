// Tests for js/data-provider.js. Run: `node --test web/tests/` (no npm install needed).
"use strict";

const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");

const P = require("../js/data-provider.js");

const DEMO = JSON.parse(fs.readFileSync(path.join(__dirname, "..", "fixtures", "demo.json"), "utf8"));
const token = () => Promise.resolve("test-token");

function jsonResponse(status, body) {
  return { ok: status >= 200 && status < 300, status, json: () => Promise.resolve(body) };
}

function recordingFetch(handler) {
  const calls = [];
  const fn = async (url, init) => {
    calls.push({ url, init });
    return handler(url, init);
  };
  fn.calls = calls;
  return fn;
}

// ---- Demo flag ---------------------------------------------------------------------

test("demo mode only with ?demo=true", () => {
  assert.equal(P.isDemoMode("?demo=true"), true);
  assert.equal(P.isDemoMode("?x=1&demo=true"), true);
  for (const s of ["", "?demo=1", "?demo=TRUE", "?demo", "?demo=false", "?notdemo=true"]) {
    assert.equal(P.isDemoMode(s), false, s);
  }
});

test("createProvider picks api mode without the flag, even if fixtures are available", () => {
  const provider = P.createProvider({ search: "", loadDemoFixtures: () => DEMO, getIdToken: token });
  assert.equal(provider.mode, "api");
  const demo = P.createProvider({ search: "?demo=true", loadDemoFixtures: () => DEMO });
  assert.equal(demo.mode, "demo");
});

// ---- API failure never falls back to demo data -------------------------------------

test("network failure → NOT_CONNECTED, no demo fallback", async () => {
  const fetchImpl = recordingFetch(() => { throw new TypeError("Failed to fetch"); });
  const provider = P.createProvider({ search: "", fetchImpl, getIdToken: token, loadDemoFixtures: () => DEMO });
  const state = await P.bootstrap(provider).then(P.success, (e) => P.failure(e));
  assert.equal(state.status, "error");
  assert.equal(state.data, null);
  assert.equal(state.error.code, "NOT_CONNECTED");
  assert.equal(state.error.retryable, true);
  assert.equal(P.deriveScreen(state), "not_connected");
});

test("no ID token → NOT_SIGNED_IN and no request is sent", async () => {
  const fetchImpl = recordingFetch(() => jsonResponse(200, {}));
  const provider = P.createApiProvider({ fetchImpl, getIdToken: () => Promise.resolve(null) });
  await assert.rejects(provider.fetchTwin(), (e) => e.code === "NOT_SIGNED_IN");
  assert.equal(fetchImpl.calls.length, 0);
  assert.equal(P.deriveScreen(P.failure(new P.ApiError("NOT_SIGNED_IN", "x"))), "not_signed_in");
});

test("server error envelope becomes a typed ApiError", async () => {
  const fetchImpl = recordingFetch(() =>
    jsonResponse(409, { error: { code: "RUN_IN_PROGRESS", message: "busy", requestId: "req_9", retryable: false } })
  );
  const provider = P.createApiProvider({ fetchImpl, getIdToken: token });
  await assert.rejects(provider.fetchRun("run_1"), (e) => {
    assert.equal(e.code, "RUN_IN_PROGRESS");
    assert.equal(e.status, 409);
    assert.equal(e.requestId, "req_9");
    assert.equal(e.retryable, false);
    return true;
  });
  assert.equal(P.deriveScreen(P.failure(new P.ApiError("RUN_IN_PROGRESS", "x"))), "error");
});

test("non-JSON error responses are BAD_RESPONSE", async () => {
  const fetchImpl = recordingFetch(() => ({ ok: false, status: 502, json: () => Promise.reject(new Error("html")) }));
  const provider = P.createApiProvider({ fetchImpl, getIdToken: token });
  await assert.rejects(provider.fetchTwin(), (e) => e.code === "BAD_RESPONSE" && e.retryable === true);
});

test("requests use Bearer auth only and never X-User-Email", async () => {
  const fetchImpl = recordingFetch(() => jsonResponse(200, { events: [], nextAfter: 3, hasMore: false }));
  const provider = P.createApiProvider({ baseUrl: "http://api.test/", fetchImpl, getIdToken: token });
  await provider.fetchEvents(3, 50);
  const { url, init } = fetchImpl.calls[0];
  assert.equal(url, "http://api.test/api/events?after=3&limit=50");
  assert.equal(init.headers.Authorization, "Bearer test-token");
  assert.equal(init.headers["X-User-Email"], undefined);
  assert.equal(init.method, "GET");
});

test("commands send a valid Idempotency-Key and If-Match", async () => {
  const fetchImpl = recordingFetch(() => jsonResponse(202, { runId: "run_1", status: "QUEUED" }));
  const provider = P.createApiProvider({ fetchImpl, getIdToken: token });
  const key = P.newIdempotencyKey();
  await provider.request("/api/sessions", { method: "POST", body: { taskId: "t1" }, idempotencyKey: key, ifMatch: 4 });
  const { init } = fetchImpl.calls[0];
  assert.equal(init.headers["Idempotency-Key"], key);
  assert.equal(init.headers["If-Match"], '"4"');
  assert.equal(init.body, JSON.stringify({ taskId: "t1" }));
  await assert.rejects(provider.request("/api/x", { method: "POST", body: {}, idempotencyKey: "short" }));
});

// ---- Explicit demo mode -------------------------------------------------------------

test("demo bootstrap loads fixtures with Task/Session/Run kept separate", async () => {
  const provider = P.createDemoProvider(() => Promise.resolve(DEMO));
  const data = await P.bootstrap(provider);
  assert.equal(data.mode, "demo");
  assert.ok(data.tasks.length > 0 && data.sessions.length > 0 && data.runs.length > 0);
  for (const t of data.tasks) assert.equal(t.sessionId, undefined, "tasks do not embed sessions");
  const statuses = new Set(data.runs.map((r) => r.status));
  for (const s of ["QUEUED", "RUNNING", "WAITING_INPUT", "FAILED"]) assert.ok(statuses.has(s), s);
  assert.equal(data.eventLog.lastSequence, DEMO.twin.latestEventSequence);
  assert.equal(data.sessionRunIds.sess_demo_03, "run_demo_03", "terminal run recovered from events");
  assert.equal(data.sessionRunIds.sess_demo_01, "run_demo_01", "active run");
  assert.equal(P.deriveScreen(P.success(data)), "ready");
});

test("demo provider returns copies, so UI mutations cannot corrupt fixtures", async () => {
  const provider = P.createDemoProvider(() => DEMO);
  const a = await provider.fetchTwin();
  a.profile.displayName = "changed";
  const b = await provider.fetchTwin();
  assert.equal(b.profile.displayName, DEMO.twin.profile.displayName);
});

test("demo data has no prediction scores", () => {
  const text = JSON.stringify(DEMO);
  for (const forbidden of ['"predicted"', '"target"', '"scoreDelta"', '"gpa"', '"satCurrent"']) {
    assert.equal(text.includes(forbidden), false, forbidden);
  }
  for (const entry of Object.values(DEMO.twin.predictionSummary)) assert.equal(entry.status, "unavailable");
  assert.equal(P.predictionLabel(DEMO.twin.predictionSummary.calc_bc), "暂无预测（未校准）");
  assert.equal(P.predictionLabel(undefined), "暂无预测（未校准）");
});

test("active run wins over event history", () => {
  const sessions = [{ sessionId: "s1", activeRunId: "r2" }, { sessionId: "s2", activeRunId: null }, { sessionId: "s3", activeRunId: null }];
  const events = [
    { sessionId: "s1", runId: "r1", type: "run.failed" },
    { sessionId: "s2", runId: "r3", type: "run.queued" },
    { sessionId: "s2", runId: "r4", type: "run.failed" },
    { sessionId: "s3", runId: null, type: "session.started" },
  ];
  assert.deepEqual(P.latestRunBySession(sessions, events), { s1: "r2", s2: "r4" });
});

// ---- Request states -----------------------------------------------------------------

test("request state transitions keep last good data on reload/error", () => {
  const ok = P.success({ v: 1 });
  assert.equal(P.deriveScreen(P.idle()), "loading");
  assert.equal(P.deriveScreen(P.loading(P.idle())), "loading");
  const reloading = P.loading(ok);
  assert.deepEqual(reloading.data, { v: 1 });
  assert.equal(P.deriveScreen(reloading), "ready");
  const failed = P.failure(new TypeError("offline"), ok);
  assert.equal(failed.error.code, "NOT_CONNECTED");
  assert.deepEqual(failed.data, { v: 1 });
});

// ---- Idempotency keys ---------------------------------------------------------------

test("idempotency keys match the server pattern and are reused per action", () => {
  for (let i = 0; i < 20; i++) assert.match(P.newIdempotencyKey(), P.IDEMPOTENCY_KEY_PATTERN);
  const keys = P.createActionKeys();
  const first = keys.keyFor("submit:sess_1:q1");
  assert.equal(keys.keyFor("submit:sess_1:q1"), first, "retry reuses the key");
  assert.notEqual(keys.keyFor("submit:sess_1:q2"), first, "different action, different key");
  keys.release("submit:sess_1:q1");
  assert.notEqual(keys.keyFor("submit:sess_1:q1"), first, "new attempt after release");
});

// ---- Event de-duplication -----------------------------------------------------------

test("mergeEvents dedupes by eventId and sequence and keeps order", () => {
  const e = (seq, id) => ({ eventId: id || "evt_" + seq, sequence: seq, type: "run.queued" });
  let log = P.mergeEvents(null, [e(2), e(1)]);
  assert.deepEqual(log.events.map((x) => x.sequence), [1, 2]);
  log = P.mergeEvents(log, [e(2), e(3), e(3), e(1, "evt_other")]);
  assert.deepEqual(log.events.map((x) => x.eventId), ["evt_1", "evt_2", "evt_3"]);
  assert.equal(log.lastSequence, 3);
  log = P.mergeEvents(log, [{ eventId: "bad" }, null]);
  assert.equal(log.events.length, 3);
});

test("mergeEvents respects a starting cursor", () => {
  const log = P.mergeEvents({ events: [], lastSequence: 10 }, []);
  assert.equal(log.lastSequence, 10);
});

// ---- Offline drafts -----------------------------------------------------------------

test("drafts persist locally and are marked as not sent", () => {
  const storage = P.memoryStorage();
  const drafts = P.createDraftStore(storage, () => "2026-10-30T00:00:00Z");
  assert.equal(drafts.load("task_1"), null);
  const saved = drafts.save("task_1", "dy/dx = ...");
  assert.deepEqual(saved, { text: "dy/dx = ...", savedAt: "2026-10-30T00:00:00Z", status: "local_draft" });
  // Survives a "reload": a new store over the same storage.
  assert.deepEqual(P.createDraftStore(storage).load("task_1"), saved);
  assert.equal(drafts.load("task_2"), null, "drafts are per task");
  drafts.save("task_1", "");
  assert.equal(drafts.load("task_1"), null, "empty text clears the draft");
  drafts.save("task_1", "x");
  drafts.clear("task_1");
  assert.equal(drafts.load("task_1"), null);
});

test("corrupt draft storage does not crash", () => {
  const storage = P.memoryStorage();
  storage.setItem("hsos.draft.task_1", "{not json");
  assert.equal(P.createDraftStore(storage).load("task_1"), null);
});

// ---- Run display --------------------------------------------------------------------

test("describeRun covers every Run status and never calls SUCCEEDED 'completed task'", () => {
  for (const status of ["QUEUED", "RUNNING", "WAITING_INPUT", "SUCCEEDED", "FAILED", "CANCELLED"]) {
    const view = P.describeRun({ status });
    assert.ok(view.label, status);
  }
  assert.equal(P.describeRun({ status: "SUCCEEDED" }).label.includes("任务"), false);
  assert.equal(P.describeRun({ status: "FAILED", error: { code: "X", retryable: true } }).retryable, true);
  assert.equal(P.describeRun({ status: "FAILED", error: { code: "X", retryable: false } }).retryable, false);
  assert.equal(P.describeRun(null), null);
});
