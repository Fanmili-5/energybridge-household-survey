from collections import Counter
'Independent structured service checks inherited from v6'
KEY={'AC': 'space_ac_available', 'WM': 'washer_available', 'DR': 'dryer_available', 'DW': 'dishwasher_available', 'WH': 'water_heater_available', 'EV': 'home_vehicle_charging'}
def need(x,msg):
    if not x:raise ValueError(msg)
def check(c):
    h = c['household']; enabled = set(h['controlled_function_ids'])
    contracts = h['service_contracts']; assets = h['service_asset_registry']
    need(set(contracts) == enabled, 'service contracts do not match enabled function set')
    function_assets = {}
    for asset, entry in assets.items():
        need(asset == entry['asset_id'] and entry['max_parallel_functions'] == 1, 'invalid service asset identity/capacity')
        need(entry['physical_execution_verified'] is False and entry['status'] == 'reference_resource_binding', 'resource binding promoted to physical verification')
        fs = entry['functions']; need(bool(fs) and len(set(fs)) == len(fs), 'empty/repeated service asset functions')
        need(set(entry['controlled_functions']) == set(fs) & enabled and set(entry['fixed_functions']) == set(fs) - enabled, 'fixed/controlled asset enrollment mismatch')
        need(len(fs) == 1 or set(fs) == {'WM', 'DR'}, 'unrelated functions share one asset')
        for f in fs:
            need(f in KEY and f not in function_assets, 'unknown/duplicate resource function')
            q = h['equipment'][KEY[f]]
            need(q['present'], 'nonexistent service asset')
            expected = (h['control_inventory'][f]['reference_asset_id'] if f in enabled else
                        q.get('reference_asset_id') or q.get('source_asset_key') or f"{c['case_id']}-{f}-fixed-reference")
            need(asset == expected, 'source/reference asset binding altered')
            function_assets[f] = asset
    need(set(function_assets) == {f for f, key in KEY.items() if h['equipment'][key]['present']}, 'present fixed or controlled service omitted from asset registry')
    shared = h['shared_control_asset_constraints']
    expected_shared = {a for a, x in assets.items() if len(x['functions']) > 1}
    need(len(shared) == len(expected_shared) and {x['asset_id'] for x in shared} == expected_shared, 'shared asset constraint missing including fixed services')
    for item in shared:
        entry = assets[item['asset_id']]
        need(set(item['functions']) == {'WM', 'DR'} and item['max_parallel_functions'] == 1 and item['precedence'] == 'wash_before_dry', 'shared washer/dryer concurrency or precedence lost')
        need(item['controlled_functions'] == entry['controlled_functions'] and item['fixed_functions'] == entry['fixed_functions'] and item['scope'] == 'controlled_and_fixed_services', 'fixed service absent from shared resource contract')
    for f, contract in contracts.items():
        need(contract['contract_id'] == f"{c['case_id']}:service:{f}" and contract['function'] == f, 'service contract ID/function binding')
        need(contract['status'] == 'benchmark_service_requirement' and contract['reference_asset_id'] == function_assets[f], 'service contract resource/status binding')
        need(contract['require_actual_service_need'] is True and contract['demand_frequency_inferred_from_enrollment'] is False, 'device enrollment invented actual demand')
        need(contract['actual_event_instantiated'] is False and contract['physical_execution_verified'] is False, 'service requirements promoted to executed events')
        need(contract['service_deadline_must_be_met'] is True, 'service deadline not protected')
        fields = set(contract['required_event_fields'])
        if f in ('WM', 'DR', 'DW'):
            need(contract['operation_policy'] == 'whole_non_interruptible_cycle' and {'start', 'end', 'cycle_program', 'completion_deadline'} <= fields, 'fragmented or incomplete appliance cycle contract')
        if f == 'DR':
            d = contract['predecessor']
            need(d['function'] == 'WM' and d['reference_asset_id'] == function_assets['WM'] and d['same_load_required'] is True and d['timing'] == 'wash_end_lte_dry_start', 'drying predecessor missing/wrong load/order')
            need(d['washer_enrolled'] == ('WM' in enabled) and d['not_focused_means_fixed_service'] is True and d['preserve_fixed_predecessor_schedule'] is True, 'unfocused washer silently rescheduled')
            need(d['resolved_event_id'] is None and d['unresolved_predecessor_blocks_instantiation'] is True and {'load_id', 'predecessor_wash_event_id'} <= fields, 'drying allowed before predecessor resolution')
        elif f == 'WM':
            need('load_id' in fields and contract['demand_basis'] == 'actual_laundry_load_not_one_cycle_per_slot', 'laundry demand manufactured per slot')
        elif f == 'DW':
            need({'dish_load_id', 'meal_or_accumulation_event_ids'} <= fields and contract['earliest_start_rule'] == 'after_all_referenced_dish_loading_events', 'dishwashing lacks load/timing dependency')
            need(contract['demand_basis'] == 'actual_accumulated_dishes_not_one_cycle_per_meal_by_default', 'dishwashing demand manufactured per meal')
        elif f == 'WH':
            need({'hot_water_draw_event_ids', 'draw_volumes_litres', 'service_temperatures', 'service_intervals', 'tank_initial_state'} <= fields and contract['thermal_and_care_safety_must_be_verified'] is True, 'water heating lacks demand or safety gate')
            need(contract['operation_policy'] == 'preheat_with_storage_and_service_safety_bounds' and contract['demand_basis'] == 'actual_hot_water_service_draws_not_extra_draws_for_coverage', 'water heating controlled by fabricated demand')
        elif f == 'EV':
            need(contract['operation_policy'] == 'single_contiguous_session_per_episode' and contract['parking_and_energy_balance_must_be_verified'] is True, 'fragmented charging or missing energy balance')
            need({'parking_session_id', 'arrival_soc', 'departure_soc_target', 'battery_capacity_kwh', 'charger_power_kw', 'efficiency', 'start', 'end'} <= fields and contract['demand_basis'] == 'one_selected_parking_episode_not_repeated_daily_soc_reset', 'EV demand repeated/undefined')
        elif f == 'AC':
            need(contract['operation_policy'] == 'bounded_temperature_setpoint' and {'service_interval', 'occupancy_and_thermal_need', 'temperature_bounds'} <= fields and contract['demand_basis'] == 'actual_thermal_service_need_with_role_comfort_bounds', 'AC lacks thermal/comfort need')
    bp = h['question_coverage_blueprint']
    for slot in bp['slots']:
        fs = slot['focus_functions']
        need(slot['service_contract_ids'] == [contracts[f]['contract_id'] for f in fs] and slot['actual_events_instantiated'] is False, 'slot missing structured service contract or claims instantiated events')
        prerequisites = slot['fixed_service_prerequisites']
        needs_fixed_wash = 'DR' in fs and 'WM' not in fs
        need(len(prerequisites) == int(needs_fixed_wash), 'slot loses fixed washing prerequisite')
        for d in prerequisites:
            need(d['function'] == 'WM' and d['reference_asset_id'] == function_assets['WM'] and d['relation'] == 'same_load_wash_completes_before_drying', 'slot fixed wash uses wrong load/asset')
            need(d['coverage_counted'] is False and d['control_mode_in_this_slot'] == 'fixed' and d['event_id'] is None and d['must_resolve_before_instantiation'] is True, 'fixed predecessor counted or rescheduled as control')
        resources = {function_assets[f] for f in fs} | ({function_assets['WM']} if needs_fixed_wash else set())
        need(slot['resource_asset_ids'] == sorted(resources), 'slot resource list misses fixed predecessor asset')
        if slot['kind'] == 'joint_function':
            need(slot['resource_rule'] == 'follow structured service contracts and shared assets including fixed predecessor services', 'legacy conditional wash-before-dry string retained')
    blocks = h['weekend_design']['blocks']; members = {m['id'] for m in h['members']}
    realized = ('no_added_outing' if not blocks else 'split_household_outing' if any(set(x['participants']) < members for x in blocks) else 'short_outings' if max(x['end']-x['start'] for x in blocks) <= 120 else 'half_day_outing')
    w = h['weekend_realization']; requested = h['weekend_design']['requested_stratum']
    need(w == {'requested_stratum': requested, 'realized_stratum': realized, 'requested_matches_realized': requested == realized, 'basis': 'derived_from_experimental_activity_blocks', 'not_a_population_rate': True}, 'requested weekend design misreported as realized activity')
    return True
