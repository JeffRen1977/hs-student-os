// portal_ui.js — React components shared by the author portal (author.html) and the
// reviewer screen (review.html): status badge, error note, sign-in, validator report and the
// student-view preview. Loaded before each page's own script (text/babel, in order).

const STATUS_COLOR = {
  draft: "bg-slate-100 text-slate-700", submitted: "bg-amber-100 text-amber-800",
  approved: "bg-sky-100 text-sky-800", active: "bg-emerald-100 text-emerald-800",
  superseded: "bg-slate-100 text-slate-500", rejected: "bg-rose-100 text-rose-800",
  retired: "bg-slate-200 text-slate-600",
};

function Badge({ status }) {
  return <span className={"px-2 py-0.5 rounded-full text-xs font-semibold " + (STATUS_COLOR[status] || "")}>{status}</span>;
}

// `text` replaces the server message with plain language (the reviewer screen); the code
// stays visible for support.
function ErrorNote({ error, text }) {
  if (!error) return null;
  return <div className="mt-3 rounded-lg bg-rose-50 text-rose-800 text-sm p-3">{text || error.message || String(error)}{error.code ? " (" + error.code + ")" : ""}</div>;
}

function SignIn({ auth, title, onSignedIn }) {
  const [email, setEmail] = React.useState("");
  const [password, setPassword] = React.useState("");
  const [error, setError] = React.useState(null);
  if (auth.mode === "local_emulator") {
    return (
      <div className={CARD + " p-6 max-w-md mx-auto mt-16"}>
        <h1 className="text-lg font-bold">{title} — local sign-in</h1>
        <p className="text-sm text-slate-500 mt-1">Synthetic accounts only (emulator-format tokens; deployed servers reject them).</p>
        <div className="mt-4 space-y-2">
          {auth.students.map((u) => (
            <button key={u.uid} className={BTN + " w-full text-left px-4 py-2 rounded-lg ring-1 ring-slate-200 hover:bg-slate-50"}
              onClick={() => { auth.signInLocal(u.uid); onSignedIn(); }}>{u.label}</button>
          ))}
        </div>
      </div>
    );
  }
  if (auth.mode !== "firebase") return <div className="p-8 text-center text-slate-500">Sign-in is not configured for this page.</div>;
  return (
    <form className={CARD + " p-6 max-w-md mx-auto mt-16 space-y-3"} onSubmit={async (e) => {
      e.preventDefault(); setError(null);
      try { await auth.signInWithPassword(email, password); onSignedIn(); } catch (err) { setError(err); }
    }}>
      <h1 className="text-lg font-bold">{title}</h1>
      <input className="w-full rounded-lg ring-1 ring-slate-200 px-3 py-2" placeholder="Email" value={email} onChange={(e) => setEmail(e.target.value)} />
      <input className="w-full rounded-lg ring-1 ring-slate-200 px-3 py-2" type="password" placeholder="Password" value={password} onChange={(e) => setPassword(e.target.value)} />
      <button className={BTN + " w-full rounded-lg bg-slate-900 text-white py-2"}>Sign in</button>
      <ErrorNote error={error} />
    </form>
  );
}

function Report({ report }) {
  const ev = report.evaluation;
  return (
    <div>
      <div className="text-sm">
        Validator <code>{report.validatorVersion}</code>: {report.valid
          ? <span className="text-emerald-700 font-semibold">valid</span>
          : <span className="text-rose-700 font-semibold">{report.errors.length} error(s)</span>}
      </div>
      {report.errors.length > 0 && (
        <ul className="mt-2 text-xs font-mono space-y-1 max-h-64 overflow-auto">
          {report.errors.map((e, i) => <li key={i}><span className="text-rose-700">{e.path}</span> [{e.code}] {e.message}</li>)}
        </ul>
      )}
      <div className="text-sm mt-2">
        Evaluation set: {ev.autoPassed}/{ev.autoCases} key-scored cases passed; {ev.modelCases} model-graded case(s) for the reviewer to run.
        {ev.failures.length > 0 && <span className="text-rose-700"> Failed: {ev.failures.join(", ")}</span>}
      </div>
    </div>
  );
}

function Preview({ preview }) {
  return (
    <div className="space-y-3">
      <p className="text-xs text-slate-500">Exactly what students see: no answer keys, rubrics, expected answers or evaluation cases.</p>
      {preview.questions.map((q) => (
        <div key={q.questionId} className="rounded-lg ring-1 ring-slate-200 p-3">
          <div className="text-xs text-slate-500">{q.questionId} · v{q.version} · {q.topic}</div>
          <div className="text-sm whitespace-pre-wrap mt-1">{q.prompt}</div>
          {q.sources && q.sources.map((s) => (
            <blockquote key={s.materialId} className="mt-2 border-l-4 border-slate-300 pl-3 text-sm">
              <div className="font-semibold text-xs">{s.title}</div>{s.text}
            </blockquote>
          ))}
          {q.items && <ol className="mt-2 text-sm list-decimal pl-5 space-y-1">{q.items.map((i) => (
            <li key={i.itemId}>{i.prompt}<div className="text-xs text-slate-600">{i.choices.map((c) => c.key + ") " + c.text).join("   ")}</div></li>
          ))}</ol>}
        </div>
      ))}
    </div>
  );
}
