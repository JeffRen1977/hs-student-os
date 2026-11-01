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

`stu_alex` also has two Digital SAT practice tasks (`task_alex_dsat_01/02`, choice sets
scored by answer key): Digital SAT is an independent course, the M3 second-course candidate.
