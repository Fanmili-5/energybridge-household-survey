"""Compose existing EB controllers for six-device engineering CASE execution."""
import csv
from pathlib import Path
import shutil
import sys
import tempfile
import time
import traceback

from .assembly import eb_bindings
from .case_commands import CaseTimeline, CommandClock, EVEbCommands
from .common import ROOT, read, require, save, seal, sha, verify
from .ev_reference import hardware_parameters
from .idf import Fields, objects, parse
from .program_resources import DEVICES, bind_program_domain, model_signature, plan_resources, write_resources
from .source_adapter import source_file
from .thermal_case_runtime import load_module

IMPLEMENTATION = ['national_idf/eb_water_heater_window.py', 'national_idf/joint_case_runtime.py', 'national_idf/joint_installation.py', 'national_idf/hvac_network.py',
    'national_idf/retained_context.py', 'national_idf/dwelling_metering.py', 'national_idf/assembly.py',
    'national_idf/program_resources.py', 'national_idf/program_case_runtime.py',
    'national_idf/case_commands.py', 'national_idf/request_support.py', 'national_idf/dated_case.py',
    'national_idf/life_binding.py', 'national_idf/life_installation.py', 'national_idf/water_service.py',
    'national_idf/source_numerics.py', 'national_idf/hvac_ports.py', 'national_idf/water_scope.py']


def life_channels(spec, case, rows, fields, timeline, root):
    """Opt in only to an assembly-bound native input installation."""
    if not spec.get('life_installation_receipt'):
        life = case['life']
        require(not life['occupancy'] and not life['mixed_water_daily'] and not life.get('mixed_water_overrides'),
            'SIX_REFERENCE_UNAPPLIED_LIFE_REQUEST')
        return None
    from .life_binding import LifeBinding
    receipt = read(source_file(spec['life_installation_receipt'], root))
    signature = model_signature(rows)
    if spec.get('registered_numerical_overlay'):
        from .source_numerics import validate_model_overlay
        overlay = validate_model_overlay(rows, spec['model'], spec['registered_numerical_overlay'],
            spec['engine_schema'], root=root)
        signature = overlay['source_model_signature']
    require(receipt['ready'] and receipt['formal_admitted'] is False
        and receipt['installed_model_signature'] == signature, 'SIX_LIFE_INSTALLATION_NOT_BOUND')
    source_file(receipt['pack'], root)
    require(receipt['general_water_gains_synchronized_to_CASE'] is False,
        'SIX_LIFE_UNREVIEWED_EVENT_GAINS_CLAIM')
    binding = LifeBinding(rows, fields, receipt['mapping'])
    binding.water_effect_scope = None
    if spec.get('water_effect_scope'):
        from .water_scope import describe
        binding.water_effect_scope = describe(rows, fields, spec['water_effect_scope'], root=root)
    for i in range(timeline.steps): binding.commands(timeline.frame(i))
    return binding


def supported(spec, case, rows, root):
    plan = plan_resources(rows, spec['engine_schema'], spec['resource_pack'], root=root)
    domain = read(source_file(spec['input_domain'], root)); bind_program_domain(plan, domain)
    timeline = CaseTimeline(case, domain, root=root)
    require(case['environment']['physics_configuration_id'] == spec['id'], 'SIX_CASE_CONFIGURATION_ID')
    require(not timeline.support['service_issues'], 'SIX_REFERENCE_UNFINISHED_TASK')
    receipt = read(source_file(spec['installation_receipt'], root))
    require(receipt['ready'] and receipt['HVAC_source_context_matched'], 'SIX_HVAC_INSTALLATION_NOT_SUPPORTED')
    if spec['EB_mapping'].get('additional_hvac') or receipt.get('HVAC_ports'):
        require(receipt.get('HVAC_ports') == [spec['EB_mapping']['hvac']]+spec['EB_mapping'].get('additional_hvac', []),
            'SIX_HVAC_GROUP_INSTALLATION_MAPPING_MISMATCH')
    fields = Fields(source_file(spec['engine_schema'], root)); eb_bindings(rows, spec['EB_mapping'], fields)
    tank = next(r for r in objects(rows, 'WaterHeater:Stratified') if r[1] == spec['EB_mapping']['water_heater'])
    require(fields.get(tank, 'heater_1_setpoint_temperature_schedule_name') == fields.get(
        tank, 'heater_2_setpoint_temperature_schedule_name'), 'SIX_DUAL_TANK_TARGET_UNSUPPORTED')
    hardware_parameters(spec['EV_reference'], root)
    for ref in spec['official_engine_files']+list(spec['EB_modules'].values()): source_file(ref, root)
    life_channels(spec, case, rows, fields, timeline, root)
    return timeline, plan, fields


def compile_joint_case(spec_ref, case, out, *, mode, root=ROOT):
    require(mode == 'engineering_reference', 'SIX_REFERENCE_MODE_REQUIRED')
    spec = read(source_file(spec_ref, root))
    require(spec['schema'] == 'national_idf.six_reference_fixture.v1', 'SIX_FIXTURE_SCHEMA')
    model = source_file(spec['model'], root); rows = parse(model.read_text())
    timeline, plan, fields = supported(spec, case, rows, root)
    for dep in spec['dependencies']:
        target = Path(dep['output_path'])
        require(not target.is_absolute() and '..' not in target.parts and target.parts, 'SIX_DEPENDENCY_PATH')
        source_file(dep['source'], root)
    weather = source_file(spec['weather'], root)
    period = objects(rows, 'RunPeriod')[0]
    import datetime as dt
    dates = [dt.date(*[int(fields.get(period, key)) for key in keys]).isoformat() for keys in
        [('begin_year', 'begin_month', 'begin_day_of_month'), ('end_year', 'end_month', 'end_day_of_month')]]
    require(dates == [case['run']['start_date'], case['run']['end_date']], 'SIX_CALENDAR_MISMATCH')
    out = Path(out).absolute(); require(not out.exists(), 'OUTPUT_EXISTS'); out.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=out.parent, prefix='.six-compile-') as temporary:
        stage = Path(temporary) / 'compiled'; stage.mkdir()
        shutil.copyfile(model, stage / 'in.idf'); shutil.copyfile(weather, stage / 'weather.epw')
        for dep in spec['dependencies']:
            target = stage / dep['output_path']; target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source_file(dep['source'], root), target)
        for name, value in [('CASE.json', case), ('FIXTURE.json', spec), ('INPUT_SUPPORT.json', timeline.support),
            ('COMPILER_IDENTITY.json', {name: sha(root / name) for name in IMPLEMENTATION})]: save(stage / name, value)
        write_resources(stage, plan, root=root)
        receipt = seal(stage, {'schema': 'national_idf.compiled_six_reference_CASE.v1',
            'execution_mode': mode, 'formal_admitted': False, 'whole_CASE_executed': False, 'six_devices_bound': True})
        stage.rename(out)
    return receipt


class SixCommands:
    def __init__(self, suite_module, timeline, plan, rows, fields, spec, root):
        from .program_case_runtime import WhitegoodsEbCommands
        self.white = WhitegoodsEbCommands(suite_module.ApplianceSuite, timeline, plan, rows, fields, DEVICES)
        hardware = hardware_parameters(spec['EV_reference'], root)['hardware']
        self.ev = EVEbCommands(suite_module.EVCharger,
            {'present': True, **hardware, 'min_soc': spec['EV_reserve_SOC']}, timeline)
        tank = next(r for r in objects(rows, 'WaterHeater:Stratified') if r[1] == spec['EB_mapping']['water_heater'])
        config = {name: {'present': False} for name in (*DEVICES, 'water_heater', 'ev', 'refrigerator')}
        config['water_heater'] = {'present': True, 'rated_kw': float(fields.get(tank, 'heater_1_capacity'))/1000}
        self.suite = suite_module.ApplianceSuite(config, timeline.days, [], explicit_only=True)
        # Share existing task states; this binding facade is never stepped.
        # Whitegoods and EV kernels are each stepped exactly once per frame.
        self.suite._shiftable = self.white.suite._shiftable
        self.suite._ev = self.ev.vehicle
        self.timeline, self.plan = timeline, plan


def run_joint_case(compiled, out, *, mode, root=ROOT, tank_diagnostics=None):
    require(mode in ('formal','engineering_reference'), 'SIX_REFERENCE_MODE_REQUIRED')
    compiled, out = Path(compiled).absolute(), Path(out).absolute(); receipt = verify(compiled)
    formal_release = None
    if mode == 'formal':
        from .runtime_release import validate_compiled
        formal_release = validate_compiled(compiled,root=root)
    else:
        require(receipt['schema'] == 'national_idf.compiled_six_reference_CASE.v1', 'SIX_COMPILED_SCHEMA')
    for name, signature in read(compiled / 'COMPILER_IDENTITY.json').items():
        require(sha(root / name) == signature, 'SIX_COMPILER_CODE_CHANGED')
    spec, case = read(compiled / 'FIXTURE.json'), read(compiled / 'CASE.json')
    require(sha(compiled / 'in.idf') == spec['model']['sha256'], 'SIX_COMPILED_MODEL_CHANGED')
    rows = parse((compiled / 'in.idf').read_text()); timeline, plan, fields = supported(spec, case, rows, root)
    life = life_channels(spec, case, rows, fields, timeline, root)
    if life is not None:
        from .water_service import WaterServiceObserver
        water = WaterServiceObserver([row[1] for row in objects(rows,'WaterUse:Equipment')])
    else: water = None
    engine = next(source_file(ref, root).parent for ref in spec['official_engine_files'] if Path(ref['path']).name == 'energyplus')
    suite_module = load_module(source_file(spec['EB_modules']['suite'], root), 'six_EB_suite')
    binding_module = load_module(source_file(spec['EB_modules']['binding'], root), 'six_EB_binding')
    commands = SixCommands(suite_module, timeline, plan, rows, fields, spec, root)
    from .hvac_ports import bind
    binding = bind(binding_module, suite_module, (compiled / 'in.idf').read_text(),
        source_file(spec['engine_schema'], root), commands.suite, spec['EB_mapping'], timeline.days)
    require(not out.exists(), 'OUTPUT_EXISTS'); out.mkdir(parents=True)
    save(out / 'IMPLEMENTATION.json', {name: sha(root / name) for name in IMPLEMENTATION})
    sys.path.insert(0, str(engine)); from pyenergyplus.api import EnergyPlusAPI
    api = EnergyPlusAPI(); state = api.state_manager.new_state(); binding.request_outputs(api.exchange, state)
    if life is not None:
        life.request_outputs(api.exchange, state); water.request_outputs(api.exchange, state)
    if tank_diagnostics is not None:
        from .joint_tank_diagnostics import JointTankDiagnostics
        require(type(tank_diagnostics) is JointTankDiagnostics, 'SIX_DIAGNOSTIC_TYPE')
        tank_diagnostics.open(out, rows, fields, spec, root)
        tank_diagnostics.request_outputs(api.exchange, state)
    clock, trace, handles, current, life_system = CommandClock(timeline), [], {}, [], []
    progress = {'zone_steps': 0, 'system_steps': 0, 'initialized': False, 'errors': []}
    def active(s): return api.exchange.api_data_fully_ready(s) and not api.exchange.warmup_flag(s) and api.exchange.kind_of_sim(s) == 3
    def fail(s): progress['errors'].append(traceback.format_exc()); api.runtime.stop_simulation(s)
    def before(s):
        if not active(s): return
        try:
            if not progress['initialized']:
                binding.initialize(api.exchange, s)
                if life is not None:
                    life.initialize(api.exchange, s); water.initialize(api.exchange, s)
                if tank_diagnostics is not None: tank_diagnostics.initialize(api.exchange, s)
                for device in DEVICES:
                    definition = plan['definition']['programs'][device]
                    for name in definition['schedules']:
                        handle = binding.handles[device] if name == definition['electric_schedule'] else api.exchange.get_actuator_handle(s, 'Schedule:File', 'Schedule Value', name)
                        require(handle >= 0, 'SIX_PROGRAM_ACTUATOR_MISSING', name); handles[name] = handle
                progress['initialized'] = True
            frame = clock.take_exchange(api.exchange, s); current[:] = [frame]
            if life is not None: life.write(api.exchange, s, frame)
            values = commands.white.step(frame); powers = {'ev': commands.ev.step(frame)}
            for device, channels in values.items():
                electric = plan['definition']['programs'][device]['electric_schedule']
                powers[device] = channels[electric]*binding.equipment[device]['design_W']/1000
                for name, value in channels.items(): api.exchange.set_actuator_value(s, handles[name], value)
            control = frame['control']
            from .eb_water_heater_window import effective_setpoint
            powers['water_heater_setpoint_C'] = effective_setpoint(control)
            binding.write(api.exchange, s, powers, heating_C=control['heating_C'], cooling_C=control['cooling_C'], available=control['hvac_available'])
            trace.append({'frame_index': frame['frame_index'], 'date': frame['date'], 'start_min': frame['start_min'],
                **control, 'water_heater_effective_setpoint_C':powers['water_heater_setpoint_C'], 'EV_connected': frame['ev']['connected'], 'EV_window_open': frame['ev']['charge_window_open'],
                **{name+'_command_kW': powers[name] for name in (*DEVICES, 'ev')}})
            if life is not None:
                trace[-1].update(requested_persons=sum(r['persons'] for r in frame['people'].values()),
                    requested_activity_total_W=sum(r['activity_total_W'] for r in frame['people'].values()),
                    requested_water_L=frame['mixed_water']['requested_volume_L'],
                    requested_water_target_C=frame['mixed_water']['target_C'])
        except Exception: fail(s)
    def before_system(s):
        if not active(s) or tank_diagnostics is None: return
        try: tank_diagnostics.begin(api.exchange, s)
        except Exception: fail(s)
    def after_system(s):
        if not active(s): return
        try:
            binding.observe_system(api.exchange, s, current[0]['day_index'])
            if life is not None:
                seconds = api.exchange.system_time_step(s)*3600
                temperatures = water.observe_system(api.exchange, s, seconds)
                volumes = life.observe(api.exchange, s, water=True)
                row = {'frame_index': current[0]['frame_index'], 'seconds': seconds}
                for name, values in volumes.items():
                    row.update({name+':'+k: v for k, v in {**values, **temperatures[name]}.items()})
                life_system.append(row)
            if tank_diagnostics is not None: tank_diagnostics.observe_system(api.exchange, s)
            progress['system_steps'] += 1
        except Exception: fail(s)
    def after(s):
        if not active(s): return
        try:
            require(len(trace) == progress['zone_steps']+1, 'SIX_CALLBACK_ORDER')
            trace[-1].update(binding.observe(api.exchange, s, current[0]['day_index'])); progress['zone_steps'] += 1
            if life is not None:
                values = life.observe(api.exchange, s, water=False)
                trace[-1].update({'native_people_'+key: sum(r[key] for r in values.values())
                    for key in next(iter(values.values()))})
        except Exception: fail(s)
    api.runtime.callback_begin_zone_timestep_before_init_heat_balance(state, before)
    if tank_diagnostics is not None:
        api.runtime.callback_begin_system_timestep_before_predictor(state, before_system)
    api.runtime.callback_end_system_timestep_after_hvac_reporting(state, after_system)
    api.runtime.callback_end_zone_timestep_after_zone_reporting(state, after)
    start = time.monotonic()
    try: code = api.runtime.run_energyplus(state, ['-w', str(compiled / 'weather.epw'), '-d', str(out / 'output'), str(compiled / 'in.idf')])
    finally:
        api.state_manager.delete_state(state)
        if tank_diagnostics is not None: tank_diagnostics.close()
    if trace:
        with (out / 'TRACE.csv').open('w', newline='') as stream:
            writer = csv.DictWriter(stream, fieldnames=trace[0]); writer.writeheader(); writer.writerows(trace)
    if life_system:
        with (out/'LIFE_SYSTEM.csv').open('w', newline='') as stream:
            writer = csv.DictWriter(stream, fieldnames=life_system[0]); writer.writeheader(); writer.writerows(life_system)
    if water is not None: save(out/'WATER_SERVICE.json', water.report())
    diagnostic_report = tank_diagnostics.report(out, timeline) if tank_diagnostics is not None and code == 0 and not progress['errors'] else None
    result = {'exit_code': code, 'seconds': time.monotonic()-start, 'progress': progress,
        'zone_clock': clock.diagnostics, 'tank_diagnostics': diagnostic_report,
        'compiled_manifest_sha256': sha(compiled / 'MANIFEST.json'), 'EV': commands.ev.report(), 'whitegoods': commands.white.report(),
        'native_tank_metered_by_existing_EB_binding': True, 'six_devices_executed': True,
        **({'HVAC_command_ports': [p['zone'] for p in [spec['EB_mapping']['hvac']]+spec['EB_mapping']['additional_hvac']],
            'whole_home_HVAC_service_verified': False} if spec['EB_mapping'].get('additional_hvac') else {}),
        'native_people_and_fixture_CASE_channels_executed': life is not None,
        'general_water_gains_synchronized_to_CASE': False if life is not None else None,
        'water_effect_scope': life.water_effect_scope if life is not None else None,
        'source_people_lights_background_and_fixture_demands_retained': True,
        'whole_CASE_executed': False, 'source_host_not_China': None, 'host_geography_not_inferred_from_reference_mode': True,
        'formal_admitted': mode == 'formal', 'runtime_release': formal_release,
        'declared_supported_CASE_channels_executed': code == 0 and not progress['errors']}
    save(out / 'RUNTIME.json', result)
    require(code == 0 and not progress['errors'] and progress['zone_steps'] == timeline.steps, 'SIX_REFERENCE_RUNTIME_FAILED', progress)
    return result
