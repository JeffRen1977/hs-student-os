// admin_portal.js — the course-access admin screen (Step 42). Platform admins find a
// student by ID, see their course access, enrollments and the access audit history, grant
// or revoke a course with a reason, and grant to a list of students at once. It never
// shows a student's answers, chats, assessments or mastery: the API does not return them.

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

function ChangeForm({ studentId, course, onDone, onCancel }) {
  const change = course.granted ? "revoke" : "grant";
  const [reason, setReason] = React.useState("");
  const [busy, setBusy] = React.useState(false);
  const [error, setError] = React.useState(null);
  async function confirm() {
    setBusy(true); setError(null);
    try {
      const fn = change === "grant" ? API.grant : API.revoke;
      onDone(await fn(studentId, course.courseId, reason.trim()), change);
    } catch (err) { setError(err); } finally { setBusy(false); }
  }
  const effect = change === "grant"
    ? "The student can enroll in " + course.name + " and practice."
    : "No new enrollment, sessions or submissions in " + course.name + ". Past work stays readable; an open session can still be abandoned.";
  return (
    <div className="mt-2 rounded-lg bg-amber-50 ring-1 ring-amber-200 p-3 text-sm">
      <div className="font-semibold">{change === "grant" ? "Grant" : "Revoke"} {course.name} for {studentId}?</div>
      <div className="text-xs text-slate-600 mt-1">{effect} The change and your reason are recorded in the audit history; the student sees only that access changed.</div>
      <input className={INPUT + " w-full mt-2"} maxLength={500} placeholder="Reason (required)" value={reason} onChange={(e) => setReason(e.target.value)} />
      <div className="mt-2 flex gap-2">
        <button disabled={busy || !reason.trim()} onClick={confirm} className={BTN + " rounded-lg bg-slate-900 text-white px-3 py-1.5 disabled:opacity-40"}>{busy ? "Saving…" : "Confirm"}</button>
        <button disabled={busy} onClick={onCancel} className="rounded-lg ring-1 ring-slate-300 px-3 py-1.5">Cancel</button>
      </div>
      <AdminError error={error} />
    </div>
  );
}

function StudentAccess({ view, onChanged }) {
  const [editing, setEditing] = React.useState(null);
  const [note, setNote] = React.useState(null);
  React.useEffect(() => { setEditing(null); setNote(null); }, [view.studentId]);
  const a = view.access;
  return (
    <div className={CARD + " p-4"}>
      <div className="flex flex-wrap items-baseline gap-2">
        <h2 className="font-semibold">{view.displayName}</h2>
        <span className="text-xs text-slate-500">{view.studentId}</span>
      </div>
      <div className="text-xs text-slate-500 mt-1">Access record last changed {when(a.updatedAt)} by {a.updatedBy || "—"}</div>
      {note && <div className="mt-2 rounded-lg bg-emerald-50 text-emerald-800 text-sm p-2">{note}</div>}
      <table className="mt-3 w-full text-sm">
        <thead><tr className="text-left text-xs text-slate-500"><th className="py-1">Course</th><th>Status</th><th>Access</th><th>Enrollment</th><th></th></tr></thead>
        <tbody>{view.courses.map((c) => (
          <React.Fragment key={c.courseId}>
            <tr className="border-t border-slate-100">
              <td className="py-1.5">{c.name} <span className="text-xs text-slate-500">{c.courseId} · {c.category}</span></td>
              <td className="text-xs">{c.availability}</td>
              <td>{c.granted ? <span className="text-emerald-700 font-semibold">granted</span> : <span className="text-slate-400">none</span>}</td>
              <td className="text-xs">{c.enrollment ? c.enrollment.status + (c.enrollment.enrolledAt ? " since " + new Date(c.enrollment.enrolledAt).toLocaleDateString() : "") : "—"}</td>
              <td className="text-right">
                <button disabled={!!editing} onClick={() => { setNote(null); setEditing(c.courseId); }}
                  className={"rounded-lg px-3 py-1 text-xs ring-1 disabled:opacity-40 " + (c.granted ? "ring-rose-300 text-rose-700" : "ring-emerald-300 text-emerald-700")}>
                  {c.granted ? "Revoke" : "Grant"}</button>
              </td>
            </tr>
            {editing === c.courseId && (
              <tr><td colSpan={5}>
                <ChangeForm studentId={view.studentId} course={c} onCancel={() => setEditing(null)}
                  onDone={(r, change) => { setEditing(null); setNote(A.changeText(r, change)); onChanged(r.access); }} />
              </td></tr>
            )}
          </React.Fragment>
        ))}</tbody>
      </table>
      <h3 className="font-semibold text-sm mt-5">Access history</h3>
      {view.audit.length === 0 ? <p className="text-xs text-slate-500 mt-1">No changes made with this tool yet.</p> : (
        <table className="mt-1 w-full text-xs">
          <thead><tr className="text-left text-slate-500"><th className="py-1">When</th><th>Change</th><th>Course</th><th>By</th><th>Reason</th></tr></thead>
          <tbody>{view.audit.map((x) => (
            <tr key={x.auditId} className="border-t border-slate-100">
              <td className="py-1">{when(x.at)}</td><td>{x.change}</td><td>{x.courseId}</td><td>{x.actorId}</td><td>{x.reason}</td>
            </tr>
          ))}</tbody>
        </table>
      )}
    </div>
  );
}

function Bulk({ courses }) {
  const [text, setText] = React.useState("");
  const [courseId, setCourseId] = React.useState("");
  const [change, setChange] = React.useState("grant");
  const [reason, setReason] = React.useState("");
  const [pending, setPending] = React.useState(false);
  const [busy, setBusy] = React.useState(false);
  const [result, setResult] = React.useState(null);
  const [error, setError] = React.useState(null);
  const parsed = A.parseStudentIds(text);
  const ready = parsed.ok && /^[a-z][a-z0-9_]{1,31}$/.test(courseId) && reason.trim();
  async function run() {
    setBusy(true); setError(null);
    try { setResult(await API.bulk({ studentIds: parsed.ids, courseId, change, reason: reason.trim() })); setPending(false); }
    catch (err) { setError(err); setPending(false); } finally { setBusy(false); }
  }
  return (
    <div className={CARD + " p-4"}>
      <h2 className="font-semibold text-sm">Class or cohort</h2>
      <p className="text-xs text-slate-500 mt-1">One course for many students. Each student is changed and audited separately; one failure does not stop the others.</p>
      <textarea className={INPUT + " w-full h-24 mt-2 font-mono text-xs"} placeholder={"stu_beth\nstu_alex"} value={text} onChange={(e) => { setText(e.target.value); setResult(null); }} />
      <div className="text-xs text-slate-500">{parsed.ids.length} student(s)
        {parsed.invalid.length > 0 && <span className="text-rose-700"> · not valid ids: {parsed.invalid.join(", ")}</span>}
        {parsed.tooMany && <span className="text-rose-700"> · at most {A.MAX_BULK} per request</span>}</div>
      <div className="mt-2 flex flex-wrap gap-2 items-center text-sm">
        <select className={INPUT} value={change} onChange={(e) => setChange(e.target.value)}>
          <option value="grant">Grant</option><option value="revoke">Revoke</option>
        </select>
        <input className={INPUT + " w-40"} list="admin-courses" placeholder="courseId" value={courseId} onChange={(e) => setCourseId(e.target.value.trim())} />
        <datalist id="admin-courses">{courses.map((c) => <option key={c.courseId} value={c.courseId}>{c.name}</option>)}</datalist>
      </div>
      <input className={INPUT + " w-full mt-2"} maxLength={500} placeholder="Reason (required)" value={reason} onChange={(e) => setReason(e.target.value)} />
      {!pending ? (
        <button disabled={!ready || busy} onClick={() => { setError(null); setPending(true); }}
          className={BTN + " mt-2 rounded-lg bg-slate-900 text-white px-4 py-2 text-sm disabled:opacity-40"}>Review…</button>
      ) : (
        <div className="mt-2 rounded-lg bg-amber-50 ring-1 ring-amber-200 p-3 text-sm">
          <div>{change === "grant" ? "Grant" : "Revoke"} <b>{courseId}</b> for {parsed.ids.length} student(s)?</div>
          <div className="mt-2 flex gap-2">
            <button disabled={busy} onClick={run} className={BTN + " rounded-lg bg-slate-900 text-white px-3 py-1.5 disabled:opacity-40"}>{busy ? "Working…" : "Confirm"}</button>
            <button disabled={busy} onClick={() => setPending(false)} className="rounded-lg ring-1 ring-slate-300 px-3 py-1.5">Cancel</button>
          </div>
        </div>
      )}
      <AdminError error={error} />
      {result && (
        <div className="mt-3 text-sm">
          <div className="font-semibold">{result.changed} changed · {result.unchanged} unchanged · {result.failed} failed</div>
          <ul className="mt-1 text-xs space-y-0.5">{result.results.map((r) => (
            <li key={r.studentId} className={r.status === "failed" ? "text-rose-700" : ""}>{r.studentId}: {r.status}{r.status === "failed" ? " — " + A.adminErrorText({ code: r.errorCode, message: r.message }) : ""}</li>
          ))}</ul>
        </div>
      )}
    </div>
  );
}

function AdminPortal({ onSignOut }) {
  const [query, setQuery] = React.useState("");
  const [view, setView] = React.useState(null);
  const [courses, setCourses] = React.useState([]);
  const [error, setError] = React.useState(null);
  const [busy, setBusy] = React.useState(false);
  async function open(e) {
    if (e) e.preventDefault();
    const sid = query.trim();
    if (!sid) return;
    setBusy(true); setError(null);
    try { const v = await API.getAccess(sid); setView(v); setCourses(v.courses); }
    catch (err) { setError(err); setView(null); } finally { setBusy(false); }
  }
  const notAdmin = error && error.code === "FORBIDDEN";
  return (
    <div className="max-w-5xl mx-auto p-4">
      <header className="flex items-center justify-between">
        <h1 className="text-xl font-bold">Course access</h1>
        <div className="flex items-center gap-4">
          <span className="text-xs text-slate-500">{AUTH.currentUid()}</span>
          <button className="text-sm text-slate-500" onClick={onSignOut}>Sign out</button>
        </div>
      </header>
      {notAdmin ? (
        <div className={CARD + " p-6 mt-6 text-sm"}>This account is not a platform admin. Course access is managed by platform admins only.</div>
      ) : (
        <div className="mt-4 grid grid-cols-1 md:grid-cols-[minmax(0,1fr)_320px] gap-4">
          <div className="space-y-4">
            <form onSubmit={open} className={CARD + " p-4 flex flex-wrap gap-2 items-center"}>
              <input className={INPUT + " flex-1 min-w-[180px]"} placeholder="Student ID, e.g. stu_beth" value={query} onChange={(e) => setQuery(e.target.value)} />
              <button disabled={busy || !query.trim()} className={BTN + " rounded-lg bg-slate-900 text-white px-4 py-2 text-sm disabled:opacity-40"}>{busy ? "Loading…" : "Open"}</button>
              <AdminError error={error} />
            </form>
            {view && <StudentAccess view={view} onChanged={(v) => { setView(v); setCourses(v.courses); }} />}
          </div>
          <Bulk courses={courses} />
        </div>
      )}
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
  if (!uid) return <SignIn auth={AUTH} title="Course access" onSignedIn={refresh} />;
  return <AdminPortal onSignOut={async () => { await AUTH.signOut(); refresh(); }} />;
}

ReactDOM.createRoot(document.getElementById("root")).render(<App />);
