"""Live EP feedback with EB planning, device state, application and checkpoints.

The household questionnaire supplies P0 and observed preferences. The adapter
omits benchmark household grading; device execution and checkpoint helpers are
from the pinned family runner. Both branches use the same live EP adapter.
"""
from copy import deepcopy
from evaluation_window import window_for,clock
import json
import re
import sys
import time
from pathlib import Path
from resource_limits import ep_compute, api_request
from common import file_hash, write_json
from eb_execution import upstream, replay, source_manifest
from paired_ep import EP, TEMPLATE, WEATHER, build_idf, read_series, find
from eb_controller_adapter import control_context, native_fallback, daily_plan_due, apply_hvac, planning_evidence
from household_config import ensure_household_config, bind_household

class EBPlanner:
    def __init__(self, request, folder, progress):
        self.request=request; self.folder=folder; self.progress=progress
        self.responses=[]; self.calls=[]; self.rounds=[]; self.last_audit={}

    def __call__(self, loop, sim_h, observed, history, reasons):
        from energybridge.llm.client import LLMClient
        runner,_=upstream(); r=self.request; scenario=r['scenario']; event=scenario['event']
        horizon=window_for(scenario)['end_sim_h']
        absolute={**event,'trigger_h':72+event['trigger_h'],'end_h':72+event['end_h']}
        folder=self.folder/f'round_{len(self.rounds)+1:03d}';folder.mkdir(parents=True)
        from proposal_contract import at
        if not hasattr(loop,'household_config'):bind_household(loop,r)
        household=loop.household_config
        bounds=control_context(loop)
        self.progress('planning',f"EB 正在根据 {at(sim_h%24)} 的模拟状态更新安排（第 {len(self.rounds)+1} 次）")
        loop.agent_profile_capsule_by_event_id={event['id']:deepcopy(household['observable_profile'])}
        calendar=runner._agent_observable_calendar_context(household,event,occupied=observed.get('occupancy_count',0)>0,occupancy=observed.get('occupancy_count'))
        upcoming=runner._find_active_or_upcoming_vpp_event(sim_h,vpp_events=[absolute])
        completed_context={'event_id':event['id'],'status':'ended','ended_event':absolute} if upcoming is None else None
        evidence=planning_evidence(loop,sim_h=sim_h,observed=observed,event=upcoming,
            appliances=household['appliances'],tariff=scenario['tariff'])
        inputs=runner._adaptive_v3_observable_planning_inputs(
            loop,event_id=event['id'],sim_h=sim_h,hod=sim_h%24,
            temp=observed['temperature_c'],out_t=observed['outdoor_c'],facility_w=observed['facility_w'],
            observable_calendar=calendar,memory_event=completed_context,vpp_event=upcoming,
            user_input='请根据当前实际模拟状态与此前已执行安排继续规划。目标是在通知的响应时段减少用电，并考虑家庭取舍；事件结束后检查恢复与未完成任务。电价全天0.60元/度，无补偿。家庭评价稍后由真人填写。',
            appliance_config=household['appliances'],setpoint_min_c=bounds['minimum_c'],setpoint_max_c=bounds['maximum_c'],
            price_context='Flat tariff 0.60 CNY/kWh; no compensation.',ordinary_plan=r['original_plan']['eb_ordinary_plan'],**evidence)
        inputs['observable_profile']['reported_household_attitudes']=deepcopy(household['tags'])
        inputs['observable_profile']['unreported_preferences']=deepcopy(household['meta']['unmeasured'])
        inputs['observable_state']['equipment_assumptions']={'notice':r['original_plan']['assumptions']['notice'],
            'ac_semantics':household['meta']['ac_semantics']}
        inputs['observable_state']['observed_prefix']=history
        inputs['observable_state']['execution_history']=deepcopy(self.rounds)
        inputs['observable_state']['decision_trigger']=reasons
        inputs['observable_state']['horizon_end_simulation_hour']=horizon
        inputs['observable_state']['post_event_restore_context']=runner._agent_post_vpp_restore_event(sim_h,vpp_events=[absolute])
        constraints=inputs.get('explicit_constraints',[])
        inputs['explicit_constraints']=[c for c in constraints if 'outside_vpp_window' not in c['constraint_id']]
        write_json(folder/'constraint_scope.json',{'not_used_as_human_quality_gates':[c for c in constraints if 'outside_vpp_window' in c['constraint_id']]})
        system,user=runner._adaptive_v3_planning_prompts(inputs)
        system+='\nEach plan has numeric setpoint and nested appliances. next_check_hour is an absolute simulation hour or null, never just hour-of-day. Use Chinese household explanations. No future simulation observations are supplied.'
        clock_note=f'\n[CURRENT DECISION CLOCK] simulation_hour={sim_h:g}; current clock={at(sim_h%24)}. This is a NEW decision after the previous checks. next_check_hour must be null or in [{sim_h+.25:g},{horizon:g}]. A previous checkpoint at {sim_h:g} has already been reached and cannot be scheduled again.'
        write_json(folder/'planning_input.json',{'inputs':inputs,'system_prompt':system,'user_prompt':user+clock_note,'observed_at_sim_h':sim_h,'control_bounds':bounds,'household_config_hash':self.request['household_config_hash']})
        replies=[];call_number=0
        def ask(extra=''):
            nonlocal call_number
            call_number+=1
            write_json(folder/f'call_{call_number}_request.json',{'system_prompt':system,'user_prompt':user+extra+clock_note,'response_format':{'type':'json_object'},'max_retries':1})
            started=time.perf_counter()
            try:
                with api_request():
                    reply=LLMClient().chat_with_metrics(system,user+extra+clock_note,max_retries=1,response_format={'type':'json_object'})
            except Exception as exc:
                failure={'status':'failed','error_type':type(exc).__name__,'seconds':round(time.perf_counter()-started,3)}
                self.calls.append(failure);write_json(folder/f'call_{call_number}_error.json',failure)
                raise
            self.calls.append({'status':'returned','seconds':round(time.perf_counter()-started,3),'metrics':reply['metrics']})
            replies.append(reply);self.responses.append(reply)
            write_json(folder/f'response_{len(replies)}.json',reply)
            return reply['text']
        def errors(plan):
            return runner._adaptive_v3_plan_control_errors(plan,sim_h=sim_h,total_sim_hours=horizon,setpoint_min_c=bounds['minimum_c'],setpoint_max_c=bounds['maximum_c'])
        try:
            raw=ask()
        except Exception as exc:
            # API failure follows the same controller fallback; it is not a household rejection.
            raw=None;result={'selected_executable_plan':None,'status':'llm_unavailable','error_type':type(exc).__name__}
        else:
            result=runner._adaptive_v3_resolve_planning_response(raw,planning_inputs=inputs,policy_error_fn=errors,
                replan_fn=lambda feedback:ask('\n[EB FORMAT REPAIR]\n'+json.dumps(feedback,ensure_ascii=False)))
        write_json(folder/'planning_audit.json',result)
        selected=result['selected_executable_plan']
        self.last_audit={'controller_source':'model','fallback_used':False}
        if selected is None:
            selected=native_fallback(loop,sim_h,observed['temperature_c'],absolute)
            self.last_audit={'controller_source':'eb_native_fallback','fallback_used':True,'failure_status':result.get('status'),
                             'source_reference':'family_runner.py:11478-11489;12138 onward'}
            write_json(folder/'controller_fallback.json',{'plan':selected,**self.last_audit})
        plan={k:deepcopy(v) for k,v in selected.items() if k in ('setpoint','appliances','next_check_hour')}
        explanation=(result.get('final_portfolio_audit',{}).get('model_selection',{}).get('selection_reason',''))
        if self.last_audit['fallback_used']:
            explanation='本次规划未产生可执行指令，已使用 EB 的回退安排继续模拟。请以实际运行记录评价。'
        return plan, explanation if isinstance(explanation,str) else ''

    def record_applied(self, record):
        # Evidence contains actual applications and contemporaneous observations,
        # never a generated household rating or an acceptance label.
        self.rounds.append(deepcopy(record))


def next_checkpoint(runner, sim_h, requested, event, dt):
    """Mirror family_runner checkpoint scheduling at lines 14665 onward.

    The upstream helper itself supplies pre-event/start/end opportunities.
    The earlier of the model's check and EB event checkpoint is observed at
    the first reachable EP timestep; no fixed local hourly replan rule.
    """
    nxt=requested.get('next_check_hour')
    checkpoint=runner._agent_next_vpp_checkpoint_hour(sim_h,vpp_events=[event])
    if checkpoint is not None and checkpoint>sim_h+max(.05,.5*dt) and (nxt is None or checkpoint<float(nxt)):
        nxt=checkpoint
    return nxt


def simulate_live(folder, request, planner=None):
    runner,Suite=upstream(); original=request['original_plan'];scenario=request['scenario'];p0=original['eb_ordinary_plan']
    household=ensure_household_config(request)
    evaluation=window_for(scenario);horizon=evaluation['end_sim_h'];days=evaluation['simulation_days']
    config=household['appliances'];notification=72+scenario['decision_h']
    event={**scenario['event'],'trigger_h':72+scenario['event']['trigger_h'],'end_h':72+scenario['event']['end_h']}
    folder=Path(folder);folder.mkdir(parents=True,exist_ok=True)
    # Identical IDF and sizing/warmup inputs in both branches. Live actuators
    # override these ordinary schedules only during the weather run.
    seed_execution=replay(original,p0,scenario,proposal=False,sim_days=days)
    idf=build_idf(folder,original,p0,scenario,request['profile'],seed_execution,horizon=horizon)
    sys.path.insert(0,str(EP.parent))
    from pyenergyplus.api import EnergyPlusAPI
    api=EnergyPlusAPI();state=api.state_manager.new_state();ex=api.exchange
    api.runtime.set_console_output_status(state,False)
    loop=runner._FamilyLoop()
    bind_household(loop,request)
    loop.sim_days=days;loop.weather_label='tianjin'
    loop.no_vpp_daily_plan_by_day={day:deepcopy(p0) for day in range(days)}
    write_json(folder/'household_binding.json',{'household_config_hash':request['household_config_hash'],
        'household_id':household['id'],'onboarding':loop.agent_preference_memory['onboarding'],
        'calendar':household['calendar'],'appliances':config,
        'native_household_model':loop.agent_household_model,
        'native_operations_knowledge':loop.agent_operations_knowledge,
        'binding_audit':loop.household_binding_audit})
    loop.appliance_suite=Suite(config,sim_days=days,vpp_events=[event] if planner else [],explicit_only=True)
    loop.sp=p0['setpoint'];loop.planned_occupied_sp=loop.sp;loop.next_check=None
    variables={'temperature_c':('Zone Mean Air Temperature','living_unit1'),
               'outdoor_c':('Site Outdoor Air Drybulb Temperature','Environment'),
               'facility_w':('Facility Total Electricity Demand Rate','Whole Building'),
               'occupancy_count':('Zone People Occupant Count','living_unit1')}
    for name,key in variables.values():ex.request_variable(state,name,key)
    handles={};actuators={};observations=[];controls=[];decisions=[];applications=[];failure=[]
    last_start=None;last_end=None;notified=False;event_started=False;ev_departure=None
    current=deepcopy(p0)
    mapping={'washer':'h_washer','dishwasher':'h_dishwasher','dryer':'h_dryer','ev':'h_ev','water_heater':'h_ewh_sp','refrigerator':'h_refrigerator'}
    def ready(s):
        if not ex.api_data_fully_ready(s) or ex.warmup_flag(s) or not runner._is_weather_run_period(ex,s):return False
        if not handles:
            for key,(name,obj) in variables.items():
                handles[key]=ex.get_variable_handle(s,name,obj)
                if handles[key]<0:raise ValueError('Missing live observation '+name)
            for device,attr in mapping.items():
                handle=ex.get_actuator_handle(s,'Schedule:Compact','Schedule Value','EB_'+device) if config.get(device,{}).get('present') else -1
                if config.get(device,{}).get('present') and handle<0:raise ValueError('Missing EB actuator '+device)
                setattr(loop,attr,handle)
                if handle>=0:actuators[device]=handle
            handles['cooling']=ex.get_actuator_handle(s,'Schedule:Compact','Schedule Value','PilotCooling')
            if handles['cooling']<0:raise ValueError('Missing cooling actuator')
            loop.h_cool=handles['cooling'];loop.h_occ=handles['occupancy_count']
            loop.h_hvac_avail=ex.get_actuator_handle(s,'Schedule:Compact','Schedule Value','PilotACAvailability')
            if loop.h_hvac_avail<0:raise ValueError('Missing HVAC availability actuator')
        return True
    def end_h(s):return (ex.day_of_month(s)-1)*24+ex.hour(s)+ex.zone_time_step_number(s)*ex.zone_time_step(s)
    def guarded(fn):
        def wrapped(s):
            if failure:return
            try:fn(s)
            except Exception as exc:
                failure.append(exc);api.runtime.stop_simulation(s)
        return wrapped
    def begin(s):
        nonlocal last_start,notified,event_started,current
        if not ready(s):return
        dt=ex.zone_time_step(s);now=round(end_h(s)-dt,12)
        if not 0<=now<horizon or now==last_start:return
        previous=last_start if last_start is not None else -dt
        last_start=now
        agent_active=planner is not None and now>=notification-1e-7
        occ,count,source=runner._observable_occupancy(ex,s,loop,household,now,now%24)
        loop.current_occupied=occ;loop.current_occupancy_count=count;loop.current_occupancy_source=source
        if not agent_active and abs(now/24-round(now/24))<1e-7:
            app=runner._adaptive_v3_apply_appliance_actions(loop.appliance_suite,p0['appliances'],now)
            applications.append({'sim_h':now,'kind':'ordinary',**app})
            current=deepcopy(p0);loop.sp=p0['setpoint']
            loop.planned_occupied_sp=loop.sp;loop.daily_plans_done.add(int(now//24))
        reasons=[]
        if agent_active:
            if daily_plan_due(loop,now,previous,dt,days):reasons.append('daily_plan')
            if not notified: reasons.append('notification');notified=True
            if not event_started and now>=event['trigger_h']-1e-7:reasons.append('vpp_start');event_started=True
            if loop.next_check is not None and now>=loop.next_check-1e-7:reasons.append('next_check')
            if reasons:
                if not observations or abs(observations[-1]['end_h']-now)>1e-6:raise ValueError('No current EP observation at decision boundary')
                observed=observations[-1]
                observed=deepcopy(observed)
                observed['occupancy_count']=loop.current_occupancy_count
                history=[deepcopy(row) for row in observations if row['end_h']>72]
                plan,explanation=planner(loop,now,deepcopy(observed),history,reasons)
                bounds=control_context(loop)
                errs=runner._adaptive_v3_plan_control_errors(plan,sim_h=now,total_sim_hours=horizon,setpoint_min_c=bounds['minimum_c'],setpoint_max_c=bounds['maximum_c'])
                if errs:raise ValueError('; '.join(errs))
                app=runner._adaptive_v3_apply_appliance_actions(loop.appliance_suite,plan['appliances'],now)
                current={'setpoint':plan['setpoint'],'appliances':{**current['appliances'],**app['applied_actions']}}
                loop.sp=plan['setpoint'];loop.planned_occupied_sp=loop.sp
                loop.next_check=next_checkpoint(runner,now,plan,event,dt)
                record={'sim_h':now,'trigger':reasons,'observed':deepcopy(observed),'requested_plan':plan,'applied_plan':deepcopy(current),
                        'application':app,'next_check_hour':loop.next_check,'explanation':explanation,
                        'controller':deepcopy(getattr(planner,'last_audit',{'controller_source':'fixture','fallback_used':False})),
                        'control_bounds':bounds}
                decisions.append(record);applications.append({'sim_h':now,'kind':'proposal',**app})
                if hasattr(planner,'record_applied'):planner.record_applied(record)
                write_json(folder/'decision_history.json',decisions)
        available,cooling=apply_hvac(loop,ex,s,original=original,sim_h=now,agent_active=agent_active)
        powers=loop.appliance_suite.step(now,dt)
        runner._write_appliance_actuators(ex,s,loop,powers,now)
        controls.append({'start_h':now,'end_h':now+dt,'cooling_setpoint':cooling,'hvac_available':available,
                         'hvac_availability_actuator':ex.get_actuator_value(s,loop.h_hvac_avail),
                         'actuators':{d:ex.get_actuator_value(s,h) for d,h in actuators.items()}})
    def end(s):
        nonlocal last_end,ev_departure
        if not ready(s):return
        now=round(end_h(s),12)
        if not 0<now<=horizon or now==last_end:return
        last_end=now
        observations.append({'end_h':now,**{k:ex.get_variable_value(s,handles[k]) for k in variables}})
        departure=evaluation.get('ev_departure_sim_h')
        if config['ev'].get('present') and departure is not None and abs(now-departure)<1e-6:
            ev=loop.appliance_suite._ev
            ev_departure={'sim_h':now,'soc':ev._soc,'target_soc':ev.target_soc,'capacity_kwh':ev.capacity_kwh,
                'target_met':ev._soc>=ev.target_soc-1e-6,'source':'EB SOC before departure; charging energy checked against EP meter'}
    api.runtime.callback_begin_zone_timestep_after_init_heat_balance(state,guarded(begin))
    api.runtime.callback_end_zone_timestep_after_zone_reporting(state,guarded(end))
    started=time.perf_counter()
    try:
        with ep_compute():
            code=api.runtime.run_energyplus(state,['-w',str(WEATHER),'-d',str(folder),str(idf)])
    finally:api.state_manager.delete_state(state);api.runtime.clear_callbacks()
    write_json(folder/'control_trace.json',controls);write_json(folder/'observations.json',observations)
    if failure:raise failure[0]
    err=(folder/'eplusout.err').read_text()
    if code or '** Severe **' in err or '**  Fatal  **' in err:raise ValueError('Live EnergyPlus run failed')
    if len(controls)!=round(horizon*6) or len(observations)!=round(horizon*6):raise ValueError('Incomplete live callback trajectory')
    traces=read_series(folder,horizon);meter=find(traces,'Electricity:Facility',horizon=horizon);temp=find(traces,'Zone Mean Air Temperature','living_unit1',horizon=horizon);weather=find(traces,'Site Outdoor Air Drybulb Temperature','Environment',horizon=horizon)
    for observed,actual in zip(observations,temp):
        if abs(observed['end_h']-actual['end_h'])>1e-6 or abs(observed['temperature_c']-actual['value'])>1e-6:raise ValueError('Live observation and finalized EP temperature disagree')
    checks={}
    for d in ('washer','dishwasher','dryer','ev'):
        if config[d]['present']:
            series=find(traces,'Electric Equipment Electricity Energy','EV_Charger' if d=='ev' else 'EB_'+d+'_Equipment',horizon=horizon)
            actual=sum(x['value'] for x in series if x['end_h']>72)/3600000
            expected=sum(r['actuators'].get(d,0)*runner._APPL_DESIGN_W[d]/1000*(r['end_h']-r['start_h']) for r in controls if r['start_h']>=72)
            if abs(actual-expected)>1e-6:raise ValueError('Live EB actuator/EP meter mismatch '+d)
            checks[d]={'actuator_expected_kwh':expected,'metered_kwh':actual}
    if config['ev'].get('present'):
        native_kwh=sum(v for day,v in loop.appliance_suite._ev._day_energy_kwh.items() if day>=3)
        if abs(native_kwh-checks['ev']['metered_kwh'])>1e-6:raise ValueError('EB charge state and EP meter disagree')
        checks['ev']['native_charge_kwh']=native_kwh
    from service_outcomes import water_outcomes,task_outcomes
    water=water_outcomes(traces,horizon) if config['water_heater'].get('present') else None
    out={'task_outcomes':task_outcomes(loop.appliance_suite),'evaluation_window':evaluation,'ev_departure':ev_departure,'water_outcome':water,'electricity':[{'start_h':r['start_h'],'end_h':r['end_h'],'kwh':r['value']/3600000} for r in meter],
         'temperature':[{'end_h':r['end_h'],'c':r['value']} for r in temp],'weather':[{'end_h':r['end_h'],'c':r['value']} for r in weather],
         'controls':controls,'decisions':decisions,'execution':{'applications':applications,'services':loop.appliance_suite.all_results()},
         'task_energy_checks':checks,'seconds':round(time.perf_counter()-started,3),'live_observation_sql_check':True,
         'warning_count':int(re.search(r'Completed Successfully--\s*(\d+) Warning',err).group(1)),
         'idf_sha256':file_hash(idf),'weather_sha256':file_hash(WEATHER),'template_sha256':file_hash(TEMPLATE)}
    write_json(folder/'trace.json',out);return out


def display_trajectory(original, baseline, proposal, scenario, prediction):
    from proposal_contract import DEVICES
    at=clock
    def intervals(rows,device):
        spans=[]
        for row in rows:
            if row['start_h']<72:continue
            if device=='ac':
                value=round(row['cooling_setpoint'],3) if row['hvac_available'] else None
            else:
                key={'home_ev':'ev','electric_water_heater':'water_heater'}.get(device,device)
                v=row['actuators'].get(key,0)
                value=round(v,5) if device=='electric_water_heater' or v>1e-8 else None
            if value is None:continue
            start,end=row['start_h']-72,row['end_h']-72
            if spans and abs(spans[-1][1]-start)<1e-6 and spans[-1][2]==value:spans[-1][1]=end
            else:spans.append([start,end,value])
        return spans
    def text(spans,device):
        if not spans:return '本情境未运行'
        parts=[]
        for start,end,v in spans:
            label=f'{at(start)}—{at(end)}'
            if device=='ac':label+=f'，设定 {v:g}℃'
            elif device=='electric_water_heater':label+=f'，设定 {v:g}℃'+('（待机）' if v==40 else '')
            else:
                runner,_=upstream();key='ev' if device=='home_ev' else device
                label+=f'，功率 {v*runner._APPL_DESIGN_W[key]/1000:.3f} kW'
            parts.append(label)
        return '；'.join(parts)
    from presentation import plan_chart, segments, thermal_chart
    design_w=upstream()[0]._APPL_DESIGN_W
    rows=[];chart_rows=[]
    for device,record in original['devices'].items():
        a=intervals(baseline['controls'],device);b=intervals(proposal['controls'],device)
        before=text(a,device) if record.get('active') else '本情境不使用'
        after=text(b,device) if record.get('active') else '本情境不使用'
        changed=bool(record.get('active')) and a!=b
        chart_rows.append({'device_id':device,'device':DEVICES[device],'active':bool(record.get('active')),'changed':changed,
                           'original':segments(a,device,design_w) if record.get('active') else [],
                           'proposal':segments(b,device,design_w) if record.get('active') else []})
        rows.append({'device_id':device,'device':DEVICES[device],'original':before,'proposal':after,'changed':changed,'change':'有调整' if changed else '不变'})
    timeline=[]
    trigger_names={'notification':'收到通知','vpp_start':'响应开始','next_check':'复查','daily_plan':'每日规划'}
    for d in proposal['decisions']:
        timeline.append({'time':at(d['sim_h']-72),'trigger':'、'.join(trigger_names[x] for x in d['trigger']),
                         'observed_temperature':f"{d['observed']['temperature_c']:.1f}℃",'explanation':d['explanation']})
    event=scenario['event'];window=at(event['trigger_h'])+'—'+at(event['end_h'])
    return {'title':'原安排与 EB 调整后的运行结果','context':scenario,'prediction':prediction,'rows':rows,
            'schedule_chart':plan_chart(chart_rows,scenario),'temperature_chart':thermal_chart(original,baseline,proposal,scenario),
            'has_changes':any(r['changed'] for r in rows),'baseline_source':original['source'],
            'question':'您是否同意采用 EB 的这套调整安排？',
            'notice':f"模拟通知时间 {at(scenario['decision_h'])}，响应时段 {window}。EB 根据模拟过程中的新状态持续复查和调整。表格展示实际执行轨迹，不只是最后一条指令。两份安排均统计到{window_for(scenario)['end_label']}，含这段时间内的跨日用电；原安排次日延续日常习惯，EB 调整方案次日重新规划。金额差不是自动认定的等服务总节省。未控制真实电器。",
            'assumptions':original['assumptions']['notice']+' 热水温度是控制设定，不是实测出水温度；住宅模型尚未校准到您家。',
            'selection_reason':'以下逐次说明来自 EB 规划时的判断，实际效果请结合模拟结果。',
            'execution_notice':'EB 未执行的指令按原有安排继续处理，已体现在执行轨迹中。' if any(d['application']['rejections'] for d in proposal['decisions']) else '',
            'timeline':timeline,'service_rows':service_rows(original,baseline,proposal),
            'comparison_metrics':[{'label':label,**{side:f"{prediction[side][key]:.2f} {unit}" for side in ('original','proposal')}}
                for label,key,unit in [('比较期总用电（至'+window_for(scenario)['end_label']+'）','comparison_kwh','度'),
                    ('比较期总费用','comparison_cost_cny','元'),('其中次日用电','next_day_kwh','度')]] if prediction else []}


def service_rows(original, baseline, proposal):
    from service_outcomes import display_services
    return display_services(original,baseline,proposal)
