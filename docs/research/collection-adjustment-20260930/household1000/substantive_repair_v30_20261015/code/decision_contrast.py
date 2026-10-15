"""Decision-relevant admission, distinct from request encoding and actor answers."""
import collections,sqlite3
from common import *
from contrast_core import control_segments,PROTOCOL

PARENT=BASE/'contrast_repair_v29_20261015'
def baseline_context(h,rr):
    path=OUT/'A_context'/h['household_id']/f'{rr["round_index"]:02d}.json'
    if path.exists():return read(path)
    receipt=read(PARENT/'runs/base7'/h['household_id']/f'{rr["round_index"]:02d}_A/RUN_RECORD.json')
    sql=PARENT/receipt['SQL_path'];assert sha(sql)==receipt['SQL_sha256']
    db=sqlite3.connect('file:'+str(sql)+'?mode=ro',uri=True)
    names=('Electricity:Facility','Cooling Coil Electricity Energy','Fan Electricity Energy','Water Heater Electricity Energy','Electric Equipment Electricity Energy','Zone Mean Air Temperature')
    query='''SELECT t.SimulationDays,t.Hour,t.Minute,d.Name,d.KeyValue,r.Value FROM ReportData r
      JOIN ReportDataDictionary d USING(ReportDataDictionaryIndex) JOIN Time t USING(TimeIndex)
      WHERE t.WarmupFlag=0 AND d.ReportingFrequency="Zone Timestep" AND t.SimulationDays>=8 AND d.Name IN ('''+','.join('?'for _ in names)+')'
    series={}
    for day,hour,minute,name,key,value in db.execute(query,names):
        i=round(((day-8)*1440+hour*60+minute)/10)-1
        if 0<=i<432:series.setdefault(name+'|'+(key or '').upper(),[None]*432)[i]=value if name=='Zone Mean Air Temperature'else value/3.6e6
    db.close();assert series and all(all(x is not None for x in v)for v in series.values())
    context={'schema':'eb.frozen_A_operating_context.v30','A_SQL_sha256':receipt['SQL_sha256'],
        'A_IDF_sha256':receipt['signature']['IDF_sha256'],'A_only_not_B_outcomes':True,'series':series}
    save(path,context);return context

def energy(ctx,name,start,end,keys=None):
    lo=max(0,start//10);hi=min(432,end//10)
    return sum(sum(v[lo:hi])for k,v in ctx['series'].items()if k.startswith(name+'|')and(keys is None or k.split('|')[1]in keys))

def source_evidence(w,p,context):
    """Predict an operative path using frozen A and the causal program ledger.

    The eventual B SQL is checked independently. No outcome-based ranking or
    actor labels, synthetic preferences, new mandatory needs or new devices.
    """
    from execution import realize
    a=p.get('service_execution_reference',{}).get('A')or realize(w,p['A'],p['world']['operator_windows'],p['needs_A'])
    b=realize(w,p['B'],p['world']['operator_windows'],p['needs_A'])
    paths=[];lo,hi=p['primary_evaluation_min'];event=p['event_window_min'];ds=w['parameter_pack']['devices']
    a_services={x['need_id']:x for x in a['program_services']}
    for item in b['program_services']:
        old=a_services[item['need_id']]
        if item['delivered_before_given_bound']!=old['delivered_before_given_bound']or item['program_chain_ran']!=old['program_chain_ran']:
            paths.append({'kind':'program_service_delivery','need_id':item['need_id'],'A':old,'B':item})
    aops={x['operation_id']:x for x in a['operations']}
    for item in b['operations']:
        old=aops.get(item['operation_id'])
        if old==item or not overlap((item['start_min'],item['end_min']),(lo,p['service_tail_min'][1])):continue
        if old is None or abs(old['start_min']-item['start_min'])>=20 or old['succeeded']!=item['succeeded']:
            paths.append({'kind':'concrete_manual_request','operation_id':item['operation_id'],
                'A':old,'B':item,'added_request_not_new_mandatory_service':old is None})
    atasks={x['task_id']:x for x in a['realized_tasks']};btasks={x['task_id']:x for x in b['realized_tasks']}
    for uid,t in atasks.items():
        z=btasks.get(uid)
        if z and abs(t['start_min']-z['start_min'])>=20 and overlap((t['start_min'],t['end_min']),(lo,hi)):
            dose=energy(context,'Electric Equipment Electricity Energy',*event,keys={t['asset_id'].upper()})
            if dose>=.1:paths.append({'kind':'actual_program_load_timing','task_id':uid,'A_event_device_kWh':dose})
    ag=a['vehicle_causal_trace']['grid_W'];bg=b['vehicle_causal_trace']['grid_W']
    for aid in ag:
        x=ag[aid];y=bg[aid];end=min(len(x),len(y),hi//10)
        changed=sum(abs(x[i]-y[i])/6000 for i in range(lo//10,end))
        if changed>=.1:paths.append({'kind':'actual_EV_charge_timing_or_dose','asset_id':aid,'absolute_changed_grid_kWh':changed})
    for seg in control_segments(p):
        if seg['kind']=='tank_setpoint'and seg['A']is not None and seg['B']is None:
            # A40min delay can merely move the same20min heating into the last
            # part of a60min event. Require B off over the entire event and
            # measure A's dose in that exact event, rather than sum endpoints.
            dose=energy(context,'Water Heater Electricity Energy',*event)
            if seg['start_min']<=event[0]and seg['end_min']>=event[1]and dose>=.1:
                paths.append({'kind':'active_hotwater_preheat_timing','A_event_heat_input_kWh':dose,
                    'B_heating_disabled_entire_event':True})
        if seg['A']is None or seg['B']is None:continue
        if seg['kind']=='tank_setpoint'and abs(seg['A']-seg['B'])>=5.:
            dose=energy(context,'Water Heater Electricity Energy',seg['start_min'],seg['end_min'])
            if dose>=.1:paths.append({'kind':'active_hotwater_heat_input','A_heat_input_kWh':dose,'delta_setpoint_C':seg['B']-seg['A']})
        # Active A cooling alone does not make a0.5C request produce a
        # discernible consequence. Apply the stronger level to the whole
        # AC-only mechanism; retain the independent post-EP threshold.
        if seg['kind']=='ac_setpoint'and abs(seg['A']-seg['B'])>=PROTOCOL['minimum_operative_AC_request_C']-1e-8:
            room=next(d['room_id']for d in ds if d['asset_id']==seg['asset_id'])
            keys={f'V16_AC_{i}_COIL'for i,d in enumerate(ds)if 'ac'in d['types']and d['room_id']==room}
            dose=energy(context,'Cooling Coil Electricity Energy',seg['start_min'],seg['end_min'],keys)
            if dose>=.1:paths.append({'kind':'active_zone_cooling','room_id':room,'A_coil_kWh':dose,'delta_setpoint_C':seg['B']-seg['A']})
    return {'passed':bool(paths),'paths':paths,'A_SQL_sha256':context['A_SQL_sha256'],
        'generic_confirmation_or_bound_only_counted':False,'B_EP_used':False},a,b

def outcome_evidence(p,r):
    """Actual delivered service/manual execution and visible model consequences."""
    paths=[];a=r['services']['A'];b=r['services']['B']
    for label,key in [('program_service_delivery','program_execution')]:
        aa={x['need_id']:x for x in a.get(key,[])}
        for x in b.get(key,[]):
            y=aa[x['need_id']]
            if any(x.get(k)!=y.get(k)for k in ('program_chain_ran','delivered_before_given_bound')):
                paths.append({'kind':label,'need_id':x['need_id']})
    ao={x['operation_id']:x for x in a['operation_results']};bo={x['operation_id']:x for x in b['operation_results']}
    for uid in ao.keys()|bo.keys():
        x=ao.get(uid);y=bo.get(uid)
        if x==y:continue
        if x is None or y is None or abs(x['start_min']-y['start_min'])>=20 or x['succeeded']!=y['succeeded']:
            paths.append({'kind':'actual_manual_request_or_feasibility','operation_id':uid,'A':x,'B':y})
    for scope,v in r['energy'].items():
        if abs(v['A']-v['B'])>=PROTOCOL['operative_energy_difference_kWh']:
            paths.append({'kind':'visible_reference_load_consequence','scope':scope,'A_kWh':v['A'],'B_kWh':v['B'],
                'not_bill_saving_or_human_perceptual_threshold':True})
    for typ in ('hot_water',):
        aa={x['need_id']:x for x in a.get(typ,[])}
        for x in b.get(typ,[]):
            y=aa[x['need_id']]
            if x['temperature_pass']!=y['temperature_pass']or abs(x['minimum_mixed_C']-y['minimum_mixed_C'])>=1.:
                paths.append({'kind':'delivered_hotwater','need_id':x['need_id'],'A_C':y['minimum_mixed_C'],'B_C':x['minimum_mixed_C']})
    aa={x['room_id']:x for x in a.get('room_air_by_scope',{}).get('event',[])}
    for x in b.get('room_air_by_scope',{}).get('event',[]):
        y=aa[x['room_id']]
        if max(abs(x[k]-y[k])for k in ('min_C','max_C'))>=PROTOCOL['operative_room_temperature_difference_C']:
            paths.append({'kind':'visible_room_temperature_consequence','room_id':x['room_id'],'A':y,'B':x,
                'not_calibrated_personal_comfort':True})
    for key in ('goals','trips'):
        aa=a.get('EV',{}).get(key,[]);bb=b.get('EV',{}).get(key,[])
        for x,y in zip(aa,bb):
            if any(x.get(k)!=y.get(k)for k in ('target_pass','trip_departed','reference_reserve_pass')):
                paths.append({'kind':'actual_EV_service','A':x,'B':y})
    return {'passed':bool(paths),'paths':paths,'rule_only_admitted':False,'human_acceptance_or_rejection':None}
