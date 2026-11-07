// Reviewer screen client (Step 41): existing review endpoints only, idempotent decisions,
// the queue, the upgrade comparison on Digital SAT 1.0.0 → 2.0.0, plain-language errors,
// the browser-only checklist, and no review client on author or student pages.
"use strict";

const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const R = require("../js/portal/review-api.js");

const ROOT = path.join(__dirname, "..", "..");
const read = (p) => fs.readFileSync(path.join(ROOT, p), "utf8");
const DSAT_1 = JSON.parse(read("server/content/authored/dsat/package.json"));
const DSAT_2 = JSON.parse(read("server/content/authored/dsat/package-2.0.0.json"));
const clone = (x) => JSON.parse(JSON.stringify(x));

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

const api = (f) => R.createReviewApi({ baseUrl: "http://api", getIdToken: async () => "tok", fetchImpl: f });

test("review: every decision goes to the existing endpoint with an Idempotency-Key", async () => {
  const f = fakeFetch([]);
  const a = api(f);
  await a.approve("dsat", "2.0.1", { notes: "ok", licenseAttested: true });
  await a.reject("dsat", "2.0.2", "Item 3 has two defensible answers.");
  await a.activate("dsat", "2.0.1");
  await a.retire("apush", "Replaced.");
  await a.queue();
  await a.getVersion("dsat", "2.0.1");
  await a.preview("dsat", "2.0.1");
  assert.deepEqual(f.calls.map((c) => [c.init.method, c.url.replace("http://api", "")]), [
    ["POST", "/api/review/packages/dsat/versions/2.0.1/approve"],
    ["POST", "/api/review/packages/dsat/versions/2.0.2/reject"],
    ["POST", "/api/review/packages/dsat/versions/2.0.1/activate"],
    ["POST", "/api/review/courses/apush/retire"],
    ["GET", "/api/review/packages?status=submitted&status=approved&status=active&status=superseded&status=rejected&status=retired"],
    ["GET", "/api/review/packages/dsat/versions/2.0.1"],
    ["GET", "/api/review/packages/dsat/versions/2.0.1/preview"],
  ]);
  assert.deepEqual(f.calls[0].body, { notes: "ok", licenseAttested: true, modelEvaluationAttested: false });
  assert.deepEqual(f.calls[1].body, { notes: "Item 3 has two defensible answers." });
  assert.deepEqual(f.calls[2].body, {});
  assert.deepEqual(f.calls[3].body, { notes: "Replaced." });
  for (const c of f.calls.slice(0, 4)) assert.match(c.init.headers["Idempotency-Key"], /^idk_/);
  for (const c of f.calls.slice(4)) assert.equal(c.init.headers["Idempotency-Key"], undefined);
  assert.equal(new Set(f.calls.slice(0, 4).map((c) => c.init.headers["Idempotency-Key"])).size, 4);
});

test("review: a retried approval reuses its key; after the server answers, a new attempt is new", async () => {
  const f = fakeFetch([
    new Error("offline"),
    { status: 422, body: { error: { code: "REVIEW_REQUIREMENTS_NOT_MET", message: "Cannot approve: the content license must be attested" } } },
    { status: 200, body: { status: "approved" } },
  ]);
  const a = api(f);
  const d = { notes: "", licenseAttested: false };
  await assert.rejects(a.approve("dsat", "2.0.1", d), (e) => e.code === "NETWORK");
  await assert.rejects(a.approve("dsat", "2.0.1", d), (e) => e.code === "REVIEW_REQUIREMENTS_NOT_MET");
  await a.approve("dsat", "2.0.1", { notes: "", licenseAttested: true });
  const keys = f.calls.map((c) => c.init.headers["Idempotency-Key"]);
  assert.equal(keys[0], keys[1]);
  assert.notEqual(keys[1], keys[2]);
});

test("review: server errors read as plain language", () => {
  const text = (code, message) => R.reviewErrorText({ code, message });
  assert.equal(text("REVIEW_REQUIREMENTS_NOT_MET", "Cannot approve: the content license must be attested"),
    "This version can't be approved yet: the content license must be attested.");
  assert.match(text("INVALID_STATE_TRANSITION", "A rejected package cannot become approved."),
    /doesn't fit this version's current status\. A rejected package cannot become approved\. Reload/);
  assert.equal(text("FORBIDDEN", "Forbidden."), "This account is not a platform reviewer.");
  assert.match(text("NOT_FOUND", "Package not found."), /Drafts are private/);
  assert.equal(text("SOMETHING_NEW", "Server said this."), "Server said this.");
});

function version(courseId, v, status, history, extra) {
  return Object.assign({ courseId, version: v, status, title: courseId, orgId: "org_x", uploadedBy: "author_x",
    history: history.map(([toStatus, at]) => ({ toStatus, at })) }, extra);
}

test("review: the queue lists submitted then approved versions, oldest first, flagging upgrades", () => {
  const rows = R.queueRows([
    version("dsat", "1.0.0", "superseded", [["submitted", "2026-11-01T00:00:00Z"]]),
    version("dsat", "2.0.0", "active", [["submitted", "2026-11-05T00:00:00Z"]]),
    version("dsat", "2.0.1", "submitted", [["submitted", "2026-11-07T10:00:00Z"]]),
    version("apush", "1.0.0", "approved", [["submitted", "2026-11-02T00:00:00Z"], ["approved", "2026-11-03T00:00:00Z"]]),
    version("bio", "1.0.0", "submitted", [["submitted", "2026-11-06T00:00:00Z"]]),
    version("chem", "1.0.0", "rejected", [["submitted", "2026-11-04T00:00:00Z"]]),
  ]);
  assert.deepEqual(rows.map((r) => [r.courseId, r.version, r.relation, r.submittedAt]), [
    ["bio", "1.0.0", null, "2026-11-06T00:00:00Z"],
    ["dsat", "2.0.1", "upgrade", "2026-11-07T10:00:00Z"],
    ["apush", "1.0.0", null, "2026-11-02T00:00:00Z"],
  ]);
});

test("review: a pending version older than the active one is flagged, decided ones are not", () => {
  assert.equal(R.versionRelation("submitted", "2.0.0", "2.0.1"), "older");
  assert.equal(R.versionRelation("approved", "2.0.10", "2.0.9"), "upgrade");
  assert.equal(R.versionRelation("rejected", "2.0.0", "2.0.1"), null);
  assert.equal(R.versionRelation("submitted", "1.0.0", null), null);
});

test("review: available actions follow the package state machine", () => {
  assert.deepEqual(R.actionsFor("submitted"), ["approve", "reject"]);
  assert.deepEqual(R.actionsFor("approved"), ["activate"]);
  assert.deepEqual(R.actionsFor("active"), ["retire"]);
  for (const s of ["draft", "superseded", "rejected", "retired"]) assert.deepEqual(R.actionsFor(s), []);
});

test("review: Digital SAT 1.0.0 → 2.0.0 keeps every question and skill ID", () => {
  const d = R.comparePackages(DSAT_1, DSAT_2);
  assert.deepEqual(d.warnings, []);
  assert.deepEqual(d.questions.removed, []);
  assert.deepEqual(d.skills.removed, []);
  assert.equal(d.questions.added.length, DSAT_2.questions.length - DSAT_1.questions.length);
  assert.equal(d.skills.added.length, DSAT_2.skills.length - DSAT_1.skills.length);
  assert.ok(d.questions.added.includes("q_dsat_info_001"));
  for (const id of DSAT_1.questions.map((q) => q.questionId)) assert.ok(!d.questions.added.includes(id));
});

test("review: removed IDs and a changed question without a new version are warnings", () => {
  const next = clone(DSAT_2);
  next.questions = next.questions.filter((q) => q.questionId !== "q_dsat_equiv_002");
  next.skills = next.skills.filter((s) => s.skillId !== "dsat.problem-solving.rates-ratios");
  const q = next.questions.find((x) => x.questionId === "q_dsat_equiv_001");
  q.items[0].answerKey = "B";
  const d = R.comparePackages(DSAT_1, next);
  assert.deepEqual(d.warnings.map((w) => [w.kind, w.id]), [
    ["question_changed_same_version", "q_dsat_equiv_001"],
    ["question_removed", "q_dsat_equiv_002"],
    ["skill_removed", "dsat.problem-solving.rates-ratios"],
  ]);
  assert.deepEqual(d.questions.changed.find((c) => c.questionId === "q_dsat_equiv_001").fields, ["items"]);
  assert.match(d.warnings[1].message, /existing tasks and sessions/);
  assert.match(d.warnings[2].message, /mastery/);
});

test("review: content shows each item's key and the skill from its rubric line", () => {
  const content = R.reviewContent(DSAT_2);
  assert.equal(content.length, DSAT_2.questions.length);
  for (const q of content) {
    assert.ok(q.source && q.rubric && q.items, q.questionId);
    for (const i of q.items) {
      assert.match(i.answerKey, /^[A-D]$/);
      assert.ok(i.skills.length > 0 && i.skills.every((s) => s.name !== "(unknown skill)"), q.questionId + "#" + i.itemId);
    }
  }
  const equiv = content.find((q) => q.questionId === "q_dsat_equiv_001");
  assert.equal(equiv.items[0].answerKey, "A");
  assert.deepEqual(equiv.items[0].skills.map((s) => s.skillId), ["dsat.advanced-math.equivalent-expressions"]);
});

function memoryStorage() {
  const m = new Map();
  return { getItem: (k) => (m.has(k) ? m.get(k) : null), setItem: (k, v) => m.set(k, v), removeItem: (k) => m.delete(k), m };
}

test("review: the checklist is per reviewer and version, in this browser only", () => {
  const storage = memoryStorage();
  const items = R.checklistItems(DSAT_2);
  assert.equal(items.length, DSAT_2.questions.reduce((n, q) => n + q.items.length, 0));
  const a = R.createChecklist(storage, "reviewer_platform", "dsat", "2.0.0");
  for (const c of R.CHECKS) a.set(items[0].key, c.id, true);
  a.set(items[1].key, "answerKey", true);
  assert.deepEqual(a.progress(items), { done: 1, total: items.length });
  // Reloading the page restores it; another version or reviewer starts empty.
  assert.deepEqual(R.createChecklist(storage, "reviewer_platform", "dsat", "2.0.0").progress(items).done, 1);
  assert.equal(R.createChecklist(storage, "reviewer_platform", "dsat", "2.0.1").isChecked(items[0].key, "answerKey"), false);
  assert.equal(R.createChecklist(storage, "reviewer_other", "dsat", "2.0.0").isChecked(items[0].key, "answerKey"), false);
  a.set(items[1].key, "answerKey", false);
  assert.equal(a.isChecked(items[1].key, "answerKey"), false);
  assert.deepEqual([...storage.m.keys()], ["hsos.reviewChecklist.reviewer_platform.dsat@2.0.0"]);
  // Blocked storage never breaks the screen.
  const broken = { getItem() { throw new Error("blocked"); }, setItem() { throw new Error("blocked"); }, removeItem() { throw new Error("blocked"); } };
  const b = R.createChecklist(broken, "r", "dsat", "2.0.0");
  b.set(items[0].key, "answerKey", true);
  assert.equal(b.isChecked(items[0].key, "answerKey"), true);
});

test("review: only the reviewer page loads the review client", () => {
  assert.match(read("web/review.html"), /js\/portal\/review-api\.js/);
  for (const page of ["web/index.html", "web/author.html"]) assert.doesNotMatch(read(page), /review-api|review_portal/);
  for (const src of ["web/js/portal/portal-api.js", "web/js/portal/author_portal.js", "web/js/data-provider.js"]) {
    assert.doesNotMatch(read(src), /\/api\/review/, src);
  }
});
