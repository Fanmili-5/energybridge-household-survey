"""Public source host: full plant + six EB controls and independent native CSV."""
import argparse
import copy
import csv
import datetime as dt
import shutil
import subprocess
import time

from national_idf.case_commands import CaseTimeline
from national_idf.common import ROOT, read, require, save
from national_idf.idf import objects, parse, render
from national_idf.joint_installation import apply as install_joint
from national_idf.program_resources import compile_reference_case, model_signature
from national_idf.program_case_runtime import run_reference_case
from national_idf.source_adapter import selector
from national_idf.supply_network import apply as install_water, closure
from national_idf.weather_mains import apply as apply_mains
from scripts import run_whitegoods_shift as source
from scripts.build_six_joint_source import OUT, ref
from scripts.run_supply_reference import METERS, PREFIX

EV = 'EB outdoor reference EV'


def engine_run(folder, rows):
    engine, _ = source.engine_and_fields(); (folder / 'in.idf').write_text(render(rows))
    weather = ROOT / 'work/p1_hpxml_004ca3ce/weather/USA_CO_Denver.Intl.AP.725650_TMY3.epw'
    start = time.monotonic()
    with (folder / 'ENGINE.log').open('w') as log:
        result = subprocess.run([str(engine / 'energyplus'), '-w', str(weather), '-d', str(folder / 'output'), str(folder / 'in.idf')], stdout=log, stderr=subprocess.STDOUT)
    save(folder / 'RUNTIME.json', {'exit_code': result.returncode, 'seconds': time.monotonic()-start,
        'model': ref(folder / 'in.idf'), 'weather': ref(weather), 'engine': ref(engine / 'energyplus'),
        'source_host_not_China': True, 'formal_admitted': False, 'implementation': ref(ROOT / 'scripts/run_six_joint.py')})
    require(result.returncode == 0, 'SIX_NATIVE_RUN_FAILED', str(folder))


def prepare(step):
    source.OUT = OUT / 'profiles'; source.OUT.mkdir(exist_ok=True); source.ORIGIN = OUT / 'source_model/run'
    source.CHANNELS = {'washer': ('clothes_washer', 'hot_water_clothes_washer'),
        'dishwasher': ('dishwasher', 'hot_water_dishwasher'), 'dryer': ('clothes_dryer', 'clothes_dryer')}
    source.SHIFTS = {'baseline': {'washer': 0, 'dryer': 0, 'dishwasher': 0}}
    folder, engine, fields, rows, _ = source.prepare('baseline', step, 'native')
    (folder / 'PRE_INSTALLATION.idf').write_text(render(rows))
    schema = read(engine / 'Energy+.schema.epJSON'); original = parse((source.ORIGIN / 'in.idf').read_text())
    pack = read(ROOT / 'configs/installation_packs/tengchong_a1_condensing_stratified_supply_20261031.json')
    picked = closure(original, schema, 'dhw loop', pack['source_auxiliary_equipment'])
    pack.update(source_model=ref(source.ORIGIN / 'in.idf'), source_objects=[selector(original, i) for i in picked], installation_zone='conditioned space')
    water_path = folder / 'WATER_PACK.json'; save(water_path, pack)
    removed = [original[i] for i in picked if not original[i][0].startswith('Schedule')]
    rows = [row for row in rows if row not in removed]
    rows, receipt, _ = install_water(rows, ref(water_path), ref(engine / 'Energy+.schema.epJSON'))
    save(folder / 'WATER_INSTALLATION.json', receipt)
    for row in objects(rows, 'Schedule:File'): row[3] = 'in.schedules.csv'
    rows, receipt = apply_mains(rows, ref(ROOT / 'configs/mains_boundaries/tengchong-TMYx-2009-2023_correlation_20261031.json'))
    save(folder / 'MAINS_BINDING.json', receipt)
    ev_template = ROOT / 'reports/eb_ev_reference_20261030/5min/in.idf'; ev_rows = parse(ev_template.read_text())
    index = next(i for i, row in enumerate(ev_rows) if row[:2] == ['ElectricEquipment', EV])
    schedule_name = fields.get(ev_rows[index], 'schedule_name'); schedule = next(i for i, row in enumerate(ev_rows) if row[:2] == ['Schedule:Constant', schedule_name])
    joint = {'schema': 'national_idf.EB_hvac_EV_installation.v1', 'installation_zone': 'conditioned space',
        'expected_source_context_signature': model_signature(rows),
        'EV_reference': ref(ROOT / 'configs/component_models/eb_ev_ochre_0bf05035.json'),
        'EV_template_model': ref(ev_template), 'EV_template_equipment': selector(ev_rows, index), 'EV_template_schedule': selector(ev_rows, schedule),
        'HVAC_availability_overlay': {'manager': 'mshp airloop Availability Manager', 'unitary': 'mshp unitary system', 'schedule_name': 'EB source HVAC availability'},
        'evidence': [ref(OUT / 'SOURCE_RECEIPT.json'), ref(ROOT / 'reports/eb_hvac_runtime_20261030/VALIDATION.json')], 'formal_admitted': False}
    path = folder / 'HVAC_EV_PACK.json'; save(path, joint)
    rows, receipt = install_joint(rows, ref(path), ref(engine / 'Energy+.schema.epJSON')); require(receipt['ready'], 'SOURCE_JOINT_PACK_NOT_READY')
    save(folder / 'JOINT_INSTALLATION.json', receipt)
    rows = [row for row in rows if not (row[0] == 'Output:Variable' and (row[2].startswith('Water Use ') or row[1] == 'water heater'
        or row[1] in ('hot_water_clothes_washer', 'hot_water_dishwasher')))]
    reports = [(PREFIX+'water heater', name) for name in ('Water Heater Electricity Energy', 'Water Heater Off Cycle Parasitic Electricity Energy',
        'Water Heater On Cycle Parasitic Electricity Energy', 'Water Heater Tank Temperature')]
    reports += [('*', 'Other Equipment Electricity Energy'), ('*', 'Electric Equipment Electricity Energy')]
    reports += [(EV, name) for name in source.ELECTRIC[1:]]
    reports += [(PREFIX+name, variable) for name in ('dhw fixtures', 'dhw distribution waste', 'clothes washer', 'dishwasher') for variable in source.WATER]
    reports += [(PREFIX+'Water Use Connections 1', 'Water Use Connections '+name) for name in ('Hot Water Volume', 'Cold Water Volume', 'Total Volume')]
    control_names = ['heating setpoint', 'cooling setpoint', 'EB source HVAC availability', PREFIX+'water heater setpoint', schedule_name,
        PREFIX+'hot_water_clothes_washer', PREFIX+'hot_water_dishwasher']
    reports += [(name, 'Schedule Value') for name in control_names]
    reports += [('mshp htg coil', 'Heating Coil Electricity Energy'), ('mshp clg coil', 'Cooling Coil Electricity Energy'), ('mshp supply fan', 'Fan Electricity Energy')]
    for key, variable in reports:
        row = ['Output:Variable', key, variable, 'Timestep']
        if row not in rows: rows.append(row)
    rows += [['Output:Meter', name+':Electricity', 'Timestep'] for name in METERS]
    inputs = read(folder / 'INPUTS.json'); inputs.update(pre_installation_model=ref(folder / 'PRE_INSTALLATION.idf'), physics_objects_unchanged=False)
    save(folder / 'INPUTS.json', inputs)
    engine_run(folder, rows)
    inputs['IDF'] = ref(folder / 'in.idf'); save(folder / 'INPUTS.json', inputs)
    print(step, 'min six-device source profiles available')


def build_case(step, season):
    native = OUT / f'profiles/native_baseline_{step}min'; engine, fields = source.engine_and_fields()
    folder = OUT / f'{season}_{step}min'; folder.mkdir()
    rows = parse((native / 'in.idf').read_text()); begin = dt.date(2007, 1 if season == 'winter' else 7, 15)
    period = objects(rows, 'RunPeriod')[0]
    for key, value in {'begin_month': begin.month, 'end_month': begin.month, 'day_of_week_for_start_day': begin.strftime('%A')}.items(): fields.set(period, key, value)
    model = folder / 'installed.idf'; model.write_text(render(rows))
    profiles, definitions = {}, {}
    for device, names in {'washer': ('clothes_washer', PREFIX+'hot_water_clothes_washer'), 'dryer': ('clothes_dryer',), 'dishwasher': ('dishwasher', PREFIX+'hot_water_dishwasher')}.items():
        values = {name: [r[4] for r in source.time_series(native / 'output/eplusout.sql', 'Schedule Value', name)] for name in names}
        support = [i for i in range(10080//step) if any(v[i] > 0 for v in values.values())]; first, last = min(support), max(support)+1
        key, version = f'hpxml_004ca3ce_joint_{device}', 'source_reference.v1'
        profiles[device] = {'model_key': key, 'version': version, 'duration_min': (last-first)*step, 'source_start_elapsed_min': first*step,
            'channels': {name: data[first:last] for name, data in values.items()}}
        definitions[device] = {'model_key': key, 'version': version, 'equipment': 'dishwasher' if device == 'dishwasher' else 'clothes '+device,
            'electric_schedule': names[0], 'schedules': list(names)}
    parent = ROOT / f'reports/eb_whitegoods_case_20261031/fixtures/all_{step}min'; fixture = read(parent / 'FIXTURE.json')
    from national_idf.native_build_runtime import bind_fixture
    original_fixture = copy.deepcopy(fixture)
    fixture = bind_fixture(fixture)
    save(folder / 'BUILD_RUNTIME_BINDING.json', {'source_fixture': ref(parent / 'FIXTURE.json'),
         'same_IDF_and_portable_schema': fixture['model'] == original_fixture['model'] and fixture['engine_schema'] == original_fixture['engine_schema'],
         'runtime_artifacts_changed': fixture['official_engine_files'] != original_fixture['official_engine_files'],
         'active_engine': ref(engine / 'energyplus'), 'physical_parameters_changed': False})
    profile_path, resource_path = folder / 'PROFILE.json', folder / 'RESOURCE_PACK.json'
    save(profile_path, {'schema': 'national_idf.program_resource_profile.v1', 'step_min': step, 'programs': profiles, 'native_interpreted_SQL': ref(native / 'output/eplusout.sql')})
    save(resource_path, {'schema': 'national_idf.program_resource_pack.v1', 'id': folder.name, 'service_unit': 'published_source_resource_window',
        'programs': definitions, 'profiles': {str(step): ref(profile_path)}, 'engine_schema': fixture['engine_schema'],
        'binding_model_signature': model_signature(rows), 'source_evidence': [ref(OUT / 'SOURCE_RECEIPT.json'), ref(native / 'JOINT_INSTALLATION.json')], 'formal_admitted': False})
    identifier = 'unregistered-six-joint-'+folder.name; case = read(parent / 'CASE.json')
    case.update(case_id=identifier, run={'start_date': begin.isoformat(), 'end_date': (begin+dt.timedelta(days=6)).isoformat()})
    case['environment']['physics_configuration_id'] = identifier; c = case['controls']; c['program_start_overrides'] = {}
    for device, program in profiles.items():
        elapsed = program['source_start_elapsed_min']+(300 if device == 'dishwasher' else 180); day, minute = divmod(elapsed, 1440)
        c['program_start_overrides'].setdefault((begin+dt.timedelta(days=day)).isoformat(), {})[device] = [minute]
    tank_target = float(fields.get(next(r for r in objects(rows, 'Schedule:Constant') if r[1] == PREFIX+'water heater setpoint'), 'hourly_value'))
    c.update(tank_target_C=tank_target, ev_target_SOC=.8,
        ev_daily_windows=[{'start_min': 0, 'end_min': 120}, {'start_min': 1080, 'end_min': 1440}],
        ev_window_overrides={(begin+dt.timedelta(days=2)).isoformat(): []}, daily_overrides=[],
        dated_overrides=[{'date': (begin+dt.timedelta(days=1)).isoformat(), 'field': 'hvac_available', 'start_min': 780, 'end_min': 960, 'value': False},
            {'date': (begin+dt.timedelta(days=2)).isoformat(), 'field': 'heating_C' if season == 'winter' else 'cooling_C',
             'start_min': 780, 'end_min': 960, 'value': c['heating_C']-2 if season == 'winter' else c['cooling_C']+2},
            {'date': (begin+dt.timedelta(days=1)).isoformat(), 'field': 'tank_target_C', 'start_min': 720, 'end_min': 900, 'value': tank_target+3}],
        basis='Fixed engineering six-device commands, not household generation or A/B')
    case['life'].update(ev_initial_SOC=.3, ev_connection_daily=[{'start_min': 0, 'end_min': 480}, {'start_min': 1080, 'end_min': 1440}],
        ev_daily={'departure_min': 480, 'return_min': 1080, 'traction_kWh': 12, 'required_departure_SOC': .8})
    save(folder / 'CASE.json', case)
    domain = read(ROOT / fixture['input_domain']['path']); domain.update(physics_configuration_id=identifier, run_period=case['run'])
    domain['bounds'].update(heating_C=[c['heating_C']-2, c['heating_C']], cooling_C=[c['cooling_C'], c['cooling_C']+2], tank_target_C=[tank_target, tank_target+3], ev_target_SOC=[0, 1])
    for device, program in profiles.items():
        domain['programs'][device].update({key: program[key] for key in ('model_key', 'version', 'duration_min')}); domain['programs'][device]['resource_pack'] = ref(resource_path)
    save(folder / 'DOMAIN.json', domain)
    mapping = fixture['EB_mapping']; mapping['equipment']['ev'] = {'equipment': EV}; mapping['water_heater'] = PREFIX+'water heater'
    mapping['hvac']['availability'] = 'EB source HVAC availability'
    fixture.update(schema='national_idf.six_reference_fixture.v1', id=identifier, model=ref(model), input_domain=ref(folder / 'DOMAIN.json'),
        resource_pack=ref(resource_path), installation_receipt=ref(native / 'JOINT_INSTALLATION.json'),
        EV_reference=ref(ROOT / 'configs/component_models/eb_ev_ochre_0bf05035.json'), EV_reserve_SOC=0,
        dependencies=[{'output_path': 'in.schedules.csv', 'source': ref(native / 'in.schedules.csv')}])
    save(folder / 'FIXTURE.json', fixture)
    compile_reference_case(ref(folder / 'FIXTURE.json'), case, folder / 'compiled', mode='engineering_reference')
    run_reference_case(folder / 'compiled', folder / 'eb_run', mode='engineering_reference')
    print(folder.name, 'all six EB controls executed')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(); parser.add_argument('--step', type=int, choices=(1, 2, 5), required=True)
    parser.add_argument('--case', action='store_true'); parser.add_argument('--season', choices=('winter', 'summer'), default='winter'); args = parser.parse_args()
    if args.case: build_case(args.step, args.season)
    else: prepare(args.step)
