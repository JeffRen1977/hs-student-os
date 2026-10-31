// data.js — presentation metadata only (icons, short names, labels, canvas style).
//
// Learning data (Twin, entitlements, catalog, tasks, sessions, runs, events) comes from
// `window.HSProvider` (js/data-provider.js): the real API, or web/fixtures/demo.json when
// the page is opened with ?demo=true. Nothing in this file is a student fact: no scores,
// no predictions, no progress percentages.

const PACK_META = {
  calc_bc: {
    shortName: "Calc BC",
    icon: "📐",
    family: "stem",
    canvas: "calc",
    currentUnit: "Unit 4: Contextual Applications of Differentiation",
    skills: [
      { name: "Socratic Math Step-by-Step", modes: ["GPA_SYNC"] },
      { name: "STEM FRQ Point-by-Point Grader", modes: ["EXAM_CRUNCH"] },
      { name: "Handwriting OCR -> LaTeX（文本闭环后启用）", modes: ["GPA_SYNC", "EXAM_CRUNCH"] },
    ],
    rag: ["Calc BC 原创题库 v1（待审阅）"],
    tools: ["math-verify", "content-retrieval"],
  },
  apush: { shortName: "APUSH", icon: "📜", family: "humanities", canvas: "history", currentUnit: "", skills: [], rag: [], tools: [] },
  physics_c: { shortName: "Physics C", icon: "⚡", family: "stem", canvas: "physics", currentUnit: "", skills: [], rag: [], tools: [] },
  dsat: { shortName: "Digital SAT", icon: "🎯", family: "sat", canvas: "calc", currentUnit: "", skills: [], rag: [], tools: [] },
};

const FALLBACK_META = { shortName: "", icon: "📘", family: "stem", canvas: "calc", currentUnit: "", skills: [], rag: [], tools: [] };

const MODE_LABEL = {
  GPA_SYNC: "日常作业",
  EXAM_CRUNCH: "大考精批",
  ADAPTIVE: "SAT 练习",
  INTERVIEW: "文书访谈",
  SCHOOL_LIST: "选校",
  ACTIVITIES: "活动列表",
};

// Presentation seam kept from the prototype. It now serves display metadata only.
window.HSData = {
  getPackMeta: function (courseId, name) {
    const meta = PACK_META[courseId] || FALLBACK_META;
    return Object.assign({ id: courseId, name: name || courseId }, meta, { shortName: meta.shortName || name || courseId });
  },
  getModeLabel: function () { return MODE_LABEL; },
};
