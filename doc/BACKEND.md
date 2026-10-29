# High School Student OS — 后端设计（v0.2，已确认）

配套文档：`HIGH_SCHOOL_STUDENT_OS.md`（产品与架构方案）、`API.md`（接口契约，本文不重复端点细节，只讲实现设计）。

## 1. 总体形态

一个服务 `hs-study-agent`，单进程、模块化单体。Phase 1 不拆微服务：Twin、Planner、Session 运行时、事件总线都在一个进程里，模块间只通过明确接口调用，为以后拆分留边界。

```
                 ┌──────────────── hs-study-agent ────────────────┐
  index.html ───▶│ API 层 (REST, 见 API.md)                        │
                 │   │            │              │                  │
                 │ TwinStore   Planner    SessionRuntime           │
                 │   │            │        │        │              │
                 │   └───── EventBus（进程内 + 落盘）────┘          │
                 │                  │                             │
                 │        SubjectPackRegistry   SkillExecutor     │
                 │                  │              │              │
                 │            packs/*.json     LLM 网关（可替换）    │
                 └──────────────────│─────────────────────────────┘
                          data/ (JSON 存储，可换 Firestore)
```

技术选型：
- **Node.js（≥18）单文件起步**：`server.js` 用内置 `http` 实现路由，零框架依赖，Mac 上 `node server.js` 直接跑。理由：与前端同语言、与 ai-college-advisor 的 JWT/JS 生态一致、演示与联调成本最低。接口稳定后如需换 Express/Fastify，只换 API 层。
- **存储分两层**：`TwinStore` 接口隔离读写；首版实现是本地 JSON 文件（见第 3 节），第二版实现换 Firestore（`userProfiles/{email}`），Planner/Session 代码零改动。
- **LLM 网关**：所有模型调用走一个 `LLMGateway` 接口（`chat({system, messages, schema}) → JSON`），实现可换（Claude / OpenAI / 本地）。Skill 不直调厂商 SDK。

## 2. 模块设计

### 2.1 TwinStore（唯一真源）

- 职责：Twin 的读写、字段级权限、版本控制。
- 读：`get(email) → Twin`（内存缓存 + 文件持久化，写时落盘）。
- 写分两条通道，严格分开：
  - `patchProfile(email, patch)`：只允许 `profile/goals/subscriptions`（对应 `PATCH /api/twin`），其余字段拒绝。
  - `commitSettlement(email, delta)`：只允许结算钩子调用，写 `mastery`、`apState.*.predicted`、任务状态，并在此处统一发事件——保证「科目包没有私有写回路径」。
- 并发：单用户量级下用内存互斥 + 落盘串行队列即可；每次写带 `version` 自增，冲突返回 409。

### 2.2 SubjectPackRegistry（学科包注册表）

- 启动时扫描 `packs/` 目录加载全部 manifest（格式见 API.md 1.2），建 `courseId → pack` 索引。
- `load(courseId)`：未注册抛 `PACK_NOT_FOUND`（API 层转 404）。
- `skillsFor(pack, taskType, mode)`：按任务类型与当前模式筛出要挂载的 Skill 列表（日常挂苏格拉底类，冲刺挂对应家族 grader），其余 Skill 不进 Session 上下文。
- 新增一门 AP = 往 `packs/` 加一个 manifest + 一个 RAG namespace 定义，不改代码。第二门起边际成本只在内容，不在工程。

### 2.3 SessionRuntime（AP Base Agent 底座 + 泛化入口）

一个运行时服务三类 Agent，控制流共用，差异在装载物：

| | AP_BASE | DSAT | ADMISSIONS |
|---|---|---|---|
| 装载 | 学科包（skills/rag/mcp） | 内置技能集（自适应出题、错因图谱、Desmos 教练、语境词汇） | 内置技能集（选校矩阵、主线引擎、访谈、活动重写） |
| 模式 | GPA_SYNC / EXAM_CRUNCH 双模式状态机 | ADAPTIVE | INTERVIEW / SCHOOL_LIST / ACTIVITIES |
| 结算 | 掌握度增量 + 预测分 + 跨域事件 | 错因标签 + 分数轨迹事件 | 主线缺口事件 |

- `start(taskId)` 流程：查任务 → 校验订阅（AP 查 `subscriptions.apCourses`，未订阅 403）→ 按上表装载 → 建 Session（状态 ACTIVE）→ 发 `session.started` → 返回 API.md 2.5 的响应结构。
- 双模式状态机只存在于 AP 路径：`calendar.pressure` 事件可*建议*切换，学生手动切换优先，状态机不自动改模式。
- Session 内每一步（学生作答、OCR、工具调用）先落事件，再调 SkillExecutor；Session 对象只持有 `sessionId/twin 引用/装载清单/当前模式`，不保存第二份学生数据。

### 2.4 SkillExecutor（技能执行器）

- Skill = 结构化提示模板 + 输入/输出 JSON Schema + 可选工具白名单（注册在 manifest 里，执行器按 schema 校验输出，不合格重试一次后降级为纯文本反馈）。
- 首版 8–10 个核心 Skill 按家族实现（见方案文档第 5 节表），苏格拉底全科目共用、按包参数化。
- 每个 Task 只挂 1–2 个 Skill：Session 启动时由 Registry 决定，执行器不做动态发现，行为可预测、可审计。
- Phase 1 的 Desmos/Java 沙箱等 MCP 工具先做演示级实现（返回结构化假结果或真实调用可插拔），契约按包注册，替换实现不动上层。

### 2.5 Planner（任务规划）

- 输入：Twin 全量 + Timeline（含 SAT 考次、5 月 AP、校内考试周）+ 当周可用小时。
- v1 用**规则引擎**，不接模型（可解释、可测试）：
  1. 算差距：SAT 当前分 vs 目标；每门 AP 预测分 vs 目标与距 5 月的天数；申请材料 vs 截止日。
  2. 加权：`权重 = f(紧急程度, 录取杠杆)`。硬规则示例：EA 文书在 11 月权重高于词汇；某 AP 预测 ≤3.5 且距大考 <8 周时切 EXAM_CRUNCH 任务占比上升；校内考试周由 `calendar.pressure` 下调 SAT 题量（默认 −30%）。
  3. 装箱：按权重降序往当周小时里装，任务必须具体到「15 道线性方程组变式」级别，不产出「去学 SAT」式任务。
  4. ROI 建议：同一套差距数据生成小时分配建议（附依据，不产出录取概率）。
- 输出：Task 列表落 TwinStore（状态 PLANNED），`GET /api/tasks` 直接读。
- 触发：每日凌晨生成当日任务 + 每次结算后增量重排（事件驱动调用同一函数）。

### 2.6 EventBus（跨域总线）

- 进程内发布/订阅 + append-only 落盘（`data/events.jsonl`），事件格式见 API.md 1.4。
- 消费者（Phase 1 只做前两个，其余先落盘待 Phase 2 启用）：
  - Planner：听 `calendar.pressure`、`narrative.gap`、`ap.predicted` → 重排任务。
  - SAT 侧：听 `skill.weak` → 按 `satTags` 生成变式题任务；听 `vocab.context` → 生成语境闪卡任务。
  - Admissions 侧：听 `ap.predicted`、`sat.trajectory` → 标记选校矩阵待重算。
- 前端事件流读同一落盘日志，保证「界面上看到的事件」与「系统实际发生的事件」是同一份。

## 3. 存储设计（首版 JSON）

```
server/
  server.js            # 入口：HTTP + 路由
  lib/                 # twin-store / planner / session / registry / skills / llm
  packs/               # 五门学科包 manifest（calc_bc.json 等）
  data/
    twin-<email>.json  # 每学生一个 Twin 文件
    events.jsonl       # 事件日志（append-only）
    tasks-<date>.json  # Planner 产出快照（可由 Twin 重建）
```

- Twin 文件写入走临时文件 + rename 原子替换，防写坏。
- 迁移 Firestore 时：`twin-<email>.json` → `userProfiles/{email}` 文档；`events.jsonl` → `twinEvents` 集合；接口与模块不变。

## 4. 关键流程

**打开 AP Session**：`POST /api/ap/session/start` → TwinStore 查订阅 → Registry 装载包 → SessionRuntime 建 Session → EventBus 发 `session.started` → 返回装载清单给前端渲染装备栏。

**订正并结算**：前端在工作区点「修正 Step 3」→ `POST /api/twin/events`（student 动作留痕）→ 完成任务后 `POST /api/session/{id}/settle` → SessionRuntime 汇总 outcome → TwinStore.commitSettlement 算掌握度增量（v1 规则：错因计数 + 分项加分；BKT 接口预留，Phase 2 替换实现）→ 更新预测分 → 发 `skill.weak`/`ap.predicted` → Planner 增量重排 → 返回新预测分给前端。

**清晨任务生成**：定时（或首次 `GET /api/tasks` 懒生成）→ Planner 读 Twin + Timeline → 生成当日 Task 列表落盘。

## 5. 安全与边界

- 本地开发：`X-User-Email` 头标识用户（已确认）；上线前换 college advisor 的 JWT 校验，email 仍作连接键。
- CORS：只允许本地前端来源（`file://` 联调时临时放行，上线收紧到正式域名）。
- 红线在后端 enforce，不靠前端自觉：Skill 输出过 schema 校验，文书类 Skill 只有大纲/追问/反馈模板，没有正文生成入口；RAG namespace 只含考纲结构与采分逻辑，不存真题全文；选校与 ROI 输出必须引用 Twin 内真实分数，缺数据时返回「数据不足」而不是编造。

## 6. 目录与运行

```
hs-student-os/
  index.html
  doc/   HIGH_SCHOOL_STUDENT_OS.md  API.md  BACKEND.md
  server/
    server.js  lib/  packs/  data/
```

运行：`cd server && node server.js` → `http://localhost:8787`；前端双击 `index.html` 即联调，后端未启动时前端按 API.md 约定回退 mock。

## 7. 实现顺序（确认后执行）

1. 骨架：server.js + TwinStore（JSON）+ 五个 manifest + `GET /api/twin`、`/api/packs`、`/api/tasks`（Planner v1 规则）跑通。
2. Session：`session/start`（含订阅校验）+ `settle`（含 commitSettlement 与事件）+ 事件读写。
3. 前端改造：启动拉取、点任务调 start、订正/结算调 settle/events、离线回退标记。
4. 联调验收：按 API.md 逐端点核对；重点验三条链——未订阅 403、结算后预测分变化并出现在事件流、AP 薄弱点生成 SAT 任务。

## 8. 可扩展性：一切皆注册表

目标是「加东西不改核心代码」。五类可扩展物全部用声明式 manifest + 目录约定，启动时扫描注册（后续可热加载）：

| 可扩展物 | 注册位置 | 内容 |
|---|---|---|
| Agent | `agents/*.json` | 运行时类型、技能集、工作流、MCP 白名单、RAG 范围、模型策略 |
| 学科包 | `packs/*.json` | 见 2.2，已有机制 |
| Skill | `skills/*.json` | 提示模板引用、输入/输出 Schema、工具白名单、默认模型档 |
| Workflow | `workflows/*.json` | 声明式步骤流（见下） |
| MCP / RAG | `mcp.json` / `rag.json` | MCP server 注册表（地址、传输、启停）；RAG namespace 注册表（后端实现可插拔：本地文件 → 向量库） |

Agent manifest 示例：

```json
{
  "agentId": "AP_BASE",
  "runtime": "session",
  "skills": ["skill.tutor.socratic_step", "skill.frq.stem_derivation_grader"],
  "workflows": ["wf.ap_session"],
  "mcpAllowlist": ["sympy", "desmos", "twin-bus"],
  "ragNamespaces": ["ced_*", "user_{email}_{courseId}"],
  "modelPolicy": { "default": "balanced", "grader": "strong", "decisions": "jev" }
}
```

新增一个 Agent 的完整流程：写 manifest + 它的 Skill/Workflow 定义 → 注册表加载 → Twin 订阅字段加一项 → 前端按 `GET /api/agents` 渲染导航入口。SessionRuntime、TwinStore、EventBus 零改动。以后加 PSAT、竞赛、夏校申请等 Agent 都走这条路。

Workflow 声明式定义：步骤数组，每步是 `skill`（调技能）、`tool`（调 MCP 工具）、`decision`（决策分支，见第 10 节）、`emit`（发 Twin 事件）之一。Session 的双模式流程、Planner 的任务生成流程都用 workflow 描述——改流程改 JSON，不改代码。

## 9. 模型路由（ModelRouter）

后端不绑死单一模型。LLMGateway 之上加一层 ModelRouter，业务代码只认**档位名**，不认具体型号：

| 档位 | 用途 | 典型承担 |
|---|---|---|
| `decision` | 只判断不生成：路由、分类、打分、校验 | Jev（见第 10 节） |
| `fast` | 闪卡生成、词汇提取、简单分类反馈 | 小模型 |
| `balanced` | 苏格拉底辅导、错题讲解、常规批改 | 主力模型 |
| `strong` | FRQ 精批、选校矩阵、文书反馈 | 最强模型 |

路由决策顺序：
1. Skill / Agent manifest 里的默认档（配置决定，可改配置不改代码）。
2. 规则升级：任务类型、输入长度、上次输出未过 schema 校验 → 自动升一档重试。
3. Jev 决策：manifest 没定档或规则判不了时，用 Jev 给任务复杂度打分选档。
4. 成本护栏：单 Session 设 token 上限，超限降档并记一条 Twin 事件，保证成本可审计。

具体型号集中写在 `models.yaml`（档位 → 厂商/型号/参数），换模型只改这一个文件。

## 10. Jev 决策层（引用 TypeSafe Jev）

Jev 是 TypeSafe AI 于 2026 年 9 月发布的「System One」决策模型：输入应用状态 + 类型化问题，输出带校准概率的决策（Choice / Score / Boolean 三类），**不生成文本**；延迟约 70–500ms，输入价格约 $0.042/百万 tokens，专为高频小判断设计。后端设一个 `DecisionService` 接口封装它。Phase 1 只接第 1 和第 3 点；其余四点随后再接。六个落点是：

1. **模型路由**：给任务复杂度打分，ModelRouter 据此选档（Jev 官方主推用法之一）。
2. **MCP 工具选择**：工具目录大时，先由 Jev 对每个工具答一次「本步是否需要」，LLM 只看到通过的少数工具，省上下文（公开实现 jev-mcp-router 的做法）。
3. **RAG 相关性门控**：检索片段逐条过 Jev 判断「是否真能支撑回答」，不达标就换源或弃权，不让模型拿不相关材料硬答。
4. **Planner 排序辅助**：任务优先级在规则权重之外，可用 Score 型决策做细粒度排序。
5. **Workflow 分支**：`decision` 步骤的默认实现——要不要重试、要不要升级强模型、要不要先追问学生。
6. **输出护栏**：生成结果过校验类问题（如文书反馈是否越界成代写、选校建议是否引用了不存在的分数），低置信时走强模型复核。

约束与回退（必须写进实现）：
- Jev 目前是 **early access**，需要去 TypeSafe 申请 API key；`DecisionService` 做成可插拔，没有 key 时整层禁用、自动回退到规则判断，业务不中断。
- Jev 训练以英文为主，官方口径是中文等语言精度较低。本产品大量中文内容场景（APUSH 汉化材料、学生中文作答）阈值要设保守，重要判断仍由强模型复核，Jev 只做第一道筛。

## 11. 已确认决定（2026-10-28）

1. 本地开发用 `X-User-Email` 代替 JWT。上线再换 college advisor 的 JWT，email 仍是 Twin 连接键。
2. Twin 首版存储用本地 JSON 文件。`TwinStore` 接口不变，以后换 Firestore 只换实现。
3. DSAT / Admissions 复用泛化入口 `POST /api/session/start`。AP 仍走 `POST /api/ap/session/start`。
4. 后端选型：Node ≥18，`server.js` 用内置 `http`，零框架依赖起步。接口稳定后再考虑换 Express / Fastify，只换 API 层。
5. 引入 Jev 作决策层。Phase 1 只接「模型路由」和「RAG 门控」。需要申请 TypeSafe API key；没有 key 时 `DecisionService` 回退到规则，业务不中断。MCP 工具选择、Planner 排序、Workflow 分支、输出护栏随后再接。
