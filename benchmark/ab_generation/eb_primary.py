"""Household binding for the original EB appliance-call model, without handling."""
from copy import deepcopy
import datetime as dt
import hashlib,importlib.util,math,sys
from .common import digest
from .daily_services import compile_daily_contract
from .upstream_eb_routine import _schedule_no_dr_routine_appliances

PROTOCOL='eb.primary_appliance_calls.v1'
KINDS={'AC':'ac','WM':'washer','DR':'dryer','DW':'dishwasher','WH':'water_heater','EV':'ev'}
NATIVE_SHA='be072673de26228a286e5ab9223d160a2a71084fa7b6c9146dbc5d024a879de9'
_CACHE={}
def active(context):
    return context.get('source',{}).get('appliance_command_protocol')==PROTOCOL

def native_module(path):
    key=str(path)
    if key not in _CACHE:
        from pathlib import Path
        if hashlib.sha256(Path(path).read_bytes()).hexdigest()!=NATIVE_SHA:raise ValueError('UNPINNED_EB_APPLIANCE_SOURCE')
        spec=importlib.util.spec_from_file_location('eb_primary_native_'+digest(key)[:12],path)
        module=importlib.util.module_from_spec(spec);sys.modules[spec.name]=module;spec.loader.exec_module(module);_CACHE[key]=module
    return _CACHE[key]

def build_problem(case,date,reference):
    from .v9_date_adapter import reference_calendar,union
    h=case['household'];q=dt.date.fromisoformat(date);dates=[date,(q+dt.timedelta(days=1)).isoformat()]
    contract=compile_daily_contract(case,date);assets={};byfun={};configs={}
    for aid,reg in h['service_asset_registry'].items():
        functions=[f for f in reg['functions'] if f in KINDS]
        if not functions:continue
        kind=KINDS[functions[0]]
        device=dict(asset_id=aid,kind=kind,types=[KINDS[f] for f in functions],
            room_id='home' if 'AC' in functions else 'parking' if 'EV' in functions else 'kitchen' if 'DW' in functions else 'utility',
            parameters={},using_household_ids=[case['case_id']],
            target_control_authorized=bool(set(functions)&set(h['controlled_function_ids'])))
        for f in functions:
            byfun[f]=aid;k=KINDS[f]
            if f in ('WM','DR','DW'):
                ref=reference['programs'][k];duration=ref['duration_min']/60
                earliest=float(ref.get('earliest_h',8.0));latest=float(ref.get('latest_h',22.0))
                if latest<earliest:latest+=24
                latest=min(24.0,latest)
                if earliest<0 or duration<=0 or latest-earliest<duration:raise ValueError('NO_COMPLETE_SAME_DAY_PROGRAMME_WINDOW:'+k)
                configs[k]=dict(present=True,earliest_h=earliest,latest_h=latest,preferred_h=float(ref.get('preferred_h',14.0)),
                    duration_h=duration,power_kw=ref['nominal_peak_kw'],shiftable=f in h['controlled_function_ids'],
                    dr_adjustable=f in h['controlled_function_ids'])
                device['parameters'][k]={'power_kw':ref['nominal_peak_kw']}
            elif f=='AC':device['parameters']['max_electric_W']=reference['AC_nominal_upper_W']
            elif f=='WH':device['parameters']['maximum_C']=reference['tank_maximum_C']
            elif f=='EV':
                ev=h['ev'];device['parameters'].update(capacity_kwh=ev['reference_battery_kwh'],charger_kw=ev['reference_charger_kw'],
                  efficiency=ev['charge_efficiency'],initial_energy_kwh=ev['arrival_soc']*ev['reference_battery_kwh'],
                  target_soc=ev['departure_soc_target'],minimum_soc=reference['EV_reserve_SOC'],
                  charge_session_policy='single_contiguous_session_per_episode')
        assets[aid]=device
    days={d:dict(base_min=i*1440,operator_windows={},calendars=reference_calendar(h,q.weekday()+i),reservations=[]) for i,d in enumerate(dates)}
    configs['refrigerator']={'present':False}
    configs['water_heater']=dict(present='WH' in byfun,normal_start_h=float(reference.get('WH_normal_start_h',17)),
        normal_end_h=float(reference.get('WH_normal_end_h',21)),normal_temp_c=reference['tank_normal_C'],
        pre_heat_window_start_h=15.0,pre_heat_window_end_h=18.0,bath_required_h=21.0,
        rated_kw=h.get('equipment',{}).get('water_heater_available',{}).get('reference_heater_kw',2.0),
        dr_adjustable='WH' in h['controlled_function_ids'])
    if not 0<=configs['water_heater']['normal_start_h']<configs['water_heater']['normal_end_h']<=24:
        raise ValueError('NON_EV_WATER_HEATER_MUST_NOT_OVERNIGHT')
    configs['ev']={'present':False};EV=dict(failures=[],journeys=[],connections=[])
    if 'EV' in byfun:
        ev=h['ev'];mid=ev['vehicle_user_member_id']
        if mid not in {m['id'] for m in h['members']}:raise ValueError('EV_DRIVER_NOT_SOURCE_MEMBER')
        parking=ev['parking_sessions'][q.weekday()];base=parking['arrival']//1440*1440
        arrival=parking['arrival']-base;departure=parking['next_departure']-base
        homes=union([[i*1440+r['start_min'],i*1440+r['end_min']] for i,d in enumerate(dates)
            for r in days[d]['calendars'][mid] if r['location']=='home'])
        intersections=[(max(a,arrival),min(z,departure)) for a,z in homes if max(a,arrival)<min(z,departure)]
        if not intersections:raise ValueError('EV_SOURCE_CONNECTION_HAS_NO_HOME_WITNESS')
        start,end=max(intersections,key=lambda x:x[1]-x[0]);lo=math.ceil(start/10)*10;hi=math.floor(end/10)*10
        if hi<=lo or not 0<=lo<1440 or hi>2880:raise ValueError('INVALID_COMPLETE_SOURCE_EV_EPISODE')
        if ev['arrival_soc']<reference['EV_reserve_SOC']-1e-9:raise ValueError('GIVEN_EV_SOC_BELOW_NATIVE_MINIMUM')
        need=case['case_id']+':EV:selected_parking_episode:'+date;aid=byfun['EV']
        EV['connections']=[dict(need_id=need,start_min=lo,end_min=hi,origin='given_source_parking_episode')]
        EV['journeys']=[dict(absolute_departure_min=hi,absolute_arrival_min=hi,traction_kWh=0.0,
            origin='selected_episode_departure_target;no_invented_trip_energy')]
        EV['episode']=dict(scope=ev['service_scope'],service_date=date,source_driver_member_id=mid,mapped_operator_id=mid,asset_id=aid,
            source_parking_interval=[arrival,departure],physical_home_witness=[start,end],connection_interval=[lo,hi],
            initial_state_scope='given_SOC_at_selected_arrival;not_a_multi_day_driving_trajectory',
            daily_traction_or_arrival_SOC_reset_invented=False)
        configs['ev']=dict(present=True,arrival_h=lo/60,departure_h=(hi%1440)/60,charger_kw=ev['reference_charger_kw'],
             capacity_kwh=ev['reference_battery_kwh'],target_soc=ev['departure_soc_target'],min_soc=reference['EV_reserve_SOC'],
             initial_soc=ev['arrival_soc'],efficiency=ev['charge_efficiency'],daily_drive_kwh=0.0)
    jobs=[]
    for req in contract['programme_requirements']:
        k=req['kind'];cfg=configs[k];nid=date+':daily:'+k
        job=dict(need_id=nid,asset_id=req['asset_id'],kind=k,date=date,release_min=round(cfg['earliest_h']*60),
            deadline_min=round(cfg['latest_h']*60),start_window_min=[math.ceil(cfg['earliest_h']*6)*10,math.floor((cfg['latest_h']-cfg['duration_h'])*6)*10+10],
            preferred_start_min=round(cfg['preferred_h']*60),quantity=1,unit='one_EB_daily_programme',
            policy=dict(duration_min=round(cfg['duration_h']*60),machine_windows_min=[[round(cfg['earliest_h']*60),round(cfg['latest_h']*60)]],
                energy_model='legacy_constant_power',native_earliest_h=cfg['earliest_h'],native_latest_h=cfg['latest_h']),
            origin='original_EB_daily_programme_contract',control_mode=req['mode'])
        # Preserve only the household's explicitly declared programme order.
        declared=h.get('service_contracts',{}).get('DR',{}).get('predecessor',{})
        if k=='dryer' and declared.get('same_load_required') and declared.get('timing')=='wash_end_lte_dry_start':
            if 'WM' not in byfun:raise ValueError('DECLARED_WASH_PREDECESSOR_MISSING')
            job['depends_on_need_id']=date+':daily:washer'
            job['programme_order_origin']='existing_household_service_contract;not_EB_manual_handling'
        jobs.append(job)
    controls=[];cool=sum(h['comfort']['preferred_cooling_c'])/len(h['comfort']['preferred_cooling_c'])
    for i,d in enumerate(dates):
        if 'AC' in byfun:controls.append(dict(asset_id=byfun['AC'],kind='ac_setpoint',start_min=i*1440,end_min=(i+1)*1440,
            cooling_setpoint_C=cool,heating_setpoint_C=reference['heating_C'],fan_operating_mode=0))
        if 'WH' in byfun:
            cfg=configs['water_heater'];controls.append(dict(asset_id=byfun['WH'],kind='tank_setpoint',
              start_min=i*1440+round(cfg['normal_start_h']*60),end_min=i*1440+round(cfg['normal_end_h']*60),value_C=cfg['normal_temp_c']))
    return dict(household_id=case['case_id'],anchor=date,end_exclusive=(q+dt.timedelta(days=2)).isoformat(),
        world=dict(household_id=case['case_id'],members=[dict(member_id=m['id'],household_id=case['case_id'],can_operate_asset_ids=[]) for m in h['members']],
            devices=list(assets.values()),native_single_program_per_day=True),
        jobs=jobs,days=days,fixed_operations=[],controls=controls,EV=EV,thermostat_policies=[],nonprogram_requirements=[],
        daily_service_contract=contract,native_appliance_configuration=configs,
        input_lineage=dict(appliance_command_protocol=PROTOCOL,household_case_sha256=digest(case),reference_rules_sha256=digest(reference),
            source_facts_modified=False,requested_days=1,technical_EV_tail_days=1,
            A_method='original_EB_no_DR_allowed_window_sampling_on_declared10min_command_grid',
            manual_handling_fields_consulted=False,programme_completion='same_calendar_date;EV_only_may_overnight'))

class GridSuite:
    """10min command encoding around the unmodified original EB routine."""
    def __init__(self,suite):self.suite=suite
    def shift_appliance(self,name,day,absolute):
        app=self.suite._shiftable[name]
        lo=math.ceil(app.earliest_h*6);hi=math.floor((app.latest_h-app.duration_h)*6)
        tick=min(hi,max(lo,round(absolute*6)))
        return self.suite.shift_appliance(name,day,tick/6)
    def set_ewh_preheat_schedule(self,*a,**k):return self.suite.set_ewh_preheat_schedule(*a,**k)
    def set_ev_mode(self,*a,**k):return self.suite.set_ev_mode(*a,**k)
    def set_ev_charge_window(self,*a,**k):return self.suite.set_ev_charge_window(*a,**k)

def sample_A(problem,native_path,seed):
    native=native_module(native_path);configs=problem['native_appliance_configuration'];last=None
    for attempt in range(256):
        suite=native.ApplianceSuite(deepcopy(configs),sim_days=2,explicit_only=True);proxy=GridSuite(suite)
        record=_schedule_no_dr_routine_appliances(proxy,deepcopy(configs),1,f"{seed}:{problem['household_id']}:{problem['anchor']}:{attempt}")
        tasks=[]
        for j in problem['jobs']:
            rec=suite._shiftable[j['kind']]._days[0]
            if rec.scheduled_abs_h is None:break
            start=round(rec.scheduled_abs_h*60);end=start+j['policy']['duration_min']
            tasks.append(dict(task_id=j['need_id'],need_id=j['need_id'],asset_id=j['asset_id'],kind=j['kind'],
                start_min=start,end_min=end,power_kw=configs[j['kind']]['power_kw'],
                **({'depends_on_need_id':j['depends_on_need_id']} if j.get('depends_on_need_id') else {})))
        if len(tasks)!=len(problem['jobs']):continue
        byneed={t['need_id']:t for t in tasks}
        if any(t.get('depends_on_need_id') and byneed[t['depends_on_need_id']]['end_min']>t['start_min'] for t in tasks):continue
        if any(a['asset_id']==b['asset_id'] and a['start_min']<b['end_min'] and b['start_min']<a['end_min'] for i,a in enumerate(tasks) for b in tasks[i+1:]):continue
        last=(suite,tasks,record,attempt);break
    if last is None:return dict(status='infeasible',A=None,causes=[{'reason':'DECLARED_NATIVE_WINDOWS_OR_ASSET_ORDER_INFEASIBLE'}])
    suite,tasks,record,attempt=last
    background=deepcopy(configs)
    for k in ('washer','dryer','dishwasher'):background[k]={'present':False}
    _schedule_no_dr_routine_appliances(GridSuite(suite),background,2,f'{seed}:EV_completion_background')
    controls=deepcopy(problem['controls']);steps=[]
    if problem['EV']['connections']:
        connection=problem['EV']['connections'][0];aid=problem['EV']['episode']['asset_id'];cfg=configs['ev']
        for t in range(connection['start_min'],connection['end_min'],10):
            power=suite._ev.step(t/60,1/6,False)
            if power>1e-10:steps.append(dict(need_id=connection['need_id'],start_min=t,end_min=t+10,grid_kWh=power/6))
        if suite._ev._soc<cfg['target_soc']-1e-7:raise ValueError('NATIVE_A_EV_DEPARTURE_TARGET_UNMET')
        controls.append(dict(asset_id=aid,kind='ev_charge_window',need_id=connection['need_id'],
            start_min=connection['start_min'],end_min=connection['end_min'],stop_at_target_soc=cfg['target_soc'],
            _unified_id='EB_EV_window:'+connection['need_id']))
    return dict(schema='eb.primary.A.v1',household_id=problem['household_id'],status='feasible',
        A=dict(tasks=tasks,operations=[],controls=controls),input_sha256=digest(problem),portrait_sha256=digest(None),
        service_ledger=[dict(need_id=t['need_id'],actual_start_min=t['start_min'],actual_end_min=t['end_min'],source='original_EB_no_DR_routine') for t in tasks],
        native_routine_record_raw_before_command_grid=record,
        native_accepted_programme_start_h={t['kind']+'_start_h':t['start_min']/60 for t in tasks},
        native_sampler_attempts=attempt+1,ev_charging_steps=steps,
        physical_ev_connections=deepcopy(problem['EV']['connections']),events_prices_B_or_answers_used=False,
        physical_status='not_computed',input_lineage=problem['input_lineage'])
