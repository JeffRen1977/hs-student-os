# 课程包契约 v1（course-package/v1）

更新：2026-11-01。实现：`server/app/schemas/package.py`（契约）、`server/app/registries/package_validator.py`（校验器）、`server/app/domain/package_service.py`（审核与发布流程）。参考包：`server/content/authored/dsat/package.json`（Digital SAT）。

课程包是**纯数据**：一个 JSON 文档完整描述一门课程。包里没有代码；能力（ability）和工具只能从平台目录中选择。缺少的能力由平台新增，所有课程都可选用，绝不为某门课写运行时分支。

## 1. 结构

```json
{
  "schemaVersion": "course-package/v1",
  "manifest": { ... },
  "systemPrompt": "…",
  "skills": [{"skillId": "dsat.algebra.linear-equations", "name": "…", "description": "…"}],
  "rubrics": [ /* 与 content/packs/*/rubrics 相同的 Rubric 结构 */ ],
  "questions": [ /* Question：自由作答，或带 items 的选择题组 */ ],
  "materials": [ /* 可选，审核过的参考材料 */ ],
  "starterTasks": [{"questionId": "…", "taskType": "PRACTICE", "mode": "ADAPTIVE", "title": "…", "durationMin": 15}],
  "evaluationSet": [{"caseId": "…", "questionId": "…", "answerText": "1: A\n2: C", "expectedStatus": "accepted", "expectedEarned": {"item-1": 1, "item-2": 0}}]
}
```

**manifest**：`courseId`、`version`（MAJOR.MINOR.PATCH）、`name`、`description`、`category`（AP / SAT / ADMISSIONS，仅为目录标签，**不授予访问权限**）、`agentType`、`supportedTaskTypes`、`supportedModes`、`abilities`、`tools`、`modelTier`、`contextBudgetTokens`、`workflowVersion`、`publisher.name`（显示名；归属以上传作者所在组织为准）、`license`。

平台能力目录：`socratic-guidance`、`rubric-assessment`、`choice-scoring`。工具目录：`math-verify`、`content-retrieval`。

**starterTasks**：学生首次注册且该课程尚无任务时，在注册事务中创建这些 PLANNED 任务（reason `INITIAL_PRACTICE`），放在最早有空余时间的日期。重新注册不会重复创建。

**evaluationSet**：每条用例给出一份作答和预期结果（`expectedEarned` 需列出该题 rubric 的每个 criterion）。选择题用例在上传时由平台按答案键确定性运行；需要模型评分的用例计入 `modelCases`，由审核员在批准时声明已运行。

## 2. 校验（一次返回全部错误）

`validate_package(raw)` 不抛异常，返回报告：每个错误带 `path`、`code`、`message`，不回显提交内容。

1. 模式：契约字段、未知字段拒绝、大小上限 900 KB（单个 Firestore 文档）。
2. 归属：所有题目/rubric/材料/技能属于 manifest 的 courseId；skillId 以 `{courseId}.` 开头。
3. 引用：题目 → rubric、rubric/题目/材料 → 技能、starter task 与评测用例 → 题目、answerCheck 与选择题 item → rubric criterion；ID 不重复。
4. 平台目录：能力与工具存在；所选能力有所需数据（`choice-scoring` ↔ 选择题组，`rubric-assessment` ↔ 自由作答题）。在校验时拒绝，而不是在运行时失败。
5. systemPrompt：只允许平台模板变量 `{{studentName}}`、`{{currentMode}}`、`{{masteryContext}}`。
6. 评测：运行选择题用例，失败的 caseId 列入 `evaluation.failures`。

模式错误时不再做交叉引用检查（引用不可信）；修复后再次上传会报告下一层问题。

## 3. 审核与发布（Step 26）

```
上传(作者) → draft ─submit→ submitted ─approve→ approved ─activate→ active
                                 └─reject→ rejected        active → superseded（新版本激活）
                                                           active ─retire→ retired
```

- **作者**属于一个作者组织，只能看到本组织的包；其他组织的包返回 404。courseId 被其他组织或平台内置课程（calc_bc、apush、physics_c）占用时返回 409 `COURSE_ID_TAKEN`。
- draft 可以覆盖上传；submitted 之后版本不可变。新版本号必须大于已提交过的所有版本（409 `PACKAGE_VERSION_EXISTS`）。
- 报告有错误时不能提交（409 `PACKAGE_INVALID`）。
- **平台审核员**批准需要：报告无错误、选择题评测全部通过、评测集非空、`licenseAttested: true`、有模型用例时 `modelEvaluationAttested: true`；否则 409 `REVIEW_REQUIREMENTS_NOT_MET`。驳回必须写备注，作者可见。
- 每次状态变化记录在版本的 `history` 中（from、to、actorId、时间、备注），审核决定记录在 `review` 中。
- 激活后旧的 active 版本变为 `superseded`，继续服务固定在它上面的 Session；不能用较旧版本替换较新的 active 版本。
- 退役：课程不再出现在目录中；新注册、新 Session、新提交返回 409 `COURSE_NOT_AVAILABLE`；学生的 Session、评估、掌握度保留可读，打开的 Session 可以放弃。
- 访问权限仍由平台管理（`entitlements.apCourses` / `entitlements.courses`，按 courseId），作者无法授予。作者与审核员不是学生，调用学生接口返回 403；包记录中没有学生数据。

## 4. 版本固定

Session 创建时固定 `contextVersion.pack`。运行时按固定版本加载题目、rubric 与材料，即使之后激活了新版本或课程已退役，旧 Session 与历史评估也不会改变内容。新 Session 使用当时的 active 版本。

## 5. 本地开发

`server/fixtures/platform/members.json` 定义合成作者（`author_hsos`、`author_sample`）、审核员（`reviewer_platform`）和本地种子包。种子包与上传走同一个校验器和评测集，但其审核记录明确标注为 `seed:local-dev`（本地种子，不是平台审核）。完整审核流程由 `tests/contract/test_package_review.py` 与 `tests/contract/test_authored_course_loop.py` 通过 API 验证。
