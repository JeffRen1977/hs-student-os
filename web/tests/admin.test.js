// Course-access admin client (Step 42): /api/admin endpoints only, idempotent changes,
// pasted student lists, plain-language errors, and no admin client on other pages.
"use strict";

const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const A = require("../js/portal/admin-api.js");

const read = (p) => fs.readFileSync(path.join(__dirname, "..", "..", p), "utf8");

function fakeFetch(responses) {
  const calls = [];
  const fn = async (url, init) => {
    calls.push({ url, init, body: init.body === undefined ? undefined : JSON.parse(init.body) });
    const r = responses.length ? responses.shift() : { status: 200, body: {} };
    if (r instanceof Error) throw r;
    return { ok: r.status < 400, status: r.status, json: async () => r.body };
  };
  fn.calls = calls;
  return fn;
}
const api = (f) => A.createAdminApi({ baseUrl: "http://api", getIdToken: async () => "tok", fetchImpl: f });

test("admin: each call goes to its /api/admin endpoint; commands carry an Idempotency-Key", async () => {
  const f = fakeFetch([]);
  const a = api(f);
  await a.getAccess("stu_beth");
  await a.grant("stu_beth", "dsat", "Pilot");
  await a.revoke("stu_beth", "dsat", "Left");
  await a.bulk({ studentIds: ["stu_a", "stu_b"], courseId: "dsat", change: "grant", reason: "Cohort" });
  assert.deepEqual(f.calls.map((c) => [c.init.method, c.url.replace("http://api", "")]), [
    ["GET", "/api/admin/students/stu_beth/access"],
    ["POST", "/api/admin/students/stu_beth/access/grant"],
    ["POST", "/api/admin/students/stu_beth/access/revoke"],
    ["POST", "/api/admin/access/bulk"],
  ]);
  assert.deepEqual(f.calls[1].body, { courseId: "dsat", reason: "Pilot" });
  assert.deepEqual(f.calls[3].body, { studentIds: ["stu_a", "stu_b"], courseId: "dsat", change: "grant", reason: "Cohort" });
  assert.equal(f.calls[0].init.headers["Idempotency-Key"], undefined);
  for (const c of f.calls.slice(1)) assert.match(c.init.headers["Idempotency-Key"], /^idk_/);
});

test("admin: a retried grant reuses its key; a different reason is a new action", async () => {
  const f = fakeFetch([new Error("offline"), { status: 200, body: { changed: true } }, { status: 200, body: {} }]);
  const a = api(f);
  await assert.rejects(a.grant("stu_beth", "dsat", "Pilot"), (e) => e.code === "NETWORK");
  await a.grant("stu_beth", "dsat", "Pilot");
  await a.grant("stu_beth", "dsat", "Pilot, corrected");
  const keys = f.calls.map((c) => c.init.headers["Idempotency-Key"]);
  assert.equal(keys[0], keys[1]);
  assert.notEqual(keys[1], keys[2]);
});

test("admin: pasted student lists are split, de-duplicated and checked", () => {
  assert.deepEqual(A.parseStudentIds("stu_a\nstu_b, stu_a ; stu_c\n\n"), { ids: ["stu_a", "stu_b", "stu_c"], invalid: [], tooMany: false, ok: true });
  const bad = A.parseStudentIds("stu_a bad/id");
  assert.deepEqual([bad.ids, bad.invalid, bad.ok], [["stu_a"], ["bad/id"], false]);
  assert.equal(A.parseStudentIds("").ok, false);
  const many = A.parseStudentIds(Array.from({ length: 201 }, (_, i) => "stu_" + i).join("\n"));
  assert.equal(many.tooMany, true);
  assert.equal(many.ok, false);
});

test("admin: errors and results read as plain language", () => {
  assert.equal(A.adminErrorText({ code: "FORBIDDEN" }), "This account is not a platform admin.");
  assert.equal(A.adminErrorText({ code: "NOT_FOUND", message: "Student not found." }), "No student with this id.");
  assert.equal(A.adminErrorText({ code: "NOT_FOUND", message: "Course not found." }), "No course with this id.");
  assert.equal(A.changeText({ changed: true }, "revoke"), "Access removed.");
  assert.match(A.changeText({ changed: false }, "grant"), /already had access/);
});

test("admin: only the admin page loads the admin client", () => {
  assert.match(read("web/admin.html"), /js\/portal\/admin-api\.js/);
  for (const page of ["web/index.html", "web/author.html", "web/review.html"]) assert.doesNotMatch(read(page), /admin-api|admin_portal/);
  for (const src of ["web/js/data-provider.js", "web/js/portal/portal-api.js", "web/js/portal/review-api.js"]) {
    assert.doesNotMatch(read(src), /\/api\/admin/, src);
  }
});
