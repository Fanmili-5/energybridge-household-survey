"""A single H6/H7/facility observation operator for an explicit dwelling world.

Authority: NBS census2020 fu06.pdf, PDF pp26-27. This module validates
arithmetic and response scope; it does not validate polygons, population
frequencies, climate, thermal parameters, or device performance.
"""
from decimal import Decimal, ROUND_HALF_UP

AREA_BASIS = 'census_building_area_components'
EVIDENCE = {'documented', 'survey_proxy', 'engineering_scenario'}
EXCLUDED_H7 = {'kitchen', 'toilet', 'corridor', 'hall', 'non_natural_space'}
NATURAL_H7 = {'bedroom', 'study', 'other_natural_room', 'living_natural_room'}


def number(value):
    if value is None or isinstance(value, bool):
        raise ValueError('missing_or_boolean_area')
    try:
        result = Decimal(str(value))
    except Exception as exc:
        raise ValueError('invalid_area') from exc
    if not result.is_finite() or result < 0:
        raise ValueError('negative_or_nonfinite_area')
    return result


def project(world):
    if world.get('area_basis') != AREA_BASIS:
        raise ValueError('thermal_or_usable_area_cannot_be_relabelled_as_building_area')
    if world.get('area_evidence') not in EVIDENCE:
        raise ValueError('missing_area_evidence_identity')
    households = world['households']
    ids = [h['household_id'] for h in households]
    if not ids or any(not isinstance(i, str) or not i for i in ids) or len(set(ids)) != len(ids):
        raise ValueError('invalid_or_duplicate_household_id')
    total = number(world['whole_unit_building_area_m2'])
    common = number(world['common_building_area_m2'])
    exclusive = {h['household_id']: number(h['exclusive_building_area_m2']) for h in households}
    if abs(sum(exclusive.values()) + common - total) > Decimal('0.000001'):
        raise ValueError('exclusive_common_whole_area_conservation_failure')
    # This is a decimal arithmetic allowance, NOT a geometry/engineering tolerance.
    rooms = world['rooms']
    room_ids = [r['room_id'] for r in rooms]
    if not rooms or len(set(room_ids)) != len(room_ids):
        raise ValueError('invalid_or_duplicate_room_id')
    counts = {i: 0 for i in ids}
    facilities = {i: {'kitchen': 'none', 'toilet': 'none'} for i in ids}
    for room in rooms:
        kind = room['census_room_class']
        if kind not in EXCLUDED_H7 | NATURAL_H7:
            raise ValueError('unadjudicated_H7_room_class')
        if room.get('classification_evidence') not in EVIDENCE:
            raise ValueError('missing_H7_classification_evidence_identity')
        users = room['using_household_ids']
        if not users or len(set(users)) != len(users) or not set(users) <= set(ids):
            raise ValueError('invalid_room_use_partition')
        # A shared natural room can exist, but is not independently used by either
        # household. Do not force every H7-eligible room into an exclusive partition.
        if kind in NATURAL_H7 and len(users) == 1:
            counts[users[0]] += 1
        if kind in {'kitchen', 'toilet'}:
            state = 'private' if len(users) == 1 else 'shared'
            for i in users:
                previous = facilities[i][kind]
                facilities[i][kind] = state if previous == 'none' else (
                    previous if previous == state else 'private_and_shared')
    output = []
    for i in ids:
        area = exclusive[i] + common / len(ids)
        output.append({'household_id': i, 'H6_unrounded_m2': str(area),
                       'H6_census_integer_m2': int(area.quantize(Decimal('1'), rounding=ROUND_HALF_UP)),
                       'H7_independent_natural_rooms': counts[i],
                       'H7_bin': str(counts[i]) if counts[i] < 5 else '5+',
                       'facilities': facilities[i]})
    return {'households': output, 'whole_unit_building_area_m2': str(total),
            'area_evidence': world['area_evidence'], 'sharing_households': len(ids),
            'unrounded_H6_conservation_residual_m2': str(
                sum(Decimal(h['H6_unrounded_m2']) for h in output) - total),
            'semantic_projection_only': True, 'physical_binding_approved': False,
            'population_joint_validated': False}


def compare(population_anchor, projection, household_id):
    """Compare same-scope response values; a design cannot fill a source unknown."""
    p = next(h for h in projection['households'] if h['household_id'] == household_id)
    issues = []
    exact = population_anchor.get('H7_exact')
    bin_value = population_anchor.get('H7_bin')
    if exact is not None and (isinstance(exact, bool) or not isinstance(exact, int) or exact < 0):
        raise ValueError('invalid_H7_exact')
    if bin_value not in {'0', '1', '2', '3', '4', '5+'}:
        raise ValueError('invalid_H7_bin')
    if exact is not None and (str(exact) if exact < 5 else '5+') != bin_value:
        raise ValueError('inconsistent_H7_exact_and_bin')
    if p['H7_bin'] != bin_value:
        issues.append('H7_bin_conflict')
    if exact is not None and exact != p['H7_independent_natural_rooms']:
        issues.append('H7_exact_conflict')
    h6 = population_anchor.get('H6_census_integer_m2')
    if h6 is not None:
        if isinstance(h6, bool) or not isinstance(h6, int) or h6 < 0:
            raise ValueError('H6_requires_integer_same_census_response_scope')
        if h6 != p['H6_census_integer_m2']:
            issues.append('H6_same_scope_conflict')
    for facility, expected in population_anchor.get('facilities', {}).items():
        if facility not in {'kitchen', 'toilet'} or expected not in {'private', 'shared', 'none', None}:
            raise ValueError('invalid_facility_anchor')
        if expected is not None and expected != p['facilities'][facility]:
            issues.append('facility_scope_conflict:' + facility)
    return {'same_scope_compatible': not issues, 'issues': issues,
            'unknown_source_H6_preserved': h6 is None,
            'topcoded_H7_exact_is_design': exact is None,
            'physical_binding_approved': False}
