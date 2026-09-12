#!/usr/bin/env python3
"""Export the live paired questionnaire contract from its runtime source."""
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "realtime_pilot"))

from common import digest  # noqa: E402
from paired_contract import CONTEXT, QUESTIONNAIRE_VERSION, QUESTIONS, VERSION  # noqa: E402
from proposal_contract import FEEDBACK_VERSION, SCORE_FIELDS  # noqa: E402


def document():
    return {
        "schema_version": QUESTIONNAIRE_VERSION,
        "status": "runtime_authoritative",
        "paired_flow_version": VERSION,
        "unit": "one household represented by one respondent",
        "question_count": len(QUESTIONS),
        "questions_sha256": digest(QUESTIONS),
        "scenario_sampling": {
            "event_start_hours": [17, 18, 19],
            "event_duration_hours": [1, 2],
            "conditioned_on_response": False,
        },
        "tariff": CONTEXT["tariff"],
        "feedback_contract": {
            "version": FEEDBACK_VERSION,
            "decision": ["accept", "reject"],
            "score_fields": list(SCORE_FIELDS),
            "score_range": [1, 5],
            "decimal_scores_allowed": True,
            "comment_required": True,
            "comment_max_chars": 1000,
        },
        "questions": QUESTIONS,
    }


if __name__ == "__main__":
    output = ROOT / "QUESTIONNAIRE_CODEBOOK.json"
    output.write_text(json.dumps(document(), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(output)
