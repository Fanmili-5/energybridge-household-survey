"""Read explicit DeST enclosure geometry without cutting households or guessing layers.

The neutral bundle is independent of city and contains the original room-side
records as well as shared middle planes. It is not an operational admission.
Only explicitly represented, unmultiplied storeys are supported here.
"""
from collections import defaultdict
from datetime import datetime, timedelta

import numpy as np

from .common import digest, require, sha
from .prototypes import table, geometry_audit


ASSEMBLY_TABLES = {1: 'SYS_OUTWALL', 2: 'SYS_INWALL', 3: 'SYS_ROOF',
                  4: 'SYS_GROUNDFLOOR', 5: 'SYS_MIDDLEFLOOR', 6: 'SYS_AIRFLOOR'}


def monthly_ground(rows, ground_id):
    """Collapse only an exact complete, non-leap, piecewise-monthly source series."""
    selected = [r for r in rows if r['ID'] == ground_id]
    require(len(selected) == 8760 and {r['HOUR'] for r in selected} == set(range(8760)),
            'NATIVE_GROUND_TIME_AXIS')
    months = defaultdict(set)
    for r in selected:
        require(np.isfinite(r['T']), 'NATIVE_GROUND_NONFINITE')
        m = (datetime(2001, 1, 1) + timedelta(hours=r['HOUR'])).month
        months[m].add(r['T'])
    require(all(len(months[m]) == 1 for m in range(1, 13)),
            'NATIVE_GROUND_NOT_EXACTLY_MONTHLY')
    return [next(iter(months[m])) for m in range(1, 13)]


def ground_boundary_rows(bundle, *, purpose=None):
    """Preserve an unknown-interface series only as an explicit source probe.

GROUND_DATA establishes numbers, not the physical location of a temperature
boundary. A conversion must not silently turn it into slab-contact evidence.
This function does not supply a replacement soil model or a local temperature.
"""
    peers = {f['source_peer']['OF_ROOM'] for f in bundle['faces'] if f['boundary'] == 'Ground'}
    if not peers:
        return [], {'ground_contact_faces': 0, 'new_physical_values': False}
    require(purpose == 'source_numerical_reference', 'NATIVE_GROUND_INTERFACE_UNRESOLVED', {
        'missing': ['temperature_interface', 'complete_transfer_path_to_floor', 'site_applicability'],
        'source_numbers_are_not_contact_temperature_evidence': True,
        'preserve_original_probe_only_with_explicit_purpose': 'source_numerical_reference'})
    grounds = bundle['grounds']
    require(len(grounds) == 1 and peers == {grounds[0]['source_ground']['GROUND_ID']},
            'NATIVE_MULTIPLE_GROUND_TEMPERATURES_UNSUPPORTED')
    values = grounds[0]['monthly_temperature_C']
    require(len(values) == 12 and all(type(v) in (int,float) and np.isfinite(v) for v in values),
            'NATIVE_GROUND_MONTHLY_VALUES')
    return [['Site:GroundTemperature:BuildingSurface', *values]], {
        'schema': 'national_idf.native_ground_reference_binding.v1',
        'purpose': purpose, 'source_sha256': bundle['source_sha256'],
        'source_ground_id': grounds[0]['source_ground']['GROUND_ID'],
        'source_ground_data_id': grounds[0]['ground_data_id'],
        'source_default_setting': grounds[0]['source_default_setting'],
        'preserved_monthly_C': values,
        'EnergyPlus_temperature_interface': 'outside_face_of_modeled_floor_construction',
        'source_temperature_interface': None,
        'source_interface_to_EnergyPlus_equivalence': None,
        'complete_source_ground_transfer_path': None,
        'local_ground_applicability': None,
        'source_numerical_reference_only': True,
        'physical_ground_correction': False, 'new_physical_values': False,
        'formal_admitted': False}


def normal(surface, south_direction=270):
    if surface['AZIMUTH'] == 999:
        return np.array([0., 0., -1.])
    if surface['AZIMUTH'] == -999:
        return np.array([0., 0., 1.])
    require(abs(surface['TILT'] - 90) < 1e-5, 'NATIVE_SLOPED_NORMAL_NOT_IMPLEMENTED')
    a = np.radians(south_direction - 180 - surface['AZIMUTH'])
    return np.array([np.cos(a), np.sin(a), 0.])


def orient(vertices, surface, south_direction=270):
    p = np.array(vertices, dtype=float)
    n = np.cross(p, np.roll(p, -1, axis=0)).sum(axis=0)/2
    expected = normal(surface, south_direction)
    require(abs(n @ expected) > 1e-8 and
            abs(n @ expected)/np.linalg.norm(n) > .99999,
            'NATIVE_NORMAL_MISMATCH', surface['SURFACE_ID'])
    return (p if n @ expected > 0 else p[::-1]).tolist()


def extract(path, *, db=None):
    if db is None:
        from access_parser_c import AccessParser
        db = AccessParser(str(path))
    storeys = table(db, 'STOREY')
    require(storeys and all(s['MULTIPLE'] == 1 for s in storeys),
            'NATIVE_EXPLICIT_STOREYS_ONLY')
    require(not table(db, 'DOOR'), 'NATIVE_DOOR_TRANSLATION_NOT_IMPLEMENTED')
    env = table(db, 'ENVIRONMENT')
    require(len(env) == 1, 'NATIVE_ENVIRONMENT_CARDINALITY')
    surfaces = {s['SURFACE_ID']: s for s in table(db, 'SURFACE')}
    rooms = table(db, 'ROOM')
    require(len({r['NAME'] for r in rooms}) == len(rooms), 'NATIVE_DUPLICATE_ROOM_NAME')
    room_ids = {r['ID'] for r in rooms}
    points = {p['POINT_ID']: [p['X'], p['Y'], p['Z']] for p in table(db, 'POINT')}
    planes = {p['PLANE_ID']: p for p in table(db, 'PLANE')}
    geometry = {g['GEOMETRY_ID']: g for g in table(db, 'GEOMETRY')}
    loops = defaultdict(list)
    for p in table(db, 'LOOP_POINT'):
        loops[p['LOOP_ID']].append(p)

    def polygon(pid):
        g = geometry[planes[pid]['GEOMETRY']]
        require(not g.get('INSIDE_LOOP_NUM', 0), 'NATIVE_GEOMETRY_HOLES_UNSUPPORTED')
        l = sorted(loops[g['BOUNDARY_LOOP_ID']], key=lambda x: x['POINT_NO'])
        require(len(l) >= 3 and len({p['POINT_NO'] for p in l}) == len(l),
                'NATIVE_POLYGON_ORDER')
        # POINT coordinates are metres in this source schema. ROOM.X/Y labels
        # use a different unit and are deliberately never geometry inputs.
        return [points[p['POINT']] for p in l]

    materials = {r['MATERIAL_ID']: r for r in table(db, 'SYS_MATERIAL')}
    enclosures = table(db, 'MAIN_ENCLOSURE')
    assemblies = []
    for kind, cid in sorted({(e['KIND'], e['CONSTRUCTION']) for e in enclosures}):
        require(kind in ASSEMBLY_TABLES, 'NATIVE_UNKNOWN_ENCLOSURE_KIND')
        t = ASSEMBLY_TABLES[kind]
        layers = sorted([l for l in table(db, t + '_MATERIAL') if l['STRUCT_ID'] == cid],
                        key=lambda l: l['LAYER_NO'])
        require(layers, 'NATIVE_CONSTRUCTION_EMPTY')
        rows = []
        for layer in layers:
            m = materials[layer['MATERIAL_ID']]
            values = [layer['LENGTH']/1000, m['CONDUCTIVITY'], m['DENSITY'], m['SPECIFIC_HEAT']]
            require(all(np.isfinite(v) and v > 0 for v in values), 'NATIVE_LAYER_RANGE')
            rows.append({'source_layer': layer, 'source_material': m,
                         'thickness_k_density_cp_SI': values})
        assemblies.append({'kind': kind, 'id': cid, 'layers': rows,
                           'stored_order': 'LAYER_NO_ascending',
                           'independent_native_physical_side_semantics': None})
    faces = []
    for e in enclosures:
        for side, peer in [('SIDE1', 'SIDE2'), ('SIDE2', 'SIDE1')]:
            s, p = surfaces[e[side]], surfaces[e[peer]]
            if s['TYPE'] in (1, 2):
                continue
            require(s['OF_ROOM'] in room_ids, 'NATIVE_FACE_ROOM_MISSING')
            require(p['TYPE'] in (1, 2) or p['OF_ROOM'] in room_ids, 'NATIVE_PEER_MISSING')
            faces.append({'source_enclosure': e, 'source_side': side,
                'source_surface': s, 'source_peer': p,
                'vertices_m': orient(polygon(e['MIDDLE_PLANE']), s, env[0]['SOUTH_DIRECTION']),
                'boundary': {1: 'Outdoors', 2: 'Ground'}.get(p['TYPE'], 'Surface')})
    windows = []
    types = {w['ID']: w for w in table(db, 'WINDOW_TYPE_DATA')}
    for w in table(db, 'WINDOW'):
        # The old SHADING field is NULL in these 2.6 files; SHADINGID is the
        # explicit new reference. Preserve the legacy NULL instead of reading
        # its zero-filled storage as a declared physical value.
        require(w.get('SHADING') in (None, 0) and w.get('SHADINGID') == 0 and
                w['CURTAIN'] == 0 and w['SCHEDULE'] == 0 and w['K'] == 1,
                'NATIVE_WINDOW_CONTROL_NOT_TRANSLATED')
        s, p = surfaces[w['SIDE1']], surfaces[w['SIDE2']]
        require((s['TYPE'] == 1) != (p['TYPE'] == 1), 'NATIVE_INTERIOR_WINDOW_NOT_IMPLEMENTED')
        inside = p if s['TYPE'] == 1 else s
        outside = s if s['TYPE'] == 1 else p
        host = [f for f in faces if f['source_enclosure']['ID'] == w['OF_ENCLOSURE'] and
                f['source_surface']['OF_ROOM'] == inside['OF_ROOM']]
        require(len(host) == 1, 'NATIVE_WINDOW_HOST_AMBIGUOUS')
        windows.append({'source_window': w, 'source_type': types[w['TYPE']],
            'source_surface': inside, 'source_peer': outside,
            'host_surface_id': host[0]['source_surface']['SURFACE_ID'],
            'vertices_m': orient(polygon(w['MIDDLE_PLANE']), inside, env[0]['SOUTH_DIRECTION'])})
    grounds = []
    ground_ids = {f['source_peer']['OF_ROOM'] for f in faces if f['boundary'] == 'Ground'}
    for gid in sorted(ground_ids):
        g = [r for r in table(db, 'GROUND') if r['GROUND_ID'] == gid]
        require(len(g) == 1, 'NATIVE_GROUND_ID_MISSING')
        if 'GROUND_DATA_ID' in g[0]:
            data_id, setting = g[0]['GROUND_DATA_ID'], None
        else:
            defaults = [r for r in table(db, 'DEFAULT_SETTING') if
                        r['TABLE_NAME'] == 'GROUND' and r['FIELD_NAME'] == 'GROUND_DATA_ID'
                        and r['TYPE'] == 2 and r['KIND'] == 0]
            require(len(defaults) == 1, 'NATIVE_GROUND_DATA_SELECTION_UNRESOLVED')
            setting, data_id = defaults[0], defaults[0]['LONG']
        grounds.append({'source_ground': g[0], 'source_default_setting': setting,
                        'ground_data_id': data_id,
                        'monthly_temperature_C': monthly_ground(table(db, 'GROUND_DATA'), data_id),
                        'local_measurement_or_derivation': None,
                        'applicability_review': None})
    return {'schema': 'national_idf.native_enclosures.v1', 'source_sha256': sha(path),
        'environment': env[0], 'storeys': storeys, 'rooms': rooms,
        'room_types': table(db, 'ROOM_TYPE_DATA'), 'assemblies': assemblies,
        'faces': faces, 'windows': windows, 'grounds': grounds,
        'whole_household_mapping': None, 'formal_admitted': False,
        'source_model_result_comparison': 'not_available',
        'retained_geometry_convention': 'Source shared MIDDLE_PLANE; no polygon snapping or scaling'}


def geometry_rows(bundle):
    rooms = {r['ID']: r for r in bundle['rooms']}
    out = [['GlobalGeometryRules', 'UpperLeftCorner', 'CounterClockWise', 'Relative']]
    for r in bundle['rooms']:
        # Geometry and room volume must independently agree; no autocalculated
        # volume is substituted for an inconvenient source value.
        out.append(['Zone', r['NAME'], 0, 0, 0, 0, 1, 1, 'Autocalculate',
                    r['VOLUME'], r['AREA']])
    for face in bundle['faces']:
        s, e = face['source_surface'], face['source_enclosure']
        kind = e['KIND']
        typ = 'Wall' if kind in (1, 2) else 'Roof' if kind == 3 else (
            'Ceiling' if kind == 5 and s['AZIMUTH'] == -999 else 'Floor')
        name = f"native_surface_{s['SURFACE_ID']}"
        construction = f"native_enclosure_{e['ID']}_{face['source_side']}"
        peer = f"native_surface_{face['source_peer']['SURFACE_ID']}" if face['boundary'] == 'Surface' else ''
        outdoor = face['boundary'] == 'Outdoors'
        out.append(['BuildingSurface:Detailed', name, typ, construction,
            rooms[s['OF_ROOM']]['NAME'], '', face['boundary'], peer,
            'SunExposed' if outdoor else 'NoSun', 'WindExposed' if outdoor else 'NoWind',
            'Autocalculate', len(face['vertices_m']), *np.array(face['vertices_m']).flatten().tolist()])
    for window in bundle['windows']:
        w = window['source_window']
        out.append(['FenestrationSurface:Detailed', f"native_window_{w['ID']}", 'Window',
            f"native_window_type_{w['TYPE']}_construction", f"native_surface_{window['host_surface_id']}",
            '', 'Autocalculate', '', 1, len(window['vertices_m']),
            *np.array(window['vertices_m']).flatten().tolist()])
    audit = geometry_audit(out)
    require(audit['passed'], 'NATIVE_GEOMETRY_CONVERSION_FAILED', audit['errors'])
    return out, audit


def geometry_identity(bundle):
    """A city/material change cannot alter a reviewed household partition."""
    return digest({
        'rooms': [{k: r[k] for k in ('ID', 'NAME', 'OF_STOREY', 'AREA', 'VOLUME')}
                  for r in bundle['rooms']],
        'storeys': [{k: s[k] for k in ('ID', 'NO', 'MULTIPLE', 'HEIGHT')} for s in bundle['storeys']],
        'faces': [{'id': f['source_surface']['SURFACE_ID'],
                   'room': f['source_surface']['OF_ROOM'],
                   'peer_room': f['source_peer']['OF_ROOM'], 'boundary': f['boundary'],
                   'kind': f['source_enclosure']['KIND'], 'vertices_m': f['vertices_m']}
                  for f in bundle['faces']],
        'windows': [{'id': w['source_window']['ID'], 'host': w['host_surface_id'],
                     'vertices_m': w['vertices_m']} for w in bundle['windows']]})


def bind_dwellings(bundle, review):
    """Apply an explicit reviewed partition to identical source geometry only."""
    require(review['schema'] == 'national_idf.native_dwelling_correspondence.v1' and
            review['geometry_sha256'] == geometry_identity(bundle), 'NATIVE_DWELLING_GEOMETRY_DRIFT')
    require(review['review_scope'] == 'publisher_plan_to_native_geometry_correspondence',
            'NATIVE_DWELLING_REVIEW_SCOPE')
    rooms = {r['NAME']: r for r in bundle['rooms']}
    memberships = [(r, d['id']) for d in review['dwellings'] for r in d['room_names']]
    require(len({r for r, _ in memberships}) == len(memberships) and
            {r for r, _ in memberships} == set(rooms), 'NATIVE_DWELLING_PARTITION_INCOMPLETE')
    require(len({d['id'] for d in review['dwellings']}) == len(review['dwellings']),
            'NATIVE_DWELLING_DUPLICATE_ID')
    owner = {rooms[r]['ID']: d for r, d in memberships}
    cards = []
    for d in review['dwellings']:
        included = [rooms[r] for r in d['room_names']]
        boundary = [f for f in bundle['faces'] if owner[f['source_surface']['OF_ROOM']] == d['id']]
        cross = [f for f in boundary if f['boundary'] == 'Surface' and
                 owner[f['source_peer']['OF_ROOM']] != d['id']]
        require(all(f['source_enclosure']['KIND'] == 2 for f in cross),
                'NATIVE_DWELLING_CROSSES_FLOOR_BOUNDARY')
        cards.append({'id': d['id'], 'room_names': d['room_names'],
            'source_room_area_sum_m2': sum(r['AREA'] for r in included),
            'source_volume_sum_m3': sum(r['VOLUME'] for r in included),
            'explicit_storeys': sorted({r['OF_STOREY'] for r in included}),
            'adjacent_dwelling_ids': sorted({owner[f['source_peer']['OF_ROOM']] for f in cross}),
            'source_empty_room_ids': [r['ID'] for r in included if r['TYPE'] == 17],
            'ground_faces': sum(f['boundary'] == 'Ground' for f in boundary),
            'outdoor_faces': sum(f['boundary'] == 'Outdoors' for f in boundary),
            'area_basis': 'Source ROOM.AREA sum consistent with shared MIDDLE_PLANE; not certified legal gross/net or conditioned area',
            'conditioned_or_occupied_area_m2': None,
            'family_matching_permitted': False, 'formal_admitted': False})
    return cards
