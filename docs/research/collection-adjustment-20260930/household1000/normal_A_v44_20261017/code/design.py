import math,collections,copy
from common import *
from activity_model import dated,ranges,configure_habits
from shared_context import dated_context
from weather import daily
from demand import profile,textile_input,wants_laundry
from scheduler import Scheduler
from power import repair_charging
from habits import habit_profile,_phase,_thermostats
from dishes import profile as dish_profile,phase as dish_phase,preference as dish_preference

def resource_world(old):
    w=copy.deepcopy(old);w.pop('world_content_sha256',None)
    w['parent_A42_world_content_sha256']=old['world_content_sha256']
    w=configure_habits(w)
    w['generation_manifest']={'stage':'joint_life_calendar_and_A.v44','rules_sha256':rules_id(),'old_annual_A_reused':False,'B_VPP_or_answers_used':False}
    w['normal_A_contract']['upstream_calendar']='joint household habits and real dated contexts rebuilt from source family;no inherited annual calendars'
    w['schema']='eb.normal_A_resource_world.v44';w['world_content_sha256']=digest(w)
    return w

def continuous_A(w):
    devices=w['parameter_pack']['devices'];by={k:[d for d in devices if k in d['types']]for k in ('ac','washer','dryer','dishwasher','water_heater','ev')}
    days={str(date):{'date':str(date),'activity':dated(w,date),'shared':dated_context(w,date),'weather':daily(w,date),
                     'needs':[],'controls':[],'textiles':None}for date in dates()}
    schedule=Scheduler(w,days);journeys=[];ev_energy_events=[]
    # Reserve only actual journey-associated connection/disconnection. There
    # are no extra access requests, event-driven chores or automatic helpers.
    if by['ev']:
        ev=by['ev'][0];p=ev['parameters'];soc=p['initial_soc']
        moving=[(date,days[str(date)]['activity']['transport'])for date in dates()if days[str(date)]['activity']['transport']]
        for i,(date,trip)in enumerate(moving):
            base=origin(date);departure=base+trip['departure_min'];arrival=base+trip['arrival_min']
            prior=soc;soc-=trip['traction_kWh']/p['capacity_kwh']
            if soc<p['min_soc']-1e-9:raise ValueError('EV_TRACTION_BELOW_RESERVE:'+str(date))
            ev_energy_events.append({'kind':'traction','start_min':departure,'end_min':departure,'battery_kWh':-trip['traction_kWh']})
            journeys.append({'date':str(date),**trip,'absolute_departure_min':departure,'absolute_arrival_min':arrival,
                             'departure_soc':prior,'arrival_soc':soc,'required_departure_soc':w['routine']['EV_target_soc']})
            if i+1==len(moving):continue
            nextdate,nexttrip=moving[i+1];deadline=origin(nextdate)+nexttrip['departure_min']
            target=w['routine']['EV_target_soc'];energy=(target-soc)*p['capacity_kwh'];minutes=math.ceil(energy/(p['charger_kw']*p['efficiency'])*6-1e-9)*10
            nid=str(date)+':EV-for-'+str(nextdate)
            plug=schedule.ev_operation(ev,nid,'EV_plug',arrival,deadline-minutes-10,arrival+10)
            unplug=schedule.ev_operation(ev,nid,'EV_unplug',max(plug['end_min']+minutes,deadline-1440),deadline,deadline-10)
            finish=plug['end_min']+minutes
            need={'need_id':nid,'kind':'ev','asset_id':ev['asset_id'],'release_min':arrival,'deadline_min':deadline,
                  'connection_start_min':plug['end_min'],'departure_min':deadline,'next_access_is_actual_trip':True,
                  'required_departure_soc':target,'quantity':energy,'unit':'battery kWh restored before next actual journey',
                  'journey':nexttrip,'requester':ev['operator_id'],'service_purpose':'为下一次已给定行程恢复常用出发电量',
                  'source_or_design_rule':'EB battery/charger/85% target;actual dated journey;no fictitious extra access'}
            days[str(date)]['needs'].append(need)
            control={'asset_id':ev['asset_id'],'kind':'ev_charge_window','need_id':nid,'start_min':plug['end_min'],'end_min':unplug['start_min'],
                     'actual_charge_end_min':finish,'battery_energy_kWh':energy,'grid_energy_kWh':energy/p['efficiency'],
                     'last_step_power_fraction':(energy/(p['charger_kw']*p['efficiency'])*60-(minutes-10))/10,
                     'stop_at_target_soc':target,'disconnect_before_next_actual_departure':True,
                     'prior_evening_disconnect_if_morning_has_no_free_slot':unplug['start_min']//1440<deadline//1440}
            days[str(date)]['controls'].append(control)
            full_energy=(minutes-10)/60*p['charger_kw']*p['efficiency']
            if minutes>10:ev_energy_events.append({'kind':'charge','start_min':plug['end_min'],'end_min':finish-10,'battery_kWh':full_energy})
            ev_energy_events.append({'kind':'charge','start_min':finish-10,'end_min':finish,'battery_kWh':energy-full_energy})
            soc=target

    p=profile(w);inventory=0.;lots=[];deferred=[]
    skeleton={'days':days};laundry_habits=habit_profile(w,skeleton,schedule);dish_habits=dish_profile(w,skeleton,schedule)
    for date in dates():
        key=str(date);data=days[key];base=origin(date);day=data['activity'];nextday=days.get(str(date+dt.timedelta(days=1)),data)['activity'];weather=data['weather']
        yesterday=days.get(str(date-dt.timedelta(days=1)),data)['weather']
        previous=inventory;added,explanation=textile_input(w,p,date-dt.timedelta(days=1),yesterday)
        if by['washer']:inventory+=added;lots.append([date,added])
        else:added=0.
        oldest=(date-lots[0][0]).days if lots else 0;washed=0.;batches=[]
        if by['washer'] and date<END-dt.timedelta(days=2):
            # Daily use is an explicit user-given task condition. Actual dirty
            # mass, timer feasibility and program/retrieval chains still bind.
            due=wants_laundry(p,date,inventory,oldest)
            while due:
                number=len(batches)+1;nid=key+':laundry:'+str(number);d=by['washer'][0]
                amount=min(p['maximum_batch_kg'],inventory)
                phase=_phase(data);h=laundry_habits['choices'][phase];linen=explanation['scheduled_household_linen_kg']>0
                anchor=h['linen_day_anchor_min']if linen else h['usual_anchor_min']
                dinner_delta=day['family_context']['dinner_min']-laundry_habits['dinner_reference_min'][phase]
                shift=int(max(-120,min(120,dinner_delta))//10)*10 if anchor>=990 else 0
                preferred=base+anchor+shift+240*(number-1)
                deadline=base+1440+w['role_policy']['service_policy']['laundry_handover_hour']*60
                try:
                    tasks,handling=schedule.batch(d,nid,'washer',base,deadline,preferred,bool(by['dryer']))
                except ValueError as error:
                    # Keep undelivered inventory and its reason; no replacement
                    # helper, fake completed batch or silent dropped request.
                    deferred.append({'date':key,'quantity_kg':inventory,'reason':str(error)});break
                need={'need_id':nid,'kind':'washer','asset_id':d['asset_id'],'release_min':base,'deadline_min':deadline,
                      'duration_min':120,'quantity':round(amount,6),'unit':'kg','loading_required':True,
                      'delivery_deadline_min':deadline,'maximum_batch_kg':p['maximum_batch_kg'],
                      'service_purpose':'清洗已积累的衣物；按给定库存与家庭常用批量安排',
                      'wearable_clothes_ready_at_program_end':False,
                      'wash_only_delivery':'clean wet textiles to basket;passive drying not simulated'if not by['dryer']else'auto combo wash then dry',
                      'source_or_design_rule':'user-given daily textile task;size-conditioned reference mass plus linen;EB120min program',**handling}
                data['needs'].append(need)
                if by['dryer']:
                    data['needs'].append({'need_id':nid+':dry','kind':'dryer','asset_id':d['asset_id'],'batch_id':nid,'upstream_need_id':nid,
                        'release_min':base,'deadline_min':deadline,'duration_min':90,'quantity':round(amount,6),'unit':'kg',
                        'source_or_design_rule':'same installed automatic combo;EB90min immediately after wash;no manual transfer invented'})
                inventory=max(0.,inventory-amount);washed+=amount;batches.append(nid)
                remaining=amount
                while lots and remaining>1e-8:
                    take=min(lots[0][1],remaining);lots[0][1]-=take;remaining-=take
                    if lots[0][1]<1e-8:lots.pop(0)
                oldest=(date-lots[0][0]).days if lots else 0
                due=inventory>=p['maximum_batch_kg'] # only real remaining load
        data['textiles']={'before_kg':round(previous,6),'generated_kg':round(added,6),'washed_kg':round(washed,6),
                           'after_kg':round(inventory,6),'oldest_days':oldest,'batch_ids':batches,'generation_context':explanation}
        if by['water_heater']:
            d=by['water_heater'][0];times=[]
            for member in w['members']:
                mid=member['member_id'];start=base+day['family_context']['bath_times_min'][mid];times.append(start)
                data['needs'].append({'need_id':key+':bath:'+mid,'kind':'water_heater','asset_id':d['asset_id'],'requester':mid,
                    'release_min':start,'deadline_min':start+10,'quantity':w['routine']['mixed_water_L_per_resident'],'unit':'L mixed water',
                    'target_C':w['routine']['mixed_target_C'],'source_or_design_rule':'retained daily household bathing;dated reserved bath and child assistance'})
            data['controls'].append({'asset_id':d['asset_id'],'kind':'tank_setpoint','start_min':min(times)-180,'end_min':max(times)+40,
                                     'value_C':w['routine']['tank_setpoint_C'],'thermal_delivery_validation':'pending EnergyPlus'})
    # Dishwashing is jointly placed after laundry and existing EV visits.
    for date in dates():
        key=str(date);data=days[key];base=origin(date);day=data['activity'];nextday=days.get(str(date+dt.timedelta(days=1)),data)['activity']
        if by['dishwasher'] and date<END-dt.timedelta(days=1):
            d=by['dishwasher'][0];nid=key+':dishes';release=base+max(day['family_context']['member_dinners_min'].values())+30
            deadline=base+1440+nextday['family_context']['dinner_min']-30
            preferred=base+dish_preference(data,days.get(str(date+dt.timedelta(days=1)),data),dish_habits['choices'][dish_phase(data)]['style'])
            tasks,handling=schedule.batch(d,nid,'dishwasher',release,deadline,preferred,latest_start=base+1910)
            data['needs'].append({'need_id':nid,'kind':'dishwasher','asset_id':d['asset_id'],'release_min':release,'deadline_min':deadline,
                'duration_min':90,'quantity':1,'unit':'EB daily after-dinner program','loading_required':True,
                'service_purpose':'当天餐后集中清洗；早餐午餐餐具在既定日内库存中轮换',
                'source_or_design_rule':'EB daily after-dinner household habit retained;daily service not removed for diversity',**handling})
    result={'schema':'eb.continuous_normal_A.v34','household_id':w['household_id'],'source_world_content_sha256':w['world_content_sha256'],
            'parameter_pack_sha256':w['parameter_pack_sha256'],'activity_rules_unchanged_from_V33':False,'daily_mobility_context_given_before_A':True,
            'anchor':str(ANCHOR),'end_exclusive':str(END),'profile':p,'days':days,'tasks':schedule.tasks,'operations':schedule.ops,
            'journeys':journeys,'EV_battery_energy_events':ev_energy_events,'deferred_laundry':deferred,
            'initial_states':{'EV_SOC':w['reference_initial_states']['EV_SOC'],'textile_inventory_kg':0.,
                              'tank_and_building_thermal_state':'requires continuous EP history;not computed here'},
            'B_price_event_answers_consulted':False,'EP_started':0}

    result['profile'].update(household_habits=laundry_habits,dishwasher_habits=dish_habits,living_habits=w['living_habits'])
    result['schema']='eb.continuous_normal_A.v44';result['upstream_calendar_regenerated']=True
    result,_=repair_charging(w,result);_thermostats(w,result)
    return result
