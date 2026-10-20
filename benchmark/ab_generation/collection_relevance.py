"""Event-linked proposal domain, independent of successful load reduction.

Zero-net and adverse event rescheduling are roots. An outside-event component
needs a literal dependency/resource witness; sharing a household is insufficient.
"""
from .model import apply, overlap
from .power import site_capacity


def direct(c, component, event):
    evidence = []
    if component['family'] in ('ac', 'water_heater'):
        key = component['magnitude'].get('axis', 'tank')
        key = key + '_setpoint_C' if component['family'] == 'ac' else 'value_C'
        for patch in component['patches']:
            if not overlap(patch['start_min'], patch['end_min'], event['start_min'], event['end_min']):
                continue
            if any(r['asset_id'] == patch['asset_id'] and r['kind'] == patch['kind']
                   and max(r['start_min'],patch['start_min'],event['start_min']) < min(r['end_min'],patch['end_min'],event['end_min'])
                   and r[key] != patch['values'][key] for r in c['A']['controls']):
                evidence.append({'kind':'event_thermal_command','asset_id':patch['asset_id'],
                    'start_min':max(patch['start_min'],event['start_min']),
                    'end_min':min(patch['end_min'],event['end_min']), 'physical_response':'unknown'})
    elif component['family'] == 'ev':
        for patch in component['patches']:
            if overlap(patch['start_min'],patch['end_min'],event['start_min'],event['end_min']):
                evidence.append({'kind':'event_charging_permission_pause','asset_id':component['asset_id'],
                    'start_min':max(patch['start_min'],event['start_min']),
                    'end_min':min(patch['end_min'],event['end_min'])})
    else:
        original={r['task_id']:r for r in c['A']['tasks']}
        for patch in component['patches']:
            if patch.get('collection') != 'tasks':continue
            for task in patch['rows']:
                a=original[task['task_id']]
                if (a['start_min'],a['end_min']) != (task['start_min'],task['end_min']) and (
                        overlap(a['start_min'],a['end_min'],event['start_min'],event['end_min']) or
                        overlap(task['start_min'],task['end_min'],event['start_min'],event['end_min'])):
                    evidence.append({'kind':'event_service_reschedule','asset_id':task['asset_id'],
                        'task_id':task['task_id'],'A_interval':[a['start_min'],a['end_min']],
                        'B_interval':[task['start_min'],task['end_min']]})
    return evidence


def _conflicts(plan, own_ids, other_ids):
    out=set()
    own=[o for o in plan['operations'] if o['operation_id'] in own_ids]
    other=[o for o in plan['operations'] if o['operation_id'] in other_ids]
    for a in own:
        for b in other:
            if not overlap(a['start_min'],a['end_min'],b['start_min'],b['end_min']):continue
            if a['operator_id']==b['operator_id']:
                out.add(('operator',a['operation_id'],b['operation_id']))
            if a['room_id']==b['room_id'] and not a['kind'].startswith('EV_') and not b['kind'].startswith('EV_'):
                out.add(('room',a['operation_id'],b['operation_id']))
    return out


def _operation_ids(child):
    return {r['operation_id'] for p in child['patches'] if p.get('collection')=='operations' for r in p['rows']}


def explain(c, children, event):
    """Root-first graph plus leave-one-component-out constraint witnesses.

    A support action must address a new conflict caused by the event-linked
    roots; a pre-existing A problem or a new gratuitous conflict is not a link.
    No energy sign, success label or human answer is an admission condition.
    """
    roots={r['id']:direct(c,r,event) for r in children}
    linked={k:{'role':'direct_event_request','evidence':v} for k,v in roots.items() if v}
    root_children=[r for r in children if r['id'] in linked]
    root_patches=[p for r in root_children for p in r['patches']]
    root_plan=apply(c['A'],root_patches)
    b=apply(c['A'],[p for r in children for p in r['patches']])
    root_ops=set().union(*(_operation_ids(r) for r in root_children)) if root_children else set()
    for child in children:
        if child['id'] in linked:continue
        witness=[];own=_operation_ids(child)
        introduced=_conflicts(root_plan,own,root_ops)-_conflicts(c['A'],own,root_ops)
        resolved=introduced-_conflicts(b,own,root_ops)
        for kind,own_id,root_id in sorted(resolved):
            witness.append({'kind':kind+'_conflict_caused_by_event_request',
                'support_operation_id':own_id,'root_operation_id':root_id,
                'absent_in_A':True,'present_without_support':True,'absent_with_support':True})
        if root_children and c.get('electrical') and child['family'] in ('washer','dishwasher','dryer','ev'):
            # Known scheduled power only. Thermal upper envelopes cannot prove
            # an actual overload, so are never used as a necessity witness.
            without=apply(c['A'],[p for r in children if r['id']!=child['id'] for p in r['patches']])
            old=set(site_capacity(c,c['A'])['known_excess_minutes'])
            new=(set(site_capacity(c,without)['known_excess_minutes']) & set(site_capacity(c,root_plan)['known_excess_minutes']))-old
            resolved_power=new-set(site_capacity(c,b)['known_excess_minutes'])
            if resolved_power:
                witness.append({'kind':'known_schedule_supply_conflict_caused_by_event_request',
                    'minutes':sorted(resolved_power),'physical_breaker_trip_claimed':False})
        if witness:
            linked[child['id']]={'role':'support_event_request','root_component_ids':sorted(roots_id for roots_id in roots if roots[roots_id]),
                'evidence':witness}
    missing=[r['id'] for r in children if r['id'] not in linked]
    return {'passed':not missing,'components':linked,'unrelated_component_ids':missing,
        'event_window_min':[event['start_min'],event['end_min']],
        'positive_reduction_required':False,'physical_outcomes_used':False}


def asset_reasons(c, children, explanation):
    """Account for physical dryer assets inside a material-linked service unit."""
    out={}
    original={r['task_id']:r for r in c['A']['tasks']}
    for child in children:
        link=explanation['components'][child['id']]
        for patch in child['patches']:
            if patch['type']!='rows':
                out.setdefault(patch['asset_id'],[]).append({'component_id':child['id'],**link})
                continue
            for r in patch['rows']:
                key=patch['identity'];a=next(x for x in c['A'][patch['collection']] if x[key]==r[key])
                if r==a:continue
                aid=r['asset_id']
                if aid==child['asset_id'] or any(e.get('asset_id')==aid for e in link['evidence']):
                    reason={'component_id':child['id'],**link}
                else:
                    task=next(t for t in original.values() if t['asset_id']==aid and t.get('depends_on_need_id')==child['service_need_id'])
                    reason={'component_id':child['id'],'role':'same_material_dependent_service_chain',
                        'parent_need_id':task['depends_on_need_id'],'child_need_id':task['need_id'],
                        'mechanism':child['mechanism'],'necessity_or_uniqueness_claimed':False}
                if reason not in out.setdefault(aid,[]):out[aid].append(reason)
    return out
