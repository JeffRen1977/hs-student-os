// portal-api.js — API client for the author portal (Step 34.1). Plain JS (window.HSPortalApi;
// Node-testable). Authors only ever call /api/authoring/*: their own organization's packages,
// a student-view preview, and aggregate course metrics. No student data is reachable here.
(function (root, factory) {
  const api = factory();
  if (typeof module === "object" && module.exports) module.exports = api;
  else root.HSPortalApi = api;
})(typeof self !== "undefined" ? self : this, function () {
  "use strict";

  class PortalError extends Error {
    constructor(code, message, status, details) {
      super(message);
      this.code = code;
      this.status = status;
      this.details = details || null;
    }
  }

  function newKey() {
    if (typeof crypto !== "undefined" && crypto.randomUUID) return "idk_" + crypto.randomUUID();
    return "idk_" + Math.random().toString(36).slice(2) + Date.now().toString(36);
  }

  // One Idempotency-Key per user action: a retry of the same action reuses it, so a
  // network failure after the server committed never uploads or submits twice.
  function createActionKeys() {
    const keys = new Map();
    return {
      keyFor(actionId) {
        if (!keys.has(actionId)) keys.set(actionId, newKey());
        return keys.get(actionId);
      },
      done(actionId) { keys.delete(actionId); },
    };
  }

  // Shared by the author portal and the reviewer screen: Bearer token, one Idempotency-Key
  // per user action (kept on network/5xx failures), typed errors from the server envelope.
  function createRequester(options) {
    const o = options || {};
    const base = (o.baseUrl || "").replace(/\/$/, "");
    const fetchImpl = o.fetchImpl || (typeof fetch !== "undefined" ? fetch.bind(globalThis) : null);
    const keys = createActionKeys();

    return async function request(method, path, body, actionId) {
      const token = await o.getIdToken();
      if (!token) throw new PortalError("UNAUTHENTICATED", "Sign in required.", 401);
      const headers = { Authorization: "Bearer " + token };
      if (body !== undefined) headers["Content-Type"] = "application/json";
      if (method === "POST") headers["Idempotency-Key"] = keys.keyFor(actionId || method + path);
      let res;
      try {
        res = await fetchImpl(base + path, { method, headers, body: body === undefined ? undefined : JSON.stringify(body) });
      } catch (_e) {
        throw new PortalError("NETWORK", "Could not reach the server. Try again.", 0);
      }
      let data = null;
      try { data = await res.json(); } catch (_e) { data = null; }
      if (!res.ok) {
        const err = data && data.error ? data.error : {};
        // A definitive answer (not a 5xx) ends the action: the next attempt is a new command.
        if (method === "POST" && res.status < 500) keys.done(actionId || method + path);
        throw new PortalError(err.code || "HTTP_" + res.status, err.message || "Request failed.", res.status, err);
      }
      if (method === "POST") keys.done(actionId || method + path);
      return data;
    };
  }

  function createPortalApi(options) {
    const request = createRequester(options);

    const enc = encodeURIComponent;
    const ver = (c, v) => "/api/authoring/packages/" + enc(c) + "/versions/" + enc(v);
    return {
      listPackages: () => request("GET", "/api/authoring/packages"),
      getPackage: (c, v) => request("GET", ver(c, v)),
      preview: (c, v) => request("GET", ver(c, v) + "/preview"),
      metrics: (c) => request("GET", "/api/authoring/courses/" + enc(c) + "/metrics"),
      upload: (pkg, actionId) => request("POST", "/api/authoring/packages", { package: pkg }, actionId),
      submit: (c, v) => request("POST", ver(c, v) + "/submit", {}, "submit:" + c + "@" + v),
    };
  }

  // Parse pasted/uploaded package JSON with a readable error (the server re-validates).
  function parsePackageText(text) {
    let raw;
    try { raw = JSON.parse(text); } catch (e) { return { ok: false, error: "Not valid JSON: " + e.message }; }
    if (!raw || typeof raw !== "object" || Array.isArray(raw)) return { ok: false, error: "A package is one JSON object." };
    return { ok: true, value: raw };
  }

  const STATUS_TEXT = {
    draft: "Draft — only your organization can see it",
    submitted: "Submitted — waiting for a platform reviewer",
    approved: "Approved — not yet live",
    active: "Active — students can enroll (with access)",
    superseded: "Superseded — serves sessions pinned to it",
    rejected: "Rejected — see reviewer notes",
    retired: "Retired — no new work",
  };

  return { createPortalApi, createRequester, createActionKeys, parsePackageText, PortalError, STATUS_TEXT };
});
