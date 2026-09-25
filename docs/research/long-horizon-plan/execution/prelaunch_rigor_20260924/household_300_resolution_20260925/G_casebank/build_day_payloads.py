#!/usr/bin/env python3
"""Materialize pending G day evidence from the two real ten-day EnergyPlus SQL runs.

No participant response, consent, or independent acceptance is inferred here.
"""
from __future__ import annotations

from collections import Counter
import csv
from hashlib import sha256
import json
from pathlib import Path
import sqlite3

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
D = ROOT / "D_integration"
E = ROOT / "E_collection_release"
J_PER_KWH = 3_600_000


def file_sha(path: Path) -> str:
    return sha256(path.read_bytes()).hexdigest()


def stable_hash(value: object) -> str:
    return sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
                             separators=(",", ":"), allow_nan=False).encode()).hexdigest()


def load(path: Path) -> dict:
    return json.loads(path.read_text())


def rows(path: Path) -> list[dict]:
    with path.open(encoding="utf-8-sig", newline="") as stream:
        return list(csv.DictReader(stream))


def hourly_sql(path: Path, controlled: list[str], devices: list[dict]) -> dict:
    db = sqlite3.connect(path)
    try:
        query = """SELECT t.Day,t.Hour,d.Name,d.KeyValue,r.Value
          FROM ReportData r JOIN ReportDataDictionary d USING(ReportDataDictionaryIndex)
          JOIN Time t USING(TimeIndex) JOIN EnvironmentPeriods e USING(EnvironmentPeriodIndex)
          WHERE e.EnvironmentType=3 AND COALESCE(t.WarmupFlag,0)=0
            AND t.Month=7 AND t.Day BETWEEN 14 AND 23 AND d.ReportingFrequency='Hourly'
          ORDER BY t.Day,t.Hour"""
        data = {}
        for day, hour, name, key, value in db.execute(query):
            item = data.setdefault(day, {}).setdefault(hour, {})
            ident = (name, (key or "").upper())
            if ident in item:
                raise ValueError(f"duplicate SQL hourly output {path.name}: {day}, {hour}, {ident}")
            item[ident] = float(value)
        if sorted(data) != list(range(14, 24)) or any(sorted(data[d]) != list(range(1, 25)) for d in data):
            raise ValueError("SQL does not contain exactly ten complete 24-hour days")
        expected = [("Zone Mean Air Temperature", z.upper()) for z in controlled]
        expected += [("Electric Equipment Electricity Energy", d["idf_equipment_name"].upper())
                     for d in devices]
        for day in data:
            for hour in data[day]:
                if any(key not in data[day][hour] for key in expected):
                    raise ValueError(f"controlled output missing: day {day} hour {hour}")
        return data
    finally:
        db.close()


def day_one_sql_equal(left: Path, right: Path) -> dict:
    q = """SELECT d.Name,d.KeyValue,d.ReportingFrequency,t.Hour,t.Minute,t.Interval,
          t.IntervalType,r.Value FROM ReportData r
          JOIN ReportDataDictionary d USING(ReportDataDictionaryIndex)
          JOIN Time t USING(TimeIndex) JOIN EnvironmentPeriods e USING(EnvironmentPeriodIndex)
          WHERE e.EnvironmentType=3 AND COALESCE(t.WarmupFlag,0)=0
          AND t.Month=7 AND t.Day=14
          ORDER BY d.Name,d.KeyValue,d.ReportingFrequency,t.Hour,t.Minute,t.Interval,t.IntervalType"""
    a, b = sqlite3.connect(left), sqlite3.connect(right)
    try:
        ar, br = a.execute(q).fetchall(), b.execute(q).fetchall()
    finally:
        a.close(); b.close()
    unequal = sum(x != y for x, y in zip(ar, br)) + abs(len(ar)-len(br))
    return {"A_rows": len(ar), "B_rows": len(br), "unequal_rows": unequal,
            "exact_equal": len(ar) == len(br) and unequal == 0}


def weather(path: Path) -> dict[int, list[float]]:
    out = {day: [None] * 24 for day in range(14, 24)}
    with path.open(encoding="utf-8", errors="replace", newline="") as stream:
        for row in csv.reader(stream):
            if len(row) < 7 or row[1:2] != ["7"]:
                continue
            day = int(row[2]); hour = int(row[3])
            if day in out and 1 <= hour <= 24:
                out[day][hour-1] = round(float(row[6]), 3)
    if any(None in hours for hours in out.values()):
        raise ValueError(f"weather missing July 14-23 hourly drybulb: {path}")
    return out


def segments(values: list[float], *, active_only: bool) -> list[dict]:
    result = []
    start = 0
    for i in range(1, len(values)+1):
        if i == len(values) or values[i] != values[start]:
            if not active_only or values[start] > 0:
                result.append({"start_min": start*10, "end_min": i*10,
                               "value": values[start]})
            start = i
    return result


def plan_view(plan: dict) -> tuple[list[dict], list[dict]]:
    # 40 C is the D contract's inactive cooling sentinel, not a proposed
    # household temperature. Internal schedule names never enter display.
    ac = [{"room": f"受控空调 {number}", "unit": "degree_C", **slice_}
          for number, (_, values) in enumerate(sorted(plan["ac_setpoint_by_schedule_10min"].items()), 1)
          for slice_ in segments([v if v < 40 else 0 for v in values], active_only=True)]
    devices = [{"device": name, "unit": "on_fraction", **slice_}
               for name, values in sorted(plan["device_on_by_name_10min"].items())
               for slice_ in segments(values, active_only=True)]
    return ac, devices


def clock(minute: int) -> str:
    hour, minute = divmod(minute, 60)
    return f"{hour:02d}:{minute:02d}"


def display_projection(raw: dict) -> dict:
    """Pending E-shaped display object; its hashes bind exactly these bytes."""
    day = raw["day_index"]
    w = raw["weather"]
    result = {"context": f"{raw['province']}{raw['city']}的固定合成家庭；模拟夏季日程。",
              "weather": {"summary": f"CSWD典型年模拟夏季第{day}日（{raw['calendar_day']}），室外{w['min_c']:g}–{w['max_c']:g}℃；非实时预报。",
                          "station_key": raw["source_context"]["weather_station_key"],
                          "simulated_day_index": day},
              "plans": {}}
    names = {"washer": "洗衣机", "dryer": "烘干机", "dishwasher": "洗碗机",
             "electric_water_heater": "电热水器", "home_ev": "家用电动汽车充电"}
    for slot in ("A", "B"):
        plan = raw["plans"][slot]
        hist = raw["history_by_branch"][slot]
        if hist["prior_days"]:
            prior = f"此前{hist['prior_days']}日累计本户受控设备代理电量{hist['cumulative_attributable_kwh']:g} kWh。"
            last_temp = list(hist["previous_day_end_room_temp_c"].values())
            if last_temp:
                prior += f"上一日末本户纳入房间平均仿真温度{sum(last_temp)/len(last_temp):.1f}℃。"
        else:
            prior = "共同初始日，尚无此前轨迹。"
        lines = [f"{row['room']} {clock(row['start_min'])}–{clock(row['end_min'])}，制冷设定{row['value']:g}℃"
                 for row in plan["ac_timeline"]]
        lines += [f"{names.get(row['device'], row['device'])} {clock(row['start_min'])}–{clock(row['end_min'])}运行"
                  for row in plan["device_timeline"]]
        if not lines:
            lines = ["当日无本户受控设备运行时段。"]
        metrics = plan["metrics"]
        all_temp = [value for series in metrics["controlled_room_temp_c_hourly"].values()
                    for value in series]
        indoor = round(sum(all_temp)/len(all_temp), 2) if all_temp else None
        visible_metrics = {**metrics,
                           "temperature_aggregation": "unweighted_owned_zone_and_hour_mean_not_measured"}
        result["plans"][slot] = {"branch_history_summary": prior,
                                  "device_schedule": lines,
                                  "indoor_temperature_c": indoor,
                                  "controlled_device_kwh": metrics["attributable_kwh"],
                                  "task_completion": "未建模任务完成；仅模拟设备日程和代理电量",
                                  "metrics": visible_metrics}
    return result


def branch_metrics(data: dict, day: int, record: dict, daily: dict, room_labels: dict) -> dict:
    ac = [data[day][h].get(("EB Selected Household AC Proxy Electricity Energy", "EMS"), 0.0)/J_PER_KWH
          for h in range(1, 25)]
    device_hour = {d["device"]: [data[day][h][("Electric Equipment Electricity Energy",
                                              d["idf_equipment_name"].upper())]/J_PER_KWH
                                 for h in range(1, 25)] for d in record["devices"]}
    total_hour = [ac[i]+sum(series[i] for series in device_hour.values()) for i in range(24)]
    # Hourly weights are fixed before candidate results and are an index, not a tariff.
    weighted = round(sum(total_hour), 6)
    result = {"device_kwh": daily["device_kwh"], "ac_proxy_kwh": daily["ac_proxy_kwh"],
              "attributable_kwh": daily["household_attributable_kwh"],
              "weighted_energy_index": weighted,
              "temperature_scope": "household_owned_zone_observation_not_all_AC_controlled",
              "attributable_kwh_hourly": [round(v, 9) for v in total_hour],
              "controlled_room_temp_c_hourly": {
                  label: [round(data[day][h][("Zone Mean Air Temperature", zone.upper())], 4)
                          for h in range(1, 25)]
                  for zone, label in room_labels.items()}}
    if abs(sum(total_hour)-daily["household_attributable_kwh"]) > 1e-5:
        raise ValueError(f"hourly/day controlled kWh mismatch day {day}")
    if any(len(x) != 24 for x in result["controlled_room_temp_c_hourly"].values()):
        raise ValueError("room series not 24 hours")
    return result


def main() -> None:
    gm = load(HERE/"candidate_input_manifest_300.json")
    cm = load(HERE/"candidate_runtime_300.json")
    dm = load(D/"behavior_input_manifest.json")
    dr = load(D/"runtime_300.json")
    if not (gm["n"] == cm["n"] == dm["n"] == dr["n"] == 300 and cm["all_passed"]
            and cm["candidate_manifest_sha256"] == file_sha(HERE/"candidate_input_manifest_300.json")
            and cm["D_runtime_sha256"] == file_sha(D/"runtime_300.json")
            and cm["F_offline_production_gate_sha256"] == file_sha(ROOT/"F_independent_review/G_OFFLINE_PRODUCTION_GATE.json")):
        raise ValueError("G candidate runtime and frozen source hashes do not match")
    public = E/"public_role_package"
    if file_sha(public/"PUBLIC_MANIFEST.json") != gm["public_role_manifest_sha256"]:
        raise ValueError("public role manifest differs from frozen G identity")
    for filename, expected in gm["public_role_table_sha256"].items():
        if file_sha(public/filename) != expected:
            raise ValueError(f"public role CSV changed: {filename}")
    profiles = {r["role_id"]: r for r in rows(public/"households_300.csv")}
    gen = {r["role_id"]: r for r in gm["records"]}
    cand = {r["role_id"]: r for r in cm["records"]}
    drec = {r["role_id"]: r for r in dm["records"]}
    base = {r["role_id"]: r for r in dr["records"]}
    if any(set(x) != set(gen) for x in (profiles, cand, drec, base)):
        raise ValueError("role set mismatch")
    weather_cache = {}
    weather_hash_cache = {}
    casebank_records, decisions, trajectory, day_payloads, display_payloads = [], {}, [], [], []
    projected_payloads = {}
    family_counts, status_counts = Counter(), Counter()
    for role in sorted(gen):
        g, c, d, a, profile = gen[role], cand[role], drec[role], base[role], profiles[role]
        a_sql = D/"runtime"/role/"eplusout.sql"
        b_sql = Path(c["sql_path"])
        a_sql_sha = file_sha(a_sql)
        if (load(D/"runtime"/role/"cache_signature.json") != a["cache_signature"] or
            file_sha(b_sql) != c["sql_sha256"]):
            raise ValueError(f"SQL hash mismatch {role}")
        controlled = list(dict.fromkeys(d["ac_selected_zones"]+d["ac_unselected_owned_zones_off"]))
        labels = {zone: f"房间 {i}" for i, zone in enumerate(controlled, 1)}
        ah = hourly_sql(a_sql, controlled, d["devices"])
        bh = hourly_sql(b_sql, controlled, d["devices"])
        first = day_one_sql_equal(a_sql, b_sql)
        if not first["exact_equal"]:
            raise ValueError(f"first-day A/B SQL diverges: {role}: {first}")
        wp = Path(g["weather_epw_path"])
        if str(wp) not in weather_hash_cache:
            weather_hash_cache[str(wp)] = file_sha(wp)
        if weather_hash_cache[str(wp)] != g["weather_epw_sha256"]:
            raise ValueError(f"weather changed: {role}")
        if str(wp) not in weather_cache:
            weather_cache[str(wp)] = weather(wp)
        wh = weather_cache[str(wp)]
        histories = {"A": [], "B": []}
        days = []
        for plan_day in g["daily_plans"]:
            idx = plan_day["day_index"]; day = 13+idx; key = f"07-{day:02d}"
            cid = f"{role}/day-{idx:02d}"
            branch = {}
            states = {}
            for slot, run, data in (("A", a, ah), ("B", c, bh)):
                prev = histories[slot]
                prior_state = {"role_id": role, "day_index": idx,
                               "prior_days": prev, "start_condition": "same_D_v3_baseline_IDF_weather"
                               if idx == 1 else "continuous_branch_trajectory"}
                states[slot] = stable_hash(prior_state)
                plan = plan_day[f"{slot}_plan"]
                plan_hash = stable_hash({"day_index": idx, "day_plan": plan})
                action_hash = stable_hash({"day_index": idx, "ac": plan["ac_setpoint_by_schedule_10min"],
                                           "devices": plan["device_on_by_name_10min"]})
                ac_timeline, device_timeline = plan_view(plan)
                metrics = branch_metrics(data, day, d, run["daily"][key], labels)
                branch[slot] = {"plan_hash": plan_hash, "day_action_hash": action_hash,
                                "ac_timeline": ac_timeline, "device_timeline": device_timeline,
                                "metrics": metrics, "metrics_hash": stable_hash(metrics),
                                "history": {"prior_days": len(prev),
                                            "prior_plan_hashes": [x["plan_hash"] for x in prev],
                                            "cumulative_attributable_kwh": round(sum(x["attributable_kwh"] for x in prev), 6),
                                            "previous_day_end_room_temp_c": prev[-1]["end_room_temp_c"] if prev else {}}}
            changed = branch["A"]["day_action_hash"] != branch["B"]["day_action_hash"]
            if changed != (plan_day["ac_changed"] or plan_day["device_changed"]):
                raise ValueError(f"G action manifest/day slice disagrees: {cid}")
            status = "meaningful" if changed else "equivalent"
            basis = "temperature_setpoint" if plan_day["ac_changed"] else "device_schedule" if changed else None
            reason = None if changed else plan_day["no_contrast_reason"] or "identical same-day actions"
            evidence = {"case_id": cid, "A_action_hash": branch["A"]["day_action_hash"],
                        "B_action_hash": branch["B"]["day_action_hash"],
                        "A_pre_event_state_hash": states["A"], "B_pre_event_state_hash": states["B"],
                        "action_initiated_today": plan_day["actions_initiated_today"],
                        "source": "actual_frozen_G_day_plan_pre_feedback"}
            semantic = {"status": status, "basis": basis, "reason": reason,
                        "same_day_action_change": changed, "evidence_hash": stable_hash(evidence),
                        "source": "pending_independent_day_evidence"}
            w = wh[day]
            display = {"schema_version": "eb.G_display_payload.v1", "case_id": cid,
                       "role_id": role, "day_index": idx, "calendar_day": key,
                       "city": profile["city"], "province": profile["province"],
                       "source_context": {"source_catalog_key": profile["source_catalog_key"],
                                          "weather_station_key": profile["weather_station_key"],
                                          "weather_kind": "CSWD typical-year simulated scenario",
                                          "home_city_to_station_km": float(profile["weather_station_distance_km"])},
                       "weather": {"outdoor_drybulb_c_hourly": w, "min_c": min(w), "max_c": max(w)},
                       "cost_weight": {"kind": "uniform_experimental_time_weight_not_local_tariff",
                                       "unit": "weighted_kwh_index_not_RMB", "hourly_weights": [1.0]*24},
                       "metrics_scope": "owned_device_electricity_plus_selected_AC_COP3_proxy_only_not_whole_home_bill",
                       "history_by_branch": {slot: branch[slot]["history"] for slot in ("A", "B")},
                       "plans": {slot: {"plan_hash": branch[slot]["plan_hash"],
                                        "ac_timeline": branch[slot]["ac_timeline"],
                                        "device_timeline": branch[slot]["device_timeline"],
                                        "metrics": branch[slot]["metrics"],
                                        "task_completion": "not_modeled_device_schedule_only"}
                                 for slot in ("A", "B")},
                       "semantic_contrast": {"status": status, "basis": basis, "reason": reason},
                       "collectable_after_independent_acceptance": changed and idx > 1,
                       "participant_feedback": None}
            display_payloads.append(display)
            projected = display_projection(display)
            projected_payloads[cid] = projected
            full = {**display, "schema_version": "eb.G_day_payload.v1",
                    "physical_evidence": {"D_baseline_sql_sha256": a_sql_sha,
                                          "G_candidate_sql_sha256": c["sql_sha256"],
                                          "G_candidate_idf_sha256": g["B_candidate_idf_sha256"],
                                          "pre_event_state_hash_A": states["A"],
                                          "pre_event_state_hash_B": states["B"],
                                          "semantic_evidence_hash": semantic["evidence_hash"]}}
            day_payloads.append(full)
            template_hash = stable_hash({"family": plan_day["family_id"],
                                         "action_kinds": [x["kind"] for x in plan_day["actions_initiated_today"]],
                                         "ac_changed": plan_day["ac_changed"],
                                         "device_changed": plan_day["device_changed"]})
            plan_refs = {}
            for slot in ("A", "B"):
                plan_refs[slot] = {"plan_version_id": f"eb.G.{slot}.fixed_policy.v1",
                                   "plan_hash_scope": "day_slice", "day_index": idx,
                                   "plan_hash": branch[slot]["plan_hash"],
                                   "day_action_hash": branch[slot]["day_action_hash"],
                                   "display_payload_hash": stable_hash(projected["plans"][slot]),
                                   "metrics_hash": stable_hash(projected["plans"][slot]["metrics"])}
            item = {"case_id": cid, "day_index": idx,
                    "case_status": "simulated_pending_independent_review",
                    "plan_family_id": plan_day["family_id"],
                    "plan_template_fingerprint": template_hash,
                    "history_group_id": role, "history_max_day_index": idx-1,
                    "pre_event_state_hash_A": states["A"],
                    "pre_event_state_hash_B": states["B"],
                    "plans": plan_refs, "semantic_contrast": semantic,
                    "pair_status": "pending_review", "collectable": False,
                    "participant_feedback": None}
            days.append(item)
            decisions[cid] = {"pre_event_state_hash_A": states["A"],
                              "pre_event_state_hash_B": states["B"],
                              "plan_family_id": plan_day["family_id"],
                              "plan_template_fingerprint": template_hash,
                              "plan_hash_A": plan_refs["A"]["plan_hash"],
                              "plan_hash_B": plan_refs["B"]["plan_hash"],
                              "day_action_hash_A": plan_refs["A"]["day_action_hash"],
                              "day_action_hash_B": plan_refs["B"]["day_action_hash"],
                              "semantic_contrast": semantic}
            for slot in ("A", "B"):
                metrics = branch[slot]["metrics"]
                histories[slot].append({"day_index": idx, "plan_hash": branch[slot]["plan_hash"],
                                        "attributable_kwh": metrics["attributable_kwh"],
                                        "end_room_temp_c": {label: values[-1] for label, values in
                                                            metrics["controlled_room_temp_c_hourly"].items()}})
            family_counts[plan_day["family_id"]] += 1
            status_counts[status] += 1
        casebank_records.append({"role_id": role, "profile_sha256": gm["B_profile_sha256"],
                                 "days": days})
        trajectory.append({"role_id": role, "first_day_sql": first,
                           "A_baseline_sql_sha256": a_sql_sha,
                           "B_candidate_sql_sha256": c["sql_sha256"],
                           "B_execution_provenance": c["execution_provenance"],
                           "D_baseline_idf_sha256": d["idf_sha256"],
                           "G_candidate_idf_sha256": g["B_candidate_idf_sha256"],
                           "ten_day_cumulative_A_kwh": round(sum(x["attributable_kwh"] for x in histories["A"]), 6),
                           "ten_day_cumulative_B_kwh": round(sum(x["attributable_kwh"] for x in histories["B"]), 6),
                           "actual_plan_contrast_days": g["days_with_actual_plan_contrast"]})
        if len(trajectory) % 50 == 0:
            print(f"day payloads {len(trajectory)}/300 roles", flush=True)
    contrast = {"schema_version": "eb.pending_day_contrast.v1",
                "status": "pending_independent_review",
                "final_evidence_sha256": gm["D_final_evidence_sha256"],
                "policy_lock_sha256": gm["preresult_policy_lock_sha256"],
                "candidate_runtime_sha256": file_sha(HERE/"candidate_runtime_300.json"),
                "decisions": decisions}
    bank = {"schema_version": "eb.offline_casebank.v1",
            "status": "pending_independent_review",
            "study_batch_id": None, "consent_version": None, "consent_text": None,
            "profile_sha256": gm["B_profile_sha256"],
            "behavior_sha256": dm["B_behavior_sha256"],
            "questionnaire_sha256": dm["questionnaire_codebook_sha256"],
            "public_role_manifest_sha256": gm["public_role_manifest_sha256"],
            "meter_version_sha256": gm["meter_identity_sha256"],
            "final_evidence_sha256": gm["D_final_evidence_sha256"],
            "semantic_contrast_evidence_sha256": stable_hash(contrast),
            "candidate_runtime_sha256": file_sha(HERE/"candidate_runtime_300.json"),
            "day_payload_builder_source_sha256": file_sha(Path(__file__)),
            "participant_feedback": None, "records": casebank_records}
    evidence = {"schema_version": "eb.G_trajectory_evidence.v1",
                "status": "300_real_candidate_or_identical_reuse_trajectories_pending_independent_review",
                "n_roles": len(trajectory), "n_days": len(day_payloads),
                "first_day_exact_equal_roles": sum(x["first_day_sql"]["exact_equal"] for x in trajectory),
                "execution_provenance_counts": dict(Counter(x["B_execution_provenance"] for x in trajectory)),
                "day_family_counts": dict(family_counts),
                "day_semantic_status_counts": dict(status_counts),
                "candidate_manifest_sha256": file_sha(HERE/"candidate_input_manifest_300.json"),
                "candidate_runtime_sha256": file_sha(HERE/"candidate_runtime_300.json"),
                "day_payload_builder_source_sha256": file_sha(Path(__file__)),
                "F_offline_production_gate_sha256": file_sha(ROOT/"F_independent_review/G_OFFLINE_PRODUCTION_GATE.json"),
                "records": trajectory}
    for name, value in (("casebank_pending.json", bank),
                        ("contrast_index_pending.json", contrast),
                        ("trajectory_evidence_300.json", evidence),
                        ("display_payloads_pending.json", projected_payloads)):
        (HERE/name).write_text(json.dumps(value, ensure_ascii=False, indent=2)+"\n")
    for name, values in (("day_payload_3000.jsonl", day_payloads),
                         ("display_payload_3000.jsonl", display_payloads)):
        with (HERE/name).open("w") as stream:
            for value in values:
                stream.write(json.dumps(value, ensure_ascii=False, separators=(",", ":"), allow_nan=False)+"\n")
    print(json.dumps({"n_roles": len(trajectory), "n_days": len(day_payloads),
                      "day_family_counts": dict(family_counts),
                      "day_semantic_status_counts": dict(status_counts),
                      "first_day_exact_equal_roles": evidence["first_day_exact_equal_roles"]},
                     ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()
