// Author portal client (Step 34.1): idempotent commands, typed errors, local parsing.
const test = require("node:test");
const assert = require("node:assert/strict");
const P = require("../js/portal/portal-api.js");
const A = require("../js/auth.js");

function fakeFetch(responses) {
  const calls = [];
  const fn = async (url, init) => {
    calls.push({ url, init });
    const r = responses.shift();
    if (r instanceof Error) throw r;
    return { ok: r.status < 400, status: r.status, json: async () => r.body };
  };
  fn.calls = calls;
  return fn;
}

test("portal: a retried upload reuses its Idempotency-Key; a new action gets a new one", async () => {
  const f = fakeFetch([new Error("offline"), { status: 201, body: { status: "draft" } }, { status: 201, body: {} }]);
  const api = P.createPortalApi({ baseUrl: "http://api", getIdToken: async () => "tok", fetchImpl: f });
  await assert.rejects(api.upload({ a: 1 }, "upload-1"), (e) => e.code === "NETWORK");
  await api.upload({ a: 1 }, "upload-1");
  await api.upload({ a: 2 }, "upload-2");
  const keys = f.calls.map((c) => c.init.headers["Idempotency-Key"]);
  assert.equal(keys[0], keys[1]);
  assert.notEqual(keys[1], keys[2]);
  assert.equal(f.calls[0].url, "http://api/api/authoring/packages");
  assert.equal(f.calls[0].init.headers.Authorization, "Bearer tok");
});

test("portal: server error envelopes become typed errors; GETs carry no Idempotency-Key", async () => {
  const f = fakeFetch([{ status: 404, body: { error: { code: "NOT_FOUND", message: "Package not found." } } }]);
  const api = P.createPortalApi({ baseUrl: "", getIdToken: async () => "t", fetchImpl: f });
  await assert.rejects(api.preview("apush", "1.0.0"), (e) => e.code === "NOT_FOUND" && e.status === 404);
  assert.equal(f.calls[0].init.headers["Idempotency-Key"], undefined);
  assert.equal(f.calls[0].url, "/api/authoring/packages/apush/versions/1.0.0/preview");
});

test("portal: signed out means no request at all", async () => {
  const f = fakeFetch([]);
  const api = P.createPortalApi({ baseUrl: "", getIdToken: async () => null, fetchImpl: f });
  await assert.rejects(api.listPackages(), (e) => e.code === "UNAUTHENTICATED");
  assert.equal(f.calls.length, 0);
});

test("portal: package text is parsed locally with a readable error", () => {
  assert.equal(P.parsePackageText("{").ok, false);
  assert.equal(P.parsePackageText("[]").ok, false);
  assert.deepEqual(P.parsePackageText('{"a":1}'), { ok: true, value: { a: 1 } });
});

test("auth: the portal offers only synthetic platform members for local sign-in", async () => {
  const store = new Map();
  const storage = { getItem: (k) => store.get(k) || null, setItem: (k, v) => store.set(k, v), removeItem: (k) => store.delete(k) };
  const auth = A.createAuth({
    hostname: "localhost", apiBaseUrl: "http://localhost:8787", storage,
    localUsers: A.SYNTHETIC_PLATFORM_MEMBERS, storageKey: "hsos.portalUid",
  });
  assert.deepEqual(auth.students.map((s) => s.uid), ["author_hsos", "author_sample", "reviewer_platform"]);
  assert.throws(() => auth.signInLocal("stu_alex"));
  auth.signInLocal("author_hsos");
  assert.equal(store.get("hsos.portalUid"), "author_hsos");
  assert.equal(store.get("hsos.localEmulatorUid"), undefined); // separate from the student app
});
