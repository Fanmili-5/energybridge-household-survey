#!/usr/bin/env python3
"""Independent saved-source/room-polygon/SQL checks, no extractor imports."""
import hashlib
import json
import math
import re
import sqlite3
from pathlib import Path

OUT = Path(__file__).resolve().parent.parent


def sha(p):
    return hashlib.sha256(p.read_bytes()).hexdigest()


def main():
    n = 0
    def check(value, label):
        nonlocal n
        if not value:
            raise AssertionError(label)
        n += 1
    results = []
    for key in ['HighT', 'HighS', 'Low', 'Th']:
        x = json.loads((OUT / (key + '_Beijing_2018_NATIVE.json')).read_text())
        check(sha(Path(x['source_path'])) == x['source_sha256'], 'source_native_bytes')
        check(len(x['rooms']) == x['table_counts']['ROOM'], 'source_room_inventory')
        check(x['table_counts']['DOOR'] == 0 and not x['ROOM_RELATION_is_door_graph'], 'absent_doors_preserved')
        maximum = 0.0
        for r in x['rooms']:
            co = r['floor_xy_polygon_m']
            area = abs(sum(a[0]*b[1]-a[1]*b[0] for a, b in zip(co, co[1:]+co[:1])))/2
            maximum = max(maximum, abs(area-r['source_area_m2']))
            check(abs(area-r['native_polygon_area_m2']) < 1e-7, 'independent_shoelace_floor_area')
            check(abs(area-r['source_area_m2']) < 1e-6, 'source_floor_area_rounding_diagnostic')
        roomids = [rid for u in x['units'] for rid in u['room_ids']]
        check(len(roomids) == len(set(roomids)), 'inferred_units_not_overlapping_room_membership')
        for u in x['units']:
            check(u['functional_inventory_complete'] and u['opaque_wall_adjacency_connected'], 'function_and_wall_graph_checks')
            check(not u['door_access_verified'] and not u['household_binding_approved'], 'inference_not_binding')
            check(u['whole_dwelling_gross_area_m2'] is None, 'native_room_area_not_census_H6')
            check(u['H7_mapping_scenarios']['living_as_counted_natural_room']-u['H7_mapping_scenarios']['living_as_excluded_hall'] == u['living_spaces'], 'H7_hall_semantic_alternative')
        if key == 'Th':
            check(len(x['units']) == 0 and len(x['storeys']) == 2, 'maisonette_not_flattened')
        results.append({'source': x['source_key'], 'room_count': len(x['rooms']), 'inferred_units': len(x['units']),
                        'max_independent_floor_area_residual_m2': maximum,
                        'middle_plane_balance_faces_outside_0_01m2_design_diagnostic': x['diagnostics']['middle_plane_balance_faces_outside_design_tolerance']})
    folder = OUT / 'conditional_source_unit_witness_v2'
    lock = json.loads((folder / 'INPUT_LOCK.json').read_text())
    check(sha(folder / 'source_unit.idf') == lock['idf_sha256'], 'witness_idf_bytes')
    check(not lock['copied_vertices_modified'] and not lock['constructions_and_materials_modified'], 'source_preservation_declared')
    db = sqlite3.connect(folder / 'run/eplusout.sql')
    data = db.execute("""SELECT r.Value,d.Units,t.Interval FROM ReportData r
      JOIN ReportDataDictionary d USING(ReportDataDictionaryIndex) JOIN Time t USING(TimeIndex)
      JOIN EnvironmentPeriods e USING(EnvironmentPeriodIndex) WHERE t.WarmupFlag=0
      AND e.EnvironmentType=3 AND d.Name='Electricity:Facility' AND d.ReportingFrequency='Zone Timestep'""").fetchall()
    db.close()
    actual = sum(v for v, unit, interval in data)/3.6e6
    check(len(data) == 96 and all(unit == 'J' and interval == 15 for v, unit, interval in data), 'one_day_SQL_meter_domain')
    check(abs(actual-1/3) < 1e-7, 'source_layout_electrical_analytic_energy')
    err = (folder / 'run/eplusout.err').read_text()
    check(not re.search(r'\*\*\s*(Severe|Fatal)\s*\*\*', err, re.I), 'engine_error_markers')
    check('GroundTemperature:BuildingSurface' in err, 'source_ground_warning_retained')
    result = {'pass': True, 'assertions': n, 'sources': results, 'native_rooms': sum(x['room_count'] for x in results),
              'inferred_units': sum(x['inferred_units'] for x in results), 'SQL_fixture_kWh': actual,
              'not_door_or_gross_area_or_thermal_calibration_validation': True,
              'IDFs_bound_to_1000': 0, 'actor_ready': 0, 'collection_release': False, 'training_release': False}
    (OUT / 'VERIFICATION.json').write_text(json.dumps(result, ensure_ascii=False, indent=2)+'\n')
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
