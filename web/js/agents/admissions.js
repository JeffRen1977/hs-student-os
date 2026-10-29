// agents/admissions.js — Admissions Agent panel (interview / matrix / activities / spike).

function AdmissionsPanel({ session, onNote }) {
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
          <div className="p-3 rounded-xl bg-slate-50 dark:bg-slate-950 ring-1 ring-slate-200/70 dark:ring-slate-800 text-slate-500 dark:text-slate-400">原描述：帮助学弟学妹学编程，组织了几次活动。</div>
          <div className="p-3 rounded-xl bg-emerald-50 dark:bg-emerald-950/30 ring-1 ring-emerald-300 dark:ring-emerald-700">Led 12 weekly Java labs for 28 students; 19 finished a published ArrayList project.</div>
          <div className="text-slate-500">148 / 150 字符。事实需学生确认后才保存。</div>
        </div>
      )}
      {kind !== "matrix" && kind !== "activities" && (
        <p className="text-xs text-slate-600 dark:text-slate-300 leading-relaxed">你写到机器人视觉。招生官还看不出这件事和社区有什么关系。那次调试发生在谁身上，你当时改了哪一个判断？</p>
      )}
      <button onClick={() => onNote(kind === "spike" ? "主线缺口：有 AP CSA 与数学，缺少能支撑 AI 伦理叙事的人文活动。" : "已把「" + session.title + "」记入本周计划。")} className={"px-4 min-h-[40px] py-1.5 rounded-full ring-1 ring-emerald-500 dark:ring-emerald-600 text-xs font-medium text-emerald-700 dark:text-emerald-200 hover:bg-emerald-50 dark:hover:bg-emerald-500/10 " + BTN}>把这条记入本周任务</button>
    </section>
  );
}
