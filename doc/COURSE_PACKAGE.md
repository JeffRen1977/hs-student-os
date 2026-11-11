# 课程包契约 v1（course-package/v1）

更新：2026-11-04（M5：能力 `source-analysis`、题目字段 `sourceMaterialIds`、APUSH 作者包、作者预览与课程指标）。2026-11-01。实现：`server/app/schemas/package.py`（契约）、`server/app/registries/package_validator.py`（校验器）、`server/app/domain/package_service.py`（审核与发布流程）。参考包：`server/content/authored/dsat/package.json`（Digital SAT 1.0.0，本地种子）、`server/content/authored/dsat/package-2.0.0.json`（Digital SAT 2.0.0：两个部分、29 项技能、8 组新题，作者上传示例，见 [AUTHORING_GUIDE.md](AUTHORING_GUIDE.md)）、`server/content/authored/apush/package.json`（AP US History，含基于材料的写作题）。

课程包是**纯数据**：一个 JSON 文档完整描述一门课程。包里没有代码；能力（ability）和工具只能从平台目录中选择。缺少的能力由平台新增，所有课程都可选用，绝不为某门课写运行时分支。

## 1. 结构

```json
{
  "schemaVersion": "course-package/v1",
  "manifest": { ... },
  "systemPrompt": "…",
  "skills": [{"skillId": "dsat.algebra.linear-equations", "name": "…", "description": "…"}],
  "rubrics": [ /* 与 content/packs/*/rubrics 相同的 Rubric 结构 */ ],
  "questions": [ /* Question：自由作答、带 items 的选择题组，或带 sourceMaterialIds 的基于材料写作题 */ ],
  "materials": [ /* 可选，审核过的参考材料 */ ],
  "starterTasks": [{"questionId": "…", "taskType": "PRACTICE", "mode": "ADAPTIVE", "title": "…", "durationMin": 15}],
  "practiceSequence": [ /* 可选，与 starterTasks 同结构：起始任务之后按顺序提供的练习 */ ],
  "evaluationSet": [{"caseId": "…", "questionId": "…", "answerText": "1: A\n2: C", "expectedStatus": "accepted", "expectedEarned": {"item-1": 1, "item-2": 0}}]
}
```

**manifest**：`courseId`、`version`（MAJOR.MINOR.PATCH）、`name`、`description`、`category`（AP / SAT / ADMISSIONS，仅为目录标签，**不授予访问权限**）、`agentType`、`supportedTaskTypes`、`supportedModes`、`abilities`、`tools`、`modelTier`、`contextBudgetTokens`、`workflowVersion`、`publisher.name`（显示名；归属以上传作者所在组织为准）、`license`。

平台能力目录：`socratic-guidance`、`rubric-assessment`、`choice-scoring`、`source-analysis`（M5 Step 34.2）。工具目录：`math-verify`、`content-retrieval`。

**基于材料的写作题**（`source-analysis`）：题目带 `sourceMaterialIds`（≤8，指向本包 `materials`），如 DBQ、基于给定段落的论证。学生在 Session `activity.sources` 中看到这些材料。评分时材料作为不可信内容隔离注入；评分器对每个 criterion 给出所用材料 `documentsCited`，引用题目材料之外的文档 → 输出无效；得分证据只能引自学生作答。这个能力不属于任何一门课：任何课程包都可以选用。

**starterTasks**：学生首次注册且该课程尚无任务时，在注册事务中创建这些 PLANNED 任务（reason `INITIAL_PRACTICE`），放在最早有空余时间的日期。重新注册不会重复创建。

**practiceSequence**（可选，≤200，2026-11-07）：与 starterTasks 同结构。课程的**练习顺序** = starterTasks 后接 practiceSequence；一道题在两者中最多出现一次（`duplicate`），校验与 starterTasks 相同（`unknown_question`、`unsupported_task_type`、`unsupported_mode`）。平台规则“练习补充”（BACKEND.md §9）按这个顺序给学生分配下一组：学生在该课程的未完成任务（PLANNED/IN_PROGRESS）少于 2 个时，按顺序挑选该学生**从未有过任务**的题目新建任务（reason `NEXT_PRACTICE`），直到未完成任务为 2 个或顺序用完。在完成 Session 时（只针对该课程）和每次计划运行时（定时与学生重排，所有已注册课程）执行；课程未激活、已退役、学生没有权限或未注册时不分配。已完成、跳过的任务对应的题目不会再次分配。新版本激活后，之前注册的学生在下一次补充时得到新版本顺序中尚未分配过的题目。没有 practiceSequence 的课程只有起始任务（行为不变）。

**evaluationSet**：每条用例给出一份作答和预期结果（`expectedEarned` 需列出该题 rubric 的每个 criterion）。选择题用例在上传时由平台按答案键确定性运行；需要模型评分的用例计入 `modelCases`，由审核员在批准时声明已运行。

## 2. 校验（一次返回全部错误）

`validate_package(raw)` 不抛异常，返回报告：每个错误带 `path`、`code`、`message`，不回显提交内容。

1. 模式：契约字段、未知字段拒绝、大小上限 900 KB（单个 Firestore 文档）。
2. 归属：所有题目/rubric/材料/技能属于 manifest 的 courseId；skillId 以 `{courseId}.` 开头。
3. 引用：题目 → rubric、rubric/题目/材料 → 技能、starter task 与评测用例 → 题目、answerCheck 与选择题 item → rubric criterion；ID 不重复。
4. 平台目录：能力与工具存在；所选能力有所需数据（`choice-scoring` ↔ 选择题组，`rubric-assessment` ↔ 不带材料的自由作答题，`source-analysis` ↔ 带 `sourceMaterialIds` 的题，材料必须存在：`unknown_material`）。选择题组不能带材料。在校验时拒绝，而不是在运行时失败。
5. systemPrompt：只允许平台模板变量 `{{studentName}}`、`{{currentMode}}`、`{{masteryContext}}`。
6. 评测：运行选择题用例，失败的 caseId 列入 `evaluation.failures`。

模式错误时不再做交叉引用检查（引用不可信）；修复后再次上传会报告下一层问题。

## 3. 审核与发布（Step 26）

```
上传(作者) → draft ─submit→ submitted ─approve→ approved ─activate→ active
                                 └─reject→ rejected        active → superseded（新版本激活）
                                                           active ─retire→ retired
```

- **作者**属于一个作者组织，只能看到本组织的包；其他组织的包返回 404。courseId 被其他组织或平台内置课程（calc_bc、physics_c）占用时返回 409 `COURSE_ID_TAKEN`。APUSH 的内置“planned”占位已在 M5 移除，`apush` 由第一方作者组织以课程包提供。
- draft 可以覆盖上传；submitted 之后版本不可变。新版本号必须大于已提交过的所有版本（409 `PACKAGE_VERSION_EXISTS`）。
- 报告有错误时不能提交（409 `PACKAGE_INVALID`）。
- **平台审核员**批准需要：报告无错误、选择题评测全部通过、评测集非空、`licenseAttested: true`、有模型用例时 `modelEvaluationAttested: true`；否则 409 `REVIEW_REQUIREMENTS_NOT_MET`。驳回必须写备注，作者可见。
- 每次状态变化记录在版本的 `history` 中（from、to、actorId、时间、备注），审核决定记录在 `review` 中。
- 激活后旧的 active 版本变为 `superseded`，继续服务固定在它上面的 Session；不能用较旧版本替换较新的 active 版本。
- 退役：课程不再出现在目录中；新注册、新 Session、新提交返回 409 `COURSE_NOT_AVAILABLE`；学生的 Session、评估、掌握度保留可读，打开的 Session 可以放弃。
- 审核员批准后，由平台管理员发布（activate）或下线（retire）；发布后任何学生都可以注册，不按学生授权。作者和审核员都不能发布或下线。作者与审核员不是学生，调用学生接口返回 403；包记录中没有学生数据。

## 4. 版本固定

Session 创建时固定 `contextVersion.pack`。运行时按固定版本加载题目、rubric 与材料，即使之后激活了新版本或课程已退役，旧 Session 与历史评估也不会改变内容。新 Session 使用当时的 active 版本。

## 5. 本地开发

`server/fixtures/platform/members.json` 定义合成作者（`author_hsos`、`author_sample`）、审核员（`reviewer_platform`）和本地种子包。种子包与上传走同一个校验器和评测集。`status: "active"` 的种子（dsat）审核记录明确标注为 `seed:local-dev`（本地种子，不是平台审核）；`status: "submitted"` 的种子（apush）只到提交为止，在审核队列中等待平台审核员。同一文件还定义合成家长账号（`parent_alex`、`parent_other`，Step 36）。完整审核流程由 `tests/contract/test_package_review.py` 与 `tests/contract/test_authored_course_loop.py` 通过 API 验证。

## 6. 作者门户与课程指标（M5 Step 34）

- **门户**：`web/author.html`。作者上传/替换 draft、查看校验报告（含评测集结果）、提交审核、查看审核意见与状态历史、以学生视角预览（`GET /api/authoring/packages/{courseId}/versions/{version}/preview`：不含答案键、expectedAnswer、rubric、systemPrompt、evaluationSet），以及查看课程指标。门户不能批准或激活，审核仍由平台审核员完成。
- **课程指标**：`GET /api/authoring/courses/{courseId}/metrics`，只有聚合数：不同学生数、评估数（按状态）、每个 rubric criterion 的平均得分。不同学生少于 5 人时整体隐藏（`suppressed: true`）。作者看不到任何单个学生的数据。
- **新增课程（Step 34.3）**：APUSH 1.0.0（`content/authored/apush`）：一道简答题（rubric-assessment）、一道基于两份公有领域文献的 DBQ 式写作题（source-analysis）、一组材料分析选择题（choice-scoring）；评测集 3 条选择题用例（上传时自动运行，全部通过）+ 4 条模型评分用例（审核员批准时须声明 `modelEvaluationAttested`）。本地种子把它放在 **submitted**（等待平台审核），不是 active。内容为草稿，文献摘录的措辞需在内容审核时与原文核对。
- **回归（Step 34.5）**：`tests/unit/test_platform_abilities.py` 在每次新增能力后检查所有作者包仍通过校验并通过自动评测用例，内置课程不受影响。

