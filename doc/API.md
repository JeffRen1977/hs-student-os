# High School Student OS — 前后端接口定义（v0.1，已确认）

范围：Phase 1。前端 `index.html` 与后端 `hs-study-agent` 之间只走这份契约。
后端已确认：Node ≥18 单文件、内置 `http`、零框架依赖。存储首版用本地 JSON 文件实现 Twin；换 Firestore 时只换存储层，接口不变。

## 0. 通用约定

- Base URL（本地开发）：`http://localhost:8787`
- 身份：以 ai-college-advisor 的 JWT 为准。本地开发阶段可用请求头 `X-User-Email` 代替；`email` 是 Twin 的连接键（对应 `userProfiles/{email}`）。
- 请求/响应均为 JSON，UTF-8。时间用 ISO 8601。
- 错误格式统一：

```json
{ "error": { "code": "COURSE_NOT_SUBSCRIBED", "message": "Course is not subscribed." } }
```

- 常用状态码：200 成功；400 参数错误；401 未登录；403 未订阅/无权限；404 资源不存在；409 状态冲突（如重复结算）。

## 1. 数据模型

### 1.1 Twin（学术数字孪生，唯一学生记录）

```json
{
  "email": "alex@hs.edu",
  "profile": {
    "name": "Alex", "grade": 11, "school": "…", "gpa": 3.94,
    "targetMajor": "CS", "targetSchools": ["CMU", "UCSD", "Purdue"]
  },
  "goals": {
    "sat": { "target": 1550, "testDates": ["2027-03-13"] },
    "apTargets": { "calc_bc": 5, "apush": 5 }
  },
  "subscriptions": { "dsat": true, "admissions": true, "apCourses": ["calc_bc", "apush", "csa"] },
  "sat": { "current": 1510, "trajectory": [ { "date": "2026-09-05", "total": 1450 }, { "date": "2026-10-03", "total": 1510 } ] },
  "apState": {
    "calc_bc": {
      "currentMode": "GPA_SYNC",
      "predicted": 4.5, "target": 4.8,
      "schoolProgress": 74, "cbCoverage": 58,
      "currentUnit": "Unit 4: Contextual Applications of Differentiation",
      "weakSkills": ["implicit-differentiation", "related-rates"]
    }
  },
  "mastery": { "sat-math.composite-functions": 0.62 },
  "artifacts": { "essayOutlines": [], "activityList": [], "schoolMatrixVersion": 3 }
}
```

说明：`apState` 只含已订阅科目；字段与前端 `AP_PACKS` 的展示字段对应，但**学科静态定义（名称、技能、RAG、MCP）不在 Twin 里**，在学科包 manifest 里（见 1.2）。

### 1.2 SubjectPack（学科包 manifest，静态定义）

```json
{
  "courseId": "calc_bc",
  "name": "AP Calculus BC", "shortName": "Calc BC", "icon": "📐",
  "family": "stem", "canvas": "calc",
  "skills": [
    { "id": "skill.tutor.socratic_step", "modes": ["GPA_SYNC"] },
    { "id": "skill.frq.stem_derivation_grader", "modes": ["EXAM_CRUNCH"] },
    { "id": "skill.vision.ocr_latex", "modes": ["GPA_SYNC", "EXAM_CRUNCH"] }
  ],
  "ragNamespaces": ["ced_calc_bc"],
  "mcpServers": ["sympy", "desmos", "twin-bus"]
}
```

首批只注册五门：`calc_bc`、`phys_c`、`csa`、`apush`、`ap_lang`。未注册的 `courseId` 一律 404。

### 1.3 Task / Session

Planner 产出的任务（Task）与打开后的会话（Session）是同一条记录的两个状态：

```json
{
  "taskId": "task_20261027_calc_u4_frq",
  "agent": "AP_BASE",
  "courseId": "calc_bc",
  "taskType": "FRQ_PRACTICE",
  "mode": "EXAM_CRUNCH",
  "title": "FRQ 精批：圆锥水箱推导",
  "durationMin": 25,
  "desc": "按评分要点核验列式分与过程分",
  "status": "PLANNED"
}
```

`agent` 取值：`AP_BASE` | `DSAT` | `ADMISSIONS`。`status`：`PLANNED` → `ACTIVE` → `SETTLED`。

### 1.4 TwinEvent（跨域事件，总线唯一交换格式）

```json
{
  "id": "evt_…", "type": "skill.weak", "ts": "2026-10-27T22:00:00-07:00",
  "from": "AP_BASE:calc_bc", "to": "DSAT",
  "payload": { "skill": "implicit-differentiation", "satTags": ["composite-functions"] },
  "text": "隐函数求导漏项 -> 已向 SAT Math 注入 5 道复合函数题"
}
```

事件类型（与方案文档第 4 节一致）：`skill.weak`、`course.rigor`、`ap.predicted`、`sat.trajectory`、`vocab.context`、`calendar.pressure`、`narrative.gap`，外加会话类 `session.started`、`session.settled`、`student.reply`、`vision.ocr`、`tool.desmos`。

## 2. 接口

### 2.1 读 Twin

`GET /api/twin` → 200 返回 1.1 的 Twin 全量（前端启动时拉取，渲染预测分、订阅、轨迹）。

### 2.2 更新 Twin（受控字段）

`PATCH /api/twin` — 只允许改 `profile`、`goals`、`subscriptions` 三个子树的字段；`mastery`、`apState.predicted` 等只能由结算接口写，前端直改返回 400。

### 2.3 学科包注册表

`GET /api/packs` → 返回全部已注册 manifest（前端订阅弹窗用）。
`GET /api/packs/{courseId}` → 单个 manifest；未注册 404。

### 2.4 今日任务（Planner）

`GET /api/tasks?date=2026-10-27` →

```json
{ "date": "2026-10-27", "tasks": [ /* 1.3 Task 数组，已按 Planner 权重排序 */ ] }
```

Planner 规则（方案文档第 3 节）：先算各目标差距，按紧急程度与录取杠杆加权，装进当周可用小时；`calendar.pressure` 事件可下调某类任务量。Phase 1 可先用规则实现，不接模型。

### 2.5 打开 AP Session（核心入口，与方案文档一致）

`POST /api/ap/session/start`

```json
// 请求
{ "taskId": "task_20261027_calc_u4_frq", "courseId": "calc_bc", "taskType": "FRQ_PRACTICE" }
// 200 响应
{
  "sessionId": "sess_…",
  "taskId": "task_20261027_calc_u4_frq",
  "mode": "EXAM_CRUNCH",
  "activeSkills": ["skill.frq.stem_derivation_grader"],
  "ragNamespaces": ["ced_calc_bc", "user_alex@hs.edu_calc_bc"],
  "mcpTools": ["sympy", "desmos", "twin-bus"],
  "studentMasteryContext": ["implicit-differentiation", "related-rates"]
}
```

- 未订阅该 `courseId` → 403 `COURSE_NOT_SUBSCRIBED`。
- `taskId` 不存在 → 404。成功后任务状态置 `ACTIVE`，并发 `session.started` 事件。
- DSAT / Admissions 的任务打开走同一入口的泛化形式：`POST /api/session/start`，请求体换成 `{ "taskId": "…" }`，响应同构（无学科包时 `activeSkills` 为该 Agent 的内置技能）。

### 2.6 结算 Session（底座 commit hook，唯一写回路径）

`POST /api/session/{sessionId}/settle`

```json
// 请求：前端只报结果，不直接改 Twin
{ "outcome": { "fixedStep": "chain-rule", "scoreDelta": 0.3 } }
// 200 响应：后端算完掌握度增量、更新预测分、发出跨域事件后返回
{
  "taskId": "task_20261027_calc_u4_frq", "status": "SETTLED",
  "masteryDelta": { "implicit-differentiation": 0.12 },
  "apPredicted": 4.8,
  "emittedEvents": ["ap.predicted"]
}
```

重复结算 → 409。科目包不得有私有写回路径，一律走这里。

### 2.7 事件总线

`POST /api/twin/events` — 写入一条 1.4 事件（学生作答、OCR、工具调用等前端动作都走这里）。
`GET /api/twin/events?limit=50` — 倒序拉取（前端右侧事件流用；后续可升级为 SSE 推送，接口语义不变）。

### 2.8 给 Admissions 复用的上下文（ai-college-advisor 侧）

`GET /api/agent/context` → 返回画像摘要：Twin 的 profile + AP 预测分 + SAT 轨迹 + 文书/roadmap 摘要，供 college advisor 现有页面与后续动态选校矩阵消费。SAT 练习从 college 侧进入时用共享密钥断言身份 + 深链（方案文档 Phase 1 切片），不在本文件展开。

## 3. 前端接入约定

1. 启动顺序：`GET /api/twin` → `GET /api/packs` → `GET /api/tasks` → 渲染；事件流 `GET /api/twin/events`。
2. 点任务：AP 走 2.5，其余走 `POST /api/session/start`；工作区内的订正/采纳/结算走 2.6 与 2.7。
3. **回退**：任一启动请求失败（后端未启动），前端自动切回内置 mock 数据并显示「离线演示模式」小标记，交互行为不变。
4. 前端不得本地计算预测分/掌握度后直接展示为「真值」——只展示后端返回值；mock 模式除外。

## 4. Phase 1 不做

- 支付与订阅开通流程（订阅先由后台数据给定）、家长周报、模拟招生委员会、Counselor 后台。
- SSE/WebSocket 实时推送（先轮询/拉取）、多学生多租户隔离（先单用户 email 键）。
- 文书正文生成（红线：不代写）、College Board 真题内容（红线）。

---

已确认（2026-10-28，与 `BACKEND.md` 第 11 节一致）：
1. 本地开发用 `X-User-Email` 头代替 JWT。
2. Twin 首版存储用本地 JSON 文件。
3. DSAT / Admissions 打开任务复用 `POST /api/session/start`。
