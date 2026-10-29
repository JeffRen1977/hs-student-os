// agents/ap.js — AP Base Agent panel: runtime header, dual-track progress,
// GPA workspace (Socratic + subject canvas) and Exam workspace (FRQ rubric).

function ApPanel({ S }) {
  const pack = S.pack;
  const currentSess = S.currentSess;
  const architect = S.architect;
  return (
    <React.Fragment>
      <section className={CARD + " p-4 space-y-3"}>
        <div className="flex flex-wrap justify-between items-center gap-2">
          <div>
            <div className="text-[10px] uppercase tracking-wide text-slate-500 dark:text-slate-500">Active Runtime</div>
            <div className="text-sm font-semibold">
              AP Base Agent <span className="text-slate-300 dark:text-slate-600">/</span> <span className="text-indigo-600 dark:text-indigo-300">{pack.icon} {pack.shortName} Pack</span>
            </div>
          </div>
          <div className="flex items-center gap-3">
            <div className="text-right">
              <div className="text-[10px] text-slate-500 dark:text-slate-400">预测分</div>
              <BigScore value={pack.predicted} />
            </div>
            <ModeToggle apMode={S.apMode} setApMode={S.setApMode} />
          </div>
        </div>
        {architect ? (
          <div className="grid grid-cols-1 sm:grid-cols-3 gap-2 text-[11px] bg-slate-50 dark:bg-slate-950 p-3 rounded-xl ring-1 ring-slate-200/70 dark:ring-slate-800">
            <div>
              <div className="text-amber-600 dark:text-amber-300 font-semibold mb-1">Mounted Skills</div>
              {pack.skills.map((sk) => (
                <div key={sk.name} className={sk.modes.indexOf(S.apMode) >= 0 ? "text-amber-700 dark:text-amber-100" : "text-slate-400 dark:text-slate-600 line-through"}>{sk.name}</div>
              ))}
            </div>
            <div>
              <div className="text-sky-600 dark:text-sky-300 font-semibold mb-1">RAG Knowledge Packs</div>
              {pack.rag.map((r) => <div key={r} className="text-sky-700 dark:text-sky-100">{r}</div>)}
            </div>
            <div>
              <div className="text-emerald-600 dark:text-emerald-300 font-semibold mb-1">Connected MCP</div>
              {pack.mcp.map((m) => <div key={m} className="text-emerald-700 dark:text-emerald-100">{m}</div>)}
            </div>
          </div>
        ) : (
          <div className="text-xs text-slate-600 dark:text-slate-300">{pack.currentUnit}</div>
        )}
        {currentSess && (
          <div className="flex flex-wrap items-center justify-between gap-2 text-xs">
            <div>
              <span className="text-slate-500">当前会话 </span>
              <span className="font-semibold">{currentSess.title}</span>
              {architect && <span className="font-mono text-slate-400 dark:text-slate-500"> · {currentSess.id}</span>}
            </div>
            <div className="flex gap-2">
              <button onClick={() => S.pushEvent("vision.ocr", "AP Base [" + pack.id + "]", "Twin", "手写推导已识别为 LaTeX，等待分步验算")} className={"px-3 min-h-[36px] rounded-full ring-1 ring-slate-300 dark:ring-slate-700 text-slate-700 dark:text-slate-200 hover:bg-slate-100 dark:hover:bg-slate-800 " + BTN}>扫码上传手写推导</button>
              <button onClick={() => S.pushEvent("session.settled", "Planner", "Twin", currentSess.title + " 已结算，掌握度写回 Twin")} className={"px-3 min-h-[36px] rounded-full bg-emerald-600 hover:bg-emerald-500 text-white font-medium " + BTN}>完成并结算 Session</button>
            </div>
          </div>
        )}
      </section>

      <section className={CARD + " p-4"}>
        <div className="text-xs font-semibold mb-2.5">双轨进度 · {pack.currentUnit}</div>
        <Bar label="校内课堂进度 (GPA)" value={pack.schoolProgress} bar="bg-emerald-500" />
        <div className="h-2.5" />
        <Bar label="5月大考覆盖 (Exam)" value={pack.cbCoverage} bar="bg-rose-500" />
      </section>

      {S.apMode === "GPA_SYNC" ? (
        <GpaWorkspace pack={pack} fixed={!!S.fixedSteps[pack.id]} tier2={S.tier2} architect={architect}
          onTier2={() => S.setTier2(true)}
          onFix={() => {
            S.setFixedSteps((p) => Object.assign({}, p, { [pack.id]: true }));
            S.pushEvent("skill.weak", "AP Base [" + pack.id + "]", "Digital SAT", pack.shortName + " 订正薄弱步骤 -> 更新 Twin，并向 SAT 注入同源变式");
          }}
          onVocab={() => S.pushEvent("vocab.context", "AP Base [" + pack.id + "]", "Digital SAT", "已把史料原句与高亮词同步到 SAT 语境闪卡")}
        />
      ) : (
        <ExamWorkspace pack={pack} fixed={!!S.fixedFrq[pack.id]}
          onAdopt={() => {
            S.setFixedFrq((p) => Object.assign({}, p, { [pack.id]: true }));
            S.pushEvent("ap.predicted", "AP Base [" + pack.id + "]", "Admissions Agent", pack.shortName + " 采分点订正，预测分上调 -> 已更新 Reach 校匹配");
          }}
        />
      )}

      <form onSubmit={(e) => { e.preventDefault(); if (!S.draft.trim()) return; S.pushEvent("student.reply", "Alex", "AP Base", "学生用自己的话作答：" + S.draft.trim()); S.setDraft(""); }} className="flex gap-2">
        <input value={S.draft} onChange={(e) => S.setDraft(e.target.value)} placeholder="用你自己的话回答追问..." className="flex-1 min-h-[44px] bg-white dark:bg-slate-900 ring-1 ring-slate-200 dark:ring-slate-800 rounded-full px-4 py-2 text-sm outline-none focus:ring-2 focus:ring-indigo-500 shadow-sm transition" />
        <button className={"px-5 min-h-[44px] rounded-full bg-indigo-600 hover:bg-indigo-500 text-white text-sm font-semibold shadow-sm " + BTN}>发送</button>
      </form>
    </React.Fragment>
  );
}

function GpaWorkspace({ pack, fixed, tier2, architect, onTier2, onFix, onVocab }) {
  const prompt = gpaPrompt(pack, fixed);
  return (
    <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
      <section className={CARD + " p-4 text-xs space-y-2.5"}>
        <div className="font-semibold text-emerald-600 dark:text-emerald-300">苏格拉底引导 · 不直接给答案</div>
        <p className="text-slate-600 dark:text-slate-300 leading-relaxed">{prompt}</p>
        {!tier2 ? (
          <button onClick={onTier2} className={"px-3 min-h-[36px] rounded-full ring-1 ring-amber-300 dark:ring-amber-500/40 text-amber-700 dark:text-amber-200 hover:bg-amber-50 dark:hover:bg-amber-500/10 " + BTN}>展开 Tier 2 提示</button>
        ) : (
          <p className="text-amber-800 dark:text-amber-100/90 leading-relaxed">{tier2Text(pack)}</p>
        )}
      </section>
      <section className={CARD + " p-4 text-xs space-y-2.5"}>
        <div className="font-semibold text-sky-600 dark:text-sky-300">{canvasTitle(pack)}</div>
        <CanvasBody pack={pack} fixed={fixed} architect={architect} onFix={onFix} onVocab={onVocab} />
      </section>
    </div>
  );
}

function CanvasBody({ pack, fixed, onFix, onVocab }) {
  if (pack.canvas === "history" || pack.canvas === "lang") {
    return (
      <div className="space-y-2">
        <p className="text-slate-600 dark:text-slate-300 leading-relaxed">
          “This, then, is held to be the duty of the man of Wealth: first, to set an example of modest, <span className="bg-amber-200/60 dark:bg-amber-400/20 text-amber-800 dark:text-amber-200 px-1 rounded">unostentatious</span> living...”
        </p>
        <div className="text-[10px] text-slate-400 dark:text-slate-500">Andrew Carnegie, The Gospel of Wealth (1889)</div>
        <button onClick={onVocab} className={"w-full min-h-[40px] py-1.5 rounded-full bg-sky-600 hover:bg-sky-500 text-white font-semibold " + BTN}>提取高亮词和原句，同步到 Digital SAT</button>
      </div>
    );
  }
  if (pack.canvas === "code") {
    return (
      <div className="space-y-2 font-mono">
        <div className="p-2.5 rounded-xl bg-slate-50 dark:bg-slate-950 ring-1 ring-slate-200/60 dark:ring-slate-800">for (int i = 0; i &lt;= list.size(); i++)</div>
        <div className={"p-2.5 rounded-xl ring-1 " + (fixed ? "ring-emerald-300 dark:ring-emerald-500 bg-emerald-50 dark:bg-transparent text-emerald-700 dark:text-emerald-200" : "ring-rose-300 dark:ring-rose-500 bg-rose-50 dark:bg-transparent text-rose-700 dark:text-rose-200")}>
          {fixed ? "i < list.size()  · 边界已改" : "i <= list.size()  · 会越界"}
        </div>
        <button onClick={onFix} className={"w-full min-h-[40px] py-1.5 rounded-full bg-indigo-600 hover:bg-indigo-500 text-white font-semibold font-sans " + BTN}>{fixed ? "已修正并写回 Twin" : "修正边界并触发跨域事件"}</button>
      </div>
    );
  }
  if (pack.canvas === "physics") {
    return (
      <div className="space-y-2 font-mono">
        <div className="p-2.5 rounded-xl bg-slate-50 dark:bg-slate-950 ring-1 ring-slate-200/60 dark:ring-slate-800">W = ∫ F · dr ✓</div>
        <div className={"p-2.5 rounded-xl ring-1 " + (fixed ? "ring-emerald-300 dark:ring-emerald-500 bg-emerald-50 dark:bg-transparent text-emerald-700 dark:text-emerald-200" : "ring-rose-300 dark:ring-rose-500 bg-rose-50 dark:bg-transparent text-rose-700 dark:text-rose-200")}>
          {fixed ? "P = dW/dt = F · v ✓" : "P = F  · 漏了速度"}
        </div>
        <button onClick={onFix} className={"w-full min-h-[40px] py-1.5 rounded-full bg-indigo-600 hover:bg-indigo-500 text-white font-semibold font-sans " + BTN}>{fixed ? "已修正并写回 Twin" : "修正此步并触发跨域事件"}</button>
      </div>
    );
  }
  return (
    <div className="space-y-2 font-mono">
      <div className="p-2.5 rounded-xl bg-slate-50 dark:bg-slate-950 ring-1 ring-slate-200/60 dark:ring-slate-800">Step 1: r = 1/2 h ✓</div>
      <div className="p-2.5 rounded-xl bg-slate-50 dark:bg-slate-950 ring-1 ring-slate-200/60 dark:ring-slate-800">Step 2: V = (π/12) h³ ✓</div>
      <div className={"p-2.5 rounded-xl ring-1 " + (fixed ? "ring-emerald-300 dark:ring-emerald-500 bg-emerald-50 dark:bg-emerald-950/30 text-emerald-700 dark:text-emerald-200" : "ring-rose-300 dark:ring-rose-500 bg-rose-50 dark:bg-rose-950/30 text-rose-700 dark:text-rose-200")}>
        {fixed ? "Step 3: dV/dt = (π/4) h² · dh/dt ✓" : "Step 3: dV/dt = (π/4) h²  · 漏乘 dh/dt"}
      </div>
      <button onClick={onFix} className={"w-full min-h-[40px] py-1.5 rounded-full bg-indigo-600 hover:bg-indigo-500 text-white font-semibold font-sans " + BTN}>{fixed ? "已修正并写回 Twin" : "修正 Step 3 并同步至 Twin"}</button>
    </div>
  );
}

function ExamWorkspace({ pack, fixed, onAdopt }) {
  const rubric = rubricFor(pack, fixed);
  return (
    <div className="grid grid-cols-1 lg:grid-cols-12 gap-3">
      <section className={CARD + " lg:col-span-7 ring-rose-200 dark:ring-rose-500/40 p-4 text-xs space-y-2.5"}>
        <div className="font-semibold text-rose-600 dark:text-rose-300">采分点精批</div>
        <p className="text-slate-500 dark:text-slate-400">{pack.shortName} · {pack.currentUnit}</p>
        <div className={"p-3 rounded-xl ring-1 " + (fixed ? "bg-emerald-50 dark:bg-emerald-950/30 ring-emerald-200 dark:ring-emerald-500/40" : "bg-rose-50 dark:bg-rose-950/40 ring-rose-200 dark:ring-rose-500/40")}>
          <div className="font-semibold mb-1">{fixed ? "这一分已经拿到" : "这一分还没拿到"}</div>
          <p className="text-slate-700 dark:text-slate-200 leading-relaxed">{fixed ? rubric.fixedLine : rubric.missLine}</p>
        </div>
        {!fixed && (
          <div className="p-3 rounded-xl bg-amber-50 dark:bg-amber-500/10 ring-1 ring-amber-200 dark:ring-amber-500/30 text-amber-900 dark:text-amber-50 leading-relaxed">
            {rubric.advice}
          </div>
        )}
        {!fixed && (
          <button onClick={onAdopt} className={"px-4 min-h-[40px] py-1.5 rounded-full bg-emerald-600 hover:bg-emerald-500 text-white font-semibold " + BTN}>采纳改写并重算 AP 预测分</button>
        )}
        {fixed && <div className="text-emerald-600 dark:text-emerald-300">预测分已写回 Twin，选校矩阵会跟着更新。</div>}
      </section>
      <section className={CARD + " lg:col-span-5 p-4 text-xs space-y-2"}>
        <div className="font-semibold text-slate-800 dark:text-slate-200">Rubric 核验</div>
        {rubric.rows.map((row) => (
          <div key={row.name} className="flex justify-between border-b border-slate-100 dark:border-slate-800 py-1.5">
            <span>{row.name}</span>
            <span className={row.got === row.max ? "text-emerald-600 dark:text-emerald-400 font-mono font-semibold" : "text-rose-500 dark:text-rose-400 font-mono font-semibold"}>{row.got}/{row.max}</span>
          </div>
        ))}
      </section>
    </div>
  );
}

function gpaPrompt(pack, fixed) {
  if (pack.canvas === "calc") {
    return fixed
      ? "Step 3 已经补上 dh/dt。用一句话说明：为什么 h 必须写成 h(t)，而不是常数？"
      : "你在右侧 Step 3 写出 dV/dt = (π/4) h²。想一想：h 是常数，还是时间 t 的函数 h(t)？";
  }
  if (pack.canvas === "history") return "卡内基说富人有责任做示范。他在为哪一种行为辩护，又把谁排除在外？";
  if (pack.canvas === "code") return "循环条件写成 i <= list.size()。最后一次循环时，i 指向哪里？";
  if (pack.canvas === "physics") return "功率不是力本身。力已经在做功，还要再乘上哪个随时间变化的量？";
  return "这篇演讲的中心论点是什么？找出一个作者用来压住反方的词。";
}

function tier2Text(pack) {
  if (pack.canvas === "calc") return "提示：体积是高度的函数，高度又是时间的函数。外层对 h 求导之后，还要乘 dh/dt。";
  if (pack.canvas === "history") return "提示：先标出他在替谁说话，再找一个被他称为“不负责任”的群体。";
  if (pack.canvas === "code") return "提示：合法下标是 0 到 size()-1。等于 size() 时 get 会抛异常。";
  if (pack.canvas === "physics") return "提示：P = dW/dt。功对时间求导之后，力还要点乘速度。";
  return "提示：先用自己的话复述论点，再指出一个被作者重定义的词。";
}

function canvasTitle(pack) {
  if (pack.canvas === "calc") return "STEM 推导画布";
  if (pack.canvas === "history" || pack.canvas === "lang") return "史料原文";
  if (pack.canvas === "code") return "代码追踪";
  return "受力与能量";
}

function rubricFor(pack, fixed) {
  if (pack.family === "humanities") {
    return {
      missLine: "文章直接从卡内基的引言开始，没有把镀金时代的劳资冲突放进上下文。",
      fixedLine: "1877 年铁路罢工之后，卡内基把私人财富写成公共责任，这是在回应全国对工业巨头的不信任。",
      advice: "补上一个早于文献的具体背景（年代 + 冲突），这一句就可以拿到 Contextualization 的 1 分。",
      rows: [
        { name: "Thesis", got: 1, max: 1 },
        { name: "Contextualization", got: fixed ? 1 : 0, max: 1 },
        { name: "Evidence", got: 2, max: 2 },
      ],
    };
  }
  return {
    missLine: "dV/dt = (π/4) h²。体积对高度求导之后，没有乘上 dh/dt。",
    fixedLine: "dV/dt = (π/4) h² · dh/dt。链式法则过程分可以拿到。",
    advice: "把高度写成 h(t)，并乘上内层导数。这一行就是过程分。",
    rows: [
      { name: "列式", got: 1, max: 1 },
      { name: "链式法则", got: fixed ? 1 : 0, max: 1 },
      { name: "单位与结论", got: 1, max: 1 },
    ],
  };
}
