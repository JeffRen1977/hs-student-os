// features.js — cross-agent features: header, TodayTasks (task list), Twin summary,
// server event feed, course catalog + manifest modals, mobile bottom Tab bar.

function Header({ S }) {
  const profile = S.twin.profile;
  return (
    <header className="sticky top-0 z-40 shrink-0 bg-white/85 dark:bg-slate-900/85 backdrop-blur border-b border-slate-200/70 dark:border-slate-800 px-3 sm:px-4 py-2.5 flex items-center justify-between gap-3">
      <div className="flex items-center gap-3 min-w-0">
        <div className="w-9 h-9 rounded-xl bg-gradient-to-br from-indigo-500 to-violet-600 flex items-center justify-center text-xs font-bold text-white shadow-sm shrink-0">OS</div>
        <div className="min-w-0">
          <div className="text-sm font-bold tracking-tight flex items-center gap-2">
            <span className="truncate">High School Student OS</span>
            {S.demo && <span className="text-[10px] font-mono font-semibold text-amber-700 dark:text-amber-200 bg-amber-100 dark:bg-amber-500/15 ring-1 ring-amber-300 dark:ring-amber-500/30 px-2 py-0.5 rounded-full">DEMO</span>}
          </div>
          <div className="text-[11px] text-slate-500 dark:text-slate-400 truncate">1 Student Record + Per-Course Agents</div>
        </div>
      </div>
      <div className="flex items-center gap-2">
        <div className="hidden xl:flex items-center gap-2 text-xs text-slate-600 dark:text-slate-300 mr-1">
          <span>{profile.displayName} · {profile.grade}th</span>
          {S.twin.goals.satTarget && (
            <React.Fragment>
              <span className="text-slate-300 dark:text-slate-600">|</span>
              <span>SAT target <strong className="text-indigo-600 dark:text-sky-400">{S.twin.goals.satTarget}</strong></span>
            </React.Fragment>
          )}
        </div>
        <div className="hidden sm:flex bg-slate-100 dark:bg-slate-950 ring-1 ring-slate-200 dark:ring-slate-800 rounded-full p-0.5 text-[11px]">
          <button onClick={() => S.setView("student")} className={"px-2.5 py-1.5 rounded-full transition active:scale-95 " + (S.view === "student" ? "bg-white dark:bg-slate-700 text-slate-900 dark:text-white shadow-sm" : "text-slate-500 dark:text-slate-400")}>Student view</button>
          <button onClick={() => S.setView("architect")} className={"px-2.5 py-1.5 rounded-full transition active:scale-95 " + (S.view === "architect" ? "bg-white dark:bg-slate-700 text-slate-900 dark:text-white shadow-sm" : "text-slate-500 dark:text-slate-400")}>Architect view</button>
        </div>
        <button onClick={() => S.setShowManifest(true)} className={"hidden md:inline-flex px-3 min-h-[36px] items-center rounded-full text-xs ring-1 ring-slate-300 dark:ring-slate-700 text-slate-700 dark:text-slate-200 hover:bg-slate-100 dark:hover:bg-slate-800 " + BTN}>Twin summary</button>
        <button onClick={() => S.setShowCatalog(true)} className={"px-3 min-h-[36px] rounded-full text-xs font-semibold bg-indigo-600 hover:bg-indigo-500 text-white shadow-sm " + BTN}>Course catalog ({S.enrolledIds.length} enrolled)</button>
        <button onClick={S.toggleDark} aria-label="Toggle dark mode" className={"w-9 h-9 shrink-0 rounded-full ring-1 ring-slate-300 dark:ring-slate-700 flex items-center justify-center text-sm hover:bg-slate-100 dark:hover:bg-slate-800 " + BTN}>{S.dark ? "☀️" : "🌙"}</button>
      </div>
    </header>
  );
}

const TASK_STATUS_LABEL = { PLANNED: "Not started", IN_PROGRESS: "In progress", COMPLETED: "Completed", SKIPPED: "Skipped" };
const TASK_KIND = {
  PRACTICE: { label: "Practice", tone: "bg-emerald-100 text-emerald-800 dark:bg-emerald-500/20 dark:text-emerald-200" },
  DIAGNOSTIC: { label: "Diagnostic", tone: "bg-amber-100 text-amber-800 dark:bg-amber-500/20 dark:text-amber-200" },
  REINFORCEMENT: { label: "Reinforcement", tone: "bg-sky-100 text-sky-800 dark:bg-sky-500/20 dark:text-sky-200" },
};

function TaskRow({ task, run, active, architect, onOpen, S }) {
  const meta = HSData.getPackMeta(task.courseId, S.courseName(task.courseId));
  const tone = task.mode === "EXAM_CRUNCH" ? "text-rose-500 dark:text-rose-400" : "text-emerald-600 dark:text-emerald-400";
  return (
    <button onClick={() => onOpen(task)}
      className={"w-full min-h-[44px] text-left px-3 py-2 rounded-xl ring-1 transition active:scale-[0.99] " + (active ? "bg-white dark:bg-slate-800 ring-indigo-400 dark:ring-indigo-500 shadow-sm" : "bg-white/60 dark:bg-slate-950/60 ring-slate-200/80 dark:ring-slate-800 hover:ring-indigo-300 dark:hover:ring-indigo-500/50")}>
      <div className="flex justify-between gap-2 text-[10px]">
        <span className="text-slate-500 dark:text-slate-400">{meta.icon} {meta.shortName} · {TASK_STATUS_LABEL[task.status]}{architect ? " · " + task.taskId : ""}</span>
        <span className={tone}>{task.durationMin}m</span>
      </div>
      <div className="text-[11px] font-semibold text-slate-800 dark:text-white leading-snug">
        {TASK_KIND[task.taskType] && <span className={"mr-1 px-1.5 py-0.5 rounded-full text-[9px] " + TASK_KIND[task.taskType].tone}>{TASK_KIND[task.taskType].label}</span>}
        {task.title}
      </div>
      {task.reason && task.reason.explanation && <div className="mt-0.5 text-[10px] text-slate-500 dark:text-slate-400 line-clamp-2">{task.reason.explanation}</div>}
      <div className="mt-0.5 text-[10px] text-slate-400">{task.scheduledDate}{task.studentLocked ? " · date locked" : ""}</div>
      {run && <div className="mt-1"><RunStatusBadge run={run} architect={architect} /></div>}
    </button>
  );
}

function PreviewRow({ preview, active, onOpen }) {
  return (
    <button onClick={() => onOpen(preview)}
      className={"w-full min-h-[44px] text-left px-3 py-2 rounded-xl ring-1 ring-dashed transition active:scale-[0.99] " + (active ? "bg-white dark:bg-slate-800 ring-indigo-400" : "bg-white/40 dark:bg-slate-950/40 ring-slate-300 dark:ring-slate-700")}>
      <div className="flex justify-between gap-2 text-[10px] text-slate-400"><span>Preview · planned</span><span>{preview.durationMin}m</span></div>
      <div className="text-[11px] font-semibold text-slate-600 dark:text-slate-300 leading-snug">{preview.title}</div>
    </button>
  );
}

function TodayTasks({ S }) {
  const architect = S.architect;
  return (
    <aside className={(S.mobileTab === "tasks" ? "block" : "hidden") + " md:block md:row-span-2 lg:row-span-1 overflow-y-auto p-3 space-y-3 md:border-r border-slate-200/70 dark:border-slate-800"}>
      <div className="flex sm:hidden bg-slate-100 dark:bg-slate-900 ring-1 ring-slate-200 dark:ring-slate-800 rounded-full p-0.5 text-[11px] mb-1">
        <button onClick={() => S.setView("student")} className={"flex-1 px-2.5 py-2 rounded-full transition active:scale-95 " + (S.view === "student" ? "bg-white dark:bg-slate-700 text-slate-900 dark:text-white shadow-sm" : "text-slate-500 dark:text-slate-400")}>Student view</button>
        <button onClick={() => S.setView("architect")} className={"flex-1 px-2.5 py-2 rounded-full transition active:scale-95 " + (S.view === "architect" ? "bg-white dark:bg-slate-700 text-slate-900 dark:text-white shadow-sm" : "text-slate-500 dark:text-slate-400")}>Architect view</button>
      </div>
      <div className="text-[11px] font-semibold uppercase tracking-wide text-slate-500 dark:text-slate-400">Today's tasks</div>

      <div className={"rounded-2xl ring-1 p-3 space-y-2.5 transition " + (S.activeAgent === "AP_BASE" ? "bg-indigo-50 dark:bg-indigo-950/30 ring-indigo-200 dark:ring-indigo-500/50" : CARD + " ring-slate-900/5")}>
        <div className="flex justify-between items-center">
          <span className="text-xs font-semibold">My courses</span>
          <span className="text-[10px] text-indigo-600 dark:text-indigo-300">{S.apTasks.length} tasks</span>
        </div>
        <div className="flex flex-wrap gap-1.5">
          {S.enrolledIds.map((cid) => {
            const meta = HSData.getPackMeta(cid, S.courseName(cid));
            return (
              <button key={cid} onClick={() => S.selectCourse(cid)}
                className={"px-2.5 py-1 rounded-full text-[10px] ring-1 transition active:scale-95 " + (S.activeAgent === "AP_BASE" && S.activeCourse === cid ? "bg-indigo-600 text-white ring-indigo-500" : "bg-white dark:bg-slate-950 text-slate-600 dark:text-slate-300 ring-slate-200 dark:ring-slate-800 hover:ring-indigo-300")}>
                {meta.icon} {meta.shortName}
              </button>
            );
          })}
          <button onClick={() => S.setShowCatalog(true)} className="px-2.5 py-1 rounded-full text-[10px] ring-1 ring-dashed ring-slate-300 dark:ring-slate-700 text-slate-500 dark:text-slate-400 transition active:scale-95">+ Course</button>
        </div>
        <div className="space-y-1.5">
          {S.apTasks.map((t) => (
            <TaskRow key={t.taskId} task={t} run={S.runForTask(t.taskId)} active={S.currentTask && S.currentTask.taskId === t.taskId} architect={architect} onOpen={S.openTask} S={S} />
          ))}
          {S.apTasks.length === 0 && <div className="text-[11px] text-slate-500">No tasks for your enrolled courses yet.</div>}
        </div>
      </div>

      {S.satPreviews.length > 0 && (
        <div className={CARD + " p-3 space-y-2.5"}>
          <div className="flex justify-between items-center">
            <button onClick={() => S.selectAgent("DSAT")} className="text-xs font-semibold text-left">Digital SAT</button>
            <span className="text-[10px] text-slate-400">Planned (M3)</span>
          </div>
          <div className="space-y-1.5">
            {S.satPreviews.map((p) => <PreviewRow key={p.id} preview={p} active={S.currentPreview && S.currentPreview.id === p.id} onOpen={S.openPreview} />)}
          </div>
        </div>
      )}

      {S.admPreviews.length > 0 && (
        <div className={CARD + " p-3 space-y-2.5"}>
          <div className="flex justify-between items-center">
            <button onClick={() => S.selectAgent("ADMISSIONS")} className="text-xs font-semibold text-left">Admissions</button>
            <span className="text-[10px] text-slate-400">Planned (M5)</span>
          </div>
          <div className="space-y-1.5">
            {S.admPreviews.map((p) => <PreviewRow key={p.id} preview={p} active={S.currentPreview && S.currentPreview.id === p.id} onOpen={S.openPreview} />)}
          </div>
        </div>
      )}
    </aside>
  );
}

const MASTERY_LABEL = { insufficient_evidence: "Not enough evidence", emerging: "Emerging", developing: "Developing", proficient: "Proficient" };

function TwinSummary({ S }) {
  const mastery = Object.entries(S.twin.masterySummary || {});
  return (
    <section className={CARD + " p-4 space-y-2.5"}>
      <div className="text-xs font-bold text-indigo-600 dark:text-indigo-300">Student record</div>
      {S.architect && <div className="text-[10px] font-mono text-slate-400 dark:text-slate-500">students/{S.twin.studentId} · v{S.twin.version}</div>}
      <div className="text-[11px] text-slate-500 dark:text-slate-400">Exam prediction</div>
      {S.enrolledIds.map((cid) => {
        const meta = HSData.getPackMeta(cid, S.courseName(cid));
        return (
          <div key={cid} className="flex justify-between items-center text-xs bg-slate-50 dark:bg-slate-950 ring-1 ring-slate-200/60 dark:ring-slate-800 px-3 py-2 rounded-xl">
            <span>{meta.icon} {meta.shortName}</span>
            <PredictionBadge entry={(S.twin.predictionSummary || {})[cid]} />
          </div>
        );
      })}
      <div className="text-[11px] text-slate-500 dark:text-slate-400 pt-1">Skill mastery (independent evidence count)</div>
      {mastery.length === 0 && <div className="text-[11px] text-slate-400">No assessed evidence yet.</div>}
      {mastery.map(([skillId, m]) => (
        <div key={skillId} className="flex justify-between items-center text-[11px] px-1">
          <span className="font-mono text-slate-600 dark:text-slate-300 truncate">{skillId.split(".").slice(1).join(".")}</span>
          <span className="text-slate-500 dark:text-slate-400">{MASTERY_LABEL[m.level] || m.level} · {m.independentEvidenceCount}</span>
        </div>
      ))}
    </section>
  );
}

const PLACEMENT_LABEL = { fixed: "Fixed", kept: "Kept", moved: "Moved", deferred: "Deferred", over_budget: "Over time budget" };

// The latest server plan with a reason for every placement (Step 25/27). Never replans on read.
function PlanCard({ S }) {
  if (S.demo) return null;
  const plan = S.plan;
  return (
    <section className={CARD + " p-4 space-y-2.5"}>
      <div className="flex justify-between items-center">
        <div className="text-xs font-bold text-indigo-600 dark:text-indigo-300">This week's plan</div>
        <button disabled={S.planBusy} onClick={S.replan} className={"px-3 min-h-[30px] rounded-full text-[11px] ring-1 ring-indigo-300 dark:ring-indigo-500/50 disabled:opacity-50 " + BTN}>{S.planBusy ? "Replanning…" : "Replan"}</button>
      </div>
      {S.actionError && <div role="alert" className="text-[11px] text-rose-600 dark:text-rose-300">{HSProvider.errorText(S.actionError.code)}</div>}
      {!plan && <div className="text-[11px] text-slate-400">No plan yet. Click “Replan” to order your tasks by deadlines, evidence gaps and your weekly time.</div>}
      {plan && (
        <React.Fragment>
          <div className="text-[10px] text-slate-500">7 days from {plan.localDate} · about {plan.dailyMinutes} min a day ({plan.weeklyMinutes} a week){plan.evidenceAvailable ? "" : " · no assessed evidence yet, so ordered conservatively"}</div>
          {plan.entries.map((e) => {
            const t = S.taskById(e.taskId);
            return (
              <div key={e.taskId} className="text-[11px] border-t border-slate-200/70 dark:border-slate-800 pt-1.5">
                <div className="flex justify-between gap-2">
                  <span className="font-semibold text-slate-700 dark:text-slate-200 truncate">{t ? t.title : e.taskId}</span>
                  <span className="text-slate-500 whitespace-nowrap">{e.scheduledDate} · {PLACEMENT_LABEL[e.placement] || e.placement}</span>
                </div>
                <div className="text-slate-500 dark:text-slate-400 leading-relaxed">{e.explanation}</div>
                {S.architect && e.sourceEventIds.length > 0 && <div className="font-mono text-[10px] text-slate-400">Source events {e.sourceEventIds.join(", ")}</div>}
              </div>
            );
          })}
          {S.architect && <div className="font-mono text-[10px] text-slate-400">{plan.planId} · {plan.ruleVersion}</div>}
        </React.Fragment>
      )}
    </section>
  );
}

function plainEvent(type) {
  return {
    "course.enrolled": "Enrolled in a course",
    "course.unenrolled": "Left a course",
    "session.started": "Started a practice session",
    "session.completed": "Session completed",
    "session.abandoned": "Session abandoned",
    "run.queued": "Submitted, queued",
    "run.started": "Grading started",
    "run.waiting_input": "Needs your confirmation",
    "run.completed": "Grading run finished",
    "run.failed": "Grading failed",
    "run.cancelled": "Cancelled",
    "assessment.completed": "Assessment ready",
    "mastery.updated": "Mastery updated",
    "plan.updated": "Plan updated",
  }[type] || "Learning record updated";
}

function describeEvent(e) {
  const p = e.payload || {};
  if (e.type === "course.enrolled" || e.type === "course.unenrolled") return p.courseId;
  if (e.type === "run.failed") return "Error " + p.errorCode + (p.retryable ? ", can retry" : "");
  if (e.type === "assessment.completed") return p.status === "accepted" ? "Assessment accepted" : "Not enough evidence; mastery not updated";
  if (e.type === "plan.updated") return (p.changedTaskIds || []).length + " tasks changed";
  if (p.taskId) return p.taskId;
  return "";
}

function formatTime(iso) {
  try {
    return new Date(iso).toLocaleString(undefined, { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" });
  } catch (_e) {
    return iso;
  }
}

function EventFeed({ S }) {
  const events = S.events.slice().reverse();
  return (
    <section className="space-y-2">
      <div className="text-[11px] font-semibold uppercase tracking-wide text-slate-500 dark:text-slate-400">Learning events</div>
      {S.demoNotes.length > 0 && (
        <div className="space-y-1.5">
          <div className="text-[10px] text-amber-700 dark:text-amber-300">Local demo action · not saved to the server</div>
          {S.demoNotes.map((n) => (
            <article key={n.id} className="p-2.5 rounded-xl ring-1 ring-dashed ring-amber-300 dark:ring-amber-500/40 text-[11px] text-slate-600 dark:text-slate-300">{n.text}</article>
          ))}
        </div>
      )}
      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-1 gap-2">
        {events.length === 0 && <div className="text-[11px] text-slate-400">No events yet.</div>}
        {events.map((e) => (
          <article key={e.eventId} className={CARD + " p-3 text-[11px] space-y-1"}>
            <div className="flex justify-between gap-2">
              {S.architect ? <span className="font-mono text-indigo-600 dark:text-indigo-300">#{e.sequence} {e.type}</span> : <span className="text-indigo-600 dark:text-indigo-200">{plainEvent(e.type)}</span>}
              <span className="text-slate-400 dark:text-slate-500">{formatTime(e.occurredAt)}</span>
            </div>
            <div className="text-slate-700 dark:text-slate-200 leading-relaxed">{describeEvent(e)}</div>
          </article>
        ))}
      </div>
    </section>
  );
}

function TwinAside({ S }) {
  return (
    <aside className={(S.mobileTab === "events" ? "block" : "hidden") + " md:block md:col-span-2 lg:col-span-1 overflow-y-auto p-3 space-y-3 lg:border-l border-slate-200/70 dark:border-slate-800"}>
      <TwinSummary S={S} />
      <PlanCard S={S} />
      <EventFeed S={S} />
    </aside>
  );
}

function MobileTabs({ S }) {
  const tabBtn = (tab, agent, icon, label) => (
    <button onClick={() => S.goMobile(tab, agent)}
      className={"flex-1 min-h-[56px] flex flex-col items-center justify-center gap-0.5 text-[10px] font-medium transition active:scale-95 " + (S.mobileTab === tab ? "text-indigo-600 dark:text-indigo-400" : "text-slate-500 dark:text-slate-400")}>
      <span className="text-lg leading-none">{icon}</span>
      <span>{label}</span>
    </button>
  );
  return (
    <nav className="md:hidden fixed bottom-0 inset-x-0 z-40 bg-white/92 dark:bg-slate-900/92 backdrop-blur border-t border-slate-200 dark:border-slate-800 flex px-1 pb-[env(safe-area-inset-bottom)]">
      {tabBtn("tasks", null, "📋", "Today")}
      {tabBtn("ap", "AP_BASE", "📚", "AP")}
      {S.satPreviews.length > 0 && tabBtn("sat", "DSAT", "🎯", "SAT")}
      {S.admPreviews.length > 0 && tabBtn("adm", "ADMISSIONS", "🎓", "Admissions")}
      {tabBtn("events", null, "🔔", "Events")}
    </nav>
  );
}

// Course catalog (API.md §1.7): availability and entitlement decide what can be added.
function catalogState(course) {
  if (course.availability !== "active") return { label: "Coming soon", can: false };
  if (!course.entitled) return { label: "Access required", can: false };
  if (course.enrolled) return { label: "Enrolled · click to remove", can: true };
  return { label: "Click to add", can: true };
}

function CatalogModal({ S }) {
  return (
    <Modal title="Course catalog" onClose={() => S.setShowCatalog(false)}>
      <p className="text-[11px] text-slate-500 dark:text-slate-400">You can add only courses that are open and that you have access to. Access is managed by the school; choosing a course does not grant access.</p>
      {S.actionError && <p className="text-[11px] text-rose-600 dark:text-rose-300">{HSProvider.errorText(S.actionError.code)}</p>}
      <div className="grid grid-cols-2 gap-2">
        {S.catalog.map((c) => {
          const meta = HSData.getPackMeta(c.courseId, c.name);
          const state = catalogState(c);
          const enabled = state.can;
          return (
            <button key={c.courseId} disabled={!enabled} onClick={() => S.toggleEnrollment(c.courseId)}
              className={"min-h-[44px] p-3 rounded-2xl ring-1 text-left text-xs transition " + (c.enrolled ? "bg-indigo-50 dark:bg-indigo-950/50 ring-indigo-400 dark:ring-indigo-500" : "bg-slate-50 dark:bg-slate-950 ring-slate-200 dark:ring-slate-800") + (enabled ? " active:scale-[0.98]" : " opacity-60 cursor-not-allowed")}>
              <div className="font-semibold">{meta.icon} {c.name}</div>
              <div className="text-[10px] mt-1 text-slate-500 dark:text-slate-400 line-clamp-2">{c.description}</div>
              <div className="text-[10px] mt-1">{state.label}</div>
            </button>
          );
        })}
      </div>
      <button onClick={() => S.setShowCatalog(false)} className={"w-full min-h-[44px] py-2 rounded-full bg-indigo-600 hover:bg-indigo-500 text-white text-xs font-semibold shadow-sm " + BTN}>Done</button>
    </Modal>
  );
}

function ManifestModal({ S }) {
  return (
    <Modal title="Twin summary (GET /api/twin)" onClose={() => S.setShowManifest(false)}>
      <pre className="text-[11px] leading-relaxed text-slate-600 dark:text-slate-300 whitespace-pre-wrap font-mono">{JSON.stringify({
        twin: S.twin,
        entitlements: S.entitlements,
        enrolledCourses: S.enrolledIds,
        lastAppliedEventSequence: S.lastSequence,
        active: { agent: S.activeAgent, course: S.activeCourse, task: S.currentTask && S.currentTask.taskId, session: S.currentSession && S.currentSession.sessionId, run: S.currentRun && S.currentRun.runId },
      }, null, 2)}</pre>
    </Modal>
  );
}
