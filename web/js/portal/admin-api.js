// admin-api.js — client and pure helpers for the course-access admin screen (Step 42).
// Plain JS (window.HSAdminApi; Node-testable, tests/admin.test.js). It calls only the
// /api/admin/* endpoints; the server checks the platform admin role on every request. Only
// admin.html loads this file.
(function (root, factory) {
  const portal = typeof module === "object" && module.exports ? require("./portal-api.js") : root.HSPortalApi;
  const api = factory(portal);
  if (typeof module === "object" && module.exports) module.exports = api;
  else root.HSAdminApi = api;
})(typeof self !== "undefined" ? self : this, function (portal) {
  "use strict";

  const ID = /^[A-Za-z0-9_\-:.]{1,128}$/;
  const MAX_BULK = 200;

  function createAdminApi(options) {
    const request = portal.createRequester(options);
    const enc = encodeURIComponent;
    const student = (sid) => "/api/admin/students/" + enc(sid) + "/access";
    // One action per (change, student, course, reason): a retry after a network failure
    // reuses its Idempotency-Key; changing the reason makes it a new action.
    const id = (kind, sid, courseId, reason) => [kind, sid, courseId, reason].join("\n");
    return {
      getAccess: (sid) => request("GET", student(sid)),
      grant: (sid, courseId, reason) =>
        request("POST", student(sid) + "/grant", { courseId, reason }, id("grant", sid, courseId, reason)),
      revoke: (sid, courseId, reason) =>
        request("POST", student(sid) + "/revoke", { courseId, reason }, id("revoke", sid, courseId, reason)),
      bulk: (b) => request("POST", "/api/admin/access/bulk",
        { studentIds: b.studentIds, courseId: b.courseId, change: b.change, reason: b.reason },
        id("bulk:" + b.change, b.studentIds.join(","), b.courseId, b.reason)),
    };
  }

  // A pasted list (one per line, or separated by commas/spaces) → unique, valid ids.
  function parseStudentIds(text) {
    const ids = [], invalid = [], seen = new Set();
    for (const raw of String(text || "").split(/[\s,;]+/)) {
      const s = raw.trim();
      if (!s || seen.has(s)) continue;
      seen.add(s);
      (ID.test(s) ? ids : invalid).push(s);
    }
    const tooMany = ids.length > MAX_BULK;
    return { ids, invalid, tooMany, ok: ids.length > 0 && invalid.length === 0 && !tooMany };
  }

  function adminErrorText(err) {
    const e = err || {};
    switch (e.code) {
      case "FORBIDDEN": return "This account is not a platform admin.";
      case "NOT_FOUND": return /course/i.test(e.message || "") ? "No course with this id." : "No student with this id.";
      case "VALIDATION_FAILED": return "The request was incomplete: " + (e.message || "") + " A reason is required.";
      case "IDEMPOTENCY_CONFLICT": return "This change was already sent with different details. Reload and try again.";
      case "UNAUTHENTICATED": return "Sign in again.";
      case "NETWORK": return e.message;
      default: return e.message || "Something went wrong.";
    }
  }

  function changeText(result, change) {
    if (!result) return "";
    if (result.changed) return change === "grant" ? "Access granted." : "Access removed.";
    return change === "grant" ? "No change: the student already had access." : "No change: the student had no access.";
  }

  return { createAdminApi, parseStudentIds, adminErrorText, changeText, MAX_BULK };
});
