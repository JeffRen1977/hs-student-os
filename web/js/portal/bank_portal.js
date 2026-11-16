// bank_portal.js — the organization question bank screen (Step 45.5).
// Authors: browse, confirm, edit, submit and discard items. Content reviewers (same
// organization, also authors): set keys and solutions, approve, reject, retire, select
// approved items into sets and build a draft package version. Everything goes through
// /api/bank/*; the server enforces every rule, the screen only offers what applies.

const API_BASE_URL = window.HS_API_BASE_URL || "http://localhost:8787";
const AUTH = HSAuth.createAuth({
  hostname: window.location.hostname,
  apiBaseUrl: API_BASE_URL,
  firebaseConfig: window.HS_FIREBASE_CONFIG || null,
  projectId: window.HS_FIREBASE_PROJECT || "demo-hs-student-os",
  storage: typeof sessionStorage !== "undefined" ? sessionStorage : null,
  localUsers: HSAuth.SYNTHETIC_PLATFORM_MEMBERS,
  storageKey: "hsos.portalUid",
});
const BANK = HSBankApi.createBankApi({ baseUrl: API_BASE_URL, getIdToken: () => AUTH.getIdToken() });

const STATE_COLOR = {
  extracted: "bg-violet-100 text-violet-800", draft: "bg-slate-100 text-slate-700",
  in_review: "bg-amber-100 text-amber-800", approved: "bg-emerald-100 text-emerald-800",
  rejected: "bg-rose-100 text-rose-800", discarded: "bg-slate-200 text-slate-500",
  retired: "bg-slate-200 text-slate-600",
};
const STATES = ["extracted", "draft", "in_review", "approved", "rejected", "discarded", "retired"];
const INPUT = "rounded-lg ring-1 ring-slate-200 px-2 py-1 text-sm";
const SMALL_BTN = BTN + " rounded-lg px-3 py-1.5 text-sm disabled:opacity-40";

function StateBadge({ state }) {
  return <span className={"px-2 py-0.5 rounded-full text-xs font-semibold " + (STATE_COLOR[state] || "")}>{state}</span>;
}

function Underlined({ text }) {
  return (
    <span className="whitespace-pre-wrap">
      {HSBankApi.underlineSegments(text).map((s, i) => (s.underline ? <u key={i} className="decoration-2">{s.text}</u> : <span key={i}>{s.text}</span>))}
    </span>
  );
}

function Flags({ flags }) {
  if (!flags || !flags.length) return null;
  return (
    <div className="flex flex-wrap gap-1 mt-2">
      {flags.map((f) => {
        const warn = /key-disputed|key-mismatch|compiled-key:|seed-answer|missing|incomplete|uncertain/.test(f);
        return <span key={f} className={"text-[11px] px-1.5 py-0.5 rounded " + (warn ? "bg-amber-100 text-amber-900" : "bg-slate-100 text-slate-600")}>{f}</span>;
      })}
    </div>
  );
}

// ---- Items ----------------------------------------------------------------------------------

function ItemList({ filters, setFilters, items, onMore, hasMore, selectedId, onSelect, loading }) {
  return (
    <div className={CARD + " p-4"}>
      <div className="grid grid-cols-2 gap-2">
        <select className={INPUT} value={filters.state} onChange={(e) => setFilters({ ...filters, state: e.target.value })}>
          <option value="">All states</option>
          {STATES.map((s) => <option key={s} value={s}>{s}</option>)}
        </select>
        <input className={INPUT} placeholder="Course id" value={filters.courseId} onChange={(e) => setFilters({ ...filters, courseId: e.target.value })} />
        <input className={INPUT + " col-span-2"} placeholder="Flag, e.g. vision-verified or seed-status:ready" value={filters.flag}
          onChange={(e) => setFilters({ ...filters, flag: e.target.value })} />
      </div>
      <ul className="mt-3 space-y-1 max-h-[70vh] overflow-auto">
        {items.map((i) => (
          <li key={i.itemId}>
            <button onClick={() => onSelect(i.itemId)} className={"w-full text-left px-2 py-1.5 rounded " + (selectedId === i.itemId ? "bg-slate-100" : "hover:bg-slate-50")}>
              <div className="flex items-center gap-2 text-sm"><span className="font-mono text-xs">{i.itemId}</span><StateBadge state={i.state} /></div>
              <div className="text-xs text-slate-500 truncate">{i.tags.join(" · ")}{i.courseId ? " · " + i.courseId : ""}</div>
            </button>
          </li>
        ))}
      </ul>
      {loading && <p className="text-sm mt-2">Loading…</p>}
      {!loading && items.length === 0 && <p className="text-sm text-slate-500 mt-2">No items match.</p>}
      {hasMore && <button className={SMALL_BTN + " mt-2 ring-1 ring-slate-200 w-full"} onClick={onMore}>Load more</button>}
    </div>
  );
}

function EditForm({ detail, canReview, onSaved, onCancel }) {
  const [form, setForm] = React.useState(() => HSBankApi.formFromVersion(detail.current, detail));
  const [busy, setBusy] = React.useState(false);
  const [error, setError] = React.useState(null);
  const action = React.useRef("edit-" + Date.now());
  const set = (k) => (e) => setForm({ ...form, [k]: e.target.value });
  const opensVersion = detail.state === "approved" || detail.state === "rejected";
  async function save() {
    const changes = HSBankApi.changesFromForm({ version: detail.current, item: detail }, form);
    if (!Object.keys(changes).length) { onCancel(); return; }
    setBusy(true); setError(null);
    try {
      const updated = await BANK.editItem(detail.itemId, detail.revision, changes, action.current);
      onSaved(updated);
    } catch (err) {
      setError(err.code === "VERSION_CONFLICT" ? { ...err, message: "Someone changed this item meanwhile. Reload it and edit again." } : err);
    } finally { setBusy(false); }
  }
  const sources = canReview ? ["", "source-key", "compiled-key", "agent-suggested", "reviewer"] : ["", "source-key", "compiled-key", "agent-suggested"];
  return (
    <div className="mt-4 space-y-2 rounded-lg ring-1 ring-slate-200 p-3">
      {opensVersion && <p className="text-xs text-amber-800 bg-amber-50 rounded p-2">Saving opens version {detail.currentVersion + 1} as a draft; the approved version stays in use until the new one is approved.</p>}
      <label className="block text-xs text-slate-500">Stem (mark underlined text as [[text]])</label>
      <textarea className={INPUT + " w-full h-28 font-mono text-xs"} value={form.stem} onChange={set("stem")} />
      <div className="flex gap-2">
        <select className={INPUT} value={form.type} onChange={set("type")}><option value="mc">multiple choice</option><option value="spr">student-produced response</option></select>
        <select className={INPUT} value={form.difficulty} onChange={set("difficulty")}><option value="">difficulty</option><option>easy</option><option>medium</option><option>hard</option></select>
        <select className={INPUT} value={form.figure} onChange={set("figure")}><option value="none">no figure</option><option value="described">figure described</option><option value="image">needs image</option></select>
      </div>
      {form.type === "mc" && ["A", "B", "C", "D"].map((k) => (
        <div key={k} className="flex items-center gap-2"><span className="w-5 text-sm font-semibold">{k}</span>
          <input className={INPUT + " flex-1"} value={form.choices[k]} onChange={(e) => setForm({ ...form, choices: { ...form.choices, [k]: e.target.value } })} /></div>
      ))}
      <div className="flex gap-2">
        <input className={INPUT + " w-28"} placeholder="answer" value={form.answer} onChange={set("answer")} />
        <select className={INPUT} value={form.answerSource} onChange={set("answerSource")}>
          {sources.map((s) => <option key={s} value={s}>{s || "key source"}</option>)}
        </select>
      </div>
      {canReview && <textarea className={INPUT + " w-full h-16 text-xs"} placeholder="Solution (worked explanation)" value={form.solution} onChange={set("solution")} />}
      <input className={INPUT + " w-full"} placeholder="Course id" value={form.courseId} onChange={set("courseId")} />
      <input className={INPUT + " w-full"} placeholder="Section" value={form.section} onChange={set("section")} />
      <input className={INPUT + " w-full"} placeholder="Skill ids, comma-separated (e.g. dsat.algebra.linear-equations)" value={form.skillIds} onChange={set("skillIds")} />
      <input className={INPUT + " w-full"} placeholder="Flags, comma-separated" value={form.flags} onChange={set("flags")} />
      <div className="flex gap-2">
        <button disabled={busy} className={SMALL_BTN + " bg-slate-900 text-white"} onClick={save}>{busy ? "Saving…" : "Save"}</button>
        <button className={SMALL_BTN + " ring-1 ring-slate-200"} onClick={onCancel}>Cancel</button>
      </div>
      <ErrorNote error={error} />
    </div>
  );
}

function ItemDetail({ itemId, me, onChanged }) {
  const [detail, setDetail] = React.useState(null);
  const [passage, setPassage] = React.useState(null);
  const [error, setError] = React.useState(null);
  const [mode, setMode] = React.useState(null); // edit | key | reject | retire
  const [text, setText] = React.useState({ answer: "", solution: "", notes: "" });
  const [busy, setBusy] = React.useState(false);
  const load = React.useCallback(async () => {
    setError(null);
    try {
      const d = await BANK.getItem(itemId);
      setDetail(d);
      setPassage(d.current.passageId ? await BANK.getPassage(d.current.passageId) : null);
    } catch (err) { setError(err); }
  }, [itemId]);
  React.useEffect(() => { setMode(null); setDetail(null); load(); }, [load]);
  if (error && !detail) return <ErrorNote error={error} />;
  if (!detail) return <p className="text-sm">Loading…</p>;
  const v = detail.current;
  const actions = HSBankApi.itemActions(detail.state, me.canReview);
  const problems = detail.state === "in_review" ? HSBankApi.approvalProblems(v) : [];

  async function run(action, body) {
    setBusy(true); setError(null);
    try {
      const updated = await BANK.act(detail.itemId, action, body, action + ":" + detail.itemId + ":" + detail.revision);
      setDetail({ ...updated, versions: detail.versions });
      setMode(null); setText({ answer: "", solution: "", notes: "" });
      onChanged(); load();
    } catch (err) { setError(err); } finally { setBusy(false); }
  }

  return (
    <div className={CARD + " p-4"}>
      <div className="flex flex-wrap items-center gap-2">
        <h2 className="font-semibold font-mono text-sm">{detail.itemId}</h2>
        <StateBadge state={detail.state} />
        <span className="text-xs text-slate-500">version {detail.currentVersion}{detail.approvedVersion ? " · approved v" + detail.approvedVersion : ""} · revision {detail.revision}</span>
      </div>
      <p className="text-xs text-slate-500 mt-1">{HSBankApi.STATE_TEXT[detail.state]}</p>
      <div className="text-xs text-slate-500 mt-1">
        Source: {v.provenance.kind}{v.provenance.reference ? " · " + v.provenance.reference : ""}{v.provenance.page ? " · page " + v.provenance.page : ""}{v.provenance.region ? " · " + v.provenance.region : ""}
        {v.submittedBy ? " · submitted by " + v.submittedBy : ""}
      </div>

      {passage && (
        <details className="mt-3 rounded-lg bg-slate-50 p-3" open>
          <summary className="text-xs font-semibold cursor-pointer">{passage.title}</summary>
          <div className="text-sm mt-2 max-h-72 overflow-auto"><Underlined text={passage.text} /></div>
        </details>
      )}
      <div className="mt-3 text-sm"><Underlined text={v.stem || "(empty stem)"} /></div>
      {v.type === "mc" && (
        <ol className="mt-2 space-y-1">
          {["A", "B", "C", "D"].map((k) => (
            <li key={k} className={"text-sm rounded px-2 py-1 " + (v.answer === k ? "bg-emerald-50 ring-1 ring-emerald-200" : "")}>
              <b>{k})</b> {(v.choices && v.choices[k]) || <span className="text-rose-600">missing</span>}
            </li>
          ))}
        </ol>
      )}
      <div className="mt-2 text-sm">
        Answer: {v.answer ? <b>{v.answer}</b> : <span className="text-slate-500">none</span>}
        {v.answerSource && <span className="text-xs text-slate-500"> — {HSBankApi.KEY_TEXT[v.answerSource]}</span>}
      </div>
      {v.solution && <div className="mt-1 text-xs text-slate-600 whitespace-pre-wrap">Solution: {v.solution}</div>}
      <Flags flags={v.flags} />
      {v.review && (
        <div className={"mt-3 rounded-lg p-2 text-sm " + (v.review.decision === "rejected" ? "bg-rose-50" : "bg-emerald-50")}>
          {v.review.decision} by {v.review.reviewerId}{v.review.notes ? ": " + v.review.notes : ""}
        </div>
      )}
      {problems.length > 0 && me.canReview && (
        <ul className="mt-3 text-xs text-amber-900 bg-amber-50 rounded p-2 list-disc pl-5">{problems.map((p) => <li key={p}>{p}</li>)}</ul>
      )}

      <div className="mt-4 flex flex-wrap gap-2">
        {actions.includes("confirm") && <button disabled={busy} className={SMALL_BTN + " bg-violet-600 text-white"} onClick={() => run("confirm")}>Confirm extraction</button>}
        {actions.includes("submit") && <button disabled={busy} className={SMALL_BTN + " bg-indigo-600 text-white"} onClick={() => run("submit")}>Submit for review</button>}
        {actions.includes("key") && <button className={SMALL_BTN + " ring-1 ring-slate-200"} onClick={() => { setMode("key"); setText({ ...text, answer: v.answer || "", solution: v.solution || "" }); }}>Set key</button>}
        {actions.includes("approve") && <button disabled={busy || problems.length > 0} className={SMALL_BTN + " bg-emerald-600 text-white"} onClick={() => run("approve", { notes: "" })}>Approve</button>}
        {actions.includes("reject") && <button className={SMALL_BTN + " bg-rose-600 text-white"} onClick={() => setMode("reject")}>Reject…</button>}
        {actions.includes("edit") && <button className={SMALL_BTN + " ring-1 ring-slate-200"} onClick={() => setMode("edit")}>Edit</button>}
        {actions.includes("retire") && <button className={SMALL_BTN + " ring-1 ring-slate-200"} onClick={() => setMode("retire")}>Retire…</button>}
        {actions.includes("discard") && <button disabled={busy} className={SMALL_BTN + " ring-1 ring-rose-200 text-rose-700"} onClick={() => run("discard", { notes: "" })}>Discard</button>}
      </div>

      {mode === "edit" && <EditForm detail={detail} canReview={me.canReview} onCancel={() => setMode(null)} onSaved={() => { setMode(null); onChanged(); load(); }} />}
      {mode === "key" && (
        <div className="mt-3 space-y-2 rounded-lg ring-1 ring-slate-200 p-3">
          <input className={INPUT} placeholder={v.type === "mc" ? "A, B, C or D" : "accepted values, e.g. 29/3|9.67"} value={text.answer} onChange={(e) => setText({ ...text, answer: e.target.value })} />
          <textarea className={INPUT + " w-full h-20 text-xs"} placeholder="Solution (required for student-produced responses)" value={text.solution} onChange={(e) => setText({ ...text, solution: e.target.value })} />
          <button disabled={busy || !text.answer.trim()} className={SMALL_BTN + " bg-slate-900 text-white"} onClick={() => run("key", { answer: text.answer.trim(), solution: text.solution.trim() || null })}>Save key</button>
        </div>
      )}
      {(mode === "reject" || mode === "retire") && (
        <div className="mt-3 space-y-2 rounded-lg ring-1 ring-slate-200 p-3">
          <textarea className={INPUT + " w-full h-16 text-sm"} placeholder={mode === "reject" ? "What must the author fix?" : "Why retire it?"} value={text.notes} onChange={(e) => setText({ ...text, notes: e.target.value })} />
          <button disabled={busy || !text.notes.trim()} className={SMALL_BTN + " bg-slate-900 text-white"} onClick={() => run(mode, { notes: text.notes.trim() })}>{mode === "reject" ? "Reject" : "Retire"}</button>
        </div>
      )}
      <ErrorNote error={error} />

      <details className="mt-4">
        <summary className="text-xs text-slate-500 cursor-pointer">History ({detail.history.length}) and versions ({(detail.versions || []).length})</summary>
        <ul className="text-xs mt-2 space-y-0.5">{detail.history.map((h, i) => (
          <li key={i}>{new Date(h.at).toLocaleString()} · v{h.version} · <b>{h.action}</b> by {h.actorId}{h.toState ? " → " + h.toState : ""}{h.notes ? " — " + h.notes : ""}</li>
        ))}</ul>
      </details>
    </div>
  );
}

function ItemsTab({ me }) {
  const [filters, setFilters] = React.useState({ state: "", courseId: "", flag: "" });
  const [items, setItems] = React.useState([]);
  const [cursor, setCursor] = React.useState(null);
  const [loading, setLoading] = React.useState(true); // no "No items match" before the first answer
  const [error, setError] = React.useState(null);
  const [selected, setSelected] = React.useState(null);
  const load = React.useCallback(async (after) => {
    setLoading(true); setError(null);
    try {
      const r = await BANK.listItems({ ...filters, cursor: after || null, limit: 50 });
      setItems((old) => (after ? old.concat(r.items) : r.items));
      setCursor(r.nextCursor);
    } catch (err) { setError(err); } finally { setLoading(false); }
  }, [filters]);
  React.useEffect(() => { const t = setTimeout(() => load(null), 250); return () => clearTimeout(t); }, [load]);
  return (
    <div className="mt-4 grid grid-cols-1 md:grid-cols-[340px_minmax(0,1fr)] gap-4">
      <div>
        <ItemList filters={filters} setFilters={setFilters} items={items} onMore={() => load(cursor)} hasMore={!!cursor}
          selectedId={selected} onSelect={setSelected} loading={loading} />
        <ErrorNote error={error} />
      </div>
      <div>{selected ? <ItemDetail itemId={selected} me={me} onChanged={() => load(null)} /> : <p className="text-sm text-slate-500">Select an item.</p>}</div>
    </div>
  );
}

// ---- Selections -------------------------------------------------------------------------------

function ApprovedPicker({ courseId, used, onAdd }) {
  const [items, setItems] = React.useState([]);
  const [cursor, setCursor] = React.useState(null);
  const [checked, setChecked] = React.useState({});
  const [error, setError] = React.useState(null);
  const load = React.useCallback(async (after) => {
    try {
      const r = await BANK.listItems({ approvedOnly: true, courseId: courseId || null, cursor: after || null, limit: 100 });
      setItems((old) => (after ? old.concat(r.items) : r.items)); setCursor(r.nextCursor);
    } catch (err) { setError(err); }
  }, [courseId]);
  React.useEffect(() => { load(null); }, [load]);
  const picked = Object.keys(checked).filter((k) => checked[k]);
  return (
    <div className="rounded-lg ring-1 ring-slate-200 p-3">
      <div className="text-xs font-semibold">Approved items{courseId ? " for " + courseId : ""}</div>
      <ul className="mt-2 max-h-56 overflow-auto space-y-0.5">
        {items.filter((i) => !used.has(i.itemId)).map((i) => (
          <li key={i.itemId} className="text-xs flex items-center gap-2">
            <input type="checkbox" checked={!!checked[i.itemId]} onChange={(e) => setChecked({ ...checked, [i.itemId]: e.target.checked })} />
            <span className="font-mono">{i.itemId}</span><span className="text-slate-500 truncate">{i.tags.join(" · ")}</span>
          </li>
        ))}
      </ul>
      {cursor && <button className="text-xs text-slate-500 mt-1" onClick={() => load(cursor)}>Load more</button>}
      <button disabled={!picked.length} className={SMALL_BTN + " mt-2 bg-slate-900 text-white"} onClick={() => { onAdd(picked); setChecked({}); }}>Add {picked.length || ""} to the open set</button>
      <ErrorNote error={error} />
    </div>
  );
}

function SelectionEditor({ me, selection, onSaved, onClose }) {
  const [draft, setDraft] = React.useState(() => (selection ? HSBankApi.draftFromSelection(selection)
    : { courseId: "dsat", name: "", sourceType: "original", sourceAuthor: "", sourceLicense: "", sets: [HSBankApi.emptySet(1)] }));
  const [open, setOpen] = React.useState(0);
  const [busy, setBusy] = React.useState(false);
  const [error, setError] = React.useState(null);
  const [version, setVersion] = React.useState("");
  const [built, setBuilt] = React.useState(null);
  const action = React.useRef("sel-" + Date.now());
  const readOnly = !me.canReview;
  const used = new Set(draft.sets.flatMap((s) => s.items.map((r) => r.itemId)));
  const problems = HSBankApi.selectionProblems(draft);
  const setSet = (i, patch) => setDraft({ ...draft, sets: draft.sets.map((s, j) => (j === i ? { ...s, ...patch } : s)) });

  async function save() {
    setBusy(true); setError(null);
    try {
      const saved = selection
        ? await BANK.updateSelection(selection.selectionId, selection.revision, HSBankApi.selectionBody(draft, false), action.current)
        : await BANK.createSelection(HSBankApi.selectionBody(draft, true), action.current);
      action.current = "sel-" + Date.now();
      onSaved(saved);
    } catch (err) { setError(err); } finally { setBusy(false); }
  }
  async function build() {
    setBusy(true); setError(null); setBuilt(null);
    try {
      const r = await BANK.build(selection.selectionId, version, "build:" + selection.selectionId + "@" + version);
      setBuilt(r); onSaved(r.selection);
    } catch (err) { setError(err); } finally { setBusy(false); }
  }

  return (
    <div className={CARD + " p-4 space-y-3"}>
      <div className="flex items-center justify-between">
        <h2 className="font-semibold">{selection ? selection.name : "New selection"}</h2>
        <button className="text-sm text-slate-500" onClick={onClose}>Close</button>
      </div>
      {readOnly && <p className="text-xs text-slate-500">Read only: only the content reviewer edits and builds selections.</p>}
      <div className="grid grid-cols-2 gap-2">
        <input disabled={readOnly || !!selection} className={INPUT} placeholder="Course id" value={draft.courseId} onChange={(e) => setDraft({ ...draft, courseId: e.target.value })} />
        <input disabled={readOnly} className={INPUT} placeholder="Selection name" value={draft.name} onChange={(e) => setDraft({ ...draft, name: e.target.value })} />
        <select disabled={readOnly} className={INPUT} value={draft.sourceType} onChange={(e) => setDraft({ ...draft, sourceType: e.target.value })}>
          <option value="original">original content</option><option value="licensed">licensed content</option>
        </select>
        <input disabled={readOnly} className={INPUT} placeholder="Source author (default: publisher)" value={draft.sourceAuthor} onChange={(e) => setDraft({ ...draft, sourceAuthor: e.target.value })} />
        <input disabled={readOnly} className={INPUT + " col-span-2"} placeholder="Source license (default: course license)" value={draft.sourceLicense} onChange={(e) => setDraft({ ...draft, sourceLicense: e.target.value })} />
      </div>

      <div className="space-y-2">
        {draft.sets.map((s, i) => (
          <div key={i} className={"rounded-lg ring-1 p-3 " + (open === i ? "ring-indigo-300" : "ring-slate-200")} onClick={() => setOpen(i)}>
            <div className="grid grid-cols-2 md:grid-cols-4 gap-2">
              <input disabled={readOnly} className={INPUT} value={s.setId} onChange={(e) => setSet(i, { setId: e.target.value })} />
              <input disabled={readOnly} className={INPUT} value={s.title} onChange={(e) => setSet(i, { title: e.target.value })} />
              <input disabled={readOnly} className={INPUT} value={s.taskTitle} onChange={(e) => setSet(i, { taskTitle: e.target.value })} />
              <select disabled={readOnly} className={INPUT} value={s.role} onChange={(e) => setSet(i, { role: e.target.value })}>
                <option value="starter">starter task</option><option value="sequence">practice sequence</option><option value="none">not assigned</option>
              </select>
              <input disabled={readOnly} className={INPUT + " col-span-2"} placeholder="Skill ids for untagged items" value={s.skillIds} onChange={(e) => setSet(i, { skillIds: e.target.value })} />
              <select disabled={readOnly} className={INPUT} value={s.difficulty} onChange={(e) => setSet(i, { difficulty: e.target.value })}><option>easy</option><option>medium</option><option>hard</option></select>
              <input disabled={readOnly} type="number" min="5" max="120" className={INPUT} value={s.durationMin} onChange={(e) => setSet(i, { durationMin: e.target.value })} />
            </div>
            <ul className="mt-2 text-xs space-y-0.5">
              {s.items.map((r, k) => (
                <li key={r.itemId} className="flex items-center gap-2">
                  <span>{k + 1}.</span><span className="font-mono">{r.itemId}</span>{r.version ? <span className="text-slate-500">v{r.version}</span> : <span className="text-slate-500">current approved</span>}
                  {!readOnly && <button className="text-rose-600" onClick={(e) => { e.stopPropagation(); setSet(i, { items: s.items.filter((x) => x.itemId !== r.itemId) }); }}>remove</button>}
                </li>
              ))}
              {!s.items.length && <li className="text-slate-500">No items yet: tick approved items below and add them to this set.</li>}
            </ul>
          </div>
        ))}
        {!readOnly && <button className={SMALL_BTN + " ring-1 ring-slate-200"} onClick={() => { setDraft({ ...draft, sets: draft.sets.concat([HSBankApi.emptySet(draft.sets.length + 1)]) }); setOpen(draft.sets.length); }}>Add set</button>}
      </div>

      {!readOnly && <ApprovedPicker courseId={draft.courseId} used={used} onAdd={(ids) => setSet(open, { items: draft.sets[open].items.concat(ids.map((id) => ({ itemId: id }))) })} />}

      {problems.length > 0 && !readOnly && <ul className="text-xs text-amber-900 bg-amber-50 rounded p-2 list-disc pl-5">{problems.map((p) => <li key={p}>{p}</li>)}</ul>}
      {!readOnly && <button disabled={busy || problems.length > 0} className={SMALL_BTN + " bg-slate-900 text-white"} onClick={save}>{selection ? "Save changes" : "Create selection"}</button>}

      {selection && !readOnly && (
        <div className="rounded-lg bg-slate-50 p-3">
          <div className="text-sm font-semibold">Build a package version</div>
          <p className="text-xs text-slate-500">Uses the latest {selection.courseId} package of your organization for the manifest, skills and tutor prompt. The result is a draft: submit it in the author portal for platform review.</p>
          <div className="mt-2 flex gap-2">
            <input className={INPUT + " w-32"} placeholder="e.g. 3.0.0" value={version} onChange={(e) => setVersion(e.target.value)} />
            <button disabled={busy || !/^\d+\.\d+\.\d+$/.test(version)} className={SMALL_BTN + " bg-indigo-600 text-white"} onClick={build}>{busy ? "Building…" : "Build"}</button>
          </div>
          {selection.builtPackageVersion && <p className="text-xs mt-2">Last built: v{selection.builtPackageVersion} by {selection.builtBy}</p>}
          {built && <div className="mt-3"><div className="text-sm">Built {built.package.courseId} v{built.package.version} <Badge status={built.package.status} /> — <a className="text-indigo-700 underline" href="author.html">open in the author portal</a></div><div className="mt-2"><Report report={built.package.report} /></div></div>}
        </div>
      )}
      <ErrorNote error={error} />
    </div>
  );
}

function SelectionsTab({ me }) {
  const [list, setList] = React.useState(null);
  const [open, setOpen] = React.useState(null); // a selection, "new", or null
  const [error, setError] = React.useState(null);
  const load = React.useCallback(async () => {
    try { setList((await BANK.listSelections()).selections); } catch (err) { setError(err); setList([]); }
  }, []);
  React.useEffect(() => { load(); }, [load]);
  return (
    <div className="mt-4 grid grid-cols-1 md:grid-cols-[300px_minmax(0,1fr)] gap-4">
      <div className={CARD + " p-4"}>
        <div className="flex items-center justify-between"><h2 className="font-semibold">Selections</h2>
          {me.canReview && <button className={SMALL_BTN + " bg-slate-900 text-white"} onClick={() => setOpen("new")}>New</button>}</div>
        {list === null ? <p className="text-sm mt-2">Loading…</p> : list.length === 0 ? <p className="text-sm text-slate-500 mt-2">No selections yet.</p> : (
          <ul className="mt-2 space-y-1">{list.map((s) => (
            <li key={s.selectionId}><button className="w-full text-left px-2 py-1 rounded hover:bg-slate-50" onClick={() => setOpen(s)}>
              <div className="text-sm">{s.name}</div>
              <div className="text-xs text-slate-500">{s.courseId} · {s.sets.length} set(s){s.builtPackageVersion ? " · built v" + s.builtPackageVersion : ""}</div>
            </button></li>
          ))}</ul>
        )}
        <ErrorNote error={error} />
      </div>
      <div>{open ? (
        <SelectionEditor key={open === "new" ? "new" : open.selectionId} me={me}
          selection={open === "new" ? null : open} onClose={() => setOpen(null)}
          onSaved={(s) => { setOpen(s); load(); }} />
      ) : <p className="text-sm text-slate-500">Open a selection{me.canReview ? " or create a new one" : ""}.</p>}</div>
    </div>
  );
}

// ---- Add questions (Step 39A: form, paste, spreadsheet) ----------------------------------------

const EMPTY_SETTINGS = { courseId: "dsat", section: "", skillIds: "", difficulty: "", keyOrigin: "source-key",
  sourceTitle: "", sourceLicense: "", tags: "" };
const EMPTY_FORM = { stem: "", type: "mc", choices: { A: "", B: "", C: "", D: "" }, answer: "", solution: "",
  passageMode: "none", passageTitle: "", passageText: "", previousPassageId: null };

function SettingsPanel({ settings, setSettings }) {
  const set = (k) => (e) => setSettings({ ...settings, [k]: e.target.value });
  return (
    <div className={CARD + " p-4 space-y-2"}>
      <div className="text-sm font-semibold">Apply to every question</div>
      <p className="text-xs text-slate-500">Fields left empty here keep what each question says.</p>
      <input className={INPUT + " w-full"} placeholder="Course id (e.g. dsat)" value={settings.courseId} onChange={set("courseId")} />
      <input className={INPUT + " w-full"} placeholder="Section (e.g. math, reading)" value={settings.section} onChange={set("section")} />
      <input className={INPUT + " w-full"} placeholder="Skill ids, comma-separated" value={settings.skillIds} onChange={set("skillIds")} />
      <div className="flex gap-2">
        <select className={INPUT} value={settings.difficulty} onChange={set("difficulty")}><option value="">difficulty</option><option>easy</option><option>medium</option><option>hard</option></select>
        <select className={INPUT} value={settings.keyOrigin} onChange={set("keyOrigin")}>
          <option value="source-key">keys printed in the source</option><option value="compiled-key">keys from a third-party list</option>
        </select>
      </div>
      <input className={INPUT + " w-full"} placeholder="Source title (e.g. Worksheet 3, Unit 2 quiz)" value={settings.sourceTitle} onChange={set("sourceTitle")} />
      <input className={INPUT + " w-full"} placeholder="Source and license note (recorded)" value={settings.sourceLicense} onChange={set("sourceLicense")} />
      <input className={INPUT + " w-full"} placeholder="Tags, comma-separated" value={settings.tags} onChange={set("tags")} />
    </div>
  );
}

function SingleForm({ settings, onImported }) {
  const [form, setForm] = React.useState(EMPTY_FORM);
  const [busy, setBusy] = React.useState(false);
  const [error, setError] = React.useState(null);
  const [saved, setSaved] = React.useState(null);
  const action = React.useRef("one-" + Date.now());
  const set = (k) => (e) => setForm({ ...form, [k]: e.target.value });
  const problems = HSBankApi.formProblems(form);
  async function save() {
    setBusy(true); setError(null);
    try {
      const body = { ...HSBankApi.formBatch(form), settings: HSBankApi.settingsBody(settings) };
      const job = await BANK.importBatch(body, action.current);
      action.current = "one-" + Date.now();
      setSaved(job); onImported(job);
      if (job.itemCount) {
        const passageId = form.passageMode === "new" ? job.passageIds[0] : form.previousPassageId;
        setForm({ ...EMPTY_FORM, type: form.type, previousPassageId: passageId || null,
          passageMode: passageId && form.passageMode !== "none" ? "previous" : "none" });
      }
    } catch (err) { setError(err); } finally { setBusy(false); }
  }
  return (
    <div className="space-y-2">
      <div className="flex gap-2 text-sm">
        {[["none", "No passage"], ["new", "New passage"], ["previous", "Same passage as before"]].map(([v, t]) => (
          <label key={v} className="flex items-center gap-1"><input type="radio" checked={form.passageMode === v} onChange={() => setForm({ ...form, passageMode: v })} disabled={v === "previous" && !form.previousPassageId} />{t}</label>
        ))}
      </div>
      {form.passageMode === "new" && (
        <div className="space-y-1">
          <input className={INPUT + " w-full"} placeholder="Passage title (e.g. Questions 1-5 are based on …)" value={form.passageTitle} onChange={set("passageTitle")} />
          <textarea className={INPUT + " w-full h-28"} placeholder="Passage text" value={form.passageText} onChange={set("passageText")} />
        </div>
      )}
      <textarea className={INPUT + " w-full h-24"} placeholder="Question (mark underlined text as [[text]])" value={form.stem} onChange={set("stem")} />
      <select className={INPUT} value={form.type} onChange={set("type")}><option value="mc">multiple choice</option><option value="spr">student-produced response (grid-in)</option></select>
      {form.type === "mc" && ["A", "B", "C", "D"].map((k) => (
        <div key={k} className="flex items-center gap-2"><span className="w-5 text-sm font-semibold">{k}</span>
          <input className={INPUT + " flex-1"} value={form.choices[k]} onChange={(e) => setForm({ ...form, choices: { ...form.choices, [k]: e.target.value } })} /></div>
      ))}
      <div className="flex gap-2">
        <input className={INPUT + " w-48"} placeholder={form.type === "mc" ? "Key: A, B, C or D" : "Accepted answers, e.g. 7/2|3.5"} value={form.answer} onChange={set("answer")} />
        <span className="text-xs text-slate-500 self-center">Leave empty if you have no key; the content reviewer can add it.</span>
      </div>
      <textarea className={INPUT + " w-full h-16"} placeholder="Solution or explanation (optional)" value={form.solution} onChange={set("solution")} />
      {problems.length > 0 && <ul className="text-xs text-amber-900 bg-amber-50 rounded p-2 list-disc pl-5">{problems.map((p) => <li key={p}>{p}</li>)}</ul>}
      <button disabled={busy || problems.length > 0} className={SMALL_BTN + " bg-slate-900 text-white"} onClick={save}>{busy ? "Saving…" : "Save and add next"}</button>
      {saved && (saved.itemCount
        ? <p className="text-sm text-emerald-700">Saved as a draft ({saved.itemIds[0]}). The form is ready for the next question.</p>
        : <p className="text-sm text-amber-800">Not saved: {saved.skipped.join("; ")}</p>)}
      <ErrorNote error={error} />
    </div>
  );
}

function BulkImport({ format, settings, onImported }) {
  const [text, setText] = React.useState("");
  const [preview, setPreview] = React.useState(null);
  const [keep, setKeep] = React.useState(new Set());
  const [busy, setBusy] = React.useState(false);
  const [error, setError] = React.useState(null);
  const [result, setResult] = React.useState(null);
  const run = React.useRef(0);
  async function doPreview() {
    setBusy(true); setError(null); setResult(null);
    try {
      const p = await BANK.parse(format, text);
      setPreview(p); run.current += 1;
      setKeep(new Set(p.questions.filter((q) => !q.duplicateOf).map((q) => q.number)));
    } catch (err) { setError(err); } finally { setBusy(false); }
  }
  async function doImport() {
    setBusy(true); setError(null);
    const keepDup = preview.questions.some((q) => q.duplicateOf && keep.has(q.number));
    const chunks = HSBankApi.chunkBatch(HSBankApi.batchFromPreview(preview, keep), 100);
    const jobs = [];
    try {
      for (let i = 0; i < chunks.length; i++) {
        const body = { ...chunks[i], settings: HSBankApi.settingsBody(settings), keepDuplicates: keepDup };
        jobs.push(await BANK.importBatch(body, "bulk:" + run.current + ":" + i));
      }
      setResult({ created: jobs.reduce((n, j) => n + j.itemCount, 0), skipped: jobs.flatMap((j) => j.skipped) });
      jobs.forEach(onImported); setPreview(null); setText("");
    } catch (err) { setError(err); } finally { setBusy(false); }
  }
  function readFile(e) {
    const f = e.target.files && e.target.files[0];
    if (f) f.text().then(setText);
  }
  const passages = preview ? Object.fromEntries(preview.passages.map((p) => [p.ref, p])) : {};
  return (
    <div className="space-y-2">
      {format === "csv" ? (
        <div className="flex items-center gap-3 text-sm">
          <input type="file" accept=".csv,text/csv" onChange={readFile} />
          <a className="text-indigo-700 underline" download="question-template.csv" href={"data:text/csv;charset=utf-8," + encodeURIComponent(HSBankApi.CSV_TEMPLATE)}>Download the template</a>
        </div>
      ) : (
        <p className="text-xs text-slate-500">Paste questions numbered 1., 2., … with choices A) – D). Keys can follow each question (“Answer: B”) or come as a block at the end (“Answers 1. B 2. D”). A line like “Questions 1-3 refer to the following passage.” starts a passage for those questions.</p>
      )}
      <textarea className={INPUT + " w-full h-56 font-mono text-xs"} placeholder={format === "csv" ? "…or paste CSV here (first row: the header)" : "Paste questions here"} value={text} onChange={(e) => { setText(e.target.value); setPreview(null); }} />
      <button disabled={busy || !text.trim()} className={SMALL_BTN + " bg-slate-900 text-white"} onClick={doPreview}>{busy && !preview ? "Reading…" : "Preview"}</button>
      <ErrorNote error={error} />
      {result && <p className="text-sm text-emerald-700">Imported {result.created} question(s) as drafts.{result.skipped.length ? " Skipped: " + result.skipped.join("; ") : ""}</p>}
      {preview && (
        <div className={CARD + " p-3"}>
          <div className="flex items-center justify-between">
            <div className="text-sm font-semibold">{preview.questions.length} question(s), {preview.passages.length} passage(s) found — {keep.size} selected</div>
            <button disabled={busy || !keep.size} className={SMALL_BTN + " bg-indigo-600 text-white"} onClick={doImport}>{busy ? "Importing…" : "Import " + keep.size + " as drafts"}</button>
          </div>
          {preview.problems.length > 0 && <ul className="mt-2 text-xs text-amber-900 bg-amber-50 rounded p-2 list-disc pl-5">{preview.problems.map((p) => <li key={p}>{p}</li>)}</ul>}
          <ul className="mt-2 divide-y divide-slate-100 max-h-[60vh] overflow-auto">
            {preview.questions.map((q) => (
              <li key={q.number} className="py-2 text-sm flex gap-3">
                <input type="checkbox" className="mt-1" checked={keep.has(q.number)} onChange={(e) => { const k = new Set(keep); e.target.checked ? k.add(q.number) : k.delete(q.number); setKeep(k); }} />
                <div className="flex-1 min-w-0">
                  <div><b>{q.number}.</b> <Underlined text={q.content.stem || "(no question text)"} /></div>
                  {q.passageRef && <div className="text-xs text-slate-500">Passage: {passages[q.passageRef] ? passages[q.passageRef].title : q.passageRef}</div>}
                  {q.content.choices && <div className="text-xs text-slate-600">{Object.entries(q.content.choices).map(([k, v]) => k + ") " + v).join("   ")}</div>}
                  <div className="text-xs">Key: {q.content.answer ? <b>{q.content.answer}</b> : <span className="text-slate-500">none</span>}{q.content.type === "spr" ? " · grid-in" : ""}{q.content.solution ? " · has solution" : ""}</div>
                  {q.duplicateOf && <div className="text-xs text-amber-800">Duplicate of {q.duplicateOf} — not imported unless ticked</div>}
                  {q.problems.length > 0 && <div className="text-xs text-amber-800">{q.problems.join(" · ")}</div>}
                </div>
              </li>
            ))}
          </ul>
        </div>
      )}
    </div>
  );
}

function ImportHistory({ refresh }) {
  const [jobs, setJobs] = React.useState(null);
  React.useEffect(() => { BANK.listImports().then((r) => setJobs(r.imports)).catch(() => setJobs([])); }, [refresh]);
  if (!jobs || !jobs.length) return null;
  return (
    <div className={CARD + " p-4"}>
      <div className="text-sm font-semibold">Recent imports</div>
      <ul className="mt-2 text-xs space-y-1">{jobs.slice(0, 10).map((j) => (
        <li key={j.jobId}>{new Date(j.createdAt).toLocaleString()} · {j.kind} · <b>{j.itemCount}</b> created{j.skipped.length ? ", " + j.skipped.length + " skipped" : ""}{j.sourceTitle ? " · " + j.sourceTitle : ""} · {j.createdBy}</li>
      ))}</ul>
    </div>
  );
}

function AddTab() {
  const [mode, setMode] = React.useState("one");
  const [settings, setSettings] = React.useState(EMPTY_SETTINGS);
  const [refresh, setRefresh] = React.useState(0);
  const modes = [["one", "One question"], ["text", "Paste text"], ["csv", "Spreadsheet (CSV)"]];
  return (
    <div className="mt-4 grid grid-cols-1 md:grid-cols-[minmax(0,1fr)_320px] gap-4">
      <div className={CARD + " p-4"}>
        <div className="flex gap-2 text-sm mb-3">
          {modes.map(([m, t]) => (
            <button key={m} onClick={() => setMode(m)} className={"px-3 py-1 rounded-full " + (mode === m ? "bg-indigo-600 text-white" : "ring-1 ring-slate-200")}>{t}</button>
          ))}
        </div>
        {mode === "one"
          ? <SingleForm settings={settings} onImported={() => setRefresh(refresh + 1)} />
          : <BulkImport key={mode} format={mode} settings={settings} onImported={() => setRefresh((r) => r + 1)} />}
      </div>
      <div className="space-y-4">
        <SettingsPanel settings={settings} setSettings={setSettings} />
        <ImportHistory refresh={refresh} />
      </div>
    </div>
  );
}

// ---- Page ---------------------------------------------------------------------------------------

function Bank({ onSignOut }) {
  const [me, setMe] = React.useState(null);
  const [error, setError] = React.useState(null);
  const [tab, setTab] = React.useState("items");
  React.useEffect(() => { BANK.me().then(setMe).catch(setError); }, []);
  return (
    <div className="max-w-7xl mx-auto p-4">
      <header className="flex items-center justify-between">
        <div className="flex items-center gap-3">
          <h1 className="text-xl font-bold">Question bank</h1>
          {me && <span className="text-xs text-slate-500">{me.orgId} · {me.uid} · {me.canReview ? "content reviewer" : "author"}</span>}
        </div>
        <div className="flex items-center gap-4">
          <a className="text-sm text-slate-500" href="author.html">Author portal</a>
          <button className="text-sm text-slate-500" onClick={onSignOut}>Sign out</button>
        </div>
      </header>
      {error && <ErrorNote error={error} text={error.status === 403 ? "This account has no organization question bank (authors and content reviewers only)." : null} />}
      {me && (
        <>
          <div className="mt-4 flex gap-2 text-sm">
            {["items", "add questions", "selections"].map((t) => (
              <button key={t} onClick={() => setTab(t)} className={"px-3 py-1 rounded-full " + (tab === t ? "bg-slate-900 text-white" : "ring-1 ring-slate-200")}>{t}</button>
            ))}
          </div>
          {tab === "items" ? <ItemsTab me={me} /> : tab === "add questions" ? <AddTab /> : <SelectionsTab me={me} />}
        </>
      )}
    </div>
  );
}

function App() {
  const [uid, setUid] = React.useState(null);
  const [ready, setReady] = React.useState(false);
  const refresh = React.useCallback(async () => {
    await AUTH.getIdToken().catch(() => null);
    setUid(AUTH.currentUid()); setReady(true);
  }, []);
  React.useEffect(() => { refresh(); }, [refresh]);
  if (!ready) return null;
  if (!uid) return <SignIn auth={AUTH} title="Question bank" onSignedIn={refresh} />;
  return <Bank onSignOut={async () => { await AUTH.signOut(); refresh(); }} />;
}

ReactDOM.createRoot(document.getElementById("root")).render(<App />);
