// bank-api.js — API client and pure helpers for the question bank screen (Step 45.5).
// Plain JS (window.HSBankApi; Node-testable). Authors and content reviewers of one
// organization; the server enforces every permission — these helpers only decide what the
// screen offers. No student data is reachable from /api/bank/*.
(function (root, factory) {
  const portal = typeof module === "object" && module.exports ? require("./portal-api.js") : root.HSPortalApi;
  const api = factory(portal);
  if (typeof module === "object" && module.exports) module.exports = api;
  else root.HSBankApi = api;
})(typeof self !== "undefined" ? self : this, function (portal) {
  "use strict";

  const enc = encodeURIComponent;

  function createBankApi(options) {
    const request = portal.createRequester(options);
    const item = (id) => "/api/bank/items/" + enc(id);
    const sel = (id) => "/api/bank/selections/" + enc(id);
    return {
      me: () => request("GET", "/api/bank/me"),
      listItems: (q) => request("GET", "/api/bank/items" + queryString(q)),
      getItem: (id) => request("GET", item(id)),
      getPassage: (id) => request("GET", "/api/bank/passages/" + enc(id)),
      createItem: (body, actionId) => request("POST", "/api/bank/items", body, actionId),
      editItem: (id, revision, changes, actionId) =>
        request("PATCH", item(id), { expectedRevision: revision, changes: changes }, actionId),
      // confirm | submit | discard | key | approve | reject | retire
      act: (id, action, body, actionId) =>
        request("POST", item(id) + "/" + action, body || {}, actionId || action + ":" + id),
      listSelections: () => request("GET", "/api/bank/selections"),
      getSelection: (id) => request("GET", sel(id)),
      createSelection: (body, actionId) => request("POST", "/api/bank/selections", body, actionId),
      updateSelection: (id, revision, selection, actionId) =>
        request("PATCH", sel(id), { expectedRevision: revision, selection: selection }, actionId),
      build: (id, version, actionId) => request("POST", sel(id) + "/build", { version: version }, actionId),
    };
  }

  function queryString(q) {
    const parts = [];
    for (const [k, v] of Object.entries(q || {})) {
      if (v !== undefined && v !== null && v !== "") parts.push(enc(k) + "=" + enc(String(v)));
    }
    return parts.length ? "?" + parts.join("&") : "";
  }

  const STATE_TEXT = {
    extracted: "Extracted — an author must open and confirm it",
    draft: "Draft — the author is editing",
    in_review: "In review — waiting for the content reviewer",
    approved: "Approved — can be selected for a package",
    rejected: "Rejected — see the reviewer's notes; editing opens a new version",
    discarded: "Discarded",
    retired: "Retired — no longer selectable",
  };

  const KEY_TEXT = {
    "source-key": "Key printed in the source",
    "compiled-key": "Third-party (compiled) key",
    reviewer: "Key confirmed by the content reviewer",
    "agent-suggested": "Suggested key — the reviewer must confirm it",
  };

  // Which commands the screen offers for an item, mirroring the server's rules.
  function itemActions(state, canReview) {
    const a = [];
    if (state === "extracted") a.push("confirm", "edit", "discard");
    if (state === "draft") a.push("submit", "edit", "discard");
    if (state === "in_review" && canReview) a.push("key", "approve", "reject", "edit");
    if (state === "approved") a.push("edit");
    if (state === "approved" && canReview) a.push("retire");
    if (state === "rejected") a.push("edit");
    return a;
  }

  // Why approval would be refused, so the screen can say it before the reviewer clicks.
  function approvalProblems(version) {
    const p = [];
    if (!version.stem || !version.stem.trim()) p.push("The stem is empty.");
    if (version.type === "mc") {
      const c = version.choices || {};
      if (!["A", "B", "C", "D"].every((k) => c[k] && c[k].trim())) p.push("Choices A–D must all be filled in.");
    }
    if (!version.answer) p.push("There is no answer key: set one.");
    else if (version.answerSource === "agent-suggested") p.push("The key is only a suggestion: confirm it with Set key.");
    if (version.type === "spr" && version.answerSource === "reviewer" && !(version.solution || "").trim()) {
      p.push("A reviewer key on a student-produced response needs a solution.");
    }
    return p;
  }

  // "[[underlined]] text" → segments the screen renders with <u> for underlined parts.
  function underlineSegments(text) {
    const out = [];
    const re = /\[\[([\s\S]*?)\]\]/g;
    let last = 0;
    let m;
    while ((m = re.exec(text || "")) !== null) {
      if (m.index > last) out.push({ text: text.slice(last, m.index), underline: false });
      out.push({ text: m[1], underline: true });
      last = m.index + m[0].length;
    }
    if (last < (text || "").length) out.push({ text: text.slice(last), underline: false });
    return out;
  }

  // Edit form ↔ item version. Lists are edited as comma-separated text.
  function formFromVersion(v, item) {
    return {
      stem: v.stem || "",
      type: v.type || "mc",
      choices: { A: "", B: "", C: "", D: "", ...(v.choices || {}) },
      answer: v.answer || "",
      answerSource: v.answerSource || "",
      solution: v.solution || "",
      section: v.section || "",
      difficulty: v.difficulty || "",
      skillIds: (v.skillIds || []).join(", "),
      flags: (v.flags || []).join(", "),
      figure: v.figure || "none",
      courseId: (item && item.courseId) || "",
    };
  }

  const splitList = (s) => s.split(",").map((x) => x.trim()).filter(Boolean);
  const orNull = (s) => (s && s.trim() ? s.trim() : null);

  // Only the fields that differ go into the PATCH; `null` clears a field.
  function changesFromForm(original, form) {
    const before = formFromVersion(original.version, original.item);
    const changes = {};
    if (form.stem !== before.stem) changes.stem = form.stem;
    if (form.type !== before.type) changes.type = form.type;
    if (form.type === "mc") {
      const choices = {};
      for (const k of ["A", "B", "C", "D"]) if (form.choices[k].trim()) choices[k] = form.choices[k];
      const was = {};
      for (const k of ["A", "B", "C", "D"]) if (before.choices[k].trim()) was[k] = before.choices[k];
      if (JSON.stringify(choices) !== JSON.stringify(was) || form.type !== before.type) {
        changes.choices = Object.keys(choices).length ? choices : null;
      }
    } else if (form.type !== before.type) {
      changes.choices = null;
    }
    if (form.answer !== before.answer || form.answerSource !== before.answerSource) {
      changes.answer = orNull(form.answer);
      changes.answerSource = changes.answer ? orNull(form.answerSource) : null;
    }
    if (form.solution !== before.solution) changes.solution = orNull(form.solution);
    if (form.section !== before.section) changes.section = orNull(form.section);
    if (form.difficulty !== before.difficulty) changes.difficulty = orNull(form.difficulty);
    if (form.skillIds !== before.skillIds) changes.skillIds = splitList(form.skillIds);
    if (form.flags !== before.flags) changes.flags = splitList(form.flags);
    if (form.figure !== before.figure) changes.figure = form.figure;
    if (form.courseId !== before.courseId) changes.courseId = orNull(form.courseId);
    return changes;
  }

  // ---- Selections ------------------------------------------------------------------------

  function emptySet(n) {
    return { setId: "set-" + n, title: "Set " + n, taskTitle: "Practice set " + n, durationMin: 20,
      difficulty: "medium", skillIds: "", items: [], role: n === 1 ? "starter" : "sequence" };
  }

  function draftFromSelection(s) {
    return {
      courseId: s.courseId, name: s.name, sourceType: s.sourceType,
      sourceAuthor: s.sourceAuthor || "", sourceLicense: s.sourceLicense || "",
      sets: s.sets.map((st) => ({
        setId: st.setId, title: st.title, taskTitle: st.taskTitle, durationMin: st.durationMin,
        difficulty: st.difficulty, skillIds: st.skillIds.join(", "),
        items: st.items.map((r) => ({ itemId: r.itemId, version: r.version })),
        role: s.starterSetIds.includes(st.setId) ? "starter" : s.sequenceSetIds.includes(st.setId) ? "sequence" : "none",
      })),
    };
  }

  // Draft → request body (`withCourse` for create; PATCH bodies omit courseId).
  function selectionBody(d, withCourse) {
    const body = {
      name: d.name,
      sets: d.sets.map((st) => ({
        setId: st.setId, title: st.title, taskTitle: st.taskTitle, durationMin: Number(st.durationMin),
        difficulty: st.difficulty, skillIds: splitList(st.skillIds),
        items: st.items.map((r) => (r.version ? { itemId: r.itemId, version: r.version } : { itemId: r.itemId })),
      })),
      starterSetIds: d.sets.filter((s) => s.role === "starter").map((s) => s.setId),
      sequenceSetIds: d.sets.filter((s) => s.role === "sequence").map((s) => s.setId),
      sourceType: d.sourceType,
      sourceAuthor: orNull(d.sourceAuthor),
      sourceLicense: orNull(d.sourceLicense),
    };
    if (withCourse) body.courseId = d.courseId;
    return body;
  }

  // Client-side checks before saving (the server repeats them).
  function selectionProblems(d) {
    const p = [];
    if (!d.name || !d.name.trim()) p.push("Give the selection a name.");
    if (!d.sets.length) p.push("Add at least one set.");
    const ids = d.sets.map((s) => s.setId);
    if (new Set(ids).size !== ids.length) p.push("Set ids must be unique.");
    for (const s of d.sets) {
      if (!/^[a-z0-9][a-z0-9-]{0,39}$/.test(s.setId)) p.push("Set id '" + s.setId + "': lowercase letters, digits and hyphens.");
      if (!s.items.length || s.items.length > 10) p.push("Set " + s.setId + ": 1 to 10 items.");
    }
    const all = d.sets.flatMap((s) => s.items.map((r) => r.itemId));
    if (new Set(all).size !== all.length) p.push("An item is used more than once.");
    if (d.sets.filter((s) => s.role === "starter").length > 20) p.push("At most 20 starter sets.");
    return p;
  }

  return {
    createBankApi, queryString, STATE_TEXT, KEY_TEXT, itemActions, approvalProblems,
    underlineSegments, formFromVersion, changesFromForm, emptySet, draftFromSelection,
    selectionBody, selectionProblems,
  };
});
