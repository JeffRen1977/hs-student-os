"""Example payloads copied from doc/API.md v0.3. Contract tests assert they validate."""

from __future__ import annotations

from typing import Any

TWIN: dict[str, Any] = {
    "studentId": "stu_alex",
    "version": 3,
    "profile": {"displayName": "Alex", "grade": 11, "targetMajor": "CS"},
    "goals": {"satTarget": 1550, "apTargets": {"calc_bc": 5}},
    "preferences": {
        "timezone": "America/Los_Angeles",
        "weeklyAvailableMinutes": 300,
        "selectedCourses": ["calc_bc"],
        "notifications": {
            "enabled": False,
            "channels": [],
            "quietHours": {"start": "21:00", "end": "08:00"},
        },
    },
    "masterySummary": {
        "calc_bc.function-composition": {
            "level": "insufficient_evidence",
            "independentEvidenceCount": 0,
        }
    },
    "predictionSummary": {"calc_bc": {"status": "unavailable", "reason": "not_calibrated"}},
    "latestEventSequence": 18,
}

ENTITLEMENTS = {"apCourses": ["calc_bc"], "dsat": True, "admissions": False}

PACK = {
    "courseId": "calc_bc",
    "name": "AP Calculus BC",
    "version": "1.0.0",
    "availability": "active",
    "supportedTaskTypes": ["SOCRATIC_STUDY", "FRQ_PRACTICE"],
    "supportedModes": ["GPA_SYNC", "EXAM_CRUNCH"],
}

TASK: dict[str, Any] = {
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
    "reason": {"code": "INITIAL_PRACTICE", "sourceEventIds": []},
}

SESSION: dict[str, Any] = {
    "sessionId": "sess_01",
    "taskId": "task_calc_01",
    "status": "OPEN",
    "activeRunId": None,
    "contextVersion": {"pack": "1.0.0", "workflow": "calc-practice-v1"},
    "completion": {"eligible": False, "reason": "accepted_assessment_required"},
}

RUN: dict[str, Any] = {
    "runId": "run_01",
    "sessionId": "sess_01",
    "status": "QUEUED",
    "kind": "ASSESS_SUBMISSION",
    "submissionId": "sub_01",
    "attemptCount": 0,
    "inputRequest": None,
    "result": None,
}

SUBMISSION_REQUEST: dict[str, Any] = {
    "questionId": "q_calc_01",
    "questionVersion": "1",
    "answer": {"text": "My derivation ...", "fileIds": []},
    "supersedesSubmissionId": None,
}

ASSESSMENT: dict[str, Any] = {
    "assessmentId": "assess_01",
    "submissionId": "sub_01",
    "sessionId": "sess_01",
    "runId": "run_01",
    "status": "accepted",
    "questionVersion": "1",
    "rubricVersion": "calc-composition-v1",
    "rubricResults": [
        {
            "criterionId": "identify-inner-function",
            "earned": 1,
            "possible": 1,
            "evidenceRefs": ["sub_01:text:0-42"],
        }
    ],
    "hintUsage": {"serverHintCount": 1},
    "skillEvidence": [
        {"skillId": "calc_bc.function-composition", "observation": "correct_with_hint"}
    ],
    "uncertainty": {"level": "limited", "reasons": ["single_assisted_attempt"]},
    "provenance": {
        "modelVersion": "configured-model-version",
        "workflowVersion": "calc-practice-v1",
        "toolResultIds": [],
    },
    "supersedesAssessmentId": None,
}

EVENT: dict[str, Any] = {
    "eventId": "evt_19",
    "sequence": 19,
    "schemaVersion": 1,
    "studentId": "stu_alex",
    "sessionId": "sess_01",
    "runId": "run_01",
    "type": "assessment.completed",
    "occurredAt": "2026-10-29T17:00:00Z",
    "causationId": "sub_01",
    "payload": {"assessmentId": "assess_01", "status": "accepted"},
}

CATALOG = {
    "courses": [
        {
            "courseId": "calc_bc",
            "name": "AP Calculus BC",
            "description": "Covers limits, derivatives, integrals, and series.",
            "category": "AP",
            "availability": "active",
            "entitled": True,
            "enrolled": True,
            "status": "enrolled",
            "agent": {
                "agentType": "AP_BASE",
                "modes": ["GPA_SYNC", "EXAM_CRUNCH"],
                "supportedTaskTypes": ["SOCRATIC_STUDY", "FRQ_PRACTICE"],
            },
        },
        {
            "courseId": "apush",
            "name": "AP US History",
            "description": "American history from pre-Columbian era to present.",
            "category": "AP",
            "availability": "planned",
            "entitled": False,
            "enrolled": False,
            "status": "coming_soon",
            "agent": {"agentType": "AP_BASE", "modes": [], "supportedTaskTypes": []},
        },
    ]
}

ENROLLMENT = {"courseId": "calc_bc", "enrolledAt": "2026-10-30T08:00:00Z", "status": "active"}

ENROLLED = {
    "enrollments": [
        {
            "courseId": "calc_bc",
            "name": "AP Calculus BC",
            "enrolledAt": "2026-10-30T08:00:00Z",
            "status": "active",
            "agent": {
                "agentType": "AP_BASE",
                "modes": ["GPA_SYNC", "EXAM_CRUNCH"],
                "supportedTaskTypes": ["SOCRATIC_STUDY", "FRQ_PRACTICE"],
            },
        }
    ]
}

COURSE_AGENT = {
    "courseId": "calc_bc",
    "agentType": "AP_BASE",
    "name": "AP Calculus BC",
    "modes": ["GPA_SYNC", "EXAM_CRUNCH"],
    "supportedTaskTypes": ["SOCRATIC_STUDY", "FRQ_PRACTICE"],
    "activeSessions": [],
    "masterySummary": {
        "calc_bc.function-composition": {
            "level": "insufficient_evidence",
            "independentEvidenceCount": 0,
        }
    },
}

ERROR = {
    "error": {
        "code": "RUN_IN_PROGRESS",
        "message": "A run is already active in this session.",
        "requestId": "req_01",
        "retryable": False,
    }
}

EVENT_PAGE = {"events": [], "nextAfter": 18, "hasMore": False}
MESSAGE_REQUEST = {"text": "Can you help me identify the inner function?", "fileIds": []}
MESSAGE_ACCEPTED = {"messageId": "msg_01", "runId": "run_hint_01", "status": "QUEUED"}
SUBMISSION_ACCEPTED = {"submissionId": "sub_01", "runId": "run_01", "status": "QUEUED"}
RUN_INPUT = {"inputRequestId": "input_ocr_01", "value": {"confirmedText": "f(g(x))"}}
