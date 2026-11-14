"""Frozen V9 household -> dated service needs and ordinary joint A.

Source life clocks and reference hardware are kept separate. Resource settings
are explicit benchmark inputs; no outcome, B or human label enters this path.
"""
from copy import deepcopy
import datetime as dt
import math
from .common import digest
from .eb_alignment import operation_windows,CONTIGUOUS,bind_household
from .unified.a_solver import solve
from .unified.pipeline import fresh_context

FUNCTION={'AC':'ac','WM':'washer','DR':'dryer','DW':'dishwasher','WH':'water_heater','EV':'ev'}

def union(rows):
 out=[]
 for a,z in sorted(rows):
  if z<=a:continue
  if out and a<=out[-1][1]:out[-1][1]=max(z,out[-1][1])
  else:out.append([a,z])
 return out

def reference_calendar(h,day):
 # Preserve exact absence boundaries, including Sunday overnight tails.
 rows={m['id']:[] for m in h['members']};start=day*1440;end=start+1440
 for event in h['calendar']['weekly_events']:
  if event['location']!='away':continue
  for offset in [k*10080 for k in range(-1,day//7+2)]:
   a=max(start,event['start']+offset);z=min(end,event['end']+offset)
   if a<z:rows[event['member_id']].append([a-start,z-start])
 result={}
 for mid,away in rows.items():
  away=union(away);points=sorted({0,1440,*[v for pair in away for v in pair]})
  result[mid]=[dict(start_min=a,end_min=z,location='away' if any(x<=a and z<=y for x,y in away) else 'home',room_id='home') for a,z in zip(points,points[1:])]
 return result

def _build_problem_opportunity_legacy(case,anchor,reference,*,days=14):
 h=case['household'];begin=dt.date.fromisoformat(anchor)
 if begin.weekday()!=0 or days not in (7,14):raise ValueError('V9_REFERENCE_WEEK_REQUIRES_MONDAY_AND_7_OR_14_DAYS')
 requested_days=days
 # One explicit planning grace day completes final-evening services.
 # No new programme demands are manufactured in the grace day.
 days=days+1
 dates=[(begin+dt.timedelta(days=i)).isoformat() for i in range(days)]
 windows=operation_windows(case,dates,anchor=anchor);hid=case['case_id'];assets={};byfun={}
 for function,kind in FUNCTION.items():
  key={'AC':'space_ac_available','WM':'washer_available','DR':'dryer_available','DW':'dishwasher_available','WH':'water_heater_available','EV':'home_vehicle_charging'}[function]
  eq=h['equipment'].get(key,{})
  if not eq.get('present'):continue
  registry=next((v for v in h['service_asset_registry'].values() if function in v['functions']),None)
  if registry is None:raise ValueError('PRESENT_FUNCTION_ASSET_NOT_BOUND:'+function)
  aid=registry['asset_id'];byfun[function]=aid
  room='home' if function=='AC' else 'kitchen' if function=='DW' else 'parking' if function=='EV' else 'utility'
  if aid not in assets:assets[aid]=dict(asset_id=aid,kind=kind,types=[],room_id=room,parameters={},using_household_ids=[hid],target_control_authorized=False)
  d=assets[aid];d['types'].append(kind);d['target_control_authorized']|=function in h['controlled_function_ids']
  if function in ['WM','DR','DW']:
   d['parameters'][kind]=dict(power_kw=reference['programs'][kind]['nominal_peak_kw'])
  elif function=='AC':d['parameters'].update(max_electric_W=reference['AC_nominal_upper_W'])
  elif function=='WH':d['parameters'].update(maximum_C=reference['tank_maximum_C'])
  else:
   v=h['ev'];d['parameters'].update(capacity_kwh=v['reference_battery_kwh'],charger_kw=v['reference_charger_kw'],efficiency=v['charge_efficiency'],initial_energy_kwh=v['arrival_soc']*v['reference_battery_kwh'],target_soc=v['departure_soc_target'],minimum_soc=reference['EV_reserve_SOC'],charge_session_policy=CONTIGUOUS)
 # Qualified operation windows are an explicit stage1 contract; no extra helper.
 qualified={x['member_id'] for day in h['routine']['daily_services'] for x in day['manual_operation_opportunities']}
 members=[dict(member_id=m['id'],household_id=hid,can_operate_asset_ids=list(assets) if m['id'] in qualified else []) for m in h['members']]
 world=dict(household_id=hid,members=members,devices=list(assets.values()),native_single_program_per_day=True)
 daily={date:dict(base_min=i*1440,operator_windows=windows[date]['operator_windows'],calendars=reference_calendar(h,i),reservations=[]) for i,date in enumerate(dates)}
 jobs=[];needs=[]
 def job(kind,nid,release,deadline,target,parent=None):
  function={'washer':'WM','dryer':'DR','dishwasher':'DW'}[kind]
  if function not in byfun:raise ValueError('REQUIRED_SERVICE_ASSET_MISSING:'+function)
  ref=reference['programs'][kind]
  policy=dict(duration_min=ref['duration_min'],maximum_preload_wait_min=reference['maximum_preload_wait_min'],maximum_retrieval_wait_min=reference['maximum_retrieval_wait_min'][kind],timer_allowed=True,machine_windows_min=[[0,1440]],energy_model='legacy_constant_power')
  j=dict(need_id=nid,asset_id=byfun[function],kind=kind,date=dates[min(days-1,target//1440)],release_min=math.ceil(release/10)*10,exact_source_release_min=release,deadline_min=deadline,preferred_start_min=target,quantity=1,unit='one_source_reference_program',batch_capacity_kg=None,policy=policy,origin='frozen_V9_demand_plus_explicit_reference_resource_model')
  if parent:j['depends_on_need_id']=parent
  jobs.append(j)
 # Weekly frequency supplies demand. Opportunities do not supply extra cycles.
 count=h['routine']['laundry_cycles_per_week']
 if 'WM' in byfun:
  for week in range(requested_days//7):
   for n in range(count):
    a=week*10080+math.floor(n*10080/count/10)*10;z=week*10080+math.floor((n+1)*10080/count/10)*10
    target_day=min(days-1,(a+z)//2//1440)
    service=h['routine']['daily_services'][target_day%7]
    preferred=target_day*1440+service['flexible_chore_window'][0]
    nid=f'{dates[target_day]}:laundry:{n}'
    job('washer',nid,a,z,preferred)
    if 'DR' in byfun:job('dryer',nid+':dry',a,z,preferred+reference['programs']['washer']['duration_min'],nid)
 elif 'DR' in byfun:raise ValueError('DR_PREDECESSOR_ASSET_MISSING')
 if 'DW' in byfun:
  for i,date in enumerate(dates[:requested_days]):
   # A batch is released by the preceding day's actual home meals. This
   # avoids inventing future dinner dishes or forcing all cycles to bedtime.
   previous=h['routine']['daily_services'][(i-1)%7]
   meals=[m for m in previous['meals'] if m['location']=='home' and m['participants']]
   if not meals:continue
   release=i*1440
   target=i*1440+h['routine']['daily_services'][i%7]['flexible_chore_window'][0]
   deadline=(i+2)*1440
   job('dishwasher',date+':dishes',release,deadline,target)
   jobs[-1]['source_meal_batch']=dict(reference_day=(i-1)%7,home_meal_events=len(meals),initial_day_inventory='preceding_reference_Sunday_meal_batch' if i==0 else None,scope='one_explicit_source_program_batch;not_asserting_all_meal_place_settings_or_wash_quality')
 controls=[];cool=sum(h['comfort']['preferred_cooling_c'])/len(h['comfort']['preferred_cooling_c'])
 if 'AC' in byfun:controls.append(dict(asset_id=byfun['AC'],kind='ac_setpoint',start_min=0,end_min=days*1440,cooling_setpoint_C=cool,heating_setpoint_C=reference['heating_C'],fan_operating_mode=0))
 if 'WH' in byfun:controls.append(dict(asset_id=byfun['WH'],kind='tank_setpoint',start_min=0,end_min=days*1440,value_C=reference['tank_normal_C']))
 EV=dict(failures=[],journeys=[],connections=[]);fixed=[]
 if 'EV' in byfun:
  # Parking is taken from the full reference actor calendar. Energy is an
  # explicit reference traction budget, never an arrival-SOC reset.
  driver=h['ev']['vehicle_user_member_id'];away=[]
  for i,date in enumerate(dates):
   cal=daily[date]['calendars'][driver]
   away.extend([i*1440+x['start_min'],i*1440+x['end_min']] for x in cal if x['location']=='away')
  away=union(away);points=sorted({0,days*1440,*[v for pair in away for v in pair]})
  params=assets[byfun['EV']]['parameters'];daily_energy=(params['target_soc']-h['ev']['arrival_soc'])*params['capacity_kwh']
  for n,(a,z) in enumerate(away):
   same_day=sum(x//1440==a//1440 for x,y in away)
   EV['journeys'].append(dict(absolute_departure_min=math.floor(a/10)*10,absolute_arrival_min=math.ceil(z/10)*10,traction_kWh=daily_energy/max(1,same_day),origin='explicit_equal_allocation_of_V9_reference_daily_traction_budget'))
  for n,(a,z) in enumerate(zip(points,points[1:])):
   if any(x<=a and z<=y for x,y in away):continue
   lo=math.ceil(a/10)*10;hi=math.floor(z/10)*10
   if hi<=lo:continue
   nid=f'EV-parking-{n}';EV['connections'].append(dict(need_id=nid,start_min=lo,end_min=hi,origin='given_anchor_connection' if a==0 else 'frozen_V9_actor_home_episode'))
   if lo>0:
    # These actions must fit a real qualified driver's exact source window.
    fixed.append(dict(operation_id=nid+':plug',asset_id=byfun['EV'],operator_id=driver,room_id='parking',kind='EV_plug',need_id=nid,start_min=lo,end_min=lo+10))
    EV['connections'][-1]['start_min']=lo+10
   if hi<days*1440:fixed.append(dict(operation_id=nid+':unplug',asset_id=byfun['EV'],operator_id=driver,room_id='parking',kind='EV_unplug',need_id=nid,start_min=hi-10,end_min=hi));EV['connections'][-1]['end_min']=hi-10
 problem=dict(household_id=hid,anchor=anchor,end_exclusive=(begin+dt.timedelta(days=days)).isoformat(),world=world,jobs=jobs,days=daily,fixed_operations=fixed,controls=controls,EV=EV,thermostat_policies=[],nonprogram_requirements=needs,input_lineage=dict(household_case_sha256=digest(case),reference_rules_sha256=digest(reference),life_calendar='unchanged_exact_frozen_V9_reference_week',demands='weekly_laundry_frequency;home_meals;actual_bathing_events;explicit_reference_EV_budget',source_facts_modified=False,requested_days=requested_days,planning_grace_days=1))
 return problem

def _dated_context_source_base(case,problem,A,date,configuration,manifest_sha256):
 c=fresh_context(problem,A,date,None,configuration)
 # Keep only the decision horizon and required predecessor/successor closure.
 selected={t['need_id'] for t in c['A']['tasks'] if t['start_min']<1920 and t['end_min']>0}
 changed=True
 while changed:
  changed=False
  for t in c['A']['tasks']:
   if t['need_id'] in selected and t.get('depends_on_need_id') and t['depends_on_need_id'] not in selected:selected.add(t['depends_on_need_id']);changed=True
   if t.get('depends_on_need_id') in selected and t['need_id'] not in selected:selected.add(t['need_id']);changed=True
 c['A']['tasks']=[t for t in c['A']['tasks'] if t['need_id'] in selected]
 evneeds={p['need_id'] for p in c['physical_ev_connections'] if p['start_min']<1920 and p['end_min']>0}
 c['A']['operations']=[o for o in c['A']['operations'] if o['need_id'] in selected|evneeds]
 c['A']['controls']=[r for r in c['A']['controls'] if r['start_min']<1920 and r['end_min']>0]
 c['needs']=[n for n in c['needs'] if n['need_id'] in selected or n.get('kind') not in ['washer','dryer','dishwasher']]
 c['physical_ev_connections']=[p for p in c['physical_ev_connections'] if p['need_id'] in evneeds]
 c['reference']['ev_charging_steps']=[r for r in c['reference']['ev_charging_steps'] if r['need_id'] in evneeds]
 c['source']['household_case_sha256']=digest(case)
 c['source']['household_input_manifest_sha256']=manifest_sha256
 return bind_household(c,case,manifest_sha256)


def _build_problem_with_source_episode(case, anchor, reference, *, days=14, service_date=None):
    """Date the frozen source. Parking opportunities are not recurring demands."""
    import datetime as _dt, copy as _copy, math as _math
    problem=_build_problem_opportunity_legacy(case,anchor,reference,days=days)
    limit=len(problem['days'])*1440
    for job in problem['jobs']:
        if job['kind'] in ('washer','dryer'):
            # A weekly frequency supplies quantity, not an observed per-batch due time.
            job['deadline_min']=min(limit,(job['release_min']//10080+1)*10080+1440)
            job['deadline_origin']='reference_weekly_quantity_with_one_day_completion_grace;not_observed_batch_deadline'
    problem['input_lineage']['laundry_deadline_contract']='weekly_quantity_completion;source_counts_and_preferred_starts_unchanged'
    device=next((d for d in problem['world']['devices'] if d['kind']=='ev'),None)
    if device is None:return problem
    h=case['household'];ev=h['ev']
    if ev.get('service_scope')!='one selected parking-session episode; not repeated daily charging demand':
        raise ValueError('UNSUPPORTED_FROZEN_EV_SERVICE_SCOPE')
    anchor_date=_dt.date.fromisoformat(anchor)
    selected_date=_dt.date.fromisoformat(service_date) if service_date else anchor_date+_dt.timedelta(days=min(2,days-1))
    day=(selected_date-anchor_date).days
    if not 0<=day<days:raise ValueError('EV_SERVICE_DATE_OUTSIDE_REQUEST')
    selected=ev['parking_sessions'][selected_date.weekday()]
    source_start=selected['arrival'];source_end=selected['next_departure']
    source_day=source_start//1440
    shift=day*1440-source_day*1440
    arrival=source_start+shift;departure=source_end+shift
    # The stated driver is an existing source household member, not a new helper.
    driver=ev['vehicle_user_member_id']
    source_members=[m for m in h['members'] if m.get('id')==driver]
    if len(source_members)!=1:raise ValueError('EV_DRIVER_NOT_SOURCE_MEMBER')
    candidates=[m for m in problem['world']['members'] if m['member_id']==driver or m['member_id'].endswith(':'+driver) or m['member_id'].endswith('-'+driver)]
    if len(candidates)!=1:raise ValueError('EV_DRIVER_IDENTIFIER_MAPPING_AMBIGUOUS')
    actor=candidates[0];mid=actor['member_id'];aid=device['asset_id']
    if aid not in actor['can_operate_asset_ids']:actor['can_operate_asset_ids'].append(aid)
    # Parking is bounded by the frozen opportunity AND the actual reference actor at home.
    homes=[]
    for date,entry in problem['days'].items():
        for row in entry['calendars'].get(mid,[]):
            if row['location']=='home':homes.append((entry['base_min']+row['start_min'],entry['base_min']+row['end_min']))
    homes=union(homes)
    physical=[(max(a,arrival),min(z,departure)) for a,z in homes if max(a,arrival)<min(z,departure)]
    physical=[x for x in physical if x[1]-x[0]>=20]
    if not physical:raise ValueError('SELECTED_EV_PARKING_HAS_NO_ACTUAL_HOME_WITNESS')
    start,end=max(physical,key=lambda x:x[1]-x[0])
    plug_start=10*_math.ceil(start/10)
    unplug_start=10*_math.floor(end/10)
    connection_start=plug_start;connection_end=unplug_start
    if connection_start>=connection_end:raise ValueError('EV_HANDLING_LEAVES_NO_CHARGING_SESSION')
    need=case['case_id']+':EV:selected_parking_episode:'+selected_date.isoformat()
    # One known episode initial state; no fabricated daily traction or SOC resets.
    problem['world']['native_ev_contiguous_session']=True
    ep=device['parameters'];ep['initial_energy_kwh']=float(ev['arrival_soc'])*ep['capacity_kwh']
    ep['charge_session_policy']='one_continuous_session_is_required_for_base_need'
    problem['EV']={'connections':[{'start_min':connection_start,'end_min':connection_end,'need_id':need,'origin':'given_source_parking_episode'}],
      'journeys':[{'absolute_departure_min':connection_end,'absolute_arrival_min':connection_end,'traction_kWh':0.0,'origin':'episode_departure_target_only;post_departure_trip_energy_not_modelled'}],
      'failures':[],
      'episode':{'scope':ev['service_scope'],'service_date':selected_date.isoformat(),'source_driver_member_id':driver,'mapped_operator_id':mid,'asset_id':aid,'source_parking_interval':[arrival,departure],'physical_home_witness':[start,end],'connection_interval':[connection_start,connection_end],
      'initial_state_scope':'known_SOC_at_selected_parking_episode;EV_outside_episode_not_a_claimed_driving_or_battery_trajectory','daily_traction_or_arrival_SOC_reset_invented':False}}
    room=device.get('room_id')
    # A source parking opportunity is instantiated as a given connection state.
    # EB's controller receives the connection window; it does not consume
    # invented 10-minute human plug/unplug reservations from that window.
    problem['fixed_operations']=[]
    problem['input_lineage']['EV_service_contract']='one source-selected parking episode, one complete charging need; no repeated daily traction'
    problem['input_lineage']['EV_manual_operation_contract']='source parking opportunity instantiated as a fixed connected-episode condition;not observed plugging;no invented human action duration'
    return problem


def build_problem(case,anchor,reference,*,days=14,service_date=None):
    """One EB command day; no fabricated loading/retrieval process."""
    if service_date is None:raise ValueError('DAILY_QUESTION_REQUIRES_EXPLICIT_SERVICE_DATE')
    q=dt.date.fromisoformat(service_date);a=dt.date.fromisoformat(anchor)
    if a.weekday()!=0 or days not in (7,14):raise ValueError('V9_REFERENCE_WEEK_REQUIRES_MONDAY_AND_7_OR_14_DAYS')
    if not 0<=(q-a).days<days:raise ValueError('DAILY_SERVICE_DATE_OUTSIDE_REQUEST')
    from .eb_primary import build_problem as native_problem
    return native_problem(case,service_date,reference)


def _dated_context_before_daily_cardinality(case, problem, A, date, configuration, manifest_sha256):
    context=_dated_context_source_base(case,problem,A,date,configuration,manifest_sha256)
    complete_day_service_scope(context,problem,A,date)
    from .primary_day_clock import attach_windows
    attach_windows(context,problem)
    episode=problem['EV'].get('episode')
    if episode:
        import datetime as _dt
        offset=(_dt.date.fromisoformat(date)-_dt.date.fromisoformat(problem['anchor'])).days*1440
        aid=episode['asset_id'];mid=episode['mapped_operator_id']
        context.setdefault('native_operation_windows_by_asset',{})[aid]={mid:[[o['start_min']-offset,o['end_min']-offset] for o in problem['fixed_operations']]}
        authority=context['authority']['assets'][aid]
        if mid not in authority['authorized_operator_ids']:authority['authorized_operator_ids'].append(mid)
        context['native_execution_contract']['EV_episode_binding']=episode
        context['native_execution_contract']['EV_operation_basis']='source vehicle user, selected source parking, actual home witness; separate from programme handling windows'
        from .connection_states import attach
        attach(context,episode)
    from .sampling import command_hash
    from .common import digest
    context['reference']['binding']['A_commands_sha256']=command_hash(context['A'])
    context['reference']['binding']['context_sha256']=digest({k:v for k,v in context.items() if k!='reference'})
    return context

def complete_day_service_scope(context,problem,A,date):
    """One questionnaire day; retain the entire necessary service continuation."""
    import datetime as _dt, copy as _copy
    from .sampling import command_hash
    from .common import digest
    context['question_window_min']=[480,1920]
    context['question_unit']='one_dated_household_day'
    # The planning/check interval includes immutable loading history and
    # completion/retrieval tails; the scored/displayed day stays exactly24h.
    endpoints=[(r['start_min'],r['end_min']) for group in ('tasks','operations') for r in context['A'][group]]
    if endpoints:
        context['horizon_min']=[min([context['horizon_min'][0]]+[a for a,z in endpoints]),
                                max([context['horizon_min'][1]]+[z for a,z in endpoints])]
    episode=problem['EV'].get('episode')
    if episode and context.get('physical_ev_connections'):
        offset=(_dt.date.fromisoformat(date)-_dt.date.fromisoformat(problem['anchor'])).days*1440
        ids={r['need_id'] for r in context['physical_ev_connections']}
        full=[{**_copy.deepcopy(r),'start_min':r['start_min']-offset,'end_min':r['end_min']-offset}
              for r in A['A']['controls'] if r['kind']=='ev_charge_window' and r.get('need_id') in ids]
        context['A']['controls']=[r for r in context['A']['controls'] if r['kind']!='ev_charge_window']+full
        context['A']['controls'].sort(key=lambda r:(r['asset_id'],r['start_min'],r['end_min']))
        context['horizon_min'][1]=max([context['horizon_min'][1]]+[r['end_min'] for r in context['physical_ev_connections']])
        context['horizon_min'][0]=min([context['horizon_min'][0]]+[r['start_min'] for r in context['physical_ev_connections']])
    context['reference']['binding']['A_commands_sha256']=command_hash(context['A'])
    context['reference']['binding']['context_sha256']=digest({k:v for k,v in context.items() if k!='reference'})
    context['reference']['day_scope']='one24h_question;history_and_complete_service_tail_are_not_extra_questions'
    return context

def dated_context(case,problem,A,date,configuration,manifest_sha256):
    from .daily_services import compile_daily_contract,audit_context_daily_services
    from .common import digest
    context=_dated_context_before_daily_cardinality(case,problem,A,date,configuration,manifest_sha256)
    context['daily_service_requirements']=compile_daily_contract(case,date)
    context['programme_service_date_by_need']={j['need_id']:j['date'] for j in problem['jobs']}
    context['daily_service_acceptance']=audit_context_daily_services(case,context)
    context['reference']['binding']['context_sha256']=digest({k:v for k,v in context.items() if k!='reference'})
    return context

def generate_day_baseline(case,date,reference,configuration,manifest_sha256,*,native_appliance_source_path):
    """Canonical daily A entry: daily tasks -> solve -> source/native gates.

    Returns plan evidence only. Physical simulations and final B selection
    remain separately bound downstream steps.
    """
    from .eb_primary import sample_A
    from .daily_services import audit_context_daily_services
    from .eb_alignment import verify_native_target,audit
    if configuration['A_target_context_mode']!='frozen_v3':
        raise ValueError('V9_DAILY_A_REQUIRES_DIRECT_SOURCE_TARGET_MODE_frozen_v3')
    target=verify_native_target(native_appliance_source_path)
    question_date=dt.date.fromisoformat(date)
    anchor=(question_date-dt.timedelta(days=question_date.weekday())).isoformat()
    problem=build_problem(case,anchor,reference,days=7,service_date=date)
    result=sample_A(problem,native_appliance_source_path,configuration['seed'],
                    deterministic_time=configuration['A_deterministic_time'])
    output=dict(schema='eb.daily_baseline_generation.v1',problem=problem,result=result,
                status=result['status'],context=None,daily_acceptance=None,native_acceptance=None,
                physical_outcomes_computed=False,human_answers_generated=False,
                A_solver_execution=dict(deterministic_time_budget=configuration['A_deterministic_time'],
                    budget_unit='OR-Tools deterministic time',construction_method_version_preserved=True))
    if result['status']!='feasible':return output
    context=dated_context(case,problem,result,date,configuration,manifest_sha256)
    context['native_execution_contract']['native_target']=target
    from .common import digest
    context['reference']['binding']['context_sha256']=digest({k:v for k,v in context.items() if k!='reference'})
    daily=audit_context_daily_services(case,context)
    native=audit(context,context['A'],side='A')
    output.update(context=context,daily_acceptance=daily,native_acceptance=native,
                  status='accepted_plan_only' if daily['passed'] and native['passed'] else 'daily_baseline_rejected')
    return output
