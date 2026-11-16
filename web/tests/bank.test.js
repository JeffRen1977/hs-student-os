// Question bank screen (Step 45.5): client, offered actions, edit diffs, selection bodies.
const test = require("node:test");
const assert = require("node:assert/strict");
const B = require("../js/portal/bank-api.js");

function fakeFetch(responses) {
  const calls = [];
  const fn = async (url, init) => {
    calls.push({ url, init });
    const r = responses.shift();
    return { ok: r.status < 400, status: r.status, json: async () => r.body };
  };
  fn.calls = calls;
  return fn;
}

test("bank: PATCH edits carry an Idempotency-Key and the expected revision; GETs build queries", async () => {
  const f = fakeFetch([{ status: 200, body: {} }, { status: 200, body: { items: [] } }]);
  const api = B.createBankApi({ baseUrl: "http://api", getIdToken: async () => "t", fetchImpl: f });
  await api.editItem("bki_1", 3, { stem: "x" }, "edit-1");
  await api.listItems({ state: "approved", courseId: "", flag: "seed-status:ready", cursor: null, limit: 50 });
  assert.equal(f.calls[0].init.method, "PATCH");
  assert.ok(f.calls[0].init.headers["Idempotency-Key"]);
  assert.deepEqual(JSON.parse(f.calls[0].init.body), { expectedRevision: 3, changes: { stem: "x" } });
  assert.equal(f.calls[1].url, "http://api/api/bank/items?state=approved&flag=seed-status%3Aready&limit=50");
  assert.equal(f.calls[1].init.headers["Idempotency-Key"], undefined);
});

test("bank: commands go to the item's action route with one key per action", async () => {
  const f = fakeFetch([{ status: 200, body: {} }, { status: 409, body: { error: { code: "ITEM_KEY_REQUIRED", message: "no key" } } }]);
  const api = B.createBankApi({ baseUrl: "", getIdToken: async () => "t", fetchImpl: f });
  await api.act("bki_1", "submit");
  await assert.rejects(api.act("bki_1", "approve", { notes: "" }), (e) => e.code === "ITEM_KEY_REQUIRED" && e.status === 409);
  assert.equal(f.calls[0].url, "/api/bank/items/bki_1/submit");
  assert.equal(f.calls[1].url, "/api/bank/items/bki_1/approve");
});

test("bank: offered actions follow the state and the reviewer permission", () => {
  assert.deepEqual(B.itemActions("extracted", false), ["confirm", "edit", "discard"]);
  assert.deepEqual(B.itemActions("in_review", false), []);
  assert.deepEqual(B.itemActions("in_review", true), ["key", "approve", "reject", "edit"]);
  assert.deepEqual(B.itemActions("approved", false), ["edit"]);
  assert.deepEqual(B.itemActions("approved", true), ["edit", "retire"]);
  assert.deepEqual(B.itemActions("retired", true), []);
});

test("bank: approval problems name what the reviewer must fix", () => {
  const ok = { stem: "s", type: "mc", choices: { A: "1", B: "2", C: "3", D: "4" }, answer: "B", answerSource: "source-key" };
  assert.deepEqual(B.approvalProblems(ok), []);
  assert.match(B.approvalProblems({ ...ok, answerSource: "agent-suggested" })[0], /suggestion/);
  assert.match(B.approvalProblems({ ...ok, answer: null })[0], /no answer key/);
  assert.match(B.approvalProblems({ ...ok, choices: { A: "1", B: "2" } })[0], /A–D/);
  const spr = { stem: "s", type: "spr", answer: "7", answerSource: "reviewer", solution: "" };
  assert.match(B.approvalProblems(spr)[0], /solution/);
});

test("bank: underlined passages split into segments", () => {
  assert.deepEqual(B.underlineSegments("At [[it's]] best, [[the]] end"), [
    { text: "At ", underline: false }, { text: "it's", underline: true }, { text: " best, ", underline: false },
    { text: "the", underline: true }, { text: " end", underline: false },
  ]);
  assert.deepEqual(B.underlineSegments("plain"), [{ text: "plain", underline: false }]);
});

test("bank: an edit sends only changed fields, with null to clear", () => {
  const version = { stem: "Old", type: "mc", choices: { A: "1", B: "2", C: "3", D: "4" }, answer: "B",
    answerSource: "source-key", skillIds: ["dsat.algebra.linear-equations"], flags: ["ocr"], figure: "none" };
  const original = { version, item: { courseId: "dsat" } };
  const form = B.formFromVersion(version, original.item);
  assert.deepEqual(B.changesFromForm(original, form), {});
  const edited = { ...form, stem: "New", choices: { ...form.choices, D: "" }, flags: "", answer: "" };
  assert.deepEqual(B.changesFromForm(original, edited), {
    stem: "New", choices: { A: "1", B: "2", C: "3" }, answer: null, answerSource: null, flags: [],
  });
});

test("bank: selection drafts become request bodies with roles mapped to task lists", () => {
  const draft = { courseId: "dsat", name: "SAT practice", sourceType: "licensed", sourceAuthor: "", sourceLicense: "Internal test only",
    sets: [{ ...B.emptySet(1), items: [{ itemId: "a" }, { itemId: "b", version: 2 }] },
           { ...B.emptySet(2), setId: "reading-1", items: [{ itemId: "c" }], skillIds: "dsat.x.y, dsat.x.z" }] };
  assert.deepEqual(B.selectionProblems(draft), []);
  const body = B.selectionBody(draft, true);
  assert.equal(body.courseId, "dsat");
  assert.deepEqual(body.starterSetIds, ["set-1"]);
  assert.deepEqual(body.sequenceSetIds, ["reading-1"]);
  assert.deepEqual(body.sets[0].items, [{ itemId: "a" }, { itemId: "b", version: 2 }]);
  assert.deepEqual(body.sets[1].skillIds, ["dsat.x.y", "dsat.x.z"]);
  assert.equal(body.sourceAuthor, null);
  assert.equal(B.selectionBody(draft, false).courseId, undefined);
  const bad = { ...draft, sets: [{ ...draft.sets[0], setId: "Bad Id", items: [] }, { ...draft.sets[0], setId: "Bad Id" }] };
  const problems = B.selectionProblems(bad);
  assert.ok(problems.some((p) => /unique/.test(p)) && problems.some((p) => /lowercase/.test(p)) && problems.some((p) => /1 to 10/.test(p)));
});

test("bank: a saved selection round-trips through the editor draft", () => {
  const s = { courseId: "dsat", name: "n", sourceType: "original", sourceAuthor: null, sourceLicense: null,
    sets: [{ setId: "s1", title: "t", taskTitle: "tt", durationMin: 20, difficulty: "medium", skillIds: [], items: [{ itemId: "a", version: 1 }] }],
    starterSetIds: ["s1"], sequenceSetIds: [] };
  const body = B.selectionBody(B.draftFromSelection(s), false);
  assert.deepEqual(body.sets[0].items, [{ itemId: "a", version: 1 }]);
  assert.deepEqual(body.starterSetIds, ["s1"]);
});

test("quick entry: settings drop empty fields and split lists", () => {
  assert.deepEqual(B.settingsBody({ courseId: " dsat ", section: "", skillIds: "a, b", difficulty: "", keyOrigin: "compiled-key", sourceTitle: "", sourceLicense: "", tags: "" }),
    { courseId: "dsat", skillIds: ["a", "b"], keyOrigin: "compiled-key" });
});

test("quick entry: a preview becomes a batch of the kept questions and only their passages", () => {
  const preview = {
    questions: [
      { number: 1, passageRef: "p1", content: { stem: "Q1", type: "mc", choices: { A: "a", B: "b", C: "c", D: "d" }, answer: "B", solution: null, section: null, skillIds: [], difficulty: null } },
      { number: 2, passageRef: null, content: { stem: "Q2", type: "spr", choices: null, answer: "7/2", solution: "x", section: null, skillIds: [], difficulty: null } },
      { number: 3, passageRef: "p2", content: { stem: "Q3", type: "mc", choices: null, answer: null, solution: null, section: null, skillIds: [], difficulty: null } },
    ],
    passages: [{ ref: "p1", title: "T1", text: "one", rangeFrom: 1, rangeTo: 1 }, { ref: "p2", title: "T2", text: "two", rangeFrom: 3, rangeTo: 3 }],
  };
  const batch = B.batchFromPreview(preview, new Set([1, 2]));
  assert.deepEqual(batch.questions.map((q) => q.number), [1, 2]);
  assert.deepEqual(batch.passages, [{ ref: "p1", title: "T1", text: "one" }]);
  assert.deepEqual(batch.questions[1].content, { stem: "Q2", type: "spr", answer: "7/2", solution: "x" });
  assert.equal(batch.questions[1].passageRef, undefined);
});

test("quick entry: chunks stay within the limit and never split a passage group", () => {
  const qs = [];
  for (let n = 1; n <= 5; n++) qs.push({ number: n, passageRef: n >= 2 && n <= 4 ? "p1" : undefined, content: {} });
  const chunks = B.chunkBatch({ questions: qs, passages: [{ ref: "p1", title: "", text: "t" }] }, 3);
  assert.deepEqual(chunks.map((c) => c.questions.map((q) => q.number)), [[1], [2, 3, 4], [5]]);
  assert.deepEqual(chunks.map((c) => c.passages.length), [0, 1, 0]);
});

test("quick entry: the single-question form builds one batch question and lists problems", () => {
  const f = { stem: "Q?", type: "mc", choices: { A: "1", B: "2", C: "3", D: "" }, answer: "E", solution: "", passageMode: "new", passageTitle: "", passageText: "", previousPassageId: null };
  assert.deepEqual(B.formProblems(f), ["Fill in choice D.", "The key is one of A, B, C or D.", "Paste the passage text, or choose no passage."]);
  const ok = { ...f, choices: { A: "1", B: "2", C: "3", D: "4" }, answer: "B", passageText: "Passage", passageTitle: "Q1-2" };
  assert.deepEqual(B.formBatch(ok), {
    questions: [{ number: 1, passageRef: "p1", content: { stem: "Q?", type: "mc", choices: { A: "1", B: "2", C: "3", D: "4" }, answer: "B" } }],
    passages: [{ ref: "p1", title: "Q1-2", text: "Passage" }],
  });
  const again = B.formBatch({ ...ok, passageMode: "previous", previousPassageId: "bkp_1" });
  assert.equal(again.questions[0].content.passageId, "bkp_1");
  assert.deepEqual(again.passages, []);
  assert.equal(B.CSV_TEMPLATE.split("\n")[0], B.CSV_COLUMNS.join(","));
});
