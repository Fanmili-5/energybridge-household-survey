"""Run explicitly scoped source thermal controls through the existing EB binding.

This reusable component runner cannot grant formal or whole-CASE execution.
All housing, equipment and source-demand definitions arrive as pinned inputs.
"""
import csv
import datetime as dt
import importlib.util
from pathlib import Path
import sys
import traceback

from .case_commands import CaseTimeline, CommandClock
from .common import ROOT, read, require, save, sha
from .idf import Fields, objects, one, parse
from .source_adapter import source_file


def load_module(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    value = importlib.util.module_from_spec(spec)
    sys.modules[name] = value
    spec.loader.exec_module(value)
    return value


def run_probe(pack_ref, out, *, root=ROOT):
    root = Path(root).resolve()
    pack = read(source_file(pack_ref, root))
    require(pack.get('schema') == 'national_idf.source_thermal_CASE_probe.v1'
            and pack.get('formal_admitted') is False and pack.get('whole_CASE_executed') is False,
            'THERMAL_PROBE_SCOPE_REQUIRED')
    channels = set(pack['applied_channels'])
    require(channels and channels <= {'hvac', 'water_heater'}, 'THERMAL_PROBE_UNSUPPORTED_CHANNEL')
    case = read(source_file(pack['case'], root))
    domain = read(source_file(pack['unreviewed_input_domain'], root))
    timeline = CaseTimeline(case, domain, root=root)
    life, control = case['life'], case['controls']
    require(not life['occupancy'] and not life['mixed_water_daily']
            and not any(life.get('mixed_water_overrides', {}).values())
            and all(need['cycles'] == 0 for need in life['services_daily'].values())
            and not any(control['program_starts_daily'].values())
            and not any(starts for values in control.get('program_start_overrides', {}).values() for starts in values.values())
            and life['ev_daily']['traction_kWh'] == 0 and not control['ev_daily_windows']
            and not any(control.get('ev_window_overrides', {}).values()), 'THERMAL_PROBE_UNAPPLIED_DEMAND')
    model = source_file(pack['model'], root)
    weather = source_file(pack['weather'], root)
    engine_refs = pack['official_engine_files']
    for ref in engine_refs:
        source_file(ref, root)
    executable = next(ref for ref in engine_refs if Path(ref['path']).name == 'energyplus')
    engine = source_file(executable, root).parent
    schema = next(ref for ref in engine_refs if Path(ref['path']).name == 'Energy+.schema.epJSON')
    require(source_file(schema, root).parent == engine, 'THERMAL_PROBE_ENGINE_SCHEMA')
    fields = Fields(source_file(schema, root))
    rows = parse(model.read_text())
    require(float(one(rows, 'Timestep')[1]) * timeline.step_min == 60, 'THERMAL_PROBE_STEP_MISMATCH')
    period = one(rows, 'RunPeriod')
    dates = [dt.date(*[int(fields.get(period, key)) for key in keys]).isoformat() for keys in
        [('begin_year', 'begin_month', 'begin_day_of_month'), ('end_year', 'end_month', 'end_day_of_month')]]
    require(dates == [case['run']['start_date'], case['run']['end_date']], 'THERMAL_PROBE_CALENDAR_MISMATCH')
    for i in range(timeline.steps):
        frame = timeline.frame(i)
        if 'hvac' not in channels:
            require(all(frame['control'][key] == control[key] for key in ('heating_C', 'cooling_C', 'hvac_available')),
                    'THERMAL_PROBE_UNSELECTED_HVAC_COMMAND')
        if 'water_heater' not in channels:
            require(frame['control']['tank_target_C'] == control['tank_target_C'], 'THERMAL_PROBE_UNSELECTED_TANK_COMMAND')
    suite_ref, binding_ref = pack['EB_modules']['suite'], pack['EB_modules']['binding']
    suite_module = load_module(source_file(suite_ref, root), 'thermal_CASE_EB_suite')
    binding_module = load_module(source_file(binding_ref, root), 'thermal_CASE_EB_binding')
    config = {key: {'present': False} for key in ('washer', 'dryer', 'dishwasher', 'water_heater', 'ev', 'refrigerator')}
    derivation = {'active_EB_values': {}, 'inactive_devices_have_no_created_tasks': True}
    if 'water_heater' in channels:
        tanks = [r for r in objects(rows, 'WaterHeater:Stratified') if r[1] == pack['EB_mapping']['water_heater']]
        require(len(tanks) == 1, 'THERMAL_PROBE_TANK_MAPPING')
        tank = tanks[0]
        require(fields.get(tank, 'heater_1_setpoint_temperature_schedule_name')
                == fields.get(tank, 'heater_2_setpoint_temperature_schedule_name'), 'THERMAL_PROBE_TANK_DUAL_TARGET_UNSUPPORTED')
        rated_W = float(fields.get(tank, 'heater_1_capacity'))
        config['water_heater'] = {'present': True, 'rated_kw': rated_W / 1000}
        derivation['active_EB_values']['water_heater.rated_kw'] = {'value': rated_W / 1000,
            'source_model': pack['model'], 'object': tank[1], 'field': 'heater_1_capacity',
            'conversion': 'W / 1000; native EP electricity only, no Python heater load'}
    suite = suite_module.ApplianceSuite(config, timeline.days, [], explicit_only=True)
    binding = binding_module.ApplianceBinding(model.read_text(), source_file(schema, root), suite, pack['EB_mapping'])
    out = Path(out).absolute()
    require(not out.exists(), 'OUTPUT_EXISTS', str(out))
    out.mkdir(parents=True)
    save(out / 'PROBE.json', pack)
    save(out / 'EB_VALUE_DERIVATION.json', derivation)
    implementation = [suite_ref, binding_ref, *engine_refs]
    for name in ('national_idf/thermal_case_runtime.py', 'national_idf/case_commands.py', 'national_idf/request_support.py'):
        implementation.append({'path': name, 'sha256': sha(root / name)})
    sys.path.insert(0, str(engine))
    from pyenergyplus.api import EnergyPlusAPI
    api = EnergyPlusAPI()
    state = api.state_manager.new_state()
    binding.request_outputs(api.exchange, state)
    clock = CommandClock(timeline)
    trace, current = [], []
    progress = {'initialized': False, 'zone_steps': 0, 'system_steps': 0, 'errors': []}

    def active(s):
        return api.exchange.api_data_fully_ready(s) and not api.exchange.warmup_flag(s) and api.exchange.kind_of_sim(s) == 3

    def fail(s):
        progress['errors'].append(traceback.format_exc())
        api.runtime.stop_simulation(s)

    def before(s):
        if not active(s):
            return
        try:
            if not progress['initialized']:
                binding.initialize(api.exchange, s)
                progress['initialized'] = True
            frame = clock.take_exchange(api.exchange, s)
            current[:] = [frame]
            c = frame['control']
            power = {'water_heater_setpoint_C': c['tank_target_C']} if 'water_heater' in channels else {}
            binding.write(api.exchange, s, power, heating_C=c['heating_C'], cooling_C=c['cooling_C'], available=c['hvac_available'])
            trace.append({'frame_index': frame['frame_index'], 'date': frame['date'], 'start_min': frame['start_min'],
                'elapsed_start_min': frame['elapsed_start_min'], 'duration_min': frame['duration_min'], **c})
        except Exception:
            fail(s)

    def after_system(s):
        if not active(s):
            return
        try:
            require(current, 'THERMAL_PROBE_SYSTEM_BEFORE_COMMAND')
            binding.observe_system(api.exchange, s, current[0]['day_index'])
            progress['system_steps'] += 1
        except Exception:
            fail(s)

    def after(s):
        if not active(s):
            return
        try:
            require(len(trace) == progress['zone_steps'] + 1, 'THERMAL_PROBE_CALLBACK_ORDER')
            trace[-1].update(binding.observe(api.exchange, s, current[0]['day_index']))
            progress['zone_steps'] += 1
        except Exception:
            fail(s)

    api.runtime.callback_begin_zone_timestep_before_init_heat_balance(state, before)
    api.runtime.callback_end_system_timestep_after_hvac_reporting(state, after_system)
    api.runtime.callback_end_zone_timestep_after_zone_reporting(state, after)
    code = None
    try:
        code = api.runtime.run_energyplus(state, ['-w', str(weather), '-d', str(out / 'output'), str(model)])
    except Exception:
        progress['errors'].append(traceback.format_exc())
    finally:
        api.state_manager.delete_state(state)
    if trace:
        with (out / 'TRACE.csv').open('w', newline='') as stream:
            writer = csv.DictWriter(stream, fieldnames=trace[0].keys())
            writer.writeheader()
            writer.writerows(trace)
    save(out / 'RUNTIME.json', {'schema': 'national_idf.source_thermal_CASE_run.v1', 'exit_code': code,
        'progress': progress, 'command_writes': clock.next_index, 'expected_steps': timeline.steps,
        'applied_channels': sorted(channels), 'whole_CASE_executed': False, 'formal_admitted': False,
        'source_demands_weather_and_physics_are_pinned_not_CASE_inactive_values': True,
        'pack': pack_ref, 'model': pack['model'], 'weather': pack['weather'], 'case': pack['case'],
        'unreviewed_input_domain': pack['unreviewed_input_domain'], 'implementation': implementation,
        'database': {'path': str((out / 'output/eplusout.sql').relative_to(root)), 'sha256': sha(out / 'output/eplusout.sql')}
            if (out / 'output/eplusout.sql').exists() else None,
        'source_value_derivation': {'path': str((out / 'EB_VALUE_DERIVATION.json').relative_to(root)), 'sha256': sha(out / 'EB_VALUE_DERIVATION.json')},
        'generator_called': False, 'Chinese_installation_or_housing_validated': False})
    require(code == 0 and not progress['errors'] and clock.next_index == progress['zone_steps'] == timeline.steps,
            'THERMAL_PROBE_RUN_FAILED', progress)
    for item in implementation:
        source_file(item, root)
    print({'probe': pack['id'], 'zone_steps': progress['zone_steps'], 'system_steps': progress['system_steps'], 'formal_admitted': False})
