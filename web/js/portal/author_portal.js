// author_portal.js — the author portal UI (Step 34.1). Authors see only their organization's
// packages. Publishing still goes through the platform reviewer: this page can upload and
// submit, never approve or activate.

const API_BASE_URL = window.HS_API_BASE_URL || "http://localhost:8787";
const AUTH = HSAuth.createAuth({
  hostname: window.location.hostname,
  apiBaseUrl: API_BASE_URL,
  firebaseConfig: window.HS_FIREBASE_CONFIG || null,
  projectId: window.HS_FIREBASE_PROJECT || "demo-hs-student-os",
  storage: typeof sessionStorage !== "undefined" ? sessionStorage : null,
  localUsers: HSAuth.SYNTHETIC_PLATFORM_MEMBERS,
  storageKey: "hsos.portalUid",
});
const API = HSPortalApi.createPortalApi({ baseUrl: API_BASE_URL, getIdToken: () => AUTH.getIdToken() });

function Upload({ onUploaded }) {
  const [text, setText] = React.useState("");
  const [busy, setBusy] = React.useState(false);
  const [error, setError] = React.useState(null);
  const action = React.useRef("upload-" + Date.now());
  async function upload() {
    const parsed = HSPortalApi.parsePackageText(text);
    if (!parsed.ok) { setError({ message: parsed.error }); return; }
    setBusy(true); setError(null);
    try {
      const v = await API.upload(parsed.value, action.current);
      action.current = "upload-" + Date.now();
      setText("");
      onUploaded(v);
    } catch (err) { setError(err); } finally { setBusy(false); }
  }
  return (
    <div className={CARD + " p-4"}>
      <h2 className="font-semibold">Upload a package version</h2>
      <p className="text-xs text-slate-500 mt-1">Course package contract v1 (doc/COURSE_PACKAGE.md). A draft can be replaced until you submit it.</p>
      <input type="file" accept="application/json" className="mt-3 text-sm" onChange={async (e) => {
        const f = e.target.files && e.target.files[0]; if (f) setText(await f.text());
      }} />
      <textarea className="mt-2 w-full h-32 font-mono text-xs rounded-lg ring-1 ring-slate-200 p-2" placeholder='{"schemaVersion": "course-package/v1", ...}'
        value={text} onChange={(e) => setText(e.target.value)} />
      <button disabled={busy || !text.trim()} className={BTN + " mt-2 rounded-lg bg-slate-900 text-white px-4 py-2 text-sm disabled:opacity-40"} onClick={upload}>
        {busy ? "Validating…" : "Upload and validate"}
      </button>
      <ErrorNote error={error} />
    </div>
  );
}

function Metrics({ metrics }) {
  if (metrics.suppressed) {
    return <p className="text-sm text-slate-600">Fewer than {metrics.minimumCohort} students have work in this course, so no metrics are shown. Metrics are aggregates only and never identify a student.</p>;
  }
  return (
    <div className="text-sm space-y-2">
      <div>{metrics.students} students · {metrics.assessments} assessments · {Object.entries(metrics.byStatus).map(([k, v]) => k + ": " + v).join(", ")}</div>
      <table className="text-xs w-full">
        <thead><tr className="text-left text-slate-500"><th>Rubric</th><th>Criterion</th><th>Scored</th><th>Avg earned / max</th></tr></thead>
        <tbody>{metrics.criteria.map((c) => (
          <tr key={c.rubricId + c.criterionId}><td>{c.rubricId}</td><td>{c.criterionId}</td><td>{c.count}</td><td>{c.averageEarned} / {c.maxPoints}</td></tr>
        ))}</tbody>
      </table>
    </div>
  );
}

function Detail({ summary, onChanged }) {
  const [tab, setTab] = React.useState("report");
  const [extra, setExtra] = React.useState({});
  const [error, setError] = React.useState(null);
  const [busy, setBusy] = React.useState(false);
  const key = summary.courseId + "@" + summary.version;
  React.useEffect(() => { setTab("report"); setExtra({}); setError(null); }, [key]);
  async function open(t) {
    setTab(t); setError(null);
    try {
      if (t === "preview" && !extra.preview) setExtra((x) => ({ ...x, preview: null }));
      if (t === "preview") { const p = await API.preview(summary.courseId, summary.version); setExtra((x) => ({ ...x, preview: p })); }
      if (t === "metrics") { const m = await API.metrics(summary.courseId); setExtra((x) => ({ ...x, metrics: m })); }
    } catch (err) { setError(err); }
  }
  async function submit() {
    setBusy(true); setError(null);
    try { await API.submit(summary.courseId, summary.version); onChanged(); } catch (err) { setError(err); } finally { setBusy(false); }
  }
  const reviewNotes = summary.history.filter((h) => h.notes && h.actorId !== summary.uploadedBy);
  return (
    <div className={CARD + " p-4"}>
      <div className="flex items-center gap-2">
        <h2 className="font-semibold">{summary.title || summary.courseId}</h2>
        <span className="text-xs text-slate-500">{summary.courseId} v{summary.version}</span>
        <Badge status={summary.status} />
      </div>
      <p className="text-xs text-slate-500 mt-1">{HSPortalApi.STATUS_TEXT[summary.status]}</p>
      {summary.status === "draft" && (
        <button disabled={busy || !summary.report.valid} onClick={submit}
          className={BTN + " mt-3 rounded-lg bg-indigo-600 text-white px-4 py-2 text-sm disabled:opacity-40"}>
          Submit for platform review
        </button>
      )}
      {reviewNotes.length > 0 && (
        <div className="mt-3 rounded-lg bg-amber-50 p-3 text-sm">
          <div className="font-semibold text-xs">Reviewer notes</div>
          {reviewNotes.map((h, i) => <div key={i}>{h.toStatus}: {h.notes}</div>)}
        </div>
      )}
      <div className="mt-4 flex gap-2 text-sm">
        {["report", "preview", "history", "metrics"].map((t) => (
          <button key={t} onClick={() => open(t)} className={"px-3 py-1 rounded-full " + (tab === t ? "bg-slate-900 text-white" : "ring-1 ring-slate-200")}>{t}</button>
        ))}
      </div>
      <div className="mt-3">
        {tab === "report" && <Report report={summary.report} />}
        {tab === "preview" && (extra.preview ? <Preview preview={extra.preview} /> : !error && <p className="text-sm">Loading…</p>)}
        {tab === "metrics" && (extra.metrics ? <Metrics metrics={extra.metrics} /> : !error && <p className="text-sm">Loading…</p>)}
        {tab === "history" && (
          <ul className="text-sm space-y-1">{summary.history.map((h, i) => (
            <li key={i}>{new Date(h.at).toLocaleString()}: {h.fromStatus || "—"} → <b>{h.toStatus}</b> by {h.actorId}{h.notes ? " — " + h.notes : ""}</li>
          ))}</ul>
        )}
      </div>
      <ErrorNote error={error} />
    </div>
  );
}

function Portal({ onSignOut }) {
  const [versions, setVersions] = React.useState(null);
  const [selected, setSelected] = React.useState(null);
  const [error, setError] = React.useState(null);
  const load = React.useCallback(async () => {
    setError(null);
    try { const r = await API.listPackages(); setVersions(r.versions); } catch (err) { setError(err); setVersions([]); }
  }, []);
  React.useEffect(() => { load(); }, [load]);
  const current = versions && selected ? versions.find((v) => v.courseId + "@" + v.version === selected) : null;
  return (
    <div className="max-w-6xl mx-auto p-4">
      <header className="flex items-center justify-between">
        <h1 className="text-xl font-bold">Author portal</h1>
        <div className="flex items-center gap-4">
          <a className="text-sm text-slate-500" href="review.html">Reviewer screen</a>
          <button className="text-sm text-slate-500" onClick={onSignOut}>Sign out</button>
        </div>
      </header>
      {error && error.status === 403 && <ErrorNote error={{ message: "This account is not a course author." }} />}
      {error && error.status !== 403 && <ErrorNote error={error} />}
      <div className="mt-4 grid grid-cols-1 md:grid-cols-[320px_minmax(0,1fr)] gap-4">
        <div className="space-y-4">
          <Upload onUploaded={(v) => { load(); setSelected(v.courseId + "@" + v.version); }} />
          <div className={CARD + " p-4"}>
            <h2 className="font-semibold">Your organization's packages</h2>
            {versions === null ? <p className="text-sm mt-2">Loading…</p> : versions.length === 0
              ? <p className="text-sm text-slate-500 mt-2">No packages yet.</p>
              : <ul className="mt-2 space-y-1">{versions.map((v) => {
                  const id = v.courseId + "@" + v.version;
                  return (
                    <li key={id}><button onClick={() => setSelected(id)} className={"w-full text-left px-2 py-1 rounded " + (selected === id ? "bg-slate-100" : "")}>
                      <span className="text-sm">{v.courseId} v{v.version}</span> <Badge status={v.status} />
                    </button></li>
                  );
                })}</ul>}
          </div>
        </div>
        <div>{current ? <Detail summary={current} onChanged={load} /> : <p className="text-sm text-slate-500">Select a package version.</p>}</div>
      </div>
    </div>
  );
}

function App() {
  const [uid, setUid] = React.useState(null);
  const [ready, setReady] = React.useState(false);
  const refresh = React.useCallback(async () => {
    await AUTH.getIdToken().catch(() => null);
    setUid(AUTH.currentUid()); setReady(true);
  }, []);
  React.useEffect(() => { refresh(); }, [refresh]);
  if (!ready) return null;
  if (!uid) return <SignIn auth={AUTH} title="Author portal" onSignedIn={refresh} />;
  return <Portal onSignOut={async () => { await AUTH.signOut(); refresh(); }} />;
}

ReactDOM.createRoot(document.getElementById("root")).render(<App />);
