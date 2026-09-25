#!/usr/bin/env python3
"""Run behavior-injected IDFs and account only household-owned electricity.

This checks EnergyPlus execution and an experimental meter interface. It does
not validate household behavior, actual device power, or a human response.
"""
from __future__ import annotations

import argparse
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
from functools import lru_cache
from hashlib import sha256
import json
from pathlib import Path
import re
import sqlite3
import subprocess

HERE = Path(__file__).resolve().parent
MANIFEST = HERE / "behavior_input_manifest.json"
EP = Path("/Applications/EnergyPlus-24-1-0/energyplus")
RUNS = HERE / "runtime"
J_PER_KWH = 3_600_000
OUTPUT_CONTRACT_VERSION = "eb.D_runtime_10day_hourly_plus_device_and_AC_checks.v2"


def sha(path: Path) -> str:
    return sha256(path.read_bytes()).hexdigest()


@lru_cache(maxsize=1)
def engine_sha256() -> str:
    return sha(EP)


def cache_signature(record: dict) -> dict:
    return {"idf_sha256": record["idf_sha256"],
            "weather_epw_sha256": record["weather_epw_sha256"],
            "energyplus_executable_sha256": engine_sha256(),
            "output_contract_version": OUTPUT_CONTRACT_VERSION,
            "runtime_reader_source_sha256": sha(Path(__file__))}


def cache_matches(marker: Path, signature: dict) -> bool:
    try:
        return json.loads(marker.read_text()) == signature
    except (OSError, ValueError):
        return False


def energy(db: sqlite3.Connection, name: str, key: str | None = None) -> tuple[int, float]:
    sql = """SELECT count(*), COALESCE(sum(r.Value), 0)
      FROM ReportData r JOIN ReportDataDictionary d USING(ReportDataDictionaryIndex)
      JOIN Time t USING(TimeIndex) JOIN EnvironmentPeriods e USING(EnvironmentPeriodIndex)
      WHERE e.EnvironmentType=3 AND COALESCE(t.WarmupFlag,0)=0
        AND d.ReportingFrequency='Hourly' AND d.Name=?"""
    params = [name]
    if key is not None:
        sql += " AND lower(d.KeyValue)=lower(?)"
        params.append(key)
    count, joules = db.execute(sql, params).fetchone()
    return int(count), float(joules)


def day_energy(db: sqlite3.Connection, name: str, key: str | None = None) -> dict[str, float]:
    sql = """SELECT printf('%02d-%02d', t.Month, t.Day), COALESCE(sum(r.Value),0)
      FROM ReportData r JOIN ReportDataDictionary d USING(ReportDataDictionaryIndex)
      JOIN Time t USING(TimeIndex) JOIN EnvironmentPeriods e USING(EnvironmentPeriodIndex)
      WHERE e.EnvironmentType=3 AND COALESCE(t.WarmupFlag,0)=0
        AND d.ReportingFrequency='Hourly' AND d.Name=?"""
    params = [name]
    if key is not None:
        sql += " AND lower(d.KeyValue)=lower(?)"
        params.append(key)
    sql += " GROUP BY t.Month,t.Day ORDER BY t.Month,t.Day"
    return {day: round(joules/J_PER_KWH, 6) for day, joules in db.execute(sql, params)}


def zone_series(db: sqlite3.Connection, name: str, key: str) -> list[tuple[int, int, float]]:
    return db.execute("""SELECT t.Day,t.Hour,r.Value
      FROM ReportData r JOIN ReportDataDictionary d USING(ReportDataDictionaryIndex)
      JOIN Time t USING(TimeIndex) JOIN EnvironmentPeriods e USING(EnvironmentPeriodIndex)
      WHERE e.EnvironmentType=3 AND COALESCE(t.WarmupFlag,0)=0
        AND d.ReportingFrequency='Hourly' AND d.Name=? AND lower(d.KeyValue)=lower(?)
      ORDER BY t.Month,t.Day,t.Hour""", (name,key)).fetchall()


def run_one(record: dict, *, reuse: bool) -> dict:
    role = record["role_id"]
    idf = Path(record["idf_path"])
    weather = Path(record["weather_epw_path"])
    if sha(idf) != record["idf_sha256"] or sha(weather) != record["weather_epw_sha256"]:
        return {"role_id": role, "status": "input_hash_mismatch"}
    folder = RUNS / role
    folder.mkdir(parents=True, exist_ok=True)
    marker = folder / "cache_signature.json"
    signature = cache_signature(record)
    if not (reuse and cache_matches(marker, signature)
            and (folder/"eplusout.end").is_file() and (folder/"eplusout.sql").is_file()):
        for old in folder.glob("eplusout.*"):
            old.unlink()
        proc = subprocess.run([str(EP), "-w", str(weather), "-d", str(folder), str(idf)],
                              stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                              text=True, timeout=240)
        (folder/"process.log").write_text(proc.stdout)
        if proc.returncode:
            return {"role_id": role, "status": "energyplus_process_failed",
                    "returncode": proc.returncode, "last_output": proc.stdout[-1000:]}
        marker.write_text(json.dumps(signature, sort_keys=True)+"\n")
    end = (folder/"eplusout.end").read_text(errors="replace") if (folder/"eplusout.end").is_file() else ""
    err = (folder/"eplusout.err").read_text(errors="replace") if (folder/"eplusout.err").is_file() else ""
    severe = len(re.findall(r"\*\*\s*Severe\s*\*", err, re.I))
    fatal = len(re.findall(r"\*\s*Fatal\s*\*", err, re.I))
    warnings = len(re.findall(r"\*\*\s*Warning\s*\*", err, re.I))
    if 'Invalid "until" field value is not a multiple of the minutes for each timestep' in err:
        return {"role_id": role, "status": "invalid_schedule_timestep_warning",
                "idf_sha256": record["idf_sha256"], "error_excerpt": "\n".join(
                    line for line in err.splitlines() if 'Invalid "until"' in line)[:1200]}
    if any('missing day types' in line and 'Schedule:Compact="EB_' in line
           for line in err.splitlines()):
        return {"role_id": role, "status": "incomplete_household_schedule_day_types",
                "idf_sha256": record["idf_sha256"]}
    if "Completed Successfully" not in end or severe or fatal or not (folder/"eplusout.sql").is_file():
        return {"role_id": role, "status": "energyplus_runtime_failed", "end": end.strip(),
                "severe": severe, "fatal": fatal, "warnings": warnings,
                "last_errors": "\n".join(err.splitlines()[-15:])}
    db = sqlite3.connect(folder/"eplusout.sql")
    try:
        days = db.execute("""SELECT count(*), count(DISTINCT printf('%02d-%02d',Month,Day))
          FROM Time WHERE COALESCE(WarmupFlag,0)=0 AND IntervalType=1 AND Interval=60""").fetchone()
        if days != (record["run_days"]*24, record["run_days"]):
            return {"role_id": role, "status": "time_grid_failed", "time_rows_days": days}
        ac_count, ac_j = energy(db, "EB Selected Household AC Proxy Electricity Energy", "EMS")
        ac_meter_count, ac_meter_j = energy(db, "Cooling:Electricity")
        if record["ac_selected_zones"]:
            if ac_count != days[0] or ac_meter_count != days[0] or abs(ac_j-ac_meter_j) > 0.01:
                return {"role_id": role, "status": "ac_meter_failed", "ac_rows": ac_count,
                        "meter_rows": ac_meter_count, "ac_j": ac_j, "meter_j": ac_meter_j}
            zone_sum = 0.0
            for index, _ in enumerate(record["ac_selected_zones"], 1):
                n, j = energy(db, f"EB Selected Zone {index} AC Proxy Electricity Energy", "EMS")
                if n != days[0]:
                    return {"role_id": role, "status": "ac_zone_series_failed", "zone_index": index, "rows": n}
                zone_sum += j
            if abs(ac_j-zone_sum) > 0.01:
                return {"role_id": role, "status": "ac_zone_sum_failed", "ac_j": ac_j, "zone_j": zone_sum}
        elif ac_count or ac_meter_count or ac_j or ac_meter_j:
            return {"role_id": role, "status": "unowned_ac_counted", "ac_rows": ac_count,
                    "meter_rows": ac_meter_count, "ac_j": ac_j, "meter_j": ac_meter_j}
        selected_zones = set(record["ac_selected_zones"])
        controlled_zones = selected_zones | set(record["ac_unselected_owned_zones_off"])
        active_hours = [set(hours) for hours in record["ac_active_hours_by_weekday"]]
        if len(active_hours) != 7:
            return {"role_id": role, "status": "ac_active_hours_manifest_missing"}
        for zone in sorted(controlled_zones):
            key = zone+" Ideal Loads"
            for variable, tolerance in (("Zone Ideal Loads Supply Air Total Cooling Energy", 1e-6),
                                        ("Zone Ideal Loads Supply Air Total Heating Energy", 1e-6),
                                        ("Zone Ideal Loads Supply Air Mass Flow Rate", 1e-9)):
                samples = zone_series(db, variable, key)
                if len(samples) != days[0]:
                    return {"role_id": role, "status": "ideal_loads_series_failed",
                            "zone": zone, "variable": variable, "rows": len(samples)}
                for day, hour, value in samples:
                    off = (zone not in selected_zones or hour not in active_hours[(day-14)%7])
                    if variable.endswith("Heating Energy") or off:
                        if abs(value) > tolerance:
                            return {"role_id": role, "status": "ideal_loads_off_or_heating_nonzero",
                                    "zone": zone, "variable": variable, "day": day,
                                    "hour": hour, "value": value, "off": off}
        devices = {}
        for item in record["devices"]:
            key = item["idf_equipment_name"]
            n, joules = energy(db, "Electric Equipment Electricity Energy", key)
            if n != days[0]:
                return {"role_id": role, "status": "device_series_failed", "device": item["device"], "rows": n}
            devices[item["device"]] = round(joules/J_PER_KWH, 6)
        # Source DeST loads are present in SQL as thermal boundary conditions.
        # The household result is assembled from EB_PRIVATE keys only.
        unexpected = db.execute("""SELECT DISTINCT d.KeyValue FROM ReportDataDictionary d
          WHERE d.Name='Electric Equipment Electricity Energy'
            AND upper(d.KeyValue) LIKE 'EB_PRIVATE_%'""").fetchall()
        expected = {d["idf_equipment_name"].upper() for d in record["devices"]}
        if {key for (key,) in unexpected} != expected:
            return {"role_id": role, "status": "device_key_mismatch",
                    "unexpected_or_missing": sorted({key for (key,) in unexpected} ^ expected)}
        ac_kwh = ac_j/J_PER_KWH
        daily = {}
        if record["run_days"] == 10:
            daily_ac = day_energy(db, "EB Selected Household AC Proxy Electricity Energy", "EMS")
            daily_devices = {item["device"]: day_energy(db, "Electric Equipment Electricity Energy",
                                                        item["idf_equipment_name"])
                             for item in record["devices"]}
            for offset in range(10):
                day = f"07-{14+offset:02d}"
                values = {device: mapping.get(day, 0.0) for device, mapping in daily_devices.items()}
                daily[day] = {"ac_proxy_kwh": daily_ac.get(day, 0.0),
                              "device_kwh": values,
                              "household_attributable_kwh": round(daily_ac.get(day,0.0)+sum(values.values()),6)}
        return {"role_id": role, "status": "runtime_and_accounting_passed",
                "input_idf_sha256": record["idf_sha256"], "run_days": record["run_days"],
                "cache_signature": signature,
                "hourly_rows": days[0], "end": end.strip(), "warning_count": warnings,
                "severe_count": severe, "fatal_count": fatal,
                "ac_proxy_kwh": round(ac_kwh,6), "device_kwh": devices,
                "household_attributable_kwh": round(ac_kwh+sum(devices.values()),6),
                "daily": daily,
                "metric_status": "experimental_physical_proxy_not_measured_or_human_response"}
    finally:
        db.close()


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--roles", nargs="*", help="selected roles; omit for all in manifest")
    ap.add_argument("--workers", type=int, default=4)
    ap.add_argument("--reuse", action="store_true")
    args = ap.parse_args()
    manifest = json.loads(MANIFEST.read_text())
    records = manifest["records"]
    if args.roles:
        wanted = set(args.roles)
        records = [r for r in records if r["role_id"] in wanted]
        if len(records) != len(wanted):
            raise ValueError("requested role missing from manifest")
    results = []
    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        futures = {pool.submit(run_one, record, reuse=args.reuse): record["role_id"] for record in records}
        for future in as_completed(futures):
            role = futures[future]
            try:
                result = future.result()
            except Exception as exc:
                result = {"role_id": role, "status": "runner_exception", "error": repr(exc)}
            results.append(result)
            if len(results)%25 == 0 or result["status"] != "runtime_and_accounting_passed":
                print(f"{len(results)}/{len(records)} {role} {result['status']}", flush=True)
    results.sort(key=lambda r:r["role_id"])
    counts = dict(Counter(r["status"] for r in results))
    report = {"schema_version": "eb.behavior_injected_energyplus_runtime.v1",
              "input_manifest_sha256": sha(MANIFEST), "n": len(results),
              "energyplus_executable_sha256": engine_sha256(),
              "output_contract_version": OUTPUT_CONTRACT_VERSION,
              "status_counts": counts,
              "all_passed": counts == {"runtime_and_accounting_passed": len(results)},
              "energyplus_version": "24.1.0", "records": results}
    output = HERE / ("runtime_300.json" if len(records)==300 else "runtime_sample.json")
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2)+"\n")
    print(json.dumps({"n":len(results), "status_counts":counts, "report":str(output)}, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()
