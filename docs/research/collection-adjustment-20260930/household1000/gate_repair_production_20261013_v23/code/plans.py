"""A before B: absolute service, program, handling and continuous-state contracts."""
import copy,datetime as dt,math
from common import *
from worlds import merge_ranges
from activity_model import dated
from needs import batch_contract

def active_wash(w,date):
    r=w['routine'];week=(date-dt.date(2025,1,6)).days//7
    return date.weekday() in r['wash_days'] and (r['wash_alternate_week_phase'] is None or week%2==r['wash_alternate_week_phase'])
def windows(w,date,days):
    return {o['operator_id']:[[d*1440+a,d*1440+b] for d in range(days) for a,b in dated(w,date+dt.timedelta(days=d))['operator_windows_min'][o['operator_id']]] for o in w['operating_context']['operators']}
def reserve(ops,ws,kind,nid,lo,hi,preferred=None,oid=None):
    order=sorted(ws,key=lambda k:(k!=oid,list(ws).index(k)))
    for opid in order:
        slots=[s for a,b in ws[opid] for s in range(((max(a,lo)+9)//10)*10,min(b,hi)-9,10)
               if all(o['operator_id']!=opid or not overlap((s,s+10),(o['start_min'],o['end_min'])) for o in ops)]
        if slots:
            s=min(slots,key=lambda s:(abs(s-(preferred if preferred is not None else lo)),s))
            o={'operation_id':nid+':'+kind,'kind':kind,'need_id':nid,'operator_id':opid,'start_min':s,'end_min':s+10,'duration_min':10}
            ops.append(o);return o
    raise ValueError('NO_HANDLING_WINDOW:'+nid+':'+kind)
def reserve_A(w,ops,ws,kind,nid,lo,hi,preferred=None,oid=None):
    try:return reserve(ops,ws,kind,nid,lo,hi,preferred,oid)
    except ValueError:
        # Common, explicit baseline resource. Only the booked ten minutes enter
        # B's resource ledger; additional helper availability is not assumed.
        contract=w['baseline_assistance_contract'];helper=contract['provider_id']
        day=lo//1440;candidate_windows=[[d*1440+contract['window_min'][0],d*1440+contract['window_min'][1]] for d in range(day,hi//1440+1)]
        booking=reserve(ops,{helper:candidate_windows},kind,nid,lo,hi,preferred,helper)
        booking['given_baseline_booking']=True
        ws.setdefault(helper,[]).append([booking['start_min'],booking['end_min']])
        ws[helper]=merge_ranges(ws[helper]);return booking

def operator_morning(w,date):
    day=dated(w,date)
    ws=sorted((a,b) for windows in day['operator_windows_min'].values() for a,b in windows)
    if not ws:raise ValueError('NO_DATED_OPERATOR_WINDOW:'+w['household_id']+':'+str(date))
    first=next(([a,b] for a,b in ws if a<720),ws[0])
    return first[0],min(first[1],first[0]+70)
def clearing_templates(w,date,days,ks):
    result=[]
    for day in range(days+1):
        dat=date+dt.timedelta(days=day);origin=day*1440
        morning_ws={oid:[[origin+a,origin+min(b,720)] for a,b in values if a<720] for oid,values in dated(w,dat)['operator_windows_min'].items()}
        for kind in ('washer','dishwasher'):
            if not ks[kind]:continue
            nid=dat.isoformat()+':carry-clearance:'+kind
            try:o=reserve(result,morning_ws,'reserved_carry_clearance',nid,origin,origin+720,oid=ks[kind][0]['operator_id'])
            except ValueError:
                helper=w['baseline_assistance_contract']['provider_id']
                o=reserve(result,{helper:[[origin+600,origin+720]]},'reserved_carry_clearance',nid,origin+600,origin+720,oid=helper)
                o['given_baseline_booking']=True
            o['clearing_for_kind']=kind;o['calendar_day_index']=day
    return result

def retrieve_A(w,ops,ws,templates,kind,nid,end,deadline,origin,oid):
    try:return reserve(ops,ws,'unload',nid,end,min(deadline,origin+1440),end+10,oid)
    except ValueError:
        template=next(t for t in templates if t['calendar_day_index']==origin//1440+1 and t['clearing_for_kind']==kind)
        if not end<=template['start_min'] or template['end_min']>deadline:raise ValueError('NO_CONTINUOUS_RETRIEVAL:'+nid)
        o={k:v for k,v in template.items() if k not in ('clearing_for_kind','calendar_day_index')}
        o.update(operation_id=nid+':unload',kind='unload',need_id=nid)
        ops.append(o)
        if o.get('given_baseline_booking'):ws.setdefault(o['operator_id'],[]).append([o['start_min'],o['end_min']])
        return o

def _make_A_raw(w,date,days=2):
    devices=w['parameter_pack']['devices'];ks={k:[d for d in devices if k in d['types']] for k in KINDS}
    ws=windows(w,date,days+1);templates=clearing_templates(w,date,days,ks);ops=copy.deepcopy(templates);needs=[];tasks=[];controls=[];r=w['routine']
    for day in range(days):
        dat=date+dt.timedelta(days=day);origin=day*1440;weekday=dat.weekday()
        morning,latest=operator_morning(w,dat);nm,nend=operator_morning(w,dat+dt.timedelta(days=1))
        day_context=dated(w,dat);family=day_context['family_context'];habit=r['stable_habit_variation_level']
        next_context=dated(w,dat+dt.timedelta(days=1))
        if ks['washer'] and active_wash(w,dat):
            evening=next((a for a,b in day_context['operator_windows_min'][w['operating_context']['operators'][0]['operator_id']] if b>=1050),morning)
            desired=max(570+habit*60 if evening<800 else evening+20, morning+20)
            # Habit level is declared design; frequency and batch mass are retained.
            for batch in range(r['wash_batches_each_active_day']):
                nid=f'{dat}:laundry:{batch+1}';d=ks['washer'][0]
                contract=batch_contract(w,dat,'washer',day_context,next_context)
                next_deadline=origin+contract['delivery_deadline_min']
                preferred=origin+desired+batch*220
                chain_minutes=120+(90 if ks['dryer'] else 0)
                load=reserve_A(w,ops,ws,'load',nid,origin+morning,min(preferred+20,next_deadline-chain_minutes-10),preferred-10,d['operator_id'])
                start=max(preferred,load['end_min']);end=start+120
                needs.append({'need_id':nid,'kind':'washer','batch_id':nid,'quantity':r['laundry_batch_kg'],'unit':'kg',
                    'duration_min':120,'release_min':origin+morning,'deadline_min':next_deadline-10,
                    'delivery_deadline_min':next_deadline,'loading_required':True,'requester':'household',
                    **contract,'delivery_deadline_min':next_deadline,'program_deadline_min':next_deadline-10,
                    'semantic_class':'mandatory_reference_service','usual_start_min':preferred,
                    'source_or_design_rule':'retained CRECS frequency and batch mass; EB120min; usual start conditioned on operator calendar and declared habit level; completion bound comes from independent given clean-batch handover',
                    'wearable_clothes_ready_at_program_end':False if ks['dryer'] else None,
                    'wearable_clothes_ready_after_required_chain':True if ks['dryer'] else None})
                tasks.append({'task_id':nid,'need_id':nid,'asset_id':d['asset_id'],'kind':'washer','start_min':start,'end_min':end})
                if ks['dryer']:
                    dn=nid+':dry';dd=ks['dryer'][0]
                    needs.append({'need_id':dn,'kind':'dryer','batch_id':nid,'upstream_need_id':nid,'quantity':r['laundry_batch_kg'],'unit':'kg',
                        'duration_min':90,'release_min':origin+morning,'deadline_min':next_deadline-10,'delivery_deadline_min':next_deadline,
                        'transfer_min':0,'semantic_class':'mandatory_reference_service',
                        'wearable_clothes_ready_at_program_end':True,
                        'source_or_design_rule':'same existing automatic washer-dryer physical combo and unchanged EB90min program'})
                    tasks.append({'task_id':dn,'need_id':dn,'asset_id':dd['asset_id'],'kind':'dryer','start_min':end,'end_min':end+90});end+=90
                retrieve=retrieve_A(w,ops,ws,templates,'washer',nid,end,next_deadline,origin,d['operator_id'])
                needs[-2 if ks['dryer'] else -1]['usual_retrieval_min']=retrieve['start_min']
        if ks['dishwasher']:
            d=ks['dishwasher'][0];nid=f'{dat}:dishes';release=origin+family['dinner_min']+30
            contract=batch_contract(w,dat,'dishwasher',day_context,next_context)
            next_deadline=origin+contract['delivery_deadline_min']
            load=reserve_A(w,ops,ws,'load',nid,release,next_deadline-100,release+10,d['operator_id'])
            start=load['end_min']+habit*10
            needs.append({'need_id':nid,'kind':'dishwasher','quantity':1,'unit':'EBprogram','duration_min':90,
                'release_min':release,'deadline_min':next_deadline-10,'delivery_deadline_min':next_deadline,
                **contract,'delivery_deadline_min':next_deadline,'program_deadline_min':next_deadline-10,
                'usual_start_min':start,'loading_required':True,'semantic_class':'mandatory_reference_service',
                'source_or_design_rule':'same household dinner completion -> load -> unchanged EB90min program -> independent next dinner inventory-use bound'})
            tasks.append({'task_id':nid,'need_id':nid,'asset_id':d['asset_id'],'kind':'dishwasher','start_min':start,'end_min':start+90})
            retrieve=retrieve_A(w,ops,ws,templates,'dishwasher',nid,start+90,next_deadline,origin,d['operator_id'])
            needs[-1]['usual_retrieval_min']=retrieve['start_min']
        if ks['water_heater']:
            d=ks['water_heater'][0];ts=[]
            for m in w['members']:
                s=origin+family['bath_times_min'][m['member_id']];ts.append(s)
                needs.append({'need_id':f'{dat}:bath:{m["member_id"]}','kind':'water_heater','requester':m['member_id'],
                    'release_min':s,'deadline_min':s+10,'quantity':30.,'unit':'L mixed water','target_C':r['mixed_target_C'],
                    'semantic_class':'mandatory_reference_service','source_or_design_rule':'unchanged30L/resident/10min reference draw; household bath reservation fits arrival, sleep and child assistance'})
            controls.append({'asset_id':d['asset_id'],'kind':'tank_setpoint','start_min':min(ts)-180,'end_min':max(ts)+40,'value_C':r['tank_setpoint_C']})
        if ks['ac'] and 5<=dat.month<=9:
            for d in ks['ac']:
                intervals=[(m,i) for m in w['members'] for i in day_context['member_calendars'][m['member_id']] if i['location']=='home' and i['room_id']==d['room_id']]
                groups=merge_ranges([[i['start_min'],i['end_min']] for m,i in intervals])
                for ix,(a,b) in enumerate(groups):
                    requesters=sorted({m['member_id'] for m,i in intervals if overlap((a,b),(i['start_min'],i['end_min']))})
                    sleeping=any(i['activity'] in ('sleep_rest','day_nap') and overlap((a,b),(i['start_min'],i['end_min'])) for m,i in intervals)
                    needs.append({'need_id':f'{dat}:cooling:{d["asset_id"]}:{ix}','kind':'ac','asset_id':d['asset_id'],
                        'requester':requesters,'release_min':origin+a,'deadline_min':origin+b,'quantity':b-a,'unit':'occupied served-room reference minutes',
                        'served_rooms':[d['room_id']],'includes_given_sleep_service':sleeping,
                        'reference_setpoint_C':26.,'reference_upper_control_C':d['reference_upper_setpoint_C'],
                        'semantic_class':'given_reference_control_service','source_or_design_rule':'R05 dated person room, including declared sleep/nap control;26C/27C are given controls, not measured comfort'})
                    controls.append({'asset_id':d['asset_id'],'kind':'ac_setpoint','start_min':origin+a,'end_min':origin+b,'value_C':26.})
        journey=day_context['transport']
        if ks['ev'] and journey:
            d=ks['ev'][0];dep,arr=journey['departure_min'],journey['arrival_min']
            next_context=dated(w,dat+dt.timedelta(days=1));next_journey=next_context['transport']
            next_dep=next_journey['departure_min'] if next_journey else 1080
            nid=f'{dat}:trip';s=origin+arr;e=origin+1440+next_dep
            charge_minutes=math.ceil(journey['traction_kWh']/(d['parameters']['charger_kw']*d['parameters'].get('efficiency',.92))*60/10)*10
            plug=reserve_A(w,ops,ws,'EV_plug',nid,s,e-charge_minutes-10,s,d['operator_id'])
            unplug=reserve_A(w,ops,ws,'EV_unplug',nid,plug['end_min']+charge_minutes,e,e-10,d['operator_id'])
            needs.append({'need_id':nid,'kind':'ev','asset_id':d['asset_id'],'requester':d['operator_id'],
                'release_min':s,'deadline_min':e,'connection_start_min':plug['end_min'],'departure_min':e,'trip_departure_min':origin+dep,
                'quantity':journey['traction_kWh'],'unit':'kWh given traction service','required_departure_soc':r['EV_target_soc'],
                'next_access_is_actual_trip':next_journey is not None,'journey':journey,
                'semantic_class':'trip_service_and_separate_reference_access_target',
                'source_or_design_rule':'R04 dated journey dose aligned to given activities; EB charger/battery/85% kept; no occupation inferred'})
            controls.append({'asset_id':d['asset_id'],'kind':'ev_charge_window','start_min':plug['end_min'],'end_min':unplug['start_min']})
    initial={'reference_initial_states':w['reference_initial_states'],'common_history_days':7,'source_world_sha256':w['world_content_sha256'],
             'date':date.isoformat(),'dated_activity_sha256':dated(w,date)['activity_day_sha256'],'binding_scope':'declared initialization plus continuous A history; not measured'}
    for c in controls:c['service_date']=(date+dt.timedelta(days=c['start_min']//1440)).isoformat()
    A={'tasks':tasks,'operations':[o for o in ops if o['kind']!='reserved_carry_clearance'],'controls':controls,'changed_controls':[],
       'predecision_state_hash':digest(initial),'parameter_pack_sha256':w['parameter_pack_sha256']}
    return needs,A,ws,initial


def make_A(w,date,days=2):
    # The daily clearing template is reserved even when the prior batch is absent.
    # This makes every originating day's A independent of how many earlier days
    # are requested, while an explicit predecessor includes visible carryover.
    ns,A,ws,initial=_make_A_raw(w,date-dt.timedelta(days=1),days+1)
    for n in ns:
        for key in ('release_min','deadline_min','delivery_deadline_min','program_deadline_min','usual_start_min','usual_retrieval_min','connection_start_min','departure_min','trip_departure_min'):
            if key in n:n[key]-=1440
    for key in ('tasks','controls','operations'):
        for x in A[key]:x['start_min']-=1440;x['end_min']-=1440
    ws={oid:[[a-1440,b-1440] for a,b in values] for oid,values in ws.items()}
    initial['date']=date.isoformat();initial['dated_activity_sha256']=dated(w,date)['activity_day_sha256']
    A['predecision_state_hash']=digest(initial)
    A['daily_carry_clearance_rule']='first reserved morning slots,per installed batch appliance; unused slots are calendar reservations,not thermal visitors or observed household chores'
    return ns,A,ws,initial
