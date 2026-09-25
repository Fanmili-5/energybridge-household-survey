"""Deterministic, explicitly synthetic fixed profiles for the current EB v4.5 questionnaire."""
from __future__ import annotations

import collections
import hashlib
import json
import random
import re
from pathlib import Path

HERE = Path(__file__).resolve().parent
BASE = HERE.parents[6]
AUDIT = HERE.parent.parent
QUESTIONS = BASE / "QUESTIONNAIRE_CODEBOOK.json"
SKELETON = AUDIT / "city_roles_300_candidate.json"
COHORT = AUDIT / "collection_cohort_300_design_v1.json"
FAMILY = HERE.parent / "A_structure" / "family_300.json"
BUILDING = HERE.parent / "C_idf" / "building_300.json"
F_SHARED_AREA = HERE.parent / "F_independent_review" / "shared_whole_dwelling_area_27.json"
SEED = 20260925
DEVICES = ("ac", "washer", "dishwasher", "dryer", "electric_water_heater", "home_ev")
TASKS = ("washer", "dishwasher", "dryer")


def balanced(n, values, seed):
    a = [values[i % len(values)] for i in range(n)]
    random.Random(seed).shuffle(a)
    return a


INCOME_TIERS = balanced(300, (2000, 3200, 4500, 6500, 9500), SEED + 61)
GRID_LEVELS = balanced(300, (1, 2, 3, 4, 5), SEED + 62)
NOTICE_HOURS = balanced(300, ("0", "0.5", "1", "3", "6", "12", "24", "48", "72"), SEED + 63)
SMART_USE = balanced(300, ("often", "sometimes", "never"), SEED + 64)
RESTORE = balanced(300, ("prefer_keep", "prefer_consider", "prefer_restore"), SEED + 65)
TENURE = balanced(300, ("owned", "rented", "shared"), SEED + 66)
BUILDING_AGE = balanced(300, ("before2000", "2000_2009", "2010_2019", "since2020"), SEED + 67)
TARIFF_MODE = balanced(300, ("flat", "tou"), SEED + 68)


def read(path):
    return json.loads(path.read_text(encoding="utf-8"))


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def choice_value(lookup, qid, target):
    vals = [o["value"] for o in lookup[qid].get("options", [])]
    exact = str(target)
    if exact in vals:
        return exact
    if vals:
        numeric = []
        for v in vals:
            try: numeric.append((abs(float(v) - float(target)), v))
            except ValueError: continue
        if not numeric: raise ValueError(f"{qid}: no numeric option for {target}")
        return min(numeric)[1]
    return exact


def status_cell(value, basis, *, reason=None):
    return {"value": value, "response_status": "answered" if value is not None else "not_applicable",
            "basis": basis, **({"reason": reason} if reason else {})}


def age_limits(band):
    if band == "80_plus":
        return 80, 110
    a, b = band.split("_")
    return int(a), int(b)


def member_profile(src, role_index, role_number):
    band = src.get("source_age_band", src.get("age_band"))
    lo, hi = age_limits(band)
    age = src.get("age_years_design")
    if age is not None:
        lo = hi = age
    if hi < 18:
        life = "preschool" if age is not None and age < 6 else "student"
        routine = "home_regular" if life == "preschool" else "out_regular"
    elif lo >= 80:
        life = ("retired", "caregiver", "home_work")[role_number % 3]
        routine = ("home_regular", "mixed", "mixed")[role_number % 3]
    elif lo >= 60:
        life = ("retired", "home_work", "outside_work", "caregiver")[role_number % 4]
        routine = ("home_regular", "mixed", "out_regular", "home_regular")[role_number % 4]
    else:
        life = ("outside_work", "home_work", "shift", "caregiver", "not_working")[role_number % 5]
        routine = {"outside_work": "out_regular", "home_work": "home_regular", "shift": "irregular",
                   "caregiver": "mixed", "not_working": "mixed"}[life]
    return {"member_id": src.get("member_id", f"m{role_index+1:02d}"),
            "parent_member_ids": src.get("parent_member_ids", []),
            "partner_member_id": src.get("partner_member_id"),
            "role": src.get("relationship_to_reference_adult", src.get("role")),
            "age_years_design": age, "design_age_band": band,
            "age_band": "under18" if hi < 18 else "older" if lo >= 60 else "adult",
            "life_roles": [life], "routine": routine,
            "typical_weekday_home_windows": {
                "out_regular": [["00:00", "07:30"], ["18:30", "24:00"]],
                "home_regular": [["00:00", "24:00"]],
                "mixed": [["00:00", "09:00"], ["12:00", "15:00"], ["19:00", "24:00"]],
                "irregular": None,
            }[routine],
            "typical_weekend_home_windows": [["00:00", "10:00"], ["13:00", "24:00"]]
                if routine != "irregular" else None,
            "comfort": ("temp_tolerant", "normal_comfort", "temp_sensitive")[role_number % 3],
            "task": ("flexible", "semi_rigid", "rigid")[(role_number // 2) % 3],
            "participation": "usually_joint", "needs_priority": "no",
            "cost_importance": str(1 + role_number % 5), "grid_importance": str(1 + (role_number * 3) % 5),
            "control": ("auto", "confirm", "manual")[(role_number * 2) % 3],
            "basis": "age_compatible_role_and_counterbalanced_experimental_member_traits"}


def presence(members):
    routines = [m["routine"] for m in members]
    home = routines.count("home_regular")
    irregular = routines.count("irregular")
    mixed = routines.count("mixed")
    if home:
        day = "mostly_occupied"
    elif mixed or irregular:
        day = "variable" if irregular and not mixed else "sometimes_occupied"
    else:
        day = "mostly_absent"
    evening = "varies" if irregular and not home else "partly_home" if mixed or irregular else "mostly_home"
    regularity = "irregular" if irregular else "partly_regular" if mixed else "regular"
    late = "sometimes" if irregular else "rarely"
    return day, evening, regularity, late


def area_from_legacy(residence, size):
    token = residence.get("per_capita_area_bin_m2", "30-39")
    if "+" in token:
        per = float(token.replace("+", "")) + 5
    else:
        parts = token.split("-")
        try:
            per = (float(parts[0]) + float(parts[1])) / 2
        except (ValueError, IndexError):
            per = 35
    return round(per * size, 1)


def area_category(area):
    return "lt50" if area < 50 else "50_89" if area < 90 else "90_119" if area < 120 else "120_159" if area < 160 else "ge160"


def income_category(monthly):
    return "lt5000" if monthly < 5000 else "5000_9999" if monthly < 10000 else "10000_19999" if monthly < 20000 else "20000_29999" if monthly < 30000 else "ge30000"


def bill_category(monthly):
    return "lt100" if monthly < 100 else "100_299" if monthly < 300 else "300_599" if monthly < 600 else "600_999" if monthly < 1000 else "ge1000"


def set_answer(raw, qid, value, basis):
    raw[qid] = status_cell(value, basis)


def assign_device_sets(families):
    def regular_ev_trip_possible(idx):
        members = families[f"cityrole-{idx+1:04d}"]["members"]
        return any((p := member_profile(m, j, idx * 11 + j * 7))["age_band"] != "under18" and
                   p["routine"] in ("out_regular", "mixed")
                   for j, m in enumerate(members))

    ids = list(range(300))
    rng = random.Random(SEED + 4)
    rng.shuffle(ids)
    # CHNS four-cell proportions rounded by largest remainder: neither, AC only, washer only, both.
    groups = ([False, False], [True, False], [False, True], [True, True])
    counts = [15, 4, 67, 214]
    out = [set() for _ in ids]
    at = 0
    for (ac, washer), n in zip(groups, counts):
        for idx in ids[at:at+n]:
            if ac: out[idx].add("ac")
            if washer: out[idx].add("washer")
        at += n
    # Rotate four additional coverage columns against shuffled order, avoiding perfect nesting.
    extras = {"dishwasher": 30, "dryer": 36, "electric_water_heater": 165, "home_ev": 24}
    for offset, (device, n) in enumerate(extras.items()):
        seq = ids.copy()
        random.Random(SEED + 31 + offset).shuffle(seq)
        for idx in seq[:n]: out[idx].add(device)
    shared = set()
    for i in range(300):
        a = families[f"cityrole-{i+1:04d}"]
        dw = a.get("dwelling", {})
        if dw.get("housing_form_design", "independent_dwelling") != "independent_dwelling":
            # B05 is household-owned AND included in EB simulation. Shared laundry,
            # kitchen, bath and parking have no exclusive control right here.
            out[i] = {"ac"}
            shared.add(i)
        else:
            area = dw.get("design_total_building_area_m2", 60)
            if area < 40: out[i].difference_update({"dishwasher", "dryer"})
            if area < 50: out[i].discard("home_ev")
            if not regular_ev_trip_possible(i): out[i].discard("home_ev")
    # Restore the planned *experimental* coverage on independent, physically
    # plausible units after the housing-control restriction.
    eligible_area = {"dishwasher": 40, "dryer": 40, "electric_water_heater": 30, "home_ev": 50}
    for j, (device, target) in enumerate(extras.items()):
        present = sum(device in ds for ds in out)
        candidates = [i for i in range(300) if i not in shared and device not in out[i]
                      and families[f"cityrole-{i+1:04d}"].get("dwelling", {}).get("design_total_building_area_m2", 60) >= eligible_area[device]
                      and (device != "home_ev" or regular_ev_trip_possible(i))]
        random.Random(SEED + 91 + j).shuffle(candidates)
        for i in candidates[:max(0, target-present)]: out[i].add(device)
    for i, owned in enumerate(out):
        if not owned: owned.add("electric_water_heater")
    # The nonempty-home fallback can add a unit beyond an experimental target.
    for j, (device, target) in enumerate(extras.items()):
        excess = sum(device in ds for ds in out) - target
        if excess > 0:
            removable = [i for i in range(300) if i not in shared and device in out[i] and len(out[i]) > 1]
            random.Random(SEED + 111 + j).shuffle(removable)
            if len(removable) < excess: raise ValueError(f"cannot restore {device} coverage target")
            for i in removable[:excess]: out[i].remove(device)
    return out


def get_family_rows(skeleton):
    # A's delivered family file supersedes provisional members/area while stable role IDs remain fixed.
    if not FAMILY.exists():
        return {x["role_id"]: x for x in skeleton["families"]}, False
    data = read(FAMILY)
    arr = data.get("families", data.get("records", data.get("households")))
    if not isinstance(arr, list) or len(arr) != 300:
        raise ValueError("A family file has unexpected shape/count; do not silently fall back")
    return {x["role_id"]: x for x in arr}, True


def get_building_rows(use_A):
    if not BUILDING.exists(): return {}, False
    if not use_A: raise ValueError("C building file exists without A family file")
    data = read(BUILDING)
    if data["family_sha256"] != digest(FAMILY):
        raise ValueError("C building file is stale against A family file")
    arr = data["records"]
    if len(arr) != 300: raise ValueError("C building count is not 300")
    return {x["role_id"]: x for x in arr}, True


def get_shared_area_rows(buildings):
    if not buildings: return {}
    data = read(F_SHARED_AREA)
    if data["C_building_sha256"] != digest(BUILDING) or data["n"] != 27:
        raise ValueError("F shared whole-unit area sidecar is stale or incomplete")
    rows = {x["role_id"]: x for x in data["records"]}
    if len(rows) != 27: raise ValueError("F shared area role IDs are not unique")
    for role_id, building in buildings.items():
        shared = building["housing_mode"].startswith("shared")
        if shared != (role_id in rows): raise ValueError(f"{role_id}: F shared-area coverage mismatch")
        if not shared: continue
        row = rows[role_id]
        if row["frozen_C_idf_sha256"] != building["idf_sha256"] or row["source_unit_zones"] != building["selected_unit_zones"]:
            raise ValueError(f"{role_id}: F shared-area unit/IDF mismatch")
        full_net = building["source_selected_unit_zone_area_m2"] * building["xy_scale"] ** 2
        full_gross = full_net / building["h6_to_net_conditioned_area_ratio"]
        if (abs(full_net - row["whole_dwelling_modeled_net_floor_area_m2"]) > 1e-4 or
                abs(full_gross - row["whole_dwelling_building_area_design_m2"]) > 1e-4 or
                area_category(full_gross) != row["whole_dwelling_building_area_category_design"]):
            raise ValueError(f"{role_id}: F shared-area numeric/category mismatch")
    return rows


def floor_from_building(building):
    floor = building["source_unit_floor"]
    if not isinstance(floor, int): return None
    roofs = sum(v for k, v in building["selected_zone_surface_constructions"].items() if "Roof" in k)
    return "top" if roofs else "ground" if floor == 1 else "middle"


def building_age_from_source(building):
    years = re.findall(r"(?:19|20)\d{2}", building["source_catalog_key"])
    if not years: return "2010_2019"  # terraced source key is expected to have a year
    year = int(years[-1])
    return "before2000" if year < 2000 else "2000_2009" if year < 2010 else "2010_2019" if year < 2020 else "since2020"


def profile_for(i, sk, family, residence, owned, lookup, use_A, building=None, shared_area=None):
    role_id = sk["role_id"]
    source_members = family.get("members", sk["members"])
    size = family.get("family_size", family.get("size_category", sk["size_category"]))
    if len(source_members) != size:
        raise ValueError(f"{role_id}: member count differs from size")
    members = [member_profile(src, j, i * 11 + j * 7) for j, src in enumerate(source_members)]
    members[0]["participation"] = "usually_decides"
    if any(m["age_band"] == "under18" for m in members):
        adults = [m for m in members if m["age_band"] != "under18"]
        if not adults: raise ValueError(f"{role_id}: no adult guardian")
        adults[0]["needs_priority"] = "yes" if adults[0]["life_roles"] == ["caregiver"] else "no"
        for m in members:
            if m["age_band"] == "under18": m["needs_priority"] = "yes"
    day, evening, regularity, late = presence(members)
    pressure = sk["economic_state"]["electricity_bill_pressure_design_level"]
    tradeoff = sk["preferences"]["tradeoff_condition"]
    extreme = (i // 5) % 2 == 0
    pairs = {"middle": (3, 3), "both_high": (5, 5) if extreme else (4, 4),
             "saving_priority": (5, 1) if extreme else (4, 2),
             "comfort_priority": (1, 5) if extreme else (2, 4),
             "both_low": (1, 1) if extreme else (2, 2)}
    cost, comfort = pairs[tradeoff]
    members[0]["control"] = {"high_trust_auto": "auto", "confirm_required": "confirm",
                               "low_auto_accept": "manual"}[sk["preferences"]["A_EB_CONTROL"]]
    members[0]["cost_importance"] = str(cost)
    income_per_person = INCOME_TIERS[i]
    income = income_per_person * size
    bill = (120, 220, 360, 520, 720)[(i * 13 + len(owned)) % 5]
    bill = min(bill, max(100, round(income * .12 / 10) * 10))
    # A modest scenario floor prevents daily home charging or several owned
    # appliances from being paired with the lowest monthly bill bin. This is
    # a plausibility screen, not an appliance-load or tariff estimate.
    if "home_ev" in owned:
        bill = max(bill, 360)
    elif len(owned) >= 4:
        bill = max(bill, 240)
    if pressure <= 2 and income_per_person >= 6500:
        budget_explanation = "本月收入已有其他固定支出安排，可灵活调整的预算较紧。"
    elif pressure <= 2:
        budget_explanation = "必要生活开支较多，本月电费变化容易挤占其他项目。"
    elif pressure >= 4 and bill / income >= .08:
        budget_explanation = "家庭已为当前电费预留预算，按这个金额可以承担；增加用电仍需重新权衡。"
    elif pressure >= 4 and income_per_person <= 3200:
        budget_explanation = "本月电费已列入预算，按当前金额可以承担。"
    elif pressure >= 4:
        budget_explanation = "本月电费占可安排预算较小。"
    else:
        budget_explanation = "本月电费可承担，但家庭会留意它的变化。"
    area = family.get("dwelling", {}).get("design_total_building_area_m2") if use_A else None
    if area is None: area = area_from_legacy(residence, size)
    area_basis = family.get("dwelling", {}).get("area_basis", "provisional_NBS_per_capita_area_bin_midpoint") if use_A else "provisional_NBS_per_capita_area_bin_midpoint"
    housing_form = family.get("dwelling", {}).get("housing_form_design", "independent_dwelling") if use_A else "provisional_independent_dwelling"
    if housing_form.startswith("shared") and building and shared_area is None:
        raise ValueError(f"{role_id}: missing F verified whole-dwelling area")
    room_count_min = family.get("dwelling", {}).get("room_count_design_minimum") if use_A else None
    room_category = family.get("dwelling", {}).get("room_count_census_h7_category") if use_A else residence.get("census_room_count_category")
    if building:
        if (building["home_city"] != residence["city"] or building["home_province"] != residence["province"]
                or building["h6_design_building_area_m2"] != area or building["h7_room_category"] != room_category):
            raise ValueError(f"{role_id}: C location/area/room mismatch")
        if building["housing_mode"].startswith("shared") != housing_form.startswith("shared"):
            raise ValueError(f"{role_id}: C housing form mismatch")
    raw = {}
    baseline = "experimental_profile"
    set_answer(raw, "B02", str(size) if size <= 5 else "6_plus", "family_structure")
    set_answer(raw, "B04", day, "derived_synthetic_member_routines")
    set_answer(raw, "B05", [d for d in DEVICES if d in owned], "CHNS_local_template_plus_experimental_other_devices")
    set_answer(raw, "F_EVENING", evening, "derived_synthetic_member_routines")
    set_answer(raw, "F_REGULARITY", regularity, baseline)
    set_answer(raw, "F_LATE_USE", late, baseline)
    set_answer(raw, "M_MEMBERS", [{k: v for k, v in m.items() if k not in ("member_id", "parent_member_ids", "partner_member_id", "role", "design_age_band", "age_years_design", "basis", "typical_weekday_home_windows", "typical_weekend_home_windows")}
                                   for m in members], "age_compatible_synthetic_member_routines_and_preferences")
    # Ordinary task windows are deliberately broad enough for EB to reschedule meaningfully.
    templates = {"washer": "1", "dishwasher": "1", "dryer": "1.5"}
    for device in TASKS:
        if device not in owned: continue
        h = str(19 + (i + DEVICES.index(device)) % 3)
        e, d, t = "19", "24" if h == "21" else "23", templates[device]
        for field, val in (("H", h), ("E", e), ("D", d), ("T", t)):
            set_answer(raw, f"{field}_{device}", choice_value(lookup, f"{field}_{device}", val), "experimental_legal_task_window")
    if "ac" in owned:
        ac_mode = ("afternoon", "evening", "all_day", "custom")[i % 4]
        home_regular = any(m["routine"] == "home_regular" for m in members)
        if day == "mostly_absent" or (ac_mode in ("afternoon", "all_day") and not home_regular):
            ac_mode = "evening"
        if ac_mode == "all_day" and (bill < 360 or income < 5000):
            ac_mode = "evening"
        set_answer(raw, "H_ac", ac_mode, "experimental_monthly_cooling_habit")
        set_answer(raw, "H_ac_temp", choice_value(lookup, "H_ac_temp", (25, 26, 27, 24)[i % 4]), baseline)
        if ac_mode == "custom":
            set_answer(raw, "H_ac_start", choice_value(lookup, "H_ac_start", 16 if home_regular else 19), baseline)
            set_answer(raw, "H_ac_end", choice_value(lookup, "H_ac_end", 23), baseline)
        ac_range = ("24_26", "25_27", "26_28", "23_25")[i % 4]
        set_answer(raw, "P_AC_RANGE", ac_range, "experimental_comfort_band")
        set_answer(raw, "P_AC_CHANGE", choice_value(lookup, "P_AC_CHANGE", (0.5, 1, 1.5)[i % 3]), "experimental_temperature_flexibility")
    if "electric_water_heater" in owned:
        start, end, need = [(6, 8, 7), (19, 22, 21), (20, 22, 21)][i % 3]
        for field, val in (("H_electric_water_heater", start), ("D_electric_water_heater", end), ("P_HOT_WATER", need)):
            set_answer(raw, field, choice_value(lookup, field, val), "experimental_daytime_heating_window")
        set_answer(raw, "P_PREHEAT", ("yes", "confirm", "no")[i % 3], baseline)
    if "home_ev" in owned:
        drivers = [m for m in members if m["age_band"] != "under18" and m["routine"] in ("out_regular", "mixed")]
        if not drivers: raise ValueError(f"{role_id}: no adult with a regular EV return trip")
        ev_driver = next((m for m in drivers if m["routine"] == "out_regular"), drivers[0])
        arrival, departure = (19 + i % 3), (7 if ev_driver["routine"] == "out_regular" else 8.5)
        set_answer(raw, "H_home_ev", choice_value(lookup, "H_home_ev", arrival), "experimental_overnight_home_charging")
        set_answer(raw, "D_home_ev", choice_value(lookup, "D_home_ev", departure), "experimental_overnight_home_charging")
        target, reserve = [(0.8, 0.2), (0.9, 0.3), (0.7, 0.4)][i % 3]
        set_answer(raw, "P_EV_TARGET", choice_value(lookup, "P_EV_TARGET", target), baseline)
        set_answer(raw, "P_EV_RESERVE", choice_value(lookup, "P_EV_RESERVE", reserve), baseline)
    set_answer(raw, "A_EB_CONTROL", sk["preferences"]["A_EB_CONTROL"], "existing_three_option_experimental_factor")
    for qid, val in (("P_COST", cost), ("P_COMFORT", comfort), ("P_GRID", GRID_LEVELS[i])):
        set_answer(raw, qid, str(val), "expanded_counterbalanced_experimental_attitude")
    set_answer(raw, "P_NOTICE", NOTICE_HOURS[i], "experimental_notice_requirement")
    set_answer(raw, "X_REGION", residence["province"], "assigned_city_province")
    set_answer(raw, "X_CITY", residence["city"], "assigned_city")
    building_type = "rowhouse" if building and building["housing_mode"].startswith("terraced") else "apartment"
    set_answer(raw, "X_BUILDING", building_type, "C_physical_prototype_type" if building else "provisional_apartment_assumption")
    whole_dwelling_design_area = shared_area["whole_dwelling_building_area_design_m2"] if shared_area else area
    set_answer(raw, "X_AREA", area_category(whole_dwelling_design_area),
               "experimental_F_scaled_whole_source_unit_net_over_shared_0p95_ratio" if shared_area else area_basis)
    set_answer(raw, "X_AREA_BASIS", "gross", area_basis)
    if building_type == "apartment":
        set_answer(raw, "X_FLOOR", floor_from_building(building) if building else ("ground", "middle", "top")[i % 3],
                   "C_source_unit_floor_and_roof_surface" if building else "provisional_experimental_floor")
    # Optional research background stays distinct from EB normalized experiment price.
    set_answer(raw, "X_TENURE", "shared" if housing_form.startswith("shared") else TENURE[i], baseline)
    set_answer(raw, "X_BUILDING_AGE", building_age_from_source(building) if building else BUILDING_AGE[i],
               "C_source_prototype_year_not_observed_building_age" if building else baseline)
    set_answer(raw, "X_INCOME", income_category(income), "NBS_2023_median_scale_experimental_income")
    set_answer(raw, "X_BILL", bill_category(bill), "experimental_cashflow_bill_with_device_floor_not_energy_prediction")
    set_answer(raw, "X_TARIFF", TARIFF_MODE[i], "experimental_local_tariff_context_separate_from_shared_normalized_EB_TOU")
    set_answer(raw, "X_EXTRA_DEVICES", ["none"] if housing_form.startswith("shared") else ["refrigerator"],
               "experimental_background_appliance_outside_EB_scope")
    set_answer(raw, "X_PROTECTED", ["sleep", "meal"] + (["care"] if any(m["age_band"] == "under18" for m in members) else []),
               "synthetic_household_constraints")
    set_answer(raw, "X_SMART", SMART_USE[i], baseline)
    set_answer(raw, "X_DR", "yes" if i % 7 == 0 else "no", baseline)
    set_answer(raw, "X_RESTORE", RESTORE[i], baseline)
    for device in DEVICES:
        if device in owned:
            count = 2 if device == "ac" and i % 4 == 0 else 1
            if device == "ac" and housing_form.startswith("shared"):
                # A shared household can only operate its assigned private rooms.
                # Cap the experimental AC count by C's private control budget.
                control_budget = len(building["ac_controllable_zones"]) if building else room_count_min
                if not control_budget or control_budget < 1:
                    raise ValueError(f"{role_id}: shared home has no private AC control zone")
                count = min(count, control_budget)
            set_answer(raw, f"X_COUNT_{device}", str(count), "experimental_owned_unit_count_with_private_zone_cap")
            set_answer(raw, f"X_FREQ_{device}", ("days_2_3", "days_4_6", "days_7")[i % 3], "experimental_weekly_frequency")
    # Materialize all 66 questions, preserving skip logic and explicit non-applicability.
    answers = {}
    for qid, q in lookup.items():
        required_when = q.get("required_when", {})
        needed_device = required_when.get("selected_device")
        show = required_when.get("show_when") or q.get("show_when")
        applicable = (not needed_device or needed_device in owned) and (not show or raw.get(show["question_id"], {}).get("value") == show["value"])
        if not applicable:
            answers[qid] = status_cell(None, "questionnaire_skip_rule", reason="selected_device_or_show_when_false")
        elif qid in raw:
            answers[qid] = raw[qid]
        else:
            raise ValueError(f"{role_id}: unfilled applicable question {qid}")
        if answers[qid]["response_status"] == "answered" and q.get("options"):
            val = answers[qid]["value"]
            possible = {o["value"] for o in q["options"]}
            if isinstance(val, list):
                if not set(val) <= possible: raise ValueError(f"{role_id}: invalid option {qid}: {val}")
            elif val not in possible: raise ValueError(f"{role_id}: invalid option {qid}: {val}")
        if q.get("required_for_generation") and applicable and answers[qid]["response_status"] != "answered":
            raise ValueError(f"{role_id}: missing required applicable {qid}")
    member_names = {"reference_adult": "主要说明人", "child": "子女", "spouse": "伴侣",
                    "parent_of_reference_adult": "长辈", "spouse_of_child": "子女伴侣", "sibling": "兄弟姐妹",
                    "spouse_or_partner": "伴侣", "parent": "父母", "other_relative": "亲属", "grandparent": "祖辈"}
    routine_names = {"out_regular": "通常定时外出", "home_regular": "通常主要在家", "mixed": "在家外出交替", "irregular": "轮班或时间多变"}
    device_names = {"ac": "空调", "washer": "洗衣机", "dishwasher": "洗碗机", "dryer": "烘干机",
                    "electric_water_heater": "电热水器", "home_ev": "可在家充电的电动车"}
    control_names = {"high_trust_auto": "约定范围内可自动调整", "confirm_required": "每次先确认",
                     "low_auto_accept": "以自己安排为主"}
    if pressure <= 2 and cost <= 2:
        rationale = "虽然电费挤压预算，但家里更在意任务按原计划完成，不愿为了少量节费频繁改时间。"
    elif pressure >= 4 and cost >= 4:
        rationale = "当前电费负担不重，但仍重视避免浪费。"
    elif cost <= 2 and comfort <= 2:
        rationale = "费用与室温都不是首要判断项，家里更关注日常任务是否照计划完成。"
    else:
        rationale = "费用压力描述的是当前预算余量；节费重视描述的是调整方案时的取舍，两者分别考虑。"
    housing_desc = (f"合住住房中本户独用{room_count_min}间房，分摊建筑面积约{area:g}平方米；整套住房设计建筑面积约{whole_dwelling_design_area:g}平方米（按模型整套净面积和实验0.95比值换算）；仅私有房间的{raw['X_COUNT_ac']['value']}台空调可由本户安排，公共设备不纳入。"
                    if housing_form.startswith("shared") else f"独立住房建筑面积约{area:g}平方米，七普口径至少{room_count_min}间自然房间。")
    compact_room = bool(building and housing_form.startswith("shared") and building["idf_selected_controlled_zone_area_m2"] < 6)
    if compact_room: housing_desc += "私有起居空间很紧凑。"
    ordinary_operation_conditions = {}
    for device in TASKS:
        if device in owned:
            ordinary_operation_conditions[device] = "默认时刻须有成员在家并完成装载；轮班或事件日另核，不默认预约或远程启动。"
    if "ac" in owned:
        ordinary_operation_conditions["ac"] = ("有人在受控房间时使用；18:00–18:30若空屋预冷，须当天确认家户许可及实际预约/远控能力，否则到家后开启；空屋冷量不算舒适收益。"
                                                if raw["H_ac"]["value"] == "evening" else
                                                "有人在受控房间时使用；轮班或事件日另核，不把空屋冷量算作舒适收益。")
    if "electric_water_heater" in owned:
        ordinary_operation_conditions["electric_water_heater"] = "普通加热须对准有人需要热水的时段；事件日及额外提前加热按当次许可确认。"
    if "home_ev" in owned:
        ordinary_operation_conditions["home_ev"] = f"由{ev_driver['member_id']}在典型外出日返家后接入；车辆实际到家、次日离家与充电权限按当天确认。"
    operations_summary = ("洗衣等任务需有人在家完成装载。" if any(d in owned for d in TASKS) else "")
    if "ac" in owned and raw["H_ac"]["value"] == "evening":
        operations_summary += "空屋提前开空调须另确认预约或远控与本人许可。"
    if any(m["routine"] == "irregular" for m in members):
        operations_summary += "轮班日按当天在家情况确认。"
    desc = (f"{residence['city']}的{size}人家庭。{housing_desc}" +
            "、".join(f"{member_names.get(m['role'], m['role'])}（{m['age_years_design']}岁，{routine_names[m['routine']]}）" for m in members) +
            f"。通常白天{ {'mostly_occupied':'有人在家','sometimes_occupied':'部分时间有人','mostly_absent':'多在外','variable':'不固定'}[day]}。" +
            f"家庭月收入情境约{income}元，通常月电费情境约{bill}元；{sk['economic_state']['role_description']}。{budget_explanation}" +
            f"纳入安排的设备：{'、'.join(device_names[x] for x in DEVICES if x in owned)}。" +
            f"节费重视{cost}/5，舒适重视{comfort}/5，系统控制边界是{control_names[answers['A_EB_CONTROL']['value']]}；" +
            f"希望提前{answers['P_NOTICE']['value']}小时通知。{rationale}{operations_summary}")
    return {"role_id": role_id, "household_id": role_id, "family_source": "A_structure" if use_A else "provisional_city_roles_300_candidate",
            "city": residence["city"], "province": residence["province"], "family_size": size,
            "members": members, "usual_presence": {"weekday_day": day, "evening": evening, "regularity": regularity,
                                                  "basis": "derived_synthetic_member_routines_not_event_presence"},
            "economic_context": {"monthly_household_income_scenario_yuan": income, "monthly_electricity_bill_scenario_yuan": bill,
                                 "bill_pressure_design_level": pressure, "bill_pressure_description": sk["economic_state"]["role_description"],
                                 "budget_explanation": budget_explanation,
                                 "income_frequency": None, "bill_frequency": None, "basis": "NBS_disposable_median_scale_proxy_for_experimental_total_income_not_exact_measure"},
            "attitude_design": {"tradeoff_condition": tradeoff, "expanded_cost_level": cost,
                                "expanded_comfort_level": comfort, "control_condition": answers["A_EB_CONTROL"]["value"],
                                "assignment_basis": "75_cell_experimental_coverage_with_within_cell_extreme_variants",
                                "population_frequency": None},
            "device_ownership": [d for d in DEVICES if d in owned],
            "device_control_scope": {d: ("private_room_unit" if housing_form.startswith("shared") else
                                         "assigned_home_charger" if d == "home_ev" else "household_owned_private_device")
                                     for d in DEVICES if d in owned},
            "ordinary_operation_conditions": ordinary_operation_conditions,
            "home_ev_driver_member_id": ev_driver["member_id"] if "home_ev" in owned else None,
            "home_charging_access": True if "home_ev" in owned else False,
            "dwelling_interface": {"design_total_building_area_m2": area, "area_basis": area_basis,
                                    "housing_form_design": housing_form,
                                    "room_count_census_h7_category": room_category,
                                    "room_count_design_minimum": room_count_min,
                                    "physical_whole_dwelling_building_area_m2": family.get("dwelling", {}).get("physical_whole_dwelling_building_area_m2") if use_A else None,
                                    "whole_dwelling_building_area_design_m2": whole_dwelling_design_area,
                                    "whole_dwelling_modeled_net_floor_area_m2": shared_area["whole_dwelling_modeled_net_floor_area_m2"] if shared_area else None,
                                    "whole_dwelling_area_evidence": "F_verified_scaled_source_unit_plus_experimental_0p95_gross_ratio" if shared_area else area_basis,
                                    "private_control_scope": "assigned_private_rooms_ac_only" if housing_form.startswith("shared") else "household_selected_devices",
                                    "building_type": answers["X_BUILDING"]["value"], "floor_position": answers["X_FLOOR"]["value"],
                                    "binding_status": "C_IDF_manifest_bound" if building else "awaiting_C_IDF_consistency_check"},
            "physical_binding": ({"virtual_building_id": building["virtual_building_id"],
                                  "housing_mode": building["housing_mode"], "idf_path": building["idf_path"],
                                  "idf_sha256": building["idf_sha256"], "weather_epw_path": building["weather_epw_path"],
                                  "weather_epw_sha256": building["weather_epw_sha256"],
                                  "source_floor": building["source_unit_floor"],
                                  "owned_zones": building["household_owned_zones"],
                                  "ac_controllable_zones": building["ac_controllable_zones"],
                                  "household_accounted_net_area_m2": building["idf_household_accounted_net_area_m2"],
                                  "selected_controlled_zone_area_m2": building["idf_selected_controlled_zone_area_m2"],
                                  "common_area_allocated_m2": building["idf_common_area_allocated_m2"],
                                  "evidence_identity": building["evidence_identity"]} if building else None),
            "physical_review_flags": ["shared_private_controlled_area_below_experimental_6m2_screen"] if compact_room else [],
            "questionnaire_answers": answers, "role_card_short": desc,
            "event_specific_presence": None, "participant_feedback": {"decision": None, "reason": None,
                                                              "score": None, "comfort_score": None, "energy_score": None, "vpp_score": None},
            "population_weight": None, "population_frequency": None,
            "evidence_identity": {"family": "source_calibrated_or_A_model", "income": "experimental_scale_anchored",
                                  "bill": "experimental", "bill_pressure": "experimental",
                                  "ac_washer_joint": "matched_local_CHNS_2015_not_population",
                                  "other_appliances": "experimental", "routines": "experimental",
                                  "attitudes": "experimental_construct_grounded",
                                  "whole_dwelling_area": "F_scaled_full_source_unit_net_over_experimental_0p95_ratio" if shared_area else "A_synthetic_whole_dwelling_area"}}


def main():
    codebook = read(QUESTIONS)
    if codebook["question_count"] != 66:
        raise ValueError("questionnaire version changed")
    lookup = {q["id"]: q for q in codebook["questions"]}
    if sum(bool(q.get("required_for_generation")) for q in lookup.values()) != 42:
        raise ValueError("generation flag count changed")
    skeleton = read(SKELETON)
    cohort = {r["role_id"]: r for r in read(COHORT)["records"]}
    families, use_A = get_family_rows(skeleton)
    devices = assign_device_sets(families)
    buildings, use_C = get_building_rows(use_A)
    shared_areas = get_shared_area_rows(buildings)
    records = []
    for i, sk in enumerate(skeleton["families"]):
        role_id = f"cityrole-{i+1:04d}"
        if sk["role_id"] != role_id or role_id not in cohort or role_id not in families:
            raise ValueError(f"role sequence mismatch {role_id}")
        residence = cohort[role_id]["residence"].copy()
        if use_A:
            for key in ("province", "city"):
                if families[role_id]["location"][key] != residence[key]:
                    raise ValueError(f"{role_id}: A city changed against frozen cohort")
                residence[key] = families[role_id]["location"][key]
        if use_C and role_id not in buildings: raise ValueError(f"missing C role {role_id}")
        rec = profile_for(i, sk, families[role_id], residence, devices[i], lookup, use_A,
                          buildings.get(role_id), shared_areas.get(role_id))
        records.append(rec)
    path_map = {}
    for q in codebook["questions"]:
        qid = q["id"]
        domain = "member_profile" if qid == "M_MEMBERS" else "usual_household_or_device" if qid.startswith(("B", "F", "H", "D", "E", "T")) else "stated_preference" if qid.startswith("P") or qid == "A_EB_CONTROL" else "dwelling_environment_or_research_context"
        if qid == "B02": source_ids = ["A_NBS_FAMILY", "EB_V45"]
        elif qid == "M_MEMBERS": source_ids = ["A_NBS_FAMILY", "NBS_TIME_USE_2024", "EB_V45"]
        elif qid in ("B04", "F_EVENING", "F_REGULARITY", "F_LATE_USE"):
            source_ids = ["NBS_TIME_USE_2024", "EB_V45", "EXPERIMENTAL_TYPICAL_DAY"]
        elif qid == "B05" or qid.startswith(("X_COUNT_", "X_FREQ_")):
            source_ids = ["CHNS_2015_LOCAL", "NBS_2023_APPLIANCE", "ZJ_2024_APPLIANCE", "EB_V45", "EXPERIMENTAL_DEVICE_COVERAGE"]
        elif qid.startswith(("H_", "D_", "E_", "T_")):
            source_ids = ["CHEN_2024_BEHAVIOR", "NIU_2016", "EB_V45", "EXPERIMENTAL_ORDINARY_WINDOW"]
        elif qid in ("P_COST", "P_COMFORT", "P_GRID", "P_NOTICE", "A_EB_CONTROL"):
            source_ids = ["CHINA_DR_CONSTRUCT", "GUANGDONG_SMART_CONTROL", "EB_V45", "EXPERIMENTAL_ATTITUDE_COVERAGE"]
        elif qid.startswith("P_"):
            source_ids = ["EB_V45", "EXPERIMENTAL_DEVICE_CONSTRAINT"]
        elif qid == "X_AREA": source_ids = ["A_NBS_FAMILY", "C_IDF_BINDING", "F_SHARED_WHOLE_UNIT_AREA", "EB_V45", "EXPERIMENTAL_BUILDING_CONTEXT"]
        elif qid in ("X_REGION", "X_CITY", "X_AREA_BASIS", "X_BUILDING", "X_FLOOR"):
            source_ids = ["A_NBS_FAMILY", "C_IDF_BINDING", "EB_V45", "EXPERIMENTAL_BUILDING_CONTEXT"]
        elif qid == "X_BUILDING_AGE": source_ids = ["C_IDF_BINDING", "EB_V45", "EXPERIMENTAL_PROTOTYPE_YEAR_CONTEXT"]
        elif qid == "X_INCOME": source_ids = ["NBS_2023_INCOME", "CHINA_ENERGY_BURDEN", "EB_V45", "EXPERIMENTAL_INCOME_SCALE"]
        elif qid == "X_BILL": source_ids = ["CHINA_ENERGY_BURDEN", "EB_V45", "EXPERIMENTAL_BILL_CONTEXT"]
        else: source_ids = ["EB_V45", "EXPERIMENTAL_RESEARCH_CONTEXT"]
        path_map[qid] = {"question_prompt": q.get("prompt"), "group": q.get("group"), "domain": domain,
                         "profile_path": f"questionnaire_answers.{qid}.value", "required_for_generation": bool(q.get("required_for_generation")),
                         "required_when": q.get("required_when"), "device": q.get("device"),
                         "source_ids": source_ids,
                         "answered_households": sum(r["questionnaire_answers"][qid]["response_status"] == "answered" for r in records),
                         "not_applicable_households": sum(r["questionnaire_answers"][qid]["response_status"] == "not_applicable" for r in records),
                         "evidence_basis_values": sorted({r["questionnaire_answers"][qid]["basis"] for r in records}),
                         "case_answer_or_feedback": False}
    behavior_rows = []
    for r in records:
        qvals = r["questionnaire_answers"]
        behavior_qids = [qid for qid in qvals if qid.startswith(("H_", "D_", "E_", "T_", "X_COUNT_")) or
                         qid in ("P_AC_RANGE", "P_AC_CHANGE", "P_EV_TARGET", "P_EV_RESERVE", "P_HOT_WATER", "P_PREHEAT")]
        behavior_rows.append({"role_id": r["role_id"], "members": [
            {k: m[k] for k in ("member_id", "age_years_design", "routine", "life_roles",
                              "typical_weekday_home_windows", "typical_weekend_home_windows")}
            for m in r["members"]],
            "usual_presence": r["usual_presence"], "device_ownership": r["device_ownership"],
            "device_control_scope": r["device_control_scope"],
            "ordinary_operation_conditions": r["ordinary_operation_conditions"],
            "home_ev_driver_member_id": r["home_ev_driver_member_id"],
            "ordinary_device_answers": {qid: qvals[qid] for qid in behavior_qids}})
    behavior = {"schema_version": "eb.synthetic_fixed_behavior_300.v1", "n": 300,
                "A_family_sha256": digest(FAMILY) if use_A else None,
                "scope": "ordinary_habits_and_device_constraints_only_not_event_day_presence_or_human_feedback",
                "records": behavior_rows}
    behavior_path = HERE / "behavior_300.json"
    behavior_path.write_text(json.dumps(behavior, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    output = {"schema_version": "eb.synthetic_fixed_profile_300.v1", "questionnaire_schema_version": codebook["schema_version"],
              "seed": SEED, "n": 300, "source_sha256": {"questionnaire": digest(QUESTIONS), "skeleton": digest(SKELETON),
                                                    "cohort": digest(COHORT), "A_family": digest(FAMILY) if use_A else None,
                                                    "C_building": digest(BUILDING) if use_C else None,
                                                    "F_shared_whole_area": digest(F_SHARED_AREA) if use_C else None},
              "family_interface_status": "A_structure_integrated" if use_A else "provisional_awaiting_A_structure",
              "building_interface_status": "C_manifest_integrated" if use_C else "awaiting_C_manifest",
              "behavior_subset_sha256": digest(behavior_path),
              "population_weight": None, "fixed_profile_ready": use_A and use_C, "full_household_package_ready": False,
              "training_release": False, "profiles": records}
    (HERE / "profile_300.json").write_text(json.dumps(output, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (HERE / "QUESTION_MAPPING_66.json").write_text(json.dumps({"n_questions": 66, "n_required_for_generation": 42,
        "rule": "required_for_generation is conditional on selected_device/show_when; no participant case feedback is filled",
        "questions": path_map}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"profiles": len(records), "A_integrated": use_A, "C_integrated": use_C,
                      "device_counts": dict(collections.Counter(d for r in records for d in r["device_ownership"])),
                      "member_count": sum(len(r["members"]) for r in records)}, ensure_ascii=False))


if __name__ == "__main__":
    main()
