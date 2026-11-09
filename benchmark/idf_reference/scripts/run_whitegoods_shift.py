"""Native/EB paired replay of a published whitegoods resource window.

The window is not an inferred machine cycle. No family generator is called.
"""
import argparse
import csv
import datetime as dt
import math
from pathlib import Path
import shutil
import sqlite3
import sys
import time
import traceback

from national_idf.common import ROOT, locked, read, require, save, sha
from national_idf.idf import Fields, objects, one, parse, render
from scripts.replay_hpxml_with_eb import module

OUT = ROOT / 'reports/eb_whitegoods_shift_20261031'
ORIGIN = ROOT / 'reports/p1_reference_components_20261029/source_published_schedule/run'
EB = ROOT / 'work/eb-native-component-20261029'
CHANNELS = {'washer': ('clothes_washer', 'hot_water_clothes_washer'),
            'dishwasher': ('dishwasher', 'hot_water_dishwasher')}
ALIASES = {'washer': 'clothes washer', 'dishwasher': 'dishwasher'}
SHIFTS = {'baseline': {'washer': 0, 'dishwasher': 0},
          'washer_shift': {'washer': 3, 'dishwasher': 0},
          'dishwasher_shift': {'washer': 0, 'dishwasher': 5},
          'both_shift': {'washer': 3, 'dishwasher': 5},
          'washer_electric_only': {'washer': 3, 'dishwasher': 0}}
ELECTRIC = ['Electric Equipment Electricity Energy', 'Electric Equipment Convective Heating Energy',
            'Electric Equipment Radiant Heating Energy', 'Electric Equipment Latent Gain Energy',
            'Electric Equipment Lost Heat Energy']
WATER = ['Water Use Equipment Hot Water Volume', 'Water Use Equipment Cold Water Volume',
         'Water Use Equipment Total Volume', 'Water Use Equipment Hot Water Temperature',
         'Water Use Equipment Cold Water Temperature', 'Water Use Equipment Target Water Temperature',
         'Water Use Equipment Mixed Water Temperature', 'Water Use Equipment Heating Energy']


def artifact(path):
    return {'path': str(path.relative_to(ROOT)), 'sha256': sha(path)}


def engine_and_fields():
    from national_idf.native_build_runtime import engine_directory
    engine = engine_directory()
    return engine, Fields(engine / 'Energy+.schema.epJSON')


def time_series(path, name, key):
    with sqlite3.connect(path) as connection:
        rows = connection.execute(
            'SELECT t.Month,t.Day,t.Hour,t.Minute,d.Value FROM ReportData d '
            'JOIN ReportDataDictionary q ON q.ReportDataDictionaryIndex=d.ReportDataDictionaryIndex '
            'JOIN Time t ON t.TimeIndex=d.TimeIndex WHERE q.Name=? AND upper(q.KeyValue)=upper(?) '
            "AND q.ReportingFrequency='Zone Timestep' AND t.WarmupFlag=0 ORDER BY d.TimeIndex",
            (name, key)).fetchall()
    return rows


def prepare(case, step, backend):
    require(case in SHIFTS and step in (1, 2, 5) and backend in ('native', 'eb'), 'INVALID_SHIFT_PROBE')
    require(not (backend == 'native' and case == 'washer_electric_only'), 'FAULT_IS_DIAGNOSTIC_ONLY')
    folder = OUT / f'{backend}_{case}_{step}min'
    require(not folder.exists(), 'OUTPUT_EXISTS', str(folder)); folder.mkdir()
    engine, fields = engine_and_fields()
    rows = parse((ORIGIN / 'in.idf').read_text())
    original = parse((ORIGIN / 'in.idf').read_text())
    year = int(fields.get(one(rows, 'RunPeriod'), 'begin_year'))
    begin = dt.datetime(year, 1, 15); end = begin + dt.timedelta(days=6)
    raw = list(csv.reader((ORIGIN / 'in.schedules.csv').open()))
    schedules = {row[1]: row for row in objects(rows, 'Schedule:File')}
    selected = {name: int(fields.get(schedules[name], 'column_number')) - 1
                for names in CHANNELS.values() for name in names}
    # Retain exactly the 24 published hourly entries on Jan15, with original
    # EnergyPlus interpolation/daylight-saving fields. Engine supplies substeps.
    source_offset = 14 * 24
    packet = {name: [raw[1 + source_offset + hour][col] for hour in range(24)]
              for name, col in selected.items()}
    require(all(sum(map(float, values)) > 0 for values in packet.values()), 'EMPTY_RESOURCE_WINDOW')
    compiled = [row[:] for row in raw]
    for row in compiled[1:]:
        for col in selected.values(): row[col] = '0'
    destination = 15 * 24  # engineering replay on Jan16, after a quiet first day
    offsets = SHIFTS[case] if backend == 'native' else SHIFTS['baseline']
    for device, names in CHANNELS.items():
        for name in names:
            for hour, value in enumerate(packet[name]):
                compiled[1 + destination + offsets[device] + hour][selected[name]] = value
    with (folder / 'in.schedules.csv').open('w', newline='') as stream:
        csv.writer(stream).writerows(compiled)
    # Nonselected source columns remain byte-for-value equivalent.
    require(all(a == b for first, second in zip(raw, compiled) for i, (a, b) in enumerate(zip(first, second))
                if i not in selected.values()), 'NONSELECTED_INPUT_COLUMN_CHANGED')
    period = one(rows, 'RunPeriod')
    for key, value in {'begin_month': begin.month, 'begin_day_of_month': begin.day, 'begin_year': year,
                       'end_month': end.month, 'end_day_of_month': end.day, 'end_year': year,
                       'day_of_week_for_start_day': begin.strftime('%A')}.items(): fields.set(period, key, value)
    one(rows, 'Timestep')[1] = 60 // step
    protocol = read(ROOT / 'configs/study_protocol.json')
    fields.set(one(rows, 'Building'), 'minimum_number_of_warmup_days', protocol['warmup_min_days'][0])
    fields.set(one(rows, 'Building'), 'maximum_number_of_warmup_days', protocol['warmup_max_days'][0])
    # Only relocate the already-required CSV; all interpolation fields retained.
    require(all(row[3] == 'in.schedules.csv' for row in objects(rows, 'Schedule:File')),
            'UNEXPECTED_EXTERNAL_SOURCE_FILE')
    excluded = {'RunPeriod', 'Timestep', 'Building'}
    physical = lambda data: [row for row in data if row[0] not in excluded and not row[0].startswith('Output')]
    require(physical(rows) == physical(original), 'SOURCE_PHYSICAL_OBJECT_CHANGED')
    rows = [row for row in rows if not row[0].startswith('Output')]
    rows += [['Output:SQLite', 'Simple']]
    for device in ('clothes washer', 'dishwasher', 'clothes dryer'):
        rows.extend([['Output:Variable', device, name, 'Timestep'] for name in ELECTRIC])
    for device in ALIASES.values():
        rows.extend([['Output:Variable', device, name, 'Timestep'] for name in WATER])
    rows.extend([['Output:Variable', name, 'Schedule Value', 'Timestep'] for name in selected])
    rows += [['Output:Variable', 'conditioned space', 'Zone Mean Air Temperature', 'Timestep'],
             ['Output:Meter', 'Electricity:Facility', 'Timestep']]
    programs = [row for row in objects(rows, 'EnergyManagementSystem:Program')
                if any(line.lower().startswith('set qdryer') for line in row[2:])]
    require(len(programs) == 1, 'DRYER_SOURCE_PROGRAM_AMBIGUOUS')
    rows += [['EnergyManagementSystem:OutputVariable', 'ShiftAudit Dryer Exhaust Flow', 'Qdryer',
              'Averaged', 'ZoneTimestep', programs[0][1], 'm3/s'],
             ['Output:Variable', '*', 'ShiftAudit Dryer Exhaust Flow', 'Timestep']]
    (folder / 'in.idf').write_text(render(rows))
    save(folder / 'INPUTS.json', {'source_IDF': artifact(ORIGIN / 'in.idf'),
         'source_CSV': artifact(ORIGIN / 'in.schedules.csv'), 'source_packet_date': f'{year}-01-15',
         'source_packet_hourly_values': packet, 'source_schedule_rows': {name: schedules[name] for name in selected},
         'reference_window_not_measured_machine_cycle': True, 'outside_window_zero_is_test_command_not_standby_evidence': True,
         'backend': backend, 'case': case, 'step_min': step, 'start_date': begin.date().isoformat(), 'days': 7,
         'shift_hours': SHIFTS[case], 'deliberate_fault': case == 'washer_electric_only',
         'IDF': artifact(folder / 'in.idf'), 'CSV': artifact(folder / 'in.schedules.csv'),
         'physics_objects_unchanged': True, 'nonselected_schedule_columns_unchanged': True,
         'family_or_AB_changed': False, 'formal_admitted': False})
    return folder, engine, fields, rows, begin


def run(case, step, backend):
    folder, engine, fields, rows, begin = prepare(case, step, backend)
    sys.path.insert(0, str(engine))
    from pyenergyplus.api import EnergyPlusAPI
    api = EnergyPlusAPI(); state = api.state_manager.new_state()
    progress = {'ticks': 0, 'writes': 0, 'initialized': False, 'errors': []}
    binding = suite = None
    profiles = {}; water_handles = {}; task_envelopes = {}
    if backend == 'eb':
        reference = OUT / f'native_baseline_{step}min/output/eplusout.sql'
        require(reference.exists(), 'NATIVE_REFERENCE_REQUIRED')
        count = 7 * 24 * 60 // step
        for names in CHANNELS.values():
            for name in names:
                series = time_series(reference, 'Schedule Value', name)
                require(len(series) == count and all(math.isfinite(r[4]) and 0 <= r[4] <= 1 for r in series),
                        'NATIVE_SOURCE_PROFILE_INVALID', name)
                profiles[name] = [r[4] for r in series]
        cfg = {name: {'present': False} for name in ('washer', 'dishwasher', 'dryer', 'ev', 'water_heater', 'refrigerator')}
        mapping = {'equipment': {}, 'water_heater': None, 'hvac': {'zone': 'conditioned space',
                   'availability': 'Always On Discrete',
                   'heating': {'kind': 'Schedule:Year', 'schedule': 'heating setpoint'},
                   'cooling': {'kind': 'Schedule:Year', 'schedule': 'cooling setpoint'}}}
        for device, names in CHANNELS.items():
            support = [i for i in range(count) if any(profiles[name][i] > 0 for name in names)]
            require(support, 'EMPTY_REFERENCE_SUPPORT')
            first, last = min(support), max(support) + 1
            shift_ticks = SHIFTS[case][device] * 60 // step
            require(last + shift_ticks <= count, 'RESOURCE_TAIL_WOULD_BE_CLIPPED')
            task_envelopes[device] = {'source_start_tick': first, 'source_end_tick': last,
                                     'shift_ticks': shift_ticks, 'support_duration_s': (last - first) * step * 60}
            row = next(row for row in objects(rows, 'ElectricEquipment') if row[1] == ALIASES[device])
            cfg[device] = {'present': True, 'power_kw': float(fields.get(row, 'design_level')) / 1000,
                          'duration_h': (last - first) * step / 60, 'earliest_h': 0, 'latest_h': 48}
            mapping['equipment'][device] = {'equipment': row[1], 'schedule_kind': 'Schedule:File'}
        suite = module('shift_suite', EB / 'appliance_sim.py').ApplianceSuite(cfg, 7, [], explicit_only=True)
        for device, span in task_envelopes.items():
            start_h = (span['source_start_tick'] + span['shift_ticks']) * step / 60
            source_day = span['source_start_tick'] * step // 1440
            require(suite.shift_appliance(device, source_day, start_h), 'EB_REFERENCE_WINDOW_REJECTED')
        binding = module('shift_binding', EB / 'appliance_binding.py').ApplianceBinding(
            (folder / 'in.idf').read_text(), engine / 'Energy+.schema.epJSON', suite, mapping)
        binding.request_outputs(api.exchange, state)
        save(folder / 'REFERENCE_TASKS.json', {'native_reference': artifact(reference), 'envelopes': task_envelopes,
             'completion_means': 'complete application of this source resource window; no cleaning/dryness inference',
             'physical_service_success': None})

    commands = []

    def active(s):
        return api.exchange.api_data_fully_ready(s) and not api.exchange.warmup_flag(s) and api.exchange.kind_of_sim(s) == 3

    def before(s):
        if backend != 'eb' or not active(s): return
        try:
            if not progress['initialized']:
                binding.initialize(api.exchange, s)
                for device, names in CHANNELS.items():
                    handle = api.exchange.get_actuator_handle(s, 'Schedule:File', 'Schedule Value', names[1])
                    require(handle >= 0, 'SOURCE_WATER_ACTUATOR_MISSING', names[1]); water_handles[device] = handle
                progress['initialized'] = True
            i = progress['ticks']
            current = dt.datetime(begin.year, api.exchange.month(s), api.exchange.day_of_month(s))
            minute = round(api.exchange.current_time(s) * 60) - step
            require((current - begin).days * 1440 + minute == i * step, 'REFERENCE_SHIFT_CLOCK_CHANGED', i)
            gates = suite.step(i * step / 60, step / 60)
            for device, names in CHANNELS.items():
                span = task_envelopes[device]; source_i = i - span['shift_ticks']
                electric = profiles[names[0]][source_i] if 0 <= source_i < len(profiles[names[0]]) else 0.0
                require(electric == 0 or gates[device] > 0, 'EB_TASK_GATE_TRUNCATES_RESOURCE', (device, i))
                water_i = i if case == 'washer_electric_only' and device == 'washer' else source_i
                water = profiles[names[1]][water_i] if 0 <= water_i < len(profiles[names[1]]) else 0.0
                # Reuse the existing EB-resolved schedule handles/design levels.
                # HVAC and all unrelated source schedules remain unactuated.
                api.exchange.set_actuator_value(s, binding.handles[device], electric)
                api.exchange.set_actuator_value(s, water_handles[device], water)
                commands.append({'tick': i, 'device': device, 'electric_fraction': electric,
                                 'water_fraction': water, 'EB_task_gate_active': gates[device] > 0})
                progress['writes'] += 2
        except Exception:
            progress['errors'].append(traceback.format_exc()); api.runtime.stop_simulation(s)

    def after(s):
        if active(s): progress['ticks'] += 1

    api.runtime.callback_begin_zone_timestep_before_init_heat_balance(state, before)
    api.runtime.callback_end_zone_timestep_after_zone_reporting(state, after)
    implementation = [Path(__file__).resolve(), EB / 'appliance_binding.py', EB / 'appliance_sim.py',
                      engine / 'energyplus', engine / 'Energy+.schema.epJSON', engine / 'Energy+.idd']
    from national_idf.native_build_runtime import api_libraries
    implementation.extend(api_libraries(engine))
    signatures = [artifact(path) for path in implementation]
    weather = ROOT / 'work/p1_hpxml_004ca3ce/weather/USA_CO_Denver.Intl.AP.725650_TMY3.epw'
    start = time.monotonic()
    try:
        code = api.runtime.run_energyplus(state, ['-w', str(weather), '-d', str(folder / 'output'), str(folder / 'in.idf')])
    finally:
        api.state_manager.delete_state(state)
    if commands:
        with (folder / 'COMMANDS.csv').open('w', newline='') as stream:
            writer = csv.DictWriter(stream, fieldnames=commands[0]); writer.writeheader(); writer.writerows(commands)
    save(folder / 'RUNTIME.json', {'exit_code': code, 'wall_seconds': time.monotonic() - start,
         'progress': progress, 'implementation': signatures, 'weather': artifact(weather),
         'task_results': None if suite is None else {name: app.all_results() for name, app in suite._shiftable.items()},
         'only_reference_packet_inputs_changed': True, 'HVAC_or_other_device_schedule_actuated': False,
         'reference_US_context_not_Chinese_admission': True, 'physical_cleaning_or_dryness_result': None,
         'family_generator_called': False, 'AB_changed': False, 'formal_admitted': False})
    require(code == 0 and not progress['errors'] and progress['ticks'] == 7 * 24 * 60 // step,
            'WHITEGOODS_SHIFT_RUN_FAILED', progress)
    for ref in signatures: locked(ref, ROOT)
    print(folder.name, 'completed', progress['ticks'], 'zone steps')


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--case', choices=SHIFTS, required=True)
    parser.add_argument('--step', type=int, choices=[1, 2, 5], required=True)
    parser.add_argument('--backend', choices=['native', 'eb'], required=True)
    args = parser.parse_args(); run(args.case, args.step, args.backend)
