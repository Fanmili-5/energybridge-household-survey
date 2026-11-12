"""Typed event requests for granular EV schedules, without changing old routes.

Scheduled charge intervals and a requested permission pause are distinct. A pause
may overlap the event even when A's nominal charging there is already zero.
"""
from benchmark.ab_generation.collection_relevance import direct as legacy_direct,explain as legacy_explain,_conflicts,_operation_ids
from benchmark.ab_generation.model import apply,overlap
from benchmark.ab_generation.power import site_capacity


def explicit_ev(component):
    return component['family']=='ev' and any(p.get('collection')=='controls' and p.get('type')=='rows' and p.get('identity')=='_unified_id' for p in component['patches'])


def direct(c,component,event):
    if c.get('source',{}).get('appliance_command_protocol')=='eb.primary_appliance_calls.v1':
        if component['family']=='ev':
            profile=component.get('profiles') or {}
            def energy(rows):
                return sum((r.get('power_kw',r.get('grid_kWh',0)*6))*overlap(r['start_min'],r['end_min'],event['start_min'],event['end_min'])/60 for r in rows)
            before=energy(profile.get('A',[]));after=energy(profile.get('B',[]))
            return [dict(kind='native_EV_event_energy_change',A_nominal_grid_kWh=before,B_nominal_grid_kWh=after,physical_outcomes_used=False)] if abs(before-after)>1e-9 else []
        window=component.get('magnitude',{}).get('native_preheat_window')
        if window:
            a,z,temp=window['A'];b,y,target=window['B'];points=sorted({event['start_min'],event['end_min'],a,z,b,y})
            changed=any(max(x,event['start_min'])<min(t,event['end_min']) and (temp if a<=x<z else None)!=(target if b<=x<y else None) for x,t in zip(points,points[1:]))
            return [dict(kind='native_single_preheat_window_change',A=window['A'],B=window['B'],actual_thermal_response_known=False)] if changed else []
    if not explicit_ev(component):return legacy_direct(c,component,event)
    pause=component['magnitude'].get('permission_pause_interval_min')
    if pause is None:return []  # Missing request semantics are not invented.
    lo,hi=pause
    if not overlap(lo,hi,event['start_min'],event['end_min']):return []
    return [dict(kind='event_charging_permission_pause',asset_id=component['asset_id'],
        start_min=max(lo,event['start_min']),end_min=min(hi,event['end_min']),
        request_interval_min=[lo,hi],scheduled_windows_are_not_connection_windows=True,
        nominal_response_can_be_zero=True)]


def explain(c,children,event):
    if c.get('source',{}).get('appliance_command_protocol')!='eb.primary_appliance_calls.v1' and not any(explicit_ev(r) for r in children):return legacy_explain(c,children,event)
    roots={r['id']:direct(c,r,event) for r in children}
    linked={k:dict(role='direct_event_request',evidence=v) for k,v in roots.items() if v}
    root_children=[r for r in children if r['id'] in linked]
    root_plan=apply(c['A'],[p for r in root_children for p in r['patches']])
    b=apply(c['A'],[p for r in children for p in r['patches']])
    root_ops=set().union(*(_operation_ids(r) for r in root_children)) if root_children else set()
    for child in children:
        if child['id'] in linked:continue
        own=_operation_ids(child);witness=[]
        introduced=_conflicts(root_plan,own,root_ops)-_conflicts(c['A'],own,root_ops)
        for kind,own_id,root_id in sorted(introduced-_conflicts(b,own,root_ops)):
            witness.append(dict(kind=kind+'_conflict_caused_by_event_request',support_operation_id=own_id,
                root_operation_id=root_id,absent_in_A=True,present_without_support=True,absent_with_support=True))
        if root_children and c.get('electrical') and child['family'] in ('washer','dishwasher','dryer','ev'):
            without=apply(c['A'],[p for r in children if r['id']!=child['id'] for p in r['patches']])
            old=set(site_capacity(c,c['A'])['known_excess_minutes'])
            introduced=(set(site_capacity(c,without)['known_excess_minutes']) & set(site_capacity(c,root_plan)['known_excess_minutes']))-old
            resolved=introduced-set(site_capacity(c,b)['known_excess_minutes'])
            if resolved:witness.append(dict(kind='known_schedule_supply_conflict_caused_by_event_request',minutes=sorted(resolved),physical_breaker_trip_claimed=False))
        if witness:linked[child['id']]=dict(role='support_event_request',root_component_ids=sorted(k for k,v in roots.items() if v),evidence=witness)
    missing=[r['id'] for r in children if r['id'] not in linked]
    return dict(passed=not missing,components=linked,unrelated_component_ids=missing,
        event_window_min=[event['start_min'],event['end_min']],positive_reduction_required=False,physical_outcomes_used=False)
