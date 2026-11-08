"use strict";
const test = require("node:test");
const assert = require("node:assert/strict");
const A = require("../js/portal/admin-api.js");
function mock(responses = []) {
  const calls = [];
  const fetchImpl = async (url, init) => {
    calls.push({ url, init });
    const r = responses.shift() || { status: 200, body: {} };
    if (r instanceof Error) throw r;
    return { ok: r.status < 400, status: r.status, json: async () => r.body };
  };
  return { calls, api: A.createAdminApi({ baseUrl: "http://api", getIdToken: async () => "tok", fetchImpl }) };
}
test("admin: publication uses course endpoints and no student grants", async () => {
  const { api, calls } = mock();
  await api.queue(); await api.publish("dsat", "2.0.1"); await api.retire("dsat", "Correction");
  assert.deepEqual(calls.map(c => c.url), ["http://api/api/admin/packages", "http://api/api/admin/packages/dsat/versions/2.0.1/activate", "http://api/api/admin/courses/dsat/retire"]);
  assert.equal(calls[0].init.headers["Idempotency-Key"], undefined);
  for (const c of calls.slice(1)) assert.match(c.init.headers["Idempotency-Key"], /^idk_/);
  assert.deepEqual(JSON.parse(calls[1].init.body), {});
  assert.equal(api.grant, undefined);
});
test("admin: interrupted publication reuses the action key", async () => {
  const { api, calls } = mock([new Error("offline")]);
  await assert.rejects(api.publish("dsat", "2.0.1"));
  await api.publish("dsat", "2.0.1");
  assert.equal(calls[0].init.headers["Idempotency-Key"], calls[1].init.headers["Idempotency-Key"]);
});
test("admin: only approved versions offer publication", () => {
  assert.deepEqual(A.actionsFor("approved"), ["publish"]);
  assert.deepEqual(A.actionsFor("active"), ["retire"]);
  for (const s of ["draft", "submitted", "rejected", "superseded", "retired"]) assert.deepEqual(A.actionsFor(s), []);
});
