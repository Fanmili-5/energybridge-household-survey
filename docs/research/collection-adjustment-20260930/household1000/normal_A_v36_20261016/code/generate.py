"""Produce a continuous normal-A calendar for1000 worlds, then derive10000 cases."""
import argparse
import collections
import copy
import math
import shutil
from concurrent.futures import ProcessPoolExecutor
from common import *
from activity_model import dated,ranges
from shared_context import dated_context
from weather import daily
from demand import profile,textile_input,wants_laundry
from scheduler import Scheduler
from power import repair_charging
from design import resource_world,redesign
from hvac import configure as configure_resources,components as hvac_components


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
    for date in dates():
        key=str(date);data=days[key];base=origin(date);day=data['activity'];nextday=days.get(str(date+dt.timedelta(days=1)),data)['activity'];weather=data['weather']
        yesterday=days.get(str(date-dt.timedelta(days=1)),data)['weather']
        previous=inventory;added,explanation=textile_input(w,p,date-dt.timedelta(days=1),yesterday)
        if by['washer']:inventory+=added;lots.append([date,added])
        else:added=0.
        oldest=(date-lots[0][0]).days if lots else 0;washed=0.;batches=[]
        if by['dishwasher'] and date<END-dt.timedelta(days=1):
            d=by['dishwasher'][0];nid=key+':dishes';release=base+max(day['family_context']['member_dinners_min'].values())+30
            deadline=base+1440+nextday['family_context']['dinner_min']-30
            preferred=base+int(d.get('source_EB_usage_defaults_evidence',{}).get('values',{}).get('dishwasher',{}).get('preferred_h',21.0)*60)
            tasks,handling=schedule.batch(d,nid,'dishwasher',release,deadline,preferred)
            data['needs'].append({'need_id':nid,'kind':'dishwasher','asset_id':d['asset_id'],'release_min':release,'deadline_min':deadline,
                'duration_min':90,'quantity':1,'unit':'EB daily after-dinner program','loading_required':True,
                'service_purpose':'当天餐后集中清洗；早餐午餐餐具在既定日内库存中轮换',
                'source_or_design_rule':'EB daily after-dinner household habit retained;daily service not removed for diversity',**handling})
        if by['washer'] and date<END-dt.timedelta(days=2):
            # Daily use is an explicit user-given task condition. Actual dirty
            # mass, timer feasibility and program/retrieval chains still bind.
            due=wants_laundry(p,date,inventory,oldest)
            while due:
                number=len(batches)+1;nid=key+':laundry:'+str(number);d=by['washer'][0]
                amount=min(p['maximum_batch_kg'],inventory)
                daytime=day['day_type']in ('weekend','national_holiday')
                source_pref=d.get('source_EB_usage_defaults_evidence',{}).get('values',{}).get('washer',{}).get('preferred_h',19.)
                preferred=base+(780 if daytime else int(source_pref*60))+240*(number-1)
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
        for d in by['ac']:
            occupied={k:[]for k in('heating','cooling','recirculation_fan')};mode_at={};presence=[]
            cooling_sp=w['role_policy']['thermal']['usual_setpoint_C'];heating_sp=w['normal_A_contract']['usual_heating_setpoint_C']
            for mid,seq in {**day['member_calendars'],**data['shared']['member_calendars']}.items():
                for item in seq:
                    if item['location']!='home'or item['room_id']!=d['room_id']:continue
                    presence.append((mid,base+item['start_min'],base+item['end_min']))
                    sleeping=item['activity']in ('sleep_rest','day_nap','sleep')
                    for minute in range(item['start_min'],item['end_min'],10):
                        temp=weather['hourly_drybulb_C'][minute//60]
                        prior=weather['hourly_drybulb_C'][:minute//60+1]+yesterday['hourly_drybulb_C'][minute//60+1:]
                        mode='heating'if temp<18 else'cooling'if temp>=cooling_sp or(sleeping and max(prior)>=cooling_sp+2 and temp>=22)else'recirculation_fan'
                        old=mode_at.get(minute)
                        priority={'heating':3,'cooling':2,'recirculation_fan':1}
                        if old is None or priority[mode]>priority[old]:mode_at[minute]=mode
            for minute,mode in mode_at.items():occupied[mode].append([base+minute,base+minute+10])
            mode_intervals=[]
            for mode,slots in occupied.items():
                intervals=ranges(slots)
                if mode=='recirculation_fan'and intervals:
                    candidates=[]
                    for a,b in intervals:
                        length=min(60,b-a);start=max(a,min(base+1140,b-length))
                        candidates.append((abs(start-(base+1140)),start,start+length))
                    _,a,b=min(candidates);intervals=[[a,b]]
                mode_intervals.extend((mode,a,b)for a,b in intervals)
            for j,(mode,a,b)in enumerate(sorted(mode_intervals,key=lambda x:x[1])):
                nid=key+':HVAC:'+d['asset_id']+':'+str(j)
                data['needs'].append({'need_id':nid,'kind':'ac','asset_id':d['asset_id'],'requester':sorted({mid for mid,s,e in presence if overlap((a,b),(s,e))}),
                    'release_min':a,'deadline_min':b,'quantity':b-a,'unit':'reference occupied room minutes',
                    'served_rooms':[d['room_id']],'reference_setpoint_C':heating_sp if mode=='heating'else cooling_sp,'mode':mode,
                    'source_or_design_rule':'explicit daily HVAC task;occupied room;EPW selects heating,cooling or recirculation;actual thermal delivery pending EP'})
                data['controls'].append({'asset_id':d['asset_id'],'kind':'ac_setpoint','mode':mode,'start_min':a,'end_min':b,
                    'value_C':heating_sp if mode=='heating'else cooling_sp,'heating_setpoint_C':heating_sp if mode=='heating'else 5.,
                    'cooling_setpoint_C':cooling_sp if mode=='cooling'else 50.,'fan_operating_mode':1,'need_id':nid,
                    'heating_and_cooling_deadband_C':(cooling_sp if mode=='cooling'else 50.)-(heating_sp if mode=='heating'else 5.)})
    return {'schema':'eb.continuous_normal_A.v34','household_id':w['household_id'],'source_world_content_sha256':w['world_content_sha256'],
            'parameter_pack_sha256':w['parameter_pack_sha256'],'activity_rules_unchanged_from_V33':False,'daily_mobility_context_given_before_A':True,
            'anchor':str(ANCHOR),'end_exclusive':str(END),'profile':p,'days':days,'tasks':schedule.tasks,'operations':schedule.ops,
            'journeys':journeys,'EV_battery_energy_events':ev_energy_events,'deferred_laundry':deferred,
            'initial_states':{'EV_SOC':w['reference_initial_states']['EV_SOC'],'textile_inventory_kg':0.,
                              'tank_and_building_thermal_state':'requires continuous EP history;not computed here'},
            'B_price_event_answers_consulted':False,'EP_started':0}


TIME_KEYS=('start_min','end_min','release_min','deadline_min','delivery_deadline_min','connection_start_min','departure_min','actual_charge_end_min','load_min','unload_min')
def relative(item,base):
    result=copy.deepcopy(item)
    for key in TIME_KEYS:
        if key in result:result[key]-=base
    return result

def episode(w,year,date,year_path,year_sha):
    base=origin(date);lo=base-1440;hi=base+3*1440
    controls=[c for day in year['days'].values()for c in day['controls']if c['start_min']<hi and c['end_min']>lo]
    ops=[o for o in year['operations']if lo<=o['start_min']<hi]
    tasks=[t for t in year['tasks']if t['start_min']<hi and t['end_min']>lo]
    ids={x['need_id']for x in tasks+ops+controls if 'need_id'in x}
    needs=[n for day in year['days'].values()for n in day['needs']if n['need_id']in ids or lo<=n['release_min']<hi]
    contexts=[copy.deepcopy(year['days'][str(date+dt.timedelta(days=i))])for i in range(-1,3)]
    for d in contexts:
        d['needs']=[relative(n,base)for n in d['needs']];d['controls']=[relative(c,base)for c in d['controls']]
    target=year['days'][str(date)];owned=target['needs'];counts=collections.Counter(n['kind']for n in owned)
    signature={'task_counts':{k:counts[k]for k in ('washer','dryer','dishwasher','water_heater')},
        'laundry_kg':round(target['textiles']['washed_kg'],1),
        'trip_kWh':target['activity']['transport']['traction_kWh']if target['activity']['transport']else 0.,
        'HVAC_mode_counts':dict(collections.Counter(n['mode']for n in owned if n['kind']=='ac')),
        'HVAC_room_minutes_30min_bins':round(sum(n['quantity']for n in owned if n['kind']=='ac')/30),
        'program_two_hour_phase_bins':sorted((t['kind'],(t['start_min']-base)//120)for t in year['tasks']if t['need_id']in{n['need_id']for n in owned}),
        'outside_person_hours':round(sum(i['end_min']-i['start_min']for seq in target['activity']['member_calendars'].values()for i in seq if i['location']=='outside')/60)}
    signals={}
    for device in w['parameter_pack']['devices']:
        if'ac'not in device['types']:continue
        relevant=[c for c in controls if c['asset_id']==device['asset_id']and c['kind']=='ac_setpoint']
        channels={'available':[],'heat_sp':[],'cool_sp':[],'fan_mode':[]}
        for minute in range(lo,hi,10):
            control=next((c for c in relevant if c['start_min']<=minute<c['end_min']),None)
            channels['available'].append(int(control is not None));channels['fan_mode'].append(control['fan_operating_mode']if control else 0)
            channels['heat_sp'].append(control['heating_setpoint_C']if control else 5.)
            channels['cool_sp'].append(control['cooling_setpoint_C']if control else 50.)
        signals[device['asset_id']]=channels
    return {'schema':'eb.normal_A_case.v34','case_id':w['household_id']+'__'+str(date),'household_id':w['household_id'],'date':str(date),
            'timeline_origin':'local midnight of case date;display/evaluation08:00 through next08:00;negative and>1440 timestamps retained',
            'source_world_content_sha256':w['world_content_sha256'],'parameter_pack_sha256':w['parameter_pack_sha256'],
            'year_A_path':year_path,'year_A_sha256':year_sha,'common_history_start_date':str(date-dt.timedelta(days=7)),
            'HVAC_signal_start_min':-1440,'HVAC_signal_step_min':10,'HVAC_signals':signals,
            'days':contexts,'needs_A':[relative(n,base)for n in needs],
            'A':{'tasks':[relative(t,base)for t in tasks],'operations':[relative(o,base)for o in ops],
                 'controls':[relative(c,base)for c in controls],'changed_controls':[]},
            'substantive_service_signature':signature,'normal_A_before_B':True,'B_generated':False,'physical_delivery_validated':False}


from functools import lru_cache
@lru_cache(maxsize=1)
def parent_records():return {r['household_id']:r for r in read(OUT.parent/'normal_A_v34_1_20261016/A_BINDINGS10000.json')['records']}

def one(job):
    row,run,signature=job;run=Path(run);hid=row['household_id'];record=run/'records'/(hid+'.json')
    if record.exists():return read(record)
    try:
        path=MASTER/row['world_path']
        if sha(path)!=row['world_sha256']:raise ValueError('MASTER_WORLD_CHANGED')
        source=parent_records()[hid]
        parent=OUT.parent/'normal_A_v34_1_20261016'
        w=resource_world(read(parent/source['A_world_path']));wp=run/'worlds'/(hid+'.json');save(wp,w)
        hp=run/'HVAC_components'/(hid+'.json');hp.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(parent/source['HVAC_components_path'],hp)
        year=read(parent/source['annual_A_path']);year,journal=redesign(w,year)
        year['schema']='eb.continuous_normal_A.v36'
        year['parent_annual_A_sha256']=source['annual_A_sha256']
        jp=run/'regeneration'/(hid+'.json');save(jp,{'household_id':hid,'parent_annual_A_sha256':source['annual_A_sha256'],'changes':journal,'background_hardware_quantities_journeys_preserved':True,'physical_acceptance':False})
        yp=run/'annual_A'/(hid+'.json');save(yp,year);ys=sha(yp)
        cases=[]
        for selected in w['random10_date_selection']['dates']:
            date=dt.date.fromisoformat(selected['date']);case=episode(w,year,date,str(yp.relative_to(OUT)),ys)
            cp=run/'cases'/(case['case_id']+'.json');save(cp,case)
            cases.append({'case_id':case['case_id'],'date':str(date),'path':str(cp.relative_to(OUT)),'sha256':sha(cp),
                          'service_signature':case['substantive_service_signature']})
        result={'household_id':hid,'passed':True,'type':row['type'],'master_world_path':row['world_path'],'master_world_sha256':row['world_sha256'],
                'A_world_path':str(wp.relative_to(OUT)),'A_world_sha256':sha(wp),'HVAC_components_path':str(hp.relative_to(OUT)),'HVAC_components_sha256':sha(hp),
                'annual_A_path':str(yp.relative_to(OUT)),'annual_A_sha256':ys,'cases':cases,
                'unique_substantive_days':len({digest(c['service_signature'])for c in cases}),
                'deferred_laundry_count':len(year['deferred_laundry']),'max_dirty_wait_days':max(d['textiles']['oldest_days']for d in year['days'].values())}
    except Exception as error:
        result={'household_id':hid,'passed':False,'error':str(error),'rules_sha256':signature}
    save(record,result);return result


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--workers',type=int,default=4);parser.add_argument('--limit',type=int,default=1000);args=parser.parse_args()
    verify_inputs();signature=rules_id();root=OUT/'runs'/signature[:16]
    for source in list((OUT/'code').glob('*.py'))+[OUT/'GENERATION_RULES.json',OUT/'INPUT_LOCK.json',OUT/'USER_DECISIONS.json']:
        target=root/'source_snapshot'/source.name;target.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(source,target)
    save(root/'RUN.json',{'rules_sha256':signature,'household_limit':args.limit,'B_generated':False,'EP_started':0})
    rows=read(MASTER/'WORLD_BINDINGS1000.json')['records'][:args.limit];records=[]
    with ProcessPoolExecutor(max_workers=args.workers)as pool:
        for r in pool.map(one,[(r,str(root),signature)for r in rows]):
            records.append(r)
            if len(records)%10==0:print({'processed':len(records),'passed':sum(r['passed']for r in records)},flush=True)
    if rules_id()!=signature:raise RuntimeError('GENERATOR_CHANGED_DURING_RUN')
    failed=[r for r in records if not r['passed']]
    report={'households':len(records),'passed':len(records)-len(failed),'failures':failed,'rules_sha256':signature,
            'cases_written':sum(len(r.get('cases',[]))for r in records),'records':records,'EP_started':0}
    save(root/'BUILD_REVIEW.json',report)
    print(canonical({k:v for k,v in report.items()if k!='records'}),flush=True)
    if failed:raise SystemExit(2)
    if len(records)==1000 and not read(OUT/'GENERATION_RULES.json').get('date_mobility_decision_pending',False):
        save(OUT/'A_BINDINGS10000.json',{'schema':'eb.normal_A_bindings.v34','rules_sha256':signature,'households':1000,'cases':10000,'records':records})
        ids={r['household_id']for r in read(MASTER/'SUBSET50.json')['records']}
        subset=[r for r in records if r['household_id']in ids]
        save(OUT/'SUBSET50.json',{'schema':'eb.normal_A_subset.v34','records':subset,'type_counts':dict(collections.Counter(r['type']for r in subset)),
                                'same_master_household_ids':True,'same_A_files_and_hashes':True,'separate_generation':False})

if __name__=='__main__':main()
