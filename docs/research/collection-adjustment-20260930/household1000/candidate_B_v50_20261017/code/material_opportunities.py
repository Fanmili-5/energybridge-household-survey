"""Choose supported request boundaries from A, never a successful B outcome.

This repair is scoped to the 500 old identical-command proposals. Its selection
criterion is command materiality, explicitly not measured VPP delivery or consent.
"""
import collections
from common import *
from event_proposals import eligible, continuous_thermal_pool, select
from thermal_flex import opportunity_options


def options(w, c, old_assignment):
    pool, future = eligible(c)
    assets = {x['asset_id']: x for x in w['parameter_pack']['devices']}
    choices = []
    joint = old_assignment['multi_event_policy'] == 'joint_all_events'
    for e in c['VPP_events']:
        es = c['VPP_events'] if joint else [e]
        lo, hi = e['start_min'], e['end_min']
        for family in ('washer', 'dishwasher'):
            for task in pool[family]:
                nid = task['need_id']
                load = next(x for x in c['A']['operations'] if x['kind'] == 'load' and x['need_id'] == nid)
                need = next(x for x in c['needs_A'] if x['need_id'] == nid)
                finish = max(x['end_min'] for x in c['A']['tasks'] if x['need_id'] in (nid, nid + ':dry'))
                duration = finish - task['start_min']
                if e['direction'] == 'down' and not overlap((task['start_min'], finish), (lo, hi)):
                    continue
                if e['direction'] == 'up' and any(z['direction'] == 'up' and overlap(
                        (task['start_min'], finish), (z['start_min'], z['end_min'])) for z in es):
                    continue
                for kind in ('program_timer', 'handling_shift'):
                    if kind == 'handling_shift' and nid not in future:
                        continue
                    # Moving the existing load shifts the program by the same delta.
                    earliest = max(DECISION, need['release_min'] + task['start_min'] - load['start_min']) \
                        if kind == 'handling_shift' else max(DECISION, load['end_min'])
                    earliest = max(earliest, task['start_min'] + DECISION - load['start_min']) \
                        if kind == 'handling_shift' else earliest
                    latest = need['deadline_min'] - duration - 10
                    targets = {lo} if e['direction'] == 'up' else {
                        z[k] - (duration if k == 'start_min' else 0)
                        for z in es if z['direction'] == 'down' for k in ('start_min', 'end_min')}
                    valid = [t for t in targets if earliest <= t <= latest and t != task['start_min'] and
                             all(z['direction'] != 'down' or not overlap((t, t + duration),
                                 (z['start_min'], z['end_min'])) for z in es)]
                    if not valid:
                        continue
                    target = min(valid, key=lambda t: (abs(t - task['start_min']), t))
                    choices.append({'mechanism': kind, 'family': family, 'selected_asset_id': task['asset_id'],
                                    'selected_need_id': nid, 'focus_event_id': e['event_id'],
                                    'target_start_min': target, 'input_overlap_minutes':
                                    max(0, min(finish, hi) - max(task['start_min'], lo)),
                                    'basis': 'VPP_boundary_with_A_load_release_program_duration_and_deadline'})
        for span in continuous_thermal_pool(pool['ac']):
            a, b = max(lo, span['start_min']), min(hi, span['end_min'])
            if a >= b:
                continue
            room = assets[span['asset_id']]['room_id']
            touched = [x for x in c['A']['controls'] if x['kind'] == 'ac_setpoint' and
                       assets[x['asset_id']]['room_id'] == room and overlap((a, b), (x['start_min'], x['end_min']))]
            if e['direction'] == 'up' and min(x['cooling_setpoint_C'] - x['heating_setpoint_C'] for x in touched) <= 2:
                continue
            choices.append({'mechanism': 'thermal_setpoint', 'family': 'ac',
                            'selected_asset_id': span['asset_id'], 'focus_event_id': e['event_id'],
                            'input_overlap_minutes': b - a,
                            'basis': 'existing_A_room_permission_intersects_event;dual_bounds_have_requested_margin'})
        for tank in pool['water_heater']:
            a, b = max(lo, tank['start_min']), min(hi, tank['end_min'])
            ceiling = min(65, assets[tank['asset_id']]['parameters']['maximum_C'])
            if a >= b or (e['direction'] == 'up' and tank['value_C'] >= ceiling) or (e['direction'] == 'down' and tank['value_C'] <= 5):
                continue
            choices.append({'mechanism': 'hotwater_target', 'family': 'water_heater',
                            'selected_asset_id': tank['asset_id'], 'focus_event_id': e['event_id'],
                            'input_overlap_minutes': b - a,
                            'basis': 'existing_A_tank_permission_intersects_event;target_within_hardware_bounds'})
        for ev in pool['ev']:
            start, end = ev['start_min'], ev['end_min']
            if e['direction'] == 'down':
                if not overlap((start, ev['actual_charge_end_min']), (lo, hi)) or end - start <= 10:
                    continue
            elif start >= lo or any(z['direction'] == 'up' and overlap(
                    (start, ev['actual_charge_end_min']), (z['start_min'], z['end_min'])) for z in es) or end <= lo + 10:
                continue
            choices.append({'mechanism': 'ev_delay', 'family': 'ev', 'selected_asset_id': ev['asset_id'],
                            'selected_need_id': ev['need_id'], 'focus_event_id': e['event_id'],
                            'input_overlap_minutes': max(0, min(ev['actual_charge_end_min'], hi) - max(start, lo)),
                            'basis': 'existing_real_connection_and_A_charge_timing;no_new_plug_or_target'})
    return choices


def select_request(w, c, old_assignment, family_counts):
    # A limited-opportunity offer may deliberately preserve a sensible routine.
    # Do not turn every such control case into a new comfort sacrifice merely
    # because another installed device could receive a different command.
    old = old_assignment['mechanism']
    if old in ('program_timer', 'handling_shift'):
        pool, future = eligible(c)
        programs = pool['washer'] + pool['dishwasher']
        if old == 'handling_shift': programs = [x for x in programs if x['need_id'] in future]
        event = next(e for e in c['VPP_events'] if e['event_id'] == old_assignment['focus_event_id'])
        es = c['VPP_events'] if old_assignment['multi_event_policy'] == 'joint_all_events' else [event]
        task = select(programs, c, event, 'program')
        finish = max(t['end_min'] for t in c['A']['tasks'] if t['need_id'] in (task['need_id'], task['need_id'] + ':dry'))
        if event['direction'] == 'down' and not any(e['direction'] == 'down' and overlap(
                (task['start_min'], finish), (e['start_min'], e['end_min'])) for e in es):
            return None
        if event['direction'] == 'up' and any(e['direction'] == 'up' and overlap(
                (task['start_min'], finish), (e['start_min'], e['end_min'])) for e in es):
            return None
    choices = options(w, c, old_assignment)
    if not choices:
        return None
    # Prefer a supported boundary for the intended mechanism. Otherwise reuse a
    # less-represented device family in this home's original design assignment.
    chosen = min(choices, key=lambda x: (
        x['mechanism'] != old, family_counts[x['family']],
        -min(90, x['input_overlap_minutes']),
        rank(c['case_id'], 'material_input_request_v50', x)))
    return {**old_assignment, **chosen,
            'candidate_class': 'actionable_A_input_opportunity_after_identical_request_review',
            'portfolio': None, 'family_event_assignments': {},
            'eligibility_checked_before_B': True,
            'source_mechanism': old, 'old_identical_commands_used_to_scope_revision': True,
            'selection_uses_command_materiality': True,
            'selection_uses_physical_response_constraint_outcome_or_acceptance': False,
            'selection_used_B_results': 'old_command_equivalence_only;not_physical_or_human_outcomes',
            'material_input_directive': True}
