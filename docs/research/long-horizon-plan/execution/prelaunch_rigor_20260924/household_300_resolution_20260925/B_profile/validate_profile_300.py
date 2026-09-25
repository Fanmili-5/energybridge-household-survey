"""Independent questionnaire, physics-input, and design-balance audit."""
from __future__ import annotations
import collections
import hashlib
import json
from pathlib import Path
import re
import sys

HERE = Path(__file__).resolve().parent
BASE = HERE.parents[6]
sys.path.insert(0, str(BASE / "realtime_pilot"))
from common import normalize_answers  # noqa: E402
from paired_contract import LOOKUP, TASKS, prepare, sanitize_profile, task_timing  # noqa: E402


def usual_home_at(member, hour):
    windows = member["typical_weekday_home_windows"]
    if windows is None: return None
    def to_hour(token):
        h, minute = token.split(":")
        return int(h) + int(minute) / 60
    return any(to_hour(start) <= hour < to_hour(end) for start, end in windows)


def main():
    d = json.loads((HERE / "profile_300.json").read_text())
    q = json.loads((BASE / "QUESTIONNAIRE_CODEBOOK.json").read_text())
    family = json.loads((HERE.parent / "A_structure" / "family_300.json").read_text())
    amap = {r["role_id"]: r for r in family["records"]}
    cpath = HERE.parent / "C_idf" / "building_300.json"
    buildings = json.loads(cpath.read_text())
    cmap = {r["role_id"]: r for r in buildings["records"]}
    fpath = HERE.parent / "F_independent_review" / "shared_whole_dwelling_area_27.json"
    farea = json.loads(fpath.read_text())
    fmap = {r["role_id"]: r for r in farea["records"]}
    behavior_path = HERE / "behavior_300.json"
    behavior = json.loads(behavior_path.read_text())
    bmap = {r["role_id"]: r for r in behavior["records"]}
    assert d["n"] == 300 and len(d["profiles"]) == 300
    assert d["family_interface_status"] == "A_structure_integrated"
    assert d["building_interface_status"] == "C_manifest_integrated"
    assert len(amap) == len(cmap) == 300
    assert len(bmap) == 300
    assert d["source_sha256"]["A_family"] == hashlib.sha256((HERE.parent / "A_structure" / "family_300.json").read_bytes()).hexdigest()
    assert d["source_sha256"]["C_building"] == hashlib.sha256(cpath.read_bytes()).hexdigest()
    assert d["source_sha256"]["F_shared_whole_area"] == hashlib.sha256(fpath.read_bytes()).hexdigest()
    assert farea["C_building_sha256"] == d["source_sha256"]["C_building"] and len(fmap) == 27
    assert buildings["family_sha256"] == d["source_sha256"]["A_family"]
    assert behavior["A_family_sha256"] == d["source_sha256"]["A_family"]
    assert d["behavior_subset_sha256"] == hashlib.sha256(behavior_path.read_bytes()).hexdigest()
    qids = {x["id"] for x in q["questions"]}
    required = {x["id"] for x in q["questions"] if x.get("required_for_generation")}
    assert len(qids) == 66 and len(required) == 42
    joint = collections.Counter()
    independent_joint = collections.Counter()
    devices = collections.Counter()
    shared_count = 0
    shared_pressure = set()
    shared_control = set()
    shared_per_person_income = set()
    values = {x: set() for x in ("P_COST", "P_COMFORT", "P_GRID", "A_EB_CONTROL", "P_NOTICE")}
    income_control = collections.defaultdict(set)
    per_person_income_cost = collections.defaultdict(set)
    older_household_control = set()
    pressure_cost = collections.Counter()
    factorial_cells = collections.Counter()
    older_outside = 0
    feedback_nonempty = 0
    required_applicable_cells = 0
    uncertain_default_start_count = 0
    for i, r in enumerate(d["profiles"], 1):
        rid = f"cityrole-{i:04d}"
        assert r["role_id"] == rid == r["household_id"]
        a = amap[rid]
        c = cmap[rid]
        b = bmap[rid]
        assert b["device_ownership"] == r["device_ownership"] and b["usual_presence"] == r["usual_presence"]
        assert b["ordinary_operation_conditions"] == r["ordinary_operation_conditions"]
        assert b["home_ev_driver_member_id"] == r["home_ev_driver_member_id"]
        assert r["family_size"] == a["family_size"] == len(r["members"])
        assert r["city"] == a["location"]["city"] and r["province"] == a["location"]["province"]
        assert r["dwelling_interface"]["design_total_building_area_m2"] == a["dwelling"]["design_total_building_area_m2"]
        assert r["physical_binding"]["idf_sha256"] == c["idf_sha256"]
        assert r["physical_binding"]["weather_epw_sha256"] == c["weather_epw_sha256"]
        assert r["physical_binding"]["selected_controlled_zone_area_m2"] == c["idf_selected_controlled_zone_area_m2"]
        assert r["physical_binding"]["ac_controllable_zones"] == c["ac_controllable_zones"]
        assert Path(r["physical_binding"]["idf_path"]).exists()
        assert Path(r["physical_binding"]["weather_epw_path"]).exists()
        assert len(r["questionnaire_answers"]) == 66 and set(r["questionnaire_answers"]) == qids
        raw = {k: v["value"] for k, v in r["questionnaire_answers"].items() if v["response_status"] == "answered"}
        normalized = normalize_answers(raw, list(LOOKUP), LOOKUP)
        normalized = sanitize_profile(normalized)
        # Exercise the actual EB input conversion without its separate generic
        # building matcher; C's physical binding is a distinct gate.
        no_environment = {k: v for k, v in raw.items() if not k.startswith("X_")}
        original, _ = prepare(normalize_answers(no_environment, list(LOOKUP), LOOKUP), rid,
                              environment_required=False)
        assert set(original["devices"]) == set(r["device_ownership"])
        owned = set(r["device_ownership"])
        assert owned and set(raw["B05"]) == owned
        assert set(r["device_control_scope"]) == owned
        for device in owned:
            count_qid = f"X_COUNT_{device}"
            assert int(raw[count_qid]) >= 1
            assert b["ordinary_device_answers"][count_qid] == r["questionnaire_answers"][count_qid]
        assert r["home_charging_access"] == ("home_ev" in owned)
        assert raw["B02"] == (str(r["family_size"]) if r["family_size"] <= 5 else "6_plus")
        for x in q["questions"]:
            qid = x["id"]
            cell = r["questionnaire_answers"][qid]
            device = x.get("required_when", {}).get("selected_device")
            show = x.get("required_when", {}).get("show_when")
            applicable = (not device or device in owned) and (not show or raw.get(show["question_id"]) == show["value"])
            if not applicable:
                assert cell["response_status"] == "not_applicable" and cell["value"] is None, (rid, qid)
            else:
                assert cell["response_status"] == "answered", (rid, qid)
                assert normalized[qid]["response_status"] == "answered", (rid, qid, normalized[qid])
            if qid in required and applicable:
                assert cell["value"] is not None
                required_applicable_cells += 1
        for device in TASKS:
            if device in owned:
                task_timing(normalized, device)
                assert float(raw[f"H_{device}"]) >= 19 and float(raw[f"E_{device}"]) >= 19
                at_start = [usual_home_at(m, float(raw[f"H_{device}"])) for m in r["members"]]
                assert True in at_start or None in at_start, (rid, device, "empty default start")
                if True not in at_start: uncertain_default_start_count += 1
                assert "装载" in r["ordinary_operation_conditions"][device]
        if raw["B04"] == "mostly_absent":
            if "ac" in owned: assert raw["H_ac"] == "evening"
            for device in TASKS:
                if device in owned: assert float(raw[f"H_{device}"]) >= 19
        if "ac" in owned:
            temp = float(raw["H_ac_temp"])
            low, high = map(float, raw["P_AC_RANGE"].split("_"))
            assert low <= temp <= high, (rid, temp, low, high)
            if raw["H_ac"] in ("afternoon", "all_day"):
                assert any(m["routine"] == "home_regular" for m in r["members"]), rid
            if raw["H_ac"] == "all_day":
                assert r["economic_context"]["monthly_electricity_bill_scenario_yuan"] >= 360
                assert r["economic_context"]["monthly_household_income_scenario_yuan"] >= 5000
            assert "空屋" in r["ordinary_operation_conditions"]["ac"]
        if "home_ev" in owned:
            assert float(raw["P_EV_RESERVE"]) <= float(raw["P_EV_TARGET"])
            assert raw["H_home_ev"] != raw["D_home_ev"]
            driver = next(m for m in r["members"] if m["member_id"] == r["home_ev_driver_member_id"])
            assert driver["age_band"] != "under18" and driver["routine"] in ("out_regular", "mixed")
            assert usual_home_at(driver, float(raw["H_home_ev"])) is True
            assert usual_home_at(driver, float(raw["D_home_ev"])) is True
            assert r["economic_context"]["monthly_electricity_bill_scenario_yuan"] >= 360
        if "electric_water_heater" in owned:
            h, end, need = map(lambda x: float(raw[x]), ("H_electric_water_heater", "D_electric_water_heater", "P_HOT_WATER"))
            assert 0 < h < end and end - h <= 8 and h <= need <= end
            at_need = [usual_home_at(m, need) for m in r["members"]]
            assert True in at_need or None in at_need, (rid, "empty hot-water need")
            if True not in at_need: uncertain_default_start_count += 1
        economics = r["economic_context"]
        income = economics["monthly_household_income_scenario_yuan"]
        bill = economics["monthly_electricity_bill_scenario_yuan"]
        assert 0 < bill <= income * .12 + 1e-9, rid
        if len(owned) >= 4: assert bill >= 240
        if economics["bill_pressure_design_level"] >= 4 and bill / income >= .08:
            assert "已为当前电费预留预算" in economics["budget_explanation"]
        joint[("ac" in owned, "washer" in owned)] += 1
        housing_form = a["dwelling"]["housing_form_design"]
        assert r["dwelling_interface"]["housing_form_design"] == housing_form
        assert r["dwelling_interface"]["area_basis"] == a["dwelling"]["area_basis"]
        assert r["dwelling_interface"]["room_count_census_h7_category"] == a["dwelling"]["room_count_census_h7_category"]
        assert r["dwelling_interface"]["physical_whole_dwelling_building_area_m2"] == a["dwelling"]["physical_whole_dwelling_building_area_m2"]
        if housing_form.startswith("shared"):
            shared_count += 1
            f = fmap[rid]
            assert f["frozen_C_idf_sha256"] == c["idf_sha256"] and f["source_unit_zones"] == c["selected_unit_zones"]
            assert raw["X_AREA"] == f["whole_dwelling_building_area_category_design"]
            assert raw["X_AREA_BASIS"] == "gross"
            assert r["dwelling_interface"]["whole_dwelling_building_area_design_m2"] == f["whole_dwelling_building_area_design_m2"]
            assert r["dwelling_interface"]["whole_dwelling_modeled_net_floor_area_m2"] == f["whole_dwelling_modeled_net_floor_area_m2"]
            assert a["dwelling"]["physical_whole_dwelling_building_area_m2"] is None
            assert owned == {"ac"} and r["dwelling_interface"]["private_control_scope"] == "assigned_private_rooms_ac_only"
            assert r["device_control_scope"]["ac"] == "private_room_unit"
            assert len(r["physical_binding"]["owned_zones"]) == a["dwelling"]["room_count_design_minimum"]
            assert int(raw["X_COUNT_ac"]) <= len(c["ac_controllable_zones"]), rid
            assert f"{raw['X_COUNT_ac']}台空调" in r["role_card_short"], rid
            assert raw["X_TENURE"] == "shared" and raw["X_EXTRA_DEVICES"] == ["none"]
            shared_pressure.add(r["economic_context"]["bill_pressure_design_level"])
            shared_control.add(raw["A_EB_CONTROL"])
            shared_per_person_income.add(r["economic_context"]["monthly_household_income_scenario_yuan"] // r["family_size"])
        else:
            assert rid not in fmap
            assert r["dwelling_interface"]["whole_dwelling_building_area_design_m2"] == a["dwelling"]["design_total_building_area_m2"]
            independent_joint[("ac" in owned, "washer" in owned)] += 1
            area = a["dwelling"]["design_total_building_area_m2"]
            if area < 40: assert not ({"dishwasher", "dryer"} & owned)
            if area < 50: assert "home_ev" not in owned
        if c["housing_mode"].startswith("terraced"):
            assert raw["X_BUILDING"] == "rowhouse"
            assert r["questionnaire_answers"]["X_FLOOR"]["response_status"] == "not_applicable"
        else:
            assert raw["X_BUILDING"] == "apartment"
            floor = c["source_unit_floor"]
            roof = sum(v for k, v in c["selected_zone_surface_constructions"].items() if "Roof" in k)
            assert raw["X_FLOOR"] == ("top" if roof else "ground" if floor == 1 else "middle")
        year = int(re.findall(r"(?:19|20)\d{2}", c["source_catalog_key"])[-1])
        assert raw["X_BUILDING_AGE"] == ("before2000" if year < 2000 else "2000_2009" if year < 2010 else "2010_2019" if year < 2020 else "since2020")
        devices.update(owned)
        for field in values: values[field].add(raw[field])
        income_control[raw["X_INCOME"]].add(raw["A_EB_CONTROL"])
        per_person_income_cost[r["economic_context"]["monthly_household_income_scenario_yuan"] // r["family_size"]].add(raw["P_COST"])
        if any(m["age_years_design"] >= 60 for m in r["members"]):
            older_household_control.add(raw["A_EB_CONTROL"])
        pressure_cost[(r["economic_context"]["bill_pressure_design_level"], raw["P_COST"])] += 1
        factorial_cells[(r["economic_context"]["bill_pressure_design_level"],
                         r["attitude_design"]["tradeoff_condition"], raw["A_EB_CONTROL"])] += 1
        for m, am in zip(r["members"], a["members"]):
            age = am["age_years_design"]
            assert m["member_id"] == am["member_id"]
            assert m["age_years_design"] == age
            assert m["age_band"] == ("under18" if age < 18 else "older" if age >= 60 else "adult")
            assert not (m["life_roles"] == ["preschool"] and age >= 6)
            if age >= 60 and m["routine"] in ("out_regular", "mixed", "irregular"): older_outside += 1
        assert any(m["age_band"] != "under18" for m in r["members"])
        assert r["event_specific_presence"] is None
        feedback_nonempty += sum(v is not None for v in r["participant_feedback"].values())
    assert feedback_nonempty == 0
    assert len(factorial_cells) == 75 and set(factorial_cells.values()) == {4}
    assert shared_count == 27
    assert shared_pressure == {1, 2, 3, 4, 5} and len(shared_control) == 3
    assert shared_per_person_income == {2000, 3200, 4500, 6500, 9500}
    # Original CHNS local template is retained approximately within the 273
    # independent dwellings; shared private-room control necessarily changes
    # the pooled 300-household four-cell table.
    assert all(abs(independent_joint[k] - target) <= 2 for k, target in
               {(False, False): 13, (True, False): 4, (False, True): 61, (True, True): 195}.items())
    assert set(devices) == {"ac", "washer", "dishwasher", "dryer", "electric_water_heater", "home_ev"}
    assert values["P_COST"] == values["P_COMFORT"] == values["P_GRID"] == set("12345")
    assert len(values["A_EB_CONTROL"]) == 3 and len(values["P_NOTICE"]) == 9
    assert all(len(x) == 3 for x in income_control.values()), income_control
    assert all(x == set("12345") for x in per_person_income_cost.values())
    assert len(older_household_control) == 3
    assert sum(n for (pressure, cost), n in pressure_cost.items() if pressure == 1 and cost <= "2") > 0
    assert older_outside > 0
    report = {"status": "pass", "profiles": 300, "EB_prepare_without_physical_environment_pass": 300,
              "required_questions": 42, "all_question_ids": 66,
              "required_applicable_cells_answered": required_applicable_cells,
              "required_conditionally_inapplicable_cells": 300 * 42 - required_applicable_cells,
              "A_structure_integrated": True, "C_building_manifest_integrated": True,
              "behavior_subset_hash_matches": True,
              "C_IDF_and_weather_path_exists": 300, "shared_private_room_households": shared_count,
              "shared_home_pressure_control_and_per_person_income_all_levels_present": True,
              "CHNS_local_joint_template_after_housing_restriction": {str(k): v for k, v in sorted(joint.items())},
              "independent_dwelling_joint": {str(k): v for k, v in sorted(independent_joint.items())},
              "device_counts": dict(devices), "attitude_value_coverage": {k: sorted(v) for k, v in values.items()},
              "income_bins_each_have_all_three_control_choices": True,
              "every_per_person_income_tier_has_all_five_cost_attitudes": True,
              "older_member_households_have_all_three_control_choices": True,
              "experimental_5x5x3_cells": len(factorial_cells), "households_per_experimental_cell": 4,
              "high_pressure_low_cost_priority_examples": sum(n for (pressure, cost), n in pressure_cost.items() if pressure == 1 and cost <= "2"),
              "older_members_with_non_home_regular_routine": older_outside,
              "default_operation_or_hot_water_need_with_only_irregular_presence": uncertain_default_start_count,
              "participant_feedback_nonempty_cells": feedback_nonempty,
              "limits": ["all timing/attitude/routine values are synthetic ordinary-day conditions, not observed household answers",
                         "A area is a whole dwelling design area for 273 independent homes and an attributed share for 27 shared homes, never IDF conditioned area",
                         "C IDF runtime validity is reported by C separately; this test checks manifest matching and file existence",
                         "event-day presence remains separate"]}
    (HERE / "VALIDATION_REPORT.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps(report, ensure_ascii=False))


if __name__ == "__main__": main()
