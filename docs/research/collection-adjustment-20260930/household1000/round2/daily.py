"""14-day synthetic diagnostic A, explicit prerequisites, bounded legal B.

All dates, task frequencies, durations, SOC and loads are experimental inputs.
No thermal calculation, recruitment, or fitted behavior model is performed.
"""
import copy, itertools, math
from datetime import date,timedelta
from common import digest

def home(p,member,t,duration):
    m=next((x for x in p['members'] if x['member_id']==member),None)
    if not m or m['age_design']<18:return False
    left=t
    while left<t+duration:
        day=left//1440; stop=min(t+duration,(day+1)*1440)
        weekday=(date(2025,7,1)+timedelta(days=day)).weekday()<5
        windows=m['weekday_home_windows_min' if weekday else 'weekend_home_windows_min'] or []
        if not any(a<=left%1440 and stop-day*1440<=b for a,b in windows):return False
        left=stop
    return True

def validate(p,tasks,materials=()):
    errors=[];byid={t['task_id']:t for t in tasks};assets={a['asset_id']:a for a in p['assets']}
    supplies={m['material_id']:m for m in materials}
    for t in tasks:
        if t['start_abs_min'] is None:continue
        start=t['start_abs_min'];end=start+t['duration_min']
        if not t['release_abs_min']<=start or end>t['deadline_abs_min']:errors.append([t['task_id'],'hard_window'])
        if not home(p,t['operator_member_id'],start,t['operator_minutes']):errors.append([t['task_id'],'operator_absent'])
        for dep in t['predecessor_task_ids']:
            if dep not in byid or byid[dep]['start_abs_min'] is None or start<byid[dep]['start_abs_min']+byid[dep]['duration_min']:errors.append([t['task_id'],'predecessor_not_completed'])
        for mat in t['material_inputs']:
            if mat in supplies:
                if start<supplies[mat]['available_abs_min']:errors.append([t['task_id'],'material_not_released'])
            elif mat not in [x for dep in t['predecessor_task_ids'] if dep in byid for x in byid[dep]['material_outputs']]:errors.append([t['task_id'],'material_not_produced'])
        if t['asset_id']:
            a=assets.get(t['asset_id'])
            if not a or a['accessible_design'] is not True or a['controllable_design'] is not True:errors.append([t['task_id'],'asset_rights_unknown_or_false'])
            if a and a['device_class']!=t['device_class']:errors.append([t['task_id'],'asset_class'])
    scheduled=[t for t in tasks if t['start_abs_min'] is not None]
    for a,b in itertools.combinations(scheduled,2):
        if a['asset_id'] and a['asset_id']==b['asset_id'] and max(a['start_abs_min'],b['start_abs_min'])<min(a['start_abs_min']+a['duration_min'],b['start_abs_min']+b['duration_min']):errors.append([a['task_id'],b['task_id'],'asset_overlap'])
        if a['operator_member_id']==b['operator_member_id'] and max(a['start_abs_min'],b['start_abs_min'])<min(a['start_abs_min']+a['operator_minutes'],b['start_abs_min']+b['operator_minutes']):errors.append([a['task_id'],b['task_id'],'operator_overlap'])
    return errors

def generate(p,case,days=14):
    tasks=[];unresolved=[];states=[];assets=p['assets'];rid=p['role_id'];operator=next((m['member_id'] for m in p['members'] if m['age_design']>=18),None)
    materials=[{'material_id':f'{rid}:dirty_batch:{d}','available_abs_min':d*1440+1140,
        'basis':'declared_boundary_laundry_accumulation_not_observed'} for d in range(days) if d%3==0]
    materials += [{'material_id':f'{rid}:dirty_dishes:{d}','available_abs_min':d*1440+1200,
        'basis':'declared_boundary_dinner_completion_not_observed'} for d in range(days)]
    first=lambda cls:next((a['asset_id'] for a in assets if a['device_class']==cls),None)
    def task(day,cls,release,deadline,duration,usual,dep=(),ins=(),outs=(),op=None):
        tid=f'{rid}/d{day:02d}/{cls}/{len(tasks):03d}'
        t={'task_id':tid,'day_index':day,'device_class':None if cls=='manual_wash' else cls,
           'task_kind':cls,'asset_id':None if cls=='manual_wash' else first(cls),
           'operator_member_id':op or operator,'operator_minutes':duration if cls in ['manual_wash','dishwasher'] else 10,
           'release_abs_min':day*1440+release,'deadline_abs_min':day*1440+deadline,
           'duration_min':duration,'usual_start_abs_min':day*1440+usual,'start_abs_min':None,
           'predecessor_task_ids':list(dep),'material_inputs':list(ins),'material_outputs':list(outs),
           'frequency_basis':'fixed_boundary_experiment_not_observed','service_result':None}
        if cls=='manual_wash' or t['asset_id']:
            # A is established once. Search does not depend on whether B exists.
            for start in range(max(t['release_abs_min'],t['usual_start_abs_min']),t['deadline_abs_min']-duration+1,10):
                t['start_abs_min']=start
                if not validate(p,tasks+[t],materials):break
                t['start_abs_min']=None
        if t['start_abs_min'] is None:unresolved.append({'task_id':tid,'reason':'no_legal_A_slot_or_asset_or_predecessor'})
        tasks.append(t);return t
    soc=.8
    for day in range(days):
        if day%3==0 and (first('washer') or first('dryer')):
            manual=case=='manual_wash_dry';kind='manual_wash' if manual else 'washer'
            deadline=1200 if case=='tight_deadline' else 1380
            wash=task(day,kind,1140,deadline,60,1140,ins=[f'{rid}:dirty_batch:{day}'],outs=[f'{rid}:wet_batch:{day}'])
            if first('dryer'):
                task(day,'dryer',1200,1380,90,1210,dep=[wash['task_id']],ins=wash['material_outputs'],outs=[f'{rid}:dry_batch:{day}'])
        if first('dishwasher'):task(day,'dishwasher',1200,1380,60,1220,ins=[f'{rid}:dirty_dishes:{day}'],outs=[f'{rid}:clean_dishes:{day}'])
        if first('electric_water_heater'):
            # Demand is a service requirement, not proof of adequate hot water.
            states.append({'day':day,'water_demand_liters_design':40,'served_liters':None,'reason':'thermal_state_engine_not_connected'})
        if first('home_ev'):
            driver=p['driver_member_id'];m=next((m for m in p['members'] if m['member_id']==driver),None)
            trip=4.0 if m and m['routine_design'] in ['out_regular','mixed'] else None
            before=soc
            if trip is None:
                states.append({'day':day,'SOC_pre_day':before,'trip_kWh_design':None,'SOC_post_day':None,'reason':'trip_driver_missing'});continue
            demand=trip
            if before+1e-9<trip/50:trip=0.0
            soc=max(0.0,soc-trip/50)
            charge=None;energy=0
            if soc<.6:
                energy=(.8-soc)*50/.9
                duration=10*math.ceil(energy/3.3*60/10)
                charge=task(day,'home_ev',1380,1890,duration,1380,op=driver)
                charge.update(energy_grid_kWh_design=energy,vehicle_capacity_kWh_design=50,efficiency_design=.9,
                    vehicle_present_interval_abs_min=[day*1440+1110,day*1440+1890],next_departure_abs_min=day*1440+1890)
                if charge['start_abs_min'] is not None:soc=.8
            states.append({'day':day,'SOC_pre_day':round(before,8),'trip_kWh_design':trip,'trip_demand_kWh_design':demand,
                'unserved_trip_demand_kWh_design':demand-trip,'SOC_after_trip':round(max(0.0,before-trip/50),8),
                'charge_task_id':charge['task_id'] if charge else None,'charge_grid_kWh_design':energy if charge and charge['start_abs_min'] is not None else 0,
                'SOC_post_day':round(soc,8),'reserve_met_design':soc>=.2})
        for a in assets:
            if a['device_class']=='ac':
                states.append({'day':day,'asset_id':a['asset_id'],'zone_id':a['zone_id'],
                    'habit_session_design_abs_min':[day*1440+1140,day*1440+1380],
                    'available_session':None,'actual_cooling_kWh':None,'reason':'climate_and_occupancy_binding_pending'})
    A={'schema':'eb.bounded_daily_A.v2','role_id':rid,'profile_hash':digest(p),'case':case,'days':days,
       'start_date':'2025-07-01','initial_state':{'EV_SOC_design':.8,'laundry_no_unrecorded_wet_stock':True,'observed_state':None},
       'tasks':tasks,'material_sources':materials,'states':states,'unresolved':unresolved,'scheduled_task_errors':validate(p,tasks,materials),
       'physical_results':None,'human_answers':None,'collection_release':False}
    return A

def select_B(p,A,max_rounds=10):
    rounds=[];failures=[];tasks=A['tasks'];attempted=0
    for day in range(A['days']):
        candidates=[t for t in tasks if t['day_index']==day and t['start_abs_min'] is not None and t['device_class'] in ['washer','dryer','dishwasher','home_ev']]
        selected=None;reasons=set()
        for x,y in itertools.combinations(candidates,2):
            if x['device_class']==y['device_class']:continue
            for dx,dy in itertools.product([10,20,30,40,50,60],repeat=2):
                attempted+=1;B=copy.deepcopy(tasks)
                for t in B:
                    if t['task_id']==x['task_id']:t['start_abs_min']+=dx
                    if t['task_id']==y['task_id']:t['start_abs_min']+=dy
                errors=validate(p,B,A['material_sources'])
                if errors:reasons.update(str(e[-1]) for e in errors);continue
                commands=[{'task_id':t['task_id'],'asset_id':t['asset_id'],'device_class':t['device_class'],
                    'A_start_abs_min':t['start_abs_min'],'B_start_abs_min':t['start_abs_min']+d,'duration_min':t['duration_min']}
                    for t,d in [(x,dx),(y,dy)]]
                selected={'round_index':len(rounds)+1,'day_index':day,'A_sha256':digest(A),'profile_sha256':digest(p),
                    'commands':commands,'legal_prior_A_days':list(range(day)),'prior_A_state_sha256':digest([s for s in A['states'] if s['day']<day]),
                    'future_B_outcomes':None,'physics':None,'answer':None,'scope':'independent_counterfactual_on_A_history_not_sequential_B_replay','collectable':False}
                break
            if selected:break
        if selected and len(rounds)<max_rounds:rounds.append(selected)
        elif len(rounds)<max_rounds:failures.append({'day_index':day,'reason':'no_two_class_legal_existing_tasks','constraint_failures':sorted(reasons)})
    return {'role_id':p['role_id'],'rounds':rounds,'round_shortfall':max_rounds-len(rounds),
        'candidate_evaluations':attempted,'failed_days_before_quota':failures,
        'A_modified_for_B':False,'new_tasks_for_B':0,'physical_ready':0,'human_answers':0,'collection_release':False}
