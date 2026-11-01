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
          Passage A assumes a higher temperature speeds up the reaction. Passage B reports only measurements at 20°C and 30°C. Is the question asking about the author's assumption or the experimental conclusion?
        </div>
      )}
      {kind === "vocab" && (
        <div className="bg-slate-50 dark:bg-slate-950 ring-1 ring-slate-200/70 dark:ring-slate-800 rounded-xl p-3.5 text-xs leading-relaxed">
          <div className="text-amber-700 dark:text-amber-200 font-semibold">unostentatious</div>
          <p className="text-slate-600 dark:text-slate-300 mt-1">“modest, unostentatious living” — Carnegie, 1889. Make a flashcard from this original sentence instead of memorizing the definition alone.</p>
        </div>
      )}
      {kind === "mock" && (
        <div className="grid grid-cols-1 sm:grid-cols-2 gap-2 text-xs">
          <div className="p-3 rounded-xl bg-slate-50 dark:bg-slate-950 ring-1 ring-slate-200/70 dark:ring-slate-800">Module 1 · routing module<br /><span className="text-slate-500 dark:text-slate-400">22 questions; sets the next module's difficulty</span></div>
          <div className="p-3 rounded-xl bg-slate-50 dark:bg-slate-950 ring-1 ring-sky-300 dark:ring-sky-800">Module 2 · harder<br /><span className="text-slate-500 dark:text-slate-400">Enough correct answers in Module 1, so the harder module follows</span></div>
        </div>
      )}
      {kind === "math" && <button onClick={onDesmos} className={"px-4 min-h-[40px] py-1.5 rounded-full bg-sky-600 hover:bg-sky-500 text-white text-xs font-semibold " + BTN}>Graph both functions in Desmos</button>}
      <p className="text-[11px] text-slate-400 dark:text-slate-500">Preview of a planned practice format. It creates no learning record and does not update mastery.</p>
    </section>
  );
}

function kindTitle(kind) {
  if (kind === "rw") return "Reading error: assumption vs. conclusion";
  if (kind === "vocab") return "Context flashcards";
  if (kind === "mock") return "Two-stage adaptive mock test";
  if (kind === "matrix") return "College list matrix";
  if (kind === "activities") return "150-character activity description";
  if (kind === "spike") return "Application theme";
  return "Composite functions · Desmos";
}
