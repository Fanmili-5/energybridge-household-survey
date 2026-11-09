"""Install one complete published enclosure by face role, without mixing donors.

This transaction imports only constructions and their material rows. Ground
physics, geometry, air flow and EB equipment remain the declared reference
model's inputs. A successful transaction is not physical/numerical admission.
"""
import copy
import math

from .common import ROOT, digest, read, require, save
from .idf import Fields, objects, parse
from .source_adapter import selected, selector, source_file
from .reference_workflow import ref

SCHEMA = 'national_idf.complete_reference_enclosure_adaptation.v1'
ROLES = ('Wall', 'Roof', 'Floor', 'Window')


def polygon_area(row, fields):
    start = fields.index(row[0], 'number_of_vertices') + 1
    coordinates = list(map(float, row[start:]))
    require(len(coordinates) >= 9 and len(coordinates) % 3 == 0, 'ENCLOSURE_POLYGON_INVALID')
    points = [coordinates[i:i+3] for i in range(0, len(coordinates), 3)]
    normal = [0., 0., 0.]
    for a, b in zip(points, points[1:] + points[:1]):
        for j in range(3): normal[j] += a[(j+1) % 3] * b[(j+2) % 3] - a[(j+2) % 3] * b[(j+1) % 3]
    return math.sqrt(sum(v*v for v in normal)) / 2


def proxy_faces(rows, fields, *, root=ROOT):
    """Recognize the pinned builder's 0.005 m2 subsurface support buffers.

    These are software representation objects, not additional building walls.
    Names alone are insufficient: check parent/child relations, geometry and
    the published high-resistance construction, then leave all rows unchanged.
    """
    from .envelope_adaptation import construction_properties
    policy = read(root / 'configs/hpxml_subsurface_proxy_v1.json')
    for source in policy['source_files'].values(): source_file(source, root)
    children = {}
    for row in objects(rows, 'FenestrationSurface:Detailed'):
        children.setdefault(fields.get(row, 'building_surface_name'), []).append(row)
    proxies = {}
    for i, face in enumerate(rows):
        if face[0] != 'BuildingSurface:Detailed' or not fields.get(face, 'construction_name').startswith('AdiabaticWallConstruction'): continue
        require(fields.get(face, 'surface_type') == 'Wall' and fields.get(face, 'outside_boundary_condition') in ('Outdoors', 'Adiabatic', 'Surface'),
                'ENCLOSURE_PROXY_CONTEXT_UNSUPPORTED')
        child = children.get(face[1], [])
        require(len(child) == 1 and fields.get(child[0], 'surface_type') in ('Window', 'Door')
                and face[1] == 'surface ' + child[0][1], 'ENCLOSURE_PROXY_PARENT_NOT_SOURCE_PATTERN')
        net_area = polygon_area(face, fields) - polygon_area(child[0], fields)
        # Only geometric serialization precision, not a thermal error tolerance.
        require(math.isclose(net_area, policy['net_parent_area_m2'], rel_tol=0, abs_tol=1e-8),
                'ENCLOSURE_PROXY_AREA_NOT_SOURCE_BUFFER', net_area)
        construction = next(r for r in objects(rows, 'Construction') if r[1] == fields.get(face, 'construction_name'))
        properties = construction_properties(rows, construction, fields)
        proxies[i] = {'surface': selector(rows, i), 'subsurface': child[0][1], 'net_opaque_area_m2': net_area,
                      'preserved_construction': construction, 'source_algorithm': policy['source_files'],
                      'preserved_layer_properties': properties,
                      'basis': policy['basis']}
    return proxies


def donor(library_ref, schema_ref, *, root=ROOT):
    library = read(source_file(library_ref, root))
    require(library['schema'] == 'national_idf.complete_reference_enclosure_library.v1', 'ENCLOSURE_LIBRARY_SCHEMA')
    fields = Fields(source_file(schema_ref, root))
    require(schema_ref['sha256'] == library['engine_schema']['sha256'], 'ENCLOSURE_SCHEMA_VERSION_CONFLICT')
    metadata = read(source_file(library['publication_metadata'], root))
    require(metadata['status'] == 'published' and metadata['metadata']['access_right'] == 'open', 'ENCLOSURE_PUBLIC_SOURCE_REQUIRED')
    source_file(library['source_parameter_pack'], root)
    source_file(library['source_archive'], root)
    source = parse(source_file(library['source_model'], root).read_text())
    require(objects(source, 'Version') == [['Version', '25.2']], 'ENCLOSURE_SOURCE_VERSION')
    rows = parse(source_file(library['construction_IDF'], root).read_text())
    expected = [r for r in source if r[0].startswith(('Material', 'WindowMaterial:'))] + objects(source, 'Construction')
    require(rows == expected and digest(rows) == library['literal_object_digest'], 'ENCLOSURE_LIBRARY_NOT_LITERAL_SOURCE')
    roles = {}
    for role in ROLES:
        usages = [r for r in source if r[0] in ('BuildingSurface:Detailed', 'FenestrationSurface:Detailed')
                  and fields.get(r, 'surface_type') == role]
        names = {fields.get(r, 'construction_name') for r in usages}
        require(len(names) == 1, 'ENCLOSURE_DONOR_ROLE_AMBIGUOUS', role)
        roles[role] = next(r for r in rows if r[0] == 'Construction' and r[1] == next(iter(names)))
    return library, rows, roles


def target_roles(rows, fields, *, root=ROOT):
    """Explicit apartment/attached boundaries; never add neighbour temperatures.

    Ordinary party walls and inter-unit slabs are intentional assignments,
    separately reported from exposed faces. Their source boundary stays exact.
    A unit ceiling uses the published floor assembly in reverse layer order.
    """
    faces = {r[1]: r for r in objects(rows, 'BuildingSurface:Detailed')}
    proxies = proxy_faces(rows, fields, root=root)
    result = {}
    for i, row in enumerate(rows):
        if row[0] == 'BuildingSurface:Detailed':
            if i in proxies: continue
            role, boundary = fields.get(row, 'surface_type'), fields.get(row, 'outside_boundary_condition')
            if role == 'Wall' and boundary in ('Outdoors', 'Adiabatic'): result[i] = role
            elif role == 'Roof' and boundary == 'Outdoors': result[i] = role
            elif role == 'Floor' and boundary in ('Ground', 'Foundation'): result[i] = role
            elif role == 'Floor' and boundary == 'Adiabatic': result[i] = role
            elif role == 'Ceiling' and boundary == 'Adiabatic': result[i] = 'Ceiling'
            elif boundary == 'Outdoors' or boundary in ('Ground', 'Foundation'):
                require(False, 'ENCLOSURE_TARGET_CONTEXT_UNSUPPORTED', [role, boundary])
        elif row[0] == 'FenestrationSurface:Detailed':
            parent = faces.get(fields.get(row, 'building_surface_name'))
            require(parent is not None, 'ENCLOSURE_WINDOW_PARENT_MISSING')
            if fields.get(row, 'surface_type') == 'Window' and fields.get(parent, 'outside_boundary_condition') == 'Outdoors':
                require(fields.get(parent, 'surface_type') == 'Wall', 'ENCLOSURE_SKYLIGHT_UNSUPPORTED')
                result[i] = 'Window'
    require({'Wall', 'Window', 'Floor'} <= set(result.values()), 'ENCLOSURE_TARGET_ROLE_MISSING', sorted(set(result.values())))
    require('Roof' in result.values() or 'Ceiling' in result.values(), 'ENCLOSURE_TARGET_TOP_BOUNDARY_MISSING')
    return result


def instantiate(rows, schema_ref, library_ref, out, *, root=ROOT):
    library, _, _ = donor(library_ref, schema_ref, root=root)
    fields = Fields(source_file(schema_ref, root))
    targets = target_roles(rows, fields, root=root)
    pack = {'schema': SCHEMA, 'id': 'complete_enclosure_' + digest({'source': rows, 'library': library_ref})[:24],
            'country': library['origin_country'], 'representation_kind': 'controlled_reference',
            'source_rows_sha256': digest(rows), 'library': library_ref,
            'assignments': [{'surface': selector(rows, i), 'role': role} for i, role in targets.items()],
            'scope': 'Complete published Chinese reference construction on explicit public reference geometry; not stock, surveyed home or code compliance',
            'retained_reference_inputs': ['doors and source subsurface support buffers', 'internal mass', 'air leakage and ventilation', 'Kiva foundation and soil', 'EB devices and controls'],
            'source_differences': ['Reference geometry and ground are from the declared HPXML model; all four enclosure roles come from one Chinese published model']}
    out.mkdir(parents=True, exist_ok=False); save(out / 'PACK.json', pack)
    result, report = apply(rows, ref(out / 'PACK.json', root), schema_ref, root=root)
    save(out / 'MODIFICATIONS.json', report)
    return result, report


def apply(rows, pack_ref, schema_ref, *, root=ROOT):
    from .envelope_adaptation import construction_properties
    pack = read(source_file(pack_ref, root))
    require(pack['schema'] == SCHEMA and pack['representation_kind'] == 'controlled_reference', 'ENCLOSURE_PACK_SCHEMA')
    require(pack['source_rows_sha256'] == digest(rows), 'ENCLOSURE_SOURCE_CONTEXT_CHANGED')
    library, donor_rows, roles = donor(pack['library'], schema_ref, root=root)
    require(pack['country'] == library['origin_country'], 'ENCLOSURE_LIBRARY_COUNTRY_CONFLICT')
    fields = Fields(source_file(schema_ref, root)); targets = target_roles(rows, fields, root=root)
    proxies = proxy_faces(rows, fields, root=root)
    if 'Ceiling' in targets.values():
        floor = roles['Floor']; roles = {**roles, 'Ceiling': [floor[0], floor[1] + ' reversed for unit ceiling', *reversed(floor[2:])]}
    require(pack['assignments'] == [{'surface': selector(rows, i), 'role': role} for i, role in targets.items()],
            'ENCLOSURE_ASSIGNMENTS_NOT_COMPLETE')
    materials = {r[1]: r for r in donor_rows if r[0] != 'Construction'}
    result = copy.deepcopy(rows); additions = []; constructions = {}; inventory = []
    names = {r[1].casefold() for r in rows if len(r) > 1}
    for role, construction in roles.items():
        copied = [construction[0], pack['id'] + ' ' + role]
        for slot, name in enumerate(construction[2:]):
            if not name: continue
            layer = copy.deepcopy(materials[name]); layer[1] = pack['id'] + ' ' + role + ' layer ' + str(slot)
            require(layer[1].casefold() not in names, 'ENCLOSURE_NAME_COLLISION'); names.add(layer[1].casefold())
            additions.append(layer); copied.append(layer[1])
        require(copied[1].casefold() not in names, 'ENCLOSURE_NAME_COLLISION'); names.add(copied[1].casefold())
        additions.append(copied); constructions[role] = copied
    for i, role in targets.items():
        surface = selected(rows, selector(rows, i))
        before = next(r for r in objects(rows, 'Construction') if r[1] == fields.get(surface, 'construction_name'))
        after = constructions[role]; fields.set(result[i], 'construction_name', after[1])
        if role == 'Window':
            previous = [r for r in rows if r[0].startswith('WindowMaterial:') and r[1] in before[2:]]
            properties = {'source_layers': [materials[n] for n in roles[role][2:] if n], 'opaque_R_or_C_inferred': False}
            old_properties = {'source_layers': previous, 'opaque_R_or_C_inferred': False}
        else:
            old_properties = construction_properties(rows, before, fields)
            properties = construction_properties(rows + additions, after, fields)
        inventory.append({'surface': selector(rows, i), 'role': role, 'before': surface, 'after': result[i],
                          'construction_before': before, 'construction_after': after,
                          'literal_donor_construction': roles[role], 'before_properties': old_properties,
                          'after_properties': properties})
    for i, (old, new) in enumerate(zip(rows, result)):
        restored = copy.deepcopy(new)
        if i in targets: fields.set(restored, 'construction_name', fields.get(old, 'construction_name'))
        require(restored == old, 'ENCLOSURE_UNRELATED_OBJECT_CHANGED', i)
    result.extend(additions)
    return result, {'schema': 'national_idf.envelope_modifications.v1', 'pack': pack_ref,
                    'source_rows_sha256': digest(rows), 'result_rows_sha256': digest(result), 'modifications': inventory,
                    'library': pack['library'], 'roles_installed': [r for r in (*ROLES, 'Ceiling') if r in targets.values()],
                    'complete_package_roles': list(ROLES), 'literal_source_layer_order_and_properties': True,
                    'geometry_and_adjacency_unchanged': True, 'unselected_objects_unchanged': True,
                    'source_materials_retained': True, 'physical_validation_passed': False, 'formal_admitted': False,
                    'retained_reference_inputs': pack['retained_reference_inputs'],
                    'source_subsurface_support_proxies_preserved': list(proxies.values()),
                    'ordinary_exterior_wall_count': sum(v == 'Wall' and fields.get(rows[i], 'outside_boundary_condition') == 'Outdoors' for i, v in targets.items()),
                    'deliberate_shared_boundary_assignments': [{'surface': selector(rows, i), 'role': role,
                        'source_boundary_unchanged': fields.get(rows[i], 'outside_boundary_condition'),
                        'basis': 'Declared common reference masonry party wall / floor; ceiling reverses whole floor layers, not a real neighbour reconstruction'}
                        for i, role in targets.items() if rows[i][0] == 'BuildingSurface:Detailed' and fields.get(rows[i], 'outside_boundary_condition') == 'Adiabatic'],
                    'roof_not_exposed_in_this_unit': 'Roof' not in targets.values(),
                    'whole_floor_layer_reversal_for_unit_ceiling_declared': 'Ceiling' in targets.values(),
                    'neighbour_temperature_or_hidden_heat_added': False}
