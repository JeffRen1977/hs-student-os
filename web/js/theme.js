// theme.js — Tailwind config + design tokens + shared class helpers.
// Plain script (not Babel): must run right after the Tailwind CDN script
// so tailwind.config is set before classes are generated.
tailwind.config = {
  darkMode: 'class',
  theme: {
    extend: {
      fontFamily: { sans: ['Inter', 'ui-sans-serif', 'system-ui', '-apple-system', 'sans-serif'] },
    },
  },
};

// Design tokens shared by every module.
const HS_FONT_STACK = "'Inter', ui-sans-serif, system-ui, -apple-system, sans-serif";
const HS_PAGE_BG = "bg-[#F7F8FA] dark:bg-slate-950";

// Shared class helpers (used across ui.js, agents/*, features.js).
const CARD = "bg-white dark:bg-slate-900 rounded-2xl shadow-sm ring-1 ring-slate-900/5 dark:ring-white/10";
const BTN = "transition hover:opacity-90 active:scale-[0.98]";

function modeClass(mode, active) {
  if (!active) return "text-slate-500 dark:text-slate-400";
  if (mode === "EXAM_CRUNCH") return "bg-rose-600 text-white shadow-sm";
  if (mode === "GPA_SYNC") return "bg-emerald-600 text-white shadow-sm";
  return "bg-indigo-600 text-white shadow-sm";
}
