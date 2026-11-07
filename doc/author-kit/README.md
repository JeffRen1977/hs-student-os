# Author kit: publishing your course on High School Student OS

This kit is for **course authors**: organizations that bring a course (AP subjects, SAT, and
more) to High School Student OS. It explains what to prepare, how to upload it, and what
happens before students can see it.

| In this kit | Use it for |
|---|---|
| `README.md` (this guide) | The steps, from first draft to a published course |
| [`FIELD_REFERENCE.md`](FIELD_REFERENCE.md) | Every field and rule, and what each validator error means |
| [`templates/blank-package.json`](templates/blank-package.json) | The smallest valid package; start here |
| [`examples/digital-sat-2.0.0.json`](examples/digital-sat-2.0.0.json) | A complete course: Digital SAT, 29 skills, 12 practice sets |

## 1. How it works

You describe your course in **one JSON file**, the *course package*. It holds your skills,
practice questions, answer keys, scoring rubrics, the tutor's teaching instructions, and test
cases. You upload it in the **author portal**; the platform checks it at once; a **platform
reviewer** approves it; then it appears in the student catalog.

```
You write the package  →  Upload (portal)  →  Validation report  →  fix and re-upload as needed
      →  Submit  →  Platform review  →  Approved  →  Activated  →  in the course catalog
```

Every course runs on the same platform. Your package does not contain code; it chooses from
abilities the platform provides:

| Ability | What it does for your students |
|---|---|
| `socratic-guidance` | A tutor that gives hints by asking questions, without giving answers away |
| `choice-scoring` | Multiple-choice sets scored instantly by your answer key |
| `rubric-assessment` | Written or worked answers graded against your rubric |
| `source-analysis` | Writing based on documents you provide (for example, a document-based question) |

If your course needs something not on this list, ask the platform team. New abilities are added
to the platform for every course; they are never added inside one package.

**What stays with the platform:** approving and activating courses, deciding which students may
enroll, and all student data. You will see aggregate results for your course (once at least 5
students are enrolled), never an individual student's work.

## 2. Before you start: content rules

Your package will be refused at review if it breaks any of these.

- **Use only content you own or have a license for.** Do not use College Board questions or
  questions from commercial test-prep books, including photos, scans, or retyped copies,
  without written permission. Every question and rubric records its source and license.
- **No real student information:** no names, answers, essays, or photos of student work.
- **No score predictions.** Do not describe practice results as SAT, AP, or other exam scores.
- **Check every answer key yourself.** The platform verifies that your *scoring* works; it
  cannot tell whether an answer key is *correct*. Each item needs exactly one defensible answer.

## 3. Writing your package

1. **Copy the template** (`templates/blank-package.json`) and rename it as you like. The file
   name does not matter.
2. **Fill in the manifest**: your course ID (lowercase, for example `ap_biology`), version
   `1.0.0`, name, description, category, abilities, and license.
3. **List your skills.** Each skill ID starts with your course ID: `ap_biology.cells.membrane-transport`.
   Students' progress is tracked per skill, so choose skills you want to report on.
4. **Write practice sets.** A multiple-choice set has up to 10 items, each with 2–4 choices
   (A–D) and one answer key. For reading items, put the short passage at the top of the item,
   then a blank line, then the question.
5. **Write one rubric per set**, with one line (criterion) per item, tagged with the skill that
   item tests. This is how answering an item updates the right skill.
6. **Write the tutor's instructions** (`systemPrompt`): how the tutor should teach your course.
   You may use only three placeholders: `{{studentName}}`, `{{currentMode}}`, `{{masteryContext}}`.
7. **Choose starter tasks**: the sets a student gets when they first join your course.
8. **Write test cases** (`evaluationSet`). For every multiple-choice set, at least:
   all answers correct, one answer wrong, and an answer that cannot be read. These run
   automatically when you upload.
9. Leave every question's `review.status` as `"draft"`. Your content reviewer changes it to
   `"reviewed"` (with their name and date) after checking the item.

The example course shows every part at full size. [`FIELD_REFERENCE.md`](FIELD_REFERENCE.md)
lists every field, its limits, and the rules that connect them.

> **Tip:** JSON is easy to break by hand (a missing comma or quote). Use an editor that
> highlights JSON errors, and upload early: the validation report points to the exact place.

## 4. Uploading and fixing

1. Sign in to the author portal (`/author.html` on the platform site) with the author account
   the platform team gave you.
2. **Upload** your file. You will get a **validation report**:
   - *Errors*, each with a location such as `questions[q_bio_cells_001].items` and a message.
     Fix them and upload again. While the version is a draft you can replace it as often as
     you need.
   - *Evaluation results*: how many of your test cases passed, and which failed.
3. Open the **student preview**: this is what students will see. Answer keys, rubrics, tutor
   instructions, and test cases are hidden from students.
4. When the report shows no errors and every test case passes, **Submit for review**. After you
   submit, that version can no longer be changed; fixes go into a new version.

## 5. Review and publication

A platform reviewer checks your validation report and test results, your license statement, and
the content itself. The reviewer either:

- **approves and activates** the course: it appears in the catalog, and students with access can
  enroll; or
- **rejects** it with notes, which you see in the portal. Fix the issues and upload a new
  version.

You can follow every step (who changed the status, and when) in the version's history.

## 6. Updating a published course

Upload a new version with a higher number (for example `1.1.0` or `2.0.0`). It goes through the
same review. When the new version is activated, students who are in the middle of a set finish
it on the old version; new practice uses the new one. Past results never change.

Keep these unchanged between versions:

- **Skill IDs.** Students' progress is stored per skill; a renamed skill starts from zero.
- **Question IDs of existing sets.** Students may have those sets planned; removing a set they
  are scheduled to do makes that task unavailable. To change a set, give it a new `version`.

Currently, students who joined before an update do not automatically receive the new sets. Only
new students get starter tasks from the new version.

## 7. After publication

The portal shows aggregate results for your course: how many students, how many answers were
graded (and how many were unreadable), and the average score on each rubric line, which helps
you find unclear items. These
numbers are hidden until at least 5 students are enrolled.

## 8. Not supported yet

- Uploading PDFs or photos of questions (planned). For now, the questions must be typed into the
  package.
- Images in questions (diagrams, graphs, charts) and formatted math. Text only for now; write
  math in plain text, such as `x² + 3x`, `3/5`, `√2`.
- Timed, full-length tests.
- An authoring assistant (planned): build and edit your package by conversation instead of
  writing JSON. You will still confirm every answer key and submit the course yourself.

## 9. Checklist before you submit

- [ ] Every question and rubric has a source and license, and you have the right to use it.
- [ ] Every answer key checked by a person; each item has exactly one defensible answer.
- [ ] Each rubric line is tagged with the skill its item tests.
- [ ] No student information, and no score predictions anywhere.
- [ ] The validation report shows no errors, and every test case passes.
- [ ] The student preview reads well.
- [ ] For an update: skill IDs and existing question IDs are unchanged, and the version number
      is higher.
