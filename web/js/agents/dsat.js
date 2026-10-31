// agents/dsat.js — Digital SAT panel (math / RW / vocab / mock). Preview only until M3.

function DsatPanel({ preview, onDesmos }) {
  const session = preview;
  const kind = session.kind || "math";
  return (
    <section className={CARD + " ring-sky-200 dark:ring-sky-500/40 p-4 sm:p-5 space-y-3 text-sm"}>
      <div>
        <div className="text-[10px] uppercase tracking-wide text-sky-600 dark:text-sky-400 font-semibold">Digital SAT · {session.title}</div>
        <h2 className="text-lg font-bold tracking-tight">{kindTitle(kind)}</h2>
        <p className="text-xs text-slate-500 dark:text-slate-400 mt-1">{session.desc}</p>
      </div>
      {kind === "math" && (
        <div className="bg-slate-50 dark:bg-slate-950 ring-1 ring-slate-200/70 dark:ring-slate-800 rounded-xl p-3.5 text-xs leading-relaxed">
          If f(x) = (2x + 1)³, what is f′(2)?
          <div className="mt-2 text-slate-500 dark:text-slate-400">A 18 · B 54 · C 150 · D 250</div>
        </div>
      )}
      {kind === "rw" && (
        <div className="bg-slate-50 dark:bg-slate-950 ring-1 ring-slate-200/70 dark:ring-slate-800 rounded-xl p-3.5 text-xs leading-relaxed text-slate-600 dark:text-slate-300">
          Passage A 假设温度上升会加快反应。Passage B 只报告了 20°C 与 30°C 的测量。题目问的是作者的假设，还是实验结论？
        </div>
      )}
      {kind === "vocab" && (
        <div className="bg-slate-50 dark:bg-slate-950 ring-1 ring-slate-200/70 dark:ring-slate-800 rounded-xl p-3.5 text-xs leading-relaxed">
          <div className="text-amber-700 dark:text-amber-200 font-semibold">unostentatious</div>
          <p className="text-slate-600 dark:text-slate-300 mt-1">“modest, unostentatious living” — Carnegie, 1889. 用这个原句出一张闪卡，而不是单独背释义。</p>
        </div>
      )}
      {kind === "mock" && (
        <div className="grid grid-cols-1 sm:grid-cols-2 gap-2 text-xs">
          <div className="p-3 rounded-xl bg-slate-50 dark:bg-slate-950 ring-1 ring-slate-200/70 dark:ring-slate-800">Module 1 · 路由模块<br /><span className="text-slate-500 dark:text-slate-400">22 题，决定下一模块难度</span></div>
          <div className="p-3 rounded-xl bg-slate-50 dark:bg-slate-950 ring-1 ring-sky-300 dark:ring-sky-800">Module 2 · 较难<br /><span className="text-slate-500 dark:text-slate-400">上一模块正确率足够，进入难题模块</span></div>
        </div>
      )}
      {kind === "math" && <button onClick={onDesmos} className={"px-4 min-h-[40px] py-1.5 rounded-full bg-sky-600 hover:bg-sky-500 text-white text-xs font-semibold " + BTN}>用 Desmos 演示两条函数图像</button>}
      <p className="text-[11px] text-slate-400 dark:text-slate-500">规划中的练习形态预览（M3）。不产生学习记录，也不更新掌握度。</p>
    </section>
  );
}

function kindTitle(kind) {
  if (kind === "rw") return "阅读错因：假设 vs 结论";
  if (kind === "vocab") return "语境闪卡";
  if (kind === "mock") return "两阶段自适应模考";
  if (kind === "matrix") return "选校矩阵";
  if (kind === "activities") return "150 字符活动描述";
  if (kind === "spike") return "申请主线";
  return "复合函数 · Desmos";
}
