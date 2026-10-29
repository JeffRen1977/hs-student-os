# High School Student OS — 实施计划 v2.0

更新：2026-10-29。采纳 [架构建议](STUDENT_OS_ARCHITECTURE_RECOMMENDATIONS.md)，替代 v1.0 的 M0–M5 排期。目标设计见 [产品方案](HIGH_SCHOOL_STUDENT_OS.md)、[BACKEND.md](BACKEND.md) v0.3、[API.md](API.md) v0.2；逐步操作见 [STEP_BY_STEP_PLAN.md](STEP_BY_STEP_PLAN.md)。

本次只更新文档，未验证或修改应用实现。此前关于 `web/` 已完成、`server/` 已有骨架的描述属于历史记录，M0 必须核对当前 checkout。下面的工作项均是待实施目标，不标记为已完成。

## 0. 工程边界与交付规则

### 0.1 独立实现与参考边界

- 实现根目录为当前 Student OS 工程根（包含本 `doc/` 的工程），不硬编码另一台机器的个人目录。只有文档的副本不能假定已存在 server/web 实现。
- `ai-college-advisor`、`sat-tutor-app` 只读参考；不在参考目录安装、编辑、迁移或提交。Student OS 不通过路径、软链接、本地端口、共享 JWT 密钥或数据库依赖它们。
- **不复制或改造任何 LOGIQ 代码，不使用 LOGIQ 服务或凭证。** 只参考通用任务、会话、工具与事件架构，独立定义 Student OS API。
- 其他参考能力如需引入，先盘点来源、许可、依赖和适配成本；只按边界引入可独立测试的领域能力，不搬迁整套身份/存储/UI。不得复制秘密、用户数据、生产日志或受限题库。
- 外部互通与参考仓库的修改是后续独立任务；本工程移除参考目录后仍应能独立登录、构建、测试和运行。

### 0.2 数据与交付约束

- 每个切片包含前后端契约、正常/失败路径、幂等、恢复和适用的学生隔离测试；跨域链在 M3 加入，不要求 M0 就实现所有功能。
- Task、Session、Run、Submission、Assessment 分开；共享学生记录是逻辑视图，不能在每个 Agent 内复制第二份权威状态。
- 评分由后端证据评估决定；没有客户端 score delta 或任意领域事件写入。entitlements 后台管理。
- 使用支持中的 Node.js LTS + TypeScript + Fastify + Ajv，Firestore/Auth emulator 从基础阶段使用，JSON 仅为 fixture/demo。
- 契约、迁移和测试先行。旧 demo 预测不能迁成真实成绩；对需保留数据先备份并提供可逆导入方案。
- 模块清晰但不为“可扩展”先建复杂通用框架。一个共享运行时与少量已验证内容包即可。
- 日志记录状态、延迟、tokens、模型版本和错误，不记录完整学生作答、文书或凭证。
- 前端优先保持 provider/store 边界；必要的状态/组件改动正常审查，不以“最多改三个文件”替代功能正确性。

## 1. 统一里程碑

首个产品闭环：**Calculus 练习 → 有依据的反馈 → 学生记录 → SAT 前置技能诊断 → 有证据的补强 → 可解释计划**。

| 里程碑 | 内容 | 退出标准 | 步骤 |
|---|---|---|---|
| M0 契约与基线 | 核对工程、schema、合成数据、评估夹具 | 代码状态有记录，接口/内容契约可验证 | 1–5 |
| M1 可靠基础 | 独立身份、隔离、Firestore、Task/Session/Run、队列 | 模拟执行可刷新/重启恢复，重复命令不重复生效 | 6–10 |
| M2 Calculus 学习闭环 | 模型/技能、评估事务、真实反馈、事件与恢复 | 审阅例题反馈有证据，失败不写进度 | 11–15 |
| M3 SAT 跨域验证 | 映射、短诊断、消费者、计划增量更新 | 诊断确认后才补强，未支持不误推荐 | 16–20 |
| M4 主动规划与试点 | 时区调度、提醒、云部署、质量与运维验证 | 外部试点可用，可靠性和学习质量均过门槛 | 21–25 |
| M5 覆盖扩展 | APUSH 等课程、申请/家长、校准与可选优化 | 每项扩展单独通过内容、权限和质量验收 | 26–30 |

M0–M4 是本轮核心范围；M5 是按试点证据排序的后续工作，不作为首发必需。旧“29 个有效开发日”估计不沿用：身份/恢复提前且评分合同变化，需要 M0 核对代码和内容投入后按切片估时。内容审阅与实施并行，不能算作已由工程时间覆盖。

## 2. M0：契约与基线

- [ ] 盘点 server/web 当前状态、可复用边界、旧 API 调用和未提交工作；不删除未知代码。
- [ ] 建 TypeScript/Fastify/Ajv 骨架、受支持 Node LTS 声明、依赖锁定、环境示例与本地开发说明。
- [ ] 以 API v0.2 建 JSON Schema：Task、Session、Run、Submission、Assessment、事件、字段白名单和错误码。
- [ ] 两名合成学生独立 studentId；默认 prediction unavailable；entitlements 与 selectedCourses 分开。
- [ ] calc_bc 为唯一初始 active AP 包；建立版本化原创题、rubric、提示例与候选 SAT 映射评估夹具。其他课程 planned。

**验收：** schema 拒绝 scoreDelta、客户端权威事件、entitlement 修改；种子无真实学生信息；客户端和领域字段一致；迁移清单明确废弃接口。本阶段不需要 Jev key、MCP server 或真实外部产品账号。

## 3. M1：可靠基础

- [ ] Student OS 独立 Firebase Auth；本地 Auth emulator；服务端验证 token 与 studentId 映射。
- [ ] Firestore repository 与两学生隔离；学生字段白名单、entitlements 管理、版本冲突与权限规则。
- [ ] 持久 Task/Session/Run，Task 最多一个 OPEN Session，Session 最多一个非终态 Run；刷新恢复与用户取消。
- [ ] 命令/Run/idempotency/outbox 同事务；Cloud Tasks adapter、本地重复投递队列、worker 租约和 fencing token。
- [ ] provider/store 接 API，显示 queued/running/failed/waiting 状态；demo 明确开启，线上错误不回退为假学生数据。

**验收：** 两学生无法互读资源；相同幂等键返回同一 Run；重启恢复待处理任务；队列重复投递不重复提交；取消和旧租约 worker 不会覆盖终态。模拟输出明确标注，仅用于内部链路，不伪装成真实评估。

## 4. M2：Calculus 学习闭环

- [ ] `LLMGateway` + 静态 ModelRouter；限次重试、Run/Session/每日预算、模型/工作流版本日志。
- [ ] 苏格拉底提示和 calc_bc rubric 评估；小规模审阅语料检索、必要数学核验；提示与独立作答分别计证据。
- [ ] `AssessmentService.commitAssessment()` 事务保存 assessment、mastery、Run 终态、事件/outbox；证据不足不改掌握度。
- [ ] `completeSession()` 依据已保存评估和任务条件关闭 Session/Task；重复完成不重新应用证据。
- [ ] SSE + 轮询共享持久事件序列；恢复与当前状态同步；先完成文本作答再加入上传/OCR，低可信识别由学生确认。

**验收：** 审阅答案、错误答案、提示后订正、材料缺失、OCR 歧义各有样例；输出引用实际题目/rubric；schema 合法但证据错误的输出被拒；数据库事务注入失败不留下部分进度。界面展示评估与证据覆盖，预测仍 unavailable。

## 5. M3：SAT 跨域验证

- [ ] 内容人员审阅 AP→SAT 共享前置技能映射，记录版本、证据要求和反例。
- [ ] AP 结果仅产生 prerequisite.suspected，提供短诊断，而非直接认定 SAT 弱点。
- [ ] DSAT 短诊断使用已审题目、独立作答与同一 AssessmentService；不从几道题换算 SAT 分数。
- [ ] confirmed 才生成补强，unsupported/证据不足不生成；事件消费者收据与任务创建同事务去重。
- [ ] Planner 增量更新仅改变未来未锁定任务，遵守小时预算并展示来源解释。

**验收链：** AP 候选 → SAT 诊断 → 支持/不支持两种结果；重复事件只生成一项对应任务；学生已无时间时可延后建议而不超配；推导类 AP 失误但前置技能正确时不推不相关练习。

## 6. M4：主动规划与外部试点

- [ ] Cloud Scheduler 触发 dueAt 扫描，按 IANA timezone/localDate 去重，覆盖夏令时与学生修改时区。
- [ ] 每周预算、延后/跳过/锁定和重排解释；与 Run/Session 状态一致。
- [ ] 选择一个提醒渠道，显式 opt-in、安静时段、频控、发送前复核同意；不默认通知家长。
- [ ] Cloud Run API/worker、Firestore、Cloud Tasks OIDC、Storage、Secret Manager 部署；备份与恢复演练、失败告警和用量指标。
- [ ] staging 检查云队列期限、worker 恢复、SSE 重连、文件归属；外部学生登录与隔离从 M1 继承验证。
- [ ] 人工评估集与试点指标过门槛，再允许真实学生使用；未达到内容质量时缩小范围，不用模拟结果补齐。

**验收：** 完整 M0–M3 链在 staging 通过；断线/重复任务/worker 崩溃不丢作答或重复增益；学生能理解为何安排后续任务；提醒可撤销；数据库和文件恢复可执行。上线前测试学生 A 对 B 的 Session、事件、文件及检索访问全部拒绝。

## 7. M5：按证据扩展

以下不是同一上线包，每项单独选取和验收：

- [ ] APUSH 优先扩展 rubric 与语料；随后 Physics C、CSA、AP Lang。新增内容类型必要时增加工具/画布，不承诺仅改 manifest。
- [ ] Admissions 访谈、大纲、活动事实确认与学校资料来源管线；不因内部 AP 估计自动调整选校分档。
- [ ] 家长 summary:read 授权和撤销；默认不开放私有对话/文书；顾问协作另立权限。
- [ ] 扩大 MCQ/FRQ/模考内容与覆盖后，用独立持出数据校准 mastery/考试预测；未过门槛不展示预测分或“官方式”评分。
- [ ] 有明确收益再评估 Jev、MCP、Temporal、向量检索或额外模型。验证真实接口、成本、隐私和质量，无依赖时核心流程照常。

## 8. 内容与质量轨

内容工作从 M0 开始，先覆盖 Calculus 小范围题型及一个共享 SAT 技能，不铺五科题库。题目、rubric、映射和测试答案均保留来源、权限、版本与审核人。

| 检查 | 记录与退出依据 |
|---|---|
| Rubric 评分一致性 | 与独立人工评分逐采分点比较，登记分歧与适用范围 |
| 反馈证据 | 引用实际答案/材料，无支持则弃权；评估错误接受率 |
| 提示依赖 | 有提示和无提示表现分开；订正不当作全新独立证据 |
| 跨域推荐 | confirmed/unsupported 标注集检验映射，审阅错误推荐 |
| 学习效果 | 新题独立作答表现、后续任务完成情况，而非聊天长度 |
| 产品理解 | 学生能解释“为何做这项任务”，记录困惑和手动调整 |
| 可靠性与成本 | 重复进度次数必须为零；记录恢复结果、每次有效评估成本 |

内容负责人和工程人员在扩大试点前记录评估集规模、门槛、失败处置与结果。少量烟雾样例不能当作校准证明。文书边界用行为样例评估，不以文件名/关键词扫描代替真实输出检查。

## 9. 迁移与风险处理

| 旧方案/风险 | 当前处理 |
|---|---|
| 合并 Task/Session、内存会话 | 持久分离资源，身份与恢复先实现 |
| 浏览器传分数与任意事件 | 只收命令/作答，服务端验证与事务提交 |
| JSON→Firestore 后期迁移 | 首版 emulator 对接真实事务模型；JSON 保留为 fixture |
| email 连接与外部 JWT 共享 | 自有身份、稳定 studentId，外部映射另行授权 |
| 模拟预测上涨作为验收 | 真实证据反馈与独立题表现；prediction unavailable |
| 五科 + 全 SAT + 申请并行上线 | 先 Calculus + 一个 SAT 前置技能闭环 |
| Jev key 或供应商不可用 | 不在关键路径，静态路由与规则可运行 |
| 工具失败但 UI 显示成功 | failed/insufficient 状态保留，禁止 stub 冒充实测 |
| 云消息重复/请求超时 | outbox、幂等、租约、分步执行与补偿扫描 |

本计划不触发部署、发送提醒或修改参考产品。实现时根据明确里程碑交付；每次验收记录所用代码版本、数据版本与实际检查结果。
