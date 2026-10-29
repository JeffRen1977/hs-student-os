// app.js — App root + AGENT_MODULES registry.
// Navigation is driven by this registry (mirroring the backend /api/agents
// registry): adding a future agent = one new module file under js/agents/
// + one line here.

const AGENT_MODULES = {
  AP_BASE: { label: "AP Base Agent", panel: ApPanel },
  DSAT: { label: "Digital SAT", panel: DsatPanel },
  ADMISSIONS: { label: "Admissions Agent", panel: AdmissionsPanel },
};

function App() {
  // All data comes through the provider seam in data.js — nothing else
  // in the app touches the raw mock constants.
  const packs = window.HSData.getPacks();
  const sessions = window.HSData.getSessions();
  const student = window.HSData.getStudent();
  const S = useAppState({ packs: packs, sessions: sessions, events: window.HSData.getEvents() });

  const ActivePanel = AGENT_MODULES[S.activeAgent] ? AGENT_MODULES[S.activeAgent].panel : null;

  return (
    <div className="min-h-screen flex flex-col bg-[#F7F8FA] dark:bg-slate-950 transition-colors">
      <Header S={S} student={student} />

      <div className="flex-1 min-h-0 grid grid-cols-1 md:grid-cols-[240px_minmax(0,1fr)] lg:grid-cols-[260px_minmax(0,1fr)_300px] pb-[64px] md:pb-0">
        <TodayTasks S={S} packs={packs} />

        <main className={(S.mobileTab === "tasks" || S.mobileTab === "events" ? "hidden" : "block") + " md:block overflow-y-auto p-3 sm:p-4 space-y-3"}>
          {S.activeAgent === "AP_BASE" && S.subs.ap.length > 0 && ActivePanel && (
            <ApPanel S={S} />
          )}

          {S.activeAgent === "DSAT" && S.subs.dsat && S.currentSess && ActivePanel && (
            <DsatPanel session={S.currentSess} onDesmos={() => S.pushEvent("tool.desmos", "Digital SAT", "Twin", "Desmos 作图求解已演示，复合函数掌握度 +1")} />
          )}

          {S.activeAgent === "ADMISSIONS" && S.subs.admissions && S.currentSess && ActivePanel && (
            <AdmissionsPanel session={S.currentSess} onNote={(text) => S.pushEvent("narrative.gap", "Admissions", "Planner", text)} />
          )}
        </main>

        <TwinAside S={S} packs={packs} student={student} />
      </div>

      <MobileTabs S={S} />

      {S.showSubModal && <SubModal S={S} packs={packs} />}
      {S.showManifest && <ManifestModal S={S} student={student} />}
    </div>
  );
}

ReactDOM.createRoot(document.getElementById("root")).render(<App />);
