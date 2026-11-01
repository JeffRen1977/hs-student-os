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
              <span>SAT 目标 <strong className="text-indigo-600 dark:text-sky-400">{S.twin.goals.satTarget}</strong></span>
            </React.Fragment>
          )}
        </div>
        <div className="hidden sm:flex bg-slate-100 dark:bg-slate-950 ring-1 ring-slate-200 dark:ring-slate-800 rounded-full p-0.5 text-[11px]">
          <button onClick={() => S.setView("student")} className={"px-2.5 py-1.5 rounded-full transition active:scale-95 " + (S.view === "student" ? "bg-white dark:bg-slate-700 text-slate-900 dark:text-white shadow-sm" : "text-slate-500 dark:text-slate-400")}>学生视图</button>
          <button onClick={() => S.setView("architect")} className={"px-2.5 py-1.5 rounded-full transition active:scale-95 " + (S.view === "architect" ? "bg-white dark:bg-slate-700 text-slate-900 dark:text-white shadow-sm" : "text-slate-500 dark:text-slate-400")}>架构师视图</button>
        </div>
        <button onClick={() => S.setShowManifest(true)} className={"hidden md:inline-flex px-3 min-h-[36px] items-center rounded-full text-xs ring-1 ring-slate-300 dark:ring-slate-700 text-slate-700 dark:text-slate-200 hover:bg-slate-100 dark:hover:bg-slate-800 " + BTN}>Twin 摘要</button>
        <button onClick={() => S.setShowCatalog(true)} className={"px-3 min-h-[36px] rounded-full text-xs font-semibold bg-indigo-600 hover:bg-indigo-500 text-white shadow-sm " + BTN}>课程目录 ({S.enrolledIds.length} 已注册)</button>
        <button onClick={S.toggleDark} aria-label="切换深色模式" className={"w-9 h-9 shrink-0 rounded-full ring-1 ring-slate-300 dark:ring-slate-700 flex items-center justify-center text-sm hover:bg-slate-100 dark:hover:bg-slate-800 " + BTN}>{S.dark ? "☀️" : "🌙"}</button>
      </div>
    </header>
  );
}

const TASK_STATUS_LABEL = { PLANNED: "未开始", IN_PROGRESS: "进行中", COMPLETED: "已完成", SKIPPED: "已跳过" };

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
      <div className="text-[11px] font-semibold text-slate-800 dark:text-white leading-snug">{task.title}</div>
      {run && <div className="mt-1"><RunStatusBadge run={run} architect={architect} /></div>}
    </button>
  );
}

function PreviewRow({ preview, active, onOpen }) {
  return (
    <button onClick={() => onOpen(preview)}
      className={"w-full min-h-[44px] text-left px-3 py-2 rounded-xl ring-1 ring-dashed transition active:scale-[0.99] " + (active ? "bg-white dark:bg-slate-800 ring-indigo-400" : "bg-white/40 dark:bg-slate-950/40 ring-slate-300 dark:ring-slate-700")}>
      <div className="flex justify-between gap-2 text-[10px] text-slate-400"><span>预览 · 规划中</span><span>{preview.durationMin}m</span></div>
      <div className="text-[11px] font-semibold text-slate-600 dark:text-slate-300 leading-snug">{preview.title}</div>
    </button>
  );
}

function TodayTasks({ S }) {
  const architect = S.architect;
  return (
    <aside className={(S.mobileTab === "tasks" ? "block" : "hidden") + " md:block md:row-span-2 lg:row-span-1 overflow-y-auto p-3 space-y-3 md:border-r border-slate-200/70 dark:border-slate-800"}>
      <div className="flex sm:hidden bg-slate-100 dark:bg-slate-900 ring-1 ring-slate-200 dark:ring-slate-800 rounded-full p-0.5 text-[11px] mb-1">
        <button onClick={() => S.setView("student")} className={"flex-1 px-2.5 py-2 rounded-full transition active:scale-95 " + (S.view === "student" ? "bg-white dark:bg-slate-700 text-slate-900 dark:text-white shadow-sm" : "text-slate-500 dark:text-slate-400")}>学生视图</button>
        <button onClick={() => S.setView("architect")} className={"flex-1 px-2.5 py-2 rounded-full transition active:scale-95 " + (S.view === "architect" ? "bg-white dark:bg-slate-700 text-slate-900 dark:text-white shadow-sm" : "text-slate-500 dark:text-slate-400")}>架构师视图</button>
      </div>
      <div className="text-[11px] font-semibold uppercase tracking-wide text-slate-500 dark:text-slate-400">今日任务</div>

      <div className={"rounded-2xl ring-1 p-3 space-y-2.5 transition " + (S.activeAgent === "AP_BASE" ? "bg-indigo-50 dark:bg-indigo-950/30 ring-indigo-200 dark:ring-indigo-500/50" : CARD + " ring-slate-900/5")}>
        <div className="flex justify-between items-center">
          <span className="text-xs font-semibold">AP 课程</span>
          <span className="text-[10px] text-indigo-600 dark:text-indigo-300">{S.apTasks.length} 个任务</span>
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
          <button onClick={() => S.setShowCatalog(true)} className="px-2.5 py-1 rounded-full text-[10px] ring-1 ring-dashed ring-slate-300 dark:ring-slate-700 text-slate-500 dark:text-slate-400 transition active:scale-95">+ 课程</button>
        </div>
        <div className="space-y-1.5">
          {S.apTasks.map((t) => (
            <TaskRow key={t.taskId} task={t} run={S.runForTask(t.taskId)} active={S.currentTask && S.currentTask.taskId === t.taskId} architect={architect} onOpen={S.openTask} S={S} />
          ))}
          {S.apTasks.length === 0 && <div className="text-[11px] text-slate-500">还没有已注册课程的任务。</div>}
        </div>
      </div>

      {S.satPreviews.length > 0 && (
        <div className={CARD + " p-3 space-y-2.5"}>
          <div className="flex justify-between items-center">
            <button onClick={() => S.selectAgent("DSAT")} className="text-xs font-semibold text-left">Digital SAT</button>
            <span className="text-[10px] text-slate-400">规划中（M3）</span>
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
            <span className="text-[10px] text-slate-400">规划中（M5）</span>
          </div>
          <div className="space-y-1.5">
            {S.admPreviews.map((p) => <PreviewRow key={p.id} preview={p} active={S.currentPreview && S.currentPreview.id === p.id} onOpen={S.openPreview} />)}
          </div>
        </div>
      )}
    </aside>
  );
}

const MASTERY_LABEL = { insufficient_evidence: "证据不足", emerging: "起步", developing: "发展中", proficient: "熟练" };

function TwinSummary({ S }) {
  const mastery = Object.entries(S.twin.masterySummary || {});
  return (
    <section className={CARD + " p-4 space-y-2.5"}>
      <div className="text-xs font-bold text-indigo-600 dark:text-indigo-300">学生记录</div>
      {S.architect && <div className="text-[10px] font-mono text-slate-400 dark:text-slate-500">students/{S.twin.studentId} · v{S.twin.version}</div>}
      <div className="text-[11px] text-slate-500 dark:text-slate-400">AP 考试预测</div>
      {S.enrolledIds.map((cid) => {
        const meta = HSData.getPackMeta(cid, S.courseName(cid));
        return (
          <div key={cid} className="flex justify-between items-center text-xs bg-slate-50 dark:bg-slate-950 ring-1 ring-slate-200/60 dark:ring-slate-800 px-3 py-2 rounded-xl">
            <span>{meta.icon} {meta.shortName}</span>
            <PredictionBadge entry={(S.twin.predictionSummary || {})[cid]} />
          </div>
        );
      })}
      <div className="text-[11px] text-slate-500 dark:text-slate-400 pt-1">技能掌握度（独立证据数）</div>
      {mastery.length === 0 && <div className="text-[11px] text-slate-400">还没有评估证据。</div>}
      {mastery.map(([skillId, m]) => (
        <div key={skillId} className="flex justify-between items-center text-[11px] px-1">
          <span className="font-mono text-slate-600 dark:text-slate-300 truncate">{skillId.split(".").slice(1).join(".")}</span>
          <span className="text-slate-500 dark:text-slate-400">{MASTERY_LABEL[m.level] || m.level} · {m.independentEvidenceCount}</span>
        </div>
      ))}
      <div className="mt-2 p-3 rounded-xl bg-slate-50 dark:bg-slate-950 ring-1 ring-slate-200 dark:ring-slate-800 text-[11px] text-slate-500 dark:text-slate-400 leading-relaxed">
        <div className="font-semibold text-slate-600 dark:text-slate-300 mb-1">Planner</div>
        Planner 尚未接入（M3）。任务的排序与理由将由服务端生成并说明来源。
      </div>
    </section>
  );
}

function plainEvent(type) {
  return {
    "course.enrolled": "已注册课程",
    "course.unenrolled": "已取消注册",
    "session.started": "开始了一次练习",
    "session.completed": "这一节已完成",
    "session.abandoned": "这一节已放弃",
    "run.queued": "已提交，排队中",
    "run.started": "开始批改",
    "run.waiting_input": "需要你确认",
    "run.completed": "批改执行完成",
    "run.failed": "批改失败",
    "run.cancelled": "已取消",
    "assessment.completed": "评估结果已生成",
    "mastery.updated": "掌握度已更新",
    "prerequisite.suspected": "建议做一次 SAT 诊断",
    "prerequisite.confirmed": "诊断确认了前置技能",
    "prerequisite.unsupported": "诊断未支持该推测",
    "plan.updated": "计划已更新",
  }[type] || "学习记录更新";
}

function describeEvent(e) {
  const p = e.payload || {};
  if (e.type === "course.enrolled" || e.type === "course.unenrolled") return p.courseId;
  if (e.type === "run.failed") return "错误 " + p.errorCode + (p.retryable ? "，可以重试" : "");
  if (e.type === "assessment.completed") return p.status === "accepted" ? "评估已接受" : "证据不足，未更新掌握度";
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
      <div className="text-[11px] font-semibold uppercase tracking-wide text-slate-500 dark:text-slate-400">学习事件</div>
      {S.demoNotes.length > 0 && (
        <div className="space-y-1.5">
          <div className="text-[10px] text-amber-700 dark:text-amber-300">本地演示操作 · 未保存到服务器</div>
          {S.demoNotes.map((n) => (
            <article key={n.id} className="p-2.5 rounded-xl ring-1 ring-dashed ring-amber-300 dark:ring-amber-500/40 text-[11px] text-slate-600 dark:text-slate-300">{n.text}</article>
          ))}
        </div>
      )}
      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-1 gap-2">
        {events.length === 0 && <div className="text-[11px] text-slate-400">还没有事件。</div>}
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
      {tabBtn("tasks", null, "📋", "今日任务")}
      {tabBtn("ap", "AP_BASE", "📚", "AP")}
      {S.satPreviews.length > 0 && tabBtn("sat", "DSAT", "🎯", "SAT")}
      {S.admPreviews.length > 0 && tabBtn("adm", "ADMISSIONS", "🎓", "申请")}
      {tabBtn("events", null, "🔔", "记录")}
    </nav>
  );
}

// Course catalog (API.md §1.7): availability and entitlement decide what can be added.
function catalogState(course) {
  if (course.availability !== "active") return { label: "即将上线", can: false };
  if (!course.entitled) return { label: "需要开通权限", can: false };
  if (course.enrolled) return { label: "已注册 · 点击移除", can: true };
  return { label: "点击添加", can: true };
}

function CatalogModal({ S }) {
  return (
    <Modal title="课程目录" onClose={() => S.setShowCatalog(false)}>
      <p className="text-[11px] text-slate-500 dark:text-slate-400">只有已开放、且你已获得权限的课程才能添加。权限由后台管理，选择课程不等于开通权限。</p>
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
      <button onClick={() => S.setShowCatalog(false)} className={"w-full min-h-[44px] py-2 rounded-full bg-indigo-600 hover:bg-indigo-500 text-white text-xs font-semibold shadow-sm " + BTN}>完成</button>
    </Modal>
  );
}

function ManifestModal({ S }) {
  return (
    <Modal title="Twin 摘要（GET /api/twin）" onClose={() => S.setShowManifest(false)}>
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
