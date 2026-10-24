"""Read-only declaration/plan compatibility checks; no simulation or labels.

A life conflict in B is retained, while an A inconsistency is a baseline finding.
An action needing consent is neither an engineering error nor rejection truth.
"""
import datetime as dt
from .core import digest, require

def clock(minute):
    day, minute = divmod(minute, 1440)
    return ('次日' if day == 1 else f'{day:+d}日' if day else '') + f'{minute//60:02d}:{minute%60:02d}'


def overlaps(lo, hi, a, b): return max(lo, a) < min(hi, b)


def containing(windows, lo, hi): return any(a <= lo and hi <= b for a, b in windows)


def audit_case(case, c, profile, p, cal_by_date):
    require(c['source']['A_case_sha256'] == case['bindings']['source_A_case_sha256'], 'A_LINEAGE_CHANGED')
    hid, date = case['household_id'], case['date']; asset = {d['asset_id']: d for d in profile['devices']}
    issues = []; changes = []; base = dt.date.fromisoformat(date)
    for arm in ('A', 'B'):
        plan = case['plans'][arm]
        for group in ('tasks', 'operations', 'controls'):
            for x in plan[group]:
                if x['asset_id'] not in asset:
                    issues.append({'category': 'engineering', 'code': 'UNOWNED_DEVICE', 'arm': arm, 'group': group})
                if x['start_min'] >= x['end_min']:
                    issues.append({'category': 'engineering', 'code': 'NONPOSITIVE_INTERVAL', 'arm': arm, 'group': group})
        for op in plan['operations']:
            if not op['need_id'].startswith(date + ':'): continue
            mid = op['operator_id']; lo, hi = op['start_min'], op['end_min']
            allowed = c['authority']['assets'][op['asset_id']]['authorized_operator_ids']
            if mid not in allowed:
                issues.append({'category': 'authority', 'code': 'HANDLER_NOT_AUTHORIZED', 'arm': arm, 'operation_id': op['operation_id']})
            if not containing(c['operator_windows'].get(mid, []), lo, hi):
                reason = []
                for delta in range(lo // 1440, (hi - 1) // 1440 + 1):
                    d = str(base + dt.timedelta(days=delta)); day = cal_by_date.get(d)
                    if day:
                        reason += [{'date': d, 'activity': e['activity'], 'start_min': e['start_min'], 'end_min': e['end_min']}
                                   for e in day['calendars'].get(mid, [])
                                   if overlaps(lo, hi, delta*1440+e['start_min'], delta*1440+e['end_min'])]
                issues.append({'category': 'baseline_inconsistency' if arm == 'A' else 'life_conflict',
                               'code': 'HANDLING_OUTSIDE_ORIGINAL_AVAILABILITY', 'arm': arm,
                               'operation_id': op['operation_id'], 'kind': op['kind'], 'member_id': mid,
                               'start_min': lo, 'end_min': hi, 'time': clock(lo)+'—'+clock(hi), 'calendar_overlap': reason})
        tasks = {x['need_id']: x for x in plan['tasks']}
        needs = {n['need_id']: n for n in c['needs']}
        for need, t in tasks.items():
            if not need.startswith(date + ':'): continue
            upstream = t.get('upstream_need_id', t.get('depends_on_need_id', needs.get(need, {}).get('upstream_need_id')))
            if upstream in tasks and t['start_min'] < tasks[upstream]['end_min']:
                issues.append({'category': 'engineering', 'code': 'DRY_BEFORE_WASH_END', 'arm': arm, 'need_id': need})
            if need in needs and (t['start_min'] < needs[need]['release_min'] or t['end_min'] > needs[need]['deadline_min']):
                issues.append({'category': 'baseline_inconsistency' if arm == 'A' else 'service_conflict',
                               'code': 'PROGRAM_OUTSIDE_ORIGINAL_SERVICE_WINDOW', 'arm': arm, 'need_id': need})
        ops = [o for o in plan['operations'] if o['need_id'].startswith(date + ':')]
        for i, a in enumerate(ops):
            for b in ops[i + 1:]:
                if a['operator_id'] == b['operator_id'] and overlaps(a['start_min'], a['end_min'], b['start_min'], b['end_min']):
                    issues.append({'category': 'baseline_inconsistency' if arm == 'A' else 'life_conflict',
                                   'code': 'ONE_PERSON_SIMULTANEOUS_MANUAL_OPERATIONS', 'arm': arm,
                                   'operation_ids': [a['operation_id'], b['operation_id']]})
        for op in ops:
            t = tasks.get(op['need_id'])
            if not t: continue
            chain = [v for k, v in tasks.items() if k in (op['need_id'], op['need_id'] + ':dry') and v['asset_id'] == op['asset_id']]
            first, finish = min(v['start_min'] for v in chain), max(v['end_min'] for v in chain)
            n = needs.get(op['need_id'], {})
            if op['kind'].startswith('load') and op['end_min'] > first:
                issues.append({'category':'engineering','code':'LOAD_AFTER_PROGRAM_START','arm':arm,'operation_id':op['operation_id']})
            if op['kind'].startswith('unload') and op['start_min'] < finish:
                issues.append({'category':'engineering','code':'UNLOAD_BEFORE_PROGRAM_END','arm':arm,'operation_id':op['operation_id']})
            checks = []
            if op['kind'].startswith('load'):
                wait = first - op['end_min']
                if n.get('timer_allowed') is False and wait != 0: checks.append('TIMER_NOT_DECLARED_ALLOWED')
                if wait > n.get('maximum_preload_wait_min', float('inf')): checks.append('PRELOAD_WAIT_EXCEEDS_DECLARATION')
                if op['start_min'] < n.get('release_min', -float('inf')): checks.append('LOAD_BEFORE_ORIGINAL_RELEASE')
            if op['kind'].startswith('unload'):
                if op['start_min'] - finish > n.get('maximum_retrieval_wait_min', float('inf')): checks.append('RETRIEVAL_WAIT_EXCEEDS_DECLARATION')
                if op['end_min'] > n.get('deadline_min', float('inf')): checks.append('RETRIEVAL_AFTER_SERVICE_DEADLINE')
            issues += [{'category':'baseline_inconsistency' if arm == 'A' else 'service_conflict', 'code':code, 'arm':arm,
                        'operation_id':op['operation_id']} for code in checks]
    before = {t['task_id']: t for t in case['plans']['A']['tasks']}
    after = {t['task_id']: t for t in case['plans']['B']['tasks']}
    shift_limit = profile['role_policy'].get('service_policy', {}).get('reschedule_limit_min')
    for tid in sorted(set(before) | set(after)):
        a, b = before.get(tid), after.get(tid)
        if a == b: continue
        if a and b:
            delta = b['start_min'] - a['start_min']
            changes.append({'kind': a['kind'], 'task_id': tid, 'A_start': clock(a['start_min']), 'B_start': clock(b['start_min']), 'shift_min': delta})
            if shift_limit is not None and abs(delta) > shift_limit:
                issues.append({'category': 'needs_additional_consent', 'code': 'SHIFT_EXCEEDS_PREEXISTING_BOUND',
                               'arm': 'B', 'task_id': tid, 'shift_min': delta, 'original_bound_min': shift_limit})
            if a['end_min']-a['start_min'] != b['end_min']-b['start_min']:
                issues.append({'category': 'needs_additional_consent', 'code': 'PROGRAM_DURATION_CHANGED', 'arm': 'B', 'task_id': tid,
                               'A_duration_min': a['end_min']-a['start_min'], 'B_duration_min': b['end_min']-b['start_min']})
        else:
            issues.append({'category': 'needs_additional_consent', 'code': 'TASK_ADDED_OR_REMOVED', 'arm': 'B', 'task_id': tid})
    ao = {x['operation_id']: x for x in case['plans']['A']['operations']}; bo = {x['operation_id']: x for x in case['plans']['B']['operations']}
    for oid in set(bo)-set(ao):
        issues.append({'category':'needs_additional_consent','code':'EXTRA_MANUAL_OPERATION','arm':'B','operation_id':oid})
    for oid in set(bo) & set(ao):
        if bo[oid]['operator_id'] != ao[oid]['operator_id']:
            issues.append({'category':'needs_additional_consent','code':'HANDLER_CHANGED','arm':'B','operation_id':oid})
    for change in case['changes']:
        if change['group'] != 'controls': continue
        a, b = change['A'], change['B']; lo, hi = change['start_min'], change['end_min']
        kind, aid = change['kind'], change['asset_id']
        if kind == 'ac_setpoint':
            d = next(d for d in p['devices'] if d['asset_id'] == aid and d['kind'] == 'ac')
            for e in d['decision_conditions']['room_use_references']:
                if e['date'] != date or not overlaps(lo, hi, e['start_min'], e['end_min']): continue
                if e['activity'] in ('sleep', 'sleep_rest', 'nap', 'day_nap', 'home_work', 'work', 'school', 'work_or_school'):
                    issues.append({'category':'soft_preference_tension','code':'THERMAL_CHANGE_DURING_DECLARED_REST_OR_WORK',
                        'arm':'B','asset_id':aid,'activity':e['activity'],'time':clock(lo)+'—'+clock(hi),
                        'note':'changed command overlaps a protected use;not measured discomfort or automatic rejection'})
                    break
        if kind == 'tank_setpoint' and {x.get('value_C') for x in a} != {x.get('value_C') for x in b}:
            d = next(d for d in p['devices'] if d['asset_id'] == aid and d['kind'] == 'water_heater')
            bound = d['authorization']['bounds']['tank_setpoint_bounds_C']
            if bound is None or any(x.get('value_C') is None or not bound[0] <= x['value_C'] <= bound[1] for x in b):
                issues.append({'category':'needs_additional_consent','code':'TANK_SETPOINT_CHANGE_REQUIRES_CONFIRMATION_WITHOUT_BOUND','arm':'B',
                           'time':clock(lo)+'—'+clock(hi),'A_tank_setpoint_C':[x.get('value_C') for x in a], 'B_tank_setpoint_C':[x.get('value_C') for x in b],
                           'note':'tank command differs from outlet requirement;not a bath-time change or proof of insufficient hot water'})
        if kind == 'ev_charge_window' and a and not b:
            issues.append({'category':'service_risk','code':'A_CHARGING_WINDOW_REMOVED','arm':'B','time':clock(lo)+'—'+clock(hi),
                           'note':'does not itself prove target SOC failure;no new physical calculation'})
        if kind != 'ac_setpoint' or not a or not b: continue
        a, b = a[0], b[0]
        thermal = profile['role_policy'].get('thermal', {})
        heating_bound = thermal.get('heating_change_limit_C')
        if a.get('heating_setpoint_C') != b.get('heating_setpoint_C') and (heating_bound is None or
                a.get('heating_setpoint_C') is None or b.get('heating_setpoint_C') is None or
                abs(b['heating_setpoint_C'] - a['heating_setpoint_C']) > heating_bound):
            issues.append({'category':'needs_additional_consent','code':'HEATING_CHANGE_REQUIRES_MODE_SPECIFIC_CONFIRMATION','arm':'B',
                           'time':clock(lo)+'—'+clock(hi), 'A_heating_C':a.get('heating_setpoint_C'),'B_heating_C':b.get('heating_setpoint_C')})
        # The 40C cooling sentinel is not a preferred/actual room temperature.
        if b.get('_eb_cooling_stop_fallback'):
            occupied = any(overlaps(lo,hi,x,y) for x,y in c['occupancy'].get(asset[aid]['room_id'],[]))
            if occupied:
                issues.append({'category':'needs_additional_consent','code':'OCCUPIED_ROOM_COOLING_STOP_REQUEST','arm':'B','time':clock(lo)+'—'+clock(hi),
                               'note':'cooling suppression request;not 40C room temperature or proof heating stopped'})
        elif p['role'] == 'A' and b.get('cooling_setpoint_C', -100) > 26:
            issues.append({'category':'soft_preference_tension','code':'COOLING_REQUEST_ABOVE_EB_A_PREFERRED26','arm':'B','time':clock(lo)+'—'+clock(hi),
                           'requested_cooling_C':b['cooling_setpoint_C'], 'note':'command only;not actual room temperature'})
        if not (a.get('_eb_cooling_stop_fallback') or b.get('_eb_cooling_stop_fallback')) and a.get('cooling_setpoint_C') is not None and b.get('cooling_setpoint_C') is not None:
            delta=b['cooling_setpoint_C']-a['cooling_setpoint_C']; limit=profile['role_policy'].get('thermal',{}).get('temporary_increase_C')
            if limit is not None and delta>limit:
                issues.append({'category':'needs_additional_consent','code':'COOLING_DELTA_EXCEEDS_PREEXISTING_BOUND','arm':'B',
                               'time':clock(lo)+'—'+clock(hi),'delta_C':delta,'existing_bound_C':limit})
    for d in p['devices']:
        expected = {'ac': {'change_cooling_setpoint', 'change_heating_setpoint'},
                    'water_heater': {'change_tank_setpoint_preserving_draw_service'}}.get(d['kind'], set())
        require(expected <= set(d['authorization']['proposal_actions']), 'PERSONA_ACTION_ONTOLOGY_MISSING')
        changed = any(x['asset_id'] == d['asset_id'] and x.get('kind') in (d['kind'], 'tank_setpoint', 'ac_setpoint', 'ev_charge_window') for x in case['changes'])
        if changed and not d['authorization']['routine_DR_eligible']:
            issues.append({'category': 'needs_additional_consent', 'code': 'DEVICE_OUTSIDE_ROUTINE_EB_DR_SCOPE', 'arm': 'B', 'asset_id': d['asset_id'], 'kind': d['kind']})
    # Demand equality and target values are checked, not observed physical outcomes.
    require(case['context']['needs']['A'] == case['context']['needs']['B'], 'A_B_SERVICE_REQUIREMENTS_DIFFER')
    return {'case_id':case['case_id'],'date':date,'case_sha256':digest(case),'context_sha256':digest(c),
            'unchanged_declared_service_requirements':True,'confirmation_is_pending_not_a_generated_acceptance_label':True,
            'task_changes':changes,'findings':issues}
