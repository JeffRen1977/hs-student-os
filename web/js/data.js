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
      { name: "Handwriting OCR -> LaTeX (enabled after the text loop)", modes: ["GPA_SYNC", "EXAM_CRUNCH"] },
    ],
    rag: ["Calc BC original question bank v1 (pending review)"],
    tools: ["math-verify", "content-retrieval"],
  },
  apush: { shortName: "APUSH", icon: "📜", family: "humanities", canvas: "history", currentUnit: "", skills: [], rag: [], tools: [] },
  physics_c: { shortName: "Physics C", icon: "⚡", family: "stem", canvas: "physics", currentUnit: "", skills: [], rag: [], tools: [] },
  dsat: { shortName: "Digital SAT", icon: "🎯", family: "sat", canvas: "calc", currentUnit: "", skills: [], rag: [], tools: [] },
};

const FALLBACK_META = { shortName: "", icon: "📘", family: "stem", canvas: "calc", currentUnit: "", skills: [], rag: [], tools: [] };

const MODE_LABEL = {
  GPA_SYNC: "Daily homework",
  EXAM_CRUNCH: "Exam grading",
  ADAPTIVE: "SAT practice",
  INTERVIEW: "Essay interview",
  SCHOOL_LIST: "College list",
  ACTIVITIES: "Activities list",
};

// Presentation seam kept from the prototype. It now serves display metadata only.
window.HSData = {
  getPackMeta: function (courseId, name) {
    const meta = PACK_META[courseId] || FALLBACK_META;
    return Object.assign({ id: courseId, name: name || courseId }, meta, { shortName: meta.shortName || name || courseId });
  },
  getModeLabel: function () { return MODE_LABEL; },
};
