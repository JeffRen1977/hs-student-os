# Synthetic fixtures

Everything here is **synthetic**. No real student names, emails, answers, or records.

- Emails use the RFC 2606 reserved domain `example.test`.
- Exam predictions are always `unavailable` (no calibrated prediction pipeline exists).
- Entitlements (`entitlements/`) are separate from student preferences/enrollments
  (`students/`). Since 2026-11-07 only `admissions` has any effect: any student may enroll in
  any active course, so the per-course lists below are legacy data kept for compatibility.

| Student | Grade | Timezone | Entitlements | Enrolled |
|---|---|---|---|---|
| `stu_alex` | 11 | America/Los_Angeles | calc_bc + dsat | calc_bc + dsat |
| `stu_beth` | 10 | America/New_York | calc_bc | calc_bc |

Legacy course lists: `apCourses` for AP courses, `courses` for the others.

`platform/members.json` holds synthetic platform members: authors `author_hsos`
(`org_hsos_content`) and `author_sample` (`org_sample_press`), the reviewer
`reviewer_platform`, and the admin `admin_platform`. It also lists the course packages local
seeding installs: `content/authored/dsat` as active and `content/authored/apush` as submitted
(waiting for review); their audit trail is labelled `seed:local-dev`, not a review.

`stu_alex` also has two Digital SAT practice tasks (`task_alex_dsat_01/02`, choice sets
scored by answer key): Digital SAT is an independent course, the M3 second-course candidate.
