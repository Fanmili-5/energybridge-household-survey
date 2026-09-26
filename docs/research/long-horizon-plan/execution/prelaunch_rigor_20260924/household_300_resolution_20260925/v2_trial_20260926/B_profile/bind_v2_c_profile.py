"""Single-direction C binding; preserves the F-reviewed static B parent bytes."""
from __future__ import annotations

import argparse
import copy
import hashlib
import json
import re
from pathlib import Path

HERE = Path(__file__).resolve().parent
TRIAL = HERE.parent
A_PATH = TRIAL / "A_structure" / "family_300_v2.json"
STATIC_PROFILE = HERE / "profile_300_v2.json"
STATIC_BEHAVIOR = HERE / "behavior_300_v2.json"
DEFAULT_C = TRIAL / "C_idf" / "building_300.json"
DEFAULT_READY = TRIAL / "C_idf" / "C_BINDING_MANIFEST.json"
PROFILE_OUT = HERE / "profile_300_v2_c_bound.json"
BEHAVIOR_OUT = HERE / "behavior_300_v2_c_bound.json"
REPORT_OUT = HERE / "C_BINDING_VALIDATION.json"
PARENT_PROFILE_SHA = "d1c0b162ac122cb36ac202c778d7ff00956bd3e63fc08643bebd8ac96ff9a168"
PARENT_BEHAVIOR_SHA = "f2340759b62632edff91cd550e613754e872be3051cb504b6894f3fae55e4287"
A_SHA = "1e880b8573124cd2b1050c55e41efc803d3a08d384950f2137cc748abb66870d"


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def read(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def write(path: Path, obj):
    path.write_text(json.dumps(obj, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def area_category(area: float) -> str:
    return "lt50" if area < 50 else "50_89" if area < 90 else "90_119" if area < 120 else "120_159" if area < 160 else "ge160"


def building_type(c):
    return "rowhouse" if c["housing_mode"].startswith("terraced") else "apartment"


def floor_position(c):
    floor = c["source_unit_floor"]
    if not isinstance(floor, int):
        raise ValueError(f"{c['role_id']}: source floor absent")
    roofs = sum(v for k, v in c["selected_zone_surface_constructions"].items() if "Roof" in k)
    return "top" if roofs else "ground" if floor == 1 else "middle"


def building_age(c):
    years = re.findall(r"(?:19|20)\d{2}", c["source_catalog_key"])
    if not years:
        raise ValueError(f"{c['role_id']}: no source catalog year for X_BUILDING_AGE")
    year = int(years[-1])
    return "before2000" if year < 2000 else "2000_2009" if year < 2010 else "2010_2019" if year < 2020 else "since2020"


def close(a, b, tolerance=0.002):
    return abs(float(a) - float(b)) <= tolerance


def verify_c_ready(c_path: Path, ready_path: Path):
    if not c_path.is_file() or not ready_path.is_file():
        raise FileNotFoundError("new v2 C building and explicit ready manifest are both required")
    c_real = c_path.resolve()
    if not c_real.is_relative_to((TRIAL / "C_idf").resolve()):
        raise ValueError("C building must be inside v2 trial C_idf")
    ready = read(ready_path)
    if ready.get("status") not in ("materialized_not_simulated", "C_MATERIALIZED_NOT_SIMULATED"):
        raise ValueError("C ready status is not materialized_not_simulated")
    a_hash = ready.get("A_family_sha256", ready.get("family_sha256"))
    c_hash = ready.get("C_building_sha256", ready.get("building_sha256"))
    if a_hash != A_SHA or c_hash != sha(c_path) or ready.get("n") != 300:
        raise ValueError("C ready manifest does not bind final A/C bytes and 300 roles")
    static_audit = c_path.parent / "static_audit_300.json"
    if (ready.get("B_reviewed_profile_sha256") != PARENT_PROFILE_SHA or
            ready.get("C_static_audit_sha256") != sha(static_audit) or
            ready.get("C_IDF_count") != 300 or ready.get("C_IDF_SHA_check_failures") != 0 or
            ready.get("C_static_check_failures") != 0 or ready.get("actual_EnergyPlus_runs") != 0):
        raise ValueError("C ready manifest audit/parent/status gate failed")
    return ready


def verify_c_row(a, b, c, c_dir):
    rid = b["role_id"]
    if rid != a["role_id"] or rid != c["role_id"]:
        raise ValueError("A/B/C role order mismatch")
    dw = a["dwelling"]
    shared = dw["housing_form_design"].startswith("shared")
    if (c["home_city"] != b["city"] or c["home_province"] != b["province"] or
            c["family_size"] != b["family_size"] or
            c["h7_room_category"] != dw["room_count_census_h7_category"] or
            c["h6_design_building_area_m2"] != dw["design_total_building_area_m2"] or
            c["housing_mode"].startswith("shared") != shared):
        raise ValueError(f"{rid}: C city/size/H6/H7/housing mode mismatch")
    if c["h6_area_basis"] != dw["area_basis"]:
        raise ValueError(f"{rid}: C H6 area semantics mismatch")
    if not close(c["idf_household_accounted_net_area_m2"], dw["modeled_net_area_design_m2"]):
        raise ValueError(f"{rid}: C household net area differs from A design")
    owned_zones = set(c["household_owned_zones"])
    selected_zones = set(c["selected_unit_zones"])
    ac_zones = set(c["ac_controllable_zones"])
    if not owned_zones or not owned_zones <= selected_zones or not ac_zones <= owned_zones:
        raise ValueError(f"{rid}: C private/selected/control zone sets conflict")
    eb_devices = b["eb_intervention_devices"]
    if "ac" in eb_devices:
        q_count = int(b["questionnaire_answers"]["X_COUNT_ac"]["value"])
        if q_count > len(ac_zones) or (shared and q_count > dw["room_count_design_minimum"]):
            raise ValueError(f"{rid}: AC device count exceeds C control zones/private room budget")
    idf = Path(c["idf_path"]).resolve()
    weather = Path(c["weather_epw_path"]).resolve()
    if not idf.is_relative_to(c_dir.resolve()) or sha(idf) != c["idf_sha256"] or sha(weather) != c["weather_epw_sha256"]:
        raise ValueError(f"{rid}: IDF/EPW path or bytes mismatch")
    ratio = c["h6_to_net_conditioned_area_ratio"]
    if not 0 < ratio <= 1:
        raise ValueError(f"{rid}: invalid experimental net/gross ratio")
    if shared:
        whole_net = c["source_selected_unit_zone_area_m2"] * c["xy_scale"] ** 2
        whole_gross = whole_net / ratio
        if whole_gross < dw["design_total_building_area_m2"] or whole_net < c["idf_household_accounted_net_area_m2"]:
            raise ValueError(f"{rid}: shared whole area below attributed household area")
    else:
        whole_gross = dw["design_total_building_area_m2"]
        whole_net = c["idf_household_accounted_net_area_m2"]
    return shared, round(whole_net, 6), round(whole_gross, 6)


def bind_one(a, parent, c, c_dir, private_room_pressure=(), dual_ac_pressure=()):
    shared, whole_net, whole_gross = verify_c_row(a, parent, c, c_dir)
    profile = copy.deepcopy(parent)
    rid = profile["role_id"]
    dw = profile["dwelling_interface"]
    dw.update({"whole_dwelling_building_area_design_m2": whole_gross,
               "whole_dwelling_modeled_net_floor_area_m2": whole_net,
               "whole_dwelling_area_evidence": "v2_C_scaled_source_unit_net_over_experimental_ratio" if shared else
                                               "A_v2_H6_whole_area_plus_v2_C_modeled_net",
               "binding_status": "v2_C_manifest_bound_pending_F_physical_review",
               "building_type": building_type(c), "floor_position": floor_position(c) if building_type(c) == "apartment" else None})
    q = profile["questionnaire_answers"]
    q["X_AREA"] = {"value": area_category(whole_gross), "response_status": "answered",
                   "basis": dw["whole_dwelling_area_evidence"]}
    q["X_BUILDING"] = {"value": building_type(c), "response_status": "answered", "basis": "v2_C_source_prototype_type"}
    q["X_FLOOR"] = ({"value": floor_position(c), "response_status": "answered", "basis": "v2_C_source_floor_and_roof"}
                    if building_type(c) == "apartment" else
                    {"value": None, "response_status": "not_applicable", "basis": "questionnaire_skip_rule"})
    q["X_BUILDING_AGE"] = {"value": building_age(c), "response_status": "answered",
                            "basis": "v2_C_source_catalog_year_proxy_not_observed_home_age"}
    eligible = c["ac_controllable_zones"] if "ac" in profile["eb_intervention_devices"] else []
    profile["physical_binding"] = {
        "virtual_building_id": c["virtual_building_id"], "housing_mode": c["housing_mode"],
        "idf_path": c["idf_path"], "idf_sha256": c["idf_sha256"],
        "weather_epw_path": c["weather_epw_path"], "weather_epw_sha256": c["weather_epw_sha256"],
        "source_floor": c["source_unit_floor"], "source_catalog_key": c["source_catalog_key"],
        "owned_zones": c["household_owned_zones"], "ac_controllable_zones": c["ac_controllable_zones"],
        "eb_ac_eligible_zones": eligible,
        "eb_ac_zone_assignment_status": "pending_D_device_to_zone_assignment" if eligible else "not_applicable_no_EB_AC",
        "household_accounted_net_area_m2": c["idf_household_accounted_net_area_m2"],
        "selected_controlled_zone_area_m2": c["idf_selected_controlled_zone_area_m2"],
        "common_area_allocated_m2": c["idf_common_area_allocated_m2"],
        "source_unit_net_area_scaled_m2": whole_net,
        "experimental_whole_building_area_m2": whole_gross,
        "ratio_net_to_H6_building": c["h6_to_net_conditioned_area_ratio"],
        "evidence_identity": c["evidence_identity"]}
    flags = [x for x in profile["physical_review_flags"] if x not in
             ("v2_C_geometry_and_control_zone_pending", "v2_shared_whole_dwelling_area_pending")]
    flags.append("v2_F_physical_review_pending")
    if rid in private_room_pressure:
        flags.append("v2_C_exploratory_private_room_7m2_pressure_pending_F")
    if rid in dual_ac_pressure:
        flags.append("v2_C_dual_AC_distinct_installation_pending_F")
    if "home_ev" in profile["eb_intervention_devices"]:
        flags.append("v2_home_charger_site_permission_pending_D_F")
    profile["physical_review_flags"] = flags
    if "ac" in profile["eb_intervention_devices"]:
        profile["device_control_scope"]["ac"] = "v2_C_eligible_private_zones_pending_D_assignment_F_review"
        profile["device_access_resolution"]["ac"]["v2_access_status"] = "v2_C_private_zone_candidates_bound_pending_F"
        profile["device_access_resolution"]["ac"]["v2_EB_control_status"] = "not_selected_pending_D_device_to_zone_assignment"
    if profile["eb_intervention_devices"]:
        profile["intervention_eligibility"]["status"] = "C_geometry_bound_pending_F_D_device_review"
        profile["intervention_eligibility"]["reason"] = "C_geometry_and_AC_eligible_zones_bound_actual_assignment_and_physical_schedule_gates_pending"
    profile["evidence_identity"]["whole_dwelling_area"] = dw["whole_dwelling_area_evidence"]
    housing_text = (f"合住：本户分摊建筑面积约{a['dwelling']['design_total_building_area_m2']:g}㎡，"
                    f"实验本户净面积约{a['dwelling']['modeled_net_area_design_m2']:g}㎡；"
                    f"v2 C整套设计建筑面积约{whole_gross:g}㎡、模型净面积约{whole_net:g}㎡。其他住户人数未知。"
                    if shared else
                    f"独立住房设计建筑面积约{whole_gross:g}㎡、v2 C模型净面积约{whole_net:g}㎡；"
                    f"H7至少{a['dwelling']['room_count_design_minimum']}间自然房。")
    profile["role_card_short"] = (
        f"【v2隔离合成角色；无真人回答】{rid}｜{profile['province']}{profile['city']}｜{profile['family_size']}人。"
        + housing_text + f"原合成设备背景：{','.join(profile['device_ownership'])}；"
        + f"本次EB拟纳入：{','.join(profile['eb_intervention_devices']) if profile['eb_intervention_devices'] else '无可控设备'}。"
        + f"典型在家情况：{profile['usual_presence']['weekday_day']}。"
        + "成员生活作息、态度与经济情境沿用同一角色静态父版本；物理与设备控制仍待F独立审核。")
    return profile, {"role_id": rid, "shared": shared, "whole_net_m2": whole_net,
                     "whole_building_m2": whole_gross, "eb_ac_eligible_zone_count": len(eligible),
                     "X_AREA": q["X_AREA"]["value"]}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--building", type=Path, default=DEFAULT_C)
    parser.add_argument("--c-ready", type=Path, default=DEFAULT_READY)
    args = parser.parse_args()
    if sha(A_PATH) != A_SHA or sha(STATIC_PROFILE) != PARENT_PROFILE_SHA or sha(STATIC_BEHAVIOR) != PARENT_BEHAVIOR_SHA:
        raise ValueError("F-reviewed A/B parent bytes changed")
    ready = verify_c_ready(args.building, args.c_ready)
    a, parent_doc, parent_behavior, c_doc = map(read, (A_PATH, STATIC_PROFILE, STATIC_BEHAVIOR, args.building))
    if c_doc.get("family_sha256") != A_SHA or c_doc.get("n") != 300:
        raise ValueError("C building does not bind A v2")
    role_ids = [f"cityrole-{i:04d}" for i in range(1, 301)]
    ar, pr, br, cr = a["records"], parent_doc["profiles"], parent_behavior["records"], c_doc["records"]
    if any([r["role_id"] for r in rows] != role_ids for rows in (ar, pr, br, cr)):
        raise ValueError("A/B/behavior/C role order differs")
    profiles, details = [], []
    private_room_pressure = {x["role_id"] for x in ready.get("shared_private_room_7m2_design_pressure", [])}
    dual_ac_pressure = {x["role_id"] for x in ready.get("space_pressure_dual_AC_roles", [])}
    for af, bp, cp in zip(ar, pr, cr):
        profile, detail = bind_one(af, bp, cp, args.building.parent, private_room_pressure, dual_ac_pressure)
        profiles.append(profile)
        details.append(detail)
    bound = {k: copy.deepcopy(v) for k, v in parent_doc.items() if k != "profiles"}
    bound.update({"schema_version": "eb.synthetic_fixed_profile_300.v2_trial_C_bound",
                  "parent_static_profile_sha256": PARENT_PROFILE_SHA,
                  "parent_static_behavior_sha256": PARENT_BEHAVIOR_SHA,
                  "C_building_sha256": sha(args.building), "C_ready_sha256": sha(args.c_ready),
                  "building_interface_status": "v2_C_manifest_bound_pending_F_physical_review",
                  "fixed_profile_ready": False, "training_release": False, "profiles": profiles})
    write(PROFILE_OUT, bound)
    behavior_rows = []
    for parent_row, profile in zip(br, profiles):
        row = copy.deepcopy(parent_row)
        row["device_control_scope"] = copy.deepcopy(profile["device_control_scope"])
        row["device_access_resolution"] = copy.deepcopy(profile["device_access_resolution"])
        row["intervention_eligibility"] = copy.deepcopy(profile["intervention_eligibility"])
        row["C_building_sha256"] = sha(args.building)
        row["eb_ac_eligible_zones"] = profile["physical_binding"]["eb_ac_eligible_zones"]
        row["eb_ac_zone_assignment_status"] = profile["physical_binding"]["eb_ac_zone_assignment_status"]
        behavior_rows.append(row)
    behavior = {"schema_version": "eb.synthetic_fixed_behavior_300.v2_trial_C_bound", "n": 300,
                "parent_static_behavior_sha256": PARENT_BEHAVIOR_SHA,
                "A_v2_family_sha256": A_SHA, "C_building_sha256": sha(args.building),
                "B_C_bound_profile_sha256": sha(PROFILE_OUT),
                "scope": "ordinary_behavior_and_C_control_zone_binding_not_event_day_or_human_feedback",
                "records": behavior_rows}
    write(BEHAVIOR_OUT, behavior)
    report = {"status": "A_B_C_STATIC_BINDING_COMPLETE_PENDING_F_PHYSICAL_REVIEW", "n": 300,
              "A_family_sha256": A_SHA, "parent_B_profile_sha256": PARENT_PROFILE_SHA,
              "parent_B_behavior_sha256": PARENT_BEHAVIOR_SHA,
              "C_building_sha256": sha(args.building), "C_ready_sha256": sha(args.c_ready),
              "B_C_bound_profile_sha256": sha(PROFILE_OUT), "B_C_bound_behavior_sha256": sha(BEHAVIOR_OUT),
              "shared_count": sum(x["shared"] for x in details),
              "shared_private_room_pressure_roles": sorted(private_room_pressure),
              "space_pressure_dual_AC_roles": sorted(dual_ac_pressure),
              "no_intervention_roles": [p["role_id"] for p in profiles if not p["eb_intervention_devices"]],
              "physical_review_pending": True, "simulation_ready": False, "CSV_release_ready": False,
              "human_responses": 0, "records": details}
    write(REPORT_OUT, report)
    print(json.dumps({k: v for k, v in report.items() if k not in ("records", "no_intervention_roles")}, ensure_ascii=False))


if __name__ == "__main__":
    main()
