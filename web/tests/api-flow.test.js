// Step 20: commands with idempotent retries, SSE parsing, event subscription, auth seam.
"use strict";

const test = require("node:test");
const assert = require("node:assert/strict");

const P = require("../js/data-provider.js");
const A = require("../js/auth.js");

function jsonResponse(status, body) {
  return { ok: status >= 200 && status < 300, status, json: () => Promise.resolve(body) };
}

function provider(handler, extra) {
  const calls = [];
  const fetchImpl = async (url, init) => { calls.push({ url, init }); return handler(url, init, calls.length); };
  const api = P.createApiProvider(Object.assign({ fetchImpl, getIdToken: () => Promise.resolve("tok") }, extra));
  return { api, calls };
}

test("a retried send reuses its Idempotency-Key; the next send gets a new one", async () => {
  const { api, calls } = provider((url, init, n) => {
    if (n === 1) throw new TypeError("Failed to fetch");
    return jsonResponse(202, { messageId: "m", runId: "r", status: "QUEUED" });
  });
  await assert.rejects(api.sendMessage("sess_1", "hi", "draft1"), (e) => e.code === "NOT_CONNECTED" && e.retryable);
  await api.sendMessage("sess_1", "hi", "draft1");
  await api.sendMessage("sess_1", "again", "draft2");
  const keys = calls.map((c) => c.init.headers["Idempotency-Key"]);
  assert.equal(keys[0], keys[1]);
  assert.notEqual(keys[1], keys[2]);
  assert.match(keys[0], P.IDEMPOTENCY_KEY_PATTERN);
  assert.equal(calls[0].url, "http://localhost:8787/api/sessions/sess_1/messages");
  assert.deepEqual(JSON.parse(calls[0].init.body), { text: "hi", fileIds: [] });
});

test("a definitive error releases the key (a later attempt is a new command)", async () => {
  const { api, calls } = provider((url, init, n) =>
    n === 1
      ? jsonResponse(409, { error: { code: "RUN_IN_PROGRESS", message: "busy", retryable: false } })
      : jsonResponse(200, { sessionId: "s", status: "COMPLETED" }));
  await assert.rejects(api.completeSession("s"), (e) => e.code === "RUN_IN_PROGRESS");
  await api.completeSession("s");
  assert.notEqual(calls[0].init.headers["Idempotency-Key"], calls[1].init.headers["Idempotency-Key"]);
});

test("submissions send answers only — never scores or statuses", async () => {
  const { api, calls } = provider(() => jsonResponse(202, { submissionId: "x", runId: "r", status: "QUEUED" }));
  await api.submitAnswer("s1", { questionId: "q1", questionVersion: "1", answer: { text: "work", fileIds: [] } }, "d1");
  const body = JSON.parse(calls[0].init.body);
  assert.deepEqual(Object.keys(body).sort(), ["answer", "questionId", "questionVersion"]);
  assert.equal(calls[0].url, "http://localhost:8787/api/sessions/s1/submissions");
});

test("every Run state has truthful copy; error codes map to safe text", () => {
  for (const status of ["QUEUED", "RUNNING", "WAITING_INPUT", "SUCCEEDED", "FAILED", "CANCELLED"]) {
    assert.ok(P.describeRun({ status }).label);
  }
  assert.match(P.errorText("BUDGET_EXCEEDED"), /budget/);
  assert.match(P.errorText("SOMETHING_NEW"), /SOMETHING_NEW/);
});

test("SSE parser handles split chunks, comments, ids and CRLF", () => {
  const feed = P.createSseParser();
  assert.deepEqual(feed("retry: 3000\n\nid: 4\nevent: run.qu"), [
    { id: null, event: "message", data: "", comment: null },
  ]);
  const frames = feed("eued\r\ndata: {\"sequence\":4}\r\n\r\n: heartbeat\n\n");
  assert.equal(frames.length, 2);
  assert.deepEqual(frames[0], { id: "4", event: "run.queued", data: "{\"sequence\":4}", comment: null });
  assert.equal(frames[1].comment, "heartbeat");
});

function streamBody(text) {
  const bytes = new TextEncoder().encode(text);
  let sent = false;
  return { getReader: () => ({ read: async () => (sent ? { done: true } : ((sent = true), { done: false, value: bytes })) }) };
}

const evt = (seq) => ({ eventId: "evt_" + seq, sequence: seq, type: "run.queued", studentId: "stu_alex" });
const frame = (seq) => "id: " + seq + "\nevent: run.queued\ndata: " + JSON.stringify(evt(seq)) + "\n\n";

test("subscription streams with Bearer + Last-Event-ID and resumes from its cursor", async () => {
  const seen = [];
  const requests = [];
  let sub;
  const fetchImpl = async (url, init) => {
    requests.push({ url, init });
    if (requests.length === 1) return { ok: true, status: 200, body: streamBody(frame(3) + frame(4)) };
    sub.stop();
    return { ok: true, status: 200, body: streamBody(frame(4) + frame(5)) };
  };
  const api = P.createApiProvider({ getIdToken: () => Promise.resolve("tok") });
  sub = P.createEventSubscription(api, { after: 2, fetchImpl, sleep: async () => {}, onEvents: (es) => seen.push(...es.map((e) => e.sequence)) });
  await sub.done;
  assert.deepEqual(seen, [3, 4]);
  assert.equal(requests[0].url, "http://localhost:8787/api/events/stream"); // no token in URL
  assert.equal(requests[0].init.headers.Authorization, "Bearer tok");
  assert.equal(requests[0].init.headers["Last-Event-ID"], "2");
  assert.equal(requests[1].init.headers["Last-Event-ID"], "4"); // reconnect resumes
});

test("subscription falls back to polling after repeated stream failures", async () => {
  const seen = [];
  let polls = 0;
  let sub;
  const api = P.createApiProvider({ getIdToken: () => Promise.resolve("tok") });
  api.fetchEvents = async (after) => {
    polls += 1;
    if (polls > 1) sub.stop();
    return { events: [evt(after + 1)], nextAfter: after + 1, hasMore: false };
  };
  const fetchImpl = async () => { throw new TypeError("no streaming"); };
  sub = P.createEventSubscription(api, { after: 0, fetchImpl, sleep: async () => {}, maxStreamFailures: 2, onEvents: (es) => seen.push(...es.map((e) => e.sequence)) });
  await sub.done;
  assert.equal(sub.state.mode, "polling");
  assert.deepEqual(seen, [1, 2]);
});

test("an expired cursor asks the app to reload its snapshot", async () => {
  let expired = false;
  const api = P.createApiProvider({ getIdToken: () => Promise.resolve("tok") });
  const sub = P.createEventSubscription(api, {
    after: 0, fetchImpl: async () => ({ ok: false, status: 410 }), sleep: async () => {},
    onEvents: () => {}, onExpired: () => { expired = true; },
  });
  await sub.done;
  assert.equal(expired, true);
});

test("auth: local emulator mode only when page and API are both on localhost", () => {
  assert.equal(A.chooseMode({ hostname: "localhost", apiBaseUrl: "http://localhost:8787" }), "local_emulator");
  assert.equal(A.chooseMode({ hostname: "127.0.0.1", apiBaseUrl: "http://127.0.0.1:8787" }), "local_emulator");
  assert.equal(A.chooseMode({ hostname: "app.example.org", apiBaseUrl: "http://localhost:8787" }), "none");
  assert.equal(A.chooseMode({ hostname: "localhost", apiBaseUrl: "https://api.example.org" }), "none");
  assert.equal(A.chooseMode({ hostname: "localhost", apiBaseUrl: "http://localhost:8787", firebaseConfig: {} }), "firebase");
});

test("auth: local sign-in is limited to synthetic students and mints emulator-format tokens", async () => {
  const store = new Map();
  const storage = { getItem: (k) => store.get(k) || null, setItem: (k, v) => store.set(k, v), removeItem: (k) => store.delete(k) };
  const auth = A.createAuth({ hostname: "localhost", apiBaseUrl: "http://localhost:8787", storage });
  assert.equal(await auth.getIdToken(), null);
  assert.throws(() => auth.signInLocal("real_student"));
  auth.signInLocal("stu_alex");
  const token = await auth.getIdToken();
  const [header, claims, signature] = token.split(".");
  const decode = (s) => JSON.parse(Buffer.from(s.replace(/-/g, "+").replace(/_/g, "/"), "base64").toString());
  assert.deepEqual(decode(header), { alg: "none", typ: "JWT" });
  assert.equal(signature, "");
  const c = decode(claims);
  assert.equal(c.sub, "stu_alex");
  assert.equal(c.aud, "demo-hs-student-os");
  assert.ok(c.exp > c.iat);
  await auth.signOut();
  assert.equal(await auth.getIdToken(), null);
  const deployed = A.createAuth({ hostname: "app.example.org", apiBaseUrl: "https://api.example.org", storage });
  assert.throws(() => deployed.signInLocal("stu_alex"));
});
