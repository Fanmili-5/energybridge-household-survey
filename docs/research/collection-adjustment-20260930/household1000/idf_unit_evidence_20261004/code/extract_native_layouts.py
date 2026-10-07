#!/usr/bin/env python3
"""Read source geometry/function/boundaries, instead of rebuilding rectangles.

Requires access_parser_c commit 93571d1 and isolated construct/tabulate/Shapely.
Numeric polygon checks do not validate Access string decoding, apartment IDs,
door access, thermal calibration, or population weights.
"""
import collections
import hashlib
import html
import json
import math
from pathlib import Path

from access_parser_c import AccessParser
from scipy.optimize import linear_sum_assignment
from shapely.geometry import Polygon
from shapely.ops import unary_union

HERE = Path(__file__).resolve().parent
OUT = HERE.parent
PROJECT = OUT.parents[4]
PARTITION = {'upper_left': [1, 3, 11, 12, 15, 20, 33],
             'upper_right': [5, 7, 8, 9, 28, 29, 35],
             'lower_left': [16, 17, 18, 19, 32],
             'lower_middle': [22, 23, 25, 26, 27],
             'lower_right': [10, 13, 14, 30, 31]}
SOURCES = {
    'HighT_Beijing_2018': PROJECT / 'artifacts/private_research/idf_evidence_20261003/HighT_Beijing_2018/HighT_Beijing_2018.accdb',
    'Th_Beijing_2018': PROJECT / 'artifacts/private_research/idf_evidence_20261004/Th_Beijing_2018/Th_Beijing_2018.accdb',
    **{f'{prefix}_Beijing_2018': PROJECT / f'artifacts/private_research/dest_batch_300_sources_20260925/{prefix}_Beijing_2018/{prefix}_Beijing_2018.accdb' for prefix in ['HighS', 'Low']}}


def save(p, value):
    p.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + '\n')


def rows(table):
    if len({len(v) for v in table.values()}) > 1:
        raise ValueError('unequal_source_column_lengths')
    return [dict(zip(table, v)) for v in zip(*table.values())]


def area3d(coords):
    normal = [0.0, 0.0, 0.0]
    for a, b in zip(coords, coords[1:] + coords[:1]):
        normal[0] += a[1] * b[2] - a[2] * b[1]
        normal[1] += a[2] * b[0] - a[0] * b[2]
        normal[2] += a[0] * b[1] - a[1] * b[0]
    return math.sqrt(sum(x*x for x in normal)) / 2


def transfer(ref, selected, shapes):
    mapping, maxdist = {}, 0.0
    for kind in {r['TYPE'] for r in ref.values()}:
        a = sorted(rid for rid in ref if ref[rid]['TYPE'] == kind)
        b = sorted(rid for rid in selected if selected[rid]['TYPE'] == kind)
        if len(a) != len(b):
            raise ValueError('cannot_transfer_partition_with_different_room_function_inventory')
        costs = [[sum((x-y)**2 for x, y in zip(shapes[xid].bounds, shapes[yid].bounds)) for yid in b] for xid in a]
        ai, bi = linear_sum_assignment(costs)
        for i, j in zip(ai, bi):
            maxdist = max(maxdist, math.sqrt(costs[i][j]))
            mapping[b[j]] = a[i]
    if maxdist > .05:
        raise ValueError('source_geometry_partition_transfer_more_than_0_05m_design_diagnostic')
    return mapping, maxdist


def extract(key, path):
    db = AccessParser(str(path))
    names = ['ROOM', 'STOREY', 'ROOM_GROUP', 'ROOM_TYPE_DATA', 'DOOR', 'ROOM_RELATION', 'SURFACE',
             'MAIN_ENCLOSURE', 'WINDOW', 'GEOMETRY', 'PLANE', 'POINT', 'LOOP_POINT']
    tables = {name: rows(db.parse_table(name)) for name in names}
    rooms = {r['ID']: r for r in tables['ROOM']}
    surfaces = {r['SURFACE_ID']: r for r in tables['SURFACE']}
    geometries = {r['GEOMETRY_ID']: r for r in tables['GEOMETRY']}
    planes = {r['PLANE_ID']: r for r in tables['PLANE']}
    points = {r['POINT_ID']: r for r in tables['POINT']}
    loops = collections.defaultdict(list)
    for r in tables['LOOP_POINT']:
        loops[r['LOOP_ID']].append(r)
    def coords(surface):
        loop = geometries[surface['GEOMETRY']]['BOUNDARY_LOOP_ID']
        return [[points[r['POINT']][axis] for axis in ['X', 'Y', 'Z']]
                for r in sorted(loops[loop], key=lambda r: r['POINT_NO'])]
    def middle_coords(enclosure):
        geometry = planes[enclosure['MIDDLE_PLANE']]['GEOMETRY']
        loop = geometries[geometry]['BOUNDARY_LOOP_ID']
        return [[points[r['POINT']][axis] for axis in ['X', 'Y', 'Z']]
                for r in sorted(loops[loop], key=lambda r: r['POINT_NO'])]
    functions = {r['ID']: r['NAME'] for r in tables['ROOM_TYPE_DATA']}
    openings = collections.Counter()
    window_output = []
    for w in tables['WINDOW']:
        for side in ['SIDE1', 'SIDE2']:
            s = surfaces[w[side]]
            if s['OF_ROOM'] in rooms:
                openings[(w['OF_ENCLOSURE'], s['OF_ROOM'])] += s['AREA']
                c = coords(s)
                window_output.append({'source_window_id': w['ID'], 'source_enclosure_id': w['OF_ENCLOSURE'],
                                      'room_id': s['OF_ROOM'], 'source_area_m2': s['AREA'],
                                      'polygon_area_m2': area3d(c), 'vertices_m': c})
    faces, bottoms = [], collections.defaultdict(list)
    for e in tables['MAIN_ENCLOSURE']:
        for side, peer in [('SIDE1', 'SIDE2'), ('SIDE2', 'SIDE1')]:
            s, other = surfaces[e[side]], surfaces[e[peer]]
            if s['OF_ROOM'] not in rooms:
                continue
            c = coords(s)
            face = {'source_enclosure_id': e['ID'], 'source_side_id': s['SURFACE_ID'], 'room_id': s['OF_ROOM'],
                    'peer_room_id': other['OF_ROOM'] if other['OF_ROOM'] in rooms else None,
                    'peer_pseudo_id': other['OF_ROOM'] if other['OF_ROOM'] not in rooms else None,
                    'kind_code': e['KIND'], 'construction_source_id': e['CONSTRUCTION'],
                    'source_area_m2': s['AREA'], 'polygon_area_m2': area3d(c),
                    'source_opening_area_m2': openings[(e['ID'], s['OF_ROOM'])],
                    'middle_plane_polygon_area_m2': area3d(middle_coords(e)),
                    'source_skin_and_middle_plane_are_different_geometric_scopes': True,
                    'source_azimuth': s['AZIMUTH'], 'source_tilt': s['TILT'], 'vertices_m': c}
            faces.append(face)
            if e['KIND'] in [3, 4, 5]:
                bottoms[s['OF_ROOM']].append(face)
    shapes, polygons = {}, {}
    for rid in rooms:
        candidates = bottoms[rid]
        zmin = min(sum(c[2] for c in f['vertices_m']) / len(f['vertices_m']) for f in candidates)
        selected = [f for f in candidates if abs(sum(c[2] for c in f['vertices_m']) / len(f['vertices_m']) - zmin) < .001]
        parts = [Polygon([(c[0], c[1]) for c in f['vertices_m']]) for f in selected]
        if any(not p.is_valid for p in parts):
            raise ValueError('invalid_native_floor_polygon')
        shape = unary_union(parts)
        if shape.geom_type != 'Polygon':
            raise ValueError('disconnected_native_room_footprint_requires_review')
        shapes[rid] = shape
        polygons[rid] = [list(x) for x in shape.exterior.coords[:-1]]
    floors = sorted(tables['STOREY'], key=lambda r: r['NO'])
    by_floor = [{rid: r for rid, r in rooms.items() if r['OF_STOREY'] == f['ID']} for f in floors]
    group = {}
    inference, displacement = None, []
    if key.startswith('HighT'):
        ref = by_floor[0]
        byname = {r['NAME']: rid for rid, r in ref.items()}
        labels = {byname[f'1-N-{suffix}']: label for label, suffixes in PARTITION.items() for suffix in suffixes}
        common = [rid for rid in ref if ref[rid]['TYPE'] == 17]
        if len(common) != 1 or set(labels) | set(common) != set(ref):
            raise ValueError('tower_reference_partition_inventory_changed')
        labels[common[0]] = 'unassigned_type17'
        for floor, selected in zip(floors, by_floor):
            mapping, delta = transfer(ref, selected, shapes)
            displacement.append(delta)
            group.update({rid: f"floor{floor['NO']}_{labels[source]}" for rid, source in mapping.items()})
        inference = 'historical_manually_traced_tower_partition_transferred_by_room_function_and_native_polygon_bbox; not_official_dwelling_ID'
    elif key.startswith(('HighS', 'Low')):
        for floor, selected in zip(floors, by_floor):
            centers = sorted(r['X'] for r in selected.values() if r['TYPE'] == 3)
            if len(centers) != 4:
                raise ValueError('four_living_room_anchors_required')
            for rid, r in selected.items():
                label = 'unassigned_type17' if r['TYPE'] == 17 else str(min(range(4), key=lambda i: abs(r['X'] - centers[i])) + 1)
                group[rid] = f"floor{floor['NO']}_{label}"
        inference = 'same_floor_nearest_living_anchor_in_X_with_function_and_wall_connectivity_checks; not_official_dwelling_ID'
    else:
        group = {rid: 'unresolved_maisonette_stairs_void_and_unit_partition' for rid in rooms}
        inference = 'inventory_only; source_type17_and_vertical_access_unresolved_no_unit_partition_adopted'
    adjacency = collections.defaultdict(set)
    for f in faces:
        if f['kind_code'] == 2 and f['peer_room_id'] is not None:
            adjacency[f['room_id']].add(f['peer_room_id'])
    units = []
    for label in sorted(set(group.values())):
        if 'unassigned' in label or 'unresolved' in label:
            continue
        selected = {rid for rid in group if group[rid] == label}
        kinds = collections.Counter(rooms[r]['TYPE'] for r in selected)
        reached = {min(selected)}
        stack = list(reached)
        while stack:
            for rid in adjacency[stack.pop()] & selected - reached:
                reached.add(rid)
                stack.append(rid)
        unitfaces = [f for f in faces if f['room_id'] in selected]
        exterior = sum(f['source_area_m2'] for f in unitfaces if f['kind_code'] == 1)
        party = sum(f['source_area_m2'] for f in unitfaces if f['kind_code'] == 2 and f['peer_room_id'] not in selected)
        beds = kinds[4] + kinds[30]
        study = sum(n for k, n in kinds.items() if functions.get(k) == '书房')
        # The census excludes 厅. 起居室/厅 classification cannot be decided
        # from its numeric room-type code, despite the source thermal polygon.
        natural = beds + study
        units.append({'unit_candidate_id': key + '__' + label, 'room_ids': sorted(selected),
            'room_names': [rooms[r]['NAME'] for r in sorted(selected)],
            'room_functions': {functions[k]: v for k, v in kinds.items()},
            'source_room_area_sum_m2': sum(rooms[r]['AREA'] for r in selected),
            'native_polygon_area_sum_m2': sum(shapes[r].area for r in selected),
            'area_scope': 'source_room_floor_area_sum_not_census_gross_or_shared_allocated_H6',
            'bedrooms': beds, 'studies': study, 'living_spaces': kinds[3],
            'H7_mapping_scenarios': {'living_as_excluded_hall': natural, 'living_as_counted_natural_room': natural + kinds[3]},
            'H7_mapping_is_observed_census_response': False,
            'kitchen_spaces': kinds[5], 'toilet_spaces': kinds[6],
            'functional_inventory_complete': kinds[3] == 1 and beds >= 1 and kinds[5] == 1 and kinds[6] >= 1,
            'opaque_wall_adjacency_connected': reached == selected,
            'door_access_verified': False, 'exterior_wall_area_m2': exterior,
            'party_or_common_wall_area_m2': party, 'whole_dwelling_gross_area_m2': None,
            'floor_multiplier_is_household_replication': False,
            'household_binding_approved': False})
    room_output = [{'source_room_id': rid, 'name': r['NAME'], 'source_function_code': r['TYPE'],
                    'source_function_name': functions[r['TYPE']], 'source_area_m2': r['AREA'],
                    'native_polygon_area_m2': shapes[rid].area,
                    'floor_id': r['OF_STOREY'], 'floor_xy_polygon_m': polygons[rid],
                    'candidate_group': group[rid]} for rid, r in rooms.items()]
    face_errors = [abs(f['polygon_area_m2'] - f['source_area_m2']) for f in faces]
    net_errors = [abs(f['polygon_area_m2'] - f['source_area_m2'] - f['source_opening_area_m2']) for f in faces]
    middle_errors = [abs(f['middle_plane_polygon_area_m2'] - f['source_area_m2'] - f['source_opening_area_m2']) for f in faces]
    room_errors = [abs(shapes[rid].area - r['AREA']) for rid, r in rooms.items()]
    overlaps = []
    for f, selected in zip(floors, by_floor):
        union = unary_union([shapes[rid] for rid in selected])
        overlaps.append({'floor_no': f['NO'], 'sum_minus_union_area_m2': sum(shapes[rid].area for rid in selected) - union.area})
    output = {'source_key': key, 'source_path': str(path), 'source_sha256': hashlib.sha256(path.read_bytes()).hexdigest(),
        'catalog_label_city': 'Beijing', 'catalog_label_year': 2018,
        'city_year_labels_are_individual_home_observations': False,
        'table_counts': {k: len(v) for k, v in tables.items()},
        'storeys': [{'source_no': f['NO'], 'multiplier': f['MULTIPLE'], 'height_m': f['HEIGHT']} for f in floors],
        'source_function_names_require_string_reader_crosscheck': True,
        'candidate_partition_inference': inference, 'tower_bbox_transfer_max_displacement_m': max(displacement, default=None),
        'door_table_empty': len(tables['DOOR']) == 0,
        'ROOM_RELATION_is_door_graph': False,
        'units': units, 'rooms': room_output, 'opaque_faces': faces, 'windows': window_output,
        'diagnostics': {'max_source_face_polygon_area_residual_m2': max(face_errors),
                        'max_wall_gross_polygon_minus_net_wall_minus_openings_residual_m2': max(net_errors),
                        'gross_net_opening_balance_faces_outside_design_tolerance': sum(x > .01 for x in net_errors),
                        'wall_polygon_gross_and_SURFACE_area_net_must_not_be_compared_as_same_quantity': True,
                        'max_middle_plane_minus_net_and_openings_residual_m2': max(middle_errors),
                        'middle_plane_balance_faces_outside_design_tolerance': sum(x > .01 for x in middle_errors),
                        'middle_plane_area_residuals_require_conversion_review_not_silent_numeric_repair': True,
                        'max_room_polygon_area_residual_m2': max(room_errors), 'floor_footprint_overlap': overlaps,
                        'tolerance_m2_design_not_external_acceptance_standard': .01},
        'idf_converted_this_run': False, 'physical_calibration_validated': False, 'population_weights': None}
    return output


def svg(model):
    floorid = model['rooms'][0]['floor_id']
    rs = [r for r in model['rooms'] if r['floor_id'] == floorid]
    xs = [x for r in rs for x, y in r['floor_xy_polygon_m']]
    ys = [y for r in rs for x, y in r['floor_xy_polygon_m']]
    xmin, xmax, ymin, ymax = min(xs), max(xs), min(ys), max(ys)
    scale = min(1050 / (xmax-xmin), 590 / (ymax-ymin))
    colors = {3: '#c9dff5', 4: '#f4cfad', 30: '#f4cfad', 5: '#c5e3c8', 6: '#decbea', 17: '#dddddd', 31: '#fdeca4', 32: '#fdeca4'}
    elements = ['<svg xmlns="http://www.w3.org/2000/svg" width="1200" height="800" viewBox="0 0 1200 800">',
                '<rect width="1200" height="800" fill="white"/>',
                f'<text x="30" y="35" font-size="23">{html.escape(model["source_key"])} — native source floor polygons</text>',
                '<text x="30" y="65" font-size="15">Source room area; walls and floor boundaries retained. Apartment groups are inferred; doors are unknown.</text>']
    for r in rs:
        xy = [((x-xmin)*scale + 40, (ymax-y)*scale + 110) for x, y in r['floor_xy_polygon_m']]
        pts = ' '.join(f'{x:.3f},{y:.3f}' for x, y in xy)
        elements.append(f'<polygon points="{pts}" fill="{colors.get(r["source_function_code"], "#eee")}" stroke="#333" stroke-width="1"/>')
        shape = Polygon(xy)
        anchor = shape.representative_point()
        label = html.escape(r['name'] + ' ' + str(r['source_function_code']))
        elements.append(f'<text x="{anchor.x:.2f}" y="{anchor.y:.2f}" font-size="11" text-anchor="middle">{label}</text>')
    elements.append('<text x="30" y="755" font-size="15">Codes: 3 living, 4 main bedroom, 30 bedroom, 5 kitchen, 6 bathroom, 31/32 study (source-specific), 17 unknown.</text>')
    elements.append('<text x="30" y="780" font-size="15">H7 excludes kitchen, toilet, corridor and hall. Source living-room classification requires an explicit mapping.</text></svg>')
    return '\n'.join(elements)


def main():
    outputs = []
    for key, path in SOURCES.items():
        output = extract(key, path)
        save(OUT / (key + '_NATIVE.json'), output)
        (OUT / (key + '_FLOOR0.svg')).write_text(svg(output))
        outputs.append({k: output[k] for k in ['source_key', 'source_sha256', 'table_counts', 'storeys', 'diagnostics']})
        print(json.dumps({'key': key, 'candidate_units': len(output['units']), 'diagnostics': output['diagnostics']}))
    save(OUT / 'SOURCE_GEOMETRY_SUMMARY.json', {'sources': outputs, 'source_geometry_replaced_by_rectangle': False,
         'candidate_units_are_official_household_ids': False, 'actor_ready': 0})


if __name__ == '__main__':
    main()
