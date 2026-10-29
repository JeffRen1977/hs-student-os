// data.js — ALL mock data for the prototype + the data-provider seam.
// Components must consume data ONLY through window.HSData. Today the
// provider returns the embedded mock data synchronously; when the
// backend lands (see ../doc/API.md), only this file changes.

const AP_PACKS = {
  calc_bc: {
    id: "calc_bc",
    name: "AP Calculus BC",
    shortName: "Calc BC",
    icon: "📐",
    family: "stem",
    canvas: "calc",
    predicted: 4.5,
    target: 4.8,
    stable: false,
    schoolProgress: 74,
    cbCoverage: 58,
    currentUnit: "Unit 4: Contextual Applications of Differentiation",
    skills: [
      { name: "Socratic Math Step-by-Step", modes: ["GPA_SYNC"] },
      { name: "STEM FRQ Point-by-Point Grader", modes: ["EXAM_CRUNCH"] },
      { name: "Handwriting OCR -> LaTeX", modes: ["GPA_SYNC", "EXAM_CRUNCH"] },
    ],
    rag: ["CB Calc CED Graph", "Mr. Smith Week 12 Syllabus"],
    mcp: ["SymPy 符号验算", "Desmos", "Twin Bus"],
  },
  apush: {
    id: "apush",
    name: "AP US History",
    shortName: "APUSH",
    icon: "📜",
    family: "humanities",
    canvas: "history",
    predicted: 4.0,
    target: 4.5,
    stable: false,
    schoolProgress: 68,
    cbCoverage: 62,
    currentUnit: "Period 6 (1865–1898): Gilded Age",
    skills: [
      { name: "Historical Sourcing Socratic Guide", modes: ["GPA_SYNC"] },
      { name: "DBQ 7-Point Rubric Diff Grader", modes: ["EXAM_CRUNCH"] },
      { name: "Contextual SAT Vocab Extractor", modes: ["GPA_SYNC", "EXAM_CRUNCH"] },
    ],
    rag: ["CB APUSH 9-Period Matrix", "Primary Doc: Carnegie (1889)"],
    mcp: ["SAT Flashcard Bridge", "Chronology Validator", "Twin Bus"],
  },
  csa: {
    id: "csa",
    name: "AP Computer Science A",
    shortName: "AP CSA",
    icon: "💻",
    family: "stem",
    canvas: "code",
    predicted: 4.8,
    target: 5,
    stable: true,
    schoolProgress: 80,
    cbCoverage: 75,
    currentUnit: "Unit 7: ArrayList Algorithms",
    skills: [
      { name: "Socratic Array Tracer", modes: ["GPA_SYNC"] },
      { name: "CB Java FRQ Penalty Checker", modes: ["EXAM_CRUNCH"] },
    ],
    rag: ["CB Java Quick Reference", "4 Standard FRQ Archetypes"],
    mcp: ["Java 17 JUnit Sandbox", "Twin Bus"],
  },
  phys_c: {
    id: "phys_c",
    name: "AP Physics C: Mechanics",
    shortName: "Physics C",
    icon: "⚡",
    family: "stem",
    canvas: "physics",
    predicted: 3.9,
    target: 5,
    stable: false,
    schoolProgress: 60,
    cbCoverage: 50,
    currentUnit: "Unit 3: Work, Energy, and Power",
    skills: [
      { name: "Free-Body & Calculus Socratic Tutor", modes: ["GPA_SYNC"] },
      { name: "Differential Equation FRQ Grader", modes: ["EXAM_CRUNCH"] },
    ],
    rag: ["CB Physics C CED", "Experimental Design Rubrics"],
    mcp: ["SymPy ODE Solver", "Twin Bus"],
  },
  ap_lang: {
    id: "ap_lang",
    name: "AP English Language",
    shortName: "AP Lang",
    icon: "✒️",
    family: "humanities",
    canvas: "lang",
    predicted: 4.2,
    target: 5,
    stable: false,
    schoolProgress: 70,
    cbCoverage: 55,
    currentUnit: "Unit 4: Rhetorical Synthesis",
    skills: [
      { name: "Rhetorical Analysis Socratic Guide", modes: ["GPA_SYNC"] },
      { name: "Argument FRQ Rubric Diff Grader", modes: ["EXAM_CRUNCH"] },
      { name: "Contextual SAT Vocab Extractor", modes: ["GPA_SYNC", "EXAM_CRUNCH"] },
    ],
    rag: ["CB AP Lang CED", "Synthesis Source Packet"],
    mcp: ["SAT Flashcard Bridge", "Twin Bus"],
  },
};

const INIT_SESSIONS = [
  { id: "sess_101", num: "101", agent: "AP_BASE", courseId: "calc_bc", mode: "GPA_SYNC", title: "攻克隐函数求导与变化率", duration: "20m", tokens: "1.8k", desc: "周五测验：排查链式法则漏写 dh/dt" },
  { id: "sess_102", num: "102", agent: "AP_BASE", courseId: "calc_bc", mode: "EXAM_CRUNCH", title: "FRQ 精批：圆锥水箱推导", duration: "25m", tokens: "2.4k", desc: "按评分要点核验列式分与过程分" },
  { id: "sess_103", num: "103", agent: "AP_BASE", courseId: "calc_bc", mode: "GPA_SYNC", title: "作业：参数方程的二阶导数", duration: "15m", tokens: "0.9k", desc: "对齐 Mr. Smith Week 12 讲义" },
  { id: "sess_201", num: "201", agent: "AP_BASE", courseId: "apush", mode: "GPA_SYNC", title: "精读《财富的福音》并提炼语境词", duration: "15m", tokens: "1.2k", desc: "Period 6 阅读，触发 vocab.context" },
  { id: "sess_202", num: "202", agent: "AP_BASE", courseId: "apush", mode: "EXAM_CRUNCH", title: "DBQ 精批：镀金时代工业化", duration: "35m", tokens: "3.1k", desc: "Contextualization 按采分点改写" },
  { id: "sess_301", num: "301", agent: "AP_BASE", courseId: "csa", mode: "GPA_SYNC", title: "ArrayList 遍历：漏判边界", duration: "20m", tokens: "1.4k", desc: "校内测验：off-by-one" },
  { id: "sess_302", num: "302", agent: "AP_BASE", courseId: "csa", mode: "EXAM_CRUNCH", title: "FRQ：ArrayList 删除重复元素", duration: "30m", tokens: "1.6k", desc: "按 Java FRQ 扣分点检查" },
  { id: "sess_601", num: "601", agent: "AP_BASE", courseId: "phys_c", mode: "GPA_SYNC", title: "功率推导：漏乘速度", duration: "20m", tokens: "1.1k", desc: "Unit 3 作业，对齐能量守恒" },
  { id: "sess_602", num: "602", agent: "AP_BASE", courseId: "phys_c", mode: "EXAM_CRUNCH", title: "FRQ：变力做功积分", duration: "25m", tokens: "1.5k", desc: "实验设计与积分过程分" },
  { id: "sess_701", num: "701", agent: "AP_BASE", courseId: "ap_lang", mode: "GPA_SYNC", title: "修辞分析：演讲里的关键词", duration: "15m", tokens: "1.0k", desc: "找出被作者重定义的词" },
  { id: "sess_702", num: "702", agent: "AP_BASE", courseId: "ap_lang", mode: "EXAM_CRUNCH", title: "Argument FRQ：证据与让步", duration: "30m", tokens: "1.8k", desc: "按论点采分点改写" },
  { id: "sess_401", num: "401", agent: "DSAT", courseId: "dsat", kind: "math", mode: "ADAPTIVE", title: "Math：复合函数变式 5 题", duration: "15m", tokens: "1.1k", cross: true, desc: "由 Calc BC 的 skill.weak 触发，含 Desmos" },
  { id: "sess_402", num: "402", agent: "DSAT", courseId: "dsat", kind: "rw", mode: "ADAPTIVE", title: "Reading：双篇科学文，分清假设与结论", duration: "20m", tokens: "1.4k", desc: "错因是混淆作者假设与实验结论" },
  { id: "sess_403", num: "403", agent: "DSAT", courseId: "dsat", kind: "vocab", mode: "ADAPTIVE", title: "词汇：用 APUSH 史料做语境闪卡", duration: "10m", tokens: "0.6k", cross: true, desc: "来自 vocab.context，不是孤立词表" },
  { id: "sess_404", num: "404", agent: "DSAT", courseId: "dsat", kind: "mock", mode: "ADAPTIVE", title: "自适应模考：Module 1 → Module 2", duration: "35m", tokens: "2.2k", desc: "Module 1 正确率决定 Module 2 难度" },
  { id: "sess_501", num: "501", agent: "ADMISSIONS", courseId: "adm", kind: "interview", mode: "INTERVIEW", title: "主文书访谈：机器人视觉与社区", duration: "30m", tokens: "2.9k", desc: "追问细节。学生自己写，不代写。" },
  { id: "sess_502", num: "502", agent: "ADMISSIONS", courseId: "adm", kind: "matrix", mode: "SCHOOL_LIST", title: "重算 Reach / Match / Safety", duration: "15m", tokens: "1.0k", desc: "用最新 AP 预测分和 SAT 1510 更新名单" },
  { id: "sess_503", num: "503", agent: "ADMISSIONS", courseId: "adm", kind: "activities", mode: "ACTIVITIES", title: "活动列表：压到 150 字符", duration: "20m", tokens: "0.8k", desc: "动作动词 + 可核对的结果，学生确认事实" },
  { id: "sess_504", num: "504", agent: "ADMISSIONS", courseId: "adm", kind: "spike", mode: "INTERVIEW", title: "主线缺口：AI 伦理缺人文活动", duration: "15m", tokens: "0.7k", desc: "把缺口写成下周任务，不生成文书" },
];

const INIT_EVENTS = [
  { id: 1, type: "skill.weak", time: "Just now", from: "AP Base [calc_bc]", to: "dSAT", text: "隐函数求导漏项 -> 已向 SAT Math 注入 5 道复合函数题" },
  { id: 2, type: "calendar.pressure", time: "10m", from: "Timeline", to: "Planner", text: "周五 Calc 校内测验，自动下调本周 SAT 刷题量 30%" },
  { id: 3, type: "ap.predicted", time: "2d ago", from: "AP Base [csa]", to: "Admissions", text: "CSA 预测分 4.8 -> 强化 CMU/UCB 工程院选校匹配度" },
];

const MODE_LABEL = {
  GPA_SYNC: "日常作业",
  EXAM_CRUNCH: "大考精批",
  ADAPTIVE: "SAT 练习",
  INTERVIEW: "文书访谈",
  SCHOOL_LIST: "选校",
  ACTIVITIES: "活动列表",
};

// Student identity shown in the header / Twin summary (mock phase).
const STUDENT = { name: "Alex", grade: 11, gpa: 3.94, email: "alex@hs.edu", satCurrent: 1510, satTarget: 1550 };

// ---- Data provider: the single seam where the backend API plugs in later.
window.HSData = {
  getPacks: function () { return AP_PACKS; },
  getSessions: function () { return INIT_SESSIONS; },
  getEvents: function () { return INIT_EVENTS; },
  getModeLabel: function () { return MODE_LABEL; },
  getStudent: function () { return STUDENT; },
};
