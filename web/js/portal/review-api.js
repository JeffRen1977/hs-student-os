// review-api.js — client and pure helpers for the reviewer screen (Step 41). Plain JS
// (window.HSReviewApi; Node-testable, tests/review.test.js). It calls only the existing
// /api/review/* endpoints for content review; admins publish via their own endpoints.
// so this screen adds no authority. Only review.html loads this file; the author portal and
// the student app never do.
(function (root, factory) {
  const portal = typeof module === "object" && module.exports ? require("./portal-api.js") : root.HSPortalApi;
  const api = factory(portal);
  if (typeof module === "object" && module.exports) module.exports = api;
  else root.HSReviewApi = api;
})(typeof self !== "undefined" ? self : this, function (portal) {
  "use strict";

  // Every status a reviewer can see (drafts stay private to their organization).
  const REVIEWER_STATUSES = ["submitted", "approved", "active", "superseded", "rejected", "retired"];

  function createReviewApi(options) {
    const request = portal.createRequester(options);
    const enc = encodeURIComponent;
    const ver = (c, v) => "/api/review/packages/" + enc(c) + "/versions/" + enc(v);
    const id = (action, c, v) => action + ":" + c + "@" + (v || "");
    return {
      queue: (statuses) => request("GET", "/api/review/packages?" +
        (statuses || REVIEWER_STATUSES).map((s) => "status=" + enc(s)).join("&")),
      getVersion: (c, v) => request("GET", ver(c, v)),
      preview: (c, v) => request("GET", ver(c, v) + "/preview"),
      approve: (c, v, d) => request("POST", ver(c, v) + "/approve", {
        notes: d.notes || "",
        licenseAttested: !!d.licenseAttested,
        modelEvaluationAttested: !!d.modelEvaluationAttested,
      }, id("approve", c, v)),
      reject: (c, v, notes) => request("POST", ver(c, v) + "/reject", { notes }, id("reject", c, v)),
    };
  }

  // ---- Queue ------------------------------------------------------------------------------

  function lastAt(v, status) {
    const hits = (v.history || []).filter((h) => h.toStatus === status);
    return hits.length ? hits[hits.length - 1].at : null;
  }

  function semverCompare(a, b) {
    const pa = String(a).split(".").map(Number), pb = String(b).split(".").map(Number);
    for (let i = 0; i < 3; i++) if ((pa[i] || 0) !== (pb[i] || 0)) return (pa[i] || 0) < (pb[i] || 0) ? -1 : 1;
    return 0;
  }

  // How a pending version relates to its course's active version: "upgrade" (newer),
  // "older" (activation would be refused) or null (no active version, or not pending).
  function versionRelation(status, version, activeVersion) {
    if (!activeVersion || activeVersion === version || (status !== "submitted" && status !== "approved")) return null;
    return semverCompare(version, activeVersion) > 0 ? "upgrade" : "older";
  }

  // Versions waiting on a reviewer (submitted, then approved-but-not-live), oldest first,
  // each with its relation to the course's active version.
  function queueRows(versions) {
    const active = {};
    for (const v of versions) if (v.status === "active") active[v.courseId] = v.version;
    return versions
      .filter((v) => v.status === "submitted" || v.status === "approved")
      .map((v) => ({
        courseId: v.courseId,
        version: v.version,
        title: v.title,
        orgId: v.orgId,
        status: v.status,
        uploadedBy: v.uploadedBy,
        submittedAt: lastAt(v, "submitted"),
        activeVersion: active[v.courseId] || null,
        relation: versionRelation(v.status, v.version, active[v.courseId]),
      }))
      .sort((a, b) => (a.status === b.status ? String(a.submittedAt).localeCompare(String(b.submittedAt)) : a.status === "submitted" ? -1 : 1));
  }

  // What a reviewer can do next, following the server's state machine.
  function actionsFor(status) {
    return { submitted: ["approve", "reject"], approved: [], active: [] }[status] || [];
  }

  // ---- Upgrade comparison -----------------------------------------------------------------

  function canonical(x) {
    if (Array.isArray(x)) return "[" + x.map(canonical).join(",") + "]";
    if (x && typeof x === "object") {
      return "{" + Object.keys(x).sort().map((k) => JSON.stringify(k) + ":" + canonical(x[k])).join(",") + "}";
    }
    return JSON.stringify(x);
  }

  function byId(list, key) {
    const out = new Map();
    for (const x of list || []) out.set(x[key], x);
    return out;
  }

  function changedFields(a, b) {
    const keys = Array.from(new Set(Object.keys(a).concat(Object.keys(b)))).sort();
    return keys.filter((k) => canonical(a[k]) !== canonical(b[k]));
  }

  // Compare the active version's package with a candidate's. Removed IDs are flagged:
  // students' existing tasks, sessions and mastery refer to question and skill IDs, and a
  // reviewer cannot see which students use them, so every removal is a warning.
  function comparePackages(active, next) {
    const qa = byId(active.questions, "questionId"), qn = byId(next.questions, "questionId");
    const sa = byId(active.skills, "skillId"), sn = byId(next.skills, "skillId");
    const questions = { added: [], removed: [], changed: [] };
    const skills = { added: [], removed: [], renamed: [] };
    const warnings = [];
    for (const [qid, q] of qn) {
      const old = qa.get(qid);
      if (!old) questions.added.push(qid);
      else if (canonical(old) !== canonical(q)) {
        questions.changed.push({ questionId: qid, fromVersion: old.version, toVersion: q.version, fields: changedFields(old, q) });
        if (old.version === q.version) {
          warnings.push({ kind: "question_changed_same_version", id: qid,
            message: "Question " + qid + " changed but kept version " + q.version + ". A changed question needs a new question version." });
        }
      }
    }
    for (const qid of qa.keys()) {
      if (!qn.has(qid)) {
        questions.removed.push(qid);
        warnings.push({ kind: "question_removed", id: qid,
          message: "Question " + qid + " is in the active version but not in this one. Students' existing tasks and sessions may still use it." });
      }
    }
    for (const [sid, s] of sn) {
      const old = sa.get(sid);
      if (!old) skills.added.push(sid);
      else if (old.name !== s.name) skills.renamed.push({ skillId: sid, from: old.name, to: s.name });
    }
    for (const sid of sa.keys()) {
      if (!sn.has(sid)) {
        skills.removed.push(sid);
        warnings.push({ kind: "skill_removed", id: sid,
          message: "Skill " + sid + " is in the active version but not in this one. Students' mastery records may still use it." });
      }
    }
    return { questions, skills, warnings };
  }

  // ---- Content for review -----------------------------------------------------------------

  // Questions with each item's answer key, its rubric line and that line's skills, so a
  // reviewer can check every item in one place.
  function reviewContent(pkg) {
    const rubrics = new Map((pkg.rubrics || []).map((r) => [r.rubricId + "@" + r.version, r]));
    const skillNames = new Map((pkg.skills || []).map((s) => [s.skillId, s.name]));
    const materials = byId(pkg.materials, "materialId");
    return (pkg.questions || []).map((q) => {
      const rubric = q.rubricRef ? rubrics.get(q.rubricRef.rubricId + "@" + q.rubricRef.version) : null;
      const criteria = new Map(((rubric && rubric.criteria) || []).map((c) => [c.criterionId, c]));
      const skillsOf = (ids) => (ids || []).map((id) => ({ skillId: id, name: skillNames.get(id) || "(unknown skill)" }));
      return {
        questionId: q.questionId,
        version: q.version,
        topic: q.topic,
        prompt: q.prompt,
        expectedAnswer: q.expectedAnswer || null,
        source: q.source || null,
        review: q.review || null,
        skills: skillsOf(q.skillIds),
        rubric: rubric ? { rubricId: rubric.rubricId, version: rubric.version, source: rubric.source || null } : null,
        sources: (q.sourceMaterialIds || []).map((m) => materials.get(m)).filter(Boolean),
        items: q.items ? q.items.map((i) => {
          const c = criteria.get(i.criterionId);
          return {
            itemId: i.itemId, prompt: i.prompt, choices: i.choices, answerKey: i.answerKey,
            criterionId: i.criterionId, skills: skillsOf(c && c.skillIds),
          };
        }) : null,
        criteria: q.items ? [] : Array.from(criteria.values()),
      };
    });
  }

  // ---- Per-item checklist (reviewer's browser only) ---------------------------------------

  const CHECKS = Object.freeze([
    { id: "answerKey", label: "Answer key is correct" },
    { id: "oneAnswer", label: "Exactly one defensible answer" },
    { id: "skillTag", label: "Skill tag fits" },
    { id: "source", label: "Source and license are acceptable" },
  ]);

  function checklistItems(pkg) {
    const out = [];
    for (const q of pkg.questions || []) {
      if (q.items) for (const i of q.items) out.push({ key: q.questionId + "#" + i.itemId, questionId: q.questionId, itemId: i.itemId });
      else out.push({ key: q.questionId, questionId: q.questionId, itemId: null });
    }
    return out;
  }

  // Kept in this browser only (localStorage), per reviewer and package version. It is a
  // working aid, not review evidence: the decision and its notes are what the server records.
  function createChecklist(storage, reviewerId, courseId, version) {
    const key = "hsos.reviewChecklist." + reviewerId + "." + courseId + "@" + version;
    let state = {};
    try { state = JSON.parse((storage && storage.getItem(key)) || "{}") || {}; } catch (_e) { state = {}; }
    function save() {
      try { if (storage) storage.setItem(key, JSON.stringify(state)); } catch (_e) { /* storage unavailable: keep in memory */ }
    }
    return {
      isChecked: (itemKey, checkId) => !!(state[itemKey] && state[itemKey][checkId]),
      set(itemKey, checkId, value) {
        const row = Object.assign({}, state[itemKey]);
        if (value) row[checkId] = true; else delete row[checkId];
        state = Object.assign({}, state, { [itemKey]: row });
        save();
      },
      progress(items) {
        const done = items.filter((i) => CHECKS.every((c) => state[i.key] && state[i.key][c.id])).length;
        return { done, total: items.length };
      },
      clear() { state = {}; try { if (storage) storage.removeItem(key); } catch (_e) { /* ignore */ } },
    };
  }

  // ---- Errors in plain language -----------------------------------------------------------

  function reviewErrorText(err) {
    const e = err || {};
    const msg = e.message || "";
    switch (e.code) {
      case "REVIEW_REQUIREMENTS_NOT_MET":
        return "This version can't be approved yet: " + msg.replace(/^Cannot approve:\s*/, "") + ".";
      case "INVALID_STATE_TRANSITION":
        return "That action doesn't fit this version's current status. " + msg + " Reload to see the latest status.";
      case "FORBIDDEN":
        return "This account is not a platform reviewer.";
      case "NOT_FOUND":
        return "Not found. Drafts are private to their organization until the author submits them.";
      case "PACKAGE_INVALID":
        return "The validator report has errors, so there is no student preview.";
      case "IDEMPOTENCY_CONFLICT":
        return "This action was already sent with different details. Reload and try again.";
      case "VALIDATION_FAILED":
        return "The request was incomplete: " + msg;
      case "UNAUTHENTICATED":
        return "Sign in again.";
      default:
        return msg || "Something went wrong.";
    }
  }

  return {
    createReviewApi, queueRows, versionRelation, actionsFor, comparePackages, reviewContent,
    CHECKS, checklistItems, createChecklist, reviewErrorText, REVIEWER_STATUSES,
  };
});
