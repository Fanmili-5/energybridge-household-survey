#!/usr/bin/env python3
"""Inject B pre-event routines/devices into C base IDFs, only under D.

All loads are explicit experimental proxies. No human response or EB online
plan is generated. Source building loads outside owned zones remain boundary
conditions and are never included in household device accounting.
"""
from __future__ import annotations

import argparse
from collections import Counter
from functools import lru_cache
from hashlib import sha256
import json
from pathlib import Path
import re
import sys

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
C_DIR = ROOT / "C_idf"
REPO = HERE.parents[6]
sys.path.insert(0, str(REPO / "scripts"))
sys.path.insert(0, str(C_DIR))
from scale_destep_highs_physics import parse_idf  # noqa: E402
from build_buildings import render  # noqa: E402
from ac_proxy import append_ac_proxy  # noqa: E402

B_PATH = ROOT / "B_profile/profile_300.json"
B_BEHAVIOR_PATH = ROOT / "B_profile/behavior_300.json"
C_PATH = C_DIR / "building_300.json"
CODEBOOK_PATH = REPO / "QUESTIONNAIRE_CODEBOOK.json"
SOURCE_FUNCTIONS_PATH = C_DIR / "source_unit_audit_300.json"
TERRACED_FUNCTIONS_PATH = C_DIR / "terraced_room_function_13.json"
OUT = HERE / "runtime_inputs"
DAYS = ("Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday")
POWERS_W = {"washer": 500, "dishwasher": 1000, "dryer": 1800,
            "electric_water_heater": 1800, "home_ev": 3300}
DURATION_H = {"electric_water_heater": 1.0, "home_ev": 3.0}
# DOE/NREL 2014 House Simulation Protocols reference-home shares for laundry
# and dishwasher; the water-heater and EV entries are conservative experimental
# boundaries. Radiant is set to zero, so the remaining indoor sensible gain is
# convective. These are scenario assumptions, not measurements of these roles.
RECOMMENDED_GAINS = {
    "washer": {"latent": 0.0, "radiant": 0.0, "lost": 0.20},
    "dryer": {"latent": 0.05, "radiant": 0.0, "lost": 0.80},
    "dishwasher": {"latent": 0.15, "radiant": 0.0, "lost": 0.25},
    "electric_water_heater": {"latent": 0.0, "radiant": 0.0, "lost": 1.0},
    "home_ev": {"latent": 0.0, "radiant": 0.0, "lost": 1.0},
}
GAIN_SCENARIOS = ("R", "L", "S", "U")
WATER_HEATER_STANDBY_W = 31.86
STEP_MIN = 10
SLOTS_PER_HOUR = 60 // STEP_MIN
SLOTS_PER_DAY = 24 * SLOTS_PER_HOUR


def sha(path: Path) -> str:
    return sha256(path.read_bytes()).hexdigest()


def answer(profile: dict, key: str):
    return profile["questionnaire_answers"][key]["value"]


@lru_cache(maxsize=1)
def codebook_questions() -> dict:
    return {q["id"]: q for q in json.loads(CODEBOOK_PATH.read_text())["questions"]}


@lru_cache(maxsize=1)
def source_room_functions() -> dict[str, dict[str, str]]:
    apartment = {case["role_id"]: case["source_room_functions"]
                 for case in json.loads(SOURCE_FUNCTIONS_PATH.read_text())["cases"]}
    terraced = {case["role_id"]: {zone["zone"]: zone["source_function"]
                                         for zone in case["zones"]}
                for case in json.loads(TERRACED_FUNCTIONS_PATH.read_text())["cases"]}
    apartment.update(terraced)
    return apartment


def verify_duration_units() -> None:
    questions = codebook_questions()
    for device in ("washer", "dishwasher", "dryer"):
        question = questions[f"T_{device}"]
        if "分钟" not in question["prompt"]:
            raise ValueError(f"unexpected displayed duration unit: {device}")
        options = [o for o in question["options"] if re.fullmatch(r"\d+\s*分钟", o["label"])]
        if not options or not any(o["value"] == "0.5" and o["label"] == "30 分钟" for o in options):
            raise ValueError(f"missing 0.5 hour to 30 minute mapping: {device}")
        if any(abs(float(o["value"])*60-int(o["label"].split()[0])) > 1e-6 for o in options):
            raise ValueError(f"display minute / stored hour mapping failed: {device}")
    if round(0.5*60/STEP_MIN) != 3:
        raise ValueError("30-minute task is not three 10-minute schedule slots")


def minutes(text: str | float) -> int:
    s = str(text)
    if ":" in s:
        h, m = s.split(":", 1)
        return int(h)*60 + int(m)
    return round(float(s)*60)


def verify_clock_options() -> None:
    """The frozen questionnaire stores hour values but displays clock labels."""
    questions = codebook_questions()
    for device in POWERS_W:
        prefixes = ("H", "E", "D") if device in ("washer", "dishwasher", "dryer") else ("H", "D")
        for prefix in prefixes:
            qid = f"{prefix}_{device}"
            for option in questions[qid]["options"]:
                if re.fullmatch(r"\d+(?:\.\d+)?", str(option["value"])):
                    if minutes(option["value"]) != minutes(option["label"]):
                        raise ValueError(f"clock label/value mismatch: {qid} {option}")
                elif prefix != "H" or not re.fullmatch(r"\d{2}:\d{2}", option["label"]):
                    raise ValueError(f"unrecognized clock alias: {qid} {option}")


def clock_minutes(qid: str, value: str | float) -> int:
    options = {str(option["value"]): option["label"]
               for option in codebook_questions()[qid]["options"]}
    if str(value) not in options:
        raise ValueError(f"clock answer absent from frozen codebook: {qid} {value}")
    label_minutes = minutes(options[str(value)])
    if re.fullmatch(r"\d+(?:\.\d+)?", str(value)) and minutes(value) != label_minutes:
        raise ValueError(f"clock answer label/value mismatch: {qid} {value}")
    return label_minutes


def ordinary_device_window(profile: dict, device: str) -> dict:
    """Validate the reported H/E/D/T contract before applying a power proxy."""
    role = profile["role_id"]
    start = clock_minutes(f"H_{device}", answer(profile, f"H_{device}"))
    if device in ("washer", "dishwasher", "dryer"):
        earliest = clock_minutes(f"E_{device}", answer(profile, f"E_{device}"))
        deadline = clock_minutes(f"D_{device}", answer(profile, f"D_{device}"))
        duration_value = str(answer(profile, f"T_{device}"))
        duration_options = {str(option["value"]): option["label"]
                            for option in codebook_questions()[f"T_{device}"]["options"]}
        if duration_value not in duration_options:
            raise ValueError(f"task duration absent from frozen codebook: {role} {device}")
        duration = minutes(duration_value)
        absolute_deadline = deadline + (1440 if deadline < earliest else 0)
        absolute_start = start + (1440 if deadline < earliest and start < earliest else 0)
        if not earliest <= absolute_start <= absolute_deadline-duration:
            raise ValueError(f"reported ordinary task violates E/D/T: {role} {device}")
        return {"reported_start_min": start, "reported_earliest_min": earliest,
                "reported_deadline_min": deadline, "modeled_duration_min": duration,
                "duration_source": f"T_{device}_reported"}
    end = clock_minutes(f"D_{device}", answer(profile, f"D_{device}"))
    span = (end-start) % 1440
    duration = round(DURATION_H[device]*60)
    if not span or duration > span:
        raise ValueError(f"power-proxy duration exceeds reported H/D service window: {role} {device}")
    return {"reported_start_min": start, "reported_end_min": end,
            "reported_service_window_min": span, "modeled_duration_min": duration,
            "duration_source": "declared_experimental_power_proxy_not_reported_full_service"}


def windows(member: dict, day: int, role_id: str, index: int) -> list[tuple[int, int]]:
    key = "typical_weekend_home_windows" if day >= 5 else "typical_weekday_home_windows"
    intervals = member[key]
    if intervals is None:
        # B intentionally leaves irregular ordinary-day timing uncertain.
        # This fixed fill is an experimental simulation scenario, not a B fact.
        h = int.from_bytes(sha256(f"{role_id}:{index}:{day}:irregular".encode()).digest()[:2], "big")
        intervals = [["00:00", "08:00"], ["16:00", "24:00"]] if h % 2 else [["00:00", "10:00"], ["14:00", "24:00"]]
    return [(minutes(a), minutes(b)) for a, b in intervals]


def compressed_schedule(name: str, values: list[list[float]], schedule_type: str) -> list[str]:
    if len(values) != 7:
        raise ValueError("one Sunday-fallback week requires seven day schedules")
    row = ["Schedule:Compact", name, schedule_type, "Through: 12/31"]
    for day, slots in list(zip(DAYS, values)) + [("AllOtherDays", values[-1])]:
        if len(slots) != SLOTS_PER_DAY:
            raise ValueError("10-minute schedule must have 144 intervals")
        row.append(f"For: {day}")
        for i in range(1, SLOTS_PER_DAY+1):
            if i == SLOTS_PER_DAY or slots[i] != slots[i-1]:
                h, m = divmod(i*STEP_MIN, 60)
                row += [f"Until: {h:02}:{m:02}", f"{slots[i-1]:g}"]
    return row


def active_days(role: str, device: str, frequency: str | None) -> set[int]:
    n = {"days_2_3": 3, "days_4_6": 5, "days_7": 7}.get(frequency)
    if n is None:
        raise ValueError(f"missing/invalid frequency: {role} {device} {frequency}")
    order = sorted(range(7), key=lambda d: sha256(f"{role}:{device}:weekly:{d}".encode()).digest())
    return set(order[:n])


def ac_habit_window(profile: dict) -> tuple[int, int]:
    mode = answer(profile, "H_ac")
    if mode == "all_day": return 0, 1440
    if mode in ("afternoon", "evening"):
        options = {option["value"]: option["label"]
                   for option in codebook_questions()["H_ac"]["options"]}
        label = options[mode]
        match = re.search(r"(\d{2}:\d{2})—(\d{2}:\d{2})", label)
        if not match:
            raise ValueError(f"frozen codebook AC time label cannot be parsed: {mode} {label}")
        return minutes(match.group(1)), minutes(match.group(2))
    if mode == "custom": return minutes(answer(profile, "H_ac_start")), minutes(answer(profile, "H_ac_end"))
    raise ValueError(f"owned AC missing ordinary window: {profile['role_id']} {mode}")


def choose_ac_zones(building: dict, count: int, functions: dict[str, str]) -> list[str]:
    controllable = building["ac_controllable_zones"]
    if count == 0: return []
    priority_by_function = {"主卧室": 0, "次卧室": 1, "起居室": 2}
    eligible = [zone for zone in controllable if functions.get(zone) in priority_by_function]
    if count > len(eligible):
        raise ValueError(f"AC units exceed source bedroom/living zones: {building['role_id']}")
    def zone_priority(z: str) -> tuple:
        return (priority_by_function[functions[z]], controllable.index(z))
    return sorted(eligible, key=zone_priority)[:count]


def device_heat_zone(building: dict, functions: dict[str, str], device: str) -> tuple[str, str]:
    """Choose an experimental source-function placement; EV has no inside gain."""
    if device == "home_ev":
        return building["household_owned_zones"][0], "outdoor_charging_accounting_anchor_no_indoor_heat"
    wanted = {"washer": "洗手间", "dryer": "洗手间",
              "dishwasher": "厨房", "electric_water_heater": "洗手间"}[device]
    candidates = list(building["household_owned_zones"])
    if building["housing_mode"] == "shared_flat_private_rooms":
        candidates += building["area_rule"]["source_shared_common_zone_names"]
    zones = [zone for zone in candidates if functions.get(zone) == wanted]
    if not zones:
        raise ValueError(f"no source-function {wanted} zone for {building['role_id']} {device}")
    return zones[0], f"source_room_function:{wanted}"


def gain_fractions(device: str, scenario: str) -> dict[str, float]:
    if scenario not in GAIN_SCENARIOS:
        raise ValueError(f"unsupported appliance heat scenario: {scenario}")
    if scenario == "L":
        gain = {"latent": 0.0, "radiant": 0.0, "lost": 1.0}
    elif scenario == "U" and device != "home_ev":
        gain = {"latent": 0.0, "radiant": 0.0, "lost": 0.0}
    else:
        gain = RECOMMENDED_GAINS[device].copy()
    if any(not 0 <= value <= 1 for value in gain.values()) or sum(gain.values()) > 1+1e-9:
        raise ValueError(f"invalid ElectricEquipment gain fractions: {device} {scenario}")
    gain["convective"] = round(1-sum(gain.values()), 9)
    gain["indoor_sensible"] = round(gain["radiant"]+gain["convective"], 9)
    gain["indoor_total"] = round(1-gain["lost"], 9)
    return gain


def task_schedule(profile: dict, device: str) -> list[list[float]]:
    role = profile["role_id"]
    n = int(answer(profile, f"X_COUNT_{device}"))
    if n < 1:
        raise ValueError("unowned device passed to task schedule")
    active = active_days(role, device, answer(profile, f"X_FREQ_{device}"))
    reported = ordinary_device_window(profile, device)
    start = reported["reported_start_min"]
    for day in active:
        present = any(any(a <= start < b for a, b in windows(member, day, role, index))
                      for index, member in enumerate(profile["members"]))
        if not present:
            raise ValueError(f"ordinary device start without household presence: {role} {device} day={day}")
        if device == "home_ev":
            driver = profile["home_ev_driver_member_id"]
            found = [(index, member) for index, member in enumerate(profile["members"])
                     if member["member_id"] == driver]
            if len(found) != 1 or not any(a <= start < b for a, b in windows(found[0][1], day, role, found[0][0])):
                raise ValueError(f"ordinary EV start before assigned driver is home: {role} day={day}")
    slots = max(1, round(reported["modeled_duration_min"]/STEP_MIN))
    first = min(SLOTS_PER_DAY-1, start//STEP_MIN)
    result = [[0.0]*SLOTS_PER_DAY for _ in range(7)]
    for day in active:
        for offset in range(slots):
            absolute = day*SLOTS_PER_DAY + first + offset
            result[(absolute//SLOTS_PER_DAY) % 7][absolute % SLOTS_PER_DAY] = 1.0
    return result


def remove_base_ac_proxy(rows: list[list[str]]) -> list[list[str]]:
    kept = []
    for r in rows:
        typ = r[0].lower()
        name = r[1].lower() if len(r)>1 else ""
        if typ.startswith("energymanagementsystem:") and (name.startswith("eb_ac_") or name.startswith("eb selected")):
            continue
        if typ == "output:meter" and name == "cooling:electricity":
            continue
        if typ == "output:variable" and ("eb selected" in name or
            (len(r)>2 and "eb selected" in r[2].lower())):
            continue
        kept.append(r)
    return kept


def effective_zone_multipliers(rows: list[list[str]]) -> dict[str, dict[str, float]]:
    """Read the actual EnergyPlus Zone and ZoneGroup replication in this IDF."""
    zones = {r[1].casefold(): r for r in rows if r[0].lower() == "zone"}
    lists = {r[1].casefold(): r[2:] for r in rows if r[0].lower() == "zonelist"}
    if len(zones) != sum(r[0].lower() == "zone" for r in rows):
        raise ValueError("duplicate zone names")
    group_by_zone = {}
    for group in (r for r in rows if r[0].lower() == "zonegroup"):
        if len(group) < 4 or group[2].casefold() not in lists:
            raise ValueError(f"invalid ZoneGroup/ZoneList: {group}")
        multiplier = float(group[3])
        if multiplier < 1 or not multiplier.is_integer():
            raise ValueError(f"invalid ZoneGroup multiplier: {group}")
        for name in lists[group[2].casefold()]:
            key = name.casefold()
            if key not in zones or key in group_by_zone:
                raise ValueError(f"unknown or repeated ZoneGroup zone: {name}")
            group_by_zone[key] = multiplier
    result = {}
    for key, row in zones.items():
        zone_multiplier = float(row[7]) if len(row) > 7 and row[7] else 1.0
        if zone_multiplier < 1 or not zone_multiplier.is_integer():
            raise ValueError(f"invalid Zone multiplier: {row[1]}")
        group_multiplier = group_by_zone.get(key, 1.0)
        result[key] = {"zone_multiplier": zone_multiplier,
                       "zonegroup_multiplier": group_multiplier,
                       "effective_multiplier": zone_multiplier * group_multiplier}
    return result


def correct_selected_ac_proxy(rows: list[list[str]], selected_zones: list[str],
                              multipliers: dict[str, dict[str, float]], cop: float) -> list[dict]:
    """Convert replicated IdealLoads cooling into one selected household unit."""
    managers = [r for r in rows if r[0].lower() == "energymanagementsystem:programcallingmanager"
                and r[1] == "EB_AC_Proxy_Calling"]
    if len(managers) != 1 or managers[0][2] != "EndOfSystemTimestepAfterHVACReporting":
        raise ValueError("expected original AC EMS calling point missing")
    # EnergyPlus 24.1 reports SystemTimestep custom meters before the old
    # AfterHVACReporting callback. Use its documented Before callback so the
    # cooling sensor and this timestep's meter are aligned.
    managers[0][2] = "EndOfSystemTimestepBeforeHVACReporting"
    programs = [r for r in rows if r[0].lower() == "energymanagementsystem:program"
                and r[1] == "EB_AC_Proxy_Program"]
    if len(programs) != 1:
        raise ValueError("selected AC EMS program missing or duplicated")
    program = programs[0]
    selected = []
    for index, zone in enumerate(selected_zones, 1):
        factor = multipliers[zone.casefold()]
        effective = factor["effective_multiplier"]
        old = f"SET EB_AC_Elec_{index} = EB_AC_Cool_{index} / {cop:.9f}"
        matches = [i for i, instruction in enumerate(program) if instruction == old]
        if len(matches) != 1:
            raise ValueError(f"expected single AC proxy instruction: {zone}")
        if effective != 1:
            program[matches[0]] = (f"SET EB_AC_Elec_{index} = EB_AC_Cool_{index} / "
                                   f"{cop * effective:.9f}")
        selected.append({"zone": zone, **factor, "cop": cop,
                         "ems_divisor": cop * effective})
    return selected


def build_one(profile: dict, building: dict, *, days: int = 10,
              gain_scenario: str = "R") -> tuple[str, dict]:
    role = profile["role_id"]
    if gain_scenario not in GAIN_SCENARIOS:
        raise ValueError(f"unsupported gain scenario: {gain_scenario}")
    base = Path(building["idf_path"])
    if sha(base) != building["idf_sha256"]:
        raise ValueError(f"base IDF changed: {role}")
    rows = remove_base_ac_proxy(parse_idf(base.read_text()))
    timestep = [r for r in rows if r[0].lower() == "timestep"]
    if len(timestep) != 1 or int(timestep[0][1]) != SLOTS_PER_HOUR:
        raise ValueError(f"C base timestep differs from D schedule resolution: {role}")
    owned = set(building["household_owned_zones"])
    controllable_list = building["ac_controllable_zones"]
    controllable = set(controllable_list)
    if not controllable.issubset(owned):
        raise ValueError(f"control outside owned zones: {role}")
    people_rows = [r for r in rows if r[0].lower() == "people" and r[2] in owned]
    if not people_rows or abs(sum(float(r[5]) for r in people_rows) - profile["family_size"]) > 1e-6:
        raise ValueError(f"base nominal headcount mismatch: {role}")
    functions = source_room_functions()[role]
    member_days = [[windows(m, day, role, i) for i, m in enumerate(profile["members"])] for day in range(7)]
    occupancy = []
    for day in range(7):
        values = []
        for slot in range(SLOTS_PER_DAY):
            t = slot*STEP_MIN + STEP_MIN//2
            present = sum(any(a <= t < b for a, b in intervals) for intervals in member_days[day])
            values.append(round(present/profile["family_size"], 6))
        occupancy.append(values)
    rows.append(compressed_schedule("EB_Household_Occupancy", occupancy, "Fraction"))
    for r in people_rows:
        r[3] = "EB_Household_Occupancy"
    # The DeST plug-gain proxy in owned zones would double count B devices.
    # Other units' source loads stay as thermal boundary conditions only.
    source_equipment_removed = sum(r[0].lower() == "electricequipment" and r[2] in owned for r in rows)
    if source_equipment_removed != len(owned):
        raise ValueError(f"unexpected source equipment binding in owned zones: {role}")
    rows = [r for r in rows if not (r[0].lower() == "electricequipment" and r[2] in owned)]
    owned_devices = set(profile["device_ownership"])
    ac_count_value = answer(profile, "X_COUNT_ac")
    ac_count = int(ac_count_value) if ac_count_value is not None else 0
    if ("ac" in owned_devices) != (ac_count > 0):
        raise ValueError(f"AC ownership/count mismatch: {role}")
    selected_ac = choose_ac_zones(building, ac_count, functions)
    zone_multipliers = effective_zone_multipliers(rows)
    if any(zone.casefold() not in zone_multipliers for zone in selected_ac):
        raise ValueError(f"selected AC zone lacks Zone object: {role}")
    ac_values = [[40.0]*SLOTS_PER_DAY for _ in range(7)]
    if ac_count:
        setpoint = float(answer(profile, "H_ac_temp"))
        start, end = ac_habit_window(profile)
        active = active_days(role, "ac", answer(profile, "X_FREQ_ac"))
        for day in active:
            for slot in range(SLOTS_PER_DAY):
                t = slot*STEP_MIN + STEP_MIN//2
                in_window = (start <= t < end) if end > start else (t >= start or t < end)
                if in_window and occupancy[day][slot] > 0:
                    ac_values[day][slot] = setpoint
    control_by_schedule = {s["cooling_schedule"]: s["zone"] for s in building["controls"]["zone_control_schedules"]}
    if set(control_by_schedule.values()) != controllable:
        raise ValueError(f"C AC schedules do not match zones: {role}")
    ideal_by_name = {r[1]:r for r in rows if r[0].lower() == "zonehvac:idealloadsairsystem"}
    if not all(z+" Ideal Loads" in ideal_by_name for z in controllable):
        raise ValueError(f"C AC IdealLoads systems do not match zones: {role}")
    rows.append(compressed_schedule("EB_AC_Off", [[0.0]*SLOTS_PER_DAY for _ in range(7)], "Any Number"))
    rows.append(compressed_schedule("EB_AC_Available",
                                    [[1.0 if value < 39.9 else 0.0 for value in day] for day in ac_values],
                                    "Any Number"))
    rows.append(compressed_schedule("EB_Heating_Off", [[-50.0]*SLOTS_PER_DAY for _ in range(7)], "Any Number"))
    dual_by_name = {r[1]:r for r in rows if r[0].lower() == "thermostatsetpoint:dualsetpoint"}
    if not all("EB_Dual_"+schedule.rsplit("_",1)[1] in dual_by_name for schedule in control_by_schedule):
        raise ValueError(f"C dual thermostat schedules do not match zones: {role}")
    for schedule in control_by_schedule:
        dual_by_name["EB_Dual_"+schedule.rsplit("_",1)[1]][2] = "EB_Heating_Off"
    for zone in controllable_list:
        ideal_by_name[zone+" Ideal Loads"][2] = "EB_AC_Available" if zone in selected_ac else "EB_AC_Off"
        # The source IdealLoads object has a separate heating availability
        # field. Disable it for this cooling-only household AC experiment.
        if len(ideal_by_name[zone+" Ideal Loads"]) <= 16:
            raise ValueError(f"C IdealLoads lacks heating availability field: {role} {zone}")
        ideal_by_name[zone+" Ideal Loads"][16] = "EB_AC_Off"
        rows.append(["Output:Variable", zone+" Ideal Loads",
                     "Zone Ideal Loads Supply Air Total Heating Energy", "Hourly"])
        rows.append(["Output:Variable", zone+" Ideal Loads",
                     "Zone Ideal Loads Supply Air Mass Flow Rate", "Hourly"])
    for r in rows:
        if r[0].lower() == "schedule:compact" and r[1] in control_by_schedule:
            zone = control_by_schedule[r[1]]
            values = ac_values if zone in selected_ac else [[40.0]*SLOTS_PER_DAY for _ in range(7)]
            r[:] = compressed_schedule(r[1], values, "Any Number")
    if selected_ac:
        append_ac_proxy(rows, selected_ac, cop=3.0)
        selected_ac_multipliers = correct_selected_ac_proxy(rows, selected_ac, zone_multipliers, 3.0)
    else:
        selected_ac_multipliers = []
    device_bindings = []
    for device, watts in POWERS_W.items():
        if device not in owned_devices:
            if answer(profile, f"X_COUNT_{device}") is not None:
                raise ValueError(f"unowned device count is set: {role} {device}")
            continue
        count = int(answer(profile, f"X_COUNT_{device}"))
        zone_for_device, heat_location_assumption = device_heat_zone(building, functions, device)
        ordinary_window = ordinary_device_window(profile, device)
        schedule = f"EB_Device_{device}"
        values = task_schedule(profile, device)
        rows.append(compressed_schedule(schedule, values, "Fraction"))
        name = f"EB_Private_{device}"
        gains = gain_fractions(device, gain_scenario)
        rows.append(["ElectricEquipment", name, zone_for_device, schedule,
                     "EquipmentLevel", f"{watts*count:g}", "", "",
                     f"{gains['latent']:g}", f"{gains['radiant']:g}", f"{gains['lost']:g}",
                     f"EB_Private_{device}"])
        rows.append(["Output:Variable", name, "Electric Equipment Electricity Energy", "Hourly"])
        device_bindings.append({"device": device, "owned_units": count,
                                "idf_equipment_name": name, "zone": zone_for_device,
                                "source_room_function": functions.get(zone_for_device),
                                "heat_location_assumption": heat_location_assumption,
                                "indoor_heat_fraction": gains["indoor_total"],
                                "heat_gain_fractions": gains,
                                "ordinary_window_contract": ordinary_window,
                                "experimental_total_power_w": watts*count,
                                "schedule_name": schedule,
                                "active_hours_per_week": round(sum(sum(day) for day in values)*STEP_MIN/60, 2),
                                "meter_scope": "equipment_key_only_not_building_interior_equipment_meter"})
    if gain_scenario == "S" and "electric_water_heater" in owned_devices:
        standby_zone, standby_location = device_heat_zone(building, functions, "electric_water_heater")
        standby_name = "EB_Private_electric_water_heater_standby"
        standby_schedule = "EB_Water_Heater_Standby"
        rows.append(compressed_schedule(standby_schedule, [[1.0]*SLOTS_PER_DAY for _ in range(7)], "Fraction"))
        rows.append(["ElectricEquipment", standby_name, standby_zone, standby_schedule,
                     "EquipmentLevel", f"{WATER_HEATER_STANDBY_W:g}", "", "", "0", "0", "0",
                     standby_name])
        rows.append(["Output:Variable", standby_name, "Electric Equipment Electricity Energy", "Hourly"])
        device_bindings.append({"device": "electric_water_heater_standby", "owned_units": 1,
                                "idf_equipment_name": standby_name, "zone": standby_zone,
                                "source_room_function": functions[standby_zone],
                                "heat_location_assumption": standby_location,
                                "indoor_heat_fraction": 1.0,
                                "heat_gain_fractions": {"latent": 0.0, "radiant": 0.0, "lost": 0.0,
                                                        "convective": 1.0, "indoor_sensible": 1.0,
                                                        "indoor_total": 1.0},
                                "ordinary_window_contract": {"duration_source": "experimental_continuous_indoor_tank_standby"},
                                "experimental_total_power_w": WATER_HEATER_STANDBY_W,
                                "schedule_name": standby_schedule,
                                "active_hours_per_week": 168.0,
                                "meter_scope": "separate_standby_electricity_and_indoor_heat_same_object"})
    period = [r for r in rows if r[0].lower() == "runperiod"]
    if len(period) != 1:
        raise ValueError("one run period required")
    period[0][2:7] = ["7", "14", "", "7", str(13+days)]
    period[0][8] = "Monday"
    if days != 10 and not 1 <= days <= 17:
        raise ValueError("July run length must be 1-17 days")
    header = (f"! D household behavior injection for {role}; C base IDF SHA-256 {building['idf_sha256']}.\n"
              f"! B profile SHA recorded in manifest; schedules and powers are explicit synthetic proxies.\n"
              f"! Only EB private equipment keys and selected AC proxy zones belong to the household meter.")
    body = render(rows, header)
    manifest = {"role_id": role, "C_base_idf_sha256": building["idf_sha256"],
                "B_behavior_facts": {"family_size": profile["family_size"],
                                     "ac_owned_units": ac_count,
                                     "ac_habit": answer(profile, "H_ac")},
                "run_days": days, "run_period": "July 14-23 synthetic weekday alignment" if days == 10 else f"July 14-{13+days}",
                "occupancy_method": "B_member_home_windows_aggregated_fraction_by_owned_zone; irregular_missing_windows_deterministically_filled",
                "controlled_room_presence": "household_presence_proxy_only; room_level_presence_unobserved",
                "occupancy_schedule": "EB_Household_Occupancy",
                "irregular_member_count": sum(m["typical_weekday_home_windows"] is None for m in profile["members"]),
                "source_owned_zone_equipment_removed": source_equipment_removed,
                "ac_selected_zones": selected_ac,
                "ac_selected_zone_multipliers": selected_ac_multipliers,
                "ac_meter_contract_version": "eb.D.single_household_AC_meter.v3",
                "ac_meter_calling_point": "EndOfSystemTimestepBeforeHVACReporting" if ac_count else None,
                "ac_unselected_owned_zones_off": sorted(controllable - set(selected_ac)),
                "ac_selected_availability_tracks_B_schedule": True,
                "ac_active_hours_by_weekday": [sorted({index//SLOTS_PER_HOUR+1 for index,value in enumerate(day) if value < 39.9})
                                               for day in ac_values],
                "heating_disabled_in_household_owned_controlled_zones": True,
                "ac_proxy_COP": 3.0 if ac_count else None,
                "appliance_heat_gain_scenario": gain_scenario,
                "appliance_heat_gain_basis": "DOE_NREL_2014_reference_appliance_shares_plus_declared_water_heater_EV_boundary",
                "appliance_sensible_split": "all_indoor_sensible_as_convective_experimental_simplification",
                "devices": device_bindings,
                "ordinary_operation_conditions": profile["ordinary_operation_conditions"],
                "home_ev_driver_member_id": profile["home_ev_driver_member_id"],
                "event_specific_precooling_permission": None,
                "electricity_accounting": "selected_private_AC_proxy_plus_EB_Private_equipment_only; source_DeST_other_units_and_lights_excluded",
                "plan_origin": "ordinary_B_pre_event_synthetic_schedule_not_EB_or_human_response"}
    return body, manifest


def main() -> None:
    verify_duration_units()
    verify_clock_options()
    parser = argparse.ArgumentParser()
    parser.add_argument("--roles", nargs="*", help="selected role IDs; omit for all 300")
    parser.add_argument("--days", type=int, default=10)
    args = parser.parse_args()
    bdoc = json.loads(B_PATH.read_text())
    cdoc = json.loads(C_PATH.read_text())
    if bdoc["behavior_subset_sha256"] != sha(B_BEHAVIOR_PATH):
        raise ValueError("B profile/behavior subset hash differs")
    if bdoc["source_sha256"]["C_building"] != sha(C_PATH):
        raise ValueError("B/C hashes differ; wait for frozen inputs")
    b = {r["role_id"]: r for r in bdoc["profiles"]}
    c = {r["role_id"]: r for r in cdoc["records"]}
    wanted = args.roles or sorted(b)
    OUT.mkdir(exist_ok=True)
    records = []
    for role in wanted:
        body, manifest = build_one(b[role], c[role], days=args.days)
        path = OUT / f"{role}.idf"
        path.write_text(body)
        manifest["idf_path"] = str(path)
        manifest["idf_sha256"] = sha(path)
        manifest["weather_epw_path"] = c[role]["weather_epw_path"]
        manifest["weather_epw_sha256"] = c[role]["weather_epw_sha256"]
        records.append(manifest)
    records.sort(key=lambda r:r["role_id"])
    report = {"schema_version": "eb.behavior_injected_idf_manifest.v1", "n": len(records),
              "A_family_sha256": cdoc["family_sha256"], "B_profile_sha256": sha(B_PATH),
              "B_behavior_sha256": sha(B_BEHAVIOR_PATH),
              "questionnaire_codebook_sha256": sha(CODEBOOK_PATH),
              "task_duration_unit_contract": {"display_unit":"minute", "value_unit":"hour",
                                              "idf_schedule_resolution_minutes":STEP_MIN,
                                              "example":"0.5 value -> 30 displayed minutes -> three 10-minute slots"},
              "appliance_heat_model": {"scenario":"R", "fraction_basis":RECOMMENDED_GAINS,
                                       "radiant_split":"zero; all sensible gain is convective",
                                       "reference":"https://www.energy.gov/sites/default/files/2014/03/f13/house_simulation_protocols_2014.pdf",
                                       "water_heater_EV_boundary":"lost=1 experimental conservative default; not measured in these roles",
                                       "alternative_scenarios":["L","S","U"]},
              "C_building_sha256": sha(C_PATH), "run_days": args.days,
              "ac_meter_contract_version": "eb.D.single_household_AC_meter.v3",
              "ac_meter_method": "selected_zone_IdealLoads_cooling_J_divided_by_Zone_multiplier_times_ZoneGroup_multiplier_times_COP",
              "ac_meter_calling_point": "EndOfSystemTimestepBeforeHVACReporting",
              "status": "materialized_inputs_not_yet_runtime_validated", "records": records}
    (HERE/"behavior_input_manifest.json").write_text(json.dumps(report, ensure_ascii=False, indent=2)+"\n")
    print(json.dumps({"n": len(records), "run_days": args.days,
                      "ac_none": sum(not r["ac_selected_zones"] for r in records),
                      "devices": dict(Counter(d["device"] for r in records for d in r["devices"]))}, ensure_ascii=False))


if __name__ == "__main__":
    main()
