# High School Student OS — API 契约 v0.3

更新：2026-11-04：M5 扩展（§6.5）：作者门户预览与课程聚合指标、平台能力 `source-analysis`（Session `activity.sources`）、家长链接与摘要、申请工作区（新增 Run 类型 `ADMISSIONS_FACTS`/`ADMISSIONS_FEEDBACK` 与 `subjectId`）、预测门控；新增错误码 `PARENT_LINK_LIMIT`、`ADMISSIONS_ACCESS_REQUIRED`、`FACTS_NOT_CONFIRMED`。2026-11-01：M3 改为课程平台，移除跨课程前置技能接口与事件，新增 `PRACTICE` 任务类型（§6.2）。2026-10-31：M2 实现补充：评估/掌握度/完成/事件流接口与字段（标注 “M2”，见 §1.4、§1.5、§2.6、§4、§8）。M1 实现补充：`COURSE_NOT_ENROLLED`、目录 `status`/`agent` 字段、消息资源、身份映射与 `date=today`（标注 “M1”）。2026-10-30 增加课程目录与注册 API（§1.7）。根据 [架构建议](STUDENT_OS_ARCHITECTURE_RECOMMENDATIONS.md) 重订接口，替代 v0.1；旧接口迁移见第 7 节。本文为目标契约，尚未声明已实现。后端设计见 [BACKEND.md](BACKEND.md)。

## 0. 通用约定

- Base path：`/api`；本地 API 默认 `http://localhost:8787`。REST/JSON，不要求兼容任何外部 agent SDK。
- `Authorization: Bearer <Student OS ID token>`；服务端验证身份并确定 studentId。生产不接受 `X-User-Email`。本地使用明确配置的 Auth emulator。
- M1：携带 `X-User-Email`/`X-Student-Id`/`X-User-Id` 头或 `studentId`/`email` 查询参数的请求一律 400（不静默忽略）。已验证 uid 经 `identities/{uid}` 映射到 studentId；已开通学生首次登录时记录映射（uid = studentId）。未开通账号 403，不自动创建学生。emulator 模式下 SDK 不校验有效期，服务端另行校验 exp/iat/aud/iss。
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
{"apCourses": ["calc_bc"], "courses": ["dsat"], "admissions": false}
```

访问按 courseId 授予：AP 课程在 `apCourses`，其他课程在 `courses`（2026-11-01 起取代 v0.3 的 `dsat` 布尔值）。课程包的 category 只是目录标签，不授予访问权限。

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

M2：Session 另含 `activity`（`{questionId, questionVersion, topic, prompt}`，开始时固定的题目版本）与 `hintCount`（服务端已发出的提示次数）。Task 可带 `questionId`。Session 打开后提交的 questionId 必须与 activity 一致（否则 400）；pack/题目版本在 Session 期间变化时 Run 以 `CONTENT_VERSION_CHANGED` 失败，不静默换版本。

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

M2：Assessment 另含 `questionId`、`rubricId`、`feedback`（学生可见反馈；insufficient_evidence 时截短为有限反馈）、`createdAt`；`rubricResults[].assessable`（false 表示该项只因前面的错误而失分或未作答，不能单独评估，得分必为 0，且不产生技能证据）。`skillEvidence` 与 `hintUsage` 由服务端从 rubric 与服务端提示记录推导，模型和客户端都不能提供；有提示或在反馈后订正的作答一律不记为 `correct_independent`。

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

无 Session/Run 的 Planner 事件相应字段为 null。sequence 在同一学生范围递增。常见事件：session.started、run.queued、run.started、run.waiting_input、run.completed、run.failed、run.cancelled、assessment.completed、mastery.updated、session.completed、session.abandoned、plan.updated、course.enrolled、course.unenrolled。

事件由服务端在事务中创建。客户端不能声明事件来源或伪造结果。UI 只接收脱敏的学生事件，不接收内部 outbox、原始模型推理或敏感工具参数。

新增的注册事件：`course.enrolled`、`course.unenrolled`，由注册 API 在事务中生成，可被 Planner 等消费者监听。

### 1.7 课程目录与注册

学生先浏览课程目录，再注册感兴趣的课程。只有注册后的课程才出现在工作台，并激活对应的 per-course agent。注册是 entitlement 检查之上的用户主动行为 —— 有权限不等于已注册。

#### 课程目录

`GET /api/courses/catalog` 返回当前学生可见的全部课程列表：

```json
{
  "courses": [
    {
      "courseId": "calc_bc",
      "name": "AP Calculus BC",
      "description": "Covers limits, derivatives, integrals, and series.",
      "category": "AP",
      "availability": "active",
      "entitled": true,
      "enrolled": true,
      "status": "enrolled",
      "agent": {"agentType": "AP_BASE", "modes": ["GPA_SYNC", "EXAM_CRUNCH"], "supportedTaskTypes": ["SOCRATIC_STUDY", "FRQ_PRACTICE"]}
    },
    {
      "courseId": "apush",
      "name": "AP US History",
      "description": "American history from pre-Columbian era to present.",
      "category": "AP",
      "availability": "planned",
      "entitled": false,
      "enrolled": false,
      "status": "coming_soon",
      "agent": {"agentType": "AP_BASE", "modes": [], "supportedTaskTypes": []}
    }
  ]
}
```

M1：`status` 为派生字段 —— `enrolled`、`available`（active + entitled，未注册）、`locked`（active，无 entitlement）、`coming_soon`（planned）。`GET /api/courses/{courseId}` 返回同结构单条；未知 courseId 404。

可见性规则：

| 状态组合 | 目录可见 | 可注册 | 工作台可见 |
|---|---|---|---|
| active + entitled + enrolled | ✓ | 已注册 | ✓ agent 激活 |
| active + entitled + not enrolled | ✓ | ✓ | ✗ |
| active + not entitled | ✓ (标记 locked) | ✗ 403 | ✗ |
| planned | ✓ (标记 coming soon) | ✗ 409 | ✗ |

#### 注册课程

`POST /api/courses/enroll` + Idempotency-Key：

```json
{"courseId": "calc_bc"}
```

成功返回 200：

```json
{
  "courseId": "calc_bc",
  "enrolledAt": "2026-10-30T08:00:00Z",
  "status": "active"
}
```

服务端在事务中验证：课程 active、学生持有 entitlement、未重复注册。重复注册同一课程幂等返回已有记录。对 planned 课程返回 409 `COURSE_NOT_AVAILABLE`；无 entitlement 返回 403 `COURSE_ACCESS_REQUIRED`。

注册写入 Firestore `students/{studentId}/enrollments/{courseId}`，同时生成 `course.enrolled` 事件。

#### 取消注册

`POST /api/courses/unenroll` + Idempotency-Key：

```json
{"courseId": "calc_bc"}
```

服务端校验无 OPEN Session 后标记 `status: "unenrolled"`、写入 `unenrolledAt`。有未完成 Session 时返回 409 `OPEN_SESSION_EXISTS`，学生须先 abandon 或 complete。

取消注册不删除历史数据（mastery、assessments、submissions），保留审计轨迹。重新注册时恢复已有学习记录。

#### 已注册课程

`GET /api/courses/enrolled` 返回当前学生所有 active 注册：

```json
{
  "enrollments": [
    {
      "courseId": "calc_bc",
      "name": "AP Calculus BC",
      "enrolledAt": "2026-10-30T08:00:00Z",
      "status": "active",
      "agent": {
        "agentType": "AP_BASE",
        "modes": ["GPA_SYNC", "EXAM_CRUNCH"],
        "supportedTaskTypes": ["SOCRATIC_STUDY", "FRQ_PRACTICE"]
      }
    }
  ]
}
```

前端工作台根据此响应渲染侧边栏课程列表。

#### 课程 Agent 入口

`GET /api/courses/{courseId}/agent` 返回该已注册课程的 agent 配置摘要：

```json
{
  "courseId": "calc_bc",
  "agentType": "AP_BASE",
  "name": "AP Calculus BC",
  "modes": ["GPA_SYNC", "EXAM_CRUNCH"],
  "supportedTaskTypes": ["SOCRATIC_STUDY", "FRQ_PRACTICE"],
  "activeSessions": [],
  "masterySummary": {
    "calc_bc.function-composition": {"level": "insufficient_evidence", "independentEvidenceCount": 0}
  }
}
```

未注册该课程返回 404。该端点不暴露内部工具地址、system prompt 或检索索引。

## 2. 学习工作流接口

### 2.1 列出任务与学生重排

- `GET /api/tasks?date=2026-10-29&cursor=...&limit=50` → tasks、nextCursor；日期按 preferences.timezone 解释，GET 不触发重新规划。M1：`date` 可省略（全部）或为 `today`（按学生时区当天）；另支持 `status`、`courseId`；只返回 active 注册课程的任务（取消注册后隐藏、重新注册后恢复）。
- 对未注册课程的 Task/Session/命令操作返回 409 `COURSE_NOT_ENROLLED`（M1 新增错误码）；检查顺序：课程存在（404）→ active（409 `COURSE_NOT_AVAILABLE`）→ entitlement（403 `COURSE_ACCESS_REQUIRED`）→ 注册（409 `COURSE_NOT_ENROLLED`）。
- `PATCH /api/tasks/{taskId}` + If-Match → 只允许 scheduledDate、studentLocked、status=SKIPPED（仅未开始任务）。M3：`skipReason`（`no_time`/`already_know`/`not_relevant`/`other`）只能与 status=SKIPPED 同时出现；改 scheduledDate 默认同时锁定（studentLocked=true），除非同一 patch 显式给出 studentLocked。Task 新增只读字段 `dueDate`、`skipReason`、`reason.explanation`（服务端写的说明，非模型输出）。
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
- `GET /api/sessions/{sessionId}/messages?cursor=...`：持久对话，按分页顺序返回。M1 消息形如 `{"messageId", "sessionId", "role": "student"|"agent", "text", "fileIds", "runId", "createdAt", "synthetic"}`；`synthetic: true` 表示合成执行（测试管线）输出，不是辅导或评分。
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

M2：`GET /api/mastery?courseId=` 返回 `{"mastery": [{skillId, courseId, level, independentEvidenceCount, evidenceCount, coverage, uncertainty, updatedAt, ruleVersion}], "nextCursor"}`，按课程全部技能分页（无证据的技能为 insufficient_evidence）；`GET /api/assessments` 需要 `sessionId`。掌握度规则为未校准的产品规则 `mastery-rules-v2`，不是考试预测；独立证据按题目计数，且只取该题第一次评分的尝试（换个 Session 重做同一题不算新的独立测量）。

模型内部重评为新 Assessment 版本，由受控后台流程执行。重评替换同一证据贡献，不向公开 API 暴露任意 mastery 写入。

## 3. 文件接口

M2：首版试点为纯文本作答，以下文件接口尚未实现，前端没有上传入口（Step 21.4）。

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

M2：流开始前先校验 cursor，所以 400/410 是真正的 HTTP 错误；之后的错误以 `event: error` 帧结束流。流在 `HSOS_SSE_MAX_STREAM_SECONDS`（默认 300 秒）或 token 过期时以注释帧关闭，客户端用 Last-Event-ID 重连。`after` 大于该学生最新 sequence 返回 400（不是该学生的 cursor）。

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

## 6.1 M2 Run 错误码与预算

Run FAILED 的 `error.code`（面向学生，不含供应商消息）：`BUDGET_EXCEEDED`、`MODEL_OUTPUT_INVALID`（有限次重试后输出仍不可用）、`MODEL_REFUSED`、`MODEL_UNAVAILABLE`、`EXECUTION_RETRIES_EXHAUSTED`、`ASSESSMENT_REJECTED`（服务端语义校验未通过，整个提交回滚）、`CONTENT_VERSION_CHANGED`、`COURSE_CONTENT_UNAVAILABLE`、`SKILL_NOT_ENABLED`。这些失败都不写评估、不改掌握度。

会话或当天预算已用完时，新的消息/提交命令返回 429 `BUDGET_EXCEEDED`。预算按 Run、Session、学生每个 UTC 日计，重试也计入；不会为省预算降级评分模型。

## 6.2 M3 课程平台：独立课程、选择题与计划

2026-11-01 起取消跨课程前置技能映射：`GET /api/prerequisites`（及 `/{findingId}`）、`prerequisite.suspected|confirmed|unsupported|inconclusive` 事件、Task reason `PREREQUISITE_DIAGNOSTIC`/`PREREQUISITE_REINFORCEMENT` 均已移除，路由返回 404。一门课程的证据不会在另一门课程中产生事件、任务或掌握度变化。尚无真实学生数据，因此不做旧事件迁移。

**独立课程与选择题**：Digital SAT（`dsat`）是一门独立课程，也是 M3 第二门课程的候选。新增通用 Task 类型 `PRACTICE`（技能练习，如选择题组）。课程包选用 `choice-scoring` 能力后，选择题 Session 的 `activity` 包含 `items[{itemId, prompt, choices[{key,text}]}]`，**不含答案键**。作答仍走 `POST /api/sessions/{id}/submissions`，`answer.text` 每题一行（如 `1: B`）。服务端按答案键评分（`provenance.modelVersion = rule:choice-scoring-v1`，不调用模型），无法读出每题一个选项时为 `insufficient_evidence`。rubric 得分从不换算成考试分数。

**事件**：`plan.updated` payload：`planId`、`changedTaskIds`、`reason`（`replan`）。课程内后续规则（Step 24.2）引入新的事件或原因值时，先在本节补充契约。

**计划**：

- `POST /api/plans/replan` + Idempotency-Key，body `{}` → 202 `{runId, status}`（PLANNING Run，sessionId=null）。同一学生同时只能有一个未结束的 PLANNING Run，否则 409 `RUN_IN_PROGRESS`。
- `GET /api/plans/latest`（还没有计划时 404）、`GET /api/plans/{planId}` → `planId`、`runId`、`ruleVersion`（`planner-rules-v1`）、`localDate`、`horizonEnd`、`weeklyMinutes`、`dailyMinutes`、`evidenceAvailable`、`entries[{taskId, courseId, durationMin, previousDate, scheduledDate, priority, placement, explanation, sourceEventIds}]`。
- `priority`：`deadline` > `evidence_gap` > `practice`（固定任务为 null）。所有已注册课程的任务共用每周时间；排序不会用一门课程的证据评判另一门课程的任务。`placement`：`fixed`（进行中/已完成/学生锁定）、`kept`、`moved`、`deferred`（本周时间已满，顺延到下周）、`over_budget`（为截止日期超出每日预算）。
- GET 从不触发重排。PLANNING Run 失败码：`RUN_ATTEMPTS_EXHAUSTED`。

## 6.3 M3 课程包：作者、审核与发布（Step 26）

契约与校验规则见 [COURSE_PACKAGE.md](COURSE_PACKAGE.md)。作者与平台审核员是平台成员（`platformMembers/{uid}`），不是学生：学生调用以下接口返回 403，平台成员调用学生接口也返回 403。所有 POST 需要 Idempotency-Key（同 key 同请求重放原结果，同 key 不同请求 409 `IDEMPOTENCY_CONFLICT`）。

作者（本组织范围；其他组织的包返回 404）：

- `POST /api/authoring/packages` body `{package: {...}}` → 201（新 draft）/ 200（覆盖 draft）`PackageVersion`，含校验报告。缺 courseId/version 时 400；courseId 属于其他组织或内置课程时 409 `COURSE_ID_TAKEN`；版本已提交或不大于已提交版本时 409 `PACKAGE_VERSION_EXISTS`。
- `GET /api/authoring/packages` → `{versions: [...]}`；`GET /api/authoring/packages/{courseId}/versions/{version}` → 单个版本（含 `package`）。
- `POST /api/authoring/packages/{courseId}/versions/{version}/submit` body `{}` → submitted；报告有错误时 409 `PACKAGE_INVALID`。

平台审核员：

- `GET /api/review/packages?status=submitted&status=approved`（默认这两种；draft 永远不可见）。
- `GET /api/review/packages/{courseId}/versions/{version}`（含 `package`）。
- `POST .../approve` body `{notes, licenseAttested, modelEvaluationAttested}`；条件不满足 409 `REVIEW_REQUIREMENTS_NOT_MET`。
- `POST .../reject` body `{notes}`（必填）。
- `POST .../activate` body `{}`：approved → active，旧 active → superseded。
- `POST /api/review/courses/{courseId}/retire` body `{notes}`。

`PackageVersion`：`courseId`、`version`、`title`、`status`（draft / submitted / approved / active / superseded / rejected / retired）、`orgId`、`contentHash`、`uploadedBy`、`createdAt`、`updatedAt`、`report{valid, validatorVersion, errors[{path, code, message}], evaluation{autoCases, autoPassed, modelCases, failures[]}}`、`review{reviewerId, decision, decidedAt, notes, licenseAttested, modelEvaluationAttested}|null`、`history[{fromStatus, toStatus, actorId, at, notes}]`，单版本读取时另含 `package`。

学生侧变化：`Availability` 增加 `retired`（退役课程不在目录列表中，`GET /api/courses/{id}` 仍可读，新工作返回 409 `COURSE_NOT_AVAILABLE`）；`GET /api/courses/{courseId}/agent` 增加 `skills[{skillId, name}]`（来自课程包，前端据此显示技能名）；首次注册时按课程包 `starterTasks` 创建任务。

## 6.4 M4 定时计划、学生控制与提醒（Steps 28–29）

- **定时计划**：每个已注册课程的学生每个**本地日**一次计划，默认本地 04:00（`HSOS_PLANNING_LOCAL_TIME`），与学生重排使用同一个 Planner。`Plan` 增加只读字段 `trigger`：`student`（`POST /api/plans/replan`）或 `scheduled`；`plan.updated` 的 `payload.reason` 相应为 `replan` 或 `scheduled`。定时计划运行期间学生重排返回 409 `RUN_IN_PROGRESS`；学生重排尚未执行时到点的定时计划并入它，不再建第二个 Run。`GET /api/tasks` 与 `GET /api/plans/*` 永不触发计划。
- **学生控制**（契约不变，前端已接入）：`PATCH /api/tasks/{taskId}` 改 `scheduledDate`（默认锁定）、`studentLocked` 解锁/锁定、`status=SKIPPED` + `skipReason`。
- **提醒同意**：`preferences.notifications.channels` 上限改为 **1**（试点只允许一个渠道），`channels` 非空需要 `enabled=true`，否则 400 `VALIDATION_FAILED`。修改 `notifications` 的 twin PATCH 同时写入同意记录（`students/{id}/consents/notifications`：granted、channels、policyVersion `reminders-v1`、grantedAt、revokedAt）。同意记录不通过 API 暴露，仅供发送前复查。
- **提醒**：每个学生、渠道、本地日最多一条摘要提醒（id = 去重键 `{localDate}.{channel}`），默认本地 16:00，避开安静时段；内容在发送时按当时的任务计算（已完成、跳过或改到别天的任务不计入；一个都不剩就不发）。接收者只有学生本人，没有家长通知。试点没有真实渠道：只有 `fake` 发送器，部署环境只发给指定的合成测试学生（`HSOS_REMINDER_TEST_RECIPIENTS`），生产环境拒绝 `fake`。
- **内部路由**（worker，仅服务身份；Cloud Scheduler 调用）：`POST /internal/planning/schedule`、`/internal/reminders/deliver`、`/internal/ops/check`（返回 `{alerts[{alert, firing, observed, threshold}]}`）、`/internal/retention/events`。学生 token 一律 401。
- **事件保留**：超过 `HSOS_EVENT_RETENTION_DAYS`（默认 180 天）的事件被清理并提高 `oldestRetainedSequence`；更早的游标返回 410（已有契约）。评估、掌握度、计划不受影响。

## 6.5 M5 扩展（Steps 34–38，2026-11-04）

M5 是试点后的可选扩展，各项单独验收（见 [STEP_BY_STEP_PLAN.md](STEP_BY_STEP_PLAN.md) M5）。所有 POST 仍需 Idempotency-Key，修改用 If-Match。

### 6.5.1 作者门户与课程指标（Step 34.1、34.4）

- `GET /api/authoring/packages/{courseId}/versions/{version}/preview`（本组织作者）、`GET /api/review/packages/{courseId}/versions/{version}/preview`（审核员）→ `PackagePreview`：`courseId`、`version`、`name`、`description`、`skills[{skillId,name}]`、`starterTasks[{questionId,title,taskType,mode,durationMin}]`、`questions[{questionId,version,topic,prompt,items?,sources?}]`。即学生看到的内容：**不含**答案键、`expectedAnswer`、rubric、systemPrompt、evaluationSet。报告有错误的版本返回 409 `PACKAGE_INVALID`；其他组织 404；学生 403。
- `GET /api/authoring/courses/{courseId}/metrics`（本组织课程）→ `CourseMetricsView`：`courseId`、`suppressed`、`minimumCohort`（5）、`students`、`assessments`、`byStatus{accepted, insufficient_evidence}`、`criteria[{rubricId, criterionId, count, averageEarned, maxPoints}]`、`updatedAt`。不同学生少于 5 人时 `suppressed: true`，其余字段为 null。只有聚合数，从不含学生 id、作答、反馈或单条记录。内置课程（calc_bc）与其他组织课程 404。
- 指标由平台消费者 `course-metrics`（订阅 `assessment.completed`）维护，凭消费回执保证每个事件只计一次；`HSOS_COURSE_METRICS_ENABLED`（默认 true）。
- 作者门户页面：`web/author.html`（上传、校验报告、提交、审核意见与历史、学生视角预览、指标）。它只调用 `/api/authoring/*`，不能批准或激活。

### 6.5.2 平台能力 `source-analysis`（Step 34.2）

- 课程包题目新增可选字段 `sourceMaterialIds`（≤8，引用本课程 materials）：基于材料的写作题（如 DBQ）。选择题组不能带材料。校验器：带材料的题需要能力 `source-analysis`；选了该能力必须至少有一道带材料的题；材料不存在 → `unknown_material`。
- Session `activity` 新增 `sources[{materialId, title, text, sourceRef}]`（按题目顺序）。
- 评分：rubric 评分 + 材料（作为不可信内容隔离注入）。每个 criterion 输出 `documentsCited`，引用题目材料以外的文档 → 输出无效（重试后 `MODEL_OUTPUT_INVALID`，不写评估）。得分证据仍必须是学生作答的原文片段。路由下限：strong。
- APUSH（`apush`）以作者包形式提供（`content/authored/apush`），本地种子状态为 **submitted**（待平台审核）；内置“planned”占位已移除。

### 6.5.3 家长摘要（Step 36）

家长是独立身份（`parents/{uid}`），不是学生，也不是平台成员；学生调用家长接口 403，家长调用学生接口 403。

学生端：
- `POST /api/parent-links` body `{scopes: ["summary:read"]}` → 201 `{linkId, status: "pending", scopes, createdAt, inviteExpiresAt, inviteCode}`。`inviteCode` 只返回一次（只存哈希；幂等重放时为 null），7 天有效。只能授予 `summary:read`；同时最多 4 个 pending/active 链接，否则 409 `PARENT_LINK_LIMIT`。
- `GET /api/parent-links` → `{links: [...]}`，状态 `pending | active | revoked | expired`，含 `parentDisplayName`、`acceptedAt`、`revokedAt`。
- `POST /api/parent-links/{linkId}/revoke` body `{}` → revoked（立即生效）。

家长端：
- `POST /api/parent/links/accept` body `{inviteCode}` → `{studentId, displayName, linkedAt}`。错误、已用或过期的码一律 404。
- `GET /api/parent/students` → `{students: [{studentId, displayName, linkedAt}]}`（只含有效链接）。
- `GET /api/parent/students/{studentId}/summary` → `ParentSummaryView`：`studentId`、`displayName`、`grade`、`courses[{courseId, name, skills[{skillId, level, independentEvidenceCount}], prediction: "unavailable"}]`、`week{start, end, planned, completed, skipped, upcoming[{courseId, title, scheduledDate, durationMin}]}`、`generatedAt`。**不含**聊天、作答、反馈、文书、申请事实、权限或事件。每次读取都在同一事务中重新校验学生侧链接与 scope；未链接、他人、已撤销 → 404。

### 6.5.4 申请工作区（Step 35）

需要后台授予 `entitlements.admissions`，否则 403 `ADMISSIONS_ACCESS_REQUIRED`。前缀 `/api/admissions`。

- 访谈：`GET /interview/prompts` → `{promptSetVersion, prompts[{promptId, category, text}]}`；`POST /interview/answers` `{promptId, text}` → 202 回答 + `run{runId, status}`（`ADMISSIONS_FACTS` Run）；`GET /interview/answers`。
- 事实：`GET /facts` → `{facts[{factId, text, category, status, source, answerId, quote, createdAt, decidedAt, version}]}`。模型只能**提议**（`status: proposed`, `source: interview`），每条必须附回答原文 `quote`，找不到原文的提议直接丢弃。`POST /facts` `{text, category}`：学生自己写的事实，直接 confirmed。`POST /facts/{id}/confirm` `{text?}`（可改写为自己的话）、`POST /facts/{id}/reject` `{}`；已决定的事实再决定 → 409 `INVALID_STATE_TRANSITION`。
- 活动：`GET /activities`；`POST /activities`、`PATCH /activities/{id}`（If-Match）body `{name, role, description, hoursPerWeek, weeksPerYear, factIds, studentConfirmed}`。`studentConfirmed` 必须为 true，且引用的事实必须全部 confirmed，否则 409 `FACTS_NOT_CONFIRMED`。
- 截止日期：`GET /deadlines`；`POST /deadlines`、`PATCH /deadlines/{id}`（If-Match）body `{school, kind, dueDate, sourceUrl?, sourceCheckedOn?, notes}`，`sourceUrl` 必须 `https://`。响应含 `daysLeft`、`verification`（`verified` 30 天内核对过 / `stale` / `unverified` / `unsourced`）与 `uncertainty` 说明。
- 文书：`GET /essays`、`POST /essays` `{title, prompt}`、`GET /essays/{id}`、`PATCH /essays/{id}` `{draft}`（If-Match；反馈生成期间 409 `RUN_IN_PROGRESS`）。草稿只由学生撰写，服务端从不写或改写。
- 提纲/反馈：`POST /essays/{id}/feedback` `{kind: "outline" | "feedback"}` → 202（`ADMISSIONS_FEEDBACK` Run；同一篇文书同时只有一个）。outline 需要至少一条 confirmed 事实（否则 409 `FACTS_NOT_CONFIRMED`），只把 confirmed 事实交给模型，每个要点 ≤25 词并引用 factId；feedback 需要非空草稿，条目为 strength / question / suggestion，每条 ≤40 词，总计 ≤250 词。超长（代写）或引用未确认事实 → `MODEL_OUTPUT_INVALID`，不保存。`GET /essays/{id}/feedback` → `{feedback[{feedbackId, essayId, essayVersion, kind, runId, items[{type, text, factIds}], createdAt, completedAt}]}`。
- Run：`kind` 新增 `ADMISSIONS_FACTS`、`ADMISSIONS_FEEDBACK`（`sessionId` 为 null），`Run.subjectId` 指向回答或反馈请求。`HSOS_LLM_PROVIDER=mock` 时失败为 `MODEL_UNAVAILABLE`（没有合成的申请输出）。其他失败码：`ADMISSIONS_ACCESS_REQUIRED`、`ADMISSIONS_INPUT_NOT_FOUND`、`ESSAY_CHANGED`。

### 6.5.5 预测门控（Step 37）

`TwinSummary.predictionSummary` 的每个已注册课程都由预测门控计算，目前一律 `{status: "unavailable", reason}`。reason 依次为：`not_calibrated`、`synthetic_only`、`mastery_not_calibrated`、`insufficient_coverage`、`no_independent_exam_outcomes`、`prediction_model_not_validated`。练习表现、自报成绩与预测分开处理，前两者永远不能使预测可用。校准脚本见 `server/scripts/run_calibration.py`。

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
