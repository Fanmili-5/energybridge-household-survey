"""Avoid certain overloads without changing appliance services or EV handling."""
import collections
import math
from common import *

def fixed_loads(w,y):
    assets={d['asset_id']:d for d in w['parameter_pack']['devices']};load=collections.defaultdict(float)
    for t in y['tasks']:
        p=assets[t['asset_id']]['parameters'];kw=p.get(t['kind'],p)['power_kw']
        for m in range(t['start_min'],t['end_min'],10):load[m]+=kw
    return load

def repair_charging(w,y):
    load=fixed_loads(w,y);pack=w['parameter_pack'];bg=pack['background_reserved_kw'];limit=pack['home_service_limit_kw']
    ev=next((d for d in pack['devices']if'ev'in d['types']),None);changes=[]
    if not ev:return y,changes
    p=ev['parameters'];kw=p['charger_kw'];on_main=ev['circuit']!='EV_bay';branch=pack['circuit_limit_kw'][ev['circuit']]
    events=[e for e in y['EV_battery_energy_events']if e['kind']=='traction']
    for day in y['days'].values():
        for c in list(day['controls']):
            if c['kind']!='ev_charge_window':continue
            old=c['start_min'];duration=c['actual_charge_end_min']-old;last=c['last_step_power_fraction']
            def feasible(start):
                return all((not on_main or load[m]+bg+kw*(last if m==start+duration-10 else 1)<=limit+1e-8)
                    and kw*(last if m==start+duration-10 else 1)<=branch+1e-8 for m in range(start,start+duration,10))
            start=next((s for s in range(old,c['end_min']-duration+1,10)if feasible(s)),None)
            if start is None:
                # A timer can pause automatic charging while the vehicle stays
                # connected. This never adds a plug, unplug, trip or human visit.
                remaining=c['battery_energy_kWh'];selected=[]
                for m in range(old,c['end_min'],10):
                    fraction=min(1.,remaining/(kw*p['efficiency']/6))
                    if (not on_main or load[m]+bg+kw*fraction<=limit+1e-8)and kw*fraction<=branch+1e-8:
                        energy=kw*p['efficiency']/6*fraction;selected.append((m,energy,fraction));remaining-=energy
                        if remaining<1e-8:break
                if remaining>1e-6:raise ValueError('NO_ELECTRICALLY_FEASIBLE_EV_WINDOW:'+c['need_id'])
                groups=[]
                for item in selected:
                    if not groups or groups[-1][-1][0]+10!=item[0]:groups.append([])
                    groups[-1].append(item)
                parts=[]
                for ix,group in enumerate(groups):
                    q=dict(c);q.update({'start_min':group[0][0],'end_min':group[-1][0]+10,
                        'actual_charge_end_min':group[-1][0]+10,'battery_energy_kWh':sum(t[1]for t in group),
                        'grid_energy_kWh':sum(t[1]for t in group)/p['efficiency'],'last_step_power_fraction':group[-1][2],
                        'automatic_segment_index':ix+1,'automatic_segment_count':len(groups),'same_physical_connection':True})
                    parts.append(q)
                    for m,energy,fraction in group:
                        load[m]+=kw*fraction if on_main else 0;events.append({'kind':'charge','start_min':m,'end_min':m+10,'battery_kWh':energy})
                index=day['controls'].index(c);day['controls'][index:index+1]=parts
                changes.append({'need_id':c['need_id'],'reason':'automatic pause around known loads;continuous feasible slot unavailable',
                    'start_A_v34_min':old,'segments_A_v34_1_min':[[q['start_min'],q['end_min']]for q in parts],'manual_operations_changed':False})
                continue
            end=start+duration
            if start!=old:
                changes.append({'need_id':c['need_id'],'reason':'known programs plus EV exceeded given inlet envelope','start_A_v34_min':old,'start_A_v34_1_min':start,'manual_operations_changed':False})
                c['start_min']=start;c['actual_charge_end_min']=end
                c['automatic_delay_within_existing_connection']=True
            full_energy=(duration-10)/60*kw*p['efficiency']
            if duration>10:events.append({'kind':'charge','start_min':start,'end_min':end-10,'battery_kWh':full_energy})
            events.append({'kind':'charge','start_min':end-10,'end_min':end,'battery_kWh':c['battery_energy_kWh']-full_energy})
            for m in range(start,end,10):load[m]+=kw*(last if m==end-10 else 1)if on_main else 0
    y['EV_battery_energy_events']=events
    y['known_power_guard']={'fixed_programs_and_EV_and_background':True,'EV_external_bay_is_separate_from_dwelling_main':not on_main,'HVAC_tank_and_offdesign_physics':'not yet validated','no_inlet_enlargement':True}
    return y,changes

def known_power_errors(w,y):
    load=fixed_loads(w,y);pack=w['parameter_pack'];ev=next((d for d in pack['devices']if'ev'in d['types']),None)
    if ev and ev['circuit']!='EV_bay':
        for day in y['days'].values():
            for c in day['controls']:
                if c['kind']!='ev_charge_window':continue
                for m in range(c['start_min'],c['actual_charge_end_min'],10):load[m]+=ev['parameters']['charger_kw']*(c['last_step_power_fraction']if m==c['actual_charge_end_min']-10 else 1)
    return ['KNOWN_FIXED_LOAD_ABOVE_INLET']if any(kw+pack['background_reserved_kw']>pack['home_service_limit_kw']+1e-7 for kw in load.values())else[]
