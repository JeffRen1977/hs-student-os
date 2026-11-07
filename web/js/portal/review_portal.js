// review_portal.js — the reviewer screen (Step 41). Platform reviewers take a submitted
// package version to approved and active (or rejected), and retire courses, through the
// existing /api/review endpoints. The server checks the reviewer role on every call; an
// author or student who opens this page gets "not a platform reviewer" and nothing else.

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
const R = HSReviewApi;
const API = R.createReviewApi({ baseUrl: API_BASE_URL, getIdToken: () => AUTH.getIdToken() });

function safeLocalStorage() {
  try { return window.localStorage; } catch (_e) { return null; }
}

const when = (at) => (at ? new Date(at).toLocaleString() : "—");
const INPUT = "w-full rounded-lg ring-1 ring-slate-200 px-3 py-2 text-sm";

function ReviewError({ error }) {
  return <ErrorNote error={error} text={error ? R.reviewErrorText(error) : null} />;
}

// ---- Decisions ------------------------------------------------------------------------------

function Confirm({ message, busy, onConfirm, onCancel }) {
  return (
    <div className="mt-3 rounded-lg bg-amber-50 ring-1 ring-amber-200 p-3 text-sm">
      <div>{message}</div>
      <div className="mt-2 flex gap-2">
        <button disabled={busy} onClick={onConfirm} className={BTN + " rounded-lg bg-slate-900 text-white px-3 py-1.5 disabled:opacity-40"}>{busy ? "Working…" : "Confirm"}</button>
        <button disabled={busy} onClick={onCancel} className="rounded-lg ring-1 ring-slate-300 px-3 py-1.5">Cancel</button>
      </div>
    </div>
  );
}

function Decisions({ version, activeVersion, onDone }) {
  const [notes, setNotes] = React.useState("");
  const [license, setLicense] = React.useState(false);
  const [modelEval, setModelEval] = React.useState(false);
  const [pending, setPending] = React.useState(null);
  const [busy, setBusy] = React.useState(false);
  const [error, setError] = React.useState(null);
  const c = version.courseId, v = version.version;
  const modelCases = version.report.evaluation.modelCases;
  const actions = R.actionsFor(version.status);
  if (actions.length === 0) return null;

  const plans = {
    approve: {
      label: "Approve", color: "bg-emerald-600",
      blocked: !license ? "Attest the content license first." : modelCases && !modelEval ? "Attest the model-graded evaluation cases first." : null,
      message: "Approve " + c + " " + v + "? The version is recorded as approved by you; it does not go live until it is activated.",
      run: () => API.approve(c, v, { notes, licenseAttested: license, modelEvaluationAttested: modelEval }),
    },
    reject: {
      label: "Reject", color: "bg-rose-600",
      blocked: notes.trim() ? null : "Rejecting needs notes: the author sees them.",
      message: "Reject " + c + " " + v + "? This cannot be undone; the author must upload a new version.",
      run: () => API.reject(c, v, notes.trim()),
    },
    activate: {
      label: "Activate", color: "bg-indigo-600", blocked: null,
      message: activeVersion && activeVersion !== v
        ? "Activate " + c + " " + v + "? " + activeVersion + " becomes superseded: sessions already open finish on it, new practice uses " + v + "."
        : "Activate " + c + " " + v + "? Students with access can then enroll.",
      run: () => API.activate(c, v),
    },
    retire: {
      label: "Retire course", color: "bg-slate-700",
      blocked: notes.trim() ? null : "Retiring needs notes.",
      message: "Retire " + c + "? No new enrollments, sessions or work for any student. Student records are kept. This cannot be undone.",
      run: () => API.retire(c, notes.trim()),
    },
  };

  async function confirm() {
    setBusy(true); setError(null);
    try {
      const updated = await plans[pending].run();
      setPending(null); setNotes("");
      onDone(updated);
    } catch (err) { setError(err); setPending(null); } finally { setBusy(false); }
  }

  const needsNotes = actions.some((a) => a === "approve" || a === "reject" || a === "retire");
  return (
    <div className="mt-4 rounded-xl ring-1 ring-slate-200 p-3">
      <div className="font-semibold text-sm">Decision</div>
      {needsNotes && (
        <textarea className={INPUT + " mt-2 h-20"} maxLength={2000} value={notes} onChange={(e) => setNotes(e.target.value)}
          placeholder={version.status === "active" ? "Why the course is retired (required)" : "Notes for the author (required to reject)"} />
      )}
      {actions.includes("approve") && (
        <div className="mt-2 space-y-1 text-sm">
          <label className="flex gap-2 items-start"><input type="checkbox" checked={license} onChange={(e) => setLicense(e.target.checked)} className="mt-1" />
            <span>I checked the sources: every question and rubric is original or licensed for this use (no official test or prep-book material).</span></label>
          {modelCases > 0 && (
            <label className="flex gap-2 items-start"><input type="checkbox" checked={modelEval} onChange={(e) => setModelEval(e.target.checked)} className="mt-1" />
              <span>I ran and checked the {modelCases} model-graded evaluation case(s).</span></label>
          )}
        </div>
      )}
      <div className="mt-3 flex flex-wrap gap-2">
        {actions.map((a) => (
          <button key={a} disabled={busy || !!pending || !!plans[a].blocked} title={plans[a].blocked || ""}
            onClick={() => { setError(null); setPending(a); }}
            className={BTN + " rounded-lg text-white px-4 py-2 text-sm disabled:opacity-40 " + plans[a].color}>{plans[a].label}</button>
        ))}
      </div>
      {actions.map((a) => plans[a].blocked && <div key={a} className="text-xs text-slate-500 mt-1">{plans[a].label}: {plans[a].blocked}</div>)}
      {pending && <Confirm message={plans[pending].message} busy={busy} onConfirm={confirm} onCancel={() => setPending(null)} />}
      <ReviewError error={error} />
    </div>
  );
}

// ---- Content -------------------------------------------------------------------------------

function SkillTags({ skills }) {
  return <span className="text-xs text-slate-500">{skills.map((s) => s.name + " (" + s.skillId + ")").join(", ") || "no skill"}</span>;
}

function ReviewStatus({ review }) {
  if (!review) return null;
  const ok = review.status === "reviewed";
  return <span className={"px-2 py-0.5 rounded-full text-xs " + (ok ? "bg-emerald-50 text-emerald-700" : "bg-amber-50 text-amber-700")}>
    content {review.status}{review.reviewer ? " by " + review.reviewer : ""}</span>;
}

function TaskList({ title, tasks }) {
  if (!tasks || !tasks.length) return null;
  return (
    <div className="mt-3">
      <div className="text-xs font-semibold text-slate-500">{title}</div>
      <ol className="text-sm list-decimal pl-5">{tasks.map((t) => <li key={t.questionId}>{t.title} <span className="text-xs text-slate-500">({t.questionId}, {t.durationMin} min)</span></li>)}</ol>
    </div>
  );
}

function Content({ pkg }) {
  const questions = React.useMemo(() => R.reviewContent(pkg), [pkg]);
  const m = pkg.manifest;
  return (
    <div className="space-y-4">
      <div className="text-sm space-y-1">
        <div><b>{m.name}</b> · {m.category} · publisher {m.publisher && m.publisher.name}</div>
        <div>License: {m.license}</div>
        <div>Abilities: {(m.abilities || []).join(", ")} · Tools: {(m.tools || []).join(", ") || "none"} · Model tier: {m.modelTier}</div>
        <div className="text-xs text-slate-500">{pkg.skills.length} skills · {pkg.questions.length} questions · {pkg.rubrics.length} rubrics · {(pkg.evaluationSet || []).length} evaluation cases</div>
        <details className="mt-1"><summary className="cursor-pointer text-sm">Tutor instructions (system prompt)</summary>
          <pre className="mt-1 whitespace-pre-wrap text-xs bg-slate-50 rounded p-2">{pkg.systemPrompt}</pre></details>
        <details><summary className="cursor-pointer text-sm">Skills</summary>
          <ul className="mt-1 text-xs">{pkg.skills.map((s) => <li key={s.skillId}><code>{s.skillId}</code> — {s.name}</li>)}</ul></details>
        <TaskList title="Starter tasks" tasks={pkg.starterTasks} />
        <TaskList title="Practice sequence" tasks={pkg.practiceSequence} />
      </div>
      {questions.map((q) => (
        <div key={q.questionId} className="rounded-lg ring-1 ring-slate-200 p-3">
          <div className="flex flex-wrap items-center gap-2 text-xs text-slate-500">
            <span>{q.questionId} · v{q.version} · {q.topic}</span><ReviewStatus review={q.review} />
          </div>
          <div className="text-xs text-slate-500 mt-1">
            Source: {q.source ? q.source.type + (q.source.author ? ", " + q.source.author : "") + " — " + q.source.license : "missing"}
            {q.rubric && <span> · Rubric {q.rubric.rubricId}@{q.rubric.version}</span>}
          </div>
          <div className="text-sm whitespace-pre-wrap mt-1">{q.prompt}</div>
          {q.sources.map((s) => (
            <blockquote key={s.materialId} className="mt-2 border-l-4 border-slate-300 pl-3 text-sm"><div className="font-semibold text-xs">{s.title}</div>{s.text}</blockquote>
          ))}
          {q.items ? (
            <ol className="mt-2 space-y-2">{q.items.map((i) => (
              <li key={i.itemId} className="text-sm">
                <div><b>{i.itemId}.</b> <span className="whitespace-pre-wrap">{i.prompt}</span></div>
                <div className="pl-4 text-sm">{i.choices.map((ch) => (
                  <div key={ch.key} className={ch.key === i.answerKey ? "text-emerald-700 font-semibold" : ""}>{ch.key}) {ch.text}{ch.key === i.answerKey ? "  ← key" : ""}</div>
                ))}</div>
                <div className="pl-4"><SkillTags skills={i.skills} /> <span className="text-xs text-slate-400">· {i.criterionId}</span></div>
              </li>
            ))}</ol>
          ) : (
            <div className="mt-2 text-sm">
              {q.expectedAnswer && <div><span className="text-xs font-semibold text-slate-500">Expected answer:</span> <span className="whitespace-pre-wrap">{q.expectedAnswer}</span></div>}
              <ul className="mt-1 text-xs space-y-1">{q.criteria.map((c) => (
                <li key={c.criterionId}><b>{c.criterionId}</b> ({c.maxPoints} pt): {c.description} — {(c.evidenceRequirements || []).join("; ")}</li>
              ))}</ul>
              <SkillTags skills={q.skills} />
            </div>
          )}
        </div>
      ))}
    </div>
  );
}

function Compare({ courseId, activeVersion, pkg }) {
  const [state, setState] = React.useState({ loading: true });
  React.useEffect(() => {
    let live = true;
    API.getVersion(courseId, activeVersion)
      .then((a) => live && setState({ diff: R.comparePackages(a.package, pkg) }))
      .catch((error) => live && setState({ error }));
    return () => { live = false; };
  }, [courseId, activeVersion, pkg]);
  if (state.error) return <ReviewError error={state.error} />;
  if (state.loading) return <p className="text-sm">Loading {activeVersion}…</p>;
  const d = state.diff;
  const list = (ids) => (ids.length ? ids.join(", ") : "none");
  return (
    <div className="text-sm space-y-2">
      <p className="text-xs text-slate-500">Compared with the active version {activeVersion}.</p>
      {d.warnings.length > 0 ? (
        <ul className="rounded-lg bg-rose-50 text-rose-800 p-3 space-y-1">{d.warnings.map((w) => <li key={w.kind + w.id}>⚠ {w.message}</li>)}</ul>
      ) : <div className="rounded-lg bg-emerald-50 text-emerald-800 p-3">Every question and skill ID in {activeVersion} is kept.</div>}
      <div><b>Questions added</b> ({d.questions.added.length}): {list(d.questions.added)}</div>
      <div><b>Questions removed</b> ({d.questions.removed.length}): {list(d.questions.removed)}</div>
      <div><b>Questions changed</b> ({d.questions.changed.length}): {d.questions.changed.length ? d.questions.changed.map((c) => c.questionId + " (v" + c.fromVersion + " → v" + c.toVersion + ": " + c.fields.join(", ") + ")").join("; ") : "none"}</div>
      <div><b>Skills added</b> ({d.skills.added.length}): {list(d.skills.added)}</div>
      <div><b>Skills removed</b> ({d.skills.removed.length}): {list(d.skills.removed)}</div>
      {d.skills.renamed.length > 0 && <div><b>Skills renamed</b>: {d.skills.renamed.map((r) => r.skillId + ": " + r.from + " → " + r.to).join("; ")}</div>}
    </div>
  );
}

function Checklist({ pkg, reviewer, courseId, version }) {
  const list = React.useMemo(() => R.createChecklist(safeLocalStorage(), reviewer, courseId, version), [reviewer, courseId, version]);
  const items = React.useMemo(() => R.checklistItems(pkg), [pkg]);
  const keys = React.useMemo(() => {
    const out = {};
    for (const q of pkg.questions) for (const i of q.items || []) out[q.questionId + "#" + i.itemId] = i.answerKey;
    return out;
  }, [pkg]);
  const [, bump] = React.useState(0);
  const p = list.progress(items);
  return (
    <div className="text-sm">
      <p className="text-xs text-slate-500">A working aid saved in this browser only. It is not sent to the server and is not part of the review record; your decision and notes are.</p>
      <div className="mt-2 font-semibold">{p.done} / {p.total} items fully checked</div>
      <table className="mt-2 w-full text-xs">
        <thead><tr className="text-left text-slate-500"><th className="py-1">Item</th>{R.CHECKS.map((c) => <th key={c.id} className="px-1">{c.label}</th>)}</tr></thead>
        <tbody>{items.map((i) => (
          <tr key={i.key} className="border-t border-slate-100">
            <td className="py-1">{i.questionId}{i.itemId ? " · item " + i.itemId : ""}{keys[i.key] ? " (key " + keys[i.key] + ")" : ""}</td>
            {R.CHECKS.map((c) => (
              <td key={c.id} className="px-1 text-center"><input type="checkbox" aria-label={i.key + " " + c.label} checked={list.isChecked(i.key, c.id)}
                onChange={(e) => { list.set(i.key, c.id, e.target.checked); bump((n) => n + 1); }} /></td>
            ))}
          </tr>
        ))}</tbody>
      </table>
    </div>
  );
}

// ---- Version view --------------------------------------------------------------------------

function VersionView({ summary, activeVersion, reviewer, onChanged }) {
  const [full, setFull] = React.useState(null);
  const [tab, setTab] = React.useState("report");
  const [preview, setPreview] = React.useState(null);
  const [error, setError] = React.useState(null);
  const c = summary.courseId, v = summary.version;
  const relation = R.versionRelation(summary.status, v, activeVersion);
  const isUpgrade = relation === "upgrade";
  React.useEffect(() => {
    let live = true;
    setFull(null); setPreview(null); setError(null); setTab("report");
    API.getVersion(c, v).then((x) => live && setFull(x)).catch((err) => live && setError(err));
    return () => { live = false; };
  }, [c, v, summary.updatedAt]);
  async function open(t) {
    setTab(t); setError(null);
    if (t === "preview" && !preview) {
      try { setPreview(await API.preview(c, v)); } catch (err) { setError(err); }
    }
  }
  const tabs = ["report", "content", "preview"].concat(isUpgrade ? ["compare"] : [], ["history", "checklist"]);
  return (
    <div className={CARD + " p-4"}>
      <div className="flex flex-wrap items-center gap-2">
        <h2 className="font-semibold">{summary.title || c}</h2>
        <span className="text-xs text-slate-500">{c} v{v} · {summary.orgId} · uploaded by {summary.uploadedBy}</span>
        <Badge status={summary.status} />
        {isUpgrade && <span className="px-2 py-0.5 rounded-full text-xs bg-indigo-50 text-indigo-700">upgrade of {activeVersion}</span>}
        {relation === "older" && <span className="px-2 py-0.5 rounded-full text-xs bg-rose-50 text-rose-700">older than active {activeVersion}: cannot be activated</span>}
      </div>
      {summary.review && (
        <div className="mt-2 text-xs text-slate-600">Decision: {summary.review.decision} by {summary.review.reviewerId} on {when(summary.review.decidedAt)}
          {summary.review.notes ? " — " + summary.review.notes : ""}{summary.review.licenseAttested ? " · license attested" : ""}{summary.review.modelEvaluationAttested ? " · model evaluation attested" : ""}</div>
      )}
      <Decisions key={c + "@" + v + ":" + summary.status} version={summary} activeVersion={activeVersion} onDone={onChanged} />
      <div className="mt-4 flex flex-wrap gap-2 text-sm">
        {tabs.map((t) => (
          <button key={t} onClick={() => open(t)} className={"px-3 py-1 rounded-full " + (tab === t ? "bg-slate-900 text-white" : "ring-1 ring-slate-200")}>{t}</button>
        ))}
      </div>
      <div className="mt-3">
        {tab === "report" && <Report report={summary.report} />}
        {tab === "content" && (full ? <Content pkg={full.package} /> : !error && <p className="text-sm">Loading…</p>)}
        {tab === "preview" && (preview ? <Preview preview={preview} /> : !error && <p className="text-sm">Loading…</p>)}
        {tab === "compare" && (full ? <Compare courseId={c} activeVersion={activeVersion} pkg={full.package} /> : <p className="text-sm">Loading…</p>)}
        {tab === "checklist" && (full ? <Checklist pkg={full.package} reviewer={reviewer} courseId={c} version={v} /> : <p className="text-sm">Loading…</p>)}
        {tab === "history" && (
          <ul className="text-sm space-y-1">{summary.history.map((h, i) => (
            <li key={i}>{when(h.at)}: {h.fromStatus || "—"} → <b>{h.toStatus}</b> by {h.actorId}{h.notes ? " — " + h.notes : ""}</li>
          ))}</ul>
        )}
      </div>
      <ReviewError error={error} />
    </div>
  );
}

// ---- Queue ---------------------------------------------------------------------------------

function Row({ v, selected, onSelect, detail }) {
  const id = v.courseId + "@" + v.version;
  return (
    <li><button onClick={() => onSelect(id)} className={"w-full text-left px-2 py-1.5 rounded " + (selected === id ? "bg-slate-100" : "hover:bg-slate-50")}>
      <div className="flex items-center gap-2"><span className="text-sm">{v.courseId} v{v.version}</span><Badge status={v.status} /></div>
      <div className="text-xs text-slate-500">{detail}</div>
    </button></li>
  );
}

function Section({ title, empty, children }) {
  const rows = React.Children.toArray(children);
  return (
    <div className={CARD + " p-4"}>
      <h2 className="font-semibold text-sm">{title}</h2>
      {rows.length ? <ul className="mt-2 space-y-1">{rows}</ul> : <p className="text-xs text-slate-500 mt-2">{empty}</p>}
    </div>
  );
}

function ReviewPortal({ onSignOut }) {
  const [versions, setVersions] = React.useState(null);
  const [selected, setSelected] = React.useState(null);
  const [error, setError] = React.useState(null);
  const load = React.useCallback(async () => {
    setError(null);
    try { setVersions((await API.queue()).versions); } catch (err) { setError(err); setVersions([]); }
  }, []);
  React.useEffect(() => { load(); }, [load]);
  const notReviewer = error && error.status === 403;
  const all = versions || [];
  const rows = R.queueRows(all);
  const activeOf = {};
  for (const v of all) if (v.status === "active") activeOf[v.courseId] = v.version;
  const current = all.find((v) => v.courseId + "@" + v.version === selected) || null;
  const decided = all.filter((v) => ["rejected", "superseded", "retired"].includes(v.status))
    .sort((a, b) => String(b.updatedAt).localeCompare(String(a.updatedAt)));
  const rowDetail = (r) => (r.title || "") + " · " + r.orgId + " · submitted " + when(r.submittedAt) + (r.relation === "upgrade" ? " · upgrade of " + r.activeVersion : r.relation === "older" ? " · older than active " + r.activeVersion : r.activeVersion ? "" : " · new course");
  return (
    <div className="max-w-6xl mx-auto p-4">
      <header className="flex items-center justify-between">
        <h1 className="text-xl font-bold">Package review</h1>
        <div className="flex items-center gap-4">
          <span className="text-xs text-slate-500">{AUTH.currentUid()}</span>
          <a className="text-sm text-slate-500" href="author.html">Author portal</a>
          <button className="text-sm text-slate-500" onClick={load}>Reload</button>
          <button className="text-sm text-slate-500" onClick={onSignOut}>Sign out</button>
        </div>
      </header>
      {notReviewer ? (
        <div className={CARD + " p-6 mt-6 text-sm"}>This account is not a platform reviewer. Package review is limited to platform reviewers; authors submit packages from the <a className="underline" href="author.html">author portal</a>.</div>
      ) : (
        <>
          {error && <ReviewError error={error} />}
          <div className="mt-4 grid grid-cols-1 md:grid-cols-[340px_minmax(0,1fr)] gap-4">
            <div className="space-y-4">
              {versions === null ? <p className="text-sm">Loading…</p> : (
                <>
                  <Section title="Waiting for review" empty="Nothing submitted.">
                    {rows.filter((r) => r.status === "submitted").map((r) => <Row key={r.courseId + r.version} v={r} selected={selected} onSelect={setSelected} detail={rowDetail(r)} />)}
                  </Section>
                  <Section title="Approved, not yet live" empty="None.">
                    {rows.filter((r) => r.status === "approved").map((r) => <Row key={r.courseId + r.version} v={r} selected={selected} onSelect={setSelected} detail={rowDetail(r)} />)}
                  </Section>
                  <Section title="Live courses" empty="None.">
                    {all.filter((v) => v.status === "active").map((v) => <Row key={v.courseId + v.version} v={v} selected={selected} onSelect={setSelected} detail={(v.title || "") + " · " + v.orgId} />)}
                  </Section>
                  <Section title="Decided" empty="None.">
                    {decided.map((v) => <Row key={v.courseId + v.version} v={v} selected={selected} onSelect={setSelected} detail={(v.title || "") + " · " + v.orgId + " · " + when(v.updatedAt)} />)}
                  </Section>
                </>
              )}
            </div>
            <div>{current
              ? <VersionView summary={current} activeVersion={activeOf[current.courseId] || null} reviewer={AUTH.currentUid()}
                  onChanged={(updated) => { load(); if (updated) setSelected(updated.courseId + "@" + updated.version); }} />
              : <p className="text-sm text-slate-500">Select a package version.</p>}</div>
          </div>
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
  if (!uid) return <SignIn auth={AUTH} title="Package review" onSignedIn={refresh} />;
  return <ReviewPortal onSignOut={async () => { await AUTH.signOut(); refresh(); }} />;
}

ReactDOM.createRoot(document.getElementById("root")).render(<App />);
