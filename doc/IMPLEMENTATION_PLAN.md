# High School Student OS — 前后端详细实施计划（v1.0）

依据：`HIGH_SCHOOL_STUDENT_OS.md`（产品方案）、`API.md`（接口契约）、`BACKEND.md` v0.2（后端设计）、`../web/README.md`（前端模块地图）。
当前状态：前端模块化版 `web/` 已完成（纯 mock，数据走 `data.js` 的 HSData 接缝）；后端 `server/` 仅有早期骨架（已暂停）。接口与后端设计已于 2026-10-28 确认，见 `BACKEND.md` 第 11 节。
工时口径：按业余时间（晚间+周末）估算的「有效开发日」，含联调不含内容生产；内容轨单独列（第 7 节）。

## 工程执行规则（必须遵守）

### 0.1 仓库边界与所有权

- **唯一实现仓库**：所有新功能、修复、测试、配置、迁移脚本和文档只能写入 `~/Documents/education/hs-student-os` (以下简称 Student OS)。
- **只读参考仓库**：`~/Documents/education/ai-college-advisor` 和 `~/Documents/education/sat-tutor-app` 只用于阅读、盘点和提取可复用思路。不得在这两个目录中编辑文件、安装依赖、运行格式化/迁移脚本、提交代码或修改其数据。
- **参考不等于集成**：Student OS 不得在运行时通过 `../ai-college-advisor`、`../sat-tutor-app`、绝对路径、软链接或本地端口依赖这两个工程。移走两个参考目录后，Student OS 仍必须能独立构建、测试和运行。
- **外部产品接入是后续边界**：如需与原有产品互通，Student OS 只在本仓库实现稳定 API/深链接契约；对方仓库的适配改动不属于本计划，必须另立任务和授权。

### 0.2 参考代码的引入规则

1. **先盘点，后实现**：引入前记录源文件、用途、依赖、数据模型、测试状态与适配工作量；不因“已有代码”就默认可直接复制。
2. **按能力切片引入**：优先提取纯函数、数据 schema、规则、测试用例和无 UI 的领域逻辑。不整目录复制，不连同旧项目的页面框架、认证、存储和部署绑定一起搬迁。
3. **先适配 Student OS 契约**：引入代码必须改造为 TwinStore、Course/Agent Registry、SessionRuntime、EventBus 和 `API.md` 定义的边界，不得为了少改旧代码而建第二套学生身份、会话、任务或掌握度数据。
4. **保留来源**：直接改造的非平凡代码需在 PR/变更记录中写明来源仓库、原路径和引入日期；代码内只在能帮助维护时保留简短 provenance 注释。
5. **合规与秘密检查**：引入前确认代码所有权/许可兼容性；严禁复制 `.env`、API key、JWT 秘钥、用户数据、生产日志、缓存、构建产物和受版权保护的题库内容。
6. **不保留旧系统隐式假设**：SAT 代码必须符合 Digital SAT 1600 分和两阶段模块；Admissions 代码必须使用 Twin 的实时画像，不继承旧项目的全局状态、假数据或提示词内嵌身份。

### 0.3 大型工程的交付规则

- **纵向切片**：一次只交付一条可运行链路（例如“读 Twin → 产生任务 → 打开 Session → 结算回写”），不先搭出大量不可验证的空框架。
- **契约先行**：更改 API、Twin event、manifest 或 schema 时，先更新契约与测试，再更新实现；不允许前后端靠未记录的隐式字段联调。
- **单一学生真值**：学生身份、目标、日历、掌握度和成果只存在 Twin；各课程 Agent 实例通过 student-scoped EventBus 交换结构化事件，不直接共享可变状态。
- **共享运行时，课程模块化**：每个已注册课程有独立 Agent 实例（`studentId:courseId`），但复用同一 CourseAgentRuntime。新增课程应以 manifest + skills + RAG + tools + tests 完成，不复制整套 Agent 核心代码。
- **每个切片自验证**：至少包含正常路径、权限/订阅失败路径、重复请求幂等性、持久化恢复和一条跨 Agent 事件链测试。
- **小步可回滚**：提交必须单一目的、不夹带无关重构；数据迁移提供版本号、旧格式读取兼容和回滚/恢复说明。
- **性能、成本与隐私可观测**：每个 Session 记录延迟、模型档位、token 和工具调用，但日志不写完整学生作答、文书正文、认证信息或密钥。

## 0. 总览：里程碑

| 里程碑 | 内容 | 出口标准 | 估时 |
|---|---|---|---|
| M0 收尾与基线 | 后端骨架清理、仓库规范、Jev key 申请 | 本地一条命令起全栈（mock 数据） | 2 天 |
| M1 后端核心 | TwinStore + 注册表 + Planner v1 + 读接口 | API.md 读接口全通，前端切到真数据渲染 | 5 天 |
| M2 会话闭环 | session start/settle + 事件总线 + 前端接线 | 三条验收链全过（见 3.3） | 5 天 |
| M3 智能层 | LLM 网关 + ModelRouter + SkillExecutor + 首批真 Skill | 苏格拉底/精批走真模型，输出过 schema 校验 | 7 天 |
| M4 Jev 决策层 | DecisionService 接 Jev（路由 + RAG 门控） | 无 key 自动回退；有 key 时路由/门控生效可观测 | 3 天 |
| M5 上线硬化 | JWT、Firestore、多用户、部署、成本护栏 | 外部学生可注册使用，红线检查全过 | 7 天 |

总计约 29 个有效开发日。M1–M2 是「能演示的真系统」，M3 起是「有真智能的系统」，M5 是「能给别人用的系统」。

## 1. M0 收尾与基线（2 天）

**后端**
- [ ] 建立参考代码盘点表：列出 `ai-college-advisor` / `sat-tutor-app` 中候选能力、源路径、依赖、许可/秘密风险、“引入/重写/放弃”决策；不做源仓库改动。
- [ ] 盘点已暂停的 `server/` 骨架，按 BACKEND.md 第 3 节目录结构对齐（server.js / lib/ / packs/ / agents/ / data/），不符合的删掉重写，不背历史包袱。
- [ ] `package.json`（零依赖声明、Node ≥18）、`.gitignore`（data/ 不入库，种子数据除外）。
- [ ] 种子 Twin 固化为 `server/data/seed/twin-alex.json`，与前端 mock 的 Alex 数据逐字段对齐（订阅 calc_bc/apush/csa、Calc 预测 4.5、SAT 1510→1550）。

**前端**
- [ ] `web/` 定为前端主线；根目录单文件 `index.html` 冻结为演示版，不再双向同步。
- [ ] `data.js` 的 HSData 接口签名冻结（getPacks/getSessions/getEvents/getStudent + 后续异步化预留），写进 web/README。

**外部依赖（尽早启动，有等待期）**
- [ ] 申请 TypeSafe Jev API key（early access，等待时间未知，M4 才用，但现在就申请）。
- [ ] 确认 LLM 网关首选厂商账号与额度（Claude / OpenAI 二选一起步）。

## 2. M1 后端核心 + 前端切真数据（5 天）

### 2.1 后端任务
- [ ] **TwinStore**（lib/twin-store.js）：get / patchProfile（字段白名单）/ commitSettlement（结算专用通道）/ version 自增与 409；JSON 落盘走临时文件+rename；内存缓存。
- [ ] **注册表**（lib/registry.js）：启动扫描 `packs/*.json`（五门）与 `agents/*.json`（三个 Agent），建索引；`skillsFor(pack, taskType, mode)` 按模式筛 Skill。
- [ ] **Planner v1**（lib/planner.js）：规则引擎——差距计算（SAT 当前 vs 目标、AP 预测 vs 目标与距 5 月天数、申请截止）、权重 = 紧急度 × 录取杠杆、按当周可用小时装箱、产出具体到题量的 Task 落盘；`calendar.pressure` 下调 SAT 题量（−30%）。
- [ ] **读接口**：GET /api/twin、/api/packs、/api/packs/:id、/api/tasks、/api/agents、/api/agent/context（画像摘要版即可）。
- [ ] **静态托管**：server.js 同时 serve `web/`，一条命令全栈启动。
- [ ] 单元测试：TwinStore 字段权限、Planner 权重规则各 ≥3 个用例（node:test，零依赖）。

### 2.2 前端任务
- [ ] `data.js` 改造为**异步 provider**：`HSData.ready()` 返回 Promise，先拉 twin/packs/tasks，组件渲染前完成；加载中显示骨架屏，失败自动回退内置 mock 并显示「离线演示模式」角标（接回 M2 前的临时形态，M2 完成事件接线后定型）。
- [ ] `app.js` 启动流程改异步；`store.js` 增加 `online` 与 `loading` 状态；其余模块不动（这是模块化预留接缝的兑现点，改动应只落在 data.js / store.js / app.js 三个文件，超出即说明接缝失效，要停下来修接缝而不是改组件）。
- [ ] 顶栏加连接状态指示（已连接/离线演示）。

### 2.3 M1 验收
- 后端未启动：前端 = 离线演示模式，行为与现版一致。
- 后端启动：刷新后任务列表、预测分、订阅状态全部来自 /api；改种子 Twin 的预测分，刷新即变。

## 3. M2 会话闭环（5 天）

### 3.1 后端任务
- [ ] **EventBus**（lib/events.js）：进程内 pub/sub + `data/events.jsonl` append-only 落盘；GET/POST /api/twin/events。
- [ ] **SessionRuntime**（lib/session.js）：POST /api/ap/session/start（订阅校验 403、未注册 404、装载清单、发 session.started）；POST /api/session/start（DSAT/Admissions 泛化入口）；Session 状态机 PLANNED→ACTIVE→SETTLED。
- [ ] **settle**（POST /api/session/:id/settle）：汇总 outcome → commitSettlement 算掌握度增量（v1 规则：错因计数+分项加分）→ 更新预测分 → 发 ap.predicted / skill.weak → 触发 Planner 增量重排；重复结算 409。
- [ ] **跨域消费者**：skill.weak → Planner 按 satTags 生成 DSAT 变式任务；vocab.context → 生成语境闪卡任务（任务落盘即可，内容 M3 生成）。

### 3.2 前端任务
- [ ] `store.js` 动作接线：openSession → 调 session start（AP 走专用入口）；「完成并结算」→ 调 settle，用返回值刷新预测分；订正/采纳/词汇同步等现有 pushEvent 动作改为同时 POST /api/twin/events（本地先行渲染、后端为准）。
- [ ] 事件流改为以后端日志为源（打开时拉取 + 动作后刷新；SSE 留 M5）。
- [ ] 在线/离线双行为一致性核对：同一操作离线走本地、在线走后端，UI 结果一致。

### 3.3 M2 验收（三条链，逐条过）
1. 未订阅 phys_c 打开任务 → 403 COURSE_NOT_SUBSCRIBED，前端给出订阅引导而非报错页。
2. Calc FRQ 订正并结算 → 预测分 4.5→4.8，事件流出现 session.settled 与 ap.predicted，Twin 落盘可查。
3. Calc GPA 订正触发 skill.weak → 今日任务里出现 SAT 复合函数变式任务。

## 4. M3 智能层（7 天）

### 4.1 后端任务
- [ ] **LLMGateway**（lib/llm.js）：统一 `chat({tier, system, messages, schema}) → JSON`；输出 schema 校验，不合格重试一次、再不合格降级为纯文本反馈并记事件。
- [ ] **ModelRouter**（lib/model-router.js）：四档 decision/fast/balanced/strong；路由顺序按 BACKEND.md 第 9 节（manifest 默认档 → 规则升级 → Jev（M4 接入，先留接口）→ 成本护栏）；型号集中在 `models.yaml`。
- [ ] **SkillExecutor**（lib/skills.js）：按 skills/*.json 注册执行；首批真 Skill（按家族）：
  - 共用：苏格拉底分步辅导（balanced，按包参数化）
  - STEM：FRQ 采分点精批（strong）、OCR→LaTeX 结构化（balanced，先接图片输入通道）
  - 文科：DBQ/论说文 Rubric Diff（strong）、史料 Sourcing 追问（balanced）
  - SAT：错因变式题生成（balanced）、语境闪卡生成（fast）
  - 申请：访谈追问（strong）、活动 150 字符改写（fast，事实需学生确认的交互不变）
- [ ] **RAG v1**：namespace 先做本地文件检索（考纲结构 + 采分逻辑 + 校内讲义），接口按 rag.json 注册表抽象，M5 换向量库不改调用方。
- [ ] **MCP v1**：SymPy/Desmos 先做演示级真调用或结构化 stub（按 packs 注册），Twin Bus 即 EventBus 的工具封装。
- [ ] **成本护栏**：单 Session token 上限（models.yaml 配置），超限降档 + 记 Twin 事件；每日用量汇总打日志。

### 4.2 前端任务
- [ ] 工作区接真 Skill 输出：苏格拉底追问、FRQ 精批、闪卡内容由接口返回渲染（替换写死文案，结构不变）；流式输出先做整段返回 + 打字机效果，不做真流式（SSE 在 M5 一并考虑）。
- [ ] 图片上传通道：手写推导入口接文件选择 → 上传 → OCR 结果回填画布。
- [ ] 错误与降级态：Skill 超时/降级时前端有明确提示，不白屏。

### 4.3 M3 验收
- 同一道 FRQ，精批结果引用真实采分点且与学生作答内容对应（非模板文案）；换一道题结果随之变化。
- 每个 Skill 的档位、token 消耗在日志里可查；超限降档实际发生过一次（人为调低上限验证）。

## 5. M4 Jev 决策层（3 天）

- [ ] **DecisionService**（lib/decision.js）：封装 Jev API（Choice/Score/Boolean 三类问题），超时 800ms 熔断；无 key / 超时 / 低置信一律回退规则，业务零感知。
- [ ] 落点一（模型路由）：manifest 未定档的任务由 Jev 打复杂度分选档，结果与规则档不一致时记事件便于复盘。
- [ ] 落点二（RAG 门控）：检索片段逐条过 Jev「是否支撑回答」，不达标弃权/换源；弃权时前端显示「材料不足」而不是硬答。
- [ ] 中文场景护栏：中文内容阈值保守（单独配置），Jev 只做第一道筛，重要判断仍走 strong 档复核（BACKEND.md 第 10 节约束）。
- [ ] 验收：断网/停用 Jev 后全功能可用（回退验证）；开启后路由与门控决策在事件流可审计。

## 6. M5 上线硬化（7 天）

- [ ] **鉴权**：X-User-Email 替换为 ai-college-advisor 的 JWT 校验；email 仍作 Twin 连接键；CORS 收紧到正式域名。
- [ ] **存储迁移**：TwinStore 换 Firestore 实现（userProfiles/{email} + twinEvents 集合），接口不变，M1 的单元测试原样跑通才算迁移完成。
- [ ] **多用户**：按 email 隔离数据与事件；订阅字段接真实开通流程的最小版（人工开通即可，不做支付）。
- [ ] **对外集成契约**：只在 Student OS 内实现并测试 `GET /api/agent/context`、JWT 验证与 SAT 深链接接收端；用 contract test/模拟客户端验证兼容性，本计划不修改 `ai-college-advisor` 或 `sat-tutor-app`。
- [ ] **实时性**：事件流升级 SSE（接口语义不变）。
- [ ] **部署**：单机部署脚本 + 环境变量清单（LLM key、Jev key、JWT 密钥）；数据备份（Twin 每日导出）。
- [ ] **红线复查**（上线门禁，逐条签核）：文书 Skill 无正文生成入口；RAG 无 College Board 真题全文；选校/ROI 输出只引用 Twin 真实分数、缺数据返回「数据不足」；无录取承诺文案。
- [ ] **前端迁移评估**（仅评估，不在本期执行）：web/ 模块与 Next.js 组件一一对应，迁移成本评估后另立计划；React Native Web 复用 store/data 层的可行性结论。

## 7. 内容轨（与开发并行，产品侧投入）

- 五门 AP 包内容：考纲结构、采分点、校内进度映射——先 Calc BC + APUSH 两门做深（已订阅演示路径），其余三门跟上。
- SAT 题库：自研题（按错因图谱组织），严禁用真题；变式题生成规则与人工抽检流程。
- 申请：Reach/Match/Safety 数据来源与更新节奏、访谈问题库。
- 内容验收标准随 M3 的 Skill 一起定（每个 Skill 至少 5 个真实样例人工评审）。

## 8. 风险与对策

| 风险 | 对策 |
|---|---|
| Jev early access 申请不到位 | M4 可整段跳过，DecisionService 回退规则，架构不受影响 |
| LLM 成本失控 | ModelRouter 分档 + 单 Session 上限 + 每日汇总，M3 就落地不等 M5 |
| 前端接缝失效（改组件才能接后端） | M1 设检查点：改动文件数超 data/store/app 三个即停工修接缝 |
| 掌握度模型 v1 过于粗糙 | settle 接口与数据结构预留 BKT，Phase 2 换实现不换契约 |
| 内容生产拖过开发 | 内容轨独立排期，开发用种子内容先行，Calc/APUSH 优先 |

## 9. 待你拍板的事项（不阻塞 M0–M2）

1. LLM 网关首选：Claude 还是 OpenAI 起步（M3 前定）。
2. M5 部署形态：自有服务器 / 云函数 / 沿用现有 Firebase 生态（M5 前定）。
3. 前端是否在本期后启动 Next.js 迁移（M5 评估后定）。
