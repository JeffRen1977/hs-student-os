# High School Student OS — API 契约 v0.2

更新：2026-10-29。根据 [架构建议](STUDENT_OS_ARCHITECTURE_RECOMMENDATIONS.md) 重订接口，替代 v0.1；旧接口迁移见第 7 节。本文为目标契约，尚未声明已实现。后端设计见 [BACKEND.md](BACKEND.md)。

## 0. 通用约定

- Base path：`/api`；本地 API 默认 `http://localhost:8787`。REST/JSON，不要求兼容任何外部 agent SDK。
- `Authorization: Bearer <Student OS ID token>`；服务端验证身份并确定 studentId。生产不接受 `X-User-Email`。本地使用明确配置的 Auth emulator。
- 时间为 UTC ISO 8601；日程另存 IANA timezone 和 localDate。所有资源 ID 均为不透明字符串。
- 所有数据按授权 studentId 隔离。跨学生资源返回 404；归属校验先于内容处理。当前学生端不得传任意 studentId 改变作用域。
- 创建/命令 POST 必须带 `Idempotency-Key`。同 key + 相同规范化请求返回原资源和原结果；同 key 不同 body 返回 `409 IDEMPOTENCY_CONFLICT`。响应可带 `Idempotency-Replayed: true`。
- 修改 profile/goals/preferences 或重排任务使用 `If-Match: "<version>"`。版本过期返回 409，缺少必要前置条件返回 428。
- 请求对象拒绝未知字段；读集合均分页，`limit` 默认 50、最大 100，返回 nextCursor（事件采用 after sequence）。
- 未登录 401；归属内权限不足 403；不存在 404；参数错误 400；状态/版本冲突 409；游标过期 410；预算/频控 429；暂不可用 503。

```json
{
  "error": {
    "code": "RUN_IN_PROGRESS",
    "message": "A run is already active in this session.",
    "requestId": "req_01",
    "retryable": false
  }
}
```

## 1. 核心资源

### 1.1 Twin 摘要与访问权限

`GET /api/twin` 返回当前学生的有界摘要，响应带 ETag；email 仅作联系方式，不作为资源键。

```json
{
  "studentId": "stu_alex",
  "version": 3,
  "profile": {"displayName": "Alex", "grade": 11, "targetMajor": "CS"},
  "goals": {"satTarget": 1550, "apTargets": {"calc_bc": 5}},
  "preferences": {
    "timezone": "America/Los_Angeles",
    "weeklyAvailableMinutes": 300,
    "selectedCourses": ["calc_bc"],
    "notifications": {"enabled": false, "channels": [], "quietHours": {"start": "21:00", "end": "08:00"}}
  },
  "masterySummary": {
    "calc_bc.function-composition": {"level": "insufficient_evidence", "independentEvidenceCount": 0}
  },
  "predictionSummary": {"calc_bc": {"status": "unavailable", "reason": "not_calibrated"}},
  "latestEventSequence": 18
}
```

`latestEventSequence` 与摘要使用一致读快照，供客户端先加载状态后增量订阅。详细历史由分页 API 读取；不能把所有学生历史塞入 Twin 响应。

`GET /api/me/entitlements` 返回后端管理的权限：

```json
{"apCourses": ["calc_bc"], "dsat": true, "admissions": false}
```

`PATCH /api/twin` 仅允许明确列出的叶字段：profile.displayName/grade/school/targetMajor/targetSchools、goals.satTarget/apTargets、preferences.timezone/weeklyAvailableMinutes/selectedCourses/notifications。每个字段有范围和格式校验，不能任意追加子树。

禁止写入 studentId、entitlements、mastery、assessments、predictionSummary、version；email 更新走身份提供方的验证流程。旧 `subscriptions` 字段不再接受。后台人工开通使用独立管理员工具，不暴露学生可调用的 entitlement 写接口。

### 1.2 Agent / SubjectPack

`GET /api/agents`、`GET /api/packs`、`GET /api/packs/{courseId}` 返回产品能力摘要，不暴露内部工具服务地址或私有检索索引。

```json
{
  "courseId": "calc_bc",
  "name": "AP Calculus BC",
  "version": "1.0.0",
  "availability": "active",
  "supportedTaskTypes": ["SOCRATIC_STUDY", "FRQ_PRACTICE"],
  "supportedModes": ["GPA_SYNC", "EXAM_CRUNCH"]
}
```

首发 calc_bc active；其他已列出但尚未验证的课程为 planned。未知 courseId 为 404；对 planned 课程创建任务/Session 为 409 `COURSE_NOT_AVAILABLE`。active 课程无 entitlement 为 403 `COURSE_ACCESS_REQUIRED`。

### 1.3 Task

```json
{
  "taskId": "task_calc_01",
  "studentId": "stu_alex",
  "agent": "AP_BASE",
  "courseId": "calc_bc",
  "taskType": "FRQ_PRACTICE",
  "mode": "GPA_SYNC",
  "title": "Explain the function composition in this problem",
  "durationMin": 20,
  "scheduledDate": "2026-10-29",
  "status": "PLANNED",
  "version": 1,
  "reason": {"code": "INITIAL_PRACTICE", "sourceEventIds": []}
}
```

Task 状态：PLANNED、IN_PROGRESS、COMPLETED、SKIPPED。学生不能直接 PATCH 为 COMPLETED；完成由 Session 完成规则决定。

### 1.4 Session 与 Run

```json
{
  "sessionId": "sess_01",
  "taskId": "task_calc_01",
  "status": "OPEN",
  "activeRunId": null,
  "contextVersion": {"pack": "1.0.0", "workflow": "calc-practice-v1"},
  "completion": {"eligible": false, "reason": "accepted_assessment_required"}
}
```

```json
{
  "runId": "run_01",
  "sessionId": "sess_01",
  "status": "QUEUED",
  "kind": "ASSESS_SUBMISSION",
  "submissionId": "sub_01",
  "attemptCount": 0,
  "inputRequest": null,
  "result": null
}
```

Session：OPEN、COMPLETED、ABANDONED。Run：QUEUED、RUNNING、WAITING_INPUT、SUCCEEDED、FAILED、CANCELLED。一个 Session 多次 Run；一个 Task 多次 Session 尝试。首版每个 Task 最多一个 OPEN Session、每个 Session 最多一个非终态 Run。学生范围的 PLANNING Run 可无 Session，此时 sessionId 为 null；它按计划版本与来源键去重，不占用学习 Session 的执行位置。

### 1.5 Submission / Assessment

学生提交内容，不提交分数、mastery delta、证据可信状态或工具运行结果。

```json
{
  "questionId": "q_calc_01",
  "questionVersion": "1",
  "answer": {"text": "My derivation ...", "fileIds": []},
  "supersedesSubmissionId": null
}
```

服务端核对 question 属于 Session 当前活动。question/rubric 版本来自已发给该 Session 的内容；不能换题绕过任务要求。提示记录取自服务端会话日志，学生可另外自报线下帮助，但不能覆盖系统记录。

```json
{
  "assessmentId": "assess_01",
  "submissionId": "sub_01",
  "sessionId": "sess_01",
  "runId": "run_01",
  "status": "accepted",
  "questionVersion": "1",
  "rubricVersion": "calc-composition-v1",
  "rubricResults": [{"criterionId": "identify-inner-function", "earned": 1, "possible": 1, "evidenceRefs": ["sub_01:text:0-42"]}],
  "hintUsage": {"serverHintCount": 1},
  "skillEvidence": [{"skillId": "calc_bc.function-composition", "observation": "correct_with_hint"}],
  "uncertainty": {"level": "limited", "reasons": ["single_assisted_attempt"]},
  "provenance": {"modelVersion": "configured-model-version", "workflowVersion": "calc-practice-v1", "toolResultIds": []},
  "supersedesAssessmentId": null
}
```

Assessment status 为 accepted 或 insufficient_evidence。后者可显示有限反馈但不更新 mastery，也不满足要求 accepted assessment 的完成规则。Run SUCCEEDED 只代表执行成功，可包含 insufficient_evidence；前端不能把二者混同。

accepted 也不代表考试预测有效。首版没有对外预测分生成接口；自报/正式考试记录与估计独立保存。

### 1.6 事件

```json
{
  "eventId": "evt_19",
  "sequence": 19,
  "schemaVersion": 1,
  "studentId": "stu_alex",
  "sessionId": "sess_01",
  "runId": "run_01",
  "type": "assessment.completed",
  "occurredAt": "2026-10-29T17:00:00Z",
  "causationId": "sub_01",
  "payload": {"assessmentId": "assess_01", "status": "accepted"}
}
```

无 Session/Run 的 Planner 事件相应字段为 null。sequence 在同一学生范围递增。常见事件：session.started、run.queued、run.started、run.waiting_input、run.completed、run.failed、run.cancelled、assessment.completed、mastery.updated、session.completed、session.abandoned、prerequisite.suspected、prerequisite.confirmed、prerequisite.unsupported、plan.updated。

事件由服务端在事务中创建。客户端不能声明事件来源或伪造结果。UI 只接收脱敏的学生事件，不接收内部 outbox、原始模型推理或敏感工具参数。

## 2. 学习工作流接口

### 2.1 列出任务与学生重排

- `GET /api/tasks?date=2026-10-29&cursor=...&limit=50` → tasks、nextCursor；日期按 preferences.timezone 解释，GET 不触发重新规划。
- `PATCH /api/tasks/{taskId}` + If-Match → 只允许 scheduledDate、studentLocked、status=SKIPPED（仅未开始任务）。
- `POST /api/plans/replan` + Idempotency-Key → 202 返回 PLANNING Run；重排保留进行中、已完成与锁定任务，并返回可解释变更。

### 2.2 创建与恢复 Session

`POST /api/sessions` + Idempotency-Key：

```json
{"taskId": "task_calc_01"}
```

返回 201 与 Session。服务端由 Task 推导 agent、courseId、模式和技能，校验归属、内容可用性与 entitlement，在事务内创建 Session、更新 Task 并发 session.started。请求中不接受 caller 指定任意 tool/namespace/course 覆盖 Task。

已有 OPEN Session 时返回 200 与该 Session；COMPLETED/SKIPPED Task 返回 409 `TASK_NOT_OPEN`，新练习由新任务表达。重复同幂等键返回第一次结果。

- `GET /api/sessions?taskId=...&cursor=...`：列出本学生的尝试，供刷新恢复。
- `GET /api/sessions/{sessionId}`：Session 当前状态、活动内容摘要与 completion eligibility。
- `GET /api/sessions/{sessionId}/messages?cursor=...`：持久对话，按分页顺序返回。
- `GET /api/sessions/{sessionId}/submissions?cursor=...`：该 Session 的不可变作答版本与 Run/Assessment 引用。
- `GET /api/submissions/{submissionId}`：归属校验后读取原始作答、内容版本和文件引用，支持反馈证据回看。

### 2.3 发消息与提交作答

`POST /api/sessions/{sessionId}/messages` + Idempotency-Key：

```json
{"text": "Can you help me identify the inner function?", "fileIds": []}
```

返回 202：

```json
{"messageId": "msg_01", "runId": "run_hint_01", "status": "QUEUED"}
```

提示 Run 的回复与使用量持久保存；提示成功不写入“独立答对”证据。

`POST /api/sessions/{sessionId}/submissions` + Idempotency-Key，body 见 1.5；返回 202：

```json
{"submissionId": "sub_01", "runId": "run_01", "status": "QUEUED"}
```

Submission、Run、幂等记录与 outbox 原子保存。不同请求竞争同一 Session 活跃 Run 返回 409；重复原请求先查幂等记录。Run 结束后提交订正生成新的不可变 Submission。

### 2.4 Run 状态、补充输入和取消

- `GET /api/runs/{runId}` → 当前状态、结果引用、安全错误码；SUCCEEDED result 包含 messageId/assessmentId 等适用字段。
- `POST /api/runs/{runId}/input` + Idempotency-Key → 仅 WAITING_INPUT 接受匹配的请求，事务保存核对内容与 outbox，返回 202、同一 Run ID、QUEUED。

```json
{"inputRequestId": "input_ocr_01", "value": {"confirmedText": "f(g(x))"}}
```

inputRequest 定义服务端允许的 schema；不能用该入口注入评估结果、tool confirmation 或新的学生身份。OCR 核对保存为附加证据版本，不覆盖原始图片/提交。

- `POST /api/runs/{runId}/cancel` + Idempotency-Key、空对象 body → 活跃 Run 标记 cancelRequested，返回 202；重复取消返回当前结果。已 CANCELLED 返回 200；已 SUCCEEDED/FAILED 返回 409 `RUN_TERMINAL`。worker 检查取消并持久化 CANCELLED；中止事件前不把任务显示为已取消。

### 2.5 完成或放弃 Session

- `POST /api/sessions/{sessionId}/complete` + Idempotency-Key、`{}` → 校验无活跃 Run且满足服务端 Task 完成规则，事务写 Session=COMPLETED、Task=COMPLETED 和事件；返回 200。
- 已完成同一 Session 再次 complete 返回现有结果；有活跃 Run 返回 409 `RUN_IN_PROGRESS`；证据不足返回 409 `COMPLETION_REQUIREMENTS_NOT_MET`。
- `POST /api/sessions/{sessionId}/abandon` + Idempotency-Key、`{}` → 无活跃 Run 时 Session=ABANDONED，未完成 Task 回到 PLANNED；活跃 Run 须先取消。完成后的 Session 不可 abandon。

完成/放弃不重新累计 mastery。结果评估和学生结束会话是不同动作。

### 2.6 读取评估与掌握度

- `GET /api/assessments/{assessmentId}` → 1.5 结果，校验归属。
- `GET /api/assessments?sessionId=...&cursor=...` → 评估历史与 supersedes 关系。
- `GET /api/mastery?courseId=calc_bc&cursor=...` → 技能状态、证据数量、覆盖度、不确定性与更新时间；无证据返回 insufficient_evidence。

模型内部重评为新 Assessment 版本，由受控后台流程执行。重评替换同一证据贡献，不向公开 API 暴露任意 mastery 写入。

## 3. 文件接口

文件能力在文本闭环后交付，未启用时客户端不展示可用上传能力。

1. `POST /api/files` + Idempotency-Key，body `{ "sessionId": "sess_01", "name": "answer.png", "contentType": "image/png", "sizeBytes": 12345 }` → 201，fileId、短期受限上传 URL、expiresAt、status=UPLOADING。
2. 上传后 `POST /api/files/{fileId}/complete` + Idempotency-Key → 202，status=VALIDATING。服务端核对对象大小、类型、归属及内容处理结果，必要时排队检查。
3. `GET /api/files/{fileId}` → READY/REJECTED 等状态；学生只能提交 READY 文件，未就绪返回 409 `FILE_NOT_READY`。
4. `GET /api/files/{fileId}/download` → 校验归属/角色后返回短期下载 URL，不持久公开对象。

初版限制由文件策略配置明确，上传接口需校验实际内容而非仅信任扩展名。跨 Session/学生引用须重新核验权限，不能接受任意对象路径。上传 URL 过期后 `POST /api/files/{fileId}/upload-url` + Idempotency-Key、`{}` 可对归属内且仍为 UPLOADING 的文件重新签发；READY/REJECTED 文件返回 409，不允许重签覆盖已用于评估的内容。

## 4. 事件与实时连接

`GET /api/events?after=18&limit=50` 返回按 sequence 升序的事件投影：

```json
{"events": [], "nextAfter": 18, "hasMore": false}
```

`GET /api/events/stream?after=18` 提供 SSE，示例：

```text
id: 19
event: assessment.completed
data: {"eventId":"evt_19","sequence":19,"schemaVersion":1,"studentId":"stu_alex","sessionId":"sess_01","runId":"run_01","type":"assessment.completed","occurredAt":"2026-10-29T17:00:00Z","causationId":"sub_01","payload":{"assessmentId":"assess_01","status":"accepted"}}

```

SSE id 使用学生范围的 sequence。重连优先采用有效 Last-Event-ID，否则用 after；若同时提供且不一致，返回 400。先重放持久事件，再持续发送；客户端按 eventId/sequence 去重并保存最后成功应用位置。

浏览器使用带 Authorization header 的 fetch streaming；不把认证 token 放入 query。服务端心跳、请求时限前重连与权限过期处理都必须实现。无法 streaming 时轮询同一事件源。

事件被清理而 cursor 过旧时返回 410 `EVENT_CURSOR_EXPIRED`，重新获取 Twin/Task/Session 状态快照并从快照 sequence 续接。客户端先存储事件，再按最新资源状态渲染，避免倒退。没有公开事件 POST；消息、作答、取消均有自己的命令端点。

## 5. 前端接入与权限投影

启动先认证，再并行获取 Twin、entitlements、packs、tasks。恢复已有 Session 和 Run；状态与事件均以后端为准。API 失败显示真实错误/重试，不自动切换合成学生数据。

离线演示只在显式 demo 模式使用 fixtures，明显标识，与真实身份/存储分开。输入草稿可保存在本地，发送前告知状态；不得声称已保存或已评估。断线重试使用同一 Idempotency-Key。

家长/顾问 API、外部 context 导出和自动预测分均不属于 M0–M4 公开 API。后续扩展需单独定义 summary 权限、撤销、来源与版本，不直接开放 GET twin 全量给家长。

## 6. 内部服务契约

以下只对服务身份开放，不属于学生 SDK：

- Run 执行、outbox 派发、超时回收和消费者重放。
- 定时日程扫描、通知派发与后台 entitlement 配置。
- `commitAssessment()`、`completeSession()` 的事务实现。

内部路径也校验 OIDC/IAM、受众与请求 schema。队列不是认证替代。运维日志、queue delivery payload 与学生事件分别存储。

## 7. v0.1 → v0.2 迁移与验收

| 旧设计 | 新契约 |
|---|---|
| email / `X-User-Email` 作为身份 | 已验证 ID token → 稳定 studentId；本地 Auth emulator |
| PATCH subscriptions | PATCH selectedCourses 仅改偏好；后台 entitlements 控制权限 |
| Task 与 Session 同记录 | Task、Session、Run 独立持久资源 |
| POST /api/ap/session/start、/api/session/start | POST /api/sessions，由 Task 推导课程 |
| POST /api/session/{id}/settle 接受 outcome/scoreDelta | POST /api/sessions/{id}/submissions；服务端评估；完成另用 complete |
| POST /api/twin/events | 移除；类型化命令触发服务端事件 |
| GET /api/twin/events | GET /api/events 与 /api/events/stream，支持 replay |
| AP prediction 4.5→4.8 | 证据/掌握度展示；prediction unavailable，等待校准 |
| 参考应用 JWT 共享与 context API | 独立身份，外部集成延后定义 |

这些是破坏性契约调整；同一实现切片内更新前端 provider 与后端。旧路径不应静默接受后忽略加分字段；开发版本应清晰返回 410 `API_CONTRACT_REPLACED` 或在尚未实现时 404。旧演示数据不能自动迁成真实成绩。

验收必须覆盖：两学生隔离、禁止越权字段、Task/Session/Run 归属、重试原结果、幂等冲突、同 Session 并发、accepted/insufficient 分支、取消竞态、完成不重复加进度、事件回放与过期 cursor。实施顺序见 [STEP_BY_STEP_PLAN.md](STEP_BY_STEP_PLAN.md)。
