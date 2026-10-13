"""A before B: absolute service, program, handling and continuous-state contracts."""
import copy,datetime as dt
from common import *
from worlds import merge_ranges

def active_wash(w,date):
    r=w['routine'];week=(date-dt.date(2025,1,6)).days//7
    return date.weekday() in r['wash_days'] and (r['wash_alternate_week_phase'] is None or week%2==r['wash_alternate_week_phase'])
def windows(w,date,days):
    return {o['operator_id']:[[d*1440+a,d*1440+b] for d in range(days) for a,b in o['weekly_windows_min'][str((date+dt.timedelta(days=d)).weekday())]] for o in w['operating_context']['operators']}
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
def operator_morning(w,weekday):
    primary=w['operating_context']['operators'][0]
    ws=primary['weekly_windows_min'][str(weekday)]
    # At most 08:00 is a usual service deadline; if no early availability, the
    # service follows the first available window and remains explicitly in tail.
    first=next(([a,b] for a,b in ws if a<720),ws[0])
    return first[0],min(first[1],first[0]+70)
def ev_times(w,weekday):
    d=next(d for d in w['parameter_pack']['devices'] if 'ev' in d['types'])
    m=next((m for m in w['members'] if m['member_id']==d['operator_id']),None)
    if m:
        s=m['daily_reference_specs'][weekday]
        departure=s['departure_min'] or s['wake_min']+90
        arrival=s['arrival_min'] or 1050
        return departure,arrival
    return 450,1110
def make_A(w,date,days=2):
    devices=w['parameter_pack']['devices'];ks={k:[d for d in devices if k in d['types']] for k in KINDS}
    ws=windows(w,date,days+1);ops=[];needs=[];tasks=[];controls=[];r=w['routine']
    for day in range(days):
        dat=date+dt.timedelta(days=day);origin=day*1440;weekday=dat.weekday()
        morning,latest=operator_morning(w,weekday);nm,nend=operator_morning(w,(weekday+1)%7)
        family=r['weekly_family_context'][weekday];habit=r['stable_habit_variation_level']
        next_deadline=origin+1440+max(nend,nm+40)
        if ks['washer'] and active_wash(w,dat):
            evening=next((a for a,b in w['operating_context']['operators'][0]['weekly_windows_min'][str(weekday)] if b>=1050),morning)
            desired=max(570+habit*60 if evening<800 else evening+20, morning+20)
            # Habit level is declared design; frequency and batch mass are retained.
            for batch in range(r['wash_batches_each_active_day']):
                nid=f'{dat}:laundry:{batch+1}';d=ks['washer'][0]
                preferred=origin+desired+batch*220
                load=reserve(ops,ws,'load',nid,origin+morning,min(preferred+20,origin+1200),preferred-10,d['operator_id'])
                start=max(preferred,load['end_min']);end=start+120
                needs.append({'need_id':nid,'kind':'washer','batch_id':nid,'quantity':r['laundry_batch_kg'],'unit':'kg',
                    'duration_min':120,'release_min':origin+morning,'deadline_min':origin+1440,
                    'delivery_deadline_min':next_deadline,'loading_required':True,'requester':'household',
                    'semantic_class':'mandatory_reference_service','usual_start_min':preferred,
                    'source_or_design_rule':'retained CRECS frequency and batch mass; EB120min; usual start conditioned on operator calendar and declared habit level; midnight program bound is given design',
                    'wearable_clothes_ready_at_program_end':False if ks['dryer'] else None,
                    'wearable_clothes_ready_after_required_chain':True if ks['dryer'] else None})
                tasks.append({'task_id':nid,'need_id':nid,'asset_id':d['asset_id'],'kind':'washer','start_min':start,'end_min':end})
                if ks['dryer']:
                    dn=nid+':dry';dd=ks['dryer'][0]
                    needs.append({'need_id':dn,'kind':'dryer','batch_id':nid,'upstream_need_id':nid,'quantity':r['laundry_batch_kg'],'unit':'kg',
                        'duration_min':90,'release_min':origin+morning,'deadline_min':origin+1440,'delivery_deadline_min':next_deadline,
                        'transfer_min':0,'semantic_class':'mandatory_reference_service',
                        'wearable_clothes_ready_at_program_end':True,
                        'source_or_design_rule':'same existing automatic washer-dryer physical combo and unchanged EB90min program'})
                    tasks.append({'task_id':dn,'need_id':dn,'asset_id':dd['asset_id'],'kind':'dryer','start_min':end,'end_min':end+90});end+=90
                retrieve=reserve(ops,ws,'unload',nid,max(end,origin+1440+nm),next_deadline,origin+1440+nm,d['operator_id'])
                needs[-2 if ks['dryer'] else -1]['usual_retrieval_min']=retrieve['start_min']
        if ks['dishwasher']:
            d=ks['dishwasher'][0];nid=f'{dat}:dishes';release=origin+family['dinner_min']+30
            load=reserve(ops,ws,'load',nid,release,release+100,release+10,d['operator_id'])
            start=load['end_min']+habit*10
            needs.append({'need_id':nid,'kind':'dishwasher','quantity':1,'unit':'EBprogram','duration_min':90,
                'release_min':release,'deadline_min':origin+1440,'delivery_deadline_min':next_deadline,
                'usual_start_min':start,'loading_required':True,'semantic_class':'mandatory_reference_service',
                'source_or_design_rule':'same household dinner completion -> load -> unchanged EB90min program -> next-use retrieval'})
            tasks.append({'task_id':nid,'need_id':nid,'asset_id':d['asset_id'],'kind':'dishwasher','start_min':start,'end_min':start+90})
            retrieve=reserve(ops,ws,'unload',nid,max(start+90,origin+1440+nm),next_deadline,origin+1440+nm+10,d['operator_id'])
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
                members=[m for m in w['members'] if m['reference_home_room_id']==d['room_id']]
                ranges=merge_ranges([[i['start_min'],i['end_min']] for m in members for i in m['weekly_calendar'][weekday]['intervals']
                                     if i['location']=='home' and i['activity']!='sleep_rest'])
                for i,(a,b) in enumerate(ranges):
                    needs.append({'need_id':f'{dat}:cooling:{d["asset_id"]}:{i}','kind':'ac','asset_id':d['asset_id'],
                        'requester':[m['member_id'] for m in members],'release_min':origin+a,'deadline_min':origin+b,
                        'quantity':b-a,'unit':'awake home served-room minutes','served_rooms':[d['room_id']],
                        'reference_setpoint_C':26.,'reference_upper_control_C':d['reference_upper_setpoint_C'],
                        'semantic_class':'given_reference_control_service','source_or_design_rule':'member full calendar -> awake home served-room interval;26C baseline and27C bound are reference controls, subjective comfort unknown'})
                    controls.append({'asset_id':d['asset_id'],'kind':'ac_setpoint','start_min':origin+a,'end_min':origin+b,'value_C':26.})
        if ks['ev'] and weekday in r['EV_trip_days']:
            d=ks['ev'][0];dep,arr=ev_times(w,weekday);next_dep,_=ev_times(w,(weekday+1)%7)
            nid=f'{dat}:trip';s=origin+arr;e=origin+1440+next_dep
            plug=reserve(ops,ws,'EV_plug',nid,s,s+90,s,d['operator_id'])
            unplug=reserve(ops,ws,'EV_unplug',nid,e-60,e,e-10,d['operator_id'])
            needs.append({'need_id':nid,'kind':'ev','asset_id':d['asset_id'],'requester':d['operator_id'],
                'release_min':s,'deadline_min':e,'connection_start_min':s,'departure_min':e,'trip_departure_min':origin+dep,
                'quantity':r['EV_daily_trip_kWh'],'unit':'kWh given traction service','required_departure_soc':r['EV_target_soc'],
                'next_access_is_actual_trip':(weekday+1)%7 in r['EV_trip_days'],
                'semantic_class':'trip_service_and_separate_reference_access_target',
                'source_or_design_rule':'unchanged EB25kWh/85% reference task; trip clock aligned to given driver scenario; unknown employment not turned into commuting'})
            controls.append({'asset_id':d['asset_id'],'kind':'ev_charge_window','start_min':plug['end_min'],'end_min':unplug['start_min']})
    initial={'reference_initial_states':w['reference_initial_states'],'common_history_days':7,'source_world_sha256':w['world_content_sha256'],
             'date':date.isoformat(),'binding_scope':'declared initialization plus continuous A history; not measured'}
    A={'tasks':tasks,'operations':ops,'controls':controls,'changed_controls':[],
       'predecision_state_hash':digest(initial),'parameter_pack_sha256':w['parameter_pack_sha256']}
    return needs,A,ws,initial
