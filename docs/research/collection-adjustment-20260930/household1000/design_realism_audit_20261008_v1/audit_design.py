"""Read-only diagnostics of frozen V18; run on the school server, no EP calls."""
import argparse
import collections
import hashlib
import json
import pathlib
import statistics


def read(path):
    return json.loads(path.read_text())


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def summary(xs):
    xs = sorted(xs)
    if not xs:
        return None
    return {"n": len(xs), "min": xs[0], "median": statistics.median(xs),
            "mean": statistics.mean(xs), "max": xs[-1]}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--dataset", type=pathlib.Path, required=True)
    parser.add_argument("--output", type=pathlib.Path, required=True)
    args = parser.parse_args()
    p = args.dataset
    worlds = [read(f) for f in sorted((p / "worlds").glob("*.json"))]
    ages = collections.Counter()
    roles = collections.Counter()
    free = collections.defaultdict(list)
    work = collections.defaultdict(list)
    ev_age = []
    ev_example = []
    child_examples = []
    child_by_age = collections.Counter()
    child_by_role = collections.Counter()
    infant_sleep = []
    infant_nap_members = 0
    under6_households = 0
    night_sleep_ac = 0
    ac_households = 0
    ev_households = 0
    external_driver = 0
    calendar_repeats = 0
    member_count = 0
    generic_kw_not_nameplate_bound = []
    for w in worlds:
        hid = w["household_id"]
        devices = w["parameter_pack"]["devices"]
        under6_households += any(m["age_years"] < 6 for m in w["members"])
        ops = {o["operator_id"]: o for o in w["operating_context"]["operators"]}
        has_ac = any("ac" in d["types"] for d in devices)
        ac_households += has_ac
        ev = next((d for d in devices if "ev" in d["types"]), None)
        if ev:
            ev_households += 1
            external_driver += w["given_transport_contract"]["driver_is_resident"] is False
            member = next((m for m in w["members"] if m["member_id"] == ev["operator_id"]), None)
            if member:
                ev_age.append(member["age_years"])
                if (member["age_years"] >= 85 or w["N"] == 1) and len(ev_example) < 12:
                    ev_example.append({"household_id": hid, "N": w["N"], "age": member["age_years"],
                        "source_work": member["current_work_source_proxy"],
                        "scenario": member["reference_activity_role"],
                        "weekday_spec": member["daily_reference_specs"][0],
                        "trip_kWh": w["routine"]["EV_daily_trip_kWh"],
                        "transport_contract": w["given_transport_contract"]})
        for m in w["members"]:
            member_count += 1
            age = m["age_years"]
            role = m["reference_activity_role"]
            roles[role] += 1
            ages[str(age)] += 1
            wd = m["weekly_calendar"][0]["intervals"]
            calendar_repeats += all(m["weekly_calendar"][d]["intervals"] == wd for d in range(1, 5))
            work[role].append(sum(i["end_min"] - i["start_min"] for i in wd if i["activity"] in ("work", "home_work", "given_short_work_activity")))
            if m["member_id"] in ops:
                free[role].append(sum(b - a for a, b in ops[m["member_id"]]["weekly_windows_min"]["0"]))
            if age < 6:
                child_by_age[str(age)] += 1
                child_by_role[role] += 1
                if age < 3 and len(child_examples) < 8:
                    child_examples.append({"household_id": hid, "member_id": m["member_id"], "age": age,
                        "source_care": m.get("preschool_care"), "spec": m["daily_reference_specs"][0],
                        "daycare_interval_minutes": sum(i["end_min"]-i["start_min"] for i in wd if i["activity"] == "school")})
            if age == 0:
                infant_sleep.append(sum(i["end_min"]-i["start_min"] for i in wd if i["activity"] == "sleep_rest"))
                infant_nap_members += any(i["activity"] == "sleep_rest" and 480 <= i["start_min"] < 1080 for i in wd)
            if has_ac and any(i["activity"] == "sleep_rest" for i in wd):
                # plans.py builds AC service from location=home AND activity != sleep_rest.
                night_sleep_ac += 1
        for d in devices:
            if "ac" in d["types"]:
                generic_kw_not_nameplate_bound.append(d["parameters"]["max_electric_W"] == d["parameters"]["rated_electric_W"])

    families = collections.Counter()
    mechanisms = collections.Counter()
    amounts = collections.defaultdict(collections.Counter)
    quantities = collections.defaultdict(collections.Counter)
    supplied_limits = collections.Counter()
    static_upper_overload = collections.Counter()
    guaranteed_program_overload = collections.Counter()
    overload_examples = []
    optional_examples = []
    pair_count = 0
    preschool_weekday_events = 0
    pediatric_by_date = collections.Counter()
    world_map = {w["household_id"]: w for w in worlds}
    for f in sorted((p / "pairs").glob("*/*.json")):
        q = read(f)
        pair_count += 1
        fam = q["proposal"]["family"]
        families[fam] += 1
        mechanisms[q["design_condition"]] += 1
        amounts[fam][json.dumps(q["proposal"]["amount"], sort_keys=True)] += 1
        for n in q["needs_A"]:
            quantities[n["kind"]][json.dumps(n["quantity"])] += 1
        w = world_map[q["household_id"]]
        import datetime
        weekday = datetime.date.fromisoformat(q["date"]).weekday()
        if weekday < 5 and any(m["age_years"] < 18 for m in w["members"]):
            pediatric_by_date[q["date"]] += 1
            preschool_weekday_events += any(m["age_years"] < 6 for m in w["members"])
        if fam.startswith("additional_") and len(optional_examples) < 6:
            optional_examples.append({"household_id": q["household_id"], "round": q["round_index"],
                "date": q["date"], "family": fam, "reason": q["proposal"]["reason"]})
        assets = {d["asset_id"]: d for d in q["world"]["devices"]}
        supplied_limits.update(q["world"]["circuit_limit_kw"].keys())
        for side in ("A", "B"):
            upper = collections.defaultdict(lambda: [0.0] * 432)
            known = collections.defaultdict(lambda: [0.0] * 432)
            for t in q[side]["tasks"]:
                d = assets[t["asset_id"]]
                cfg = d["parameters"].get(t["kind"], d["parameters"])
                kw = cfg["power_kw"]
                for s in range(max(0, t["start_min"]) // 10, min(4320, t["end_min"]) // 10):
                    upper[d["circuit"]][s] += kw
                    known[d["circuit"]][s] += kw
            for c in q[side]["controls"]:
                d = assets[c["asset_id"]]
                for s in range(max(0, c["start_min"]) // 10, min(4320, c["end_min"]) // 10):
                    upper[d["circuit"]][s] += d["max_electric_kw"]
            for circuit, limit in q["world"]["circuit_limit_kw"].items():
                peak = max(upper[circuit], default=0)
                guaranteed_peak = max(known[circuit], default=0)
                if peak > limit + 1e-8:
                    static_upper_overload[side + ":" + circuit] += 1
                if guaranteed_peak > limit + 1e-8:
                    guaranteed_program_overload[side + ":" + circuit] += 1
                    if len(overload_examples) < 8:
                        overload_examples.append({"household_id": q["household_id"], "round": q["round_index"],
                            "side": side, "circuit": circuit, "limit_kW": limit, "constant_program_peak_kW": guaranteed_peak})

    physical = []
    zero_event = []
    opposite_direction = []
    sensitivity = []
    goals_met = 0
    for f in sorted((p / "readback" / "base7").glob("*/*.json")):
        x = read(f)
        d = x["energy"]["event"]["A_minus_B_kWh"]
        physical.append(d)
        goals_met += d >= 0.5 - 1e-6
        if abs(d) < 1e-6:
            zero_event.append({"household_id": x["household_id"], "round": x["round_index"], "date": x["date"]})
        elif d < 0:
            opposite_direction.append({"household_id": x["household_id"], "round": x["round_index"], "date": x["date"], "A_minus_B_kWh": d})
        other = p / "readback" / "seasonal7" / f.parent.name / f.name
        if other.exists():
            y = read(other)
            sensitivity.append({"household_id": x["household_id"], "round": x["round_index"],
                "event_fixed15_delta": d, "event_seasonal_delta": y["energy"]["event"]["A_minus_B_kWh"],
                "24h_fixed15_delta": x["energy"]["living_day"]["A_minus_B_kWh"],
                "24h_seasonal_delta": y["energy"]["living_day"]["A_minus_B_kWh"]})
    out = {"schema": "eb.readonly_design_realism_audit.v1", "date": "2026-10-08",
        "dataset": str(p), "delivery_sha256": sha(p / "DELIVERY.json"),
        "scope": "all1000 frozen worlds and10000 input pairs; original50 existing readbacks only; no EP, no changes to V18, no human answers",
        "households": len(worlds), "members": member_count, "pairs": pair_count,
        "roles": dict(roles), "weekday_operator_free_minutes": {k: summary(v) for k, v in free.items()},
        "weekday_work_minutes": {k: summary(v) for k, v in work.items()},
        "all_mon_fri_member_calendars_identical_count": calendar_repeats,
        "under6_ages": dict(child_by_age), "under6_scenarios": dict(child_by_role), "under3_examples": child_examples,
        "under6_households": under6_households,
        "age0_weekday_sleep_minutes": summary(infant_sleep), "age0_members_with_explicit_daytime_nap": infant_nap_members,
        "EV": {"households": ev_households, "given_nonresident_driver": external_driver,
            "resident_passenger_or_handler_age": summary(ev_age), "age75plus": sum(a >= 75 for a in ev_age),
            "examples": ev_example},
        "AC": {"households": ac_households, "members_with_sleep_but_no_sleep_AC_service_by_rule": night_sleep_ac,
            "generic_rated_equals_declared_max_power_units": sum(generic_kw_not_nameplate_bound),
            "generic_AC_units": len(generic_kw_not_nameplate_bound)},
        "proposal_families": dict(families), "proposal_mechanisms": dict(mechanisms),
        "proposal_amounts": {k: dict(v) for k, v in amounts.items()},
        "service_quantities": {k: dict(v) for k, v in quantities.items()},
        "given_circuit_limits_present_in_pairs": dict(supplied_limits),
        "static_max_power_upper_bounds_exceeding_given_circuit": dict(static_upper_overload),
        "constant_program_power_exceeding_given_circuit": dict(guaranteed_program_overload),
        "upper_bounds_are_not_measured_AC_or_EV_power": True,
        "upper_bound_interpretation": "concurrent declared metadata max-power proxy; generic AC rated=max is not a certified offdesign bound",
        "overload_examples": overload_examples,
        "optional_service_proposal_examples": optional_examples,
        "weekday_dates_with_under18_members": dict(pediatric_by_date),
        "preschool_weekday_cases": preschool_weekday_events,
        "existing50_event_reduction_kWh": summary(physical),
        "existing50_pairs_meeting_given_0_5kW_mean_reduction_in_one_hour": goals_met,
        "existing50_zero_event_delta_count": len(zero_event), "existing50_zero_event_examples": zero_event[:8],
        "existing50_event_increase_count": len(opposite_direction), "existing50_event_increase_examples": opposite_direction[:8],
        "inlet_sensitivity_pairs": len(sensitivity),
        "inlet_event_sign_flip_count": sum(x["event_fixed15_delta"] * x["event_seasonal_delta"] < 0 for x in sensitivity),
        "inlet_24h_sign_flip_count": sum(x["24h_fixed15_delta"] * x["24h_seasonal_delta"] < 0 for x in sensitivity),
        "inlet_max_abs_24h_delta_change_kWh": max((abs(x["24h_fixed15_delta"] - x["24h_seasonal_delta"]) for x in sensitivity), default=0),
        "inlet_sensitivity": sensitivity,
        "source_code_sha256": {f.name: sha(f) for f in sorted((p / "code").glob("*.py"))}}
    ranges = [("2025-01-01", "2025-01-01"), ("2025-01-28", "2025-02-04"),
        ("2025-04-04", "2025-04-06"), ("2025-05-01", "2025-05-05"),
        ("2025-05-31", "2025-06-02"), ("2025-10-01", "2025-10-08")]
    out["national_holiday_weekday_under18_household_cases"] = {
        day: count for day, count in pediatric_by_date.items()
        if any(lo <= day <= hi for lo, hi in ranges)}
    out["national_holiday_weekday_under18_case_count"] = sum(out["national_holiday_weekday_under18_household_cases"].values())
    oldest = []
    for w in worlds:
        ev = next((d for d in w["parameter_pack"]["devices"] if "ev" in d["types"]), None)
        m = next((m for m in w["members"] if ev and m["member_id"] == ev["operator_id"]), None)
        if m and m["age_years"] >= 85:
            oldest.append({"household_id": w["household_id"], "N": w["N"], "age": m["age_years"],
                "source_work": m["current_work_source_proxy"], "scenario": m["reference_activity_role"]})
    out["EV"]["oldest_resident_handlers"] = sorted(oldest, key=lambda m: -m["age"])[:8]
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(out, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps({k: v for k, v in out.items() if k not in ("weekday_dates_with_under18_members", "inlet_sensitivity", "source_code_sha256", "EV", "service_quantities", "proposal_amounts")}, ensure_ascii=False))
    print(json.dumps({"EV_households": ev_households, "external_drivers": external_driver, "EV_age75plus": sum(a >= 75 for a in ev_age)}, ensure_ascii=False))


if __name__ == "__main__":
    main()
