"""Bind publisher-defined apartments across explicit reference floors.

Unlike the terraced-house partition, apartments have separate households above
and below and unassigned source common areas. Membership is checked against
the primary plan and recorded repeat derivation, not inferred from room count.
"""
from .common import ROOT, locked, read, require
from .native_enclosures import geometry_identity


def bind(bundle, review, *, root=ROOT):
    require(review['schema'] == 'national_idf.source_apartment_correspondence.v1'
        and review['geometry_sha256'] == geometry_identity(bundle)
        and review['review_scope'] == 'publisher_plan_and_explicit_source_repeat_reference',
        'APARTMENT_CORRESPONDENCE_NOT_BOUND')
    primary = read(locked(review['primary_plan_correspondence'], root))
    derivation = read(locked(review['repeat_derivation'], root))
    require(derivation['geometry_audit']['passed'] and not derivation['primary_physical_vectors_modified']
        and not derivation['source_engine_aggregation_equivalence_claimed'], 'APARTMENT_REPEAT_NOT_REVIEWED')
    rooms = {r['NAME']: r for r in bundle['rooms']}; origins = {r['model_room_name']: r for r in derivation['zone_origins']}
    require(set(rooms) == set(origins), 'APARTMENT_ROOM_ORIGINS_INCOMPLETE')
    members = []; ids = set()
    for dwelling in review['dwellings']:
        require(dwelling['id'] not in ids, 'APARTMENT_DWELLING_DUPLICATE'); ids.add(dwelling['id'])
        floor = dwelling['physical_storey_index']; group = dwelling['primary_unit_id']
        expected = []
        for name, origin in origins.items():
            if origin['physical_storey_index'] != floor: continue
            primary_ids = primary['storeys'][str(origin['primary_storey_id'])][group]['room_ids']
            if origin['primary_room_id'] in primary_ids: expected.append(name)
        require(expected and set(expected) == set(dwelling['room_names'])
            and len(expected) == len(dwelling['room_names']), 'APARTMENT_PRIMARY_MEMBERSHIP_CHANGED', dwelling['id'])
        require(len({rooms[n]['OF_STOREY'] for n in expected}) == 1, 'APARTMENT_MERGES_FLOORS')
        members += [(name, dwelling['id']) for name in expected]
    assigned = {n for n, _ in members}; context = set(review['context_room_names'])
    require(len(assigned) == len(members) and assigned.isdisjoint(context)
        and assigned | context == set(rooms), 'APARTMENT_FULL_CONTEXT_PARTITION')
    owner = {rooms[n]['ID']: d for n, d in members}
    owner.update({rooms[n]['ID']: 'source_context' for n in context})
    floor_by_id = {r['ID']: r['NO'] for r in bundle['storeys']}
    rooms_by_id = {r['ID']: r for r in bundle['rooms']}
    cards = []
    for dwelling in review['dwellings']:
        selected = [rooms[n] for n in dwelling['room_names']]
        faces = [f for f in bundle['faces'] if owner[f['source_surface']['OF_ROOM']] == dwelling['id']]
        cross = [f for f in faces if f['boundary'] == 'Surface'
                 and owner[f['source_peer']['OF_ROOM']] != dwelling['id']]
        for face in cross:
            a, b = (rooms_by_id[face[key]['OF_ROOM']] for key in ('source_surface', 'source_peer'))
            delta = abs(floor_by_id[a['OF_STOREY']]-floor_by_id[b['OF_STOREY']])
            require((delta == 0 and face['source_enclosure']['KIND'] == 2)
                or (delta == 1 and face['source_enclosure']['KIND'] == 5), 'APARTMENT_BOUNDARY_KIND_OR_FLOOR_CONFLICT')
        cards.append({'id': dwelling['id'], 'room_names': dwelling['room_names'],
            'source_room_area_sum_m2': sum(r['AREA'] for r in selected),
            'source_volume_sum_m3': sum(r['VOLUME'] for r in selected),
            'explicit_storeys': sorted({r['OF_STOREY'] for r in selected}),
            'physical_storey_index': dwelling['physical_storey_index'], 'primary_unit_id': dwelling['primary_unit_id'],
            'adjacent_dwelling_ids': sorted({owner[f['source_peer']['OF_ROOM']] for f in cross}),
            'source_empty_room_ids': [r['ID'] for r in selected if r['TYPE'] == 17],
            'ground_faces': sum(f['boundary'] == 'Ground' for f in faces),
            'outdoor_faces': sum(f['boundary'] == 'Outdoors' for f in faces),
            'cross_floor_interfaces': sum(f['source_enclosure']['KIND'] == 5 for f in cross),
            'area_basis': 'Primary ROOM.AREA sum; no legal gross/net conversion',
            'conditioned_or_occupied_area_m2': None, 'family_matching_permitted': False, 'formal_admitted': False})
    return cards
