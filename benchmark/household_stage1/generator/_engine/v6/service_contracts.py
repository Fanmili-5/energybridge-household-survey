"""Requirements for later event generation, never fabricated appliance events."""
KEY = {'AC': 'space_ac_available', 'WM': 'washer_available',
       'DR': 'dryer_available', 'DW': 'dishwasher_available',
       'WH': 'water_heater_available', 'EV': 'home_vehicle_charging'}
FIELDS = {
    'AC': ['service_interval', 'occupancy_and_thermal_need', 'temperature_bounds'],
    'WM': ['load_id', 'cycle_program', 'start', 'end', 'completion_deadline'],
    'DR': ['load_id', 'cycle_program', 'start', 'end', 'completion_deadline', 'predecessor_wash_event_id'],
    'DW': ['dish_load_id', 'meal_or_accumulation_event_ids', 'cycle_program', 'start', 'end', 'completion_deadline'],
    'WH': ['hot_water_draw_event_ids', 'draw_volumes_litres', 'service_temperatures', 'service_intervals', 'tank_initial_state'],
    'EV': ['parking_session_id', 'arrival_soc', 'departure_soc_target', 'battery_capacity_kwh', 'charger_power_kw', 'efficiency', 'start', 'end'],
}
POLICY = {'AC': 'bounded_temperature_setpoint', 'WM': 'whole_non_interruptible_cycle',
          'DR': 'whole_non_interruptible_cycle', 'DW': 'whole_non_interruptible_cycle',
          'WH': 'preheat_with_storage_and_service_safety_bounds',
          'EV': 'single_contiguous_session_per_episode'}


def asset_for(h, f, case_id):
    q = h['equipment'][KEY[f]]
    if h['control_inventory'][f]['enabled']:
        return h['control_inventory'][f]['reference_asset_id']
    return q.get('reference_asset_id') or q.get('source_asset_key') or f'{case_id}-{f}-fixed-reference'


def attach(c):
    h = c['household']; enabled = set(h['controlled_function_ids'])
    assets = {}
    for f, key in KEY.items():
        if not h['equipment'][key]['present']:
            continue
        asset = asset_for(h, f, c['case_id'])
        entry = assets.setdefault(asset, {'asset_id': asset, 'functions': [],
                    'controlled_functions': [], 'fixed_functions': [],
                    'max_parallel_functions': 1, 'status': 'reference_resource_binding',
                    'physical_execution_verified': False})
        entry['functions'].append(f)
        entry['controlled_functions' if f in enabled else 'fixed_functions'].append(f)
    h['service_asset_registry'] = assets
    shared = []
    for asset, entry in assets.items():
        if len(entry['functions']) > 1:
            assert set(entry['functions']) == {'WM', 'DR'}, entry
            shared.append({'asset_id': asset, 'functions': ['WM', 'DR'],
                           'controlled_functions': entry['controlled_functions'],
                           'fixed_functions': entry['fixed_functions'],
                           'max_parallel_functions': 1, 'precedence': 'wash_before_dry',
                           'scope': 'controlled_and_fixed_services'})
    h['shared_control_asset_constraints'] = shared
    contracts = {}
    for f in h['controlled_function_ids']:
        contract = {'contract_id': f"{c['case_id']}:service:{f}",
                    'function': f, 'status': 'benchmark_service_requirement',
                    'reference_asset_id': asset_for(h, f, c['case_id']),
                    'required_event_fields': FIELDS[f], 'operation_policy': POLICY[f],
                    'require_actual_service_need': True,
                    'demand_frequency_inferred_from_enrollment': False,
                    'actual_event_instantiated': False, 'physical_execution_verified': False,
                    'service_deadline_must_be_met': True}
        if f == 'DR':
            contract['predecessor'] = {
                'function': 'WM', 'reference_asset_id': asset_for(h, 'WM', c['case_id']),
                'same_load_required': True, 'timing': 'wash_end_lte_dry_start',
                'washer_enrolled': 'WM' in enabled,
                'not_focused_means_fixed_service': True,
                'preserve_fixed_predecessor_schedule': True,
                'resolved_event_id': None,
                'unresolved_predecessor_blocks_instantiation': True}
        elif f == 'DW':
            contract['demand_basis'] = 'actual_accumulated_dishes_not_one_cycle_per_meal_by_default'
            contract['earliest_start_rule'] = 'after_all_referenced_dish_loading_events'
        elif f == 'WH':
            contract['demand_basis'] = 'actual_hot_water_service_draws_not_extra_draws_for_coverage'
            contract['thermal_and_care_safety_must_be_verified'] = True
        elif f == 'EV':
            contract['demand_basis'] = 'one_selected_parking_episode_not_repeated_daily_soc_reset'
            contract['parking_and_energy_balance_must_be_verified'] = True
        elif f == 'AC':
            contract['demand_basis'] = 'actual_thermal_service_need_with_role_comfort_bounds'
        else:
            contract['demand_basis'] = 'actual_laundry_load_not_one_cycle_per_slot'
        contracts[f] = contract
    h['service_contracts'] = contracts
    for slot in h['question_coverage_blueprint']['slots']:
        fs = slot['focus_functions']
        slot['service_contract_ids'] = [contracts[f]['contract_id'] for f in fs]
        slot['actual_events_instantiated'] = False
        fixed = []
        if 'DR' in fs and 'WM' not in fs:
            fixed.append({'function': 'WM', 'reference_asset_id': asset_for(h, 'WM', c['case_id']),
                          'relation': 'same_load_wash_completes_before_drying',
                          'coverage_counted': False, 'control_mode_in_this_slot': 'fixed',
                          'event_id': None, 'must_resolve_before_instantiation': True})
        slot['fixed_service_prerequisites'] = fixed
        slot['resource_asset_ids'] = sorted({contracts[f]['reference_asset_id'] for f in fs} |
                                           {x['reference_asset_id'] for x in fixed})
        if 'resource_rule' in slot:
            slot['resource_rule'] = 'follow structured service contracts and shared assets including fixed predecessor services'
    blocks = h['weekend_design']['blocks']; members = {m['id'] for m in h['members']}
    if not blocks:
        realized = 'no_added_outing'
    elif any(set(x['participants']) < members for x in blocks):
        realized = 'split_household_outing'
    elif max(x['end'] - x['start'] for x in blocks) <= 120:
        realized = 'short_outings'
    else:
        realized = 'half_day_outing'
    requested = h['weekend_design']['requested_stratum']
    h['weekend_realization'] = {'requested_stratum': requested, 'realized_stratum': realized,
                              'requested_matches_realized': requested == realized,
                              'basis': 'derived_from_experimental_activity_blocks',
                              'not_a_population_rate': True}
    return c
