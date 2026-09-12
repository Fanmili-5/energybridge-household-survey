"""Freeze the existing EB appliance binding as a reproducible, separate IDF.

No upstream edits, controller changes, household imputation, or model API calls.
Only the pinned author's date/HVAC preparation functions are executed, using
AST extraction to avoid importing or initializing the planning stack.
"""
from __future__ import annotations

import argparse
import ast
from collections import Counter
from datetime import date, timedelta
import json
from pathlib import Path
import sys
import tempfile

PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT / 'realtime_pilot'))
from common import UPSTREAM, file_hash
from native_assets import BINDING_VERSION, bind_native_appliances, idf_objects
from audit_upstream_appliance_binding import extract_function

MODEL_VERSION = 'eb.tianjin_family_all_appliances.v1'
MODEL_NAME = 'family_all_appliances.idf'
DEFAULT_OUTPUT = PROJECT / 'models/tianjin_family_eb_v1'
START_DATE = date(2007, 7, 1)
SOURCES = {
    'template': 'experiments/models/family_home/family_simple.idf',
    'thermal_reference': 'experiments/models/family_home/original_model.idf',
    'controller': 'experiments/benchmark/family_runner.py',
    'date_preparation': 'energybridge/data/day_ahead.py',
    'hvac_preparation': 'experiments/benchmark/run_persona_json.py',
    'author_construction_report': 'Family_Model/envelope_retrofit_report.md',
    'weather': 'experiments/weather/epw/CHN_TJ_Tianjin.545270_CSWD.epw',
}


def canonical(body):
    return Counter(tuple(v.lower() for v in r) for r in idf_objects(body))


def pretty_binding(row):
    labels = (['Name', 'Schedule Type Limits Name (optional)', 'Hourly Value']
              if row[0] == 'Schedule:Constant' else
              ['Name', 'Zone or ZoneList or Space or SpaceList Name', 'Schedule Name',
               'Design Level Calculation Method', 'Design Level {W}',
               'Watts per Floor Area {W/m2}', 'Watts per Person {W/person}',
               'Fraction Latent', 'Fraction Radiant', 'Fraction Lost',
               'End-Use Subcategory'])
    if len(labels) != len(row) - 1:
        raise ValueError('Unexpected appliance binding schema')
    lines = [row[0] + ',']
    for i, (value, label) in enumerate(zip(row[1:], labels)):
        punctuation = ';' if i == len(labels) - 1 else ','
        lines.append(f'    {value + punctuation:<40} !- {label}')
    return '\n'.join(lines)


def build():
    pin = json.loads((PROJECT / 'UPSTREAM_TRACKED_FILES.json').read_text())
    sources = {}
    for role, relative in SOURCES.items():
        actual = file_hash(UPSTREAM / relative)
        if actual != pin['files'].get(relative):
            raise ValueError('Pinned source changed: ' + relative)
        sources[role] = {'path': relative, 'sha256': actual}
    source = UPSTREAM / SOURCES['template']
    source_body = source.read_text()
    tree = ast.parse((UPSTREAM / SOURCES['controller']).read_text())
    design = next(ast.literal_eval(n.value) for n in tree.body
                  if isinstance(n, ast.Assign) and any(
                      isinstance(t, ast.Name) and t.id == '_APPL_DESIGN_W'
                      for t in n.targets))
    date_ns = {'Path': Path, 'date': date, 'timedelta': timedelta}
    extract_function(UPSTREAM / SOURCES['date_preparation'], '_idf_field', date_ns)
    generate = extract_function(UPSTREAM / SOURCES['date_preparation'],
                                'generate_runperiod_idf', date_ns)
    hvac_ns = {}
    extract_function(UPSTREAM / SOURCES['hvac_preparation'], '_idf_field', hvac_ns)
    inject = extract_function(UPSTREAM / SOURCES['hvac_preparation'],
                              '_enable_hvac_availability_control', hvac_ns)
    with tempfile.TemporaryDirectory() as scratch:
        target = generate(source, Path(scratch), start_date=START_DATE, days=1)
        target.write_text('\n'.join(inject(target.read_text().splitlines())) + '\n')
        prepared = target.read_text()
        binding = bind_native_appliances(target, design)
        if binding['added_objects'] != 8:
            raise ValueError('Expected four new schedule/equipment pairs')
        compact = target.read_text()
        new_rows = idf_objects(compact[len(prepared):])
        body = prepared + '\n! ' + BINDING_VERSION + '\n'
        body += '\n\n'.join(pretty_binding(row) for row in new_rows) + '\n'
        if canonical(body) != canonical(compact):
            raise ValueError('Formatting changed the physical model')
        target.write_text(body)
        # The exported file must still be accepted by the existing runtime binder.
        if bind_native_appliances(target, design)['added_objects'] != 0:
            raise ValueError('Export is not idempotent with runtime preparation')

    # There are exactly two edits to original objects: RunPeriod and the HVAC
    # availability-manager schedule reference. Everything else is append-only.
    before, after = canonical(source_body), canonical(body)
    removed, added = list((before - after).elements()), list((after - before).elements())
    if Counter(row[0] for row in removed) != Counter({'runperiod': 1, 'availabilitymanager:scheduled': 1}):
        raise ValueError('Unexpected modification to original building objects')
    if Counter(row[0] for row in added) != Counter({
            'runperiod': 1, 'availabilitymanager:scheduled': 1,
            'schedule:constant': 5, 'electricequipment': 4}):
        raise ValueError('Unexpected added building objects')
    inventory = idf_objects(body)
    equipment = [r[1] for r in inventory if r[0].lower() == 'electricequipment']
    expected = {'EV_Charger', *(b['equipment'] for b in binding['bindings'].values())}
    if set(equipment) != expected or len(equipment) != len(expected):
        raise ValueError('Duplicate or unexpected electric appliance loads')
    header = (
        f'! {MODEL_VERSION}\n'
        f'! Derived from EnergyBridge {pin["commit"]}; original source preserved.\n'
        '! One weather-file day: July 1 (Sunday, reference calendar 2007).\n'
        '! Use the manifest EPW and the EB Python controller for appliance schedules.\n'
        '! Added appliance power fractions default to zero; standalone EP does not plan tasks.\n'
        '! Thermal fractions inherit original_model.idf; not calibrated to a respondent home.\n\n'
    )
    body = header + body
    import hashlib
    manifest = {
        'model_version': MODEL_VERSION,
        'idf_file': MODEL_NAME,
        'idf_sha256': hashlib.sha256(body.encode()).hexdigest(),
        'energyplus_version': '24.1.0',
        'upstream_repository': 'https://github.com/Agentic-Intelligence-Lab/EnergyBridge',
        'upstream_commit': pin['commit'],
        'sources': sources,
        'builder': {'path': str(Path(__file__).relative_to(PROJECT)),
                    'sha256': file_hash(Path(__file__))},
        'runtime_binding': {'path': 'realtime_pilot/native_assets.py',
                            'sha256': file_hash(PROJECT / 'realtime_pilot/native_assets.py'),
                            'version': BINDING_VERSION},
        'default_run': {'reference_calendar_date': START_DATE.isoformat(), 'days': 1,
                        'weather_type': 'Tianjin CSWD typical weather; not observed 2007 weather',
                        'timestep_per_hour': 6,
                        'household_specific_occupancy': False},
        'preserved': ['building_geometry', 'materials_and_constructions', 'two_thermal_zones',
                      'hvac_system', 'ev_charger', 'water_heater_and_dhw_connections',
                      'original_background_loads_and_schedules', 'eb_controller_and_constraints'],
        'modified_original_objects': [{'type': r[0], 'name': r[1]} for r in removed],
        'added_object_counts': {'Schedule:Constant': 5, 'ElectricEquipment': 4},
        'added_appliance_bindings': binding['bindings'],
        'electric_equipment_names': equipment,
        'scope': {
            'supported_devices': ['hvac', 'ev', 'water_heater', 'washer',
                                  'dishwasher', 'dryer', 'refrigerator'],
            'refrigerator_role': 'non-shiftable base load in the EB controller',
            'task_and_ev_states': 'maintained by original EB Python models',
            'added_ep_physics': 'electrical load and inherited zone heat-gain fractions',
            'detailed_appliance_mechanics_or_dhw_added': False,
            'household_calibrated': False,
            'production_template_switched_by_builder': False,
        },
    }
    return body, manifest


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument('--check', action='store_true', help='Verify reproducibility without writing')
    args = parser.parse_args()
    destination = args.output.resolve()
    if destination == UPSTREAM.resolve() or UPSTREAM.resolve() in destination.parents:
        raise ValueError('Never overwrite pinned upstream files')
    def forbid_network(event, _args):
        if event in ('socket.connect', 'socket.getaddrinfo'):
            raise RuntimeError('Model asset generation does not use the network')
    sys.addaudithook(forbid_network)
    body, manifest = build()
    outputs = {MODEL_NAME: body, 'manifest.json': json.dumps(manifest, ensure_ascii=False, indent=2) + '\n'}
    if args.check:
        for name, text in outputs.items():
            if (destination / name).read_text() != text:
                raise ValueError('Generated asset differs: ' + name)
        print('PASS: IDF and manifest reproduce exactly; pinned source hashes verified.')
    else:
        destination.mkdir(parents=True, exist_ok=True)
        for name, text in outputs.items():
            (destination / name).write_text(text)
        print(json.dumps({'model': str(destination / MODEL_NAME),
                          'sha256': manifest['idf_sha256'], 'paid_api_calls': 0}))


if __name__ == '__main__':
    main()
