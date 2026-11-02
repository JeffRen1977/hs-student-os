// M3: choice sets, planning and student task controls on the data-provider seam.
"use strict";

const test = require("node:test");
const assert = require("node:assert/strict");

const P = require("../js/data-provider.js");

function jsonResponse(status, body) {
  return { ok: status >= 200 && status < 300, status, json: () => Promise.resolve(body) };
}

function provider(handler) {
  const calls = [];
  const fetchImpl = async (url, init) => { calls.push({ url, init }); return handler(url, init, calls.length); };
  return { api: P.createApiProvider({ fetchImpl, getIdToken: () => Promise.resolve("tok") }), calls };
}

test("choice answers are one line per item, and only when every item is answered", () => {
  const items = [{ itemId: "1" }, { itemId: "2" }, { itemId: "3" }];
  assert.equal(P.formatChoiceAnswer(items, { 1: "B", 2: "C", 3: "A" }), "1: B\n2: C\n3: A");
  assert.equal(P.formatChoiceAnswer(items, { 1: "B", 3: "A" }), null);
  assert.equal(P.formatChoiceAnswer([], {}), "");
});

test("replan is an idempotent command with an empty body; retries reuse the key", async () => {
  const { api, calls } = provider((url, init, n) => {
    if (n === 1) throw new TypeError("Failed to fetch");
    return jsonResponse(202, { runId: "run_1", status: "QUEUED" });
  });
  await assert.rejects(api.requestReplan("click1"), (e) => e.code === "NOT_CONNECTED");
  const accepted = await api.requestReplan("click1");
  assert.equal(accepted.status, "QUEUED");
  assert.equal(calls[0].url, "http://localhost:8787/api/plans/replan");
  assert.equal(calls[0].init.method, "POST");
  assert.deepEqual(JSON.parse(calls[0].init.body), {});
  assert.equal(calls[0].init.headers["Idempotency-Key"], calls[1].init.headers["Idempotency-Key"]);
});

test("rescheduling sends only the new date with If-Match; conflicts surface as typed errors", async () => {
  const { api, calls } = provider((url, init, n) =>
    n === 1
      ? jsonResponse(200, { taskId: "t1", version: 4, studentLocked: true })
      : jsonResponse(409, { error: { code: "VERSION_CONFLICT", message: "stale", retryable: false } }));
  await api.patchTask("t1", 3, { scheduledDate: "2026-11-07" });
  assert.equal(calls[0].init.method, "PATCH");
  assert.equal(calls[0].init.headers["If-Match"], '"3"');
  assert.deepEqual(JSON.parse(calls[0].init.body), { scheduledDate: "2026-11-07" });
  await assert.rejects(api.patchTask("t1", 3, { scheduledDate: "2026-11-08" }), (e) => e.code === "VERSION_CONFLICT");
  assert.match(P.errorText("VERSION_CONFLICT"), /Refresh/);
});

test("plans are read-only GETs, and there is no cross-course findings call", async () => {
  const { api, calls } = provider(() => jsonResponse(200, {}));
  await api.fetchLatestPlan();
  assert.equal(api.fetchPrerequisites, undefined);
  assert.equal(P.findingView, undefined);
  assert.deepEqual(calls.map((c) => [c.init.method, c.url.replace("http://localhost:8787", "")]), [
    ["GET", "/api/plans/latest"],
  ]);
  assert.equal(calls[0].init.body, undefined);
});

test("task controls and reminder opt-in are If-Match PATCHes of allowlisted fields", async () => {
  const { api, calls } = provider(() => jsonResponse(200, {}));
  await api.patchTask("t1", 2, { studentLocked: false });
  await api.patchTask("t1", 3, { status: "SKIPPED", skipReason: "no_time" });
  const notifications = { enabled: true, channels: ["email"], quietHours: { start: "21:00", end: "08:00" } };
  await api.patchTwin(5, { preferences: { notifications: notifications } });
  assert.deepEqual(calls.map((c) => [c.init.method, c.url.replace("http://localhost:8787", ""), c.init.headers["If-Match"]]), [
    ["PATCH", "/api/tasks/t1", '"2"'],
    ["PATCH", "/api/tasks/t1", '"3"'],
    ["PATCH", "/api/twin", '"5"'],
  ]);
  assert.deepEqual(JSON.parse(calls[2].init.body), { preferences: { notifications: notifications } });
  assert.equal(calls[2].init.headers["Idempotency-Key"], undefined);
});
