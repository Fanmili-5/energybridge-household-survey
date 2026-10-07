"""Census-scope arithmetic for explicitly specified whole/shared design cases.

The formulas are from census2020 fu06.pdf PDF pages26-27. They do not identify
missing allocation components or make a scenario a population observation.
"""
from decimal import Decimal, ROUND_HALF_UP


def decimal(value):
    if isinstance(value, bool) or value is None:
        raise ValueError('missing_or_invalid_area')
    d = Decimal(str(value))
    if not d.is_finite() or d < 0:
        raise ValueError('negative_or_nonfinite_area')
    return d


def shared_allocation(whole_unit_gross_m2, common_gross_m2, households, natural_room_ids):
    """Each household receives its exclusive area and 1/n of unit common area.

    Input areas must already have the SAME gross scope. A thermal/net area is
    not admitted without a separate explicit bridge. Rooms are independently
    used H7-countable spaces, not bedrooms inferred from generation count.
    """
    total, common = decimal(whole_unit_gross_m2), decimal(common_gross_m2)
    if len(households) < 2:
        raise ValueError('shared_allocation_requires_at_least_two_households')
    ids = [h['household_id'] for h in households]
    if len(set(ids)) != len(ids):
        raise ValueError('duplicate_household_id')
    areas = [decimal(h['exclusive_gross_m2']) for h in households]
    if abs(sum(areas) + common - total) > Decimal('.000001'):
        raise ValueError('whole_exclusive_common_area_conservation_failure')
    room_ids = [r for h in households for r in h['exclusive_natural_room_ids']]
    if len(set(room_ids)) != len(room_ids):
        raise ValueError('natural_room_assigned_to_multiple_households')
    if set(room_ids) != set(natural_room_ids):
        raise ValueError('exclusive_H7_room_partition_incomplete_or_ineligible')
    share = common / len(households)
    output = []
    for h, exclusive in zip(households, areas):
        a = exclusive + share
        output.append({'household_id': h['household_id'], 'household_H6_unrounded_m2': float(a),
                       'census_H6_integer_m2': int(a.quantize(Decimal('1'), rounding=ROUND_HALF_UP)),
                       'household_H7_independent_rooms': len(h['exclusive_natural_room_ids']),
                       'exclusive_natural_room_ids': h['exclusive_natural_room_ids']})
    # Rounded census responses may not sum to the rounded dwelling total.
    return {'whole_unit_gross_m2': float(total), 'common_gross_m2': float(common),
            'sharing_household_count': len(households), 'households': output,
            'unrounded_H6_conservation_residual_m2': float(sum(decimal(h['household_H6_unrounded_m2']) for h in output) - total),
            'rounded_H6_sum_need_not_equal_rounded_unit': True,
            'evidence_status': 'explicit_engineering_scenario_arithmetic_not_observed_population_allocation'}


def binding_gate(profile, unit, scenario=None):
    """Fail closed on unidentifiable semantic/physical matching, not template fit."""
    h = profile['housing']
    problems = []
    for field in ['city', 'building_form', 'code_era', 'unit_position_and_exposure',
                  'area_scope_bridge', 'H7_living_hall_mapping', 'neighbor_boundary', 'meter_boundary']:
        if not scenario or scenario.get(field) is None:
            problems.append('missing_explicit_engineering_or_observed_context:' + field)
    if h['H6_building_area_m2'] is None:
        problems.append('population_household_H6_unknown; scenario_cannot_silently_overwrite')
    if h['H7_natural_rooms_exact'] is None:
        problems.append('household_H7_exact_unknown_or_topcoded')
    if not unit['functional_inventory_complete']:
        problems.append('source_functional_inventory_incomplete')
    if not unit['opaque_wall_adjacency_connected']:
        problems.append('source_wall_connectivity_failure')
    if not unit['door_access_verified']:
        problems.append('functional_access_not_verified; wall_adjacency_is_not_door_access')
    facilities = h['facilities']
    if facilities.get('kitchen_present_any') is False and unit['kitchen_spaces'] > 0:
        problems.append('source_private_kitchen_conflicts_with_household_facility_state')
    if facilities.get('toilet_present_any') is False and unit['toilet_spaces'] > 0:
        problems.append('source_private_toilet_conflicts_with_household_facility_state')
    if scenario and scenario.get('H7_living_hall_mapping') in unit['H7_mapping_scenarios']:
        n = unit['H7_mapping_scenarios'][scenario['H7_living_hall_mapping']]
        if h['occupancy_scope'] == 'whole_household_private' and h['H7_natural_rooms_exact'] != n:
            problems.append('household_H7_not_equal_mapped_independent_source_rooms')
    return {'household_physical_binding_approved': not problems, 'issues': problems,
            'actor_ready': False, 'full_service_and_human_validation': False}
