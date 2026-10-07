#!/usr/bin/env python3
"""Keep the original converted unit polygons/functions in a conditional run.

This is an engineering witness. No synthetic household is asserted to live in
Beijing or have this apartment. Neighbor zero-flux is an explicit assumption.
"""
import copy
import hashlib
import json
import re
import sqlite3
import subprocess
from pathlib import Path

HERE = Path(__file__).resolve().parent
OUT = HERE.parent
PROJECT = OUT.parents[4]
SOURCE_IDF = PROJECT / 'artifacts/private_research/dest_batch_300_sources_20260925/HighS_Beijing_2018/HighS_Beijing_2018.idf'
EPW = PROJECT / 'artifacts/private_research/role_weather_300_20260925/CHN_Beijing.Beijing.545110_CSWD.epw'
ENGINE = Path('/Applications/EnergyPlus-24-1-0/energyplus')


def rows(text):
    return [[x.strip() for x in p.split(',')] for p in re.sub(r'!.*', '', text).split(';') if p.strip()]


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def save(path, x):
    path.write_text(json.dumps(x, ensure_ascii=False, indent=2, allow_nan=False) + '\n')


def main():
    folder = OUT / 'conditional_source_unit_witness_v2'
    if folder.exists():
        raise ValueError('new_witness_output_required')
    folder.mkdir()
    native = json.loads((OUT / 'HighS_Beijing_2018_NATIVE.json').read_text())
    unit = next(u for u in native['units'] if u['unit_candidate_id'].endswith('floor1_1'))
    selected = set(unit['room_names'])
    original = rows(SOURCE_IDF.read_text())
    zones = [r for r in original if r[0].lower() == 'zone' and r[1] in selected]
    if len(zones) != len(selected):
        raise ValueError('source_native_names_to_converted_zones_mismatch')
    native_rooms = {r['name']: r for r in native['rooms']}
    for z in zones:
        # This stored conversion serializes area to 0.001m2; half its last
        # decimal is a rounding bound, not an engineering validity threshold.
        if abs(float(z[10]) - native_rooms[z[1]]['source_area_m2']) > .0005001:
            raise ValueError('source_room_to_IDF_zone_area_mismatch')
        if int(z[7]) != 1:
            raise ValueError('unit_zone_contains_unaccounted_multiplier')
    surfaces = [r for r in original if r[0].lower() == 'buildingsurface:detailed' and r[4] in selected]
    names = {r[1] for r in surfaces}
    windows = [r for r in original if r[0].lower() == 'fenestrationsurface:detailed' and r[4] in names]
    if not windows or not surfaces:
        raise ValueError('source_unit_lost_geometry')
    changes = []
    native_surfaces = copy.deepcopy(surfaces)
    smap = {r[1]: r for r in surfaces}
    for s in surfaces:
        if s[6].lower() == 'surface' and (s[7] not in names or smap[s[7]][4] == s[4]):
            changes.append({'surface': s[1], 'original_neighbor_surface': s[7], 'new_boundary': 'Adiabatic',
                            'evidence': 'explicit_zero_flux_neighbor_design; not_observed_apartment_state'})
            s[6:10] = ['Adiabatic', '', 'NoSun', 'NoWind']
    for before, after in zip(native_surfaces, surfaces):
        if before[12:] != after[12:]:
            raise ValueError('source_vertices_changed')
    for s in surfaces:
        if s[6].lower() == 'surface' and (smap[s[7]][7] != s[1] or smap[s[7]][4] not in selected):
            raise ValueError('nonreciprocal_intra_unit_neighbor')
    needed = {r[3] for r in surfaces + windows}
    constructions = {r[1]: r for r in original if r[0].lower() == 'construction'}
    material_types = {'material', 'material:nomass', 'windowmaterial:simpleglazingsystem'}
    mats = {r[1]: r for r in original if r[0].lower() in material_types}
    layers = {name for key in needed for name in constructions[key][2:]}
    materials = [mats[name] for name in sorted(layers)]
    props = materials + [constructions[name] for name in sorted(needed)]
    grounds = [r for r in original if r[0].lower() == 'site:groundtemperature:buildingsurface']
    epw = EPW.read_text().splitlines()[0].split(',')
    kitchen = next(name for name in selected if native_rooms[name]['source_function_code'] == 5)
    header = [['Version', '24.1'], ['Building', 'SourcePolygon_Slab_Beijing_ConditionalUnit', '0', 'Suburbs', '.04', '.4', 'FullExterior', '25', '6'],
              ['Timestep', '4'], ['SimulationControl', 'No', 'No', 'No', 'No', 'Yes'],
              ['RunPeriod', 'OneDay', '7', '1', '2023', '7', '1', '2023', 'Saturday', 'Yes', 'Yes', 'No', 'Yes', 'Yes'],
              ['Site:Location', 'Beijing_CSWD_ConditionalWeather', *epw[6:10]],
              ['GlobalGeometryRules', 'UpperLeftCorner', 'Counterclockwise', 'Relative', 'Relative']]
    equipment = [['ScheduleTypeLimits', 'InputWatts', '0', '', 'Continuous'],
                 ['Schedule:Compact', 'FixtureInput', 'InputWatts', 'Through: 12/31', 'For: AllDays', 'Interpolate: Average',
                  'Until: 10:10', '0', 'Until: 10:30', '1000', 'Until: 24:00', '0'],
                 ['ElectricEquipment', 'ExplicitElectricalFixture', kitchen, 'FixtureInput', 'EquipmentLevel', '1', '', '', '0', '0', '1', 'SourceGeometryWitness'],
                 ['Output:SQLite', 'SimpleAndTabular'], ['Output:Diagnostics', 'DisplayExtraWarnings'],
                 ['Output:Meter', 'Electricity:Facility', 'Timestep'],
                 ['Output:Variable', '*', 'Zone Mean Air Temperature', 'Timestep']]
    content = header + grounds + props + zones + surfaces + windows + equipment
    path = folder / 'source_unit.idf'
    path.write_text('! Conditional source-preserving unit; original cross-unit neighbors made adiabatic.\n'
                    '! No real household, ownership, operator, HVAC or service completion is claimed.\n'
                    + '\n'.join(',\n  '.join(r) + ';' for r in content) + '\n')
    manifest = {'source_native_sha256': native['source_sha256'], 'source_full_idf_sha256': sha(SOURCE_IDF),
        'source_native_json_sha256': sha(OUT / 'HighS_Beijing_2018_NATIVE.json'), 'weather_sha256': sha(EPW),
        'unit': unit, 'selected_zones': sorted(selected), 'neighbor_boundary_changes': changes,
        'copied_vertices_modified': False, 'constructions_and_materials_modified': False,
        'source_zone_area_sum_m2': sum(float(z[10]) for z in zones),
        'source_vertices_are_original_floorplan': True, 'census_H6_area_bridge_validated': False,
        'native_function_to_IDF_zone_area_checked': True, 'inherited_source_people_devices_HVAC': False,
        'stored_conversion_area_rounding_m2': .001, 'source_area_comparison_rounding_bound_m2': .0005001,
        'added_fixture_is_household_owned_appliance': False,
        'meter_scope': 'engineering_unit_fixture_only_not_measured_household',
        'IDFs_bound_to_1000': 0, 'actor_ready': 0, 'collection_release': False, 'training_release': False,
        'idf_sha256': sha(path), 'source_script_sha256': sha(Path(__file__))}
    save(folder / 'INPUT_LOCK.json', manifest)
    result = subprocess.run([str(ENGINE), '-w', str(EPW), '-d', str(folder / 'run'), str(path)],
                            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, timeout=180)
    (folder / 'console.txt').write_text(result.stdout)
    err = (folder / 'run/eplusout.err').read_text() if (folder / 'run/eplusout.err').exists() else ''
    sql = folder / 'run/eplusout.sql'
    data = []
    if sql.exists():
        db = sqlite3.connect(sql)
        data = db.execute("""SELECT r.Value,d.Units,t.Interval FROM ReportData r
          JOIN ReportDataDictionary d USING(ReportDataDictionaryIndex) JOIN Time t USING(TimeIndex)
          JOIN EnvironmentPeriods e USING(EnvironmentPeriodIndex) WHERE t.WarmupFlag=0
          AND e.EnvironmentType=3 AND d.Name='Electricity:Facility' AND d.ReportingFrequency='Zone Timestep'""").fetchall()
        db.close()
    actual = sum(r[0] for r in data)/3.6e6
    severe = len(re.findall(r'\*\*\s*(?:Severe|Fatal)\s*\*\*', err, re.I))
    warnings = len(re.findall(r'\*\*\s*Warning\s*\*\*', err, re.I))
    passed = result.returncode == 0 and severe == 0 and len(data) == 96 and abs(actual-1/3) < 1e-7
    passed = passed and all(unit == 'J' and interval == 15 for _, unit, interval in data)
    report = {'pass': passed, 'exit_code': result.returncode, 'warnings': warnings, 'severe_or_fatal': severe,
        'meter_intervals': len(data), 'fixture_kWh': actual, 'analytic_kWh': 1/3,
        'geometry_and_electrical_witness_only': True, 'door_or_housing_area_or_thermal_calibration_verified': False,
        'source_functional_unit_spaces': len(zones), 'actor_ready': 0, 'IDFs_bound_to_1000': 0}
    save(folder / 'RESULT.json', report)
    print(json.dumps(report, ensure_ascii=False))
    if not passed:
        raise RuntimeError('witness_failed; retain_failure_artifacts_for_review')


if __name__ == '__main__':
    main()
