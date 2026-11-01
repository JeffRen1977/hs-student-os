// agents/ap.js — AP Base Agent panel: course header, Task/Session/Run status,
// GPA workspace (Socratic + subject canvas), Exam workspace (FRQ rubric), answer input.
// Canvas content is illustrative; interactions are local demo notes only.

function ApPanel({ S }) {
  const pack = S.pack;
  const task = S.currentTask;
  const session = S.currentSession;
  const run = S.currentRun;
  const architect = S.architect;
  const demoOnly = (text) => () => S.noteDemo("demo.note", text);
  return (
    <React.Fragment>
      <section className={CARD + " p-4 space-y-3"}>
        <div className="flex flex-wrap justify-between items-center gap-2">
          <div>
            <div className="text-[10px] uppercase tracking-wide text-slate-500 dark:text-slate-500">Course Agent</div>
            <div className="text-sm font-semibold">
              AP Base Agent <span className="text-slate-300 dark:text-slate-600">/</span> <span className="text-indigo-600 dark:text-indigo-300">{pack.icon} {pack.shortName}</span>
            </div>
          </div>
          <div className="flex items-center gap-3">
            <div className="text-right">
              <div className="text-[10px] text-slate-500 dark:text-slate-400">AP prediction</div>
              <PredictionBadge entry={(S.twin.predictionSummary || {})[pack.id]} />
            </div>
            <ModeToggle apMode={S.apMode} setApMode={S.setApMode} />
          </div>
        </div>
        {architect ? (
          <div className="grid grid-cols-1 sm:grid-cols-3 gap-2 text-[11px] bg-slate-50 dark:bg-slate-950 p-3 rounded-xl ring-1 ring-slate-200/70 dark:ring-slate-800">
            <div>
              <div className="text-amber-600 dark:text-amber-300 font-semibold mb-1">Skills</div>
              {pack.skills.map((sk) => (
                <div key={sk.name} className={sk.modes.indexOf(S.apMode) >= 0 ? "text-amber-700 dark:text-amber-100" : "text-slate-400 dark:text-slate-600 line-through"}>{sk.name}</div>
              ))}
            </div>
            <div>
              <div className="text-sky-600 dark:text-sky-300 font-semibold mb-1">Content</div>
              {pack.rag.map((r) => <div key={r} className="text-sky-700 dark:text-sky-100">{r}</div>)}
            </div>
            <div>
              <div className="text-emerald-600 dark:text-emerald-300 font-semibold mb-1">Tools (server-side)</div>
              {pack.tools.map((m) => <div key={m} className="text-emerald-700 dark:text-emerald-100">{m}</div>)}
            </div>
          </div>
        ) : (
          pack.currentUnit && <div className="text-xs text-slate-600 dark:text-slate-300">{pack.currentUnit}</div>
        )}
        {task && <TaskSessionRunCard S={S} task={task} session={session} run={run} architect={architect} demoOnly={demoOnly} />}
      </section>

      {S.apMode === "GPA_SYNC" ? (
        <GpaWorkspace pack={pack} fixed={!!S.fixedSteps[pack.id]} tier2={S.tier2} architect={architect}
          onTier2={() => S.setTier2(true)}
          onFix={() => {
            S.setFixedSteps((p) => Object.assign({}, p, { [pack.id]: true }));
            S.noteDemo("demo.note", "Demo: the correction is shown locally only. Any follow-up practice is decided by the server after an accepted assessment.");
          }}
          onVocab={demoOnly("Demo: context-vocabulary sync is a planned feature; nothing was saved.")}
        />
      ) : (
        <ExamWorkspace pack={pack} fixed={!!S.fixedFrq[pack.id]}
          onAdopt={() => {
            S.setFixedFrq((p) => Object.assign({}, p, { [pack.id]: true }));
            S.noteDemo("demo.note", "Demo: the rewrite was adopted locally. The AP prediction stays unavailable (not calibrated); one correction does not change it.");
          }}
        />
      )}

      <AnswerComposer S={S} />
    </React.Fragment>
  );
}

// Task (plan) → Session (this attempt) → Run (one backend execution), shown separately.
function TaskSessionRunCard({ task, session, run, architect, demoOnly }) {
  return (
    <div className="grid grid-cols-1 sm:grid-cols-3 gap-2 text-[11px]">
      <div className="p-2.5 rounded-xl bg-slate-50 dark:bg-slate-950 ring-1 ring-slate-200/70 dark:ring-slate-800">
        <div className="text-slate-400">Task</div>
        <div className="font-semibold text-slate-800 dark:text-slate-100">{task.title}</div>
        <div className="text-slate-500">{TASK_STATUS_LABEL[task.status]}{architect ? " · " + task.taskId : ""}</div>
      </div>
      <div className="p-2.5 rounded-xl bg-slate-50 dark:bg-slate-950 ring-1 ring-slate-200/70 dark:ring-slate-800">
        <div className="text-slate-400">This session</div>
        {session ? (
          <React.Fragment>
            <div className="font-semibold text-slate-800 dark:text-slate-100">{session.status === "OPEN" ? "In progress" : session.status}</div>
            <div className="text-slate-500">{session.completion.eligible ? "Ready to complete" : "Needs an accepted assessment to complete"}{architect ? " · " + session.sessionId : ""}</div>
          </React.Fragment>
        ) : (
          <div className="text-slate-500">Not started</div>
        )}
      </div>
      <div className="p-2.5 rounded-xl bg-slate-50 dark:bg-slate-950 ring-1 ring-slate-200/70 dark:ring-slate-800 space-y-1">
        <div className="text-slate-400">Grading</div>
        {run ? <RunStatusBadge run={run} architect={architect} /> : <div className="text-slate-500">No grading in progress</div>}
        {run && run.status === "WAITING_INPUT" && run.inputRequest && <div className="text-amber-700 dark:text-amber-200">{run.inputRequest.prompt}</div>}
        {run && run.status === "FAILED" && run.error && <div className="text-rose-600 dark:text-rose-300">{run.error.code}</div>}
        {run && run.status === "WAITING_INPUT" && (
          <button onClick={demoOnly("Demo: confirming the recognized text submits a new evidence version (POST /api/runs/{id}/input); nothing was sent.")} className={"px-3 min-h-[32px] rounded-full ring-1 ring-amber-300 text-amber-800 dark:text-amber-200 " + BTN}>Confirm recognized text</button>
        )}
        {run && run.status === "FAILED" && run.error && run.error.retryable && (
          <button onClick={demoOnly("Demo: a retry resubmits with the same Idempotency-Key; nothing was sent.")} className={"px-3 min-h-[32px] rounded-full ring-1 ring-rose-300 text-rose-700 dark:text-rose-200 " + BTN}>Retry</button>
        )}
      </div>
    </div>
  );
}

// Answer input. Text is kept as a local draft until the server accepts a submission.
function AnswerComposer({ S }) {
  const send = (e) => {
    e.preventDefault();
    if (!S.draft.trim()) return;
    if (S.demo) {
      S.noteDemo("demo.note", "Demo: the answer was not sent to the server or assessed.");
      S.clearDraft();
    }
    // API mode: POST /api/sessions/{id}/submissions with an Idempotency-Key (M1 Step 14).
  };
  return (
    <form onSubmit={send} className="space-y-1">
      <div className="flex gap-2">
        <input value={S.draft} onChange={(e) => S.setDraft(e.target.value)} placeholder="Answer the follow-up in your own words..." className="flex-1 min-h-[44px] bg-white dark:bg-slate-900 ring-1 ring-slate-200 dark:ring-slate-800 rounded-full px-4 py-2 text-sm outline-none focus:ring-2 focus:ring-indigo-500 shadow-sm transition" />
        <button disabled={!S.demo} className={"px-5 min-h-[44px] rounded-full bg-indigo-600 hover:bg-indigo-500 disabled:opacity-50 text-white text-sm font-semibold shadow-sm " + BTN}>Send</button>
      </div>
      {S.draftSavedAt && <div className="text-[10px] text-slate-400 px-4">Draft saved on this device only; not sent yet.</div>}
    </form>
  );
}

function GpaWorkspace({ pack, fixed, tier2, architect, onTier2, onFix, onVocab }) {
  const prompt = gpaPrompt(pack, fixed);
  return (
    <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
      <section className={CARD + " p-4 text-xs space-y-2.5"}>
        <div className="font-semibold text-emerald-600 dark:text-emerald-300">Socratic guidance · no direct answers</div>
        <p className="text-slate-600 dark:text-slate-300 leading-relaxed">{prompt}</p>
        {!tier2 ? (
          <button onClick={onTier2} className={"px-3 min-h-[36px] rounded-full ring-1 ring-amber-300 dark:ring-amber-500/40 text-amber-700 dark:text-amber-200 hover:bg-amber-50 dark:hover:bg-amber-500/10 " + BTN}>Show Tier 2 hint</button>
        ) : (
          <p className="text-amber-800 dark:text-amber-100/90 leading-relaxed">{tier2Text(pack)}</p>
        )}
      </section>
      <section className={CARD + " p-4 text-xs space-y-2.5"}>
        <div className="font-semibold text-sky-600 dark:text-sky-300">{canvasTitle(pack)}</div>
        <CanvasBody pack={pack} fixed={fixed} architect={architect} onFix={onFix} onVocab={onVocab} />
      </section>
    </div>
  );
}

function CanvasBody({ pack, fixed, onFix, onVocab }) {
  if (pack.canvas === "history" || pack.canvas === "lang") {
    return (
      <div className="space-y-2">
        <p className="text-slate-600 dark:text-slate-300 leading-relaxed">
          “This, then, is held to be the duty of the man of Wealth: first, to set an example of modest, <span className="bg-amber-200/60 dark:bg-amber-400/20 text-amber-800 dark:text-amber-200 px-1 rounded">unostentatious</span> living...”
        </p>
        <div className="text-[10px] text-slate-400 dark:text-slate-500">Andrew Carnegie, The Gospel of Wealth (1889)</div>
        <button onClick={onVocab} className={"w-full min-h-[40px] py-1.5 rounded-full bg-sky-600 hover:bg-sky-500 text-white font-semibold " + BTN}>Extract highlighted words and sentences (planned)</button>
      </div>
    );
  }
  if (pack.canvas === "code") {
    return (
      <div className="space-y-2 font-mono">
        <div className="p-2.5 rounded-xl bg-slate-50 dark:bg-slate-950 ring-1 ring-slate-200/60 dark:ring-slate-800">for (int i = 0; i &lt;= list.size(); i++)</div>
        <div className={"p-2.5 rounded-xl ring-1 " + (fixed ? "ring-emerald-300 dark:ring-emerald-500 bg-emerald-50 dark:bg-transparent text-emerald-700 dark:text-emerald-200" : "ring-rose-300 dark:ring-rose-500 bg-rose-50 dark:bg-transparent text-rose-700 dark:text-rose-200")}>
          {fixed ? "i < list.size()  · bound fixed" : "i <= list.size()  · out of bounds"}
        </div>
        <button onClick={onFix} className={"w-full min-h-[40px] py-1.5 rounded-full bg-indigo-600 hover:bg-indigo-500 text-white font-semibold font-sans " + BTN}>{fixed ? "Fixed locally" : "Fix the bound"}</button>
      </div>
    );
  }
  if (pack.canvas === "physics") {
    return (
      <div className="space-y-2 font-mono">
        <div className="p-2.5 rounded-xl bg-slate-50 dark:bg-slate-950 ring-1 ring-slate-200/60 dark:ring-slate-800">W = ∫ F · dr ✓</div>
        <div className={"p-2.5 rounded-xl ring-1 " + (fixed ? "ring-emerald-300 dark:ring-emerald-500 bg-emerald-50 dark:bg-transparent text-emerald-700 dark:text-emerald-200" : "ring-rose-300 dark:ring-rose-500 bg-rose-50 dark:bg-transparent text-rose-700 dark:text-rose-200")}>
          {fixed ? "P = dW/dt = F · v ✓" : "P = F  · missing velocity"}
        </div>
        <button onClick={onFix} className={"w-full min-h-[40px] py-1.5 rounded-full bg-indigo-600 hover:bg-indigo-500 text-white font-semibold font-sans " + BTN}>{fixed ? "Fixed locally" : "Fix this step"}</button>
      </div>
    );
  }
  return (
    <div className="space-y-2 font-mono">
      <div className="p-2.5 rounded-xl bg-slate-50 dark:bg-slate-950 ring-1 ring-slate-200/60 dark:ring-slate-800">Step 1: r = 1/2 h ✓</div>
      <div className="p-2.5 rounded-xl bg-slate-50 dark:bg-slate-950 ring-1 ring-slate-200/60 dark:ring-slate-800">Step 2: V = (π/12) h³ ✓</div>
      <div className={"p-2.5 rounded-xl ring-1 " + (fixed ? "ring-emerald-300 dark:ring-emerald-500 bg-emerald-50 dark:bg-emerald-950/30 text-emerald-700 dark:text-emerald-200" : "ring-rose-300 dark:ring-rose-500 bg-rose-50 dark:bg-rose-950/30 text-rose-700 dark:text-rose-200")}>
        {fixed ? "Step 3: dV/dt = (π/4) h² · dh/dt ✓" : "Step 3: dV/dt = (π/4) h²  · missing × dh/dt"}
      </div>
      <button onClick={onFix} className={"w-full min-h-[40px] py-1.5 rounded-full bg-indigo-600 hover:bg-indigo-500 text-white font-semibold font-sans " + BTN}>{fixed ? "Fixed locally" : "Fix Step 3"}</button>
    </div>
  );
}

function ExamWorkspace({ pack, fixed, onAdopt }) {
  const rubric = rubricFor(pack, fixed);
  return (
    <div className="grid grid-cols-1 lg:grid-cols-12 gap-3">
      <section className={CARD + " lg:col-span-7 ring-rose-200 dark:ring-rose-500/40 p-4 text-xs space-y-2.5"}>
        <div className="font-semibold text-rose-600 dark:text-rose-300">Point-by-point grading</div>
        <p className="text-slate-500 dark:text-slate-400">{pack.shortName} · {pack.currentUnit}</p>
        <div className={"p-3 rounded-xl ring-1 " + (fixed ? "bg-emerald-50 dark:bg-emerald-950/30 ring-emerald-200 dark:ring-emerald-500/40" : "bg-rose-50 dark:bg-rose-950/40 ring-rose-200 dark:ring-rose-500/40")}>
          <div className="font-semibold mb-1">{fixed ? "This point is earned" : "This point is not earned yet"}</div>
          <p className="text-slate-700 dark:text-slate-200 leading-relaxed">{fixed ? rubric.fixedLine : rubric.missLine}</p>
        </div>
        {!fixed && (
          <div className="p-3 rounded-xl bg-amber-50 dark:bg-amber-500/10 ring-1 ring-amber-200 dark:ring-amber-500/30 text-amber-900 dark:text-amber-50 leading-relaxed">
            {rubric.advice}
          </div>
        )}
        {!fixed && (
          <button onClick={onAdopt} className={"px-4 min-h-[40px] py-1.5 rounded-full bg-emerald-600 hover:bg-emerald-500 text-white font-semibold " + BTN}>Adopt rewrite</button>
        )}
        {fixed && <div className="text-emerald-600 dark:text-emerald-300">This step is corrected. Official scoring comes from the server assessment; the AP prediction stays unavailable.</div>}
      </section>
      <section className={CARD + " lg:col-span-5 p-4 text-xs space-y-2"}>
        <div className="font-semibold text-slate-800 dark:text-slate-200">Rubric check</div>
        {rubric.rows.map((row) => (
          <div key={row.name} className="flex justify-between border-b border-slate-100 dark:border-slate-800 py-1.5">
            <span>{row.name}</span>
            <span className={row.got === row.max ? "text-emerald-600 dark:text-emerald-400 font-mono font-semibold" : "text-rose-500 dark:text-rose-400 font-mono font-semibold"}>{row.got}/{row.max}</span>
          </div>
        ))}
      </section>
    </div>
  );
}

function gpaPrompt(pack, fixed) {
  if (pack.canvas === "calc") {
    return fixed
      ? "Step 3 now has dh/dt. In one sentence: why must h be written as h(t) rather than a constant?"
      : "In Step 3 on the right you wrote dV/dt = (π/4) h². Think: is h a constant, or a function of time h(t)?";
  }
  if (pack.canvas === "history") return "Carnegie says the rich have a duty to set an example. What behavior is he defending, and whom does he leave out?";
  if (pack.canvas === "code") return "The loop condition is i <= list.size(). On the last iteration, what does i point to?";
  if (pack.canvas === "physics") return "Power is not the force itself. The force is already doing work; what time-varying quantity must it be multiplied by?";
  return "What is the central claim of this speech? Find one word the author uses to shut down the other side.";
}

function tier2Text(pack) {
  if (pack.canvas === "calc") return "Hint: volume is a function of height, and height is a function of time. After differentiating the outer function in h, multiply by dh/dt.";
  if (pack.canvas === "history") return "Hint: first mark whom he speaks for, then find a group he calls “irresponsible”.";
  if (pack.canvas === "code") return "Hint: valid indexes are 0 to size()-1. get throws when the index equals size().";
  if (pack.canvas === "physics") return "Hint: P = dW/dt. After differentiating work with respect to time, dot the force with velocity.";
  return "Hint: restate the claim in your own words, then point to one word the author redefines.";
}

function canvasTitle(pack) {
  if (pack.canvas === "calc") return "STEM derivation canvas";
  if (pack.canvas === "history" || pack.canvas === "lang") return "Primary source";
  if (pack.canvas === "code") return "Code trace";
  return "Forces and energy";
}

function rubricFor(pack, fixed) {
  if (pack.family === "humanities") {
    return {
      missLine: "The essay opens straight with Carnegie's quote and never places it in the Gilded Age labor conflict.",
      fixedLine: "After the 1877 railroad strike, Carnegie framed private wealth as a public duty, answering national distrust of industrial magnates.",
      advice: "Add one specific context that predates the document (date + conflict) and this sentence earns the Contextualization point.",
      rows: [
        { name: "Thesis", got: 1, max: 1 },
        { name: "Contextualization", got: fixed ? 1 : 0, max: 1 },
        { name: "Evidence", got: 2, max: 2 },
      ],
    };
  }
  return {
    missLine: "dV/dt = (π/4) h². After differentiating volume with respect to height, dh/dt was not multiplied in.",
    fixedLine: "dV/dt = (π/4) h² · dh/dt. This earns the chain-rule process point.",
    advice: "Write height as h(t) and multiply by the inner derivative. That line is the process point.",
    rows: [
      { name: "Setup", got: 1, max: 1 },
      { name: "Chain rule", got: fixed ? 1 : 0, max: 1 },
      { name: "Units and conclusion", got: 1, max: 1 },
    ],
  };
}
