// agents/admissions.js — Admissions panel (interview / matrix / activities / spike). Preview only (M5).

function AdmissionsPanel({ preview, onNote }) {
  const session = preview;
  const kind = session.kind || "interview";
  return (
    <section className={CARD + " ring-emerald-200 dark:ring-emerald-500/40 p-4 sm:p-5 space-y-3 text-sm"}>
      <div>
        <div className="text-[10px] uppercase tracking-wide text-emerald-600 dark:text-emerald-400 font-semibold">Admissions · {MODE_LABEL[session.mode]}</div>
        <h2 className="text-lg font-bold tracking-tight">{session.title}</h2>
        <p className="text-xs text-slate-500 dark:text-slate-400 mt-1">{session.desc}</p>
      </div>
      {kind === "matrix" && (
        <div className="grid grid-cols-1 sm:grid-cols-3 gap-2 text-xs">
          <div className="p-3 rounded-xl bg-rose-50 dark:bg-rose-950/30 ring-1 ring-rose-200 dark:ring-rose-500/30">Reach<br />CMU SCS</div>
          <div className="p-3 rounded-xl bg-amber-50 dark:bg-amber-950/30 ring-1 ring-amber-200 dark:ring-amber-500/30">Match<br />UCSD CSE</div>
          <div className="p-3 rounded-xl bg-emerald-50 dark:bg-emerald-950/30 ring-1 ring-emerald-200 dark:ring-emerald-500/30">Safety<br />Purdue CS</div>
        </div>
      )}
      {kind === "activities" && (
        <div className="text-xs space-y-2">
          <div className="p-3 rounded-xl bg-slate-50 dark:bg-slate-950 ring-1 ring-slate-200/70 dark:ring-slate-800 text-slate-500 dark:text-slate-400">Original: Helped younger students learn to code and organized a few events.</div>
          <div className="p-3 rounded-xl bg-emerald-50 dark:bg-emerald-950/30 ring-1 ring-emerald-300 dark:ring-emerald-700">Led 12 weekly Java labs for 28 students; 19 finished a published ArrayList project.</div>
          <div className="text-slate-500">148 / 150 characters. Facts are saved only after the student confirms them.</div>
        </div>
      )}
      {kind !== "matrix" && kind !== "activities" && (
        <p className="text-xs text-slate-600 dark:text-slate-300 leading-relaxed">You wrote about robot vision. An admissions reader can't yet see how it connects to your community. Who was that debugging session for, and which decision did you change?</p>
      )}
      <button onClick={() => onNote(kind === "spike" ? "Theme gap: AP CSA and math are there, but no humanities activity supports the AI-ethics story." : "Demo: “" + session.title + "” was not added to the plan (planned feature).")} className={"px-4 min-h-[40px] py-1.5 rounded-full ring-1 ring-emerald-500 dark:ring-emerald-600 text-xs font-medium text-emerald-700 dark:text-emerald-200 hover:bg-emerald-50 dark:hover:bg-emerald-500/10 " + BTN}>Add to this week's tasks (demo)</button>
    </section>
  );
}
