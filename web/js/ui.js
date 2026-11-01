// ui.js — shared primitives used across panels and features.

function Card({ className, children }) {
  return <div className={CARD + (className ? " " + className : "")}>{children}</div>;
}

function Badge({ className, children }) {
  return (
    <span className={"inline-flex items-center px-2 py-0.5 rounded-full text-[10px] font-medium ring-1 " + (className || "")}>
      {children}
    </span>
  );
}

function Bar({ label, value, bar }) {
  return (
    <div>
      <div className="flex justify-between text-[11px] text-slate-500 dark:text-slate-400 mb-1"><span>{label}</span><span className="font-mono font-semibold">{value}%</span></div>
      <div className="h-2.5 rounded-full bg-slate-200/80 dark:bg-slate-800 overflow-hidden">
        <div className={"h-full rounded-full transition-all duration-500 " + bar} style={{ width: value + "%" }} />
      </div>
    </div>
  );
}

function Modal({ title, onClose, children }) {
  return (
    <div className="fixed inset-0 bg-slate-950/50 dark:bg-black/70 backdrop-blur-sm flex items-end sm:items-center justify-center p-0 sm:p-4 z-50">
      <div className="bg-white dark:bg-slate-900 ring-1 ring-slate-200 dark:ring-slate-700 rounded-t-3xl sm:rounded-3xl shadow-xl max-w-lg w-full p-5 space-y-3 max-h-[88vh] overflow-y-auto">
        <div className="flex justify-between items-center">
          <div className="text-sm font-bold">{title}</div>
          <button onClick={onClose} className={"min-h-[36px] px-3 rounded-full text-xs text-slate-500 dark:text-slate-400 hover:bg-slate-100 dark:hover:bg-slate-800 " + BTN}>Close</button>
        </div>
        {children}
      </div>
    </div>
  );
}

// Exam prediction. Always "unavailable" until a calibrated pipeline exists (M5).
function PredictionBadge({ entry }) {
  return (
    <div className="text-xs font-semibold text-slate-500 dark:text-slate-400" title="Predicted scores are shown only after independent calibration">
      {HSProvider.predictionLabel(entry)}
    </div>
  );
}

const RUN_TONE = {
  slate: "bg-slate-50 text-slate-600 ring-slate-200 dark:bg-slate-900 dark:text-slate-300 dark:ring-slate-700",
  indigo: "bg-indigo-50 text-indigo-700 ring-indigo-200 dark:bg-indigo-950/40 dark:text-indigo-200 dark:ring-indigo-500/40",
  amber: "bg-amber-50 text-amber-800 ring-amber-200 dark:bg-amber-500/10 dark:text-amber-200 dark:ring-amber-500/30",
  emerald: "bg-emerald-50 text-emerald-700 ring-emerald-200 dark:bg-emerald-950/40 dark:text-emerald-200 dark:ring-emerald-500/40",
  rose: "bg-rose-50 text-rose-700 ring-rose-200 dark:bg-rose-950/40 dark:text-rose-200 dark:ring-rose-500/40",
};

// QUEUED / RUNNING / WAITING_INPUT / SUCCEEDED / FAILED / CANCELLED for one Run.
function RunStatusBadge({ run, architect }) {
  const view = HSProvider.describeRun(run);
  if (!view) return null;
  return (
    <Badge className={RUN_TONE[view.tone]}>
      {view.label}
      {view.retryable ? " · can retry" : ""}
      {architect ? " · " + run.status : ""}
    </Badge>
  );
}

function DemoBanner() {
  return (
    <div className="shrink-0 px-3 sm:px-4 py-1.5 text-[11px] bg-amber-100 dark:bg-amber-500/15 text-amber-900 dark:text-amber-100 border-b border-amber-200 dark:border-amber-500/30">
      <strong>DEMO mode</strong> · synthetic data; actions are simulated on this device and are never saved or assessed. Remove <code>?demo=true</code> from the URL to exit.
    </div>
  );
}

// Full-page loading / not connected / not signed in / error states.
function StatusScreen({ screen, error, onRetry }) {
  const copy = {
    loading: { title: "Connecting to Student OS…", body: "Loading your learning record." },
    not_connected: { title: "Not connected to Student OS", body: "Cannot reach the backend API. Your learning data will not be replaced with demo data. Make sure the service is running, then retry." },
    not_signed_in: { title: "Sign-in required", body: "No student data is shown before you sign in." },
    error: { title: "Failed to load", body: "The server returned an error. No substitute data is shown." },
  }[screen] || { title: "Failed to load", body: "" };
  return (
    <div className="min-h-screen flex items-center justify-center p-6 bg-[#F7F8FA] dark:bg-slate-950">
      <div className={CARD + " max-w-md w-full p-6 space-y-3"} role={screen === "loading" ? "status" : "alert"}>
        <div className="text-sm font-bold">{copy.title}</div>
        <p className="text-xs text-slate-600 dark:text-slate-300 leading-relaxed">{copy.body}</p>
        {error && (
          <div className="text-[11px] font-mono text-slate-400 dark:text-slate-500">
            {error.code}{error.requestId ? " · " + error.requestId : ""}
          </div>
        )}
        {screen !== "loading" && (
          <div className="flex flex-wrap gap-2 pt-1">
            <button onClick={onRetry} className={"px-4 min-h-[40px] rounded-full bg-indigo-600 hover:bg-indigo-500 text-white text-xs font-semibold " + BTN}>Retry</button>
            <a href="?demo=true" className="px-4 min-h-[40px] inline-flex items-center rounded-full ring-1 ring-slate-300 dark:ring-slate-700 text-xs text-slate-600 dark:text-slate-300">Open demo mode (synthetic data)</a>
          </div>
        )}
      </div>
    </div>
  );
}

// Sign-in. Firebase Auth when configured; on localhost without Firebase config, a labeled
// local emulator sign-in for the synthetic fixture students only (see js/auth.js).
function SignInScreen({ auth, error, onSignedIn }) {
  const [email, setEmail] = React.useState("");
  const [password, setPassword] = React.useState("");
  const [failure, setFailure] = React.useState(null);
  const submit = (e) => {
    e.preventDefault();
    setFailure(null);
    auth.signInWithPassword(email, password).then(onSignedIn, () => setFailure("Sign-in failed. Check your email and password."));
  };
  return (
    <div className="min-h-screen flex items-center justify-center p-6 bg-[#F7F8FA] dark:bg-slate-950">
      <div className={CARD + " max-w-md w-full p-6 space-y-3"}>
        <div className="text-sm font-bold">Sign in to Student OS</div>
        {error && error.code === "UNAUTHENTICATED" && <p className="text-xs text-rose-600">Your sign-in expired. Please sign in again.</p>}
        {auth.mode === "firebase" && (
          <form onSubmit={submit} className="space-y-2">
            <input value={email} onChange={(e) => setEmail(e.target.value)} type="email" autoComplete="username" placeholder="Email" className="w-full min-h-[40px] px-3 rounded-xl ring-1 ring-slate-300 dark:ring-slate-700 bg-white dark:bg-slate-900 text-sm" />
            <input value={password} onChange={(e) => setPassword(e.target.value)} type="password" autoComplete="current-password" placeholder="Password" className="w-full min-h-[40px] px-3 rounded-xl ring-1 ring-slate-300 dark:ring-slate-700 bg-white dark:bg-slate-900 text-sm" />
            <button className={"w-full min-h-[40px] rounded-full bg-indigo-600 text-white text-xs font-semibold " + BTN}>Sign in</button>
            {failure && <p className="text-xs text-rose-600">{failure}</p>}
          </form>
        )}
        {auth.mode === "local_emulator" && (
          <div className="space-y-2">
            <p className="text-[11px] text-amber-800 dark:text-amber-200 bg-amber-50 dark:bg-amber-500/10 p-2 rounded-lg">
              Local development sign-in: signs in a synthetic student with an Auth-emulator-style token. Works only when the local backend runs in emulator mode; deployed environments reject it.
            </p>
            {auth.students.map((s) => (
              <button key={s.uid} onClick={() => { auth.signInLocal(s.uid); onSignedIn(); }}
                className={"w-full min-h-[40px] rounded-full ring-1 ring-indigo-300 text-xs font-semibold text-indigo-700 dark:text-indigo-200 " + BTN}>{s.label}</button>
            ))}
          </div>
        )}
        {auth.mode === "none" && <p className="text-xs text-slate-600 dark:text-slate-300">Sign-in is not configured for this page. No student data is shown before you sign in.</p>}
        <a href="?demo=true" className="block text-center text-[11px] text-slate-500 underline">Open demo mode (synthetic data)</a>
      </div>
    </div>
  );
}

// GPA_SYNC / EXAM_CRUNCH two-option mode toggle.
function ModeToggle({ apMode, setApMode }) {
  return (
    <div className="flex bg-slate-100 dark:bg-slate-950 p-1 rounded-full ring-1 ring-slate-200 dark:ring-slate-800 text-xs">
      <button onClick={() => setApMode("GPA_SYNC")} className={"px-3 py-1.5 rounded-full transition active:scale-95 " + modeClass("GPA_SYNC", apMode === "GPA_SYNC")}>Daily GPA support</button>
      <button onClick={() => setApMode("EXAM_CRUNCH")} className={"px-3 py-1.5 rounded-full transition active:scale-95 " + modeClass("EXAM_CRUNCH", apMode === "EXAM_CRUNCH")}>May exam crunch</button>
    </div>
  );
}
