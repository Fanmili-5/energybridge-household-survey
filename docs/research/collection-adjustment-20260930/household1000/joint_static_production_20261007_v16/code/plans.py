"""Independent stable A, immutable needs, then outcome-blind legacy B candidates."""
import collections, copy, datetime as dt
from common import *
LEGACY=read(OUT/'inputs/legacy_AB_rules.json')
def overlaps(a,b): return max(a[0],b[0])<min(a[1],b[1])
def active_wash(w,date):
    r=w['routine'];week=(date-dt.date(2025,1,6)).days//7
    return date.weekday() in r['wash_days'] and (r['wash_alternate_week_phase'] is None or week%2==r['wash_alternate_week_phase'])
def windows(w,date,days=3):
    op=w['operating_context']['operators'][0]
    return {op['operator_id']:[[d*1440+a,d*1440+b] for d in range(days)
        for a,b in op['weekly_windows_min'][str((date+dt.timedelta(days=d)).weekday())]]}
def reserve(ops,windows_map,kind,nid,release,deadline,duration=10):
    for oid,ws in windows_map.items():
        for lo,hi in ws:
            for s in range(((max(lo,release)+9)//10)*10,min(hi,deadline)-duration+1,10):
                if all(o['operator_id']!=oid or not overlaps((s,s+duration),(o['start_min'],o['end_min'])) for o in ops):
                    o={'operation_id':nid+':'+kind,'kind':kind,'need_id':nid,'operator_id':oid,'start_min':s,'end_min':s+duration,'duration_min':duration}
                    ops.append(o);return o
    raise ValueError('NO_HANDLING_WINDOW:'+nid+':'+kind)
def make_A(w,date):
    routine=w['routine'];devices=w['parameter_pack']['devices'];bykind={k:[d for d in devices if k in d['types']] for k in KINDS}
    ws=windows(w,date);ops=[];needs=[];tasks=[];controls=[]
    morning=390 if w['operating_context']['operators'][0]['resident'] else 420
    for day in range(2):
        dat=date+dt.timedelta(days=day);origin=day*1440
        if bykind['washer'] and active_wash(w,dat):
            # Routine workload is generated before proposals and without DR outcomes.
            for batch in range(routine['wash_batches_each_active_day']):
                nid=f'{dat}:laundry:{batch+1}';aid=bykind['washer'][0]['asset_id']
                load=reserve(ops,ws,'load',nid,origin+morning,origin+morning+10)
                desired=origin+routine['wash_preferred_min']+batch*220
                start=max(desired,load['end_min'])
                n={'need_id':nid,'kind':'washer','batch_id':nid,'quantity':routine['laundry_batch_kg'],'unit':'kg',
                    'duration_min':120,'release_min':origin+390,'deadline_min':origin+1440,'loading_required':True,
                    'requester':'household','source_or_design_rule':'frozen usage recipe and EB120min program'}
                needs.append(n);tasks.append({'task_id':nid,'need_id':nid,'asset_id':aid,'kind':'washer','start_min':start,'end_min':start+120})
                end=start+120
                if bykind['dryer']:
                    dryid=nid+':dry';d=bykind['dryer'][0]
                    n={'need_id':dryid,'kind':'dryer','batch_id':nid,'upstream_need_id':nid,'quantity':routine['laundry_batch_kg'],'unit':'kg',
                        'duration_min':90,'release_min':origin+390,'deadline_min':origin+1440,'transfer_min':0,
                        'requester':'household','source_or_design_rule':'same physical combo;automatic wash-to-dry transition;EB90min dry program'}
                    needs.append(n);tasks.append({'task_id':dryid,'need_id':dryid,'asset_id':d['asset_id'],'kind':'dryer','start_min':end,'end_min':end+90});end+=90
                reserve(ops,ws,'unload',nid,origin+1440+morning+10,origin+1440+morning+20)
        if bykind['dishwasher']:
            nid=f'{dat}:dishes';load=reserve(ops,ws,'load',nid,origin+1170,origin+1300)
            start=max(origin+routine['dish_preferred_min'],load['end_min'])
            needs.append({'need_id':nid,'kind':'dishwasher','quantity':1,'unit':'EBprogram','duration_min':90,
                'release_min':origin+1170,'deadline_min':origin+1440,'loading_required':True,'requester':'household',
                'source_or_design_rule':'after19:00-19:30 reference dinner;one EBprogram;not inferred OEM place settings'})
            tasks.append({'task_id':nid,'need_id':nid,'asset_id':bykind['dishwasher'][0]['asset_id'],'kind':'dishwasher','start_min':start,'end_min':start+90})
            reserve(ops,ws,'unload',nid,origin+1440+morning+20,origin+1440+morning+30)
        if bykind['water_heater']:
            tank=bykind['water_heater'][0]
            for i,m in enumerate(w['members']):
                s=origin+routine['bath_start_min']+i*10
                needs.append({'need_id':f'{dat}:bath:{m["member_id"]}','kind':'water_heater','requester':m['member_id'],
                    'release_min':s,'deadline_min':s+10,'quantity':30.,'unit':'L mixed water','target_C':routine['mixed_target_C'],
                    'source_or_design_rule':'explicit30L/resident/10min reference draw at native mixed target;not surveyed demand'})
            lo,hi=routine['tank_heat_window_min']
            controls.append({'asset_id':tank['asset_id'],'kind':'tank_setpoint','start_min':origin+lo,'end_min':origin+hi,'value_C':routine['tank_setpoint_C']})
        if bykind['ac'] and 5<=dat.month<=9:
            for d in bykind['ac']:
                rid=d['room_id'];members=[m for m in w['members'] if m['reference_home_room_id']==rid]
                # All of these members are home18:30-22:30 in the pinned activity grammar.
                needs.append({'need_id':f'{dat}:cooling:{d["asset_id"]}','kind':'ac','asset_id':d['asset_id'],'requester':[m['member_id'] for m in members],
                    'release_min':origin+1110,'deadline_min':origin+1350,'quantity':240,'unit':'occupied room-minutes','served_rooms':[rid],
                    'reference_setpoint_C':26.,'reference_upper_control_C':27.,'source_or_design_rule':'same occupied served zone;26C design baseline,control bound not observed personal comfort'})
                controls.append({'asset_id':d['asset_id'],'kind':'ac_setpoint','start_min':origin+1110,'end_min':origin+1350,'value_C':26.})
        if bykind['ev'] and dat.weekday() in routine['EV_trip_days']:
            d=bykind['ev'][0];s=origin+1110;e=origin+1890
            needs.append({'need_id':f'{dat}:trip','kind':'ev','asset_id':d['asset_id'],'requester':'given reference transport service',
                'release_min':s,'deadline_min':e,'connection_start_min':s,'departure_min':e,'trip_departure_min':origin+450,
                'quantity':25.,'unit':'kWh trip traction energy','required_departure_soc':.85,
                'source_or_design_rule':'same fixed weekday trip and bay window;not source-observed ownership/license/mileage'})
            plug=reserve(ops,ws,'EV_plug',f'{dat}:trip',s,s+60)
            unplug=reserve(ops,ws,'EV_unplug',f'{dat}:trip',e-30,e)
            controls.append({'asset_id':d['asset_id'],'kind':'ev_charge_window','start_min':plug['end_min'],'end_min':unplug['start_min']})
    initial={'reference_initial_states':w['reference_initial_states'],'common_history_days':7,
        'source_world_sha256':w['world_content_sha256'],'date':date.isoformat(),
        'binding_scope':'common initialization and nominal A-prefix input;not a measured or EP-verified physical state'}
    A={'tasks':tasks,'operations':ops,'controls':controls,'changed_controls':[],
        'predecision_state_hash':digest(initial),'parameter_pack_sha256':w['parameter_pack_sha256']}
    return needs,A,ws,initial
def rebuild_unloads(B,needs,ws,decision):
    # Keep every loading and prior operation unchanged. Only future unloading follows
    # shifted cycle end, with the same person, deadline and clothes batch.
    # Stable morning handling reservations are independent of the proposal.
    # A candidate that cannot finish before its retained unload is rejected.
    return

def propose(pair,family,amount):
    p=copy.deepcopy(pair);B=p['B'];decision=p['decision_abs_min'];needs=p['needs_A'];ws=p['world']['operator_windows']
    if family in ['task_shift','task_plus_ac']:
        eligible=[t for t in B['tasks'] if t['start_min']>=decision and t['start_min']<1440 and t['kind'] in ['washer','dishwasher']]
        if not eligible:raise ValueError('NO_ELIGIBLE_FUTURE_TASK')
        t=min(eligible,key=lambda t:rank(pair['case_id'],'task-choice',t['task_id']));t['start_min']+=amount;t['end_min']+=amount
        dry=next((d for d in B['tasks'] if d['need_id']==t['need_id']+':dry'),None)
        if dry:dry['start_min']+=amount;dry['end_min']+=amount
        rebuild_unloads(B,needs,ws,decision)
    if family in ['ac_setpoint','task_plus_ac']:
        eligible=[c for c in B['controls'] if c['kind']=='ac_setpoint' and c['start_min']<1440]
        if not eligible:raise ValueError('NO_AC_TASK_ON_DATE')
        # Restrict the changed future control to the event overlap, restore afterwards.
        lo,hi=pair['event_window_min'];new=[]
        for c in B['controls']:
            if c not in eligible:new.append(c);continue
            a,b=max(lo,c['start_min']),min(hi,c['end_min'])
            if a>=b:raise ValueError('NO_ACTIVE_EVENT_OVERLAP')
            if c['start_min']<a:new.append({**c,'end_min':a})
            changed={**c,'start_min':a,'end_min':b,'value_C':26.+(.5 if family=='task_plus_ac' else amount)};new.append(changed)
            if b<c['end_min']:new.append({**c,'start_min':b})
        B['controls']=new
    if family=='hotwater_preheat_shift':
        cs=[c for c in B['controls'] if c['kind']=='tank_setpoint' and c['start_min']<1440]
        if not cs:raise ValueError('NO_TANK')
        for c in cs:
            if c['start_min']<decision:raise ValueError('ALREADY_COMMITTED_HEATING')
            c['start_min']+=amount;c['end_min']+=amount
    if family=='ev_charge_delay':
        cs=[c for c in B['controls'] if c['kind']=='ev_charge_window' and c['start_min']<1440]
        if not cs:raise ValueError('NO_EV_TRIP_ON_DATE')
        for c in cs:c['start_min']+=amount
    B['changed_controls']=[c for c in B['controls'] if c not in p['A']['controls']]
    p['proposal']={'family':family,'amount':amount,'origin':'R16/R54 magnitudes and least-used feasible family;explicit v16 same-need/handling adapter',
        'legacy_rules_sha256':sha(OUT/'inputs/legacy_AB_rules.json'),'energy_cost_or_human_outputs_consulted':False,'LLM_call_occurred':False}
    return p
def pair(w,index,usage,validate):
    selected=w['random10_date_selection']['dates'][index];date=dt.date.fromisoformat(selected['date'])
    needs,A,ws,initial=make_A(w,date);decision=960 if index%2==0 else 1050
    p={'schema':'eb.joint_same_need_pair.v1','case_id':w['household_id']+':'+date.isoformat(),'household_id':w['household_id'],
        'round_index':index+1,'date':date.isoformat(),'date_selection':selected,'world_sha256':w['world_content_sha256'],
        'parameter_pack_sha256':w['parameter_pack_sha256'],'decision_abs_min':decision,'event_window_min':[1080,1140],
        'horizon_min':3330,'primary_evaluation_min':[0,2880],'service_tail_min':[2880,3330],
        'tail_rule':'fixed next-morning handling/departure tail;not a new question;selection independent of savings',
        'world':{'devices':copy.deepcopy(w['parameter_pack']['devices']),'operator_windows':ws,
            'circuit_limit_kw':w['parameter_pack']['circuit_limit_kw'],'home_service_limit_kw':w['parameter_pack']['home_service_limit_kw'],'background_reserved_kw':w['parameter_pack']['background_reserved_kw']},
        'common_initialization_binding':initial,'needs_A':needs,'needs_B':copy.deepcopy(needs),
        'A':A,'B':copy.deepcopy(A),'A_frozen_before_B_sha256':digest(A),
        'human_adoption':None,'human_relative_preference':None,'simulated_consequences':None}
    errors=validate(p)
    if errors:raise ValueError('BASELINE_STATIC:'+p['case_id']+':'+str(errors))
    control_round=rank(w['household_id'],'identity-round')%10
    if index==control_round:
        p['proposal']={'family':'identity_control','origin':'one household-hash-prespecified identity date','energy_outputs_consulted':False};return p
    magnitudes={'task_shift':LEGACY['task_shift_offsets_min'],'task_plus_ac':LEGACY['task_shift_offsets_min'],
        'ac_setpoint':LEGACY['ac_setpoint_increase_C'],'hotwater_preheat_shift':LEGACY['hotwater_availability_shift_offsets_min'],
        'ev_charge_delay':LEGACY['ev_charge_delay_min']}
    feasible=[];rejections=collections.Counter()
    for family,values in magnitudes.items():
        for amount in values:
            try:
                q=propose(p,family,amount);errs=validate(q)
                if errs:rejections.update(errs)
                else:feasible.append(q)
            except ValueError as e:rejections[str(e)]+=1
    if feasible:
        q=min(feasible,key=lambda q:(usage[q['proposal']['family']],rank(p['case_id'],q['proposal']['family'],q['proposal']['amount'])))
        usage[q['proposal']['family']]+=1;p=q
    else:p['proposal']={'family':'no_legal_change','origin':'retain frozen date;no statically legal legacy candidate'}
    p['candidate_rejection_counts']=dict(rejections)
    return p
