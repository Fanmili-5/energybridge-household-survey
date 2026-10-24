"""Literal full-horizon A checks, separate from CP model construction.

Checks the declared planning model, never thermal delivery or real behavior.
The unchanged greedy comparator may have different need identities; unmatched
services are reported rather than paired with a nearby successful task.
"""
import argparse
from collections import Counter,defaultdict
from pathlib import Path
from benchmark.ab_generation.common import read,save


def contained(start,end,windows):
    cursor=start
    for a,z in sorted(windows):
        if a<=cursor<z:cursor=max(cursor,z)
        if cursor>=end:return True
    return False


def inspect(p,plan,steps):
    errors=[];jobs={j['need_id']:j for j in p['jobs']};tasks={t['need_id']:t for t in plan['tasks']}
    assets={d['asset_id']:d for d in p['world']['devices']};members={m['member_id']:m for m in p['world']['members']}
    operations=defaultdict(dict)
    for o in plan['operations']:operations[o['need_id']][o['kind']]=o
    missing=sorted(set(jobs)-set(tasks));extra=sorted(set(tasks)-set(jobs))
    people=defaultdict(list);rooms=defaultdict(list);holds=defaultdict(list)
    def fail(code,need):errors.append(dict(code=code,need_id=need))
    for nid,j in jobs.items():
        if nid not in tasks:continue
        t=tasks[nid];policy=j['policy'];pair=operations[nid]
        if j.get('automatic_parent_need_id'):
            parent=tasks.get(j['automatic_parent_need_id']);source=jobs.get(j['automatic_parent_need_id'])
            d=assets[j['asset_id']]
            if d.get('automatic_programs')!=['washer','dryer'] or not {'washer','dryer'}<=set(d.get('types',[])):
                fail('AUTOMATIC_CAPABILITY_NOT_DECLARED',nid)
            if not parent or not source or parent['asset_id']!=t['asset_id'] or source.get('automatic_child_need_id')!=nid:
                fail('AUTOMATIC_PHASE_PARENT_OR_ASSET',nid)
            elif parent['end_min']!=t['start_min']:fail('AUTOMATIC_PHASE_NOT_IMMEDIATE',nid)
            if pair:fail('INVENTED_AUTOMATIC_TRANSFER',nid)
            if t['asset_id']!=j['asset_id'] or t['kind']!=j['kind']:fail('WRONG_DEVICE_OR_SERVICE',nid)
            if t['end_min']-t['start_min']!=policy['duration_min']:fail('PROGRAM_DURATION',nid)
            unload=operations[j['automatic_parent_need_id']].get('unload')
            if not unload or not j['release_min']<=t['start_min']<t['end_min']<=unload['start_min']<unload['end_min']<=j['deadline_min']:
                fail('AUTOMATIC_PHASE_ORDER_OR_DEADLINE',nid)
            if unload and unload['start_min']-t['end_min']>policy['maximum_retrieval_wait_min']:
                fail('AUTOMATIC_RETRIEVAL_WAIT',nid)
            windows=[(day['base_min']+a,day['base_min']+z) for day in p['days'].values() for a,z in policy['machine_windows_min']]
            if not contained(t['start_min'],t['end_min'],windows):fail('MACHINE_WINDOW',nid)
            continue
        if not {'load','unload'}<=set(pair):fail('MISSING_HANDLING',nid);continue
        l,u=pair['load'],pair['unload'];d=assets[j['asset_id']]
        if t['asset_id']!=j['asset_id'] or t['kind']!=j['kind']:fail('WRONG_DEVICE_OR_SERVICE',nid)
        if t['end_min']-t['start_min']!=policy['duration_min']:fail('PROGRAM_DURATION',nid)
        if not j['release_min']<=l['start_min']<l['end_min']<=t['start_min']<t['end_min']<=u['start_min']<u['end_min']<=j['deadline_min']:
            fail('SERVICE_ORDER_OR_DEADLINE',nid)
        completion=t['end_min']
        child_id=j.get('automatic_child_need_id')
        if child_id:
            child=tasks.get(child_id)
            if child is None:fail('MISSING_AUTOMATIC_DRY_PHASE',nid)
            else:completion=child['end_min']
            if completion>u['start_min']:fail('UNLOAD_BEFORE_AUTOMATIC_END',nid)
        if t['start_min']-l['end_min']>policy['maximum_preload_wait_min'] or u['start_min']-completion>policy['maximum_retrieval_wait_min']:fail('HANDLING_WAIT',nid)
        if not policy['timer_allowed'] and l['end_min']!=t['start_min']:fail('NO_TIMER',nid)
        machine=[]
        for day in p['days'].values():machine.extend((day['base_min']+a,day['base_min']+z) for a,z in policy['machine_windows_min'])
        if not contained(t['start_min'],t['end_min'],machine):fail('MACHINE_WINDOW',nid)
        holds[j['asset_id']].append((l['start_min'],u['end_min'],nid))
        for o in (l,u):
            mid=o['operator_id'];m=members.get(mid,{})
            qualified=j['asset_id'] in m.get('can_operate_asset_ids',[]) and m.get('household_id') in d['using_household_ids']
            if d.get('operator_id'):qualified &= mid==d['operator_id']
            if d.get('normal_operator_ids') is not None:qualified &= mid in d['normal_operator_ids']
            if not d.get('operator_id') and d.get('normal_operator_ids') is None:qualified &= m.get('household_id')==p['household_id']
            if not qualified:fail('OPERATOR_QUALIFICATION',nid)
            windows=[w for day in p['days'].values() for w in day['operator_windows'].get(mid,[])]
            if not contained(o['start_min'],o['end_min'],windows):fail('OPERATOR_WINDOW',nid)
            people[mid].append((o['start_min'],o['end_min'],o['operation_id']))
            rooms[d['room_id']].append((o['start_min'],o['end_min'],o['operation_id']))
            if any(r['room_id']==d['room_id'] and max(o['start_min'],day['base_min']+r['start_min'])<min(o['end_min'],day['base_min']+r['end_min']) for day in p['days'].values() for r in day['reservations']):fail('ROOM_RESERVED',nid)
        parent=j.get('depends_on_need_id')
        if parent and (parent not in operations or 'unload' not in operations[parent] or operations[parent]['unload']['end_min']>l['start_min']):fail('WASH_DRY_TRANSFER',nid)
    for o in p['fixed_operations']:people[o['operator_id']].append((o['start_min'],o['end_min'],o['operation_id']))
    for label,groups in [('PERSON',people),('ROOM',rooms),('MACHINE_HOLD',holds)]:
        for key,intervals in groups.items():
            intervals.sort()
            if any(a[1]>b[0] for a,b in zip(intervals,intervals[1:])):fail(label+'_OVERLAP',key)
    ev=next((d for d in assets.values() if d['kind']=='ev'),None)
    if ev:
        ep=ev['parameters'];energy=ep['initial_energy_kwh'];trips={t['absolute_departure_min']:t for t in p['EV']['journeys']}
        bytime=defaultdict(float)
        for s in steps:
            bytime[s['start_min']]+=s['grid_kWh']
            if not any(c['start_min']<=s['start_min']<s['end_min']<=c['end_min'] for c in p['EV']['connections']):fail('EV_CONNECTION',s['need_id'])
            if s['grid_kWh']>ep['charger_kw']/6+1e-5:fail('EV_POWER',s['need_id'])
        for t in range(0,len(p['days'])*1440,10):
            if t in trips:
                if energy<ep['target_soc']*ep['capacity_kwh']-1e-4:fail('EV_DEPARTURE_TARGET',str(t))
                energy-=trips[t]['traction_kWh']
                if energy<ep['minimum_soc']*ep['capacity_kwh']-1e-4:fail('EV_RESERVE',str(t))
            energy+=bytime[t]*ep['efficiency']
            if energy>ep['capacity_kwh']+1e-4:fail('EV_CAPACITY',str(t))
    supply=p['world'].get('electrical',{}).get('supply_W')
    if supply:
        for t in range(0,len(p['days'])*1440,10):
            power=sum(x.get('power_kw',assets[x['asset_id']]['parameters'].get('power_kw',0)) for x in plan['tasks'] if x['start_min']<=t<x['end_min'])
            power+=sum(s['grid_kWh']*6 for s in steps if s['start_min']==t)
            if power*1000>supply+1e-5:fail('KNOWN_NOMINAL_SUPPLY',str(t))
    return dict(passed=not errors and not missing and not extra,errors=errors,missing_need_ids=missing,extra_need_ids=extra,
        compiled_jobs=len(jobs),scope='literal planning model;thermal delivery and human preferences not validated')


def run(out):
    out=Path(out);rows=[]
    for source in sorted((out/'fresh-public/source').glob('*/PARALLEL_PROBLEM.json.gz')):
        p=read(source);hid=p['household_id']
        for ap in sorted((out/'fresh-public/A'/hid).glob('*.json.gz')):
            a=read(ap)
            if a['status']=='feasible':rows.append(dict(household_id=hid,seed=int(ap.name.split('.')[0]),**inspect(p,a['A'],a['ev_charging_steps'])))
        legacy=p['legacy_comparator'];ev=next((d for d in p['world']['devices'] if d['kind']=='ev'),None)
        evsteps=[{**s,'grid_kWh':s['battery_kWh']/ev['parameters']['efficiency']} for s in legacy['EV'].get('charge_events',[])] if ev else []
        rows.append(dict(household_id=hid,seed=None,arm='unchanged_greedy',**inspect(p,legacy['A'],evsteps)))
    result=dict(records=rows,new_A_runs=sum(r['seed'] is not None for r in rows),new_A_failures=[r for r in rows if r['seed'] is not None and not r['passed']],
        comparison_demand_identity_caveat='original greedy demands can differ;missing/extra retained;no superiority inferred')
    save(out/'INDEPENDENT_A_CHECK.json',result);return {k:v for k,v in result.items() if k!='records'}


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--out',required=True);a=p.parse_args();print(run(a.out))
