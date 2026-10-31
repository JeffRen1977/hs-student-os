# Learning evaluation baseline (Step 7)

Reviewable expected outcomes for judging AI grading. This is a **content gate**: no model
has been evaluated against these cases yet, and every case is `review.status = draft`
until a named content reviewer signs off.

- `calc_bc/` — annotated answers: correct, incorrect, partial, assisted (hints),
  ambiguous, and insufficient work shown.
- `prerequisites/` — counterexamples (calculus errors that must **not** suggest a SAT
  weakness) and one supporting case (repeated algebra errors → `prerequisite.suspected`
  only; confirmation requires a separate diagnostic).
- `dimensions.json` — evaluation dimensions. Thresholds are `null` until set by a reviewer.
- `report-template.md` — versioned report template.

All student answers are synthetic and written for this project.
