// Admins publish reviewer-approved courses for every student.
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
const A = HSAdminApi;
const API = A.createAdminApi({ baseUrl: API_BASE_URL, getIdToken: () => AUTH.getIdToken() });

const when = (at) => (at ? new Date(at).toLocaleString() : "—");
const INPUT = "rounded-lg ring-1 ring-slate-200 px-3 py-2 text-sm";

function AdminError({ error }) {
  return <ErrorNote error={error} text={error ? A.adminErrorText(error) : null} />;
}

function Publication({ version, onChanged }) {
  const [pending, setPending] = React.useState(null);
  const [notes, setNotes] = React.useState("");
  const [busy, setBusy] = React.useState(false);
  const [error, setError] = React.useState(null);
  const c = version.courseId, v = version.version;
  async function confirm() {
    setBusy(true); setError(null);
    try {
      if (pending === "publish") await API.publish(c, v);
      else await API.retire(c, notes.trim());
      setPending(null); await onChanged();
    } catch (err) { setError(err); } finally { setBusy(false); }
  }
  return (
    <article className={CARD + " p-4 space-y-3"}>
      <div className="flex items-center gap-2"><h2 className="font-semibold">{version.title || c}</h2><span className="text-xs">{c} · {v}</span><Badge status={version.status} /></div>
      {version.review && <p className="text-sm">Reviewed by {version.review.reviewerId} on {when(version.review.decidedAt)}. {version.review.notes}</p>}
      <Report report={version.report} />
      <div className="flex gap-2">{A.actionsFor(version.status).map((action) => (
        <button key={action} disabled={busy || !!pending} onClick={() => setPending(action)} className={BTN + " rounded-lg bg-slate-900 text-white px-4 py-2 text-sm disabled:opacity-40"}>
          {action === "publish" ? "Publish to catalog" : "Retire course"}
        </button>
      ))}</div>
      {pending && <div className="rounded-lg bg-amber-50 p-3 text-sm space-y-2">
        <p>{pending === "publish"
          ? "Publish " + c + " " + v + "? Every student can enroll. Any previous active version becomes superseded; open sessions retain their version."
          : "Retire " + c + "? New enrollments and learning activity stop for everyone. Past work stays readable."}</p>
        {pending === "retire" && <input aria-label="Reason for retirement" className={INPUT + " w-full"} maxLength={2000} placeholder="Reason (required)" value={notes} onChange={(e) => setNotes(e.target.value)} />}
        <button disabled={busy || (pending === "retire" && !notes.trim())} onClick={confirm} className={BTN + " rounded-lg bg-slate-900 text-white px-3 py-2 disabled:opacity-40"}>{busy ? "Saving…" : "Confirm"}</button>
        <button disabled={busy} onClick={() => setPending(null)} className="px-3 py-2">Cancel</button>
      </div>}
      <details><summary className="text-sm cursor-pointer">Publication history</summary><ul className="text-xs space-y-1 mt-2">{version.history.map((h, i) => <li key={i}>{when(h.at)}: {h.toStatus} by {h.actorId}{h.notes ? " — " + h.notes : ""}</li>)}</ul></details>
      <AdminError error={error} />
    </article>
  );
}

function AdminPortal({ onSignOut }) {
  const [versions, setVersions] = React.useState(null);
  const [error, setError] = React.useState(null);
  const load = React.useCallback(async () => {
    setError(null);
    try { const data = await API.queue(); setVersions(data.versions); }
    catch (err) { setError(err); }
  }, []);
  React.useEffect(() => { load(); }, [load]);
  return <main className="max-w-5xl mx-auto p-4 space-y-4">
    <header className="flex items-center justify-between"><h1 className="text-xl font-bold">Course publication</h1><button onClick={onSignOut} className="text-sm">Sign out</button></header>
    <p className="text-sm text-slate-600">Publish courses after reviewer approval. Every student can enroll in a published course.</p>
    <AdminError error={error} />
    <button onClick={load} className="text-sm underline">Refresh</button>
    {!versions && !error && <p>Loading…</p>}
    {versions && versions.length === 0 && <p>No reviewed courses awaiting publication or published courses yet.</p>}
    {(!error || error.code !== "FORBIDDEN") && versions && versions.map((v) => <Publication key={v.courseId + "@" + v.version} version={v} onChanged={load} />)}
  </main>;
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
  if (!uid) return <SignIn auth={AUTH} title="Course publication" onSignedIn={refresh} />;
  return <AdminPortal onSignOut={async () => { await AUTH.signOut(); refresh(); }} />;
}

ReactDOM.createRoot(document.getElementById("root")).render(<App />);
