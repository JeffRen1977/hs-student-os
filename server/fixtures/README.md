# Synthetic fixtures

Everything here is **synthetic**. No real student names, emails, answers, or records.

- Emails use the RFC 2606 reserved domain `example.test`.
- Exam predictions are always `unavailable` (no calibrated prediction pipeline exists).
- Entitlements (`entitlements/`) are separate from student preferences/enrollments
  (`students/`): selecting a course is a preference, not an access grant.

| Student | Grade | Timezone | Entitlements | Enrolled |
|---|---|---|---|---|
| `stu_alex` | 11 | America/Los_Angeles | calc_bc + dsat | calc_bc + dsat |
| `stu_beth` | 10 | America/New_York | calc_bc | calc_bc |

Entitlements are per courseId: `apCourses` for AP courses, `courses` for the others.

`platform/members.json` holds synthetic platform members: authors `author_hsos`
(`org_hsos_content`) and `author_sample` (`org_sample_press`), and the reviewer
`reviewer_platform`. It also lists the course packages local seeding installs as active
(`content/authored/dsat`); their audit trail is labelled `seed:local-dev`, not a review.

`stu_alex` also has two Digital SAT practice tasks (`task_alex_dsat_01/02`, choice sets
scored by answer key): Digital SAT is an independent course, the M3 second-course candidate.
