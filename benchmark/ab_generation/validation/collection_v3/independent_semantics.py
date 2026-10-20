"""Literal command/relevance audit without generation or dose-label imports."""
import argparse
from collections import Counter
from pathlib import Path
from benchmark.ab_generation.common import read,save,verify
from benchmark.ab_generation.model import apply
from benchmark.ab_generation.power import site_capacity


def at(plan,aid,t):
    rows=[r for r in plan['controls'] if r['kind']=='ac_setpoint' and r['asset_id']==aid and r['start_min']<=t<r['end_min']]
    if len(rows)!=1:raise ValueError('AMBIGUOUS_AC_COMMAND')
    return rows[0]


def collision(plan,a,b,kind):
    ops={o['operation_id']:o for o in plan['operations']};x,y=ops[a],ops[b]
    same=x['operator_id']==y['operator_id'] if kind=='operator' else x['room_id']==y['room_id']
    return same and max(x['start_min'],y['start_min'])<min(x['end_min'],y['end_min'])


def literal_errors(c,row,config):
    errors=[];a=c['A'];b=apply(a,row['patches']);event=config['event'];lo,hi=event['start_min'],event['end_min']
    components=row['components'];roots=set();root_ops=set();expected_axes=set()
    if row['features']['intensity']!='not_aggregated_use_amplitude_axes':errors.append('FALSE_OVERALL_INTENSITY')
    if any('intensity=' in t for t in row['tags']):errors.append('OVERALL_INTENSITY_REWARDED')
    if {p['asset_id'] for p in b['controls'] if p['kind']=='ac_setpoint'}-set(d['asset_id'] for d in c['devices']):errors.append('UNKNOWN_AC')
    for comp in components:
        family=comp['family'];aid=comp['asset_id'];m=comp['magnitude']
        direct=False
        for p in comp['patches']:
            if family in ('ac','water_heater'):
                key=m['axis']+'_setpoint_C' if family=='ac' else 'value_C'
                if max(p['start_min'],lo)<min(p['end_min'],hi):
                    direct |= any(r['asset_id']==aid and r['kind']==p['kind'] and r[key]!=p['values'][key]
                        and max(r['start_min'],p['start_min'],lo)<min(r['end_min'],p['end_min'],hi) for r in a['controls'])
            elif family=='ev':direct |= max(p['start_min'],lo)<min(p['end_min'],hi)
            elif p.get('collection')=='tasks':
                old={t['task_id']:t for t in a['tasks']}
                for t in p['rows']:
                    x=old[t['task_id']]
                    direct |= (x['start_min'],x['end_min'])!=(t['start_min'],t['end_min']) and (
                        max(x['start_min'],lo)<min(x['end_min'],hi) or max(t['start_min'],lo)<min(t['end_min'],hi))
        if direct:
            roots.add(comp['id'])
            root_ops.update(o['operation_id'] for p in comp['patches'] if p.get('collection')=='operations' for o in p['rows'])
            if comp['event_relevance']['role']!='direct_event_request':errors.append('MISSING_DIRECT_REASON')
        if family!='ac':
            expected_axes.add(family+'.'+('setpoint_offset' if family=='water_heater' else 'pause_and_slack' if family=='ev' else 'schedule_shift')+'='+comp['absolute_level'])
            continue
        ac=m['ac_intervention'];z=apply(a,comp['patches']);key=m['axis']+'_setpoint_C'
        left=min(p['start_min'] for p in comp['patches']);right=max(p['end_min'] for p in comp['patches'])
        sentinel=c['reference'].get('ac_control_contract',{}).get('cooling_off_fallback_C')
        ref=at(a,aid,lo)[key];enabled=paused=pre=event_minutes=0;diff=[];offset=[];raw_diff=[]
        for t in range(left,right,10):
            x,y=at(a,aid,t),at(z,aid,t)
            if {k:v for k,v in x.items() if k not in ('start_min','end_min')}=={k:v for k,v in y.items() if k not in ('start_min','end_min')}:continue
            xoff=sentinel is not None and x['cooling_setpoint_C']==sentinel
            yoff=sentinel is not None and y['cooling_setpoint_C']==sentinel
            enabled+=10*int(xoff and not yoff);paused+=10*int(not xoff and yoff)
            pre+=10*int(t<lo);event_minutes+=10*int(lo<=t<hi)
            raw_diff.append(abs(y[key]-x[key]))
            if not xoff and not yoff:diff.append(abs(y[key]-x[key]))
            if not yoff:offset.append(abs(y[key]-ref))
            phases=[p for p in ac['phases'] if p['start_min']<=t<p['end_min']]
            if len(phases)!=1:errors.append('AC_PHASE_COVERAGE_MISMATCH');continue
            p=phases[0];delta=None if xoff or yoff else y[key]-x[key]
            if p['same_time_setpoint_delta_C']!=delta:errors.append('FALLBACK_COUNTED_AS_TEMPERATURE_DOSE')
            if p['A']['compressor_running'] is not None or p['B']['compressor_running'] is not None:errors.append('INVENTED_COMPRESSOR_STATE')
            if p['A']['encoded_cooling_threshold_C']!=x['cooling_setpoint_C'] or p['B']['encoded_cooling_threshold_C']!=y['cooling_setpoint_C']:errors.append('AC_STATE_ENCODING_MISMATCH')
            if xoff and (p['A']['mode']!='cooling_stop_fallback' or p['A']['cooling_setpoint_C'] is not None):errors.append('FALLBACK_PRESENTED_AS_COMFORT_TARGET')
            if yoff and (p['B']['mode']!='cooling_stop_fallback' or p['B']['cooling_setpoint_C'] is not None):errors.append('FALLBACK_PRESENTED_AS_COMFORT_TARGET')
        value=max(offset,default=None);low,mid=config['ac_delta_C'][:2]
        temp='not_applicable' if value is None else 'none' if value==0 else 'small' if value<=low else 'medium' if value<=mid else 'large'
        timebin=lambda n:'none' if n==0 else 'small' if n<=10 else 'medium' if n<=30 else 'large'
        eventbin=lambda n:'none' if n==0 else 'small' if n<=20 else 'medium' if n<=40 else 'large'
        axes={'temperature_offset':temp,'preconditioning':timebin(pre),'additional_enable':timebin(enabled),'cooling_pause':eventbin(paused),
            'event_duration':eventbin(event_minutes)}
        mode='mixed' if enabled and paused else 'leave_cooling_stop_fallback' if enabled else 'request_cooling_stop_fallback' if paused else 'unchanged'
        expected={'additional_thermostat_enabled_min':enabled,'cooling_stop_requested_min':paused,'preconditioning_min':pre,
            'event_changed_min':event_minutes,'max_comparable_setpoint_delta_C':max(diff,default=None),
            'max_offset_from_occupied_reference_C':value,'amplitude_axes':axes,'state_change':mode}
        if any(ac.get(k)!=v for k,v in expected.items()):errors.append('AC_DOSE_AXIS_MISMATCH')
        if max(raw_diff,default=0)!=m['actual_max_command_delta_C']:errors.append('RAW_COMMAND_DELTA_MISMATCH')
        level='state_change' if mode!='unchanged' else 'multi_axis' if pre else temp
        if comp['absolute_level']!=level:errors.append('MISLEADING_AC_COMPONENT_LABEL')
        expected_axes.add('ac.control_state='+mode)
        expected_axes.update('ac.'+k+'='+v for k,v in axes.items() if v not in ('none','not_applicable'))
        if ac['native_availability_off_claimed'] or any(ac[k] is not None for k in ('actual_compressor_runtime_min','actual_room_temperature_C','response_kWh','whole_intervention_intensity')):errors.append('INVENTED_AC_OUTCOME')
    for comp in components:
        link=comp['event_relevance']
        if row['event_relevance']['components'].get(comp['id'])!=link:errors.append('COMPONENT_REASON_BINDING_MISMATCH')
        if comp['id'] in roots:continue
        if not roots or link['role']!='support_event_request' or not link['evidence']:
            errors.append('UNRELATED_COMPONENT');continue
        without=apply(a,[p for x in components if x['id']!=comp['id'] for p in x['patches']])
        for witness in link['evidence']:
            if witness['kind'].startswith(('operator_','room_')):
                own,root=witness['support_operation_id'],witness['root_operation_id'];kind=witness['kind'].split('_')[0]
                if root not in root_ops or collision(a,own,root,kind) or not collision(without,own,root,kind) or collision(b,own,root,kind):errors.append('FALSE_SUPPORT_CONSTRAINT_WITNESS')
            elif witness['kind']=='known_schedule_supply_conflict_caused_by_event_request':
                root_plan=apply(a,[p for x in components if x['id'] in roots for p in x['patches']])
                known=set(site_capacity(c,without)['known_excess_minutes']) & set(site_capacity(c,root_plan)['known_excess_minutes'])
                known-=set(site_capacity(c,a)['known_excess_minutes'])|set(site_capacity(c,b)['known_excess_minutes'])
                if not set(witness['minutes'])<=known or not witness['minutes']:errors.append('FALSE_SUPPLY_SUPPORT_WITNESS')
            else:errors.append('UNKNOWN_SUPPORT_WITNESS')
    if sorted(expected_axes)!=row['features']['amplitude_axes']:errors.append('AGGREGATED_AXIS_PROFILE_MISMATCH')
    if set(row['changed_assets'])!=set(row['asset_change_reasons']):errors.append('CHANGED_ASSET_HAS_NO_REASON')
    for aid,reasons in row['asset_change_reasons'].items():
        for reason in reasons:
            if reason['role']=='same_material_dependent_service_chain' and not any(t['asset_id']==aid and t['need_id']==reason['child_need_id'] and t.get('depends_on_need_id')==reason['parent_need_id'] for t in a['tasks']):errors.append('FALSE_MATERIAL_DEPENDENCY')
    if row['actual_outcomes'] is not None or row['human_acceptance'] is not None:errors.append('INVENTED_OUTCOME')
    return sorted(set(errors))


def audit(root):
    root=Path(root);verify(root);config=read(root/'DESIGN.json');selected=set(read(root/'ASSIGNMENT.json')['selected_ids'])
    checked=0;failures=[];relevance=engineering=0;statuses=Counter();roles=Counter()
    for p in sorted((root/'catalogues').glob('*.json.gz')):
        c=read(root/'contexts'/p.name);day=read(p)
        for row in day['rows']:
            checked+=1;bad=literal_errors(c,row,config)
            if bad:failures.append({'id':row['id'],'errors':bad})
            if row['id'] in selected:
                statuses.update([row['features']['event']]);roles.update(x['role'] for x in row['event_relevance']['components'].values())
        for ledger in ('relevance_diagnostics','engineering_diagnostics'):
            for item in day[ledger]:
                if item['repaired'] or item['replacement_generated']:failures.append({'case_id':c['case_id'],'errors':['DIAGNOSTIC_REPLACED']})
        relevance+=len(day['relevance_diagnostics']);engineering+=len(day['engineering_diagnostics'])
    return {'schema':'eb.collection.independent_semantics.v3','passed':not failures,'eligible_requests_checked':checked,
        'selected':len(selected),'selected_event_status':dict(statuses),'selected_component_roles':dict(roles),
        'unrelated_requests_retained':relevance,'engineering_requests_retained':engineering,
        'failures':failures,'new_engine_runs':0,'original_A_changed':False,'outcomes_used':False}


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--root',required=True);p.add_argument('--out',required=True);a=p.parse_args()
    result=audit(a.root);save(a.out,result);print({k:v for k,v in result.items() if k!='failures'})
    if not result['passed']:raise SystemExit(1)
