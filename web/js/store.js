// store.js — app state shape + actions, isolated from components.
// useAppState() is the only place React state lives; components receive
// the returned object (conventionally `S`) plus data via props.
const { useState } = React;

function useAppState(deps) {
  const packs = deps.packs;
  const sessions = deps.sessions;

  const [view, setView] = useState("architect");
  const [subs, setSubs] = useState({ dsat: true, admissions: true, ap: ["calc_bc", "apush", "csa"] });
  const [activeAgent, setActiveAgent] = useState("AP_BASE");
  const [activeCourse, setActiveCourse] = useState("calc_bc");
  const [apMode, setApMode] = useState("GPA_SYNC");
  const [activeSessId, setActiveSessId] = useState("sess_101");
  const [showSubModal, setShowSubModal] = useState(false);
  const [showManifest, setShowManifest] = useState(false);
  const [fixedSteps, setFixedSteps] = useState({});
  const [fixedFrq, setFixedFrq] = useState({});
  const [tier2, setTier2] = useState(false);
  const [draft, setDraft] = useState("");
  const [dark, setDark] = useState(false);
  const [mobileTab, setMobileTab] = useState("tasks");
  const [events, setEvents] = useState(deps.events);

  const toggleDark = () => {
    const next = !dark;
    setDark(next);
    document.documentElement.classList.toggle("dark", next);
  };

  const architect = view === "architect";
  const pack = packs[activeCourse] || packs.calc_bc;
  const mountedCount = subs.ap.length + (subs.dsat ? 1 : 0) + (subs.admissions ? 1 : 0);

  const apTasks = sessions.filter((s) => s.agent === "AP_BASE" && subs.ap.includes(s.courseId));
  const satTasks = subs.dsat ? sessions.filter((s) => s.agent === "DSAT") : [];
  const admTasks = subs.admissions ? sessions.filter((s) => s.agent === "ADMISSIONS") : [];
  const currentSess = sessions.find((s) => s.id === activeSessId) || apTasks[0];

  const pushEvent = (type, from, to, text) => {
    setEvents((prev) => [{ id: Date.now(), type, time: "Just now", from, to, text }, ...prev]);
  };

  const selectCourse = (cid) => {
    setActiveAgent("AP_BASE");
    setActiveCourse(cid);
    setTier2(false);
    const next = sessions.find((s) => s.courseId === cid);
    if (next) {
      setActiveSessId(next.id);
      setApMode(next.mode);
    }
  };

  const selectAgent = (agent) => {
    setActiveAgent(agent);
    setTier2(false);
    const next = sessions.find((s) => s.agent === agent && (agent !== "AP_BASE" || s.courseId === activeCourse));
    if (next) {
      setActiveSessId(next.id);
      if (next.agent === "AP_BASE") setApMode(next.mode);
    }
  };

  const openSession = (s) => {
    setActiveSessId(s.id);
    setActiveAgent(s.agent);
    setTier2(false);
    if (s.agent === "AP_BASE") {
      setActiveCourse(s.courseId);
      setApMode(s.mode);
    }
    setMobileTab(s.agent === "DSAT" ? "sat" : s.agent === "ADMISSIONS" ? "adm" : "ap");
  };

  const toggleAp = (cid) => {
    setSubs((prev) => {
      const on = prev.ap.includes(cid);
      const ap = on ? prev.ap.filter((x) => x !== cid) : [...prev.ap, cid];
      return { ...prev, ap };
    });
    if (!subs.ap.includes(cid)) selectCourse(cid);
    if (subs.ap.includes(cid) && activeCourse === cid) {
      const rest = subs.ap.filter((x) => x !== cid);
      if (rest[0]) selectCourse(rest[0]);
    }
  };

  const scoreLabel = (cid) => {
    const p = packs[cid];
    const shown = fixedFrq[cid] ? Math.min(5, p.predicted + 0.3).toFixed(1) : p.predicted.toFixed(1);
    if (p.stable && !fixedFrq[cid]) return shown + "（稳 5 分）";
    return shown + " → " + p.target.toFixed(1);
  };

  const goMobile = (tab, agent) => {
    setMobileTab(tab);
    if (agent) selectAgent(agent);
  };

  return {
    view, setView, subs, setSubs,
    activeAgent, setActiveAgent, activeCourse, setActiveCourse,
    apMode, setApMode, activeSessId, setActiveSessId,
    showSubModal, setShowSubModal, showManifest, setShowManifest,
    fixedSteps, setFixedSteps, fixedFrq, setFixedFrq,
    tier2, setTier2, draft, setDraft,
    dark, toggleDark, mobileTab, setMobileTab,
    events, setEvents,
    architect, pack, mountedCount,
    apTasks, satTasks, admTasks, currentSess,
    pushEvent, selectCourse, selectAgent, openSession, toggleAp, scoreLabel, goMobile,
  };
}
