"""Read-only full A re-audit, using its pinned checks plus departure SOC checks."""
import collections
import copy
import sys
from pathlib import Path

STAGE=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(STAGE.parent/'normal_A_v34_1_20261016/code'))
from common import *
from review import errors,case_errors

def main():
    bindings=read(OUT/'A_BINDINGS10000.json');bad=[];cases=0;departures=0
    parent=OUT.parent/'normal_A_v34_20261016';parents={r['household_id']:r for r in read(parent/'A_BINDINGS10000.json')['records']}
    for ix,row in enumerate(bindings['records']):
        w=read(OUT/row['A_world_path']);year=read(OUT/row['annual_A_path'])
        problems=errors(w,year)
        previous=parents[row['household_id']];old=read(parent/previous['annual_A_path'])
        if row['A_world_sha256']!=previous['A_world_sha256']or row['HVAC_components_sha256']!=previous['HVAC_components_sha256']:problems.append('PARENT_WORLD_OR_HARDWARE_CHANGED')
        if any(year[k]!=old[k]for k in('tasks','operations','journeys','initial_states','profile')):problems.append('PARENT_TASK_OPERATIONS_JOURNEYS_CHANGED')
        for date,day in year['days'].items():
            ref=old['days'][date]
            if any(day[k]!=ref[k]for k in('activity','shared','weather','needs','textiles')):problems.append('PARENT_NEEDS_OR_BACKGROUND_CHANGED')
            if [c for c in day['controls']if c['kind']!='ev_charge_window']!=[c for c in ref['controls']if c['kind']!='ev_charge_window']:problems.append('PARENT_NON_EV_CONTROL_CHANGED')
        ev=next((d for d in w['parameter_pack']['devices']if'ev'in d['types']),None)
        if ev:
            # Integrate only charge delivered before each departure; no daily reset.
            charges=sorted((e for e in year['EV_battery_energy_events']if e['end_min']>e['start_min']),key=lambda e:e['start_min'])
            traction=0.;charged=0.;cursor=0;initial=year['initial_states']['EV_SOC']*ev['parameters']['capacity_kwh']
            for j in year['journeys']:
                t=j['absolute_departure_min']
                while cursor<len(charges)and charges[cursor]['end_min']<=t:
                    charged+=charges[cursor]['battery_kWh'];cursor+=1
                partial=0.
                if cursor<len(charges)and charges[cursor]['start_min']<t:
                    e=charges[cursor];partial=e['battery_kWh']*(t-e['start_min'])/(e['end_min']-e['start_min'])
                before=initial-traction+charged+partial
                if before+1e-6<j['required_departure_soc']*ev['parameters']['capacity_kwh']:problems.append('ACTUAL_DEPARTURE_TARGET_SOC_NOT_MET')
                traction+=j['traction_kWh'];departures+=1
        for r in row['cases']:
            p=OUT/r['path'];c=read(p);cases+=1
            if sha(p)!=r['sha256']:problems.append('CASE_BYTES_CHANGED')
            problems+=case_errors(w,c)
            # Every displayed need is exactly the same dated annual need, shifted once.
            offset=origin(dt.date.fromisoformat(c['date']))
            annual={n['need_id']:n for d in year['days'].values()for n in d['needs']}
            for n in c['needs_A']:
                expected=copy.deepcopy(annual[n['need_id']])
                for k in ('release_min','deadline_min','delivery_deadline_min','load_min','unload_min','connection_start_min','departure_min'):
                    if k in expected:expected[k]-=offset
                if expected!=n:problems.append('NEED_NOT_FROZEN_ANNUAL_CONTEXT')
        if problems:bad.append({'household_id':row['household_id'],'errors':sorted(set(problems))})
        if(ix+1)%100==0:print({'A_households_reaudited':ix+1,'failures':len(bad)},flush=True)
    report={'accepted':not bad and cases==10000,'households':len(bindings['records']),'cases':cases,'actual_departures_checked':departures,
            'failures':bad,'A_bindings_sha256':sha(OUT/'A_BINDINGS10000.json'),'A_seal_sha256':sha(OUT/'FINAL_SEAL.json'),
            'A_bytes_modified':False,'parent_family_needs_trips_operations_hardware_preserved':not any(any('PARENT_'in e for e in r['errors'])for r in bad),
            'limitations':['whole EnergyPlus assembly and physical service delivery pending','daily appliance use and mobility are given benchmark tasks, not population prevalence','HVAC uses occupied rooms and reference weather; indoor comfort remains unvalidated']}
    save(STAGE/'A_REAUDIT.json',report)
    if bad:raise SystemExit(2)

if __name__=='__main__':main()
