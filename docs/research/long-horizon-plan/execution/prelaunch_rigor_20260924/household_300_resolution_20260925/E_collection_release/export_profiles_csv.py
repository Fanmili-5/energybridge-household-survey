"""Export the frozen A/B/C synthetic household inputs to normalized UTF-8 CSV.

Only fixed inputs are exported. Ten-day simulation results and participant
responses are deliberately absent. Run with --verify for a read-back audit.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
from collections import Counter
from pathlib import Path

HERE = Path(__file__).resolve().parent
BASE = HERE.parent
REPO = next(p for p in HERE.parents if p.name == "energybridge-household-survey")
A_PATH = BASE / "A_structure" / "family_300.json"
B_PATH = BASE / "B_profile" / "profile_300.json"
C_PATH = BASE / "C_idf" / "building_300.json"
F_PATH = BASE / "F_independent_review" / "shared_whole_dwelling_area_27.json"
Q_PATH = REPO / "QUESTIONNAIRE_CODEBOOK.json"
MAP_PATH = BASE / "B_profile" / "QUESTION_MAPPING_66.json"

# This export represents one explicit input version. A changed source requires
# review and a new exporter/package version rather than silent regeneration.
LOCKED_SHA256 = {
    "A_family": "d8446c68dd81fa6865cb79add18602fa609188b18631b4134c315385a90ad810",
    "B_profile": "7dbd4e5c87cc440de9f23a5042d83a809bd1cfea9d422245d228816146daaa69",
    "C_building": "bdaab43a705bfb1fba0a675e73e86284aefe38dbcc0db9dd0271190fa42753d3",
    "F_shared_whole_area": "4ccfc37140dce0a644a313baa7e53082d93db8df7e2797c2401d82868385fb35",
}
INPUT_PATHS = {"A_family": A_PATH, "B_profile": B_PATH, "C_building": C_PATH, "F_shared_whole_area": F_PATH}
NA = "NOT_APPLICABLE"
UNKNOWN = "UNKNOWN"

HEADERS = {
    "households_300.csv": [
        "role_id", "source_version", "city", "province", "administrative_city_code", "family_size", "generation_category",
        "older_member_present", "weekday_day_presence", "evening_presence", "routine_regularity",
        "monthly_income_scenario_yuan", "monthly_bill_scenario_yuan", "bill_pressure_design_level",
        "bill_pressure_description", "budget_explanation", "tradeoff_condition", "cost_importance_1_5",
        "comfort_importance_1_5", "grid_importance_1_5", "control_condition", "notice_hours",
        "housing_form", "h7_room_category", "h7_room_minimum", "h6_per_capita_area_bin_m2",
        "h6_design_building_area_m2", "h6_area_basis", "whole_dwelling_building_area_m2", "whole_dwelling_area_status",
        "x_area_answer_code", "x_area_semantic_status", "building_type", "floor_position", "source_floor",
        "virtual_building_id", "housing_mode", "source_catalog_key", "source_unit_exposure",
        "household_accounted_net_area_m2", "selected_controlled_zone_area_m2", "common_allocated_area_m2",
        "weather_station_key", "weather_station_distance_km", "weather_epw_repo_path", "weather_epw_sha256",
        "idf_repo_path", "idf_sha256", "owned_zone_count", "ac_candidate_zone_count", "selected_window_count",
        "private_control_scope", "home_charging_access", "home_ev_driver_member_id", "role_card_short", "actor_card_full",
        "event_presence_status", "participant_feedback_status", "simulation_result_status", "population_weight_status",
    ],
    "members_300.csv": [
        "role_id", "member_id", "member_order", "relationship_to_reference_adult", "partner_member_id", "age_years_design",
        "source_age_band", "age_band", "life_role", "routine", "comfort", "task_flexibility", "participation",
        "needs_priority", "cost_importance_1_5", "grid_importance_1_5", "control", "trait_basis",
        "weekday_window_status", "weekend_window_status",
    ],
    "member_links_300.csv": ["role_id", "member_id", "related_member_id", "relationship_type", "evidence_status"],
    "member_windows_300.csv": ["role_id", "member_id", "day_type", "window_order", "start_local_time", "end_local_time", "time_status", "basis"],
    "devices_300.csv": [
        "role_id", "device", "owned_unit_count", "weekly_frequency_code", "control_scope", "operation_condition",
        "usual_start_code", "earliest_start_code", "latest_end_code", "task_duration_hours_internal", "task_duration_minutes",
        "ac_mode", "ac_custom_start_code", "ac_custom_end_code", "ac_temperature_c", "ac_comfort_range_c",
        "ac_acceptable_change_c", "hot_water_need_time_code", "preheat_choice", "ev_target_soc_fraction",
        "ev_reserve_soc_fraction", "ev_driver_member_id", "device_data_status",
    ],
    "zones_300.csv": [
        "role_id", "zone_name", "source_unit_zone", "household_owned_zone", "ac_candidate_zone",
        "owned_but_unconditioned_zone", "ac_device_assigned_status", "building_idf_sha256",
    ],
    "question_answers_300.csv": [
        "role_id", "question_id", "question_group", "question_prompt", "required_for_generation", "applicable",
        "answer_index", "value_kind", "value_code", "display_label", "response_status", "basis", "value_reference",
        "semantic_status", "source_profile_sha256",
    ],
    "provenance_300.csv": ["role_id", "field_group", "field_path", "source_id", "evidence_label", "source_scope", "source_version"],
}


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def read(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def relative_repo_path(raw: str) -> str:
    path = Path(raw).resolve()
    try:
        return path.relative_to(REPO).as_posix()
    except ValueError as exc:
        raise ValueError(f"path outside repository: {path}") from exc


def cell(value):
    if value is None:
        return ""
    if isinstance(value, bool):
        return "1" if value else "0"
    if isinstance(value, (dict, list)):
        raise TypeError("nested values must be exported as long-table rows")
    value = str(value)
    if value.startswith(("=", "+", "-", "@")):
        raise ValueError(f"spreadsheet formula-like text requires review: {value[:50]}")
    return value


def write_table(name: str, rows: list[dict]):
    path = HERE / name
    header = HEADERS[name]
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=header, extrasaction="raise", lineterminator="\r\n")
        writer.writeheader()
        for row in rows:
            writer.writerow({key: cell(row.get(key)) for key in header})
    return {"rows": len(rows), "sha256": sha(path)}


def answer(q, key):
    x = q[key]
    return x["value"] if x["response_status"] == "answered" else None


def option_label(question, value):
    for option in question.get("options", []):
        if option["value"] == value:
            return option.get("label", value)
    return value


def format_time(code):
    if code is None:
        return "未设定"
    try:
        minutes = round(float(code) * 60)
    except ValueError:
        return str(code)
    return f"{minutes // 60:02d}:{minutes % 60:02d}"


def actor_card(a, b, c, q_map):
    q = b["questionnaire_answers"]
    def qlabel(qid):
        value = answer(q, qid)
        return option_label(q_map[qid], value) if value is not None else "不适用"

    member_fields = {field["id"]: field for field in q_map["M_MEMBERS"]["fields"]}
    def mlabel(field, code):
        return option_label(member_fields[field], code)

    device_names = {"ac": "空调", "washer": "洗衣机", "dishwasher": "洗碗机", "dryer": "烘干机",
                    "electric_water_heater": "电热水器", "home_ev": "可在家充电的电动汽车"}
    relationship_names = {"reference_adult": "主要说明人", "child": "子女", "spouse": "伴侣",
                          "parent_of_reference_adult": "长辈", "spouse_of_child": "子女伴侣", "sibling": "兄弟姐妹",
                          "spouse_or_partner": "伴侣", "parent": "父母", "other_relative": "亲属", "grandparent": "祖辈"}
    area = a["dwelling"]
    if area["housing_form_design"].startswith("shared"):
        area_line = (f"合住，本户独用{area['room_count_design_minimum']}间自然房；{area['design_total_building_area_m2']:g}㎡是本户分摊建筑面积，"
                     f"整套住房设计建筑面积约{b['dwelling_interface']['whole_dwelling_building_area_design_m2']:g}㎡，"
                     "按冻结源单元净面积和实验 0.95 比值换算，并非实测。")
    else:
        area_line = (f"独立住宅，H7 至少{area['room_count_design_minimum']}间自然房；整套设计建筑面积"
                     f"{area['design_total_building_area_m2']:g}㎡。")
    member_lines = []
    for m in b["members"]:
        windows = m["typical_weekday_home_windows"]
        if windows is None:
            home = "工作日到家时段不固定"
        else:
            home = "工作日通常在家 " + "、".join(f"{start}–{end}" for start, end in windows)
        member_lines.append(f"{m['member_id']} {relationship_names.get(m['role'],m['role'])}，{m['age_years_design']}岁，"
                            f"{mlabel('life_roles',m['life_roles'][0])} / {mlabel('routine',m['routine'])}；{home}；"
                            f"室温感受：{mlabel('comfort',m['comfort'])}；电器时间：{mlabel('task',m['task'])}；"
                            f"参与安排：{mlabel('participation',m['participation'])}；需求优先：{mlabel('needs_priority',m['needs_priority'])}；"
                            f"节费/错峰重视 {m['cost_importance']}/{m['grid_importance']}；系统控制：{mlabel('control',m['control'])}。")
    device_lines = []
    for device in b["device_ownership"]:
        count = answer(q, f"X_COUNT_{device}")
        freq = qlabel(f"X_FREQ_{device}")
        if device in ("washer", "dishwasher", "dryer"):
            timing = (f"默认 {format_time(answer(q, f'H_{device}'))}，可从 {format_time(answer(q, f'E_{device}'))} 开始，"
                      f"最晚 {format_time(answer(q, f'D_{device}'))} 完成，一次 {round(float(answer(q, f'T_{device}'))*60)} 分钟")
        elif device == "ac":
            timing = (f"{qlabel('H_ac')}，制冷设定 {answer(q, 'H_ac_temp')}℃，室温希望范围 {qlabel('P_AC_RANGE')}，"
                      f"可接受变化 {answer(q, 'P_AC_CHANGE')}℃")
            if answer(q, "H_ac") == "custom":
                timing += f"，自选时段 {format_time(answer(q, 'H_ac_start'))}–{format_time(answer(q, 'H_ac_end'))}"
        elif device == "electric_water_heater":
            timing = (f"加热 {format_time(answer(q, 'H_electric_water_heater'))}–{format_time(answer(q, 'D_electric_water_heater'))}，"
                      f"需热水 {format_time(answer(q, 'P_HOT_WATER'))}，提前加热：{qlabel('P_PREHEAT')}")
        else:
            timing = (f"接入 {format_time(answer(q, 'H_home_ev'))}，次日离家 {format_time(answer(q, 'D_home_ev'))}，"
                      f"目标/保底电量 {qlabel('P_EV_TARGET')}/{qlabel('P_EV_RESERVE')}，驾驶成员 {b['home_ev_driver_member_id']}")
        unit = "辆" if device == "home_ev" else "台"
        device_lines.append(f"{device_names[device]} {count}{unit}，每周 {freq}；{timing}。条件：{b['ordinary_operation_conditions'][device]}")
    economy = b["economic_context"]
    return "\n".join([
        "【合成角色条件；尚无真人回答】", f"{b['role_id']}｜{b['province']}{b['city']}｜{b['family_size']}人｜{area_line}",
        f"{qlabel('X_BUILDING')}，楼层位置 {qlabel('X_FLOOR')}，房龄背景 {qlabel('X_BUILDING_AGE')}；住宅原型 {c['source_catalog_key']}，源户位 {c['source_unit_exposure']}，天气代理站 {c['weather_station_key']}（距城市约{c['weather_home_city_distance_km']:.1f}km）；天气/原型及房龄并非本户实测。",
        *member_lines,
        f"通常白天：{qlabel('B04')}；晚间：{qlabel('F_EVENING')}；作息：{qlabel('F_REGULARITY')}；深夜用电：{qlabel('F_LATE_USE')}；事件当天是否在受控房间另核。",
        f"家庭月收入情境 {economy['monthly_household_income_scenario_yuan']}元、上月电费情境 {economy['monthly_electricity_bill_scenario_yuan']}元；"
        f"电费压力 {economy['bill_pressure_design_level']}/5。{economy['budget_explanation']}",
        f"节费/舒适/错峰重视 {answer(q,'P_COST')}/{answer(q,'P_COMFORT')}/{answer(q,'P_GRID')}；"
        f"控制边界：{qlabel('A_EB_CONTROL')}；提前通知 {qlabel('P_NOTICE')}；"
        f"受保护活动：{', '.join(option_label(q_map['X_PROTECTED'],v) for v in answer(q,'X_PROTECTED'))}。",
        f"居住方式：{qlabel('X_TENURE')}；电价背景：{qlabel('X_TARIFF')}；定时/自动控制经验：{qlabel('X_SMART')}；"
        f"既有错峰经验：{qlabel('X_DR')}；受扰后恢复偏好：{qlabel('X_RESTORE')}；"
        f"其他背景设备：{', '.join(option_label(q_map['X_EXTRA_DEVICES'],v) for v in answer(q,'X_EXTRA_DEVICES'))}。",
        *device_lines,
        "参与者对十天方案的选择、理由和评分尚未填写。",
    ])


def main(verify_only=False):
    actual = {name: sha(path) for name, path in INPUT_PATHS.items()}
    if actual != LOCKED_SHA256:
        raise ValueError(f"input version changed: {actual}; expected {LOCKED_SHA256}")
    a_data, b_data, c_data, f_data, codebook, mapping = map(read, (A_PATH, B_PATH, C_PATH, F_PATH, Q_PATH, MAP_PATH))
    if b_data["source_sha256"]["A_family"] != actual["A_family"] or b_data["source_sha256"]["C_building"] != actual["C_building"]:
        raise ValueError("B source hashes do not match frozen A/C")
    if b_data["source_sha256"]["questionnaire"] != sha(Q_PATH):
        raise ValueError("questionnaire changed")
    if b_data["source_sha256"]["F_shared_whole_area"] != actual["F_shared_whole_area"] or f_data["C_building_sha256"] != actual["C_building"]:
        raise ValueError("F whole-area sidecar does not match B/C")
    a_map = {x["role_id"]: x for x in a_data["records"]}
    b_map = {x["role_id"]: x for x in b_data["profiles"]}
    c_map = {x["role_id"]: x for x in c_data["records"]}
    f_map = {x["role_id"]: x for x in f_data["records"]}
    role_ids = [f"cityrole-{i:04d}" for i in range(1, 301)]
    if list(b_map) != role_ids or set(a_map) != set(role_ids) or set(c_map) != set(role_ids):
        raise ValueError("role IDs do not match the frozen 300")
    q_map = {x["id"]: x for x in codebook["questions"]}
    if len(q_map) != 66 or len(mapping["questions"]) != 66:
        raise ValueError("questionnaire coverage changed")
    tables = {name: [] for name in HEADERS}
    semantic_issues = []
    for role_id in role_ids:
        a, b, c = a_map[role_id], b_map[role_id], c_map[role_id]
        q = b["questionnaire_answers"]
        if set(q) != set(q_map):
            raise ValueError(f"{role_id}: missing question")
        if a["family_size"] != b["family_size"] or b["city"] != c["home_city"]:
            raise ValueError(f"{role_id}: A/B/C identity mismatch")
        shared = a["dwelling"]["housing_form_design"].startswith("shared")
        area_status = "experimental_F_scaled_whole_dwelling" if shared else "known_synthetic_whole_dwelling"
        x_area_status = "matches_F_experimental_whole_dwelling" if shared else "matches_synthetic_whole_dwelling"
        if shared:
            if role_id not in f_map or q["X_AREA"]["value"] != f_map[role_id]["whole_dwelling_building_area_category_design"]:
                semantic_issues.append({"role_id": role_id, "question_id": "X_AREA", "issue": "F_area_mismatch"})
        elif role_id in f_map:
            semantic_issues.append({"role_id": role_id, "question_id": "X_AREA", "issue": "unexpected_F_area"})
        housing = a["dwelling"]
        physical = b["physical_binding"]
        economic = b["economic_context"]
        tables["households_300.csv"].append({
            "role_id": role_id, "source_version": b_data["schema_version"], "city": b["city"], "province": b["province"],
            "administrative_city_code": a["location"]["administrative_city_code"], "family_size": b["family_size"],
            "generation_category": a["generation_category"], "older_member_present": a["older_member_present"],
            "weekday_day_presence": b["usual_presence"]["weekday_day"], "evening_presence": b["usual_presence"]["evening"],
            "routine_regularity": b["usual_presence"]["regularity"],
            "monthly_income_scenario_yuan": economic["monthly_household_income_scenario_yuan"],
            "monthly_bill_scenario_yuan": economic["monthly_electricity_bill_scenario_yuan"],
            "bill_pressure_design_level": economic["bill_pressure_design_level"],
            "bill_pressure_description": economic["bill_pressure_description"], "budget_explanation": economic["budget_explanation"],
            "tradeoff_condition": b["attitude_design"]["tradeoff_condition"],
            "cost_importance_1_5": answer(q, "P_COST"), "comfort_importance_1_5": answer(q, "P_COMFORT"),
            "grid_importance_1_5": answer(q, "P_GRID"), "control_condition": answer(q, "A_EB_CONTROL"),
            "notice_hours": answer(q, "P_NOTICE"), "housing_form": housing["housing_form_design"],
            "h7_room_category": housing["room_count_census_h7_category"], "h7_room_minimum": housing["room_count_design_minimum"],
            "h6_per_capita_area_bin_m2": housing["per_capita_building_area_census_h6_bin_m2"],
            "h6_design_building_area_m2": housing["design_total_building_area_m2"], "h6_area_basis": housing["area_basis"],
            "whole_dwelling_building_area_m2": b["dwelling_interface"]["whole_dwelling_building_area_design_m2"],
            "whole_dwelling_area_status": area_status, "x_area_answer_code": answer(q, "X_AREA"),
            "x_area_semantic_status": x_area_status, "building_type": answer(q, "X_BUILDING"),
            "floor_position": answer(q, "X_FLOOR") or NA, "source_floor": c["source_unit_floor"],
            "virtual_building_id": c["virtual_building_id"], "housing_mode": c["housing_mode"],
            "source_catalog_key": c["source_catalog_key"], "source_unit_exposure": c["source_unit_exposure"],
            "household_accounted_net_area_m2": physical["household_accounted_net_area_m2"],
            "selected_controlled_zone_area_m2": physical["selected_controlled_zone_area_m2"],
            "common_allocated_area_m2": physical["common_area_allocated_m2"],
            "weather_station_key": c["weather_station_key"],
            "weather_station_distance_km": c["weather_home_city_distance_km"],
            "weather_epw_repo_path": relative_repo_path(physical["weather_epw_path"]),
            "weather_epw_sha256": physical["weather_epw_sha256"],
            "idf_repo_path": relative_repo_path(physical["idf_path"]), "idf_sha256": physical["idf_sha256"],
            "owned_zone_count": len(physical["owned_zones"]), "ac_candidate_zone_count": len(physical["ac_controllable_zones"]),
            "selected_window_count": c["selected_window_count"], "private_control_scope": b["dwelling_interface"]["private_control_scope"],
            "home_charging_access": b["home_charging_access"], "home_ev_driver_member_id": b["home_ev_driver_member_id"],
            "role_card_short": b["role_card_short"], "actor_card_full": actor_card(a, b, c, q_map),
            "event_presence_status": UNKNOWN, "participant_feedback_status": "NOT_COLLECTED",
            "simulation_result_status": "NOT_EXPORTED_PENDING_D_ACCEPTANCE", "population_weight_status": UNKNOWN,
        })
        members = {m["member_id"]: m for m in b["members"]}
        for order, member in enumerate(b["members"], 1):
            source_member = a["members"][order - 1]
            if member["member_id"] != source_member["member_id"] or len(member["life_roles"]) != 1:
                raise ValueError(f"{role_id}: member identity or life role mismatch")
            tables["members_300.csv"].append({
                "role_id": role_id, "member_id": member["member_id"], "member_order": order,
                "relationship_to_reference_adult": member["role"], "partner_member_id": member["partner_member_id"],
                "age_years_design": member["age_years_design"], "source_age_band": member["design_age_band"],
                "age_band": member["age_band"], "life_role": member["life_roles"][0], "routine": member["routine"],
                "comfort": member["comfort"], "task_flexibility": member["task"],
                "participation": member["participation"], "needs_priority": member["needs_priority"],
                "cost_importance_1_5": member["cost_importance"], "grid_importance_1_5": member["grid_importance"],
                "control": member["control"], "trait_basis": member["basis"],
                "weekday_window_status": "UNKNOWN_IRREGULAR" if member["typical_weekday_home_windows"] is None else "SYNTHETIC_TYPICAL",
                "weekend_window_status": "UNKNOWN_IRREGULAR" if member["typical_weekend_home_windows"] is None else "SYNTHETIC_TYPICAL",
            })
            for parent_id in member["parent_member_ids"]:
                if parent_id not in members: raise ValueError(f"{role_id}: missing parent {parent_id}")
                tables["member_links_300.csv"].append({"role_id": role_id, "member_id": member["member_id"],
                    "related_member_id": parent_id, "relationship_type": "parent", "evidence_status": "experimental_family_template"})
            if member["partner_member_id"]:
                if member["partner_member_id"] not in members: raise ValueError(f"{role_id}: missing partner")
                tables["member_links_300.csv"].append({"role_id": role_id, "member_id": member["member_id"],
                    "related_member_id": member["partner_member_id"], "relationship_type": "partner", "evidence_status": "experimental_family_template"})
            for day_type, key in (("weekday", "typical_weekday_home_windows"), ("weekend", "typical_weekend_home_windows")):
                windows = member[key]
                if windows is None:
                    tables["member_windows_300.csv"].append({"role_id": role_id, "member_id": member["member_id"],
                        "day_type": day_type, "window_order": 0, "time_status": UNKNOWN, "basis": "irregular_routine_not_fixed_clock"})
                else:
                    for window_order, (start, end) in enumerate(windows, 1):
                        tables["member_windows_300.csv"].append({"role_id": role_id, "member_id": member["member_id"],
                            "day_type": day_type, "window_order": window_order, "start_local_time": start,
                            "end_local_time": end, "time_status": "SYNTHETIC_TYPICAL", "basis": "B_member_routine_template"})
        for device in b["device_ownership"]:
            if device not in b["device_control_scope"] or device not in b["ordinary_operation_conditions"]:
                raise ValueError(f"{role_id}: missing device control/condition {device}")
            duration = answer(q, f"T_{device}") if device in ("washer", "dishwasher", "dryer") else None
            tables["devices_300.csv"].append({
                "role_id": role_id, "device": device, "owned_unit_count": answer(q, f"X_COUNT_{device}"),
                "weekly_frequency_code": answer(q, f"X_FREQ_{device}"), "control_scope": b["device_control_scope"][device],
                "operation_condition": b["ordinary_operation_conditions"][device],
                "usual_start_code": answer(q, f"H_{device}"),
                "earliest_start_code": answer(q, f"E_{device}") if device in ("washer", "dishwasher", "dryer") else NA,
                "latest_end_code": answer(q, f"D_{device}") if f"D_{device}" in q else NA,
                "task_duration_hours_internal": duration or NA,
                "task_duration_minutes": round(float(duration) * 60) if duration is not None else NA,
                "ac_mode": answer(q, "H_ac") if device == "ac" else NA,
                "ac_custom_start_code": (answer(q, "H_ac_start") or NA) if device == "ac" else NA,
                "ac_custom_end_code": (answer(q, "H_ac_end") or NA) if device == "ac" else NA,
                "ac_temperature_c": answer(q, "H_ac_temp") if device == "ac" else NA,
                "ac_comfort_range_c": answer(q, "P_AC_RANGE") if device == "ac" else NA,
                "ac_acceptable_change_c": answer(q, "P_AC_CHANGE") if device == "ac" else NA,
                "hot_water_need_time_code": answer(q, "P_HOT_WATER") if device == "electric_water_heater" else NA,
                "preheat_choice": answer(q, "P_PREHEAT") if device == "electric_water_heater" else NA,
                "ev_target_soc_fraction": answer(q, "P_EV_TARGET") if device == "home_ev" else NA,
                "ev_reserve_soc_fraction": answer(q, "P_EV_RESERVE") if device == "home_ev" else NA,
                "ev_driver_member_id": b["home_ev_driver_member_id"] if device == "home_ev" else NA,
                "device_data_status": "SYNTHETIC_FIXED_PROFILE",
            })
        selected = set(c["selected_unit_zones"])
        owned = set(c["household_owned_zones"])
        ac = set(c["ac_controllable_zones"])
        unconditioned = set(c["owned_but_unconditioned_source_zones"])
        for zone in sorted(selected | owned | ac | unconditioned):
            tables["zones_300.csv"].append({"role_id": role_id, "zone_name": zone,
                "source_unit_zone": zone in selected, "household_owned_zone": zone in owned,
                "ac_candidate_zone": zone in ac, "owned_but_unconditioned_zone": zone in unconditioned,
                "ac_device_assigned_status": "NOT_ASSIGNED_BY_B", "building_idf_sha256": c["idf_sha256"]})
        for question in codebook["questions"]:
            qid = question["id"]
            record = q[qid]
            requirement = question.get("required_when", {})
            selected_device = requirement.get("selected_device")
            show = requirement.get("show_when") or question.get("show_when")
            applicable = ((not selected_device or selected_device in b["device_ownership"]) and
                          (not show or answer(q, show["question_id"]) == show["value"]))
            if applicable != (record["response_status"] == "answered"):
                raise ValueError(f"{role_id}: condition mismatch {qid}")
            value = record["value"]
            if qid == "M_MEMBERS" and applicable:
                values = [("member_reference", "", "", "members_300.csv")]
            elif isinstance(value, list):
                values = [("list_item", item, option_label(question, item), "") for item in value]
                if not values: raise ValueError(f"{role_id}: empty applicable list {qid}")
            elif applicable:
                values = [("scalar", value, option_label(question, value), "")]
            else:
                values = [("none", "", "", "")]
            for index, (kind, value_code, label, reference) in enumerate(values, 1):
                tables["question_answers_300.csv"].append({
                    "role_id": role_id, "question_id": qid, "question_group": question["group"],
                    "question_prompt": question["prompt"], "required_for_generation": bool(question.get("required_for_generation")),
                    "applicable": applicable, "answer_index": index, "value_kind": kind, "value_code": value_code,
                    "display_label": label, "response_status": record["response_status"], "basis": record["basis"],
                    "value_reference": reference, "semantic_status": x_area_status if qid == "X_AREA" else "matched_to_codebook",
                    "source_profile_sha256": actual["B_profile"],
                })
            for source_id in mapping["questions"][qid]["source_ids"]:
                tables["provenance_300.csv"].append({"role_id": role_id, "field_group": "B_question",
                    "field_path": f"questionnaire_answers.{qid}", "source_id": source_id,
                    "evidence_label": record["basis"], "source_scope": "question_value_and_construct_not_population_weight",
                    "source_version": actual["B_profile"]})
        for field, evidence in a["field_evidence"].items():
            tables["provenance_300.csv"].append({"role_id": role_id, "field_group": "A_family",
                "field_path": field, "source_id": "A_STRUCTURE", "evidence_label": evidence,
                "source_scope": "field_level_provenance", "source_version": actual["A_family"]})
        for field, evidence in b["evidence_identity"].items():
            tables["provenance_300.csv"].append({"role_id": role_id, "field_group": "B_profile",
                "field_path": field, "source_id": "B_PROFILE", "evidence_label": evidence,
                "source_scope": "field_level_provenance", "source_version": actual["B_profile"]})
        tables["provenance_300.csv"].append({"role_id": role_id, "field_group": "C_building",
            "field_path": "building", "source_id": "C_IDF_BINDING", "evidence_label": c["evidence_identity"],
            "source_scope": "prototype_and_weather_not_measured_home", "source_version": actual["C_building"]})
        if shared:
            tables["provenance_300.csv"].append({"role_id": role_id, "field_group": "F_shared_area",
                "field_path": "dwelling_interface.whole_dwelling_building_area_design_m2",
                "source_id": "F_SHARED_WHOLE_UNIT_AREA", "evidence_label": "modeled_full_source_unit_net_over_experimental_0p95_ratio",
                "source_scope": "synthetic_whole_dwelling_design_not_A_household_H6_share_or_observation",
                "source_version": actual["F_shared_whole_area"]})
    if len(tables["households_300.csv"]) != 300 or semantic_issues:
        raise ValueError(f"household or shared semantic audit failed: {semantic_issues[:5]}")
    if verify_only:
        verify_tables(tables)
        return
    output = {name: write_table(name, rows) for name, rows in tables.items()}
    manifest = {"schema_version": "eb.synthetic_household_csv_package.v1", "status": "FIXED_PROFILE_EXPORT_SEMANTIC_PASS_D_RESULTS_PENDING",
        "source_sha256": actual, "questionnaire_sha256": sha(Q_PATH), "question_mapping_sha256": sha(MAP_PATH),
        "tables": output, "role_ids": 300, "member_rows": len(tables["members_300.csv"]),
        "device_rows": len(tables["devices_300.csv"]), "question_ids": 66,
        "semantic_issues": {"X_AREA_shared_whole_dwelling_missing": 0},
        "simulation_results_exported": 0, "participant_responses_exported": 0,
        "notes": ["All role values are synthetic conditions, not observed Chinese household records.",
                  "Shared X_AREA uses F checked full source-unit net area divided by an explicit experimental 0.95 ratio; it is a design whole-dwelling value, not observed housing data.",
                  "IDF/EPW paths are repository-relative references; CSV package does not bundle large or private assets."]}
    (HERE / "PACKAGE_MANIFEST.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    verify_tables(tables)
    print(json.dumps({"status": manifest["status"], "tables": {k: v["rows"] for k, v in output.items()},
                      "semantic_issues": manifest["semantic_issues"]}, ensure_ascii=False))


def verify_tables(expected):
    role_ids = {f"cityrole-{i:04d}" for i in range(1, 301)}
    read_back = {}
    for name, rows in expected.items():
        path = HERE / name
        with path.open("r", encoding="utf-8-sig", newline="") as handle:
            reader = csv.DictReader(handle)
            if reader.fieldnames != HEADERS[name]: raise ValueError(f"{name}: header mismatch")
            reread = list(reader)
        if len(reread) != len(rows): raise ValueError(f"{name}: row-count mismatch")
        if any(row["role_id"] not in role_ids for row in reread): raise ValueError(f"{name}: orphan role ID")
        for original, actual in zip(rows, reread):
            if {key: cell(original.get(key)) for key in HEADERS[name]} != actual:
                raise ValueError(f"{name}: CSV roundtrip mismatch for {actual['role_id']}")
        read_back[name] = reread
    households = read_back["households_300.csv"]
    if len(households) != 300 or {r["role_id"] for r in households} != role_ids:
        raise ValueError("main table must have exactly one row per household")
    members = {(r["role_id"], r["member_id"]) for r in read_back["members_300.csv"]}
    if len(members) != len(read_back["members_300.csv"]): raise ValueError("duplicate member key")
    for name in ("member_links_300.csv", "member_windows_300.csv"):
        for row in read_back[name]:
            if (row["role_id"], row["member_id"]) not in members: raise ValueError(f"{name}: orphan member")
            if name == "member_links_300.csv" and (row["role_id"], row["related_member_id"]) not in members:
                raise ValueError("orphan related member")
    devices = read_back["devices_300.csv"]
    if len({(r["role_id"], r["device"]) for r in devices}) != len(devices): raise ValueError("duplicate device key")
    qrows = read_back["question_answers_300.csv"]
    if {r["question_id"] for r in qrows} != set(read(Q_PATH)["questions"][i]["id"] for i in range(66)):
        raise ValueError("66 question IDs not preserved")
    if len({(r["role_id"], r["question_id"]) for r in qrows}) != 300 * 66:
        raise ValueError("some household-question pairs are missing")
    if sum(r["question_id"] == "X_AREA" and r["semantic_status"] == "matches_F_experimental_whole_dwelling" for r in qrows) != 27:
        raise ValueError("shared X_AREA evidence/status lost")
    if any(r["whole_dwelling_building_area_m2"] == "" for r in households):
        raise ValueError("whole-dwelling design area missing")
    if sum(r["participant_feedback_status"] != "NOT_COLLECTED" for r in households):
        raise ValueError("participant feedback incorrectly filled")
    print(json.dumps({"readback": "pass", "households": 300, "members": len(members),
                      "devices": len(devices), "household_question_pairs": 19800,
                      "shared_x_area_semantic_blockers": 0}, ensure_ascii=False))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--verify", action="store_true", help="read back the existing package and check against frozen inputs")
    main(parser.parse_args().verify)
