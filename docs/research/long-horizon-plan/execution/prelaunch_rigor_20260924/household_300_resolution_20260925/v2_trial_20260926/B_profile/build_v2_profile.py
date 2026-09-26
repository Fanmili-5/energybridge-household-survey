"""Isolated v2 role adaptation. Never edits the released A/B/C/E chain."""
from __future__ import annotations

import collections
import copy
import hashlib
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
TRIAL = HERE.parent
FROZEN = TRIAL.parent
ROOT = FROZEN.parents[5]
A_PATH = TRIAL / "A_structure" / "family_300_v2.json"
A_READY = TRIAL / "READY_A.md"
A_MANIFEST = TRIAL / "SELECTION_MANIFEST.json"
OLD_A = FROZEN / "A_structure" / "family_300.json"
OLD_B = FROZEN / "B_profile" / "profile_300.json"
OLD_BEHAVIOR = FROZEN / "B_profile" / "behavior_300.json"
CODEBOOK = ROOT / "QUESTIONNAIRE_CODEBOOK.json"
PROFILE_OUT = HERE / "profile_300_v2.json"
BEHAVIOR_OUT = HERE / "behavior_300_v2.json"
LEDGER_OUT = HERE / "CHANGE_LEDGER_300.json"
VALIDATION_OUT = HERE / "MAPPING_VALIDATION.json"
PRESSURE_OUT = HERE / "SPACE_PRESSURE_REVIEW.json"
DEVICES = ("ac", "washer", "dishwasher", "dryer", "electric_water_heater", "home_ev")


def read(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write(path: Path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def rows(data):
    for key in ("records", "families", "households", "profiles"):
        if isinstance(data.get(key), list):
            return data[key]
    raise ValueError("300-row array missing")


def is_shared(family):
    return family["dwelling"]["housing_form_design"].startswith("shared")


def area_category(area):
    return "lt50" if area < 50 else "50_89" if area < 90 else "90_119" if area < 120 else "120_159" if area < 160 else "ge160"


def answer(value, basis, status="answered", reason=None):
    cell = {"value": value, "response_status": status, "basis": basis}
    if reason:
        cell["reason"] = reason
    return cell


def update_answer(profile, qid, value, basis, changes, reason, *, status="answered"):
    old = profile["questionnaire_answers"][qid]
    new = answer(value, basis, status, reason if status != "answered" else None)
    profile["questionnaire_answers"][qid] = new
    if old != new:
        changes.append({"path": f"questionnaire_answers.{qid}", "old": old, "new": new, "reason": reason})


def preserve_member_identity(new_family, old_family, old_profile):
    for key in ("role_id", "family_size", "generation_category", "location"):
        if new_family[key] != old_family[key]:
            raise ValueError(f"{new_family['role_id']}: frozen identity field changed: {key}")
    old_members = old_family["members"]
    new_members = new_family["members"]
    if len(new_members) != len(old_members) or len(new_members) != len(old_profile["members"]):
        raise ValueError(f"{new_family['role_id']}: member count changed")
    keys = ("member_id", "age_years_design", "relationship_to_reference_adult", "parent_member_ids", "partner_member_id")
    for prior, current in zip(old_members, new_members):
        for key in keys:
            if prior.get(key) != current.get(key):
                raise ValueError(f"{new_family['role_id']}: member identity changed: {key}")
    old_dw = old_family["dwelling"]
    new_dw = new_family["dwelling"]
    for key in ("room_count_census_h7_category", "room_count_design_minimum"):
        if old_dw[key] != new_dw[key]:
            raise ValueError(f"{new_family['role_id']}: frozen H7 changed: {key}")


def legal_devices(profile, new_family):
    old = list(profile["device_ownership"])
    area = new_family["dwelling"]["design_total_building_area_m2"]
    shared = is_shared(new_family)
    kept = []
    removals = []
    for device in old:
        reason = None
        if shared and device != "ac":
            reason = "shared_household_has_no_verified_private_laundry_kitchen_bath_or_charger_control"
        elif not shared and area < 40 and device in ("dishwasher", "dryer"):
            reason = "v2_whole_dwelling_area_below_existing_40m2_device_screen"
        elif not shared and area < 50 and device == "home_ev":
            reason = "v2_whole_dwelling_area_below_existing_50m2_home_charging_screen"
        if reason:
            removals.append({"device": device, "reason": reason})
        else:
            kept.append(device)
    return kept, removals


def exact_field_changes(old, new, prefix=""):
    if isinstance(old, dict) and isinstance(new, dict):
        for key in sorted(set(old) | set(new)):
            path = f"{prefix}.{key}" if prefix else key
            if key not in old or key not in new:
                yield path, old.get(key), new.get(key)
            else:
                yield from exact_field_changes(old[key], new[key], path)
    elif old != new:
        yield prefix, old, new


def field_reason(path):
    head = path.split(".")[0]
    if head == "dwelling_interface":
        return "A_v2_area_housing_and_experimental_net_design_or_pending_v2_C_binding"
    if head in ("physical_binding", "physical_review_flags"):
        return "old_C_geometry_IDF_and_control_zones_invalid_for_A_v2"
    if head in ("device_ownership", "device_control_scope", "ordinary_operation_conditions",
                "home_ev_driver_member_id", "home_charging_access", "prior_synthetic_device_inventory",
                "device_access_resolution", "prior_device_habits_unverified", "intervention_eligibility",
                "eb_intervention_devices", "prior_home_ev_driver_member_id", "prior_device_conditions_unverified"):
        return "device_availability_and_private_control_rechecked_under_A_v2_housing"
    if head == "questionnaire_answers":
        qid = path.split(".")[1]
        if qid in ("X_BUILDING", "X_FLOOR", "X_BUILDING_AGE"):
            return "prior_experimental_building_context_pending_v2_C_check"
        if qid in ("B05", "X_AREA", "X_AREA_BASIS", "X_TENURE", "X_EXTRA_DEVICES", "X_COUNT_ac"):
            return "A_v2_housing_area_or_control_scope_recomputed"
        if qid.startswith(("H_", "D_", "E_", "T_", "P_", "X_COUNT_", "X_FREQ_")):
            return "device_changed_questionnaire_applicability_recomputed"
        raise ValueError(f"unrecognized changed questionnaire field: {path}")
    if head in ("family_source", "role_card_short", "evidence_identity"):
        return "v2_trial_identity_and_role_description_refreshed_without_new_human_answer"
    raise ValueError(f"unexpected changed profile field: {path}")


def adapt_one(old_family, new_family, original, codebook):
    preserve_member_identity(new_family, old_family, original)
    role_id = original["role_id"]
    profile = copy.deepcopy(original)
    changes = []
    old_dw, new_dw = old_family["dwelling"], new_family["dwelling"]
    old_shared, shared = is_shared(old_family), is_shared(new_family)
    area = new_dw["design_total_building_area_m2"]
    if not isinstance(area, (int, float)) or area <= 0:
        raise ValueError(f"{role_id}: invalid v2 area")
    household_net = new_dw["modeled_net_area_design_m2"]
    if not isinstance(household_net, (int, float)) or household_net <= 0 or household_net > area:
        raise ValueError(f"{role_id}: invalid A v2 experimental net-area design")
    if old_dw["design_total_building_area_m2"] != area:
        changes.append({"path": "dwelling_interface.design_total_building_area_m2",
                        "old": old_dw["design_total_building_area_m2"], "new": area,
                        "reason": "A_v2_selected_size_copula_raw_H6_numeric_area"})
    if old_shared != shared:
        changes.append({"path": "dwelling_interface.housing_form_design", "old": old_dw["housing_form_design"],
                        "new": new_dw["housing_form_design"], "reason": "A_v2_experimental_housing_branch"})
    old_interface = original["dwelling_interface"]
    new_whole = None if shared else area
    if old_interface["whole_dwelling_building_area_design_m2"] != new_whole:
        changes.append({"path": "dwelling_interface.whole_dwelling_building_area_design_m2",
                        "old": old_interface["whole_dwelling_building_area_design_m2"], "new": new_whole,
                        "reason": "v2_whole_dwelling_known_only_for_independent_A_area_pending_C_for_shared"})
    new_whole_net = None if shared else household_net
    if old_interface["whole_dwelling_modeled_net_floor_area_m2"] != new_whole_net:
        changes.append({"path": "dwelling_interface.whole_dwelling_modeled_net_floor_area_m2",
                        "old": old_interface["whole_dwelling_modeled_net_floor_area_m2"], "new": new_whole_net,
                        "reason": "A_v2_experimental_net_design_not_v2_C_geometry" if not shared else
                                  "shared_whole_unit_net_pending_v2_C_geometry"})
    changes.append({"path": "dwelling_interface.household_modeled_net_area_design_m2", "old": None,
                    "new": household_net, "reason": "A_v2_experimental_H6_to_net_design_ratio"})
    if original["physical_binding"] is not None:
        changes.append({"path": "physical_binding", "old_idf_sha256": original["physical_binding"]["idf_sha256"],
                        "new": None, "reason": "old_C_IDF_and_zones_cannot_bind_v2_area"})

    dwelling = profile["dwelling_interface"]
    dwelling.update({"design_total_building_area_m2": area, "area_basis": new_dw["area_basis"],
                     "housing_form_design": new_dw["housing_form_design"],
                     "room_count_census_h7_category": new_dw["room_count_census_h7_category"],
                     "room_count_design_minimum": new_dw["room_count_design_minimum"],
                     "physical_whole_dwelling_building_area_m2": new_dw.get("physical_whole_dwelling_building_area_m2"),
                     "whole_dwelling_building_area_design_m2": new_whole,
                     "household_modeled_net_area_design_m2": household_net,
                     "whole_dwelling_modeled_net_floor_area_m2": new_whole_net,
                     "household_net_area_evidence": "A_v2_experimental_H6_to_net_design_ratio_not_C_geometry",
                     "whole_dwelling_area_evidence": "pending_v2_C_source_unit_geometry" if shared else new_dw["area_basis"],
                     "private_control_scope": "assigned_private_rooms_ac_only_pending_C_zone" if shared else "household_selected_devices_pending_C_zone",
                     "binding_status": "awaiting_v2_C_IDF_and_zone_review"})
    # An old IDF, its floor/area and its controllable zones cannot be inherited.
    profile["physical_binding"] = None
    profile["physical_review_flags"] = ["v2_C_geometry_and_control_zone_pending"]
    if shared:
        profile["physical_review_flags"].append("v2_shared_whole_dwelling_area_pending")
    if "exploratory_7m2_per_person_plus_service_pressure" in new_dw.get("area_v2_review_flags", []):
        profile["physical_review_flags"].append("v2_exploratory_occupancy_space_pressure_review")
    profile["family_source"] = "A_structure_v2_trial"

    kept, removals = legal_devices(profile, new_family)
    # The prior synthetic inventory is a role condition. A changed residence
    # does not prove an appliance disappeared, nor that it remains accessible.
    profile["prior_synthetic_device_inventory"] = list(original["device_ownership"])
    profile["device_access_resolution"] = {
        d: {"prior_synthetic_ownership": True,
            "v2_access_status": "assumed_private_pending_C" if d in kept else "unknown_in_v2_dwelling",
            "v2_EB_control_status": "provisional_pending_C" if d in kept else "not_included_unverified",
            "v2_EB_included": d in kept,
            "reason": next((x["reason"] for x in removals if x["device"] == d), "retained_prior_role_device_pending_C_control_review")}
        for d in original["device_ownership"]}
    prior_q = original["questionnaire_answers"]
    profile["prior_device_habits_unverified"] = {
        d: {qid: copy.deepcopy(cell) for qid, cell in prior_q.items()
            if (qid.endswith("_" + d) or qid in ({"P_AC_RANGE", "P_AC_CHANGE"} if d == "ac" else
                {"P_EV_TARGET", "P_EV_RESERVE"} if d == "home_ev" else
                {"P_HOT_WATER", "P_PREHEAT"} if d == "electric_water_heater" else set()))
            and cell["response_status"] == "answered"}
        for d in original["device_ownership"] if d not in kept}
    profile["prior_device_conditions_unverified"] = {
        d: original["ordinary_operation_conditions"][d]
        for d in original["device_ownership"] if d not in kept}
    for removal in removals:
        changes.append({"path": f"eb_intervention_devices.{removal['device']}", "old": "included", "new": "excluded_pending_access_review",
                        "reason": removal["reason"]})
    if not kept:
        profile["physical_review_flags"].append("no_verified_exclusive_EB_device_after_v2_housing_screen")
    profile["intervention_eligibility"] = {
        "status": "pending_v2_C_control_review" if kept else "no_currently_controllable_EB_device",
        "effective_DR_case_allowed": False,
        "reason": "v2_C_geometry_and_device_control_not_yet_verified" if kept else
                  "prior_devices_remain_role_background_but_none_has_verified_exclusive_control_in_v2_dwelling"}
    profile["device_ownership"] = list(original["device_ownership"])
    profile["eb_intervention_devices"] = kept
    profile["device_control_scope"] = {
        d: ("private_room_unit_pending_C_zone" if shared else
            "assigned_home_charger_pending_C_parking" if d == "home_ev" else
            "household_owned_private_device_pending_C_zone" if d == "ac" else
            "household_owned_private_device") for d in kept}
    profile["ordinary_operation_conditions"] = {
        d: (original["ordinary_operation_conditions"][d] if d in original["ordinary_operation_conditions"] else
            "有人在待C核定的私有受控房间时使用；空屋预冷须另确认预约或远控及许可，空屋冷量不算舒适收益。")
        for d in kept}
    profile["prior_home_ev_driver_member_id"] = original["home_ev_driver_member_id"]
    if "home_ev" not in kept:
        profile["home_ev_driver_member_id"] = None
        profile["home_charging_access"] = None if "home_ev" in original["device_ownership"] else False
    if original["device_control_scope"] != profile["device_control_scope"]:
        changes.append({"path": "device_control_scope", "old": original["device_control_scope"],
                        "new": profile["device_control_scope"], "reason": "v2_housing_branch_and_C_zone_rights_rechecked"})
    if old_shared and not shared:
        changes.append({"path": "eb_intervention_devices", "old": original["device_ownership"], "new": kept,
                        "reason": "no_new_appliance_inferred_when_shared_home_becomes_independent"})

    update_answer(profile, "B05", kept if kept else ["none"], "v2_EB_selected_device_scope_not_physical_inventory", changes,
                  "device_availability_and_exclusive_control_rechecked_under_v2_housing")
    update_answer(profile, "X_AREA_BASIS", "gross", new_dw["area_basis"], changes,
                  "v2_H6_like_building_area_basis")
    if shared:
        update_answer(profile, "X_AREA", None, "pending_v2_C_whole_dwelling_geometry", changes,
                      "EB_question_asks_whole_dwelling_area_for_shared_home", status="pending_physical_binding")
    else:
        update_answer(profile, "X_AREA", area_category(area), new_dw["area_basis"], changes,
                      "independent_whole_dwelling_equals_A_v2_H6_area")
    if shared != old_shared:
        tenure = "shared" if shared else "rented"
        # Prior tenure of a shared role is unrecoverable; rented is an explicit
        # experimental tenure scenario, never a claim about a source household.
        update_answer(profile, "X_TENURE", tenure, "v2_experimental_tenure_scenario", changes,
                      "housing_branch_changed_tenure_must_be_reassigned_explicitly")
        update_answer(profile, "X_EXTRA_DEVICES", ["none"] if shared else ["refrigerator"],
                      "v2_experimental_background_appliance_scenario", changes,
                      "housing_branch_changed_background_device_access_rechecked")
    if shared and "ac" in kept:
        old_count = profile["questionnaire_answers"]["X_COUNT_ac"]["value"]
        cap = new_dw["room_count_design_minimum"]
        if int(old_count) > cap:
            update_answer(profile, "X_COUNT_ac", str(cap), "v2_private_room_count_cap_pending_C_zones", changes,
                          "shared_AC_count_cannot_exceed_H7_private_room_design_minimum")

    qmap = {q["id"]: q for q in codebook["questions"]}
    for qid, q in qmap.items():
        device = q.get("required_when", {}).get("selected_device")
        show = q.get("required_when", {}).get("show_when") or q.get("show_when")
        applicable = (not device or device in kept) and (not show or
                      profile["questionnaire_answers"][show["question_id"]]["value"] == show["value"])
        cell = profile["questionnaire_answers"][qid]
        if not applicable and cell["response_status"] != "not_applicable":
            update_answer(profile, qid, None, "questionnaire_skip_rule", changes,
                          "device_removed_or_show_when_false", status="not_applicable")
        elif applicable and cell["response_status"] == "not_applicable":
            raise ValueError(f"{role_id}: newly applicable question has no preserved value: {qid}")
    # C-derived source type, floor and age remain readable scenarios, with
    # explicit provisional basis. They must be checked again against v2 C.
    for qid in ("X_BUILDING", "X_FLOOR", "X_BUILDING_AGE"):
        cell = profile["questionnaire_answers"][qid]
        if cell["response_status"] == "answered":
            cell["basis"] = "prior_experimental_context_pending_v2_C_check"
    dwelling["building_type"] = profile["questionnaire_answers"]["X_BUILDING"]["value"]
    dwelling["floor_position"] = profile["questionnaire_answers"]["X_FLOOR"]["value"]
    profile["evidence_identity"]["whole_dwelling_area"] = (
        "pending_v2_C_source_unit_geometry" if shared else "A_v2_synthetic_whole_dwelling_area")
    profile["evidence_identity"]["family"] = "A_v2_population_marginal_plus_experimental_local_size_area_rank"
    profile["role_card_short"] = (
        f"【v2隔离合成角色；无真人回答】{role_id}｜{profile['province']}{profile['city']}｜"
        f"{profile['family_size']}人。"
        + (f"合住：本户独用{new_dw['room_count_design_minimum']}间自然房，分摊建筑面积约{area:g}㎡；"
           "整套建筑面积待v2物理单元确定，其他住户人数未知。"
           if shared else f"独立住房建筑面积约{area:g}㎡，H7至少{new_dw['room_count_design_minimum']}间自然房。")
        + f"原合成设备背景：{','.join(original['device_ownership'])}；本次EB拟纳入：{','.join(kept) if kept else '无可控设备'}。"
        + f"典型在家情况：{profile['usual_presence']['weekday_day']}。"
        + f"月收入/电费仅为实验情境：{profile['economic_context']['monthly_household_income_scenario_yuan']}/"
          f"{profile['economic_context']['monthly_electricity_bill_scenario_yuan']}元。"
        + "成员生活作息、态度、通知偏好和其余适用设备时钟沿用同一角色原值；实际受控房间待v2 C核定。"
    )
    return profile, changes, removals


def main():
    if not (A_PATH.exists() and A_READY.exists() and A_MANIFEST.exists()):
        raise SystemExit("A v2 is not ready: family_300_v2.json, SELECTION_MANIFEST.json and READY_A.md required")
    old_a, new_a, old_b, old_behavior, codebook = map(read, (OLD_A, A_PATH, OLD_B, OLD_BEHAVIOR, CODEBOOK))
    selection = read(A_MANIFEST)
    if (selection.get("family_v2_sha256") != sha(A_PATH) or
            selection.get("frozen_family_sha256") != sha(OLD_A) or
            selection.get("method") != "size_copula_raw" or selection.get("seed") != 0 or
            selection.get("identity_city_size_members_H7_preserved") is not True):
        raise ValueError("A v2 selection manifest does not bind the selected family and frozen base")
    if sha(A_PATH) not in A_READY.read_text(encoding="utf-8"):
        raise ValueError("READY_A does not name the selected A v2 bytes")
    old_rows, new_rows, old_profiles = rows(old_a), rows(new_a), rows(old_b)
    ids = [f"cityrole-{i:04d}" for i in range(1, 301)]
    if any(len(x) != 300 for x in (old_rows, new_rows, old_profiles)):
        raise ValueError("all A/B inputs must contain 300 rows")
    if [r["role_id"] for r in old_rows] != ids or [r["role_id"] for r in new_rows] != ids or [r["role_id"] for r in old_profiles] != ids:
        raise ValueError("A/B role sequence changed")
    if old_b["source_sha256"]["A_family"] != sha(OLD_A):
        raise ValueError("old profile does not bind current frozen A")
    if old_b["behavior_subset_sha256"] != sha(OLD_BEHAVIOR):
        raise ValueError("old behavior sidecar mismatch")
    if len(codebook["questions"]) != 66:
        raise ValueError("EB question count changed")
    # Selection manifest and READY are required for handoff; the actual A bytes
    # are the binding. Never infer readiness merely from a copied candidate.
    profiles, ledgers = [], []
    for old_family, new_family, old_profile in zip(old_rows, new_rows, old_profiles):
        profile, changes, removals = adapt_one(old_family, new_family, old_profile, codebook)
        profiles.append(profile)
        exact_changes = [{"path": path, "old": before, "new": after, "reason": field_reason(path)}
                         for path, before, after in exact_field_changes(old_profile, profile)]
        ledgers.append({"role_id": profile["role_id"], "changes": changes,
                        "all_field_changes": exact_changes,
                        "eb_scope_exclusions": removals, "housing_branch_changed": is_shared(old_family) != is_shared(new_family)})
    profile_doc = {"schema_version": "eb.synthetic_fixed_profile_300.v2_trial", "n": 300,
                   "source_sha256": {"A_v2_family": sha(A_PATH), "A_v2_selection_manifest": sha(A_MANIFEST),
                                     "A_v2_ready": sha(A_READY), "B_v1_profile": sha(OLD_B),
                                     "B_v1_behavior": sha(OLD_BEHAVIOR), "questionnaire": sha(CODEBOOK)},
                   "family_interface_status": "A_v2_trial_integrated", "building_interface_status": "awaiting_v2_C",
                   "population_weight": None, "fixed_profile_ready": False,
                   "full_household_package_ready": False, "training_release": False,
                   "human_responses": 0, "profiles": profiles}
    write(PROFILE_OUT, profile_doc)
    behavior_qids = lambda qid: (qid.startswith(("H_", "D_", "E_", "T_", "X_COUNT_")) or qid in
                                  ("P_AC_RANGE", "P_AC_CHANGE", "P_EV_TARGET", "P_EV_RESERVE", "P_HOT_WATER", "P_PREHEAT"))
    behavior_rows = []
    for profile in profiles:
        behavior_rows.append({"role_id": profile["role_id"], "members": [
            {k: m[k] for k in ("member_id", "age_years_design", "routine", "life_roles",
                              "typical_weekday_home_windows", "typical_weekend_home_windows")}
            for m in profile["members"]], "usual_presence": profile["usual_presence"],
            "device_ownership": profile["device_ownership"],
            "eb_intervention_devices": profile["eb_intervention_devices"],
            "device_control_scope": profile["device_control_scope"],
            "prior_synthetic_device_inventory": profile["prior_synthetic_device_inventory"],
            "device_access_resolution": profile["device_access_resolution"],
            "prior_device_habits_unverified": profile["prior_device_habits_unverified"],
            "prior_device_conditions_unverified": profile["prior_device_conditions_unverified"],
            "intervention_eligibility": profile["intervention_eligibility"],
            "ordinary_operation_conditions": profile["ordinary_operation_conditions"],
            "home_ev_driver_member_id": profile["home_ev_driver_member_id"],
            "prior_home_ev_driver_member_id": profile["prior_home_ev_driver_member_id"],
            "ordinary_device_answers": {qid: cell for qid, cell in profile["questionnaire_answers"].items() if behavior_qids(qid)}})
    behavior = {"schema_version": "eb.synthetic_fixed_behavior_300.v2_trial", "n": 300,
                "A_v2_family_sha256": sha(A_PATH), "B_v2_profile_sha256": sha(PROFILE_OUT),
                "scope": "ordinary_habits_and_device_constraints_only_not_event_day_presence_or_human_feedback",
                "records": behavior_rows}
    write(BEHAVIOR_OUT, behavior)
    write(LEDGER_OUT, {"schema_version": "eb.v2_profile_change_ledger.v1", "n": 300,
                       "source_A_v2_sha256": sha(A_PATH), "records": ledgers})
    pending_area = [p["role_id"] for p in profiles if p["questionnaire_answers"]["X_AREA"]["response_status"] == "pending_physical_binding"]
    no_device = [p["role_id"] for p in profiles if not p["eb_intervention_devices"]]
    report = {"status": "A_B_MAPPING_COMPLETE_PENDING_V2_C_AND_INDEPENDENT_REVIEW", "n": 300,
              "A_v2_family_sha256": sha(A_PATH), "B_v2_profile_sha256": sha(PROFILE_OUT),
              "B_v2_behavior_sha256": sha(BEHAVIOR_OUT), "changed_role_count": sum(bool(x["changes"]) for x in ledgers),
              "housing_branch_change_count": sum(x["housing_branch_changed"] for x in ledgers),
              "eb_scope_exclusion_count": sum(len(x["eb_scope_exclusions"]) for x in ledgers),
              "prior_owned_device_counts": dict(collections.Counter(d for p in profiles for d in p["device_ownership"])),
              "eb_intervention_device_counts": dict(collections.Counter(d for p in profiles for d in p["eb_intervention_devices"])),
              "shared_whole_dwelling_area_pending_roles": pending_area,
              "no_verified_EB_device_roles": no_device,
              "physical_binding_ready": False, "CSV_release_ready": False, "human_responses": 0}
    write(VALIDATION_OUT, report)
    pressure_rows = []
    for family, profile in zip(new_rows, profiles):
        if "exploratory_7m2_per_person_plus_service_pressure" not in family["dwelling"].get("area_v2_review_flags", []):
            continue
        dw = family["dwelling"]
        ac_count = int(profile["questionnaire_answers"]["X_COUNT_ac"]["value"]) if "ac" in profile["eb_intervention_devices"] else 0
        rooms = dw["room_count_design_minimum"]
        pressure_rows.append({"role_id": profile["role_id"], "family_size": family["family_size"],
                              "H7_natural_room_minimum": rooms,
                              "household_H6_like_building_area_m2": dw["design_total_building_area_m2"],
                              "household_experimental_net_design_m2": dw["modeled_net_area_design_m2"],
                              "net_design_per_person_m2": round(dw["modeled_net_area_design_m2"] / family["family_size"], 3),
                              "housing_form_design": dw["housing_form_design"],
                              "prior_device_ownership": profile["device_ownership"],
                              "eb_intervention_devices": profile["eb_intervention_devices"], "ac_count": ac_count,
                              "ac_count_exceeds_H7_room_minimum": ac_count > rooms,
                              "weekday_day_presence": profile["usual_presence"]["weekday_day"],
                              "automatic_daily_behavior_change": False,
                              "assessment": "exploratory_space_pressure_not_a_measured_occupancy_or_appliance_impossibility",
                              "next_gate": "v2_C_room_geometry_private_control_and_appliance_fit_then_D_G_schedules"})
    if len(pressure_rows) != selection["counts"]["exploratory_occupancy_space_flags"]:
        raise ValueError("A pressure flag count changed after B mapping")
    write(PRESSURE_OUT, {"status": "EXPLORATORY_PRESSURE_REVIEW_PENDING_V2_C", "n": len(pressure_rows),
                         "A_v2_family_sha256": sha(A_PATH), "rows": pressure_rows,
                         "conclusion": "No daily routine is changed solely because of an exploratory area-per-person screen. Device access is rescreened by housing form and size; C must verify usable rooms, equipment placement and control zones."})
    print(json.dumps({k: v for k, v in report.items() if not isinstance(v, list)}, ensure_ascii=False))


if __name__ == "__main__":
    main()
