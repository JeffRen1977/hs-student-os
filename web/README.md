# High School Student OS — 前端（模块化版）

`../index.html` 是单文件版原型；本目录是同一界面、同一数据、同一交互的**模块化重构**，方便后续按 Agent 逐个扩展与接入后端。

## 预览

模块用多个 `<script type="text/babel" src="...">` 加载，必须经 HTTP 打开（`file://` 下浏览器不允许读取外部 babel 脚本）。任选一种静态服务器：

```bash
npx serve web            # 在 hs-student-os/ 目录下执行
# 或
python3 -m http.server 8000 -d web
```

然后打开 http://localhost:8000（serve 默认端口以其输出为准）。

## 运行模式

| URL | 数据来源 | 说明 |
|---|---|---|
| `/` | 后端 API（`window.HS_API_BASE_URL`，默认 `http://localhost:8787`） | 先登录（`js/auth.js`）：配置 `window.HS_FIREBASE_CONFIG` 时用 Firebase Auth；本机（页面与 API 都在 localhost）未配置时提供“本地开发登录”，只能登录合成学生，令牌为 Auth 模拟器格式，部署环境的后端会拒绝。**API 失败不会改用演示数据。** |
| `/?demo=true` | `fixtures/demo.json`（合成数据，API v0.3 形状） | 顶部有 DEMO 横幅；所有操作只在本机模拟，不保存、不评估。 |

## 模块地图

| 文件 | 职责 |
|---|---|
| `index.html` | 薄壳：CDN（Tailwind / React / ReactDOM / Babel）、root 容器、按依赖顺序加载模块。 |
| `js/theme.js` | 普通脚本：Tailwind 配置、设计令牌、共享类名 helper（`CARD`、`BTN`、`modeClass`）。 |
| `js/data-provider.js` | 普通脚本（无 JSX），浏览器中为 `window.HSProvider`，Node 中可 `require`。异步数据提供层：API/演示两种 provider、请求状态、错误类型、Idempotency-Key、事件去重、本地草稿、Run 状态展示。 |
| `fixtures/demo.json` | 演示数据。由 `server/tests/contract/test_web_demo_fixtures.py` 按后端 Pydantic schema 校验。 |
| `js/data.js` | 仅展示元数据（图标、简称、模式标签）。`window.HSData.getPackMeta / getModeLabel`。不含任何学生数据或分数。 |
| `js/store.js` | `useAppState(data)`：全部 React state。Task、Session、Run 分开保存；服务端事件日志（去重）与本地演示操作（`demoNotes`）分开。 |
| `js/ui.js` | 共享 UI：`Card`、`Badge`、`Modal`、`PredictionBadge`（固定显示“暂无预测”）、`RunStatusBadge`、`DemoBanner`、`StatusScreen`、`ModeToggle`。 |
| `js/agents/ap.js` | AP 课程面板（演示模式）：Task / Session / Run 状态卡、GPA 工作区、考试工作区、作答输入（本地草稿）。 |
| `js/agents/course_session.js` | API 模式的课程 agent 学习流程：开始练习、对话（提示）、提交解答、全部 Run 状态、评估结果（含“证据不足不计入掌握度”）、完成 / 放弃 / 取消、网络错误按同一 Idempotency-Key 重试、刷新后从服务端恢复。 |
| `js/auth.js` | 普通脚本（`window.HSAuth`）：ID token 来源（Firebase / 本地模拟器开发登录 / 未配置）。 |
| `js/agents/dsat.js`、`js/agents/admissions.js` | 规划中功能的预览面板，仅在演示模式出现。 |
| `js/features.js` | `Header`、`TodayTasks`、`TwinSummary`（预测与掌握度）、`EventFeed`（服务端事件）、`CatalogModal`（课程目录）、`ManifestModal`、`MobileTabs`。 |
| `js/app.js` | 选择 provider → `bootstrap()` → 根据请求状态渲染 `StatusScreen` 或 `Workspace`。`AGENT_MODULES` 注册表。 |
| `tests/` | `node --test web/tests/`（无需 npm install）。 |

## 数据接缝

### 旧接口（已替换）

原型的 `window.HSData` 同步返回内嵌 mock：`getPacks()`（含 `predicted/target` 预测分）、`getSessions()`（Task 与 Session 混为一条记录）、`getEvents()`（客户端拼出的事件，`from/to/text`）、`getModeLabel()`、`getStudent()`（以 email 为标识，含 GPA/SAT 当前分）。`store.js` 的 `pushEvent` 在浏览器内直接生成“领域事件”，`scoreLabel` 在订正后把预测分 +0.3。这些都违反 API v0.3，已移除。

### 新接口（`HSProvider`）

```js
provider.fetchTwin()                 // GET /api/twin
provider.fetchEntitlements()         // GET /api/me/entitlements
provider.fetchPacks()                // GET /api/packs
provider.fetchCatalog()              // GET /api/courses/catalog
provider.fetchTasks({date, cursor})  // GET /api/tasks
provider.fetchSessions({taskId})     // GET /api/sessions
provider.fetchSession(sessionId)     // GET /api/sessions/{id}
provider.fetchRun(runId)             // GET /api/runs/{id}
provider.fetchEvents(afterSequence)  // GET /api/events?after=
provider.fetchMessages / fetchSubmissions / fetchAssessments / fetchAssessment / fetchMastery
provider.enrollCourse / unenrollCourse / createSession / sendMessage / submitAnswer
provider.completeSession / abandonSession / cancelRun   // POST + Idempotency-Key
HSProvider.createEventSubscription(provider, {after, onEvents, onExpired})
                                     // SSE（fetch streaming + Bearer，Last-Event-ID 重连），失败后轮询
HSProvider.bootstrap(provider)       // 启动顺序（API.md §5）
```

- 每个请求的状态为 `idle / loading / success / error`；`deriveScreen()` 决定显示加载、未连接、需要登录、错误或工作台。
- 错误为 `ApiError {code, status, retryable, requestId}`，服务端错误信封原样保留。
- 命令请求用 `createActionKeys().keyFor(actionId)`：同一操作重试复用同一个 Idempotency-Key。
- 事件经 `mergeEvents()` 按 eventId 与 sequence 去重并排序，记录最后应用的 sequence。
- 草稿只存本机（`createDraftStore`），界面明确显示“尚未发送”。

API 模式下写命令已接入（M2 Step 20）；演示模式下这些按钮仍只写本地演示记录。本地联调：`make server-memory`（或 `make server` + 模拟器）与 `make web`，打开 `http://localhost:8000/`。`HSOS_LLM_PROVIDER=mock` 时 agent 回复是标注的合成回复，不会产生评估，因此无法完成练习；真实批改需要配置模型提供方（`HSOS_LLM_PROVIDER=anthropic` 或 `openai`）及对应 API key。首版只支持文本作答，没有上传入口。
