"""Separate malformed data, given-constraint failures, physical unknowns and consent."""
import collections
from common import *

def active_signature(plan,minute):
    def clip(rows):
        result=[]
        for r in rows:
            if r['start_min']<minute:
                q=copy.deepcopy(r);q['end_min']=min(q['end_min'],minute)
                # Derived EV end/energy metadata describes the future, not prior commands.
                if q.get('kind')=='ev_charge_window':
                    q={k:q[k]for k in('asset_id','kind','need_id','start_min','end_min','stop_at_target_soc')}
                result.append(q)
        return sorted(result,key=canonical)
    return {k:clip(plan[k])for k in('tasks','operations','controls')}

def integrity(w,c,plan):
    bad=[];assets={d['asset_id']:d for d in w['parameter_pack']['devices']};needs={n['need_id']:n for n in c['needs_A']}
    if active_signature(c['A'],DECISION)!=active_signature(plan,DECISION):bad.append('PREDECISION_HISTORY_CHANGED')
    for key,ident in(('tasks','task_id'),('operations','operation_id')):
        if sorted(x[ident]for x in plan[key])!=sorted(x[ident]for x in c['A'][key]):bad.append('INVENTED_OR_DROPPED_'+key.upper())
    evops=lambda p:[o for o in p['operations']if o['kind'].startswith('EV_')]
    if evops(plan)!=evops(c['A']):bad.append('EV_HANDLING_CHANGED_OR_FILLER')
    for key in('tasks','operations','controls'):
        for x in plan[key]:
            if x['asset_id']not in assets:bad.append('UNKNOWN_ASSET');continue
            if not isinstance(x['start_min'],int)or not isinstance(x['end_min'],int)or x['start_min']>=x['end_min']:bad.append('INVALID_INTERVAL')
            if x['start_min']%10 or x['end_min']%10:bad.append('NON_TEN_MINUTE_COMMAND')
            if x.get('need_id')and x['need_id']not in needs:bad.append('INVENTED_SERVICE')
            if key=='tasks':
                if x['kind']not in assets[x['asset_id']]['types']:bad.append('ABSENT_FUNCTION')
                if x['end_min']-x['start_min']!=(120 if x['kind']=='washer'else 90):bad.append('ALTERED_PROGRAM_DURATION')
            if key=='operations'and(x['kind']not in('load','unload','EV_plug','EV_unplug')or x['end_min']-x['start_min']!=10):bad.append('FAKE_HANDLING')
            if x['kind']=='tank_setpoint'and not 5<=x['value_C']<=assets[x['asset_id']]['parameters']['maximum_C']:bad.append('TANK_HARDWARE_BOUND')
            if x['kind']=='ac_setpoint'and x['cooling_setpoint_C']-x['heating_setpoint_C']<2:bad.append('HVAC_DEADBAND')
            if x['kind']=='ev_charge_window'and(x['actual_charge_end_min']>x['end_min']or not 0<x['last_step_power_fraction']<=1+1e-8):bad.append('EV_PROJECTION_OUTSIDE_WINDOW')
    for t in plan['tasks']:
        if t['kind']=='dryer':
            prior=next((a for a in plan['tasks']if a['need_id']==t['upstream_need_id']),None)
            if prior is None or prior['end_min']!=t['start_min']or prior['asset_id']!=t['asset_id']:bad.append('BROKEN_AUTOMATIC_WASH_DRY_CHAIN')
    windows=collections.defaultdict(list)
    for x in plan['controls']:
        if x['kind']=='ac_setpoint':windows[x['asset_id']].append((x['start_min'],x['end_min']))
    if any(any(a[1]>b[0]for a,b in zip(sorted(seq),sorted(seq)[1:]))for seq in windows.values()):bad.append('OVERLAPPING_HVAC_COMMANDS')
    return sorted(set(bad))

def assess(w,c,plan):
    flags=[];opfail=collections.defaultdict(list);batch=[];ev=[];assets={d['asset_id']:d for d in w['parameter_pack']['devices']}
    needs={n['need_id']:n for n in c['needs_A']};ops=plan['operations'];slots=collections.defaultdict(list)
    def flag(code,nid=None,details=None):
        row={'code':code}
        if nid:row['need_id']=nid
        if details is not None:row['details']=details
        if row not in flags:flags.append(row)
    blocks=[];daymap={}
    for d in c['days']:
        base=(dt.date.fromisoformat(d['date'])-dt.date.fromisoformat(c['date'])).days*1440;daymap[base//1440]=d
        blocks +=[(r['room_id'],base+r['start_min'],base+r['end_min'])for r in d['shared']['facility_reservations']]
        blocks +=[(w['activity_contract']['room_map']['bath'],base+t,base+t+10)for t in d['activity']['family_context']['bath_times_min'].values()]
    for o in ops:
        if o['start_min']<DECISION:continue
        day=daymap.get(o['start_min']//1440);local=o['start_min']%1440;oid=o['operation_id']
        if day is None:opfail[oid].append('CONTEXT_HORIZON_EXCEEDED')
        elif not any(a<=local and local+10<=b for a,b in day['activity']['operator_windows_min'].get(o['operator_id'],[])):opfail[oid].append('OPERATOR_UNAVAILABLE')
        if any(room==o['room_id']and overlap((a,b),(o['start_min'],o['end_min']))for room,a,b in blocks):opfail[oid].append('FACILITY_RESERVED')
        for t in range(o['start_min'],o['end_min'],10):
            slots[('person',o['operator_id'],t)].append(oid);slots[('room',o['room_id'],t)].append(oid)
    for key,ids in slots.items():
        if len(ids)>1:
            for oid in ids:opfail[oid].append('OPERATOR_DOUBLE_BOOKED'if key[0]=='person'else'FACILITY_DOUBLE_BOOKED')
    for o in ops:
        for f in sorted(set(opfail[o['operation_id']])):flag(f,o['need_id'],{'operation_id':o['operation_id'],'requested_min':o['start_min']})
    holds=collections.defaultdict(list)
    for load in sorted((o for o in ops if o['kind']=='load'),key=lambda o:(o['start_min'],o['operation_id'])):
        nid=load['need_id'];n=needs[nid];ts=[t for t in plan['tasks']if t['need_id']in(nid,nid+':dry')]
        unload=next((o for o in ops if o['need_id']==nid and o['kind']=='unload'),None)
        if not ts or unload is None:continue # truncated, unchanged history at extraction boundary
        first=min(t['start_min']for t in ts);end=max(t['end_min']for t in ts);reasons=[]
        if load['start_min']<n['release_min']:reasons.append('LOAD_BEFORE_SERVICE_RELEASE')
        if load['end_min']>first:reasons.append('PROGRAM_BEFORE_LOADING')
        if first-load['end_min']>720:reasons.append('GIVEN_PRELOAD_BOUND_EXCEEDED')
        if any(overlap((load['start_min'],unload['end_min']),(a,b))for a,b in holds[load['asset_id']]):reasons.append('ASSET_STILL_OCCUPIED')
        blocked=bool(opfail[load['operation_id']])or bool(reasons)
        if unload['start_min']<end:reasons.append('RETRIEVAL_BEFORE_COMPLETION')
        if unload['end_min']>n['deadline_min']:reasons.append('SERVICE_DEADLINE_MISSED')
        if unload['start_min']-end>n['maximum_retrieval_wait_min']:reasons.append('GIVEN_RETRIEVAL_WAIT_EXCEEDED')
        if max(end,unload['end_min'])>=DECISION:
            for f in reasons:flag(f,nid)
        unloaded=not blocked and not opfail[unload['operation_id']]and unload['start_min']>=end
        if not blocked:holds[load['asset_id']].append((load['start_min'],unload['end_min']if unloaded else 4320))
        status='not_started_under_given_constraints'if blocked else('ran_but_not_collected'if not unloaded else('collected_with_contract_violation'if reasons else'completed_within_given_constraints'))
        if max(end,unload['end_min'])>=DECISION:batch.append({'need_id':nid,'status':status,'program_executed':not blocked,'collected':unloaded,'requested_end_min':end,'requested_retrieval_min':unload['start_min'],'reasons':reasons})
    evgroups=collections.defaultdict(list)
    for x in plan['controls']:
        if x['kind']=='ev_charge_window':evgroups[x['need_id']].append(x)
    for nid,windows in evgroups.items():
        if not any(x['start_min']>=DECISION for x in windows):continue
        n=needs[nid];p=assets[n['asset_id']]['parameters'];related={o['kind']:o for o in ops if o['need_id']==nid}
        plug=related.get('EV_plug');unplug=related.get('EV_unplug')
        if not plug or not unplug:continue
        available=0.
        for x in windows:
            a=max(x['start_min'],plug['end_min']);b=min(x['end_min'],unplug['start_min'],n['departure_min'])
            available+=max(0,b-a)/60*p['charger_kw']*p['efficiency']
            if x['start_min']<plug['end_min']or x['end_min']>unplug['start_min']:flag('CHARGE_OUTSIDE_REAL_CONNECTION',nid)
        short=max(0,n['quantity']-available)
        if short>1e-6:flag('EV_TARGET_ENERGY_IMPOSSIBLE_IN_WINDOW',nid,{'shortfall_battery_kWh':short})
        ev.append({'need_id':nid,'given_target_soc':n['required_departure_soc'],'battery_energy_required_kWh':n['quantity'],
                   'window_energy_upper_bound_kWh':available,'unavoidable_target_shortfall_kWh':short,
                   'departure_soc_upper_bound_from_common_connection_state':n['required_departure_soc']-short/p['capacity_kwh'],
                   'basis':'fixed-power upper bound at first changed connection;subsequent recovery and physical rollout remain pending'})
    # Certain electric conflicts only: omit HVAC/tank rather than invent thermal power.
    loads=collections.defaultdict(float)
    for t in plan['tasks']:
        p=assets[t['asset_id']]['parameters'];kw=p.get(t['kind'],p)['power_kw']
        for m in range(t['start_min'],t['end_min'],10):loads[m]+=kw
    for x in plan['controls']:
        if x['kind']=='ev_charge_window':
            for m in range(x['start_min'],x['actual_charge_end_min'],10):loads[m]+=assets[x['asset_id']]['parameters']['charger_kw']*(x['last_step_power_fraction']if m==x['actual_charge_end_min']-10 else 1)
    pk=w['parameter_pack'];peak=max((v+pk['background_reserved_kw']for m,v in loads.items()if DECISION<=m<4320),default=pk['background_reserved_kw'])
    if peak>pk['home_service_limit_kw']+1e-7:flag('REQUESTED_KNOWN_POWER_EXCEEDS_INLET',details={'known_load_lower_bound_kw':peak,'given_limit_kw':pk['home_service_limit_kw']})
    pending=any(x['kind']in('ac_setpoint','tank_setpoint')for x in plan['controls'])
    return {'integrity_errors':integrity(w,c,plan),'constraint_flags':flags,'given_constraints_feasible':not flags,
            'batch_execution_under_given_resources':batch,'EV_window_upper_bounds':ev,'requested_known_load_peak_lower_bound_kw':peak,
            'full_physical_execution_status':'pending','energy_cost_thermal_comfort_difference':None,
            'thermal_delivery_pending':pending,'human_acceptance':None,'no_automatic_repair_helper_or_rejection_filter':True}
