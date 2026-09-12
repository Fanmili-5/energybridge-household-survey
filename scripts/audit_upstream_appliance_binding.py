"""Offline, isolated EP reproduction; never changes the checkout or calls an LLM.

The repair is a REVIEW CANDIDATE: powers/names come from the current runner;
heat fractions come from the author's original_model.idf. In particular, their
use in the Berlin building is a modeling choice, not an established calibration.
"""
from __future__ import annotations

import argparse
import ast
from contextlib import redirect_stdout
from datetime import date, timedelta
import difflib
import hashlib
import json
from pathlib import Path
import re
import sqlite3
import subprocess
import sys
from types import SimpleNamespace

DEVICES = {
    "washer": ("ClothesWasher", "clotheswasher1"),
    "dishwasher": ("Dishwasher", "dishwasher1"),
    "dryer": ("ClothesDryer", "electric_dryer1"),
    "refrigerator": ("Refrigerator", "refrigerator1"),
}
TEMPLATES = ["family_simple_3day.idf", "family_simple_7day.idf",
             "family_simple_14day.idf", "berlin_family_geg_final.idf"]


def objects(body):
    return [[v.strip() for v in raw.split(",")]
            for raw in re.sub(r"!.*", "", body).split(";") if raw.strip()]


def extract_function(path, name, namespace):
    tree = ast.parse(path.read_text())
    nodes = [n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef) and n.name == name]
    assert len(nodes) == 1, (path, name)
    node = nodes[0]
    node.decorator_list = []
    # Postpone annotations; no import/initialization of API clients or trainers.
    module = ast.Module(body=[ast.ImportFrom(module="__future__", names=[ast.alias(name="annotations")], level=0), node], type_ignores=[])
    exec(compile(ast.fix_missing_locations(module), str(path), "exec"), namespace)
    return namespace[name]


def candidate_body(body, reference, design):
    records = objects(body)
    assert any(r[0].lower() == "zone" and r[1].lower() == "living_unit1" for r in records)
    reference_equipment = {r[1].lower(): r for r in objects(reference) if r[0].lower() == "electricequipment"}
    additions = []
    for device, (prefix, original_name) in DEVICES.items():
        schedule, equipment = prefix + "_Power_Frac", prefix + "_Appliance"
        # Do not add duplicates over an existing static or dynamic appliance.
        conflicting = {schedule.lower(), equipment.lower(), original_name.lower()}
        assert not any(len(r) > 1 and r[1].lower() in conflicting for r in records), device
        source = reference_equipment[original_name]
        additions += [
            f"! Binding review candidate: {device}; heat fractions from original_model.idf\n"
            f"Schedule:Constant,{schedule},,0;\n",
            f"ElectricEquipment,{equipment},living_unit1,{schedule},EquipmentLevel,"
            f"{design[device]:g},,,{source[8]},{source[9]},{source[10]},{source[11]};\n",
        ]
    return body + "\n" + "\n".join(additions)


def run_case(root, ep_root, out, template_body, writer, design, pulse_start):
    out.mkdir(parents=True, exist_ok=False)
    namespace = {"Path": Path, "date": date, "timedelta": timedelta}
    day_ahead = root / "energybridge/data/day_ahead.py"
    extract_function(day_ahead, "_idf_field", namespace)
    generator = extract_function(day_ahead, "generate_runperiod_idf", namespace)
    template = out / "template.idf"
    template.write_text(template_body)
    idf = generator(template, out, start_date=date(2007, 7, 1), days=1)
    reporting = "\nOutput:SQLite,SimpleAndTabular;\nOutput:Meter,Electricity:Facility,Timestep;\n"
    reporting += "Output:Variable,*,Electric Equipment Electricity Energy,Timestep;\n"
    idf.write_text(idf.read_text() + reporting)
    sys.path.insert(0, str(ep_root))
    from pyenergyplus.api import EnergyPlusAPI
    api = EnergyPlusAPI()
    state = api.state_manager.new_state()
    api.runtime.set_console_output_status(state, False)
    ex = api.exchange
    loop = SimpleNamespace(appliance_suite=None, sp=26.0)
    errors, handles, commands = [], {}, []

    def callback(s):
        try:
            if not ex.api_data_fully_ready(s): return
            if not handles:
                for device, (prefix, _) in DEVICES.items():
                    handle = ex.get_actuator_handle(s, "Schedule:Constant", "Schedule Value", prefix + "_Power_Frac")
                    handles[device] = handle
                    setattr(loop, "h_" + device, handle)
                loop.h_ev = ex.get_actuator_handle(s, "Schedule:Constant", "Schedule Value", "EV_Charging_Fraction_Control")
                loop.h_cool = ex.get_actuator_handle(s, "Schedule:Compact", "Schedule Value", "cooling_sch")
                loop.h_heat = ex.get_actuator_handle(s, "Schedule:Compact", "Schedule Value", "heating_sch")
                loop.h_ewh_sp = -1  # Isolate this test from hot-water control.
            if ex.warmup_flag(s) or ex.kind_of_sim(s) != 3: return
            # Some EP templates expose 18.999999999 at the 19:00 boundary.
            # This belongs to the fixed test pulse, not the upstream scheduler.
            hour = round(ex.current_time(s), 8)
            on = pulse_start is not None and pulse_start <= hour < pulse_start + 1
            powers = {device: watts / 2000 if on else 0.0 for device, watts in design.items() if device in DEVICES}
            writer(ex, s, loop, powers, hour)
            commands.append({"hour": hour, "requested_kw": powers})
        except Exception as error:
            errors.append(repr(error))
            api.runtime.stop_simulation(s)

    api.runtime.callback_end_system_timestep_after_hvac_reporting(state, callback)
    weather = root / "experiments/weather/epw/CHN_TJ_Tianjin.545270_CSWD.epw"
    with (out / "console.txt").open("w") as log, redirect_stdout(log):
        code = api.runtime.run_energyplus(state, ["-w", str(weather), "-d", str(out), str(idf)])
    api.state_manager.delete_state(state)
    assert code == 0 and not errors, (out, code, errors)
    db = sqlite3.connect(out / "eplusout.sql")
    rows = db.execute("""SELECT d.Name,d.KeyValue,d.Units,t.Hour,t.Minute,r.Value
        FROM ReportData r JOIN ReportDataDictionary d USING(ReportDataDictionaryIndex)
        JOIN Time t USING(TimeIndex) JOIN EnvironmentPeriods e USING(EnvironmentPeriodIndex)
        WHERE t.WarmupFlag=0 AND e.EnvironmentType=3
        AND d.ReportingFrequency IN ('Zone Timestep','HVAC System Timestep')""").fetchall()
    db.close()
    equipment, facility, series = {}, 0.0, []
    for name, key, unit, hour, minute, value in rows:
        if name == "Electricity:Facility":
            assert unit == "J"
            facility += value / 3.6e6
            series.append(value / 3.6e6)
        if name == "Electric Equipment Electricity Energy" and key.lower().endswith("_appliance"):
            assert unit == "J"
            record = equipment.setdefault(key, {"kwh": 0.0, "active_end_hours": []})
            record["kwh"] += value / 3.6e6
            if value > 1e-6: record["active_end_hours"].append(hour + minute / 60)
    assert len(series) == 144, len(series)
    result = {"ep_exit": code, "handles": handles, "equipment": equipment,
              "facility_kwh": facility, "facility_series_kwh": series,
              "commands": commands, "idf_sha256": hashlib.sha256(idf.read_bytes()).hexdigest()}
    (out / "result.json").write_text(json.dumps(result, indent=2))
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--upstream", type=Path, required=True)
    parser.add_argument("--ep-root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    root, output = args.upstream.resolve(), args.output.resolve()
    output.mkdir(parents=True, exist_ok=False)
    runner = root / "experiments/benchmark/family_runner.py"
    tree = ast.parse(runner.read_text())
    design = next(ast.literal_eval(n.value) for n in tree.body if isinstance(n, ast.Assign)
                  and any(isinstance(t, ast.Name) and t.id == "_APPL_DESIGN_W" for t in n.targets))
    namespace = {"_APPL_DESIGN_W": design}
    native_writer = extract_function(runner, "_write_appliance_actuators", namespace)
    rl_writer = extract_function(root / "baselines/rl_energyplus/environment_pref_v2.py", "_write_actuators", {})
    folder = root / "experiments/models/family_home"
    reference = (folder / "original_model.idf").read_text()
    report = {"author_repo": "https://github.com/Agentic-Intelligence-Lab/EnergyBridge",
              "commit": subprocess.check_output(["git", "-C", str(root), "rev-parse", "HEAD"], text=True).strip(),
              "api_calls": 0, "production_changed": False,
              "thermal_assumption": "Heat fractions copied from author's Tianjin original_model.idf; Berlin transfer requires author review.",
              "cases": {}}
    patch = []
    for name in TEMPLATES:
        original = (folder / name).read_text()
        fixed = candidate_body(original, reference, design)
        # Exact same experiment for each default resource, independent of method.
        relative = "experiments/models/family_home/" + name
        patch.extend(line if line.endswith("\n") else line + "\n\\ No newline at end of file\n"
                     for line in difflib.unified_diff(original.splitlines(True), fixed.splitlines(True),
                                                     fromfile="a/" + relative, tofile="b/" + relative))
        case = {}
        for label, body, start, write in [
            ("original_off", original, None, native_writer),
            ("original_on", original, 18.0, native_writer),
            ("candidate_off", fixed, None, native_writer),
            ("candidate_on", fixed, 18.0, native_writer),
            ("candidate_shifted", fixed, 20.0, native_writer),
            ("candidate_rl_writer", fixed, 18.0, rl_writer),
        ]:
            run = run_case(root, args.ep_root, output / name / label, body, write, design, start)
            case[label] = {key: value for key, value in run.items() if key not in ("commands", "facility_series_kwh")}
            if label == "original_off": original_series = run["facility_series_kwh"]
            if label == "original_on":
                assert all(h == -1 for h in run["handles"].values())
                assert original_series == run["facility_series_kwh"], "Unexpected raw equipment response"
            if label == "candidate_off":
                assert all(v["kwh"] == 0 for v in run["equipment"].values())
                assert original_series == run["facility_series_kwh"], "Zero-input changed existing meter"
            if label.startswith("candidate"):
                assert all(h != -1 for h in run["handles"].values())
                assert len(run["equipment"]) == 4
                for device, (prefix, _) in DEVICES.items():
                    item = run["equipment"][(prefix + "_Appliance").upper()]
                    expected = 0 if start is None else design[device] / 2000
                    assert abs(item["kwh"] - expected) < 1e-6, (name, label, device, item, expected)
                    if start is not None:
                        assert len(item["active_end_hours"]) == 6
                        assert all(start < h <= start + 1 + 1e-6 for h in item["active_end_hours"])
        report["cases"][name] = case
        (output / "report.json").write_text(json.dumps(report, indent=2))
        print(name, "PASS", flush=True)
    (output / "candidate.patch").write_text("".join(patch))
    (output / "report.json").write_text(json.dumps(report, indent=2))
    print("Report:", output / "report.json", flush=True)


if __name__ == "__main__": main()
