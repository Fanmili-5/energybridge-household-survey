"""Household habits and occupied dual thermostats, independent of B/outcomes."""
import collections
import copy
import math
import statistics
from common import *
from scheduler import Scheduler
from power import repair_charging
from activity_model import ranges

ANCHORS=[420,540,660,840,990,1140]

def resource_world(old):
    w=copy.deepcopy(old);w.pop('world_content_sha256',None)
    w['parent_V34_1_world_content_sha256']=old['world_content_sha256']
    w['normal_A_contract'].update(HVAC_modes=['dual_thermostat'],
        mode_selection='indoor dual thermostat decides heating/cooling;outdoor temperature does not select mode',
        minimum_fan_task='up to60 occupied minutes in each08-to-next08 window;cycling fan otherwise',
        appliance_habits='given household-specific feasible habits in annual_A.profile;not inferred observed preferences')
    w['routine']['time_source']='V36 household-specific given habit and dated calendars;see annual_A.profile.household_habits'
    w['generation_manifest']={'stage':'normal_A_design_repair.v36','rules_sha256':rules_id(),
        'parent_world_content_sha256':old['world_content_sha256'],'B_or_human_answers_consulted':False}
    w['schema']='eb.normal_A_resource_world.v36';w['world_content_sha256']=digest(w)
    return w

def _phase(d):return 'rest'if d['activity']['day_type']in('weekend','national_holiday')else'weekday'

def habit_profile(w,y,scheduler):
    device=next((d for d in w['parameter_pack']['devices']if'washer'in d['types']),None)
    if device is None:return {'applies_to_washer':False,'given_not_observed':True}
    duration=210 if'dryer'in device['types']else 120
    wait=240 if'dryer'in device['types']else 90
    score={};medians={};choices={}
    for phase in('weekday','rest'):
        all_days=[d for d in y['days'].values()if d['date'].startswith('2025')and _phase(d)==phase]
        sample=[min((d for d in all_days if dt.date.fromisoformat(d['date']).month==month),key=lambda d:rank(w['household_id'],phase,d['date']))for month in range(1,13)]
        counts=collections.Counter()
        for day in sample:
            base=origin(dt.date.fromisoformat(day['date']));loads=scheduler.slots(base,base+1440,device['room_id']);unloads=loads
            for anchor in ANCHORS:
                start=base+anchor;ls=[s for s in loads if start-720<=s[0]+10<=start];us=[s for s in unloads if start+duration<=s[0]<=start+duration+wait]
                if ls and us:counts[anchor]+=1
        eligible=[a for a in ANCHORS if counts[a]>=6]or[a for a in ANCHORS if counts[a]==max(counts.values(),default=0)]
        selected=min(eligible,key=lambda a:rank(w['household_id'],phase,'given-habit',a))
        earlier=[a for a in eligible if a<selected]
        linen=min(earlier,key=lambda a:rank(w['household_id'],phase,'linen-first',a))if earlier else selected
        choices[phase]={'usual_anchor_min':selected,'linen_day_anchor_min':linen,'eligible_anchors_min':eligible}
        medians[phase]=statistics.median(d['activity']['family_context']['dinner_min']for d in all_days)
        score[phase]={str(a):counts[a]for a in ANCHORS}
    return {'applies_to_washer':True,'given_not_observed':True,'choices':choices,'sampled_calendar_feasibility_counts':score,
        'dinner_reference_min':medians,'source':'12 dated calendars per phase;explicit operator/facility availability;hash chooses among feasible given habits',
        'linen_response':'given habit:prioritize already-generated household linen earlier when a feasible earlier habit exists',
        'not_inferred_from_age_sex_job_or_human_preference':True,'no_date_jitter':True}

def redesign(w,y):
    olddays=y['days'];devices=w['parameter_pack']['devices'];classes={k for d in devices for k in d['types']}
    # The household calendar, quantities, journeys and EV physical visits stay fixed.
    days={key:{**copy.deepcopy(d),'needs':[copy.deepcopy(n)for n in d['needs']if n['kind']not in('washer','dryer','dishwasher','ac')],
               'controls':[copy.deepcopy(c)for c in d['controls']if c['kind']=='tank_setpoint']}for key,d in olddays.items()}
    scheduler=Scheduler(w,days)
    evops=[copy.deepcopy(o)for o in y['operations']if o['kind'].startswith('EV_')]
    scheduler.ops=evops
    for o in evops:
        scheduler.person_busy.add((o['operator_id'],o['start_min']));scheduler.room_busy.add((o['room_id'],o['start_min']))
    habits=habit_profile(w,y,scheduler);by={d['asset_id']:d for d in devices}
    for key,day in days.items():
        base=origin(dt.date.fromisoformat(key));old=olddays[key]
        for n in old['needs']:
            if n['kind']not in('washer','dishwasher'):continue
            d=by[n['asset_id']]
            if n['kind']=='washer':
                phase=_phase(day);h=habits['choices'][phase]
                linen=old['textiles']['generation_context']['scheduled_household_linen_kg']>0
                anchor=h['linen_day_anchor_min']if linen else h['usual_anchor_min']
                # Real dinner changes can alter the routine. Never inject minute jitter.
                dinner_delta=day['activity']['family_context']['dinner_min']-habits['dinner_reference_min'][phase]
                delta=int(max(-120,min(120,dinner_delta))//10)*10 if anchor>=990 else 0
                number=int(n['need_id'].rsplit(':',1)[-1]);preferred=base+anchor+delta+240*(number-1)
            else:
                # Keep the existing after-dinner service and EB90min program.
                preferred=base+max(day['activity']['family_context']['member_dinners_min'].values())+180
            rows,handling=scheduler.batch(d,n['need_id'],n['kind'],n['release_min'],n['deadline_min'],preferred,n['kind']=='washer'and'dryer'in classes)
            need=copy.deepcopy(n);need.update(handling);day['needs'].append(need)
            if n['kind']=='washer'and'dryer'in classes:
                day['needs'].append(copy.deepcopy(next(z for z in old['needs']if z['need_id']==n['need_id']+':dry')))
        for n in day['needs']:
            if n['kind']!='ev':continue
            p=by[n['asset_id']]['parameters'];plug=next(o for o in evops if o['need_id']==n['need_id']and o['kind']=='EV_plug');unplug=next(o for o in evops if o['need_id']==n['need_id']and o['kind']=='EV_unplug')
            duration=math.ceil(n['quantity']/(p['charger_kw']*p['efficiency'])*6-1e-9)*10
            day['controls'].append({'kind':'ev_charge_window','asset_id':n['asset_id'],'need_id':n['need_id'],'start_min':plug['end_min'],'end_min':unplug['start_min'],
                'actual_charge_end_min':plug['end_min']+duration,'battery_energy_kWh':n['quantity'],'grid_energy_kWh':n['quantity']/p['efficiency'],
                'last_step_power_fraction':n['quantity']/(p['charger_kw']*p['efficiency'])*6-(duration/10-1),'stop_at_target_soc':n['required_departure_soc'],
                'disconnect_before_next_actual_departure':True,'prior_evening_disconnect_if_morning_has_no_free_slot':unplug['start_min']//1440<n['departure_min']//1440})
    y['days']=days;y['tasks']=scheduler.tasks;y['operations']=scheduler.ops
    y,charging_changes=repair_charging(w,y)
    _thermostats(w,y)
    y['profile']['household_habits']=habits;y['source_world_content_sha256']=w['world_content_sha256']
    y['schema']='eb.continuous_normal_A.v36';y['HVAC_indoor_feedback_contract']={'heating_C':22.,'cooling_C':w['role_policy']['thermal']['usual_setpoint_C'],
        'plant_selects_mode_from_zone_temperature':True,'daily_fan_task_not_compressor_energy':True,'actual_thermal_delivery':'pending representative EP'}
    return y,{'household_habits':habits,'EV_automatic_charge_changes':charging_changes,'no_EV_manual_operation_changed':True,
              'service_quantities_and_deadlines_preserved':True,'HVAC':'occupied dual thermostat with cycling fan and explicit daily fan task'}

def _thermostats(w,y):
    acs=[d for d in w['parameter_pack']['devices']if'ac'in d['types']];presence={d['asset_id']:set()for d in acs}
    room_assets=collections.defaultdict(list)
    for d in acs:room_assets[d['room_id']].append(d['asset_id'])
    opmap=collections.defaultdict(dict)
    for o in y['operations']:
        if not o['operator_id']in{m['member_id']for m in w['members']}:continue
        opmap[o['start_min']][o['operator_id']]=None if o['kind'].startswith('EV_')else o['room_id']
    for key,day in y['days'].items():
        base=origin(dt.date.fromisoformat(key));calendar={**day['activity']['member_calendars'],**day['shared']['member_calendars']}
        occupied=collections.defaultdict(set)
        for mid,seq in calendar.items():
            for item in seq:
                if item['location']!='home':continue
                for t in range(base+item['start_min'],base+item['end_min'],10):
                    rid=opmap.get(t,{}).get(mid,item['room_id'])
                    if rid in room_assets:occupied[rid].add(t)
        for rid,minutes in occupied.items():
            for aid in room_assets[rid]:presence[aid].update(minutes)
    grouped={}
    for aid,slots in presence.items():
        grouped[aid]=collections.defaultdict(list)
        for t in sorted(slots):grouped[aid][t//1440].append(t)
    fan={aid:set()for aid in presence};start=origin(ANCHOR);stop=origin(END)
    for aid,slots in presence.items():
        for base in range(start,stop,1440):
            index=base//1440
            options=[t for t in grouped[aid][index]+grouped[aid][index+1]if base+480<=t<base+1920]
            # Real occupied slots only;one explicit hour of daily circulation,
            # split if necessary. This is use, not an invented compressor need.
            selected=sorted(options,key=lambda t:(abs(t-(base+1140)),t))[:6]
            fan[aid].update(selected)
    cool=w['role_policy']['thermal']['usual_setpoint_C'];heat=22.
    for key,day in y['days'].items():
        base=origin(dt.date.fromisoformat(key))
        for d in acs:
            aid=d['asset_id'];slots=grouped[aid][base//1440]
            for flag in(0,1):
                intervals=ranges([[t,t+10]for t in slots if int(t in fan[aid])==flag])
                for j,(a,b)in enumerate(intervals):
                    nid=key+':HVAC:'+aid+':'+str(flag)+':'+str(j)
                    day['needs'].append({'need_id':nid,'kind':'ac','asset_id':aid,'mode':'dual_thermostat','release_min':a,'deadline_min':b,'quantity':b-a,
                        'unit':'occupied thermostat availability minutes','served_rooms':[d['room_id']],'requester':sorted(mid for mid,seq in {**day['activity']['member_calendars'],**day['shared']['member_calendars']}.items()if any(item['location']=='home'and item['room_id']==d['room_id']and max(base+item['start_min'],a)<min(base+item['end_min'],b)for item in seq)),
                        'reference_heating_setpoint_C':heat,'reference_cooling_setpoint_C':cool,'reference_setpoint_C':cool,
                        'source_or_design_rule':'occupied dual thermostat;mode selected from actual indoor state in EP;fan minimum is explicit benchmark task'})
                    day['controls'].append({'kind':'ac_setpoint','asset_id':aid,'need_id':nid,'mode':'dual_thermostat','start_min':a,'end_min':b,
                        'value_C':cool,'heating_setpoint_C':heat,'cooling_setpoint_C':cool,'fan_operating_mode':flag,'heating_and_cooling_deadband_C':cool-heat})
