// features.js — cross-agent features: header, TodayTasks (Planner task list),
// Twin summary, cross-domain event feed, subscription + manifest modals,
// mobile bottom Tab bar.

function Header({ S, student }) {
  return (
    <header className="sticky top-0 z-40 shrink-0 bg-white/85 dark:bg-slate-900/85 backdrop-blur border-b border-slate-200/70 dark:border-slate-800 px-3 sm:px-4 py-2.5 flex items-center justify-between gap-3">
      <div className="flex items-center gap-3 min-w-0">
        <div className="w-9 h-9 rounded-xl bg-gradient-to-br from-indigo-500 to-violet-600 flex items-center justify-center text-xs font-bold text-white shadow-sm shrink-0">OS</div>
        <div className="min-w-0">
          <div className="text-sm font-bold tracking-tight flex items-center gap-2">
            <span className="truncate">High School Student OS</span>
            <span className="hidden lg:inline text-[10px] font-mono font-medium text-indigo-600 dark:text-indigo-300 bg-indigo-50 dark:bg-indigo-500/15 ring-1 ring-indigo-200 dark:ring-indigo-500/30 px-2 py-0.5 rounded-full">Multi-Agent Runtime v2.4</span>
          </div>
          <div className="text-[11px] text-slate-500 dark:text-slate-400 truncate">1 Core Twin + Dynamic Subscribed Agents</div>
        </div>
      </div>
      <div className="flex items-center gap-2">
        <div className="hidden xl:flex items-center gap-2 text-xs text-slate-600 dark:text-slate-300 mr-1">
          <span>{student.name} · {student.grade}th</span>
          <span className="text-slate-300 dark:text-slate-600">|</span>
          <span>GPA <strong className="text-emerald-600 dark:text-emerald-400">{student.gpa}</strong></span>
          <span className="text-slate-300 dark:text-slate-600">|</span>
          <span>dSAT <strong className="text-indigo-600 dark:text-sky-400">{student.satCurrent} → {student.satTarget}</strong></span>
        </div>
        <div className="hidden sm:flex bg-slate-100 dark:bg-slate-950 ring-1 ring-slate-200 dark:ring-slate-800 rounded-full p-0.5 text-[11px]">
          <button onClick={() => S.setView("student")} className={"px-2.5 py-1.5 rounded-full transition active:scale-95 " + (S.view === "student" ? "bg-white dark:bg-slate-700 text-slate-900 dark:text-white shadow-sm" : "text-slate-500 dark:text-slate-400")}>学生视图</button>
          <button onClick={() => S.setView("architect")} className={"px-2.5 py-1.5 rounded-full transition active:scale-95 " + (S.view === "architect" ? "bg-white dark:bg-slate-700 text-slate-900 dark:text-white shadow-sm" : "text-slate-500 dark:text-slate-400")}>架构师视图</button>
        </div>
        <button onClick={() => S.setShowManifest(true)} className={"hidden md:inline-flex px-3 min-h-[36px] items-center rounded-full text-xs ring-1 ring-slate-300 dark:ring-slate-700 text-slate-700 dark:text-slate-200 hover:bg-slate-100 dark:hover:bg-slate-800 " + BTN}>Manifest 透视</button>
        <button onClick={() => S.setShowSubModal(true)} className={"px-3 min-h-[36px] rounded-full text-xs font-semibold bg-indigo-600 hover:bg-indigo-500 text-white shadow-sm " + BTN}>订阅与课程包挂载 ({S.mountedCount})</button>
        <button onClick={S.toggleDark} aria-label="切换深色模式" className={"w-9 h-9 shrink-0 rounded-full ring-1 ring-slate-300 dark:ring-slate-700 flex items-center justify-center text-sm hover:bg-slate-100 dark:hover:bg-slate-800 " + BTN}>{S.dark ? "☀️" : "🌙"}</button>
      </div>
    </header>
  );
}

function TaskRow({ session, active, architect, onOpen, packs }) {
  const course = packs[session.courseId];
  const tone = session.mode === "EXAM_CRUNCH" ? "text-rose-500 dark:text-rose-400" : "text-emerald-600 dark:text-emerald-400";
  return (
    <button onClick={() => onOpen(session)}
      className={"w-full min-h-[44px] text-left px-3 py-2 rounded-xl ring-1 transition active:scale-[0.99] " + (active ? "bg-white dark:bg-slate-800 ring-indigo-400 dark:ring-indigo-500 shadow-sm" : "bg-white/60 dark:bg-slate-950/60 ring-slate-200/80 dark:ring-slate-800 hover:ring-indigo-300 dark:hover:ring-indigo-500/50")}>
      <div className="flex justify-between gap-2 text-[10px]">
        <span className="text-slate-500 dark:text-slate-400">{course ? course.icon + " " + course.shortName : MODE_LABEL[session.mode]}{architect ? " #" + session.num : ""}</span>
        <span className={tone}>{session.duration}</span>
      </div>
      <div className="text-[11px] font-semibold text-slate-800 dark:text-white leading-snug">{session.title}</div>
    </button>
  );
}

function TodayTasks({ S, packs }) {
  const architect = S.architect;
  const currentSess = S.currentSess;
  return (
    <aside className={(S.mobileTab === "tasks" ? "block" : "hidden") + " md:block md:row-span-2 lg:row-span-1 overflow-y-auto p-3 space-y-3 md:border-r border-slate-200/70 dark:border-slate-800"}>
      <div className="flex sm:hidden bg-slate-100 dark:bg-slate-900 ring-1 ring-slate-200 dark:ring-slate-800 rounded-full p-0.5 text-[11px] mb-1">
        <button onClick={() => S.setView("student")} className={"flex-1 px-2.5 py-2 rounded-full transition active:scale-95 " + (S.view === "student" ? "bg-white dark:bg-slate-700 text-slate-900 dark:text-white shadow-sm" : "text-slate-500 dark:text-slate-400")}>学生视图</button>
        <button onClick={() => S.setView("architect")} className={"flex-1 px-2.5 py-2 rounded-full transition active:scale-95 " + (S.view === "architect" ? "bg-white dark:bg-slate-700 text-slate-900 dark:text-white shadow-sm" : "text-slate-500 dark:text-slate-400")}>架构师视图</button>
      </div>
      <div className="text-[11px] font-semibold uppercase tracking-wide text-slate-500 dark:text-slate-400">每个 Agent 下的任务</div>

      <div className={"rounded-2xl ring-1 p-3 space-y-2.5 transition " + (S.activeAgent === "AP_BASE" ? "bg-indigo-50 dark:bg-indigo-950/30 ring-indigo-200 dark:ring-indigo-500/50" : CARD + " ring-slate-900/5")}>
        <div className="flex justify-between items-center">
          <span className="text-xs font-semibold">AP Base Agent</span>
          <span className="text-[10px] text-indigo-600 dark:text-indigo-300">{S.apTasks.length} 个任务</span>
        </div>
        <div className="flex flex-wrap gap-1.5">
          {S.subs.ap.map((cid) => (
            <button key={cid} onClick={() => S.selectCourse(cid)}
              className={"px-2.5 py-1 rounded-full text-[10px] ring-1 transition active:scale-95 " + (S.activeAgent === "AP_BASE" && S.activeCourse === cid ? "bg-indigo-600 text-white ring-indigo-500" : "bg-white dark:bg-slate-950 text-slate-600 dark:text-slate-300 ring-slate-200 dark:ring-slate-800 hover:ring-indigo-300")}>
              {packs[cid].icon} {packs[cid].shortName}
            </button>
          ))}
          <button onClick={() => S.setShowSubModal(true)} className="px-2.5 py-1 rounded-full text-[10px] ring-1 ring-dashed ring-slate-300 dark:ring-slate-700 text-slate-500 dark:text-slate-400 transition active:scale-95">+ AP</button>
        </div>
        <div className="space-y-1.5">
          {S.apTasks.map((s) => (
            <TaskRow key={s.id} session={s} active={currentSess && currentSess.id === s.id} architect={architect} onOpen={S.openSession} packs={packs} />
          ))}
          {S.apTasks.length === 0 && <div className="text-[11px] text-slate-500">还没有挂载 AP 课程包。</div>}
        </div>
      </div>

      {S.subs.dsat ? (
        <div className={"rounded-2xl ring-1 p-3 space-y-2.5 transition " + (S.activeAgent === "DSAT" ? "bg-sky-50 dark:bg-sky-950/30 ring-sky-200 dark:ring-sky-500/50" : CARD + " ring-slate-900/5")}>
          <div className="flex justify-between items-center">
            <button onClick={() => S.selectAgent("DSAT")} className="text-xs font-semibold text-left">Digital SAT</button>
            <span className="text-[10px] font-mono text-sky-600 dark:text-sky-300">{S.satTasks.length} 个任务 · 1510</span>
          </div>
          <div className="space-y-1.5">
            {S.satTasks.map((s) => (
              <TaskRow key={s.id} session={s} active={currentSess && currentSess.id === s.id} architect={architect} onOpen={S.openSession} packs={packs} />
            ))}
          </div>
        </div>
      ) : (
        <button onClick={() => S.setShowSubModal(true)} className="w-full min-h-[44px] p-3 rounded-2xl ring-1 ring-dashed ring-slate-300 dark:ring-slate-700 text-xs text-slate-500 text-left transition active:scale-[0.99]">未订阅 · Digital SAT</button>
      )}

      {S.subs.admissions ? (
        <div className={"rounded-2xl ring-1 p-3 space-y-2.5 transition " + (S.activeAgent === "ADMISSIONS" ? "bg-emerald-50 dark:bg-emerald-950/30 ring-emerald-200 dark:ring-emerald-500/50" : CARD + " ring-slate-900/5")}>
          <div className="flex justify-between items-center">
            <button onClick={() => S.selectAgent("ADMISSIONS")} className="text-xs font-semibold text-left">Admissions Agent</button>
            <span className="text-[10px] text-emerald-600 dark:text-emerald-300">{S.admTasks.length} 个任务</span>
          </div>
          <div className="space-y-1.5">
            {S.admTasks.map((s) => (
              <TaskRow key={s.id} session={s} active={currentSess && currentSess.id === s.id} architect={architect} onOpen={S.openSession} packs={packs} />
            ))}
          </div>
        </div>
      ) : (
        <button onClick={() => S.setShowSubModal(true)} className="w-full min-h-[44px] p-3 rounded-2xl ring-1 ring-dashed ring-slate-300 dark:ring-slate-700 text-xs text-slate-500 text-left transition active:scale-[0.99]">未订阅 · Admissions</button>
      )}
    </aside>
  );
}

function TwinSummary({ S, packs, student }) {
  return (
    <section className={CARD + " p-4 space-y-2.5"}>
      <div className="text-xs font-bold text-indigo-600 dark:text-indigo-300">Academic Digital Twin</div>
      {S.architect && <div className="text-[10px] font-mono text-slate-400 dark:text-slate-500">userProfiles/{student.email}</div>}
      <div className="text-[11px] text-slate-500 dark:text-slate-400">AP 实时预测分</div>
      {S.subs.ap.map((cid) => (
        <div key={cid} className="flex justify-between items-center text-xs bg-slate-50 dark:bg-slate-950 ring-1 ring-slate-200/60 dark:ring-slate-800 px-3 py-2 rounded-xl">
          <span>{packs[cid].icon} {packs[cid].shortName}</span>
          <span className="font-mono font-semibold text-emerald-600 dark:text-emerald-400">{S.scoreLabel(cid)}</span>
        </div>
      ))}
      {S.subs.dsat && (
        <div className="flex justify-between items-center text-xs bg-slate-50 dark:bg-slate-950 ring-1 ring-slate-200/60 dark:ring-slate-800 px-3 py-2 rounded-xl">
          <span>Digital SAT</span>
          <span className="font-mono font-semibold text-indigo-600 dark:text-sky-400">{student.satCurrent} → {student.satTarget}</span>
        </div>
      )}
      <div className="mt-2 p-3 rounded-xl bg-amber-50 dark:bg-amber-500/10 ring-1 ring-amber-200 dark:ring-amber-500/30 text-[11px] text-amber-900 dark:text-amber-100 leading-relaxed">
        <div className="font-semibold text-amber-700 dark:text-amber-300 mb-1">Planner ROI</div>
        当前 dSAT 1510。本周投入 5 小时稳住 Calc BC 5 分档的录取杠杆，高于刷 SAT 低频词。
      </div>
    </section>
  );
}

function plainEvent(type) {
  if (type === "skill.weak") return "薄弱点已同步到 SAT";
  if (type === "calendar.pressure") return "本周课业变重";
  if (type === "ap.predicted") return "预测分更新了选校";
  if (type === "vocab.context") return "词汇已送去 SAT";
  if (type === "narrative.gap") return "申请主线有缺口";
  if (type === "session.settled") return "这一节已完成";
  if (type === "vision.ocr") return "手写已识别";
  if (type === "student.reply") return "你的回答";
  if (type === "tool.desmos") return "Desmos 演示";
  return "Twin 更新";
}

function EventFeed({ S }) {
  return (
    <section className="space-y-2">
      <div className="text-[11px] font-semibold uppercase tracking-wide text-slate-500 dark:text-slate-400">Cross-Domain Event Bus</div>
      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-1 gap-2">
        {S.events.map((e) => (
          <article key={e.id} className={CARD + " p-3 text-[11px] space-y-1"}>
            <div className="flex justify-between gap-2">
              {S.architect ? <span className="font-mono text-indigo-600 dark:text-indigo-300">{e.type}</span> : <span className="text-indigo-600 dark:text-indigo-200">{plainEvent(e.type)}</span>}
              <span className="text-slate-400 dark:text-slate-500">{e.time}</span>
            </div>
            {S.architect && <div className="text-slate-400 dark:text-slate-500">{e.from} → {e.to}</div>}
            <div className="text-slate-700 dark:text-slate-200 leading-relaxed">{e.text}</div>
          </article>
        ))}
      </div>
    </section>
  );
}

function TwinAside({ S, packs, student }) {
  return (
    <aside className={(S.mobileTab === "events" ? "block" : "hidden") + " md:block md:col-span-2 lg:col-span-1 overflow-y-auto p-3 space-y-3 lg:border-l border-slate-200/70 dark:border-slate-800"}>
      <TwinSummary S={S} packs={packs} student={student} />
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
      {tabBtn("sat", "DSAT", "🎯", "SAT")}
      {tabBtn("ap", "AP_BASE", "📚", "AP")}
      {tabBtn("adm", "ADMISSIONS", "🎓", "申请")}
      {tabBtn("events", null, "🔔", "事件")}
    </nav>
  );
}

function SubModal({ S, packs }) {
  return (
    <Modal title="订阅与课程包热插拔" onClose={() => S.setShowSubModal(false)}>
      <div className="text-[11px] font-semibold text-slate-500 dark:text-slate-400">顶层支柱</div>
      <div className="flex gap-2 text-xs">
        <button onClick={() => { S.setSubs((p) => ({ ...p, dsat: !p.dsat })); if (S.subs.dsat && S.activeAgent === "DSAT") S.selectAgent("AP_BASE"); }}
          className={"flex-1 min-h-[44px] p-3 rounded-2xl ring-1 text-left transition active:scale-[0.98] " + (S.subs.dsat ? "bg-sky-50 dark:bg-sky-950/50 ring-sky-400 dark:ring-sky-500" : "bg-slate-50 dark:bg-slate-950 ring-slate-200 dark:ring-slate-800 text-slate-500")}>
          Digital SAT<br />{S.subs.dsat ? "已挂载" : "未订阅"}
        </button>
        <button onClick={() => { S.setSubs((p) => ({ ...p, admissions: !p.admissions })); if (S.subs.admissions && S.activeAgent === "ADMISSIONS") S.selectAgent("AP_BASE"); }}
          className={"flex-1 min-h-[44px] p-3 rounded-2xl ring-1 text-left transition active:scale-[0.98] " + (S.subs.admissions ? "bg-emerald-50 dark:bg-emerald-950/40 ring-emerald-400 dark:ring-emerald-500" : "bg-slate-50 dark:bg-slate-950 ring-slate-200 dark:ring-slate-800 text-slate-500")}>
          Admissions<br />{S.subs.admissions ? "已挂载" : "未订阅"}
        </button>
      </div>
      <div className="text-[11px] font-semibold text-slate-500 dark:text-slate-400 pt-2">AP 学科包 · 订阅才加载</div>
      <div className="grid grid-cols-2 gap-2">
        {Object.keys(packs).map((cid) => {
          const p = packs[cid];
          const on = S.subs.ap.indexOf(cid) >= 0;
          return (
            <button key={cid} onClick={() => S.toggleAp(cid)} className={"min-h-[44px] p-3 rounded-2xl ring-1 text-left text-xs transition active:scale-[0.98] " + (on ? "bg-indigo-50 dark:bg-indigo-950/50 ring-indigo-400 dark:ring-indigo-500" : "bg-slate-50 dark:bg-slate-950 ring-slate-200 dark:ring-slate-800 text-slate-500")}>
              <div className="font-semibold">{p.icon} {p.shortName}</div>
              <div className="text-[10px] mt-1 text-slate-500 dark:text-slate-400">{p.skills.length} Skills · {p.rag.length} RAG · {p.mcp.length} MCP</div>
              <div className="text-[10px] mt-1">{on ? "已挂载" : "点击订阅"}</div>
            </button>
          );
        })}
      </div>
      <button onClick={() => S.setShowSubModal(false)} className={"w-full min-h-[44px] py-2 rounded-full bg-indigo-600 hover:bg-indigo-500 text-white text-xs font-semibold shadow-sm " + BTN}>确认并热重载工作台</button>
    </Modal>
  );
}

function ManifestModal({ S, student }) {
  return (
    <Modal title="Twin Manifest" onClose={() => S.setShowManifest(false)}>
      <pre className="text-[11px] leading-relaxed text-slate-600 dark:text-slate-300 whitespace-pre-wrap font-mono">{JSON.stringify({
        student: student.email,
        grade: student.grade,
        gpa: student.gpa,
        dsat: { current: student.satCurrent, target: student.satTarget },
        subscribedAgents: { dsat: S.subs.dsat, admissions: S.subs.admissions },
        apPacks: S.subs.ap,
        active: { agent: S.activeAgent, course: S.activeCourse, mode: S.activeAgent === "AP_BASE" ? S.apMode : S.currentSess && S.currentSess.mode },
      }, null, 2)}</pre>
    </Modal>
  );
}
