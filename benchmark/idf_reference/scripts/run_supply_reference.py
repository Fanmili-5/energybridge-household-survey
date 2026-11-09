"""Replay the imported plant in its public host; not a Chinese housing run."""
import argparse
import copy
import datetime as dt
import shutil
import subprocess
import time

from national_idf.common import ROOT, read, require, save
from national_idf.idf import objects, parse, render
from national_idf.program_resources import compile_reference_case, model_signature
from national_idf.program_case_runtime import run_reference_case
from national_idf.source_adapter import equipment_zone
from national_idf.supply_network import apply, closure
from national_idf.weather_mains import apply as apply_mains
from scripts import run_whitegoods_shift as source
from scripts.build_supply_source import OUT, ref
from scripts.build_supply_candidate import ID

METERS = ['InteriorLights', 'InteriorEquipment', 'Heating', 'Cooling', 'Fans', 'WaterSystems', 'Pumps']
PREFIX = 'EB_WATER_'


def prepare(step, shifted):
    source.OUT = OUT / 'native'; source.OUT.mkdir(exist_ok=True)
    source.ORIGIN = OUT / 'source_model/run'
    source.CHANNELS = {'washer': ('clothes_washer', 'hot_water_clothes_washer'),
        'dishwasher': ('dishwasher', 'hot_water_dishwasher'), 'dryer': ('clothes_dryer', 'clothes_dryer')}
    source.SHIFTS = {'baseline': {'washer': 0, 'dryer': 0, 'dishwasher': 0},
        'both_shift': {'washer': 3, 'dryer': 3, 'dishwasher': 5}}
    folder, engine, fields, rows, _ = source.prepare('both_shift' if shifted else 'baseline', step, 'native')
    schema = read(engine / 'Energy+.schema.epJSON')
    pack = read(ROOT / f'configs/installation_packs/{ID}.json')
    original = parse((source.ORIGIN / 'in.idf').read_text())
    picked = closure(original, schema, pack['source_loop'], pack['source_auxiliary_equipment'])
    # Shared schedules remain in the source host. Only system/auxiliary objects
    # are retired; all imported schedules are independently namespaced.
    removed = [original[i] for i in picked if not original[i][0].startswith('Schedule')]
    rows = [row for row in rows if row not in removed]
    zone = equipment_zone(rows, next(row[2] for row in objects(rows, 'ElectricEquipment') if row[1] == 'clothes washer'), fields)
    pack.update(id=f'source_host_supply_{step}min', installation_zone=zone)
    path = folder / 'SUPPLY_PACK.json'; save(path, pack)
    rows, receipt, dependencies = apply(rows, ref(path), ref(engine / 'Energy+.schema.epJSON'))
    save(folder / 'SUPPLY_NETWORK.json', receipt)
    # Native CSV controls are an explicit test input. No source coefficient,
    # pipe, water-use or tank field is fitted to the run.
    for row in objects(rows, 'Schedule:File'): row[3] = 'in.schedules.csv'
    rows, mains = apply_mains(rows, ref(ROOT / 'configs/mains_boundaries/tengchong-TMYx-2009-2023_correlation_20261031.json'))
    save(folder / 'MAINS_BINDING.json', mains)
    # Old reporting keys are retired together with the old network.
    rows = [row for row in rows if not (row[0] == 'Output:Variable' and
        (row[2].startswith('Water Use ') or row[1] == 'water heater'))]
    reports = [('Environment', 'Site Mains Water Temperature'),
        (PREFIX+'water heater', 'Water Heater Electricity Energy'),
        (PREFIX+'water heater', 'Water Heater Off Cycle Parasitic Electricity Energy'),
        (PREFIX+'water heater', 'Water Heater On Cycle Parasitic Electricity Energy'),
        (PREFIX+'water heater', 'Water Heater Tank Temperature'),
        ('*', 'Other Equipment Electricity Energy'), ('*', 'Electric Equipment Electricity Energy')]
    for name in ('dhw fixtures', 'dhw distribution waste', 'clothes washer', 'dishwasher'):
        reports += [(PREFIX+name, variable) for variable in source.WATER]
    reports += [(PREFIX+'Water Use Connections 1', 'Water Use Connections '+variable)
        for variable in ('Hot Water Volume', 'Cold Water Volume', 'Total Volume')]
    reports += [(PREFIX+name, 'Schedule Value') for name in ('hot_water_clothes_washer', 'hot_water_dishwasher')]
    for key, variable in reports:
        row = ['Output:Variable', key, variable, 'Timestep']
        if row not in rows: rows.append(row)
    rows += [['Output:Meter', name+':Electricity', 'Timestep'] for name in METERS]
    (folder / 'in.idf').write_text(render(rows))
    save(folder / 'TRANSFORMATION.json', {'removed_system_objects': removed,
        'retained_shared_schedules': [original[i] for i in picked if original[i][0].startswith('Schedule')],
        'supply_package': ref(path), 'relocated_schedules': 'test-controlled in.schedules.csv',
        'source_host_not_China': True, 'local_inlet_is_model_counterfactual_not_measured': True,
        'numerical_acceptance_granted': False, 'formal_admitted': False})
    start = time.monotonic()
    weather = ROOT / 'work/p1_hpxml_004ca3ce/weather/USA_CO_Denver.Intl.AP.725650_TMY3.epw'
    with (folder / 'ENGINE.log').open('w') as stream:
        result = subprocess.run([str(engine / 'energyplus'), '-w', str(weather), '-d', str(folder / 'output'),
            str(folder / 'in.idf')], stdout=stream, stderr=subprocess.STDOUT)
    save(folder / 'RUNTIME.json', {'exit_code': result.returncode, 'wall_seconds': time.monotonic()-start,
        'model': ref(folder / 'in.idf'), 'CSV': ref(folder / 'in.schedules.csv'), 'engine': ref(engine / 'energyplus'),
        'outdoor_weather': ref(weather), 'implementation': ref(ROOT / 'scripts/run_supply_reference.py'),
        'formal_admitted': False, 'family_or_AB_changed': False, 'source_host_not_China': True})
    require(result.returncode == 0, 'SUPPLY_NATIVE_RUN_FAILED', str(folder))
    print(folder.name, 'complete')


def build_case(step):
    native = OUT / f'native/native_baseline_{step}min'
    rows = parse((native / 'in.idf').read_text())
    folder = OUT / f'reference_{step}min'; folder.mkdir()
    profiles, definitions = {}, {}
    for device, names in {'washer': ('clothes_washer', PREFIX+'hot_water_clothes_washer'),
        'dryer': ('clothes_dryer',), 'dishwasher': ('dishwasher', PREFIX+'hot_water_dishwasher')}.items():
        values = {name: [row[4] for row in source.time_series(native / 'output/eplusout.sql', 'Schedule Value', name)] for name in names}
        require(all(len(v) == 10080//step for v in values.values()), 'SUPPLY_SOURCE_PROFILE_INCOMPLETE')
        support = [i for i in range(10080//step) if any(v[i] > 0 for v in values.values())]
        first, last = min(support), max(support)+1
        key, version = f'hpxml_004ca3ce_{device}_stratified_condensing', 'published_reference.v1'
        profiles[device] = {'model_key': key, 'version': version, 'duration_min': (last-first)*step,
            'source_start_elapsed_min': first*step, 'channels': {name: data[first:last] for name, data in values.items()}}
        definitions[device] = {'model_key': key, 'version': version,
            'equipment': 'clothes '+device if device != 'dishwasher' else device,
            'electric_schedule': names[0], 'schedules': list(names)}
    parent = ROOT / f'reports/eb_whitegoods_case_20261031/fixtures/all_{step}min'
    fixture = copy.deepcopy(read(parent / 'FIXTURE.json'))
    profile_path = folder / 'PROFILE.json'; resource_path = folder / 'RESOURCE_PACK.json'
    save(profile_path, {'schema': 'national_idf.program_resource_profile.v1', 'step_min': step,
        'programs': profiles, 'native_interpreted_SQL': ref(native / 'output/eplusout.sql')})
    save(resource_path, {'schema': 'national_idf.program_resource_pack.v1', 'id': f'imported_supply_{step}min',
        'service_unit': 'published_source_resource_window', 'programs': definitions,
        'profiles': {str(step): ref(profile_path)}, 'engine_schema': fixture['engine_schema'],
        'binding_model_signature': model_signature(rows), 'source_evidence': [ref(native / 'SUPPLY_PACK.json'),
            ref(native / 'SUPPLY_NETWORK.json'), ref(OUT / 'SOURCE_RECEIPT.json')], 'formal_admitted': False})
    identifier = f'unregistered-imported-supply-{step}min'
    case = read(parent / 'CASE.json'); case.update(case_id=identifier)
    case['environment']['physics_configuration_id'] = identifier; case['controls']['program_start_overrides'] = {}
    for device, program in profiles.items():
        elapsed = program['source_start_elapsed_min']+(300 if device == 'dishwasher' else 180)
        day, minute = divmod(elapsed, 1440); date = (dt.date(2007, 1, 15)+dt.timedelta(days=day)).isoformat()
        case['controls']['program_start_overrides'].setdefault(date, {})[device] = [minute]
    save(folder / 'CASE.json', case)
    domain = read(ROOT / fixture['input_domain']['path']); domain['physics_configuration_id'] = identifier
    for device, program in profiles.items():
        domain['programs'][device].update({key: program[key] for key in ('model_key', 'version', 'duration_min')})
        domain['programs'][device]['resource_pack'] = ref(resource_path)
    save(folder / 'DOMAIN.json', domain)
    fixture.update(id=identifier, model=ref(native / 'in.idf'), input_domain=ref(folder / 'DOMAIN.json'),
        resource_pack=ref(resource_path), dependencies=[{'output_path': 'in.schedules.csv', 'source': ref(native / 'in.schedules.csv')}])
    for key in ('installation_pack', 'whole_plug_load_replacement'): fixture.pop(key, None)
    save(folder / 'FIXTURE.json', fixture)
    compile_reference_case(ref(folder / 'FIXTURE.json'), case, folder / 'compiled', mode='engineering_reference')
    run_reference_case(folder / 'compiled', folder / 'eb_run', mode='engineering_reference')
    print(step, 'min imported water CASE/EB complete')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(); parser.add_argument('--step', type=int, choices=(1, 2, 5), required=True)
    parser.add_argument('--shifted', action='store_true'); parser.add_argument('--case', action='store_true')
    args = parser.parse_args()
    if args.case: build_case(args.step)
    else: prepare(args.step, args.shifted)
