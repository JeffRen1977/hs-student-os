// agents/course_session.js — the per-course agent learning flow against the real API
// (Step 20). Demo mode keeps the illustrative ApPanel; this panel is used in API mode.
//
// Truthful-state rules: everything shown comes from the server (session, messages, run,
// assessments). The draft is local until a command is accepted. A failed request shows the
// error and offers a retry that reuses the same Idempotency-Key. Run SUCCEEDED is shown as
// "Run finished", never as task completion; insufficient evidence is labeled as not counted.

const SESSION_REFRESH_EVENTS = ["run.", "assessment.", "mastery.", "session."];

function newActionId() {
  return "a" + Date.now().toString(36) + Math.random().toString(36).slice(2, 8);
}

function CourseSessionPanel({ S }) {
  const task = S.currentTask;
  const api = S.api;
  const [session, setSession] = React.useState(null);
  const [messages, setMessages] = React.useState([]);
  const [assessments, setAssessments] = React.useState([]);
  const [run, setRun] = React.useState(null);
  const [kind, setKind] = React.useState("ask"); // ask = message (hint), answer = submission
  const [busy, setBusy] = React.useState(false);
  const [error, setError] = React.useState(null);
  const [retry, setRetry] = React.useState(null); // the failed action, retried with its key
  const [choices, setChoices] = React.useState({}); // itemId → key, for SAT choice sets
  const [newDate, setNewDate] = React.useState("");
  const actionIdRef = React.useRef(newActionId());

  const reload = React.useCallback(async (sessionId) => {
    if (!sessionId) return;
    const [s, m, a, sub] = await Promise.all([
      api.fetchSession(sessionId),
      api.fetchMessages(sessionId),
      api.fetchAssessments(sessionId),
      api.fetchSubmissions(sessionId),
    ]);
    setSession(s);
    S.upsertSession(s);
    // Submitted answers are immutable submissions, not chat messages; show both in order.
    const answers = (sub.submissions || []).map((x) => ({
      messageId: x.submissionId, role: "student", text: x.answer.text, createdAt: x.createdAt,
      runId: x.runId, synthetic: false, isSubmission: true,
    }));
    setMessages((m.messages || []).concat(answers).sort((x, y) => (x.createdAt < y.createdAt ? -1 : x.createdAt > y.createdAt ? 1 : 0)));
    setAssessments((a.assessments || []).slice().reverse());
    const runId = s.activeRunId || (m.messages || []).concat(sub.submissions || []).sort((x, y) => (x.createdAt < y.createdAt ? -1 : 1)).map((x) => x.runId).filter(Boolean).pop();
    setRun(runId ? await api.fetchRun(runId) : null);
  }, [api]);

  // Task changed (or page reloaded): recover the open session from the server.
  React.useEffect(() => {
    setError(null);
    setRetry(null);
    const open = task ? S.sessionForTask(task.taskId) : null;
    setSession(open);
    setMessages([]);
    setAssessments([]);
    setRun(null);
    setChoices({});
    setNewDate("");
    if (open) reload(open.sessionId).catch(setError);
  }, [task && task.taskId]);

  // Server events for this session (SSE or polling) trigger a refetch of its state.
  const lastSeq = S.lastSequence;
  const seenSeq = React.useRef(lastSeq);
  React.useEffect(() => {
    const since = seenSeq.current;
    seenSeq.current = lastSeq;
    if (!session) return;
    const relevant = S.events.some((e) => e.sequence > since && e.sessionId === session.sessionId &&
      SESSION_REFRESH_EVENTS.some((p) => String(e.type).indexOf(p) === 0));
    if (relevant) reload(session.sessionId).catch(setError);
  }, [lastSeq]);

  // Safety net while a run is active: poll it, in case events are delayed.
  const active = run && !HSProvider.describeRun(run).terminal;
  React.useEffect(() => {
    if (!active || !session) return undefined;
    const t = setInterval(() => reload(session.sessionId).catch(() => {}), 3000);
    return () => clearInterval(t);
  }, [active, session && session.sessionId]);

  if (!task) {
    return <section className={CARD + " p-4 text-xs text-slate-500"}>Pick a task on the left to start practicing.</section>;
  }

  const perform = async (action) => {
    setBusy(true);
    setError(null);
    try {
      await action();
      setRetry(null);
    } catch (e) {
      setError(e);
      setRetry(e && e.retryable ? () => action : null);
    } finally {
      setBusy(false);
    }
  };

  const start = () => perform(async () => {
    const s = await api.createSession(task.taskId);
    setSession(s);
    S.upsertSession(s);
    await Promise.all([reload(s.sessionId), S.refreshTasks()]);
  });

  const items = session && session.activity && session.activity.items;
  const choiceText = items ? HSProvider.formatChoiceAnswer(items, choices) : null;

  const send = () => {
    const answeringChoices = kind === "answer" && items;
    const text = answeringChoices ? choiceText : S.draft.trim();
    if (!text || !session) return;
    const actionId = actionIdRef.current; // same id → same Idempotency-Key on retry
    const act = session.activity;
    return perform(async () => {
      const accepted = kind === "answer" && act
        ? await api.submitAnswer(session.sessionId, {
            questionId: act.questionId, questionVersion: act.questionVersion,
            answer: { text: text, fileIds: [] },
          }, actionId)
        : await api.sendMessage(session.sessionId, text, actionId);
      actionIdRef.current = newActionId();
      if (answeringChoices) setChoices({});
      else S.clearDraft();
      setRun({ runId: accepted.runId, status: accepted.status });
      await reload(session.sessionId);
    });
  };

  const complete = () => perform(async () => {
    const s = await api.completeSession(session.sessionId);
    setSession(s);
    await Promise.all([S.refreshTasks(), S.refreshTwin(), S.refreshSessions()]);
  });
  const abandon = () => perform(async () => {
    const s = await api.abandonSession(session.sessionId);
    setSession(s);
    await Promise.all([S.refreshTasks(), S.refreshSessions()]);
  });
  const cancel = () => perform(async () => {
    await api.cancelRun(run.runId);
    await reload(session.sessionId);
  });

  const reschedule = () => perform(async () => {
    await S.rescheduleTask(task, newDate);
    setNewDate("");
  });

  const open = session && session.status === "OPEN";
  const canSend = open && !active && !busy;
  const isSat = task.agent === "DSAT";
  const answerReady = kind === "answer" && items ? !!choiceText : !!S.draft.trim();
  return (
    <React.Fragment>
      <section className={CARD + " p-4 space-y-3"}>
        <div className="flex flex-wrap justify-between items-start gap-2">
          <div>
            <div className="text-[10px] uppercase tracking-wide text-slate-500">Course Agent · {S.courseName(task.courseId)}</div>
            <div className="text-sm font-semibold">{task.title}</div>
            <div className="text-[11px] text-slate-500">{TASK_STATUS_LABEL[task.status]}{S.architect ? " · " + task.taskId : ""}</div>
          </div>
          <div className="text-right">
            <div className="text-[10px] text-slate-500">{isSat ? "SAT prediction" : "AP prediction"}</div>
            <PredictionBadge entry={(S.twin.predictionSummary || {})[task.courseId]} />
          </div>
        </div>
        {task.reason && task.reason.explanation && (
          <div className="p-3 rounded-xl bg-amber-50 dark:bg-amber-950/30 ring-1 ring-amber-200/70 dark:ring-amber-500/30 text-[11px] text-slate-700 dark:text-slate-200 leading-relaxed">
            <div className="text-[10px] font-semibold text-amber-700 dark:text-amber-300 mb-0.5">Why this task</div>
            {task.reason.explanation}
          </div>
        )}
        {session && session.activity && (
          <div className="p-3 rounded-xl bg-slate-50 dark:bg-slate-950 ring-1 ring-slate-200/70 dark:ring-slate-800 text-xs space-y-1">
            <div className="text-[10px] text-slate-400">Question · {session.activity.topic}</div>
            <div className="text-slate-800 dark:text-slate-100 leading-relaxed">{session.activity.prompt}</div>
            {items && <div className="text-[11px] text-slate-500">Choose one answer per item; answers are scored by key. Rubric points are not an exam score.</div>}
          </div>
        )}
        {task.status === "PLANNED" && !session && S.api && (
          <div className="flex flex-wrap items-center gap-2 text-[11px] text-slate-500">
            <span>Scheduled for {task.scheduledDate}{task.studentLocked ? " (locked by you)" : ""}</span>
            <input type="date" value={newDate} onChange={(e) => setNewDate(e.target.value)} aria-label="New date"
              className="bg-white dark:bg-slate-900 ring-1 ring-slate-200 dark:ring-slate-800 rounded-lg px-2 py-1" />
            <button disabled={busy || !newDate} onClick={reschedule} className={"px-3 min-h-[30px] rounded-full ring-1 ring-slate-300 dark:ring-slate-700 disabled:opacity-40 " + BTN}>Reschedule (kept on replan)</button>
          </div>
        )}
        {!session && (task.status === "PLANNED" || task.status === "IN_PROGRESS") && (
          <button disabled={busy} onClick={start} className={"px-4 min-h-[40px] rounded-full bg-indigo-600 hover:bg-indigo-500 disabled:opacity-50 text-white text-xs font-semibold " + BTN}>Start practice</button>
        )}
        {!session && task.status === "COMPLETED" && <div className="text-xs text-slate-500">This task is completed. New practice will appear as a new task.</div>}
        {session && !open && <div className="text-xs text-slate-500">This session was {session.status === "COMPLETED" ? "completed" : "abandoned"}.</div>}
      </section>

      {session && (
        <section className={CARD + " p-4 space-y-2"} aria-live="polite">
          {messages.length === 0 && <div className="text-xs text-slate-500">Ask the agent a question, or submit your solution.</div>}
          {messages.map((m) => <MessageBubble key={m.messageId} message={m} />)}
          {run && <RunLine run={run} architect={S.architect} onCancel={open && active ? cancel : null} busy={busy} />}
        </section>
      )}

      {assessments.map((a) => <AssessmentCard key={a.assessmentId} assessment={a} architect={S.architect} />)}

      {error && (
        <div role="alert" className="p-3 rounded-xl bg-rose-50 dark:bg-rose-950/40 ring-1 ring-rose-200 dark:ring-rose-500/30 text-xs text-rose-700 dark:text-rose-200 flex flex-wrap items-center gap-2">
          <span>{HSProvider.errorText(error.code)}</span>
          {error.requestId && <span className="font-mono text-[10px] opacity-70">{error.requestId}</span>}
          {retry && <button disabled={busy} onClick={() => perform(retry)} className={"px-3 min-h-[32px] rounded-full ring-1 ring-rose-300 " + BTN}>Retry</button>}
        </div>
      )}

      {open && (
        <form onSubmit={(e) => { e.preventDefault(); send(); }} className="space-y-2">
          <div className="flex gap-2 text-xs">
            <button type="button" onClick={() => setKind("ask")} className={"px-3 py-1.5 rounded-full ring-1 " + (kind === "ask" ? "bg-indigo-600 text-white ring-indigo-600" : "ring-slate-300 dark:ring-slate-700")}>Ask / get a hint</button>
            {session.activity && <button type="button" onClick={() => setKind("answer")} className={"px-3 py-1.5 rounded-full ring-1 " + (kind === "answer" ? "bg-indigo-600 text-white ring-indigo-600" : "ring-slate-300 dark:ring-slate-700")}>{items ? "Answer (scored by answer key)" : "Submit solution (will be graded)"}</button>}
          </div>
          {kind === "answer" && items ? (
            <div className="space-y-2">
              {items.map((it) => (
                <fieldset key={it.itemId} className="p-3 rounded-xl ring-1 ring-slate-200 dark:ring-slate-800 text-xs space-y-1.5">
                  <legend className="px-1 font-semibold">{it.itemId}. {it.prompt}</legend>
                  <div className="flex flex-wrap gap-2">
                    {it.choices.map((c) => (
                      <label key={c.key} className={"px-3 py-1.5 rounded-full ring-1 cursor-pointer " + (choices[it.itemId] === c.key ? "bg-indigo-600 text-white ring-indigo-600" : "ring-slate-300 dark:ring-slate-700")}>
                        <input type="radio" className="sr-only" name={"item-" + it.itemId} value={c.key}
                          checked={choices[it.itemId] === c.key}
                          onChange={() => setChoices(Object.assign({}, choices, { [it.itemId]: c.key }))} />
                        {c.key}. {c.text}
                      </label>
                    ))}
                  </div>
                </fieldset>
              ))}
              <div className="flex justify-end">
                <button disabled={!canSend || !answerReady} className={"px-5 min-h-[44px] rounded-full bg-indigo-600 hover:bg-indigo-500 disabled:opacity-50 text-white text-sm font-semibold " + BTN}>Submit answers</button>
              </div>
            </div>
          ) : (
          <div className="flex gap-2">
            <textarea value={S.draft} onChange={(e) => S.setDraft(e.target.value)} rows={kind === "answer" ? 4 : 2}
              placeholder={kind === "answer" ? "Show all your steps; only what you write is assessed…" : "Ask a question; the agent gives hints, not answers…"}
              className="flex-1 bg-white dark:bg-slate-900 ring-1 ring-slate-200 dark:ring-slate-800 rounded-2xl px-4 py-2 text-sm outline-none focus:ring-2 focus:ring-indigo-500" />
            <button disabled={!canSend || !answerReady} className={"self-end px-5 min-h-[44px] rounded-full bg-indigo-600 hover:bg-indigo-500 disabled:opacity-50 text-white text-sm font-semibold " + BTN}>Send</button>
          </div>
          )}
          <div className="text-[10px] text-slate-400 px-2">
            {active ? "Wait for the current request to finish before sending." : S.draftSavedAt ? "Draft saved on this device only; not sent yet." : ""}
            {session.hintCount > 0 ? " " + session.hintCount + " hint(s) used: later answers count as hint-assisted." : ""}
          </div>
          <div className="flex flex-wrap gap-2 pt-1">
            <button type="button" disabled={busy || !session.completion.eligible} onClick={complete}
              className={"px-4 min-h-[40px] rounded-full bg-emerald-600 hover:bg-emerald-500 disabled:opacity-40 text-white text-xs font-semibold " + BTN}>Complete session</button>
            <button type="button" disabled={busy || active} onClick={abandon}
              className={"px-4 min-h-[40px] rounded-full ring-1 ring-slate-300 dark:ring-slate-700 text-xs disabled:opacity-40 " + BTN}>Abandon</button>
            {!session.completion.eligible && <span className="self-center text-[11px] text-slate-500">{COMPLETION_REASON[session.completion.reason] || ""}</span>}
          </div>
        </form>
      )}
    </React.Fragment>
  );
}

const COMPLETION_REASON = {
  accepted_assessment_required: "An accepted assessment is needed before completing.",
  run_in_progress: "Still processing.",
  session_closed: "",
};

function MessageBubble({ message }) {
  const mine = message.role === "student";
  return (
    <div className={"flex " + (mine ? "justify-end" : "justify-start")}>
      <div className={"max-w-[85%] px-3 py-2 rounded-2xl text-sm whitespace-pre-wrap " + (mine ? "bg-indigo-600 text-white" : "bg-slate-100 dark:bg-slate-800 text-slate-800 dark:text-slate-100")}>
        {message.isSubmission && <div className="text-[10px] font-semibold opacity-80 mb-1">Submitted solution</div>}
        {message.synthetic && <div className="text-[10px] font-semibold text-amber-700 dark:text-amber-300 mb-1">Synthetic reply · pipeline testing only, not tutoring or grading</div>}
        {message.text}
      </div>
    </div>
  );
}

function RunLine({ run, architect, onCancel, busy }) {
  const view = HSProvider.describeRun(run);
  return (
    <div className="flex flex-wrap items-center gap-2 text-[11px] pt-1">
      <span className="text-slate-400">{run.kind === "ASSESS_SUBMISSION" ? "Grading" : run.kind === "PLANNING" ? "Planning" : "Reply"}</span>
      <RunStatusBadge run={run} architect={architect} />
      {run.status === "QUEUED" && <span className="text-slate-500">Received, queued…</span>}
      {run.status === "RUNNING" && <span className="text-slate-500">{run.kind === "ASSESS_SUBMISSION" ? "Grading against the rubric…" : "Thinking…"}</span>}
      {run.status === "WAITING_INPUT" && run.inputRequest && <span className="text-amber-700 dark:text-amber-200">{run.inputRequest.prompt}</span>}
      {run.status === "FAILED" && run.error && <span className="text-rose-600 dark:text-rose-300">{HSProvider.errorText(run.error.code)}</span>}
      {run.status === "CANCELLED" && <span className="text-slate-500">Cancelled; no assessment recorded.</span>}
      {onCancel && <button disabled={busy} onClick={onCancel} className={"px-3 min-h-[28px] rounded-full ring-1 ring-slate-300 dark:ring-slate-700 " + BTN}>Cancel</button>}
    </div>
  );
}

const OBSERVATION_LABEL = {
  correct_independent: "Correct, independently",
  correct_with_hint: "Correct after a hint/correction (not independent)",
  partially_correct: "Partially correct",
  incorrect: "Incorrect",
};

function AssessmentCard({ assessment, architect }) {
  const a = assessment;
  const accepted = a.status === "accepted";
  const earned = a.rubricResults.reduce((n, r) => n + r.earned, 0);
  const possible = a.rubricResults.reduce((n, r) => n + r.possible, 0);
  return (
    <section className={CARD + " p-4 space-y-2 text-xs"}>
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div className="font-semibold">Assessment</div>
        <Badge className={accepted ? RUN_TONE.emerald : RUN_TONE.amber}>
          {accepted ? "Accepted (counts toward mastery)" : "Not enough evidence (not counted toward mastery)"}
        </Badge>
      </div>
      {a.feedback && <p className="text-sm leading-relaxed text-slate-700 dark:text-slate-200 whitespace-pre-wrap">{a.feedback}</p>}
      <div className="space-y-1">
        {a.rubricResults.map((r) => (
          <div key={r.criterionId} className="flex justify-between gap-2 text-[11px]">
            <span className="text-slate-600 dark:text-slate-300">{r.criterionId}{r.assessable === false ? " (affected by an earlier error; not assessed on its own)" : ""}</span>
            <span className="font-mono">{r.earned}/{r.possible}</span>
          </div>
        ))}
        <div className="flex justify-between text-[11px] text-slate-500 border-t border-slate-200 dark:border-slate-800 pt-1">
          <span>Rubric points (not an exam score)</span><span className="font-mono">{earned}/{possible}</span>
        </div>
      </div>
      {accepted && a.skillEvidence.length > 0 && (
        <div className="text-[11px] text-slate-600 dark:text-slate-300">
          {a.skillEvidence.map((e) => <div key={e.skillId}>{e.skillId}: {OBSERVATION_LABEL[e.observation] || e.observation}</div>)}
        </div>
      )}
      <div className="text-[10px] text-slate-400">
        Hints {a.hintUsage.serverHintCount} · uncertainty {a.uncertainty.level}
        {architect ? " · " + a.provenance.modelVersion + " · " + a.provenance.workflowVersion + " · rubric v" + a.rubricVersion : ""}
      </div>
    </section>
  );
}
