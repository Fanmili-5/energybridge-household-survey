"""Apply REVIEW_023 to a new child; preserve all F-reviewed parent bytes."""
from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
TRIAL = HERE.parent
STAGE = TRIAL.parent
PARENT_PROFILE = HERE / "profile_300_v2_c_bound.json"
PARENT_BEHAVIOR = HERE / "behavior_300_v2_c_bound.json"
STATIC_PROFILE = HERE / "profile_300_v2.json"
C_BUILDING = TRIAL / "C_idf" / "building_300.json"
C_READY = TRIAL / "C_idf" / "C_BINDING_MANIFEST.json"
DECISION = STAGE / "REVIEW_023_COMPACT_SHARED_CONTROL_SCOPE.md"
PROFILE_OUT = HERE / "profile_300_v2_c_control1.json"
BEHAVIOR_OUT = HERE / "behavior_300_v2_c_control1.json"
LEDGER_OUT = HERE / "COMPACT_SHARED_CONTROL_LEDGER.json"
REPORT_OUT = HERE / "COMPACT_SHARED_CONTROL_VALIDATION.json"
PARENT_PROFILE_SHA = "e17b7efe455705169a0659054844d40d45822fa37b80ddc967e470df2780b202"
PARENT_BEHAVIOR_SHA = "057556553077e1da48ee4822db9e71643112674f34c26f491c3300fd15b9f18b"
STATIC_PROFILE_SHA = "d1c0b162ac122cb36ac202c778d7ff00956bd3e63fc08643bebd8ac96ff9a168"
C_SHA = "bb063fb494fd5d1ca8faaeafafab1444fe9f1fe6cd54b09ee5657e19dc957c0d"
COMPACT = {"cityrole-0025", "cityrole-0074", "cityrole-0134", "cityrole-0232",
           "cityrole-0249", "cityrole-0275", "cityrole-0279"}
COUNT_CHANGED = {"cityrole-0025", "cityrole-0249"}


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def read(path):
    return json.loads(path.read_text(encoding="utf-8"))


def write(path, data):
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def validate_inputs():
    if (sha(PARENT_PROFILE) != PARENT_PROFILE_SHA or sha(PARENT_BEHAVIOR) != PARENT_BEHAVIOR_SHA or
            sha(STATIC_PROFILE) != STATIC_PROFILE_SHA or sha(C_BUILDING) != C_SHA):
        raise ValueError("reviewed C-bound/static B or C bytes changed")
    ready = read(C_READY)
    if ready["C_building_sha256"] != C_SHA or ready["B_reviewed_profile_sha256"] != STATIC_PROFILE_SHA:
        raise ValueError("C ready manifest no longer binds inputs")
    if {x["role_id"] for x in ready["shared_private_room_7m2_design_pressure"]} != COMPACT:
        raise ValueError("C compact shared role set changed")
    decision = DECISION.read_text(encoding="utf-8")
    if not all(token in decision for token in ("0025", "0249", "最多选择面积最大的一个本户私用热区")):
        raise ValueError("root control-scope decision text changed")
    return ready


def apply_one(parent, static, compact):
    row = copy.deepcopy(parent)
    rid = row["role_id"]
    q = row["questionnaire_answers"]
    old_count = int(static["questionnaire_answers"]["X_COUNT_ac"]["value"]) if "ac" in static["eb_intervention_devices"] else 0
    row["eb_ac_controllable_unit_count"] = old_count
    if not compact:
        return row, None
    if rid in COUNT_CHANGED and old_count != 2:
        raise ValueError(f"{rid}: expected 2 prior synthetic AC units")
    if rid not in COUNT_CHANGED and old_count > 1:
        raise ValueError(f"{rid}: unlisted multi-AC compact role")
    eb_count = min(old_count, 1)
    binding = row["physical_binding"]
    if "eb_ac_selected_zones" in binding:
        raise ValueError(f"{rid}: actual D selected zones leaked into C-bound parent")
    row["eb_ac_controllable_unit_count"] = eb_count
    binding["eb_ac_selection_policy"] = (
        "largest_one_household_private_zone_pending_D_assignment" if eb_count else "not_applicable_no_EB_AC")
    binding["eb_ac_zone_assignment_status"] = (
        "pending_D_largest_private_zone_assignment" if eb_count else "not_applicable_no_EB_AC")
    row["physical_review_flags"].append("v2_REVIEW_023_compact_shared_control_scope_pending_D_F")
    if eb_count:
        row["device_control_scope"]["ac"] = "one_largest_private_zone_candidate_pending_D_assignment_F_review"
        row["device_access_resolution"]["ac"].update({
            "prior_synthetic_owned_count": old_count,
            "unmodeled_owned_count": old_count - eb_count,
            "count_scope_reason": "REVIEW_023_conservative_experimental_control_not_installation_impossibility"})
        row["ordinary_operation_conditions"]["ac"] = (
            parent["ordinary_operation_conditions"]["ac"] +
            " 本轮紧凑合住仅一台空调进入EB控制及电量代理；其他原合成设备不计入该代理。")
    row["intervention_eligibility"]["effective_DR_case_allowed"] = False
    row["role_card_short"] += (
        f" 紧凑合住控制范围：原合成拥有空调{old_count}台，本轮EB最多纳入{eb_count}台；"
        "实际选区待D生成，未纳入设备不计入本轮电量代理；房间使用和安装未验证。")
    return row, {"role_id": rid, "prior_synthetic_owned_AC_count": old_count,
                 "EB_controllable_AC_count": eb_count, "unmodeled_owned_AC_count": old_count - eb_count,
                 "prior_X_COUNT_ac": static["questionnaire_answers"]["X_COUNT_ac"] if old_count else None,
                 "new_X_COUNT_ac": q["X_COUNT_ac"] if eb_count else None,
                 "X_COUNT_ac_preserved_as_total_owned": True,
                 "reason": "REVIEW_023_one_largest_private_zone_conservative_control_scope_not_physical_impossibility"}


def main():
    validate_inputs()
    parent, behavior_parent, static = map(read, (PARENT_PROFILE, PARENT_BEHAVIOR, STATIC_PROFILE))
    ids = [f"cityrole-{i:04d}" for i in range(1, 301)]
    pr, br, sr = parent["profiles"], behavior_parent["records"], static["profiles"]
    if any([r["role_id"] for r in rows] != ids for rows in (pr, br, sr)):
        raise ValueError("role order differs")
    profiles, changes = [], []
    for p, s in zip(pr, sr):
        row, change = apply_one(p, s, p["role_id"] in COMPACT)
        profiles.append(row)
        if change:
            changes.append(change)
    if {x["role_id"] for x in changes} != COMPACT or {x["role_id"] for x in changes if x["unmodeled_owned_AC_count"]} != COUNT_CHANGED:
        raise ValueError("REVIEW_023 changed-role set differs")
    child = {k: copy.deepcopy(v) for k, v in parent.items() if k != "profiles"}
    child.update({"schema_version": "eb.synthetic_fixed_profile_300.v2_trial_C_control1",
                  "parent_C_bound_profile_sha256": PARENT_PROFILE_SHA,
                  "parent_C_bound_behavior_sha256": PARENT_BEHAVIOR_SHA,
                  "root_control_scope_decision_sha256": sha(DECISION),
                  "fixed_profile_ready": False, "training_release": False,
                  "profiles": profiles})
    write(PROFILE_OUT, child)
    behavior_rows = []
    for prior, profile in zip(br, profiles):
        row = copy.deepcopy(prior)
        row["device_control_scope"] = copy.deepcopy(profile["device_control_scope"])
        row["device_access_resolution"] = copy.deepcopy(profile["device_access_resolution"])
        row["ordinary_operation_conditions"] = copy.deepcopy(profile["ordinary_operation_conditions"])
        row["prior_device_habits_unverified"] = copy.deepcopy(profile["prior_device_habits_unverified"])
        row["prior_device_conditions_unverified"] = copy.deepcopy(profile["prior_device_conditions_unverified"])
        row["intervention_eligibility"] = copy.deepcopy(profile["intervention_eligibility"])
        row["eb_ac_zone_assignment_status"] = profile["physical_binding"]["eb_ac_zone_assignment_status"]
        row["eb_ac_controllable_unit_count"] = profile["eb_ac_controllable_unit_count"]
        row["eb_ac_selection_policy"] = profile["physical_binding"].get("eb_ac_selection_policy")
        behavior_rows.append(row)
    behavior = {"schema_version": "eb.synthetic_fixed_behavior_300.v2_trial_C_control1", "n": 300,
                "parent_C_bound_behavior_sha256": PARENT_BEHAVIOR_SHA,
                "C_building_sha256": C_SHA,
                "root_control_scope_decision_sha256": sha(DECISION),
                "B_C_control1_profile_sha256": sha(PROFILE_OUT),
                "scope": "REVIEW_023_compact_shared_EB_unit_limit_not_owned_inventory_or_actual_D_zone_assignment",
                "records": behavior_rows}
    write(BEHAVIOR_OUT, behavior)
    write(LEDGER_OUT, {"status": "REVIEW_023_CONTROL_SCOPE_APPLIED_TO_C_BOUND_CHILD", "n": len(changes),
                       "parent_C_bound_profile_sha256": PARENT_PROFILE_SHA,
                       "child_profile_sha256": sha(PROFILE_OUT), "decision_sha256": sha(DECISION),
                       "records": changes})
    report = {"status": "CONTROL_SCOPE_CHILD_READY_PENDING_D_ZONE_ASSIGNMENT_AND_F_REVIEW", "n": 300,
              "parent_C_bound_profile_sha256": PARENT_PROFILE_SHA,
              "parent_C_bound_behavior_sha256": PARENT_BEHAVIOR_SHA,
              "C_building_sha256": C_SHA, "decision_sha256": sha(DECISION),
              "child_profile_sha256": sha(PROFILE_OUT), "child_behavior_sha256": sha(BEHAVIOR_OUT),
              "compact_shared_roles": sorted(COMPACT), "AC_count_reduced_roles": sorted(COUNT_CHANGED),
              "D_actual_zone_assignment_ready": False, "simulation_ready": False, "CSV_release_ready": False,
              "human_responses": 0}
    write(REPORT_OUT, report)
    print(json.dumps(report, ensure_ascii=False))


if __name__ == "__main__":
    main()
