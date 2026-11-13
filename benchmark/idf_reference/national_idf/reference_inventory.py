"""Inventory projection using existing exact-edit compiler and EB device kernels.

This extension supports explicit removal of isolated whitegoods. It does not
infer which fraction of an aggregate load belonged to an absent appliance.
"""
import copy
import csv
from pathlib import Path
import shutil
import sys
import time
import traceback

from .common import ROOT, read, require, save, seal, sha, verify
from .idf import Fields, objects, parse, render
from .reference_workflow import ref
from .source_adapter import source_file, selected


def compile_case(parent_fixture_ref, inventory_pack_ref, case, out, *, root=ROOT):
    from .assembly import transform, validate_objects
    from .case_commands import CaseTimeline
    from .program_resources import plan_resources, bind_program_domain
    from .reference_scenarios import inventory
    from .source_adapter import housing_fingerprint
    parent = read(source_file(parent_fixture_ref, root))
    rows = parse(source_file(parent['model'], root).read_text())
    plan = plan_resources(rows, parent['engine_schema'], parent['resource_pack'], root=root)
    pack = read(source_file(inventory_pack_ref, root))
    require(pack.get('schema') == 'national_idf.reference_inventory_pack.v1', 'INVENTORY_PACK_SCHEMA')
    inv = inventory(pack['equipment'])
    require(pack['parent_model'] == parent['model'], 'INVENTORY_SOURCE_NOT_BOUND')
    require(set(inv['installed']) >= {'air_conditioner', 'water_heater'}, 'INVENTORY_NETWORK_RETIREMENT_NOT_SUPPORTED')
    require(not inv['unknown_presence'], 'INVENTORY_PRESENCE_UNKNOWN')
    require(set(inv['installed']) == set(inv['controlled']), 'INVENTORY_BACKGROUND_RUNTIME_REQUIRES_FIXED_SERVICE')
    fields = Fields(source_file(parent['engine_schema'], root))
    absent = set(('washer', 'dryer', 'dishwasher','ev')) - set(inv['installed'])
    allowed = set(); retired_water = set()
    for device in absent:
        if device=='ev':
            consumers=[row for row in objects(rows,'ElectricEquipment') if row[1]==parent['EB_mapping']['equipment']['ev']['equipment']]
            require(len(consumers)==1,'INVENTORY_EV_SOURCE_MAPPING')
            require(all(float(fields.get(consumers[0],k))==v for k,v in
                        [('fraction_lost',1),('fraction_latent',0),('fraction_radiant',0)]),'INVENTORY_EV_NOT_OUTDOOR')
        else:
            programme = plan['definition']['programs'][device]
            consumers = [row for row in rows if
                         row[0] == 'ElectricEquipment' and row[1] == programme['equipment'] or
                         row[0] in ('OtherEquipment', 'WaterUse:Equipment') and
                         fields.get(row, 'schedule_name' if row[0] == 'OtherEquipment' else 'flow_rate_fraction_schedule_name')
                         in programme['schedules']]
        require(set(pack['retired_physical_object_names'][device]) == {row[1] for row in consumers},
                'INVENTORY_RETIREMENT_SCOPE_NOT_DERIVED_FROM_DEVICE', device)
        allowed.update((row[0], row[1]) for row in consumers)
        retired_water.update(row[1] for row in consumers if row[0] == 'WaterUse:Equipment')
    retired_names = {name for kind, name in allowed}
    from .assembly import referenced_row
    for operation in pack['changes']:
        require(operation['action'] in ('remove', 'replace'), 'INVENTORY_OPERATION_NOT_A_RETIREMENT')
        before = selected(rows, operation['object'])
        if operation['action'] == 'remove':
            require(tuple(before[:2]) in allowed or before[0] == 'Output:Variable' and before[1] in retired_names,
                    'INVENTORY_EDIT_OUTSIDE_ABSENT_DEVICE', before[:2])
        else:
            after = referenced_row(operation['after'], root)
            require(before[0] == 'WaterUse:Connections' and after == [v for v in before if v not in retired_water],
                    'INVENTORY_WATER_CONNECTION_EDIT_OUTSIDE_RETIREMENT')
    # Reuse exact selectors, source housing protections and dependency relocation.
    manifest = {'housing_sha256': housing_fingerprint(rows), 'legacy_groups': {}, 'schedule_files': []}
    changed, modifications, _ = transform({'changes': pack['changes'], 'legacy_group_policy': {}}, manifest, rows, root)
    fields = validate_objects(changed, source_file(parent['engine_schema'], root))
    for device in ('washer', 'dryer', 'dishwasher','ev'):
        name = parent['EB_mapping']['equipment']['ev']['equipment'] if device=='ev' else plan['definition']['programs'][device]['equipment']
        present = any(r[1] == name for r in objects(changed, 'ElectricEquipment'))
        require(present == (device in inv['installed']), 'INVENTORY_DEVICE_PRESENCE_MISMATCH', device)
        if not present:
            names = set(pack['retired_physical_object_names'][device])
            require(not any(any(value in names for value in row[1:]) for row in changed
                            if not row[0].startswith(('Schedule', 'Output'))), 'INVENTORY_RETIRED_DEPENDENCY_REMAINS', device)
    domain = read(source_file(parent['input_domain'], root)); domain['physics_configuration_id'] = pack['id']
    bind_program_domain(plan, domain); timeline = CaseTimeline(case, domain, root=root)
    require(not timeline.support['service_issues'], 'INVENTORY_TASK_SERVICE_UNSUPPORTED')
    for i in range(timeline.steps):
        require(all(t['device'] in inv['installed'] for t in timeline.frame(i)['program_starts']), 'INVENTORY_ABSENT_DEVICE_COMMAND')
    require(case['environment']['physics_configuration_id'] == pack['id'], 'INVENTORY_CASE_CONFIGURATION_ID')
    if 'ev' in absent:
        require(not case['life']['ev_connection_daily'] and case['life']['ev_daily']['traction_kWh']==0
                and case['life']['ev_daily']['required_departure_SOC']==0 and case['controls']['ev_target_SOC']==0
                and not case['controls']['ev_daily_windows'] and not case['controls']['ev_window_overrides'],
                'INVENTORY_ABSENT_EV_CHANNEL_REQUESTED')
    # Inventory retirement must preserve the already installed people and
    # general fixture ports. Validate the parent receipt before deriving a
    # receipt for the otherwise identical, smaller equipment inventory.
    from .joint_case_runtime import life_channels
    source_life = life_channels(parent, case, rows, fields, timeline, root)
    if source_life is not None:
        from .reference_life import inventory_receipt
        life_receipt = inventory_receipt(parent, rows, changed, root=root)
    out = Path(out).resolve(); require(not out.exists(), 'OUTPUT_EXISTS'); out.mkdir(parents=True)
    (out/'in.idf').write_text(render(changed)); shutil.copyfile(source_file(parent['weather'], root), out/'weather.epw')
    if source_life is not None:
        save(out/'LIFE_INSTALLATION.json', life_receipt)
        life_spec = copy.deepcopy(parent)
        life_spec.pop('registered_numerical_overlay', None)
        life_spec['life_installation_receipt'] = ref(out/'LIFE_INSTALLATION.json', root)
        life_channels(life_spec, case, changed, fields, timeline, root)
        save(out/'LIFE_FIXTURE.json', life_spec)
    for dep in parent['dependencies']:
        path = Path(dep['output_path']); require(not path.is_absolute() and '..' not in path.parts, 'INVENTORY_DEPENDENCY_PATH')
        target = out/path; target.parent.mkdir(exist_ok=True); shutil.copyfile(source_file(dep['source'], root), target)
    for name, value in [('PARENT_FIXTURE.json', parent), ('INVENTORY_PACK.json', pack), ('DOMAIN.json', domain),
                        ('CASE.json', case), ('MODIFICATIONS.json', modifications), ('INPUT_SUPPORT.json', timeline.support)]:
        save(out/name, value)
    save(out/'IMPLEMENTATION.json', {p: sha(root/p) for p in (
        'national_idf/reference_inventory.py', 'national_idf/reference_scenarios.py', 'national_idf/assembly.py',
        'national_idf/program_case_runtime.py', 'national_idf/case_commands.py', 'national_idf/program_resources.py',
        'national_idf/reference_life.py', 'national_idf/life_binding.py', 'national_idf/joint_case_runtime.py',
        'national_idf/water_service.py', 'national_idf/water_scope.py')})
    return seal(out, {'schema': 'national_idf.compiled_inventory_reference.v1', 'installed_devices': inv['installed'],
                      'controlled_devices': inv['controlled'], 'formal_admitted': False})


def run(compiled, out, *, root=ROOT):
    from .case_commands import CaseTimeline, CommandClock
    from .program_resources import plan_resources
    from .joint_case_runtime import SixCommands, life_channels
    from .program_case_runtime import WhitegoodsEbCommands
    from .thermal_case_runtime import load_module
    compiled, out = Path(compiled).resolve(), Path(out).resolve(); receipt = verify(compiled)
    require(receipt['schema'] == 'national_idf.compiled_inventory_reference.v1', 'INVENTORY_COMPILED_SCHEMA')
    for path, signature in read(compiled/'IMPLEMENTATION.json').items():
        require(sha(root/path) == signature, 'INVENTORY_IMPLEMENTATION_CHANGED', path)
    spec, case = read(compiled/'PARENT_FIXTURE.json'), read(compiled/'CASE.json')
    parent_rows = parse(source_file(spec['model'], root).read_text()); rows = parse((compiled/'in.idf').read_text())
    fields = Fields(source_file(spec['engine_schema'], root)); plan = plan_resources(parent_rows, spec['engine_schema'], spec['resource_pack'], root=root)
    timeline = CaseTimeline(case, read(compiled/'DOMAIN.json'), root=root)
    life_spec = read(compiled/'LIFE_FIXTURE.json') if (compiled/'LIFE_FIXTURE.json').exists() else spec
    life = life_channels(life_spec, case, rows, fields, timeline, root)
    if life is not None:
        from .water_service import WaterServiceObserver
        water = WaterServiceObserver([row[1] for row in objects(rows, 'WaterUse:Equipment')])
    else: water = None
    for item in spec['official_engine_files']+list(spec['EB_modules'].values()): source_file(item, root)
    suite_module = load_module(source_file(spec['EB_modules']['suite'], root), 'inventory_EB_suite')
    binding_module = load_module(source_file(spec['EB_modules']['binding'], root), 'inventory_EB_binding')
    # Reuse existing EV/native-WH kernels exactly; replace only the selected
    # whitegoods facade, with physically absent devices omitted from the IDF.
    commands = SixCommands(suite_module, timeline, plan, parent_rows, fields, spec, root)
    ev_present='ev' in receipt['installed_devices']
    if not ev_present:
        disabled=suite_module.ApplianceSuite({name:{'present':False} for name in
            ('washer','dryer','dishwasher','water_heater','ev','refrigerator')},timeline.days,[],explicit_only=True)
        commands.suite._ev=disabled._ev;commands.ev=None
    selected = [d for d in ('washer', 'dryer', 'dishwasher') if d in receipt['installed_devices']]
    commands.white = WhitegoodsEbCommands(suite_module.ApplianceSuite, timeline, plan, rows, fields, selected)
    commands.suite._shiftable = commands.white.suite._shiftable
    mapping = copy.deepcopy(spec['EB_mapping']); mapping['equipment'] = {k:v for k,v in mapping['equipment'].items() if k in receipt['installed_devices']}
    binding = binding_module.ApplianceBinding((compiled/'in.idf').read_text(), source_file(spec['engine_schema'], root), commands.suite, mapping)
    engine = next(source_file(item, root).parent for item in spec['official_engine_files'] if Path(item['path']).name == 'energyplus')
    sys.path.insert(0, str(engine)); from pyenergyplus.api import EnergyPlusAPI
    api = EnergyPlusAPI(); state = api.state_manager.new_state(); binding.request_outputs(api.exchange, state)
    if life is not None:
        life.request_outputs(api.exchange, state); water.request_outputs(api.exchange, state)
    require(not out.exists(), 'OUTPUT_EXISTS'); out.mkdir(parents=True)
    clock, trace, handles, current, life_system = CommandClock(timeline), [], {}, [], []
    progress = {'zone_steps': 0, 'system_steps': 0, 'errors': [], 'initialized': False}
    def active(s): return api.exchange.api_data_fully_ready(s) and not api.exchange.warmup_flag(s) and api.exchange.kind_of_sim(s) == 3
    def fail(s): progress['errors'].append(traceback.format_exc()); api.runtime.stop_simulation(s)
    def before(s):
        if not active(s): return
        try:
            if not progress['initialized']:
                binding.initialize(api.exchange, s)
                if life is not None:
                    life.initialize(api.exchange, s); water.initialize(api.exchange, s)
                for device in selected:
                    for name in plan['definition']['programs'][device]['schedules']:
                        h = api.exchange.get_actuator_handle(s, 'Schedule:File', 'Schedule Value', name)
                        require(h >= 0, 'INVENTORY_PROGRAM_ACTUATOR_MISSING', name); handles[name] = h
                progress['initialized'] = True
            frame = clock.take_exchange(api.exchange, s); current[:] = [frame]
            if life is not None: life.write(api.exchange, s, frame)
            values = commands.white.step(frame); powers = {'ev': commands.ev.step(frame)} if ev_present else {}
            for device, channels in values.items():
                electric = plan['definition']['programs'][device]['electric_schedule']
                powers[device] = channels[electric]*binding.equipment[device]['design_W']/1000
                for name, value in channels.items(): api.exchange.set_actuator_value(s, handles[name], value)
            control = frame['control']
            from .eb_water_heater_window import effective_setpoint
            powers['water_heater_setpoint_C'] = effective_setpoint(control)
            binding.write(api.exchange, s, powers, heating_C=control['heating_C'], cooling_C=control['cooling_C'], available=control['hvac_available'])
            trace.append({'frame_index': frame['frame_index'], 'date': frame['date'], 'start_min': frame['start_min'], **control, 'water_heater_effective_setpoint_C':powers['water_heater_setpoint_C'],
                          'EV_connected': frame['ev']['connected'], 'EV_window_open': frame['ev']['charge_window_open'],
                          **{d+'_command_kW': powers[d] for d in [*selected, *(['ev'] if ev_present else [])]}})
            if life is not None:
                trace[-1].update(requested_persons=sum(r['persons'] for r in frame['people'].values()),
                    requested_activity_total_W=sum(r['activity_total_W'] for r in frame['people'].values()),
                    requested_water_L=frame['mixed_water']['requested_volume_L'],
                    requested_water_target_C=frame['mixed_water']['target_C'])
        except Exception: fail(s)
    def system(s):
        if active(s):
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
                progress['system_steps'] += 1
            except Exception: fail(s)
    def after(s):
        if active(s):
            try:
                trace[-1].update(binding.observe(api.exchange, s, current[0]['day_index'])); progress['zone_steps'] += 1
                if life is not None:
                    values = life.observe(api.exchange, s, water=False)
                    trace[-1].update({'native_people_'+key: sum(r[key] for r in values.values())
                        for key in next(iter(values.values()))})
            except Exception: fail(s)
    api.runtime.callback_begin_zone_timestep_before_init_heat_balance(state, before)
    api.runtime.callback_end_system_timestep_after_hvac_reporting(state, system)
    api.runtime.callback_end_zone_timestep_after_zone_reporting(state, after)
    start = time.monotonic()
    try: code = api.runtime.run_energyplus(state, ['-w', str(compiled/'weather.epw'), '-d', str(out/'output'), str(compiled/'in.idf')])
    finally: api.state_manager.delete_state(state)
    if trace:
        with (out/'TRACE.csv').open('w', newline='') as stream:
            writer = csv.DictWriter(stream, fieldnames=trace[0]); writer.writeheader(); writer.writerows(trace)
    if life_system:
        with (out/'LIFE_SYSTEM.csv').open('w', newline='') as stream:
            writer = csv.DictWriter(stream, fieldnames=life_system[0]); writer.writeheader(); writer.writerows(life_system)
    if water is not None: save(out/'WATER_SERVICE.json', water.report())
    result = {'exit_code': code, 'seconds': time.monotonic()-start, 'progress': progress,
              'zone_clock': clock.diagnostics, 'installed_devices': receipt['installed_devices'],
              'EV': commands.ev.report() if ev_present else None,
              'EV_channel_state':'source_reference_present' if ev_present else 'home_charging_component_not_installed;SOC_and_trips_not_simulated',
              'actual_household_vehicle_ownership_inferred':False,
              'whitegoods': commands.white.report(), 'formal_admitted': False,
              'native_people_and_fixture_CASE_channels_executed': life is not None,
              'general_water_gains_synchronized_to_CASE': False if life is not None else None,
              'water_effect_scope': life.water_effect_scope if life is not None else None,
              'native_tank_metered_by_existing_EB_binding': True, 'device_physics_reimplemented': False}
    save(out/'RUNTIME.json', result)
    require(code == 0 and not progress['errors'] and progress['zone_steps'] == timeline.steps, 'INVENTORY_RUNTIME_FAILED')
    return result
