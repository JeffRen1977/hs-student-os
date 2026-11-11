# 运维手册（M4：Steps 30–32）

更新：2026-11-05（provision.sh 重新运行，M5 代码部署到 staging，§5）。2026-11-04（记录 2026-11-03 首次真实 staging 部署与冒烟测试，§5）。2026-11-01。本文件记录部署方式、日志与指标、告警处置、备份恢复与删除，以及**哪些检查真正跑过**（Step 30.5）。只写进文档不算完成：除非下表标明"已运行"，否则该项仍未验证。

## 1. 部署形态（Step 30）

- 镜像：`server/Dockerfile`，API 与 worker 共用一个镜像，用 `HSOS_ASGI_APP` 区分（`app.main:app` / `app.workers.main:app`）。镜像以非 root 用户（10001）运行，只包含 `app/` 与 `content/`，不含合成 fixtures、测试和脚本。
- 资源创建：`deploy/staging/provision.sh`。默认**只打印命令**（dry run）；`APPLY=1` 才执行。拒绝 `demo-*` 项目。使用独立的 staging 项目，不与其他教育项目共享任何资源。
  - Cloud Run：`hsos-api`（公开 HTTPS，学生用 Firebase ID token）与 `hsos-worker`（`--no-allow-unauthenticated`，仅 `hsos-tasks-invoker` 有 `run.invoker`）。
  - 服务账号分离：`hsos-api`、`hsos-worker`、`hsos-tasks-invoker`（Cloud Tasks 与 Cloud Scheduler 的 OIDC 身份）。worker 只接受该身份签发、audience 为 worker URL 的 Google OIDC token；学生 token 返回 401（已有测试）。
  - Firestore（native）+ `server/firestore.indexes.json`；每日托管备份，保留 14 天。
  - Cloud Tasks 队列 `runs`：最多 5 次、5 s–300 s 退避。
  - Cloud Scheduler（全部带 OIDC）：outbox 派发每分钟；恢复扫描、提醒、告警检查每 5 分钟；定时计划每 15 分钟；事件保留每天 03:30 UTC。
  - Secret Manager：`<LLM_PROVIDER>-api-key`（默认 `anthropic-api-key`；staging 用 `LLM_PROVIDER=openai` → `openai-api-key`），只授权 worker 读取。值手工添加，不进仓库。
  - Storage：`-uploads`（文本试点暂不用）与 `-backups`（30 天后自动删除）。
  - 预算：设置 `BILLING_ACCOUNT` 时创建月度预算（默认 200 USD，50%/90% 提醒）。模型用量另有应用内 token 预算（每 Run / Session / 学生每天）。
- 配置：`deploy/staging/api.env.yaml`、`worker.env.yaml`。`tests/unit/test_deploy_config.py` 验证它们加上脚本注入的变量能通过部署环境检查。

### 1.1 超时与重试（Step 30.4）

| 项 | 值 | 原因 |
|---|---|---|
| API 请求超时 | 900 s | SSE 每 300 s 主动关闭（`HSOS_SSE_MAX_STREAM_SECONDS`），客户端带 `Last-Event-ID` 续接 |
| worker 请求超时 / Scheduler attempt deadline | 600 s / 540 s | 覆盖一次 Run（模型 60 s × 3 次） |
| Run 租约 | 300 s | 必须大于模型超时 × 次数（180 s）；配置在部署环境下会拒绝更短的租约（新检查，见下） |
| QUEUED 重新入队 | 600 s | 队列丢消息时由恢复扫描补发 |

M4 发现：此前的默认租约 120 s 小于最坏模型调用时间 180 s。fencing token 保证不会重复提交，但会让第二个 worker 重复调用模型（重复计费）。现在 `Settings` 在 staging/production 拒绝 `HSOS_RUN_LEASE_SECONDS <= 超时 × 次数`。

## 2. 日志与指标（Step 31.1–31.2）

- 部署环境必须 `HSOS_LOG_FORMAT=json`（配置检查强制）。`app/adapters/observability.py` 的格式化器：数字/布尔任意字段可输出；字符串、列表、字典只在允许的键（各类 id、状态、错误码、模型档位等）下输出，其余替换为 `[redacted]`；异常只记录类型和栈帧，不记录消息（消息可能回显输入）。因此即使某处误把答案放进 `extra`，也不会进日志。
- 指标作为 `message="metric"` 的日志条目输出，Cloud Monitoring 用基于日志的指标（`deploy/monitoring/metric-*.yaml`）统计：
  - `run.execute_ms`（评估/提示延迟，按 kind）、`run.committed`；模型 token 用量来自网关已有的 `app.llm` 日志（`tokens` 字段）。
  - `outbox.pending_scanned`、`outbox.backlog`、`runs.failed_last_hour`、`outbox.dispatch_failed`。
  - `duplicate.suppressed`（`source=idempotency|delivery|reminder`）。
  - `http.latency_ms`（按路由模板，不用原始路径）、`reminder.outcome`、`ops.alert`。
- 未做：学习质量回归没有在线指标。质量由评估集（Step 7/21）离线衡量，阈值待内容审核员设定。

## 3. 告警（Step 31.3）

`/internal/ops/check` 每 5 分钟评估，触发时以 ERROR 记录 `alert_firing`，`deploy/monitoring/alert-ops.json` 据此告警；另有 worker 5xx 告警（`alert-worker-errors.json`，503 是"稍后重试"信号，不计入）。

| 告警 | 条件（默认） | 处置 |
|---|---|---|
| `outbox_backlog` | ≥ 50 条 PENDING 超过 5 分钟 | 检查 Scheduler 的 outbox 任务与 Cloud Tasks 队列；手工 `POST /internal/outbox/dispatch`；条目不会丢失 |
| `worker_failures` | 1 小时内 ≥ 10 个 Run FAILED | 按 `errorCode` 分组查看日志；模型提供方故障时暂停评估入口 |
| `budget_overruns` | 1 小时内 ≥ 5 个 Run 因 `BUDGET_EXCEEDED` 失败 | 检查是否有异常使用；预算上限是保护措施，不要直接调高 |

`tests/contract/test_operations.py` 模拟三种告警的触发与恢复。

## 4. 备份、恢复与删除（Step 31.4–31.5）

- **整库**：Firestore 托管每日备份（保留 14 天）。恢复到**另一个**数据库后再核对，不直接覆盖生产库。
- **单个学生**：`uv run python -m scripts.student_data export|restore|verify|delete`（`app/adapters/firestore/backup.py`）。
  - 导出包含 `students/{id}` 下全部文档和指向该学生的 `identities/{uid}`。备份文件含完整学习记录，只能存放在受保护的 backups 存储桶中。
  - 恢复只接受该学生自己的文档；默认不覆盖已有学生；**已删除学生（`deletedStudents/{id}` 墓碑）拒绝恢复**，所以旧备份不会让已删除的数据回来。
  - `verify` 检查记录内所有链接：Session→Task、Run→Session、Submission→Session/Run、Assessment→Session/Run/Submission、Run 结果→Assessment/Plan、outbox→Run、planState→Plan、事件序号连续。
  - 删除：先删子文档再删根文档，然后写只含 id 和时间的墓碑。删除后集合组扫描（outbox、Run、计划调度、提醒、学生列表）都查不到该学生。仍在托管备份中的数据随 14 天保留期过期；在此期间如需从整库备份恢复，恢复后必须对墓碑中的学生再次执行删除。
- **事件保留**：每天清理超过 180 天的事件并提高 `oldestRetainedSequence`；评估、掌握度、计划不清理。
- 已验证：内存存储上完成"完整学习流程 → 导出 → JSON 往返 → 恢复到独立存储 → 一致性检查 → 两边 API 读出完全相同"（`test_backup_restores_into_a_separate_store_with_every_link_intact`），以及删除与保留测试。Firestore SDK 路径（递归读取、批量写删）由 `tests/emulator/test_backup_emulator.py` 覆盖，**尚未运行**（本机没有 Java）。
- 文件（Cloud Storage 对象）尚未实现；实现文件上传时，导出与删除必须同时处理对象。

## 5. 检查记录（Step 30.5 / 32）

| 检查 | 状态 | 证据 / 原因 |
|---|---|---|
| 镜像构建并以非 root 运行；两个应用可导入；不含 fixtures | ✅ 已运行（本机 Docker，2026-11-01） | `docker build server/`；生产配置缺项时启动被拒绝 |
| 部署配置通过环境检查 | ✅ 已运行 | `tests/unit/test_deploy_config.py` |
| provision.sh 语法与 dry run | ✅ 已运行 | `bash -n`；dry run 输出命令；`demo-*` 被拒绝 |
| 真实部署到 staging | ✅ 已运行（2026-11-03，项目 `hs-student-os`） | `provision.sh APPLY=1`：Firestore `nam5`（`FIRESTORE_LOCATION`），Cloud Run / Tasks / Scheduler 在 `us-central1`，OpenAI 密钥在 Secret Manager，$20 预算告警。镜像 `eb4667d-dirty-20261103b`（M5 之前的代码）。Web 部署到 Firebase Hosting（`deploy_web.sh`） |
| provision.sh 重新运行（幂等）+ M5 后端部署 | ✅ 已运行（2026-11-05） | `PROJECT_ID=hs-student-os REGION=us-central1 FIRESTORE_LOCATION=nam5 LLM_PROVIDER=openai IMAGE_TAG=b22eb36-dirty-20261105 APPLY=1`：先 dry run 再执行。已存在的资源（数据库、密钥、桶、队列、仓库、6 个 Scheduler 作业、4 个日志指标、2 条告警策略）均跳过，未重复创建；IAM 绑定重新应用。Cloud Build 成功（1m25s），镜像 `b22eb36-dirty-20261105`（`b22eb36` 加未提交的 M5 改动）；`hsos-worker-00004-brn`、`hsos-api-00003-wsv` 各承接 100% 流量。部署后检查：`/api/health` 200、无 token 401、外部访问 worker 404。**未做**：Web 重新部署（Hosting 仍是 11-03 的前端）、新修订版上的提交 → worker → OpenAI 端到端 |
| 冒烟测试（真实 Firebase Auth + Firestore + Cloud Tasks + worker + 模型） | ✅ 已运行（2026-11-03） | 合成学生密码登录；health、无 token 401、托管域名 CORS、worker 外部访问 404；Alex 列出课程与任务、建 Session、Beth 读 Alex 的 Session 404；提交 → Cloud Tasks → worker → OpenAI → 评估提交 16 s，占位答案正确判为 `insufficient_evidence`；事件序列完整 |
| Cloud Tasks OIDC 端到端 | ✅ 已运行（2026-11-03） | 上面的提交经 Cloud Tasks 以 invoker 身份调用私有 worker 并完成 |
| Cloud Scheduler 作业与 `--ingress internal-and-cloud-load-balancing` 的组合 | ✅ 已查看执行日志（2026-11-07） | 当天 6 个作业的 `AttemptFinished` 全部 200（outbox 150 次、ops-check 30、reminders 30、planning 10、run-recovery 29/30），OIDC 调用内部 worker 正常。唯一一次 500 在 16:45:04，被路由到刚下线的旧修订版 `hsos-worker-00005`（0 s，无实例），见下面“修订版切换” |
| provision.sh 重新运行 + 当前 `main` 部署 | ✅ 已运行（2026-11-07） | `make check` 通过后部署 `61dfda6`（干净工作区），随后带修复重新部署 `IMAGE_TAG=61dfda6-dirty-20261107`：`hsos-worker-00006-d97`、`hsos-api-00005-8pj`（之后为 32.3 临时改并发，已恢复为 `hsos-api-00007-fgb`，concurrency 80、min 0）。`firebase deploy --only firestore:indexes`；Web 重新部署到 Hosting。部署后 health 200、无 token 401、外部访问 worker 404 |
| Step 32.1 Calc BC 完整学习链（真实模型） | ✅ 已运行（2026-11-07） | Alex：提示消息 → Cloud Tasks → worker → OpenAI `gpt-5.5-2026-04-23`；提交 → 评估 9.9 s，三项满分 `accepted`；提示后的证据记为 `correct_with_hint`（不算独立）；chain-rule `emerging`、独立证据 0；预测 `unavailable`；`complete` 幂等重放；Task `COMPLETED`；完成不重复计入掌握度 |
| Step 32.2 Digital SAT 与 Calc BC 并行 | 🟡 部分（2026-11-07） | 两门课同时在册；DSAT 按答案键计分 [1,0,1]、不调模型、答案键不下发；Calc 掌握度不变；无法识别的选项 → `insufficient_evidence` 无证据。**未运行**：课程内后续规则链（Step 24.2 未实现） |
| Step 32.2a 作者路径 | ✅ 已运行（2026-11-07） | 临时课程 `stgalg11071646`（DSAT 包改 id）：上传 → 报告（12/12 自动用例）→ 提交 → 审核 → 激活；其他组织 404、学生 403、草稿与无权限不可见/不可选；管理员授权后选课 → 2 个起始任务；打开的 Session 固定 1.0.0；1.1.0 发布后 1.0.0 `superseded`，旧 Session 仍按 1.0.0 答案键计分 [1,1,1]，新 Session 固定 1.1.0，旧评估不变；旧版本不能再激活（409）；最后退役，记录保留。测试课程均已退役，目录恢复为 `calc_bc`、`dsat`、`physics_c`；另留一个无效草稿 `stg_alg_11071636`（下划线使 rubricId 不合法，验证器正确拒绝） |
| **staging 发现的缺陷：worker 的包副本过期** | ✅ 已修复（2026-11-07） | 课程激活后约 30 s 内（`HSOS_PACKAGE_REFRESH_SECONDS`）提交的 Run，在包副本较旧的 worker 实例上以 `SESSION_NOT_OPEN`（不可重试）永久失败。`PackageContentSync.ensure_version` 文档写明会在 Run 固定的版本未加载时立即重新加载，但没有任何调用处。修复：`RunExecutionService` 在租约事务内检查固定版本是否已加载，缺失则不写任何东西、在事务外重新加载后再取一次租约。回归测试 `test_a_worker_with_a_stale_copy_runs_a_just_activated_course`；修复部署后 staging 中激活后立即提交的 Run 成功 |
| **staging 发现的缺陷：重新播种重置事件序号** | ✅ 已修复；数据已修补（2026-11-07） | `seed_staging` 把 `eventState/current` 覆盖为 `nextSequence: 1`，而已有事件保留，导致序号重复（11-06 一次、11-07 本次播种一次）；`course-metrics` 的 `processedSequence`（13）高于新序号，会静默跳过事件。修复：重新播种时保留已存在的 `eventState`、`planState`（`without_existing_runtime_state`，单测）。修补：把 Alex、Beth 的 `nextSequence` 提到已有最大序号之上（14、9），未删除任何事件；旧的重复序号作为历史保留 |
| Step 32.3 SSE 跨实例重连 | ✅ 已运行（2026-11-07） | API 临时设为 concurrency 1、min 2，相邻两个读者重叠打开因而必在不同实例。读者 0–3 分别在 4 个实例（`…2248e0`、`…b2fc12`、`…0a694e`、`…fb2535`），按 `Last-Event-ID` 续接，事件 9–15 无缺口、无重复。读者 4、5 得到 429/500（“等待可用实例超时”），是测试配置所致（见下一行）。测试后已恢复 |
| **发现：断开的 SSE 流在服务端持续到 300 s 上限** | ⚠️ 未处理 | 客户端约 10 s 后停止读取并退出，但 4 条流在 Cloud Run 日志中都持续 300.4–300.6 s：Cloud Run 后面 `request.is_disconnected()` 没有触发。每个被遗弃的标签页占用一个并发槽并每秒轮询 Firestore（`HSOS_SSE_POLL_SECONDS=1`），约 300 次读取。可选：降低 `HSOS_SSE_MAX_STREAM_SECONDS` 或轮询频率 |
| **发现：修订版切换后约 30 s 内的 5xx** | ⚠️ 未处理 | 两次部署后各有请求在流量已 100% 切换后被路由到已关闭的旧修订版，前端直接返回 500（0 s、无实例）：API 2 次（16:45:28、16:45:34），worker 的 run-recovery 1 次。重试即成功。命令都带 `Idempotency-Key`，客户端对 5xx 重试是安全的；Web 客户端目前是否重试未核实 |
| Digital SAT 2.0.0 在 staging 发布 | ✅ 已运行（2026-11-07） | `author_hsos` 上传 `package-2.0.0.json`（报告有效，36/36 自动用例）并提交；`reviewer_platform` 在审核队列中看到它，核对报告、状态历史、完整内容（与本地校验过的文件一致，全部为原创来源，保留 1.0.0 的题目 ID）和学生预览（12 组、29 项技能，无答案键）；批准（`licenseAttested`）并激活：1.0.0 → `superseded`，目录显示 2.0.0 描述。Beth 在授权前选课 403 `COURSE_ACCESS_REQUIRED`；管理员直接在 `students/stu_beth/access/current` 的 `courses` 中加入 `dsat`（尚无管理工具）后选课 200，得到 2.0.0 的两个起始任务；代数组按答案键评分 5/5，Session 完成，掌握度记录在 5 项代数技能上。已选课的 Alex 没有得到新题组的任务（已知平台缺口）。所有题目仍为 `draft`，生产环境前需内容审核 |
| Digital SAT 学习演示：提示看到题目 + 练习补充（2.0.1） | ✅ 已运行（2026-11-07） | 部署 `16df5a5-dirty-20261107b`（`hsos-worker-00009-8k9`、`hsos-api-00008-fkg`），先 `make check`（633 通过）与 `make test-emulator`（8/8）。作者上传 2.0.1（只新增 `practiceSequence`，36/36），审核员在预览中看到练习顺序（2 个起始 + 10 个后续）后批准并激活，2.0.0 → `superseded`。Beth 在信息与观点组问第 3 题：导师（OpenAI）直接针对该题给提示（之前会让学生粘贴题目），被追问“是不是 C”时仍拒绝确认；提交（第 4 题错）→ 按答案键 [1,1,1,0,1] 和逐题反馈；完成后立即得到顺序中的下两组（她已无未完成任务，补到 2 个）；技巧与结构组在提示后 5/5，记为有提示（非独立证据）。计划只列出 Digital SAT：她唯一的 Calc 任务是 11-02 开始的进行中任务，早于计划窗口，不列出（现有规则）。Alex（2.0.0 之前注册）完成旧组后得到 2.0.1 顺序中第一组新题（信息与观点）。作者指标因少于 5 名学生而隐藏。预测仍为 `unavailable` |
| Step 32.5 跨学生隔离 | ✅ 已运行（2026-11-07） | Beth 读 Alex 的 Session、消息、提交、评估、Run、Task 均 404；评估列表为空；向 Alex 的 Session 发消息、开始 Alex 的 Task 均 404；Beth 的事件只含 Beth；`studentId` 查询参数 400；SSE 的 URL token 401；作者读学生数据 403。**未运行**：文件（未实现） |
| Step 32.6 无重复进度、状态真实 | ✅ 已运行（2026-11-07） | 同 key 同 body → 同一 runId；同 key 不同 body → 409 `IDEMPOTENCY_CONFLICT`；Run 进行中新命令 → 409 `RUN_IN_PROGRESS`；只新增一条评估；模糊答案（真实模型）→ `insufficient_evidence`；没有接受的评估时 `complete` → 409 `COMPLETION_REQUIREMENTS_NOT_MET` |
| 部署中发现并修复的问题 | ✅ | 缺 7 个 Firestore 复合索引（内存存储与模拟器都不检查索引，只有真实 Firestore 会报 `FailedPrecondition`）；API 无密钥时 OpenAI SDK 构造即失败（改为首次调用时创建）；provision.sh 三处问题（worker 首次部署前需要自身 URL、桶“已拥有”提示未识别、告警策略需要 gcloud alpha，改用 REST）。已加 `server/.gcloudignore`，确保 `.env` 不会上传 |
| Step 32.4 worker 中途修订版切换 | ✅ 已运行（2026-11-07） | 评分 Run 处于 RUNNING 时更新 worker 修订版：Cloud Run 让进行中的请求跑完，Run 一次成功（attempt 1），一条评估，`run.queued`/`run.completed` 各一次。这不是崩溃：Cloud Run 没有杀掉单个实例的接口 |
| Step 32.4 worker 崩溃恢复 | ✅ 已运行（2026-11-07） | 模拟“取得租约后进程死亡且队列任务丢失”：暂停队列 → Beth 提交 → 把 Run 改为 RUNNING、租约已过期、持有者 `worker-crashed-step32` → 删除队列里的任务 → 恢复队列。`hsos-run-recovery`（Scheduler）重新入队，worker 接管：89 s 后 `SUCCEEDED`（attempt 2），一条评估，`run.completed` 一次，序号单调。（没有 `run.started`：模拟的崩溃跳过了真实租约写入的那条事件，接管只在 QUEUED 时发出它） |
| Cloud Run 超时 | ❌ 未运行 | 没有制造超过 dispatch deadline 的模型调用 |
| Firestore 模拟器测试（含新增备份测试） | ✅ 已运行（2026-11-05） | `make test-emulator`（openjdk 21）：8/8 通过——评估原子提交、备份、消费者效果 + 回执 + 偏移同一事务且重放无副作用、PLANNING 原子提交、核心流程、种子。首次运行时消费者测试失败：它写于 M3，假定只有测试用 `ProbeConsumer`，而 M5 的 `course-metrics` 默认注册，产生第二条回执（模拟器 harness 不像 contract harness 那样关闭它）。修正为只按 `PROBE` 取回执，并断言 `course-metrics` 在同一事件上各自记账、重放不增加回执 |
| 托管备份恢复演练 | ❌ 未运行 | 需要 staging |
| 告警策略实际触发 | ❌ 未运行 | 两条策略已创建并启用；需在 staging 制造一次积压确认通知送达 |
| staging 与 `main` 的差距 | ⚠️ 未部署（核对于 2026-11-10） | 最近一次记录的 staging 部署是 `16df5a5-dirty-20261107b`。之后的提交都只在本地验证：审核界面（Step 41，`9ab930f`）、课程发布政策（管理员发布给所有学生，`ea70fce`）、能力注册表（Step 44，`d5daea8`）、删除按学生授权的代码（`dee041a`）。上面 2026-11-07 的记录中“审核员激活”“管理员授权后选课”“403 `COURSE_ACCESS_REQUIRED`”描述的是旧政策。重新部署后需按 [examples/DIGITAL_SAT_WALKTHROUGH.md](examples/DIGITAL_SAT_WALKTHROUGH.md) 在 staging 再跑一次发布流程 |
| 已知风险 | ⚠️ | 2026-11-03 开启邮箱登录时，Identity Toolkit 返回的密码哈希 `signerKey` 被打印进一次会话记录（未提交到仓库）。项目只有合成用户；将其视为仅测试用项目，引入真实用户前先评估轮换方式 |

### Step 32 清单（staging 部署后执行）

1. 32.1 Calc BC 完整学习链（真实模型）。
2. 32.2 Digital SAT 与 Calc BC 并行；课程内后续规则（Step 24.2）尚未实现，该部分目前无法执行。
3. 32.2a 作者路径：上传 → 报告 → 审核 → 激活 → 有打开 Session 时升级版本。
4. 32.3 SSE 跨 Cloud Run 实例重连（缩放到 ≥2 实例，断开后带 `Last-Event-ID` 续接）。
5. 32.4 worker 崩溃恢复：执行中删除实例 / 部署新修订版，确认租约过期后恢复且没有重复评估。
6. 32.5 跨学生隔离：Session、事件、评估（文件尚未实现）。
7. 32.6 没有重复进度、重启恢复、失败/等待状态真实。
8. 定时计划与提醒：测试学生在其本地 04:00 得到计划，16:00 收到（fake 渠道）提醒；退订后不再发送。
