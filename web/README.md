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

## 模块地图

| 文件 | 职责 |
|---|---|
| `index.html` | 薄壳：CDN（Tailwind / React / ReactDOM / Babel）、root 容器、按依赖顺序加载模块。无业务逻辑。 |
| `js/theme.js` | 普通脚本（非 Babel）：Tailwind 配置（darkMode: 'class'、Inter）+ 设计令牌 + 共享类名 helper（`CARD`、`BTN`、`modeClass`）。须紧跟 Tailwind CDN 加载。 |
| `js/data.js` | 全部 mock 数据（AP_PACKS、INIT_SESSIONS、INIT_EVENTS、MODE_LABEL、STUDENT）+ 数据提供层 `window.HSData`（getPacks / getSessions / getEvents / getModeLabel / getStudent）。组件只能经此接口取数据。 |
| `js/store.js` | 应用状态与动作：`useAppState()` 独占全部 React state（视图 / Agent / 课程 / 模式 / 会话 / 订阅 / 事件流 / fixed 标记 / 草稿 / 深色 / 移动端 Tab）与动作（pushEvent、selectCourse、selectAgent、openSession、toggleAp、scoreLabel、goMobile、toggleDark）及派生数据（任务分组、mountedCount、pack、currentSess）。 |
| `js/ui.js` | 共享 UI 原语：`Card`、`Badge`、`Bar`（进度条）、`Modal`、`BigScore`（预测分大数字）、`ModeToggle`（GPA/冲刺切换）。 |
| `js/agents/ap.js` | AP Base Agent 面板：运行时头部（Skills/RAG/MCP 挂载透视）、双轨进度、GPA 工作区（苏格拉底 + 四种学科画布）、考试工作区（采分点精批 + Rubric 核验）、作答输入框；含 gpaPrompt / tier2Text / canvasTitle / rubricFor 内容函数。 |
| `js/agents/dsat.js` | Digital SAT 面板：math / rw / vocab / mock 四种任务形态 + kindTitle。 |
| `js/agents/admissions.js` | Admissions 面板：interview / matrix（Reach·Match·Safety）/ activities（150 字符）/ spike。 |
| `js/features.js` | 跨 Agent 功能：`Header`（含视图切换、深色开关）、`TodayTasks`（按 Agent 分组的任务列表 + TaskRow）、`TwinSummary`（预测分总览 + Planner ROI）、`EventFeed`（跨域事件流 + plainEvent）、`TwinAside`、`MobileTabs`（移动端底部 Tab）、`SubModal`（订阅与课程包热插拔）、`ManifestModal`（Twin Manifest 透视）。 |
| `js/app.js` | App 根组件 + `AGENT_MODULES` 注册表（agentId → 面板模块）。新增 Agent = 在 `js/agents/` 加一个模块文件 + 在注册表加一行，与后端 `/api/agents` 注册表一一对应。 |

数据流：`data.js (HSData)` → `app.js` 取数 → `store.js (useAppState)` 管状态 → 各面板/功能组件纯展示 + 回调。

## 接后端的唯一接缝

目前**没有任何 fetch / API 调用**，数据全部来自 `data.js` 的同步 mock。按 `../doc/API.md` 接后端时，只改 `data.js` 一个文件：把 `HSData` 的实现换成（或包装为）对 `GET /api/twin`、`/api/packs`、`/api/tasks`、`/api/twin/events` 的请求，并把 `store.js` 里 `pushEvent` 等动作改为同时上报 `POST /api/twin/events` / `session start` / `settle`——组件与其它模块零改动。
