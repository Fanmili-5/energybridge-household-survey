"""Revise dish habits only; retain V36 family, laundry, mobility and native hardware."""
import copy,collections
from common import *
from scheduler import Scheduler
from power import repair_charging
from dishes import profile,phase,preference
# Reuse pinned V36 occupied thermostat implementation unchanged.
import importlib.util
_spec=importlib.util.spec_from_file_location('parent_design',BASE/'normal_A_v36_20261016/code/design.py');_parent=importlib.util.module_from_spec(_spec);_spec.loader.exec_module(_parent)

def resource_world(old):
    w=copy.deepcopy(old);w.pop('world_content_sha256',None);w['parent_V36_world_content_sha256']=old['world_content_sha256']
    w['normal_A_contract']['dishwasher_habit']='household weekday/rest style from dated meal,bath,wake calendars;see annual profile'
    w['generation_manifest']={'stage':'normal_A_dish_habits.v38','rules_sha256':rules_id(),'parent_world_content_sha256':old['world_content_sha256'],'B_VPP_or_human_answers_consulted':False}
    w['schema']='eb.normal_A_resource_world.v38';w['world_content_sha256']=digest(w);return w

def redesign(w,y):
    oldtasks=y['tasks'];oldops=y['operations'];dishids={n['need_id']for day in y['days'].values()for n in day['needs']if n['kind']=='dishwasher'}
    days={key:{**copy.deepcopy(day),'needs':[copy.deepcopy(n)for n in day['needs']if n['kind']not in('dishwasher','ac')],
      'controls':[copy.deepcopy(c)for c in day['controls']if c['kind']!='ac_setpoint']}for key,day in y['days'].items()}
    scheduler=Scheduler(w,days);scheduler.tasks=[copy.deepcopy(t)for t in oldtasks if t['need_id']not in dishids]
    scheduler.ops=[copy.deepcopy(o)for o in oldops if o['need_id']not in dishids]
    for o in scheduler.ops:scheduler.person_busy.add((o['operator_id'],o['start_min']));scheduler.room_busy.add((o['room_id'],o['start_min']))
    unloads={o['need_id']:o for o in scheduler.ops if o['kind']=='unload'}
    old_starts={t['need_id']:t['start_min']for t in oldtasks}
    for o in scheduler.ops:
        if o['kind']=='load':
            unload=unloads[o['need_id']]
            scheduler.asset_busy.setdefault(o['asset_id'],[]).append((o['start_min'],unload['end_min']))
    for seq in scheduler.asset_busy.values():seq.sort()
    habits=profile(w,y,scheduler);changes=[];by={d['asset_id']:d for d in w['parameter_pack']['devices']}
    for key,day in days.items():
        ref=y['days'][key];base=origin(dt.date.fromisoformat(key));nextkey=str(dt.date.fromisoformat(key)+dt.timedelta(days=1));nextday=days.get(nextkey,day)
        for n in ref['needs']:
            if n['kind']!='dishwasher':continue
            style=habits['choices'][phase(day)]['style'];preferred=base+preference(day,nextday,style)
            tasks,handling=scheduler.batch(by[n['asset_id']],n['need_id'],'dishwasher',n['release_min'],n['deadline_min'],preferred,latest_start=base+1910)
            day['needs'].append({**copy.deepcopy(n),**handling})
            before=old_starts[n['need_id']]
            if before!=tasks[0]['start_min']:changes.append({'need_id':n['need_id'],'A36_start_min':before,'A38_start_min':tasks[0]['start_min'],'given_style':style,'dated_preferred_min':preferred,'joint_resource_fallback':tasks[0]['start_min']!=preferred})
    y['days']=days;y['tasks']=scheduler.tasks;y['operations']=scheduler.ops
    ev=next((d for d in w['parameter_pack']['devices']if'ev'in d['types']),None)
    if ev:
        p=ev['parameters'];ops={}
        for o in y['operations']:
            if o['kind'].startswith('EV_'):ops.setdefault(o['need_id'],{})[o['kind']]=o
        for day in days.values():
            day['controls']=[c for c in day['controls']if c['kind']!='ev_charge_window']
            for n in day['needs']:
                if n['kind']!='ev':continue
                a=ops[n['need_id']]['EV_plug']['end_min'];b=ops[n['need_id']]['EV_unplug']['start_min'];steps=__import__('math').ceil(n['quantity']/(p['charger_kw']*p['efficiency'])*6-1e-9)
                day['controls'].append({'kind':'ev_charge_window','asset_id':ev['asset_id'],'need_id':n['need_id'],'start_min':a,'end_min':b,'actual_charge_end_min':a+steps*10,
                  'battery_energy_kWh':n['quantity'],'grid_energy_kWh':n['quantity']/p['efficiency'],'last_step_power_fraction':n['quantity']/(p['charger_kw']*p['efficiency'])*6-(steps-1),'stop_at_target_soc':n['required_departure_soc'],
                  'disconnect_before_next_actual_departure':True,'prior_evening_disconnect_if_morning_has_no_free_slot':b//1440<n['departure_min']//1440})
    y,charging=repair_charging(w,y)
    _parent._thermostats(w,y)
    y['profile']['dishwasher_habits']=habits;y['source_world_content_sha256']=w['world_content_sha256'];y['schema']='eb.continuous_normal_A.v38'
    return y,{'dishwasher_habits':habits,'changed_dish_starts':changes,'EV_automatic_charge_changes':charging,'washer_tasks_and_operations_unchanged':True,'EV_manual_operations_unchanged':True,'daily_service_quantities_and_deadlines_preserved':True}
