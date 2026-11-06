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
| Cloud Scheduler 作业与 `--ingress internal-and-cloud-load-balancing` 的组合 | 🟡 作业已创建并启用 | 6 个作业 ENABLED；尚未查看它们的执行日志确认调用成功 |
| 部署中发现并修复的问题 | ✅ | 缺 7 个 Firestore 复合索引（内存存储与模拟器都不检查索引，只有真实 Firestore 会报 `FailedPrecondition`）；API 无密钥时 OpenAI SDK 构造即失败（改为首次调用时创建）；provision.sh 三处问题（worker 首次部署前需要自身 URL、桶“已拥有”提示未识别、告警策略需要 gcloud alpha，改用 REST）。已加 `server/.gcloudignore`，确保 `.env` 不会上传 |
| 跨实例恢复、SSE 跨实例重连、Cloud Run 超时 | ❌ 未运行 | Step 32.3–32.4 |
| Firestore 模拟器测试（含新增备份测试） | ❌ 未运行 | 本机现已安装 Java（2026-11-03），但 `make test-emulator` 还没有运行 |
| 托管备份恢复演练 | ❌ 未运行 | 需要 staging |
| 告警策略实际触发 | ❌ 未运行 | 两条策略已创建并启用；需在 staging 制造一次积压确认通知送达 |
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
