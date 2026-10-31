"""Synthetic execution: a deterministic stand-in for the LLM (Step 15.5).

Used for internal pipeline tests and local runs with `HSOS_LLM_PROVIDER=mock`. Output is
clearly labeled and marked `synthetic=True`; it never produces an Assessment, a score, or
mastery evidence, so it can never be mistaken for real grading.
"""

from __future__ import annotations

from app.domain.ports.execution import ExecutionOutput, ExecutionRequest
from app.domain.types.run import RunKind

SYNTHETIC_MODEL_VERSION = "synthetic-v1"
SYNTHETIC_LABEL = "[Synthetic response: test pipeline only, not tutoring or grading]"


class SyntheticExecutor:
    async def execute(self, request: ExecutionRequest) -> ExecutionOutput:
        if request.run.kind is RunKind.ASSESS_SUBMISSION:
            body = "Your answer was received. No assessment is produced in synthetic mode."
        else:
            body = "Your message was received. Real tutoring needs a configured model."
        return ExecutionOutput(
            agent_text=f"{SYNTHETIC_LABEL} {body} (course {request.course.course_id}, "
            f"attempt {request.run.attempt_count})",
            model_version=SYNTHETIC_MODEL_VERSION,
            synthetic=True,
        )
