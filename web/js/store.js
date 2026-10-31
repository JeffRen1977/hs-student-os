// store.js — app state shape + actions, isolated from components.
// useAppState() is the only place React state lives; components receive the returned
// object (conventionally `S`). Server data arrives already loaded from the provider
// (see app.js); Task, Session and Run are kept as separate collections.
const { useState, useMemo } = React;

const DRAFTS = HSProvider.createDraftStore(
  typeof localStorage !== "undefined" ? localStorage : HSProvider.memoryStorage()
);

function indexBy(list, key) {
  const out = {};
  (list || []).forEach((item) => { out[item[key]] = item; });
  return out;
}

function useAppState(data) {
  const demo = data.mode === "demo";
  const twin = data.twin;

  const [view, setView] = useState("student");
  const [catalog, setCatalog] = useState(data.catalog);
  const [activeAgent, setActiveAgent] = useState("AP_BASE");
  const enrolledIds = catalog.filter((c) => c.enrolled && c.availability === "active").map((c) => c.courseId);
  const [activeCourse, setActiveCourse] = useState(enrolledIds[0] || null);
  const [apMode, setApMode] = useState("GPA_SYNC");
  const firstTaskId = data.tasks[0] ? data.tasks[0].taskId : null;
  const [activeItemId, setActiveItemId] = useState(firstTaskId);
  const [showCatalog, setShowCatalog] = useState(false);
  const [showManifest, setShowManifest] = useState(false);
  const [fixedSteps, setFixedSteps] = useState({});
  const [fixedFrq, setFixedFrq] = useState({});
  const [tier2, setTier2] = useState(false);
  const [dark, setDark] = useState(false);
  const [mobileTab, setMobileTab] = useState("tasks");
  const [eventLog, setEventLog] = useState(data.eventLog);
  // Local-only demo interactions. Kept apart from the server event log on purpose:
  // the browser never creates domain events.
  const [demoNotes, setDemoNotes] = useState([]);
  const initialDraft = firstTaskId ? DRAFTS.load(firstTaskId) : null;
  const [draftText, setDraftText] = useState(initialDraft ? initialDraft.text : "");
  const [draftSavedAt, setDraftSavedAt] = useState(initialDraft ? initialDraft.savedAt : null);

  const sessionsByTask = useMemo(() => {
    const out = {};
    data.sessions.forEach((s) => { if (s.status === "OPEN") out[s.taskId] = s; });
    return out;
  }, [data.sessions]);
  const runsById = useMemo(() => indexBy(data.runs, "runId"), [data.runs]);

  const toggleDark = () => {
    const next = !dark;
    setDark(next);
    document.documentElement.classList.toggle("dark", next);
  };

  const architect = view === "architect";
  const courseName = (cid) => {
    const c = catalog.find((x) => x.courseId === cid);
    return c ? c.name : cid;
  };
  const pack = activeCourse ? HSData.getPackMeta(activeCourse, courseName(activeCourse)) : null;

  const apTasks = data.tasks.filter((t) => t.agent === "AP_BASE" && enrolledIds.includes(t.courseId));
  const satPreviews = demo ? data.previews.filter((p) => p.agent === "DSAT") : [];
  const admPreviews = demo ? data.previews.filter((p) => p.agent === "ADMISSIONS") : [];
  const currentTask = apTasks.find((t) => t.taskId === activeItemId) || null;
  const currentPreview = data.previews.find((p) => p.id === activeItemId) || null;
  const currentSession = currentTask ? sessionsByTask[currentTask.taskId] || null : null;
  const runForSession = (s) => (s && data.sessionRunIds[s.sessionId] ? runsById[data.sessionRunIds[s.sessionId]] || null : null);
  const currentRun = runForSession(currentSession);
  const runForTask = (taskId) => runForSession(sessionsByTask[taskId]);

  const draftKey = currentTask ? currentTask.taskId : "general";

  const noteDemo = (type, text) => {
    setDemoNotes((prev) => [{ id: Date.now() + Math.random(), type, text, at: new Date().toISOString() }, ...prev].slice(0, 20));
  };

  const applyServerEvents = (events) => setEventLog((log) => HSProvider.mergeEvents(log, events));

  const selectCourse = (cid) => {
    setActiveAgent("AP_BASE");
    setActiveCourse(cid);
    setTier2(false);
    const next = data.tasks.find((t) => t.courseId === cid);
    if (next) openTask(next);
  };

  const selectAgent = (agent) => {
    setActiveAgent(agent);
    setTier2(false);
    if (agent === "AP_BASE") {
      if (apTasks[0]) openTask(apTasks[0]);
      return;
    }
    const preview = data.previews.find((p) => p.agent === agent);
    if (preview) setActiveItemId(preview.id);
  };

  function openTask(task) {
    setActiveItemId(task.taskId);
    setActiveAgent("AP_BASE");
    setActiveCourse(task.courseId);
    setApMode(task.mode);
    setTier2(false);
    const saved = DRAFTS.load(task.taskId);
    setDraftText(saved ? saved.text : "");
    setDraftSavedAt(saved ? saved.savedAt : null);
    setMobileTab("ap");
  }

  const openPreview = (p) => {
    setActiveItemId(p.id);
    setActiveAgent(p.agent);
    setTier2(false);
    setMobileTab(p.agent === "DSAT" ? "sat" : "adm");
  };

  const setDraft = (text) => {
    setDraftText(text);
    const saved = DRAFTS.save(draftKey, text);
    setDraftSavedAt(saved ? saved.savedAt : null);
  };

  const clearDraft = () => {
    DRAFTS.clear(draftKey);
    setDraftText("");
    setDraftSavedAt(null);
  };

  // Demo only: enrollment is simulated locally. In API mode this becomes
  // POST /api/courses/enroll|unenroll with an Idempotency-Key (M1 Step 11).
  const toggleEnrollment = (cid) => {
    const course = catalog.find((c) => c.courseId === cid);
    if (!demo || !course || course.availability !== "active" || !course.entitled) return;
    const next = !course.enrolled;
    setCatalog((prev) => prev.map((c) => (c.courseId === cid ? Object.assign({}, c, { enrolled: next }) : c)));
    noteDemo(next ? "course.enrolled" : "course.unenrolled", (next ? "演示：已在本地注册 " : "演示：已在本地取消注册 ") + course.name + "（未调用服务器）");
    if (next) selectCourse(cid);
    else if (activeCourse === cid) setActiveCourse(enrolledIds.filter((x) => x !== cid)[0] || null);
  };

  const goMobile = (tab, agent) => {
    setMobileTab(tab);
    if (agent) selectAgent(agent);
  };

  return {
    demo, twin, entitlements: data.entitlements,
    view, setView, catalog, enrolledIds,
    activeAgent, setActiveAgent, activeCourse, setActiveCourse,
    apMode, setApMode, activeItemId,
    showCatalog, setShowCatalog, showManifest, setShowManifest,
    fixedSteps, setFixedSteps, fixedFrq, setFixedFrq,
    tier2, setTier2,
    draft: draftText, draftSavedAt, setDraft, clearDraft,
    dark, toggleDark, mobileTab, setMobileTab,
    events: eventLog.events, lastSequence: eventLog.lastSequence, applyServerEvents,
    demoNotes, noteDemo,
    architect, pack, courseName,
    apTasks, satPreviews, admPreviews,
    currentTask, currentPreview, currentSession, currentRun, runForTask,
    selectCourse, selectAgent, openTask, openPreview, toggleEnrollment, goMobile,
  };
}
