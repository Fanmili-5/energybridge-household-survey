#!/usr/bin/env python3
"""Build deterministic, lawful offline ten-day candidate IDFs from frozen D baselines.

No model, planning API, participant response, or simulated-result search is used.
"""
from __future__ import annotations

import argparse
from collections import Counter
from copy import deepcopy
from hashlib import sha256
import json
from pathlib import Path
import sys

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
REPO = HERE.parents[6]
D_DIR = ROOT/"D_integration"
sys.path.insert(0, str(D_DIR))
sys.path.insert(0, str(REPO/"realtime_pilot"))

from build_runtime_inputs import (DAYS, STEP_MIN, SLOTS_PER_DAY, active_days,
                                  answer, clock_minutes, minutes, ordinary_device_window,
                                  parse_idf, render, sha, windows)
from paired_contract import task_timing  # deterministic EB intake gate; no upstream model call

POLICY_VERSION = "eb.g.fixed_policy.v1"
POLICY_SEED = "eb.g.20260926.fixed-policy.v1"
DEVICE_ORDER = ("washer", "dishwasher", "dryer", "electric_water_heater", "home_ev")
OUT = HERE/"candidate_idfs"
MANIFEST = HERE/"candidate_input_manifest_300.json"
D_MANIFEST = D_DIR/"behavior_input_manifest.json"
D_RUNTIME = D_DIR/"runtime_300.json"
B_PATH = ROOT/"B_profile/profile_300.json"
C_PATH = ROOT/"C_idf/building_300.json"
D_FINAL = D_DIR/"final_evidence_chain.json"
PUBLIC_ROLE_MANIFEST = ROOT/"E_collection_release/public_role_package/PUBLIC_MANIFEST.json"
METER_VERSION = "eb.D.single_household_AC_meter.v3"
POLICY_LOCK = HERE/"POLICY_LOCK.json"


def stable_hash(value: object) -> str:
    return sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
                             separators=(",", ":"), allow_nan=False).encode()).hexdigest()


def public_role_identity() -> dict:
    """Bind the fixed public role package to its actual table bytes."""
    public=json.loads(PUBLIC_ROLE_MANIFEST.read_text())
    if (public["schema_version"]!="eb.public_synthetic_fixed_roles.v1" or
        public["source_input_sha256"]["B_profile"]!=sha(B_PATH)):
        raise ValueError("public fixed roles do not bind current B profile")
    for name,entry in public["tables"].items():
        if sha(PUBLIC_ROLE_MANIFEST.parent/name)!=entry["sha256"]:
            raise ValueError(f"public fixed role table bytes changed: {name}")
    return {"public_role_manifest_sha256":sha(PUBLIC_ROLE_MANIFEST),
            "public_role_table_sha256":{name:entry["sha256"]
                                        for name,entry in public["tables"].items()},
            "public_role_status":public["status"]}


def verify_policy_lock(meter_identity_sha256: str) -> dict:
    lock=json.loads(POLICY_LOCK.read_text())
    if (lock.get("status")!="frozen_before_candidate_results" or
        lock.get("policy_version")!=POLICY_VERSION or
        lock.get("policy_seed")!=POLICY_SEED or
        lock.get("generator_source_sha256")!=sha(Path(__file__)) or
        lock.get("meter_identity_sha256")!=meter_identity_sha256):
        raise ValueError("G action policy/seed/source/input identity differs from pre-result lock")
    return lock


def parse_week_schedule(row: list[str]) -> list[list[float]]:
    if row[0].lower() != "schedule:compact" or row[3] != "Through: 12/31":
        raise ValueError(f"expected frozen D weekly compact schedule: {row[:4]}")
    groups: dict[str,list[float]] = {}
    name = None
    slot = 0
    i = 4
    while i < len(row):
        field = row[i]
        if field.startswith("For:"):
            if name is not None and slot != SLOTS_PER_DAY:
                raise ValueError(f"incomplete D day schedule: {row[1]} {name}")
            name = field.removeprefix("For:").strip()
            groups[name] = [float("nan")]*SLOTS_PER_DAY
            slot = 0
            i += 1
            continue
        if field.startswith("Until:") and name is not None and i+1 < len(row):
            end = minutes(field.removeprefix("Until:").strip())
            if end%STEP_MIN or not slot < end//STEP_MIN <= SLOTS_PER_DAY:
                raise ValueError(f"invalid D schedule boundary: {row[1]} {field}")
            groups[name][slot:end//STEP_MIN] = [float(row[i+1])]*(end//STEP_MIN-slot)
            slot = end//STEP_MIN
            i += 2
            continue
        raise ValueError(f"unexpected frozen D schedule field: {row[1]} {field}")
    if name is None or slot != SLOTS_PER_DAY or any(day not in groups for day in DAYS):
        raise ValueError(f"D week schedule lacks seven complete days: {row[1]}")
    if groups.get("AllOtherDays") != groups["Sunday"]:
        raise ValueError(f"D fallback no longer mirrors Sunday: {row[1]}")
    return [groups[day] for day in DAYS]


def calendar_schedule(name: str, kind: str, values: list[list[float]]) -> list[str]:
    if len(values) != 10 or any(len(day) != SLOTS_PER_DAY for day in values):
        raise ValueError("ten 144-slot calendar days required")
    row = ["Schedule:Compact", name, kind]
    for index, day in enumerate(values):
        row += [f"Through: 07/{14+index:02d}", "For: AllDays"]
        for slot in range(1, SLOTS_PER_DAY+1):
            if slot == SLOTS_PER_DAY or day[slot] != day[slot-1]:
                hour, minute = divmod(slot*STEP_MIN, 60)
                row += [f"Until: {hour:02d}:{minute:02d}", f"{day[slot-1]:g}"]
    row += ["Through: 12/31", "For: AllDays", "Until: 24:00", f"{values[-1][-1]:g}"]
    return row


def interval_presence(profile: dict, absolute_start_min: int, duration_min: int,
                      day_index_zero: int, *, driver_only: bool) -> bool:
    """Require someone, or the assigned EV driver, home for every task slot."""
    role = profile["role_id"]
    for minute in range(absolute_start_min, absolute_start_min+duration_min, STEP_MIN):
        relative_day,clock=divmod(minute+STEP_MIN//2,1440)
        if relative_day < day_index_zero or relative_day > day_index_zero+1:
            return False
        weekday=relative_day%7
        if not any((not driver_only or member["member_id"]==profile["home_ev_driver_member_id"])
                   and any(a<=clock<b for a,b in windows(member,weekday,role,index))
                   for index,member in enumerate(profile["members"])):
            return False
    return True


def shift_offsets(role: str, device: str, day_index_one: int) -> list[int]:
    bit = sha256(f"{POLICY_SEED}|{role}|{device}|{day_index_one}".encode()).digest()[0]&1
    positive = [30,20,10]
    negative = [-30,-20,-10]
    return [x for pair in zip(positive,negative) for x in (pair if bit == 0 else pair[::-1])]


def legal_shift_options(current: list[float], day_zero: int, original_min: int,
                        duration_min: int, earliest_min: int, deadline_min: int,
                        offsets: list[int], presence_ok) -> list[tuple[int,list[float]]]:
    """Enumerate legal offset schedules before taking the fixed hash ordering."""
    slots=duration_min//STEP_MIN
    old_abs=day_zero*SLOTS_PER_DAY+original_min//STEP_MIN
    if (duration_min%STEP_MIN or original_min%STEP_MIN or
        not earliest_min<=original_min<=deadline_min-duration_min or
        old_abs<0 or old_abs+slots>len(current) or
        current[old_abs:old_abs+slots]!=[1.0]*slots):
        raise ValueError("baseline task is not a complete legal duration in the fixed grid")
    legal=[]
    for offset in offsets:
        proposed=original_min+offset
        if (not earliest_min<=proposed<=deadline_min-duration_min or
            proposed%STEP_MIN):
            continue
        new_abs=day_zero*SLOTS_PER_DAY+proposed//STEP_MIN
        if (new_abs<day_zero*SLOTS_PER_DAY or new_abs+slots>len(current) or
            not presence_ok(day_zero*1440+proposed,duration_min)):
            continue
        trial=current.copy()
        trial[old_abs:old_abs+slots]=[0.0]*slots
        if any(trial[new_abs:new_abs+slots]):
            continue
        trial[new_abs:new_abs+slots]=[1.0]*slots
        if sum(trial)!=sum(current) or trial==current:
            continue
        legal.append((offset,trial))
    return legal


def shift_one(profile: dict, device: str, day_zero: int,
              current: list[float]) -> tuple[list[float],dict] | None:
    role = profile["role_id"]
    weekday = day_zero%7
    frequency = answer(profile, f"X_FREQ_{device}")
    if weekday not in active_days(role, device, frequency):
        return None
    reported = ordinary_device_window(profile, device)
    if device in ("washer", "dishwasher", "dryer"):
        native = task_timing(profile["questionnaire_answers"], device)
        if (round(native["earliest_h"]*60) != reported["reported_earliest_min"] or
            round(native["deadline_h"]*60) != reported["reported_deadline_min"] or
            round(native["duration_h"]*60) != reported["modeled_duration_min"]):
            raise ValueError(f"native EB task intake disagrees with D: {role} {device}")
        earliest = reported["reported_earliest_min"]
        deadline = reported["reported_deadline_min"]
        if deadline < earliest:
            deadline += 1440
        original = round(native["absolute_start_h"]*60)
    else:
        earliest = reported["reported_start_min"]
        deadline = reported["reported_end_min"]
        if deadline <= earliest:
            deadline += 1440
        original = earliest
        if device == "electric_water_heater":
            hot_water_need = clock_minutes("P_HOT_WATER", answer(profile,"P_HOT_WATER"))
            if hot_water_need < earliest:
                hot_water_need += 1440
            deadline = min(deadline,hot_water_need)
    duration = reported["modeled_duration_min"]
    if (original%STEP_MIN or duration%STEP_MIN or not earliest <= original <= deadline-duration):
        raise ValueError(f"baseline task violates B/native window: {role} {device}")
    if day_zero*SLOTS_PER_DAY+original//STEP_MIN+duration//STEP_MIN > 10*SLOTS_PER_DAY:
        return None
    offsets=shift_offsets(role,device,day_zero+1)
    legal=legal_shift_options(current,day_zero,original,duration,earliest,deadline,offsets,
        lambda absolute_start,span:interval_presence(
            profile,absolute_start,span,day_zero,driver_only=device=="home_ev"))
    if legal:
        offset,trial=legal[0]
        proposed=original+offset
        directions=sorted({"earlier" if candidate_offset<0 else "later"
                           for candidate_offset,_ in legal})
        action = {"kind":"device_time_shift", "device":device,
                  "source_day_index":day_zero+1,
                  "original_start_clock_min":original%1440,
                  "candidate_start_clock_min":proposed%1440,
                  "offset_min":offset, "duration_min":duration,
                  "legal_offset_directions":directions,
                  "legal_offset_minutes_in_fixed_order":[x for x,_ in legal],
                  "direction_selection_rule":"first_legal_offset_in_hash_order_after_full_interval_checks",
                  "reported_window_earliest_min":earliest,
                  "reported_window_deadline_unwrapped_min":deadline,
                  "full_duration_presence_checked":"assigned_driver" if device=="home_ev" else "any_household_member",
                  "service_scope":"scheduled_energy_and_window_only_no_SOC_or_water_temperature"
                    if device in ("home_ev","electric_water_heater") else "task_start_duration_deadline"}
        return trial,action
    return None


def plan_role(profile: dict, building: dict, d_record: dict) -> tuple[str,dict]:
    role = profile["role_id"]
    baseline_path = Path(d_record["idf_path"])
    if sha(baseline_path) != d_record["idf_sha256"]:
        raise ValueError(f"D IDF hash changed: {role}")
    source_rows = parse_idf(baseline_path.read_text())
    rows = deepcopy(source_rows)
    schedules = {r[1]:r for r in source_rows if r[0].lower()=="schedule:compact"}
    selected_zones = set(d_record["ac_selected_zones"])
    selected_ac_names = {x["cooling_schedule"] for x in building["controls"]["zone_control_schedules"]
                         if x["zone"] in selected_zones}
    if len(selected_ac_names) != len(selected_zones):
        raise ValueError(f"AC source control mapping incomplete: {role}")
    baseline_week = {name:parse_week_schedule(schedules[name]) for name in selected_ac_names}
    base_ac = {name:[week[day%7].copy() for day in range(10)]
               for name,week in baseline_week.items()}
    candidate_ac = deepcopy(base_ac)
    owned = set(profile["device_ownership"])
    base_device = {}
    candidate_device = {}
    for device in DEVICE_ORDER:
        if device not in owned:
            continue
        week = parse_week_schedule(schedules[f"EB_Device_{device}"])
        days = [week[day%7].copy() for day in range(10)]
        base_device[device] = days
        candidate_device[device] = [slot for day in days for slot in day]
    ac_allowed = False
    if selected_ac_names:
        setpoint = float(answer(profile,"H_ac_temp"))
        change = float(answer(profile,"P_AC_CHANGE"))
        low,high = (float(x) for x in answer(profile,"P_AC_RANGE").split("_"))
        ac_allowed = change >= .5 and low <= setpoint+.5 <= high
    actions_by_day = [[] for _ in range(10)]
    legal_shift_devices_by_day = [[] for _ in range(10)]
    for day_zero in range(1,10):
        if ac_allowed:
            active = sum(value < 39.9 for name in selected_ac_names
                         for value in base_ac[name][day_zero])
            if active:
                for name in selected_ac_names:
                    candidate_ac[name][day_zero] = [round(v+.5,3) if v<39.9 else v
                                                    for v in base_ac[name][day_zero]]
                actions_by_day[day_zero].append({"kind":"ac_setpoint", "delta_c":.5,
                                                 "controlled_zone_count":len(selected_zones),
                                                 "active_zone_slots":active,
                                                 "within_B_change_and_temperature_range":True})
        legal = []
        for device in DEVICE_ORDER:
            if device not in candidate_device:
                continue
            moved = shift_one(profile,device,day_zero,candidate_device[device])
            if moved:
                rank = sha256(f"{POLICY_SEED}|choose|{role}|{day_zero+1}|{device}".encode()).hexdigest()
                legal.append((rank,device,moved))
        legal.sort(key=lambda item:item[0])
        legal_shift_devices_by_day[day_zero] = [device for _,device,_ in legal]
        if legal:
            rank,device,(candidate_device[device],action) = legal[0]
            action["eligible_shift_devices_today"] = legal_shift_devices_by_day[day_zero]
            action["selection_rank_sha256"] = rank
            action["selection_rule"] = "minimum_SHA256_of_seed_role_day_device_among_all_legal"
            actions_by_day[day_zero].append(action)
    changed_names = set()
    for row in rows:
        if row[0].lower() != "schedule:compact":
            continue
        name = row[1]
        if name in selected_ac_names and candidate_ac[name] != base_ac[name]:
            row[:] = calendar_schedule(name,row[2],candidate_ac[name])
            changed_names.add(name)
        elif name.startswith("EB_Device_"):
            device = name.removeprefix("EB_Device_")
            if device in candidate_device:
                before = [slot for day in base_device[device] for slot in day]
                after = candidate_device[device]
                if before != after:
                    row[:] = calendar_schedule(name,row[2],
                                              [after[i*SLOTS_PER_DAY:(i+1)*SLOTS_PER_DAY]
                                               for i in range(10)])
                    changed_names.add(name)
    for before,after in zip(source_rows,rows):
        if before != after and before[1] not in changed_names:
            raise ValueError(f"unrelated candidate IDF object changed: {role} {before[:2]}")
    if len(source_rows) != len(rows):
        raise ValueError(f"candidate IDF object count changed: {role}")
    if changed_names:
        header = (f"! G deterministic offline ten-day candidate for {role}.\n"
                  f"! Source D IDF SHA-256 {d_record['idf_sha256']}; policy {POLICY_VERSION}; seed {POLICY_SEED}.\n"
                  "! Only selected household AC setpoints or owned-device schedules differ; no model or human answer.")
        body = render(rows,header)
        path = OUT/f"{role}__G_candidate.idf"
        path.write_text(body)
        candidate_path = str(path)
        candidate_sha = sha(path)
    else:
        candidate_path = str(baseline_path)
        candidate_sha = d_record["idf_sha256"]
    if actions_by_day[0]:
        raise ValueError("candidate changed initial calendar day")
    plans = []
    for day_zero in range(10):
        ac_before = {name:base_ac[name][day_zero] for name in sorted(base_ac)}
        ac_after = {name:candidate_ac[name][day_zero] for name in sorted(candidate_ac)}
        device_before = {device:base_device[device][day_zero] for device in sorted(base_device)}
        device_after = {device:candidate_device[device][day_zero*SLOTS_PER_DAY:(day_zero+1)*SLOTS_PER_DAY]
                        for device in sorted(candidate_device)}
        ac_diff = ac_before != ac_after
        device_diff = device_before != device_after
        if day_zero == 0 and (ac_diff or device_diff):
            raise ValueError("candidate day1 plan differs despite equal-start contract")
        family = ("ac_plus_device_shift" if ac_diff and device_diff else
                  "ac_setpoint" if ac_diff else
                  "device_time_shift" if device_diff else "no_contrast")
        plans.append({"day_index":day_zero+1, "calendar_day":f"07-{14+day_zero:02d}",
                      "family_id":family, "ac_changed":ac_diff,
                      "device_changed":device_diff,
                      "eligible_shift_devices_today":legal_shift_devices_by_day[day_zero],
                      "no_contrast_reason": ("common_initialization_day" if day_zero==0 else
                          "no_legal_today_plan_change" if family=="no_contrast" else None),
                      "actions_initiated_today":actions_by_day[day_zero],
                      "A_plan": {"ac_setpoint_by_schedule_10min":ac_before,
                                 "device_on_by_name_10min":device_before},
                      "B_plan": {"ac_setpoint_by_schedule_10min":ac_after,
                                 "device_on_by_name_10min":device_after}})
    report = {"role_id":role, "policy_version":POLICY_VERSION,
              "policy_seed":POLICY_SEED,
              "A_baseline_idf_path":str(baseline_path),
              "A_baseline_idf_sha256":d_record["idf_sha256"],
              "B_candidate_idf_path":candidate_path,
              "B_candidate_idf_sha256":candidate_sha,
              "candidate_reuses_identical_baseline_IDF":not changed_names,
              "modified_IDF_schedules":sorted(changed_names),
              "weather_epw_path":d_record["weather_epw_path"],
              "weather_epw_sha256":d_record["weather_epw_sha256"],
              "ac_selected_zones":d_record["ac_selected_zones"],
              "devices":d_record["devices"],
              "candidate_day_action_counts":dict(Counter(action["kind"] for day in actions_by_day
                                                          for action in day)),
              "days_with_actual_plan_contrast":sum(day["family_id"]!="no_contrast" for day in plans),
              "daily_plans":plans,
              "trajectory_semantics":"two fixed policies from same Jul14 start; each carries own ten-day thermal history; no feedback conditioning"}
    return candidate_path,report


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--roles", nargs="*", help="sample roles; omit for 300")
    args = parser.parse_args()
    d_path = D_MANIFEST
    ddoc = json.loads(d_path.read_text())
    runtime = json.loads(D_RUNTIME.read_text())
    if (ddoc["n"] != 300 or runtime["n"] != 300 or not runtime["all_passed"] or
        runtime["input_manifest_sha256"] != sha(d_path) or
        ddoc["B_profile_sha256"] != sha(B_PATH) or
        ddoc["C_building_sha256"] != sha(C_PATH)):
        raise ValueError("G source must be current D accepted 300-home baseline")
    final = json.loads(D_FINAL.read_text())
    if (ddoc.get("ac_meter_contract_version") != METER_VERSION or
        final.get("ac_meter_contract_version") != METER_VERSION or
        final["baseline_10day_passed"] != 300 or
        final["sha256"]["D_manifest"] != sha(d_path) or
        final["sha256"]["D_runtime"] != sha(D_RUNTIME) or
        final["sha256"]["B_profile"] != sha(B_PATH)):
        raise ValueError("D final evidence chain incomplete")
    public_identity=public_role_identity()
    meter_identity={"meter_contract_version":METER_VERSION,
                    "D_manifest_sha256":sha(D_MANIFEST),
                    "D_runtime_sha256":sha(D_RUNTIME),
                    "D_final_evidence_sha256":sha(D_FINAL),
                    "B_profile_sha256":sha(B_PATH),
                    "public_role_manifest_sha256":public_identity["public_role_manifest_sha256"]}
    identity_sha=stable_hash(meter_identity)
    verify_policy_lock(identity_sha)
    b={r["role_id"]:r for r in json.loads(B_PATH.read_text())["profiles"]}
    c={r["role_id"]:r for r in json.loads(C_PATH.read_text())["records"]}
    d={r["role_id"]:r for r in ddoc["records"]}
    wanted=args.roles or sorted(b)
    if any(role not in b for role in wanted):
        raise ValueError("unknown requested role")
    OUT.mkdir(exist_ok=True)
    records=[]
    for role in wanted:
        _,record=plan_role(b[role],c[role],d[role])
        records.append(record)
    records.sort(key=lambda r:r["role_id"])
    report={"schema_version":"eb.G_candidate_input_manifest.v1",
            "status":"candidate_IDFs_materialized_not_runtime_validated",
            "policy_version":POLICY_VERSION,"policy_seed":POLICY_SEED,
            "ac_meter_contract_version":METER_VERSION,
            "meter_identity_sha256":identity_sha,
            "meter_identity":meter_identity,
            "preresult_policy_lock_sha256":sha(POLICY_LOCK),
            **public_identity,
            "n":len(records),"D_manifest_sha256":sha(D_MANIFEST),
            "D_runtime_sha256":sha(D_RUNTIME),"D_final_evidence_sha256":sha(D_FINAL),
            "B_profile_sha256":sha(B_PATH),"C_building_sha256":sha(C_PATH),
            "records":records}
    path = MANIFEST if len(records)==300 else HERE/"candidate_input_sample.json"
    path.write_text(json.dumps(report,ensure_ascii=False,indent=2)+"\n")
    print(json.dumps({"n":len(records),
                      "roles_with_changes":sum(not r["candidate_reuses_identical_baseline_IDF"] for r in records),
                      "contrast_days":sum(r["days_with_actual_plan_contrast"] for r in records),
                      "family_counts":dict(Counter(day["family_id"] for r in records
                                                   for day in r["daily_plans"])),
                      "report":str(path)},ensure_ascii=False))


if __name__=="__main__":
    main()
