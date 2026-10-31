// data-provider.js — the async data-provider seam between the UI and the backend API
// (doc/API.md v0.3). Plain JavaScript (no JSX) so it runs in the browser as
// `window.HSProvider` and in Node for tests (`node --test web/tests/`).
//
// Rules this module enforces:
// - Demo data is used ONLY when the page is opened with `?demo=true`.
// - API failures surface as typed errors. They never fall back to demo data.
// - The browser sends commands/answers only; it never fabricates events, scores, or
//   mastery. Events come from the server and are de-duplicated by eventId/sequence.
(function (root, factory) {
  const api = factory();
  if (typeof module === "object" && module.exports) module.exports = api;
  else root.HSProvider = api;
})(typeof self !== "undefined" ? self : this, function () {
  "use strict";

  // ---- Request state ----------------------------------------------------------------

  const RequestStatus = Object.freeze({
    IDLE: "idle",
    LOADING: "loading",
    SUCCESS: "success",
    ERROR: "error",
  });

  function idle() { return { status: RequestStatus.IDLE, data: null, error: null }; }
  // Keeps the last good data while reloading so the UI does not flash empty.
  function loading(prev) {
    return { status: RequestStatus.LOADING, data: prev ? prev.data : null, error: null };
  }
  function success(data) { return { status: RequestStatus.SUCCESS, data: data, error: null }; }
  function failure(error, prev) {
    return { status: RequestStatus.ERROR, data: prev ? prev.data : null, error: toApiError(error) };
  }

  // ---- Errors -----------------------------------------------------------------------

  const ClientErrorCode = Object.freeze({
    NOT_CONNECTED: "NOT_CONNECTED", // network failure / backend not running
    NOT_SIGNED_IN: "NOT_SIGNED_IN", // no ID token available (auth lands in M1 Step 8)
    BAD_RESPONSE: "BAD_RESPONSE", // non-JSON or malformed response
  });

  class ApiError extends Error {
    constructor(code, message, options) {
      super(message);
      const o = options || {};
      this.name = "ApiError";
      this.code = code;
      this.status = o.status == null ? null : o.status;
      this.retryable = !!o.retryable;
      this.requestId = o.requestId || null;
    }
  }

  function toApiError(error) {
    if (error instanceof ApiError) return error;
    return new ApiError(ClientErrorCode.NOT_CONNECTED, (error && error.message) || "Request failed", { retryable: true });
  }

  // ---- Demo flag --------------------------------------------------------------------

  function isDemoMode(search) {
    try {
      return new URLSearchParams(search || "").get("demo") === "true";
    } catch (_e) {
      return false;
    }
  }

  // ---- Idempotency keys -------------------------------------------------------------

  const IDEMPOTENCY_KEY_PATTERN = /^[A-Za-z0-9_-]{16,128}$/;

  function newIdempotencyKey() {
    const c = typeof crypto !== "undefined" ? crypto : null;
    if (c && typeof c.randomUUID === "function") return "idk_" + c.randomUUID().replace(/-/g, "");
    let hex = "";
    for (let i = 0; i < 32; i++) hex += Math.floor(Math.random() * 16).toString(16);
    return "idk_" + hex;
  }

  // One key per *user action*: retries of the same action reuse the key, so the server
  // returns the original result instead of applying the command twice. Release the key
  // once the action has a definitive server response.
  function createActionKeys(generate) {
    const gen = generate || newIdempotencyKey;
    const keys = new Map();
    return {
      keyFor: function (actionId) {
        if (!keys.has(actionId)) keys.set(actionId, gen());
        return keys.get(actionId);
      },
      release: function (actionId) { keys.delete(actionId); },
      has: function (actionId) { return keys.has(actionId); },
    };
  }

  // ---- Events -----------------------------------------------------------------------

  // Merge server events into a log: dedupe by eventId AND sequence, keep ascending
  // sequence order, and track the last applied sequence for `GET /api/events?after=`.
  function mergeEvents(log, incoming) {
    const current = log || { events: [], lastSequence: 0 };
    const byId = new Set(current.events.map(function (e) { return e.eventId; }));
    const bySeq = new Set(current.events.map(function (e) { return e.sequence; }));
    const merged = current.events.slice();
    (incoming || []).forEach(function (e) {
      if (!e || typeof e.sequence !== "number" || !e.eventId) return;
      if (byId.has(e.eventId) || bySeq.has(e.sequence)) return;
      byId.add(e.eventId);
      bySeq.add(e.sequence);
      merged.push(e);
    });
    merged.sort(function (a, b) { return a.sequence - b.sequence; });
    const last = merged.length ? merged[merged.length - 1].sequence : 0;
    return { events: merged, lastSequence: Math.max(current.lastSequence, last) };
  }

  // ---- Local drafts -----------------------------------------------------------------

  // Drafts are local-only. They are never described as sent, saved, or assessed.
  function memoryStorage() {
    const m = new Map();
    return {
      getItem: function (k) { return m.has(k) ? m.get(k) : null; },
      setItem: function (k, v) { m.set(k, String(v)); },
      removeItem: function (k) { m.delete(k); },
    };
  }

  function createDraftStore(storage, now) {
    const s = storage || memoryStorage();
    const clock = now || function () { return new Date().toISOString(); };
    const prefix = "hsos.draft.";
    return {
      load: function (key) {
        try {
          const raw = s.getItem(prefix + key);
          return raw ? JSON.parse(raw) : null;
        } catch (_e) {
          return null;
        }
      },
      save: function (key, text) {
        if (!text) { s.removeItem(prefix + key); return null; }
        const draft = { text: text, savedAt: clock(), status: "local_draft" };
        s.setItem(prefix + key, JSON.stringify(draft));
        return draft;
      },
      clear: function (key) { s.removeItem(prefix + key); },
    };
  }

  // ---- Display helpers ---------------------------------------------------------------

  const RUN_STATUS_VIEW = Object.freeze({
    QUEUED: { label: "排队中", tone: "slate", terminal: false },
    RUNNING: { label: "批改中", tone: "indigo", terminal: false },
    WAITING_INPUT: { label: "等待你确认", tone: "amber", terminal: false },
    // SUCCEEDED means the execution finished; it does NOT mean the task is complete.
    SUCCEEDED: { label: "执行完成", tone: "emerald", terminal: true },
    FAILED: { label: "失败", tone: "rose", terminal: true },
    CANCELLED: { label: "已取消", tone: "slate", terminal: true },
  });

  function describeRun(run) {
    if (!run) return null;
    const view = RUN_STATUS_VIEW[run.status];
    if (!view) return { label: "未知状态", tone: "slate", terminal: false, retryable: false };
    return {
      label: view.label,
      tone: view.tone,
      terminal: view.terminal,
      retryable: run.status === "FAILED" && !!(run.error && run.error.retryable),
    };
  }

  function predictionLabel(entry) {
    if (!entry || entry.status === "unavailable") return "暂无预测（未校准）";
    return "暂无预测";
  }

  // ---- Providers --------------------------------------------------------------------

  function buildQuery(params) {
    const parts = [];
    Object.keys(params || {}).forEach(function (k) {
      const v = params[k];
      if (v !== undefined && v !== null && v !== "") parts.push(encodeURIComponent(k) + "=" + encodeURIComponent(v));
    });
    return parts.length ? "?" + parts.join("&") : "";
  }

  function createApiProvider(options) {
    const o = options || {};
    const baseUrl = (o.baseUrl || "http://localhost:8787").replace(/\/$/, "");
    const fetchImpl = o.fetchImpl || (typeof fetch !== "undefined" ? fetch.bind(globalThis) : null);
    const getIdToken = o.getIdToken || function () { return Promise.resolve(null); };

    async function request(path, opts) {
      const r = opts || {};
      const token = await getIdToken();
      if (!token) throw new ApiError(ClientErrorCode.NOT_SIGNED_IN, "Sign-in is required", { retryable: false });
      const headers = { Accept: "application/json", Authorization: "Bearer " + token };
      if (r.body !== undefined) headers["Content-Type"] = "application/json";
      if (r.idempotencyKey) {
        if (!IDEMPOTENCY_KEY_PATTERN.test(r.idempotencyKey)) throw new Error("invalid Idempotency-Key");
        headers["Idempotency-Key"] = r.idempotencyKey;
      }
      if (r.ifMatch != null) headers["If-Match"] = '"' + r.ifMatch + '"';

      let response;
      try {
        response = await fetchImpl(baseUrl + path, {
          method: r.method || "GET",
          headers: headers,
          body: r.body === undefined ? undefined : JSON.stringify(r.body),
        });
      } catch (e) {
        throw new ApiError(ClientErrorCode.NOT_CONNECTED, "Cannot reach the Student OS server", { retryable: true });
      }

      let payload = null;
      try {
        payload = await response.json();
      } catch (_e) {
        payload = null;
      }
      if (!response.ok) {
        const err = payload && payload.error;
        if (err && err.code) {
          throw new ApiError(err.code, err.message || err.code, {
            status: response.status, retryable: !!err.retryable, requestId: err.requestId,
          });
        }
        throw new ApiError(ClientErrorCode.BAD_RESPONSE, "Unexpected response " + response.status, {
          status: response.status, retryable: response.status >= 500,
        });
      }
      if (payload === null) throw new ApiError(ClientErrorCode.BAD_RESPONSE, "Response was not JSON", { status: response.status });
      return payload;
    }

    return {
      mode: "api",
      request: request,
      fetchTwin: function () { return request("/api/twin"); },
      fetchEntitlements: function () { return request("/api/me/entitlements"); },
      fetchPacks: function () { return request("/api/packs"); },
      fetchCatalog: function () { return request("/api/courses/catalog"); },
      fetchTasks: function (params) { return request("/api/tasks" + buildQuery(params)); },
      fetchSessions: function (params) { return request("/api/sessions" + buildQuery(params)); },
      fetchSession: function (sessionId) { return request("/api/sessions/" + encodeURIComponent(sessionId)); },
      fetchRun: function (runId) { return request("/api/runs/" + encodeURIComponent(runId)); },
      fetchEvents: function (afterSequence, limit) {
        return request("/api/events" + buildQuery({ after: afterSequence || 0, limit: limit }));
      },
      // Product previews exist only in demo mode.
      fetchPreviews: function () { return Promise.resolve([]); },
    };
  }

  function clone(value) { return JSON.parse(JSON.stringify(value)); }

  // `loadFixtures` returns a Promise of the parsed web/fixtures/demo.json document.
  function createDemoProvider(loadFixtures) {
    let cached = null;
    function data() {
      if (!cached) cached = Promise.resolve(loadFixtures());
      return cached.then(clone);
    }
    function notFound(what) {
      return new ApiError("NOT_FOUND", what + " not found", { status: 404 });
    }
    return {
      mode: "demo",
      fetchTwin: function () { return data().then(function (d) { return d.twin; }); },
      fetchEntitlements: function () { return data().then(function (d) { return d.entitlements; }); },
      fetchPacks: function () { return data().then(function (d) { return { packs: d.packs || [] }; }); },
      fetchCatalog: function () { return data().then(function (d) { return d.catalog; }); },
      fetchTasks: function () { return data().then(function (d) { return d.tasks; }); },
      fetchSessions: function () { return data().then(function (d) { return d.sessions; }); },
      fetchSession: function (sessionId) {
        return data().then(function (d) {
          const s = d.sessions.sessions.find(function (x) { return x.sessionId === sessionId; });
          if (!s) throw notFound("Session");
          return s;
        });
      },
      fetchRun: function (runId) {
        return data().then(function (d) {
          const r = d.runs.find(function (x) { return x.runId === runId; });
          if (!r) throw notFound("Run");
          return r;
        });
      },
      fetchEvents: function (afterSequence) {
        return data().then(function (d) {
          const events = d.events.events.filter(function (e) { return e.sequence > (afterSequence || 0); });
          return { events: events, nextAfter: d.events.nextAfter, hasMore: false };
        });
      },
      fetchPreviews: function () { return data().then(function (d) { return d.previews || []; }); },
    };
  }

  // Picks the provider. There is deliberately no fallback from api → demo.
  function createProvider(options) {
    const o = options || {};
    if (isDemoMode(o.search)) {
      if (!o.loadDemoFixtures) throw new Error("demo mode requires loadDemoFixtures");
      return createDemoProvider(o.loadDemoFixtures);
    }
    return createApiProvider(o);
  }

  // Startup sequence from API.md §5: Twin, entitlements, catalog and tasks in parallel,
  // then sessions/runs for recovery, then recent events after the Twin snapshot.
  async function bootstrap(provider) {
    const results = await Promise.all([
      provider.fetchTwin(),
      provider.fetchEntitlements(),
      provider.fetchCatalog(),
      provider.fetchTasks(),
      provider.fetchSessions(),
      provider.fetchPreviews(),
    ]);
    const twin = results[0];
    const sessions = results[4].sessions || [];
    const after = Math.max(0, (twin.latestEventSequence || 0) - 20);
    const eventPage = await provider.fetchEvents(after, 50);
    const eventLog = mergeEvents({ events: [], lastSequence: after }, eventPage.events);
    const sessionRunIds = latestRunBySession(sessions, eventLog.events);
    const runIds = Object.keys(sessionRunIds).map(function (k) { return sessionRunIds[k]; });
    const runs = await Promise.all(runIds.map(function (id) { return provider.fetchRun(id); }));
    return {
      mode: provider.mode,
      twin: twin,
      entitlements: results[1],
      catalog: results[2].courses || [],
      tasks: results[3].tasks || [],
      sessions: sessions,
      runs: runs,
      sessionRunIds: sessionRunIds,
      eventLog: eventLog,
      previews: results[5] || [],
    };
  }

  // The Run to show for each open Session: its active Run if any, otherwise the most
  // recent Run seen in run.* events (e.g. a FAILED run the student may retry).
  function latestRunBySession(sessions, events) {
    const out = {};
    (events || []).forEach(function (e) {
      if (e.sessionId && e.runId && String(e.type).indexOf("run.") === 0) out[e.sessionId] = e.runId;
    });
    const result = {};
    (sessions || []).forEach(function (s) {
      const id = s.activeRunId || out[s.sessionId];
      if (id) result[s.sessionId] = id;
    });
    return result;
  }

  // Which screen the app should render for a bootstrap request state.
  function deriveScreen(state) {
    if (!state || state.status === RequestStatus.IDLE || state.status === RequestStatus.LOADING) {
      return state && state.data ? "ready" : "loading";
    }
    if (state.status === RequestStatus.SUCCESS) return "ready";
    const code = state.error && state.error.code;
    if (code === ClientErrorCode.NOT_CONNECTED) return "not_connected";
    if (code === ClientErrorCode.NOT_SIGNED_IN || code === "UNAUTHENTICATED") return "not_signed_in";
    return "error";
  }

  return {
    RequestStatus: RequestStatus,
    ClientErrorCode: ClientErrorCode,
    ApiError: ApiError,
    IDEMPOTENCY_KEY_PATTERN: IDEMPOTENCY_KEY_PATTERN,
    idle: idle,
    loading: loading,
    success: success,
    failure: failure,
    isDemoMode: isDemoMode,
    newIdempotencyKey: newIdempotencyKey,
    createActionKeys: createActionKeys,
    mergeEvents: mergeEvents,
    createDraftStore: createDraftStore,
    memoryStorage: memoryStorage,
    describeRun: describeRun,
    predictionLabel: predictionLabel,
    createApiProvider: createApiProvider,
    createDemoProvider: createDemoProvider,
    createProvider: createProvider,
    bootstrap: bootstrap,
    latestRunBySession: latestRunBySession,
    deriveScreen: deriveScreen,
  };
});
