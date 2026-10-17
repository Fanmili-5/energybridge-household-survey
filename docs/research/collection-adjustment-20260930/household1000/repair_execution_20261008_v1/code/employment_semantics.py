"""Decode CHFS questionnaire evidence; never infer a job or retirement from age.

A3100a: 1=current work, same main job; 2=current work, changed main job;
3=no current work. A3132b and A3131a are separate prior-work/skip fields.
Outputs describe auxiliary source evidence, not observed synthetic persons.
"""

CURRENT = {
    1: ("has_work", "same_main_job_as_last_year"),
    2: ("has_work", "changed_main_job_since_last_year"),
    3: ("no_current_work", "not_applicable"),
}
NO_WORK_REASONS = {
    1: "disability_or_illness_reason", 2: "school_reason", 3: "retirement_reason",
    4: "involuntary_job_loss_reason", 5: "personal_job_loss_reason",
    6: "land_change_reason", 7: "housework_reason", 8: "never_worked_after_graduation_reason",
    9: "old_age_unable_to_work_reason", 7777: "other_reason",
}


def decode_current_work(proxy, last_year_work=None, no_work_reason=None):
    if isinstance(proxy, bool):
        raise ValueError("boolean is not a CHFS work code")
    current, continuity = CURRENT.get(proxy, ("unknown", "unknown"))
    source_conflict = last_year_work == 1 and no_work_reason is not None
    if proxy in CURRENT:
        missing_kind = "not_missing"
    elif proxy is not None:
        missing_kind = "unrecognized_code_preserved"
    elif source_conflict:
        missing_kind = "secondary_skip_inputs_need_review"
    elif last_year_work == 2 and no_work_reason in (1, 3, 9):
        missing_kind = "questionnaire_structural_skip_supported"
    elif no_work_reason is not None:
        missing_kind = "reason_available_skip_not_confirmed"
    else:
        missing_kind = "unasked_or_missing_not_identified"
    return {
        "source_A3100a": proxy, "current_work_evidence": current,
        "main_job_continuity_evidence": continuity, "missing_kind": missing_kind,
        "source_A3132b": last_year_work, "source_A3131a": no_work_reason,
        "source_no_work_reason_evidence": NO_WORK_REASONS.get(no_work_reason),
        "secondary_source_conflict": source_conflict,
        "retirement_or_activity_assigned": False,
        "evidence_scope": "auxiliary coarsened source evidence; not observed current job of synthetic role",
    }
