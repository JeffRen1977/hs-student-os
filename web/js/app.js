// app.js — App root: picks the data provider, runs the startup sequence with explicit
// loading / error / success states, and renders the workspace only with real (or
// explicitly requested demo) data. AGENT_MODULES maps agentId → panel module.

const AGENT_MODULES = {
  AP_BASE: { label: "AP Base Agent", panel: ApPanel },
  DSAT: { label: "Digital SAT", panel: DsatPanel },
  ADMISSIONS: { label: "Admissions Agent", panel: AdmissionsPanel },
};

const PROVIDER = HSProvider.createProvider({
  search: window.location.search,
  baseUrl: window.HS_API_BASE_URL || "http://localhost:8787",
  // Firebase Auth is wired in M1 Step 8. Until then there is no ID token, so normal
  // mode stops at the "not signed in / not connected" screen.
  getIdToken: () => Promise.resolve(null),
  loadDemoFixtures: () =>
    fetch("fixtures/demo.json").then((r) => {
      if (!r.ok) throw new Error("demo fixtures unavailable");
      return r.json();
    }),
});

function App() {
  const [boot, setBoot] = React.useState(HSProvider.idle());

  const load = React.useCallback(() => {
    setBoot((prev) => HSProvider.loading(prev));
    HSProvider.bootstrap(PROVIDER).then(
      (data) => setBoot(HSProvider.success(data)),
      (error) => setBoot((prev) => HSProvider.failure(error, prev))
    );
  }, []);

  React.useEffect(load, [load]);

  const screen = HSProvider.deriveScreen(boot);
  if (screen !== "ready") return <StatusScreen screen={screen} error={boot.error} onRetry={load} />;
  return <Workspace data={boot.data} />;
}

function Workspace({ data }) {
  const S = useAppState(data);

  return (
    <div className="min-h-screen flex flex-col bg-[#F7F8FA] dark:bg-slate-950 transition-colors">
      {S.demo && <DemoBanner />}
      <Header S={S} />

      <div className="flex-1 min-h-0 grid grid-cols-1 md:grid-cols-[240px_minmax(0,1fr)] lg:grid-cols-[260px_minmax(0,1fr)_300px] pb-[64px] md:pb-0">
        <TodayTasks S={S} />

        <main className={(S.mobileTab === "tasks" || S.mobileTab === "events" ? "hidden" : "block") + " md:block overflow-y-auto p-3 sm:p-4 space-y-3"}>
          {S.activeAgent === "AP_BASE" && S.pack && <ApPanel S={S} />}
          {S.activeAgent === "AP_BASE" && !S.pack && (
            <section className={CARD + " p-4 text-xs text-slate-500"}>还没有注册课程。打开课程目录添加一门已开放的课程。</section>
          )}

          {S.activeAgent === "DSAT" && S.currentPreview && (
            <DsatPanel preview={S.currentPreview} onDesmos={() => S.noteDemo("tool.desmos", "演示：Desmos 作图（不更新掌握度）")} />
          )}

          {S.activeAgent === "ADMISSIONS" && S.currentPreview && (
            <AdmissionsPanel preview={S.currentPreview} onNote={(text) => S.noteDemo("demo.note", text)} />
          )}
        </main>

        <TwinAside S={S} />
      </div>

      <MobileTabs S={S} />

      {S.showCatalog && <CatalogModal S={S} />}
      {S.showManifest && <ManifestModal S={S} />}
    </div>
  );
}

ReactDOM.createRoot(document.getElementById("root")).render(<App />);
