"""Exact pinned EB appliance kernels; no LLM or roleplay feedback invocation."""
import csv, datetime as dt, importlib.util
from common import *
KERNEL_PATH=UP/'energybridge/simulation/appliance_sim.py'
spec=importlib.util.spec_from_file_location('eb_assembly_native_appliance_sim',KERNEL_PATH)
kernel=importlib.util.module_from_spec(spec);sys.modules[spec.name]=kernel;spec.loader.exec_module(kernel)
START=dt.date(2025,7,1);SLOTS=144;STEP=1/6
KINDS=['washer','dishwasher','dryer','water_heater','ev']

def round_spec(w,index):
    families=[['washer'],['ac'],['water_heater'],['ev'],['dishwasher'],['dryer'],['washer','dryer'],['ac','water_heater'],['ev','washer'],[]]
    targets=families[index-1];day=index+3;date=START+dt.timedelta(days=day);weekday=date.weekday();jobs=w['weekly_tasks'][weekday]['jobs']
    applicable=[k for k in targets if w['assets'][k]['present'] and (k=='ac' or any(j['kind']==k for j in jobs))]
    context={'date':date.isoformat(),'day_index_from_A_start':day,'decision_h':18.,'event_window_h':[18.,19.],
             'notice_minutes':[30,120][index%2],'event_compensation_CNY_per_kWh':0. if index%2 else .2,
             'event_compensation_is_experimental_factor_not_observed_tariff':True,'requested_device_family':targets,
             'service_constraints':jobs,'evaluation_end_day_index':day+2}
    actions=[]
    if 'washer' in applicable:
        actions.append({'kind':'washer','command':'shift','new_start_h':20.})
        if w['assets']['dryer']['present'] and any(j['kind']=='dryer' for j in jobs):actions.append({'kind':'dryer','command':'shift','new_start_h':22.})
    if 'dishwasher' in applicable:actions.append({'kind':'dishwasher','command':'shift','new_start_h':21.5})
    if 'dryer' in applicable and 'washer' not in applicable:actions.append({'kind':'dryer','command':'shift','new_start_h':22.})
    if 'water_heater' in applicable:actions.append({'kind':'water_heater','command':'heater_reference_preheat','heating_window_h':[16.,18.],'setpoint_C':65.})
    if 'ev' in applicable:actions.append({'kind':'ev','command':'charge_window','window_h':[22.,7.5]})
    if 'ac' in applicable:actions.append({'kind':'ac','command':'cooling_setpoint_window','setpoint_C':28.,'window_h':[18.,19.],'restore_setpoint_C':26.})
    # An earlier preheat is an earlier intervention; freeze that decision/state explicitly.
    if any(a['kind']=='water_heater' for a in actions):context['decision_h']=16.
    return {'schema':'eb.assembled_round.v1','household_id':w['household_id'],'round_index':index,'world_content_sha256':w['world_content_sha256'],
            'context':context,'actions':actions,'applicability':'actionable_reference' if actions else 'no_action_reference',
            'proposal_origin':'prespecified EB-compatible task proposal experiment;not a claimed LLM-generated plan',
            'human_acceptance':None,'relative_preference':None,'modified_plan_requires_new_execution':True}

def trace(w,days=365,case=None):
    configs={k:dict(v['config']) for k,v in w['assets'].items()};configs['refrigerator']={'present':False}
    suite=kernel.ApplianceSuite(configs,sim_days=days,explicit_only=True)
    target_day=case['context']['day_index_from_A_start'] if case else -1
    events=[]
    if case:events=[{'trigger_h':target_day*24+18.,'end_h':target_day*24+19.}]
    suite._vpp_events=events
    output=[];states=[];commands=[];service=[]
    for day in range(days):
        date=START+dt.timedelta(days=day);weekday=date.weekday();jobs=w['weekly_tasks'][weekday]['jobs'];trip=next((j for j in jobs if j['kind']=='ev'),None)
        # Calendar-specified travel inputs change; original simulator function bodies stay intact.
        suite._ev.daily_drive_kwh=trip['daily_drive_kWh'] if trip else 0.
        suite._ev.arrival_h=trip['arrival_h'] if trip else 0.
        suite._ev.departure_h=trip['departure_h'] if trip else 24.
        suite.set_ev_mode(day,'normal')
        for kind in ['washer','dishwasher','dryer']:
            job=next((j for j in jobs if j['kind']==kind),None)
            if job:assert suite.shift_appliance(kind,day,day*24+job['baseline_start_h'])
        if w['assets']['water_heater']['present']:suite._water_heater.set_preheat_schedule(day,17.,21.,55.,force_routine=True)
        heater_window=[17.,21.];heater_sp=55.
        for slot in range(SLOTS):
            hod=slot*STEP;absolute=day*24+hod
            if case and day==target_day and abs(hod-case['context']['decision_h'])<1e-7:
                for action in case['actions']:
                    k=action['kind'];ok=True
                    if action['command']=='shift':ok=suite.shift_appliance(k,day,day*24+action['new_start_h'])
                    elif k=='ev':ok=suite.set_ev_charge_window(day,*action['window_h'])
                    elif k=='water_heater':
                        heater_window=action['heating_window_h'];heater_sp=action['setpoint_C'];ok=suite.set_ewh_preheat_schedule(day,*heater_window,heater_sp)
                    commands.append({'day':day,'sim_h':absolute,'action':action,'EB_kernel_accepted':ok})
                    if not ok:raise ValueError('unexecutable reference proposal:'+canonical(action))
            if trip and abs(hod-trip['departure_h'])<1e-7:
                service.append({'kind':'ev','day':day,'date':date.isoformat(),'departure_soc_before_trip':suite._ev._soc,'required_soc':trip['target_SOC'],'served':suite._ev._soc>=trip['target_SOC']-1e-8})
            power=suite.step(absolute,STEP)
            ac=26.
            if case and day==target_day and any(a['kind']=='ac' for a in case['actions']) and 18<=hod<19:ac=28.
            # Thermal water tank uses the same requested heating clock but its own real state equation.
            tank_sp=heater_sp if heater_window[0]<=hod<heater_window[1] else 10.
            n=w['N'];draw_begin=20.5;draw_end=draw_begin+n/6
            row={k:power[k]*1000 for k in KINDS};row.update({'tank_setpoint_C':tank_sp,'water_draw_fraction':1. if draw_begin<=hod<draw_end and w['assets']['water_heater']['present'] else 0.,'ac_setpoint_C':ac})
            output.append(row)
            if days<=17 or day<=16:
                states.append({'sim_h_start':absolute,'date':date.isoformat(),'EV_SOC_after_step':suite._ev._soc,'powers_W':{k:row[k] for k in KINDS},'tank_setpoint_command_C':tank_sp})
        for kind in ['washer','dishwasher','dryer']:
            job=next((j for j in jobs if j['kind']==kind),None)
            if job:
                result=suite._shiftable[kind].day_result(day);start=result['scheduled_abs_h'];finish=start+w['assets'][kind]['config']['duration_h']
                service.append({'kind':kind,'day':day,'date':date.isoformat(),'release_h':job['release_h'],'deadline_h':job['deadline_h'],'start_h':start-day*24,'finish_h':finish-day*24,'program_completed':result['completed'],'served':result['completed'] and finish<=day*24+job['deadline_h']+1e-8})
    return {'rows':output,'states':states,'service':service,'applied_commands':commands,'EB_kernel_path':str(KERNEL_PATH),'EB_kernel_sha256':sha(KERNEL_PATH),'tank_proxy_ready_at_bath_not_used_as_thermal_service_truth':True}

def member_room(w,m,date,hod):
    weekday=date.weekday();activity=next(x for x in m['weekly_calendar'][weekday]['intervals'] if x['start_h']<=hod<x['end_h'])
    if activity['location']!='home':return None
    if activity['activity'] in ['personal_and_breakfast','dinner','meal_and_rest']:
        communal=next((r['room_id'] for r in w['layout']['rooms'] if w['household_id'] in r['using_household_ids'] and r['census_room_class']=='living'),None)
        if communal:return communal
    return m['reference_home_room_id']

def write_schedules(w,trace_data,path,annual_base=None,selected_signals=None):
    """Schedule:File is Jan1-indexed; selected simulation calendar spans July--June."""
    rooms=w['layout']['rooms'];members=w['members'];signals=list(trace_data['rows'][0]) if selected_signals is None else selected_signals
    if annual_base is None:
        signals+=['light_'+r['room_id'] for r in rooms]+['background_'+r['room_id'] for r in rooms]
        signals+=['person_'+m['local_id']+'_'+r['room_id'] for m in members for r in rooms if w['household_id'] in r['using_household_ids']]
    data={};full=365*SLOTS
    for i in range(full):
        day,slot=divmod(i,SLOTS);date=START+dt.timedelta(days=day);hod=slot*STEP
        if i<len(trace_data['rows']):values=dict(trace_data['rows'][i])
        else:values=dict(annual_base[i])
        if annual_base is None:
            locations={m['local_id']:member_room(w,m,date,hod) for m in members}
            for r in rooms:
                # Fixed source-backed densities, calendar-driven duty, explicitly separate from named equipment.
                active=(6.5<=hod<22.5 and any(v is not None for v in locations.values()) and w['household_id'] in r['using_household_ids'])
                values['light_'+r['room_id']]=int(active);values['background_'+r['room_id']]=int(active)
            for m in members:
                for r in rooms:
                    if w['household_id'] in r['using_household_ids']:values['person_'+m['local_id']+'_'+r['room_id']]=int(locations[m['local_id']]==r['room_id'])
        doy=date.timetuple().tm_yday-1;data[doy*SLOTS+slot]=[values[k] for k in signals]
    path.parent.mkdir(parents=True,exist_ok=True)
    with path.open('w',newline='') as f:
        writer=csv.writer(f);writer.writerow(signals);writer.writerows(data[i] for i in range(full))
    return {k:i+1 for i,k in enumerate(signals)}
