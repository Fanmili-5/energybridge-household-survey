"""Verify the standalone Tianjin household IDF with real, offline EnergyPlus.

This checks device/IDF coupling with fixed inputs, not LLM plan quality, model
provider capacity, calibrated household realism, or a production deployment.
All generated run-period/reporting copies stay below --output. The original
author callbacks, run-period generator, and availability injector are extracted
from source without importing any model client.
"""
from __future__ import annotations

import argparse
import ast
from datetime import date, datetime, timedelta
import hashlib
import json
import math
import os
from pathlib import Path
import re
import subprocess
import sys

from audit_device_interface_controls import measure, method, values, kwh
from audit_upstream_appliance_binding import DEVICES, extract_function, objects

PROJECT = Path(__file__).resolve().parents[1]
VARIANTS = (
    'fixed_off', 'fixed_half', 'fixed_shifted', 'fixed_full',
    'original_ev', 'original_ewh', 'original_cool24', 'original_cool28',
)
HANDLES = {
    **{device: ('schedule:constant', prefix + '_Power_Frac')
       for device, (prefix, _) in DEVICES.items()},
    'ev': ('schedule:constant', 'EV_Charging_Fraction_Control'),
    'ewh_sp': ('schedule:constant', 'EWH_Setpoint_Control'),
    'cool': ('schedule:compact', 'cooling_sch'),
    'heat': ('schedule:compact', 'heating_sch'),
    'hvac_avail': ('schedule:constant', 'HVAC_Availability_Control'),
}


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def save(path, value):
    Path(path).write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + '\n')


def require(condition, detail):
    if not condition:
        raise AssertionError(detail)


def close(a, b, detail, *, absolute=1e-6, relative=1e-10):
    require(math.isfinite(float(a)) and math.isfinite(float(b)), detail + ': non-finite value')
    require(math.isclose(a, b, abs_tol=absolute, rel_tol=relative),
            f'{detail}: {a!r} != {b!r}')


def series_check(row, name, key=None):
    points = values(row, name, key)
    require(len(points) == 144, f'{name}/{key}: expected 144 ten-minute rows, got {len(points)}')
    for index, (end_hour, value) in enumerate(points):
        close(end_hour, (index + 1) / 6, f'{name}/{key}: timestep {index}')
        require(math.isfinite(value), f'{name}/{key}: nonfinite reading')
    return points


def compare_points(left, right, label):
    require(len(left) == len(right), label + ': row count mismatch')
    maximum = 0.0
    exact = True
    for index, ((ha, va), (hb, vb)) in enumerate(zip(left, right)):
        close(ha, hb, f'{label}: timestamp {index}')
        close(va, vb, f'{label}: value {index}')
        maximum = max(maximum, abs(va - vb))
        exact = exact and ha == hb and va == vb
    return {'rows': len(left), 'exactly_equal': exact, 'max_abs_difference': maximum}


def error_report(folder):
    err = (folder / 'eplusout.err').read_text(errors='replace')
    warning_messages = len(re.findall(r'\*\*\s*Warning\s*\*\*', err, re.I))
    severe_messages = len(re.findall(r'\*\*\s*Severe\s*\*\*', err, re.I))
    fatal_messages = len(re.findall(r'\*\*\s*Fatal\s*\*\*', err, re.I))
    summaries = re.findall(r'EnergyPlus Completed Successfully--\s*(\d+)\s+Warning;\s*(\d+)\s+Severe Errors', err)
    result = {
        'warning_message_count': warning_messages,
        'severe_message_count': severe_messages,
        'fatal_message_count': fatal_messages,
        'completed_summary_warning_count': int(summaries[-1][0]) if summaries else None,
        'completed_summary_severe_count': int(summaries[-1][1]) if summaries else None,
        'warning_note': 'Existing modeling warnings are retained and counted; pass does not mean zero warnings.',
    }
    require(severe_messages == 0 and fatal_messages == 0, f'{folder}: Severe/Fatal in EnergyPlus log')
    require(bool(summaries) and result['completed_summary_severe_count'] == 0,
            f'{folder}: missing successful completion summary')
    return result


def standalone_contract(body, reference, design):
    records = objects(body)
    lookup = {(r[0].lower(), r[1].lower()): r for r in records if len(r) > 1}
    declared = {key: (kind, name.lower()) in lookup for key, (kind, name) in HANDLES.items()}
    require(all(declared.values()), f'Standalone template missing control schedules: {declared}')
    originals = {r[1].lower(): r for r in objects(reference)
                 if r[0].lower() == 'electricequipment'}
    bindings = {}
    for device, (prefix, original) in DEVICES.items():
        schedule = lookup['schedule:constant', (prefix + '_Power_Frac').lower()]
        equipment_name = (prefix + '_Appliance').lower()
        candidates = [r for r in records if r[0].lower() == 'electricequipment' and r[1].lower() == equipment_name]
        require(len(candidates) == 1, f'{device}: expected exactly one dynamic ElectricEquipment')
        require(not any(r[0].lower() == 'electricequipment' and r[1].lower() == original
                        for r in records), f'{device}: old fixed equipment would duplicate load')
        equipment = candidates[0]
        require(equipment[2].lower() == 'living_unit1', f'{device}: wrong thermal zone')
        require(equipment[3].lower() == (prefix + '_Power_Frac').lower(), f'{device}: wrong schedule reference')
        close(float(schedule[3]), 0.0, f'{device}: default input must be zero')
        close(float(equipment[5]), design[device], f'{device}: writer design wattage mismatch')
        for index in (8, 9, 10):
            close(float(equipment[index]), float(originals[original][index]), f'{device}: changed heat fraction {index}')
        bindings[device] = {'design_w': float(equipment[5]),
                            'heat_fractions_latent_radiant_lost': list(map(float, equipment[8:11])),
                            'schedule_type_limits': schedule[2]}
    return {'all_nine_schedules_in_standalone_file': declared, 'device_bindings': bindings}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--upstream', type=Path, default=PROJECT / 'upstream_2b17ae6')
    parser.add_argument('--model', type=Path, default=PROJECT / 'models/tianjin_family_eb_v1/family_all_appliances.idf')
    parser.add_argument('--ep-root', type=Path, default=Path(os.environ.get('EPLUS_ROOT', '/Applications/EnergyPlus-24-1-0')))
    parser.add_argument('--output', type=Path,
                        default=PROJECT / 'artifacts' / ('complete-household-idf-' + datetime.now().strftime('%Y%m%d-%H%M%S')))
    args = parser.parse_args()
    root, model, ep, output = (getattr(args, name).resolve() for name in ('upstream', 'model', 'ep_root', 'output'))
    require(model.is_file(), f'Missing standalone model: {model}')
    require((ep / 'energyplus').is_file(), f'Missing EnergyPlus executable: {ep}')
    output.mkdir(parents=True, exist_ok=False)
    def forbid_network(event, arguments):
        if event in ('socket.connect', 'socket.getaddrinfo'):
            raise RuntimeError('Complete IDF verification forbids network and model calls')
    sys.addaudithook(forbid_network)

    runner = root / 'experiments/benchmark/family_runner.py'
    generator_file = root / 'energybridge/data/day_ahead.py'
    prep = root / 'experiments/benchmark/run_persona_json.py'
    base = root / 'experiments/models/family_home/family_simple.idf'
    reference = root / 'experiments/models/family_home/original_model.idf'
    bindings_file = PROJECT / 'realtime_pilot/native_assets.py'
    source_paths = [Path(__file__).resolve(), Path(measure.__code__.co_filename).resolve(),
                    Path(extract_function.__code__.co_filename).resolve(), runner, generator_file,
                    prep, base, reference, bindings_file, model,
                    root / 'experiments/weather/epw/CHN_TJ_Tianjin.545270_CSWD.epw']
    source_hashes = {str(path): sha(path) for path in source_paths}
    try:
        commit = subprocess.check_output(['git', '-C', str(root), 'rev-parse', 'HEAD'], text=True, stderr=subprocess.DEVNULL).strip()
    except subprocess.CalledProcessError:
        commit = None
    report = {
        'passed': False, 'upstream_commit': commit, 'source_hashes': source_hashes,
        'energyplus_version': subprocess.check_output([str(ep / 'energyplus'), '--version'], text=True).strip(),
        'paid_api_calls': 0, 'network_forbidden': True, 'production_changed': False,
        'scope': 'Fixed commands through original EB init/writer and real one-day EP; original thermal fractions preserved.',
        'not_validated': ['LLM planning quality', 'provider throughput', 'individual-home calibration', 'production deployment'],
        'cases': {}, 'comparisons': {},
    }
    try:
        tree = ast.parse(runner.read_text())
        design = next(ast.literal_eval(node.value) for node in tree.body if isinstance(node, ast.Assign)
                      and any(isinstance(target, ast.Name) and target.id == '_APPL_DESIGN_W' for target in node.targets))
        writer = extract_function(runner, '_write_appliance_actuators', {'_APPL_DESIGN_W': design})
        init = method(runner, '_FamilyLoop', 'init', {})
        namespace = {'Path': Path, 'date': date, 'timedelta': timedelta}
        extract_function(generator_file, '_idf_field', namespace)
        generator = extract_function(generator_file, 'generate_runperiod_idf', namespace)
        prep_namespace = {}
        extract_function(prep, '_idf_field', prep_namespace)
        inject = extract_function(prep, '_enable_hvac_availability_control', prep_namespace)
        binding_tree = ast.parse(bindings_file.read_text())
        binding_namespace = {'Path': Path, 're': re, 'UPSTREAM': root, 'file_hash': sha}
        for node in binding_tree.body:
            if isinstance(node, ast.Assign):
                for target in node.targets:
                    if isinstance(target, ast.Name) and target.id in ('BINDING_VERSION', 'DEVICE_BINDINGS'):
                        binding_namespace[target.id] = ast.literal_eval(node.value)
        extract_function(bindings_file, 'idf_objects', binding_namespace)
        bind = extract_function(bindings_file, 'bind_native_appliances', binding_namespace)

        complete_body = model.read_text()
        report['standalone_contract'] = standalone_contract(complete_body, reference.read_text(), design)
        first_injection = inject(complete_body.splitlines())
        require(inject(first_injection) == first_injection, 'Availability injection must be idempotent')
        report['availability_injection_idempotent'] = True
        runtime_folder = output / 'runtime_asset'
        runtime_folder.mkdir()
        runtime_idf = generator(base, runtime_folder, start_date=date(2007, 7, 1), days=1)
        runtime_idf.write_text('\n'.join(inject(runtime_idf.read_text().splitlines())) + '\n')
        report['runtime_binding_repair'] = bind(runtime_idf, design)
        runtime_body = runtime_idf.read_text()
        report['runtime_asset_sha256'] = sha(runtime_idf)
        runs = {}
        cases = [('original_zero', base.read_text(), 'original_off')]
        cases += [(group + '/' + variant, body, variant)
                  for group, body in (('standalone', complete_body), ('runtime', runtime_body))
                  for variant in VARIANTS]
        for label, body, variant in cases:
            folder = output / label
            row = measure(root, ep, folder, body, writer, init, generator, inject, design, variant)
            if label != 'original_zero':
                require(all(value != -1 for value in row['handles'].values()), f'{label}: missing handle')
                require(set(row['handles']) == set(HANDLES), f'{label}: unexpected handle inventory')
            for name, key in (('Electricity:Facility', None), ('Cooling:Electricity', None),
                              ('Zone Mean Air Temperature', 'living_unit1'),
                              ('Zone Thermostat Cooling Setpoint Temperature', 'living_unit1'),
                              ('Water Heater Electricity Energy', 'Water Heater_Tank_unit1'),
                              ('Water Heater Tank Temperature', 'Water Heater_Tank_unit1')):
                series_check(row, name, key)
            errors = error_report(folder)
            record = {'passed': True, 'variant': variant, 'handles': row['handles'],
                      'facility_kwh': kwh(row, 'Electricity:Facility'), 'errors': errors,
                      'artifact_hashes': {str(p.relative_to(output)): sha(p) for p in folder.iterdir() if p.is_file()}}
            report['cases'][label] = record
            runs[label] = row
            save(output / 'report.json', report)
            print(label + ' PASS', flush=True)

        baseline, off = runs['original_zero'], runs['standalone/fixed_off']
        report['comparisons']['zero_input_vs_original'] = {}
        for name, key in (('Electricity:Facility', None), ('Zone Mean Air Temperature', 'living_unit1')):
            report['comparisons']['zero_input_vs_original'][name] = compare_points(values(baseline, name, key), values(off, name, key), name)
        report['comparisons']['standalone_vs_runtime'] = {}
        for variant in VARIANTS:
            left, right = runs['standalone/' + variant], runs['runtime/' + variant]
            common = sorted(set(left['series']) & set(right['series']))
            evidence = {}
            for name in common:
                a, b = left['series'][name], right['series'][name]
                require(a['unit'] == b['unit'], variant + '/' + name + ': unit mismatch')
                evidence[name] = compare_points(a['values'], b['values'], variant + '/' + name)
            report['comparisons']['standalone_vs_runtime'][variant] = {
                'passed': True, 'common_output_count': len(common), 'series': evidence,
                'standalone_only_reporting_keys': sorted(set(left['series']) - set(right['series'])),
                'runtime_only_reporting_keys': sorted(set(right['series']) - set(left['series'])),
            }

        report['device_pulse_results'] = {}
        for device, (prefix, _) in DEVICES.items():
            key = prefix + '_Appliance'
            off_points = series_check(off, 'Electric Equipment Electricity Energy', key)
            require(all(abs(value) < 1e-8 for _, value in off_points), device + ': nonzero off load')
            report['device_pulse_results'][device] = {}
            for variant in ('fixed_half', 'fixed_shifted', 'fixed_full'):
                row = runs['standalone/' + variant]
                points = series_check(row, 'Electric Equipment Electricity Energy', key)
                expected = design[device] / 1000 * (1.0 if variant == 'fixed_full' else 0.5)
                amount = kwh(row, 'Electric Equipment Electricity Energy', key)
                close(amount, expected, device + '/' + variant + ': pulse kWh', absolute=1e-7)
                start = 20 if variant == 'fixed_shifted' else 18
                active = [h for h, value in points if value > 1e-8]
                require(len(active) == 6 and all(start < h <= start + 1 + 1e-7 for h in active),
                        f'{device}/{variant}: unexpected active slots {active}')
                report['device_pulse_results'][device][variant] = {'kwh': amount, 'expected_kwh': expected, 'active_end_hours': active}

        ev = runs['standalone/original_ev']
        ev_kwh = kwh(ev, 'Electric Equipment Electricity Energy', 'EV_Charger')
        close(ev_kwh, 3.5, 'EV half-design one-hour energy', absolute=1e-7)
        ev_active = [h for h, value in series_check(ev, 'Electric Equipment Electricity Energy', 'EV_Charger') if value > 1e-8]
        require(len(ev_active) == 6 and all(18 < h <= 19 + 1e-7 for h in ev_active), 'EV pulse outside requested window')
        wh = runs['standalone/original_ewh']
        wh_off = kwh(off, 'Water Heater Electricity Energy', 'Water Heater_Tank_unit1')
        wh_on = kwh(wh, 'Water Heater Electricity Energy', 'Water Heater_Tank_unit1')
        require(wh_on > wh_off + 1e-5, 'Water heater setpoint pulse did not increase heater energy')
        off_tank = values(off, 'Water Heater Tank Temperature', 'Water Heater_Tank_unit1')
        on_tank = values(wh, 'Water Heater Tank Temperature', 'Water Heater_Tank_unit1')
        tank_gain = max(on_value - off_value for (h, on_value), (_, off_value) in zip(on_tank, off_tank) if 18 < h <= 20)
        require(tank_gain > 0.1, 'Water heater setpoint pulse did not raise physical tank temperature')
        cold, warm = runs['standalone/original_cool24'], runs['standalone/original_cool28']
        cold_kwh, warm_kwh = kwh(cold, 'Cooling:Electricity'), kwh(warm, 'Cooling:Electricity')
        require(cold_kwh > warm_kwh + 1e-5, 'Lower cooling setpoint did not increase cooling electricity')
        cold_temp = values(cold, 'Zone Mean Air Temperature', 'living_unit1')
        warm_temp = values(warm, 'Zone Mean Air Temperature', 'living_unit1')
        mean_temp_difference = sum(b - a for (_, a), (_, b) in zip(cold_temp, warm_temp)) / 144
        require(mean_temp_difference > 0.1, 'Cooling setpoints did not change physical zone temperature')
        for row, target in ((cold, 24), (warm, 28)):
            points = values(row, 'Zone Thermostat Cooling Setpoint Temperature', 'living_unit1')
            require(any(abs(value - target) < 1e-6 for _, value in points), 'Requested cooling setpoint absent from EP outputs')
        report['positive_controls'] = {'ev_pulse_kwh': ev_kwh, 'ev_active_end_hours': ev_active,
            'ewh_standby_kwh': wh_off, 'ewh_preheat_kwh': wh_on, 'ewh_max_tank_temperature_gain_c': tank_gain,
            'cooling_24c_kwh': cold_kwh, 'cooling_28c_kwh': warm_kwh,
            'mean_zone_temperature_28_minus_24_c': mean_temp_difference}
        report['passed'] = True
        report['real_ep_cases'] = len(runs)
    except Exception as exc:
        report['failure'] = {'type': type(exc).__name__, 'message': str(exc)}
        raise
    finally:
        report['sources_unchanged'] = {path: sha(path) == value for path, value in source_hashes.items()}
        if not all(report['sources_unchanged'].values()):
            report['passed'] = False
        save(output / 'report.json', report)
    require(report['passed'], 'Verification failed or source changed; see report.json')
    print(f'PASS: {report["real_ep_cases"]} real EP cases; zero model calls. Report: {output / "report.json"}', flush=True)


if __name__ == '__main__':
    main()
