// ui.js — shared primitives used across panels and features.

function Card({ className, children }) {
  return <div className={CARD + (className ? " " + className : "")}>{children}</div>;
}

function Badge({ className, children }) {
  return (
    <span className={"inline-flex items-center px-2 py-0.5 rounded-full text-[10px] font-medium ring-1 " + (className || "")}>
      {children}
    </span>
  );
}

function Bar({ label, value, bar }) {
  return (
    <div>
      <div className="flex justify-between text-[11px] text-slate-500 dark:text-slate-400 mb-1"><span>{label}</span><span className="font-mono font-semibold">{value}%</span></div>
      <div className="h-2.5 rounded-full bg-slate-200/80 dark:bg-slate-800 overflow-hidden">
        <div className={"h-full rounded-full transition-all duration-500 " + bar} style={{ width: value + "%" }} />
      </div>
    </div>
  );
}

function Modal({ title, onClose, children }) {
  return (
    <div className="fixed inset-0 bg-slate-950/50 dark:bg-black/70 backdrop-blur-sm flex items-end sm:items-center justify-center p-0 sm:p-4 z-50">
      <div className="bg-white dark:bg-slate-900 ring-1 ring-slate-200 dark:ring-slate-700 rounded-t-3xl sm:rounded-3xl shadow-xl max-w-lg w-full p-5 space-y-3 max-h-[88vh] overflow-y-auto">
        <div className="flex justify-between items-center">
          <div className="text-sm font-bold">{title}</div>
          <button onClick={onClose} className={"min-h-[36px] px-3 rounded-full text-xs text-slate-500 dark:text-slate-400 hover:bg-slate-100 dark:hover:bg-slate-800 " + BTN}>关闭</button>
        </div>
        {children}
      </div>
    </div>
  );
}

// Big predicted-score numeral (e.g. "4.5 / 5").
function BigScore({ value }) {
  return (
    <div className="text-2xl font-extrabold leading-none tracking-tight text-slate-900 dark:text-white">
      {value.toFixed(1)}<span className="text-xs font-semibold text-slate-400 dark:text-slate-500"> / 5</span>
    </div>
  );
}

// GPA_SYNC / EXAM_CRUNCH two-option mode toggle.
function ModeToggle({ apMode, setApMode }) {
  return (
    <div className="flex bg-slate-100 dark:bg-slate-950 p-1 rounded-full ring-1 ring-slate-200 dark:ring-slate-800 text-xs">
      <button onClick={() => setApMode("GPA_SYNC")} className={"px-3 py-1.5 rounded-full transition active:scale-95 " + modeClass("GPA_SYNC", apMode === "GPA_SYNC")}>日常 GPA 护航</button>
      <button onClick={() => setApMode("EXAM_CRUNCH")} className={"px-3 py-1.5 rounded-full transition active:scale-95 " + modeClass("EXAM_CRUNCH", apMode === "EXAM_CRUNCH")}>5月大考冲刺</button>
    </div>
  );
}
