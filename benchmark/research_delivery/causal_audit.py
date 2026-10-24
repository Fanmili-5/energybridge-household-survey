"""Independent literal checks of selected action paths and withdrawal evidence.

Imports the patch application utility, but no generator relevance/admission or
capacity predicate. This validates a plan-side path, never actual response.
"""
import argparse
from collections import defaultdict
from pathlib import Path
from benchmark.ab_generation.common import read,save
from benchmark.ab_generation.model import apply


def overlap(a,z,b,y):return max(a,b)<min(z,y)


def resource_conflict(plan,e,kind):
    ops={o['operation_id']:o for o in plan['operations']}
    a,b=ops[e['support_operation_id']],ops[e['root_operation_id']]
    return a[kind+'_id']==b[kind+'_id'] and overlap(a['start_min'],a['end_min'],b['start_min'],b['end_min'])


def material_conflict(plan,e):
    ops=plan['operations']
    a=next(o for o in ops if o['need_id']==e['root_need_id'] and o['kind']=='unload')
    b=next(o for o in ops if o['need_id']==e['support_need_id'] and o['kind']=='load')
    return a['end_min']>b['start_min']


def known_power(c,plan):
    """Independent flat-program/nominal-EV arithmetic; no thermal envelopes."""
    devices={d['asset_id']:d for d in c['devices']};power=defaultdict(float)
    for t in plan['tasks']:
        p=devices[t['asset_id']]['parameters'];p=p.get(t['kind'],p)
        kw=t.get('power_kw',p.get('power_kw'))
        for minute in range(max(c['decision_min'],t['start_min']),min(c['horizon_min'][1],t['end_min']),10):power[minute]+=kw*1000
    groups=defaultdict(list)
    for s in c['reference'].get('ev_charging_steps',[]):groups[s['need_id']].append(s)
    for nid,ss in groups.items():
        original=[r for r in c['A']['controls'] if r['kind']=='ev_charge_window' and r['need_id']==nid]
        if not original:continue
        rating=devices[original[0]['asset_id']]['parameters']['charger_kw']
        left=sum(s['grid_kWh'] for s in ss if s['start_min']>=c['decision_min'])
        windows=[r for r in plan['controls'] if r['kind']=='ev_charge_window' and r['need_id']==nid]
        stop=min(c['horizon_min'][1],max(r['end_min'] for r in original))
        for minute in range(max(c['decision_min'],min(s['start_min'] for s in ss)),stop,10):
            if any(r['start_min']<=minute and minute+10<=r['end_min'] for r in windows):
                amount=min(left,rating/6);left-=amount;power[minute]+=amount*6000
    return power


def direct_path(c,component,A,B):
    if component['family'] in ('washer','dryer','dishwasher'):
        old={t['task_id']:t for t in A['tasks']}
        return any((r['start_min'],r['end_min'])!=(old[r['task_id']]['start_min'],old[r['task_id']]['end_min']) and
            (overlap(r['start_min'],r['end_min'],1080,1140) or overlap(old[r['task_id']]['start_min'],old[r['task_id']]['end_min'],1080,1140))
            for p in component['patches'] if p.get('collection')=='tasks' for r in p['rows'])
    if component['family']=='ev':
        pause=component['magnitude'].get('permission_pause_interval_min')
        if pause is None:
            p=next((p for p in component['patches'] if p['type']=='control_pause'),None)
            if p:pause=[p['start_min'],p['end_min']]
        if not pause or not overlap(*pause,1080,1140):return False
        nid=component.get('service_need_id');ops=[o for o in A['operations'] if o.get('need_id')==nid and o['asset_id']==component['asset_id']]
        spans=[(a['end_min'],b['start_min']) for a in ops for b in ops if a['kind']=='EV_plug' and b['kind']=='EV_unplug']
        spans += [(r['start_min'],r['end_min']) for r in c.get('physical_ev_connections',[]) if r['need_id']==nid]
        return any(overlap(a,z,1080,1140) for a,z in spans)
    field=component['magnitude'].get('axis','tank')
    field='value_C' if component['family']=='water_heater' else field+'_setpoint_C'
    a=[r for r in A['controls'] if r['asset_id']==component['asset_id']]
    b=[r for r in B['controls'] if r['asset_id']==component['asset_id']]
    points=sorted({1080,1140}|{t for r in a+b for t in (r['start_min'],r['end_min']) if 1080<t<1140})
    for t in points[:-1]:
        av=next((r.get(field) for r in a if r['start_min']<=t<r['end_min']),None)
        bv=next((r.get(field) for r in b if r['start_min']<=t<r['end_min']),None)
        if av!=bv:return True
    return False


def check_case(c,proposal,A=None,B=None):
    """Audit all literal components; reusable for the complete candidate bank."""
    A=c['A'] if A is None else A
    B=apply(A,proposal['patches']) if B is None else B
    records=[]
    for child in proposal['components']:
        link=child['event_relevance'];passed=False;errors=[]
        if link['role']=='direct_event_request':passed=direct_path(c,child,A,B)
        else:
            without=apply(A,[p for part in proposal['components'] if part['id']!=child['id'] for p in part['patches']])
            for e in link['evidence']:
                kind=e['kind']
                if kind.startswith(('operator_conflict','room_conflict')):
                    f=lambda p:resource_conflict(p,e,'operator' if kind.startswith('operator') else 'room')
                    passed |= not f(A) and f(without) and not f(B)
                elif kind=='material_transfer':
                    passed |= not material_conflict(A,e) and material_conflict(without,e) and not material_conflict(B,e)
                elif kind=='machine_occupancy':
                    def f(plan):
                        roots=[t for t in plan['tasks'] if t['need_id']==e['root_need_id']]
                        supports=[t for t in plan['tasks'] if t['need_id']==e['support_need_id']]
                        return any(a['asset_id']==b['asset_id'] and overlap(a['start_min'],a['end_min'],b['start_min'],b['end_min']) for a in roots for b in supports)
                    passed |= not f(A) and f(without) and not f(B)
                elif kind=='known_schedule_supply_conflict_caused_by_event_request':
                    aa,bb,ww=known_power(c,A),known_power(c,B),known_power(c,without);limit=c['electrical']['supply_W']
                    passed |= bool(e['minutes']) and all(aa[t]<=limit+1e-6 and ww[t]>limit+1e-6 and bb[t]<=limit+1e-6 for t in e['minutes'])
        for change in child['magnitude'].get('companion_setpoint_changes',[]):
            t=change['start_min'];r=next(r for r in B['controls'] if r['asset_id']==child['asset_id'] and r['kind']=='ac_setpoint' and r['start_min']<=t<r['end_min'])
            h,k=r['heating_setpoint_C'],r['cooling_setpoint_C'];d=change['required_deadband_C']
            restored=(k-change['A']) if change['field']=='heating_setpoint_C' else (change['A']-h)
            if k-h<d-1e-8 or restored>=d-1e-8:errors.append('COMPANION_WITHDRAWAL_NOT_NECESSARY')
        record=dict(case_id=proposal['id'],household_id=proposal['household_id'],date=proposal['date'],component_id=child['id'],role=link['role'],
            passed=bool(passed) and not errors,errors=errors)
        records.append(record)
    return records


def run(out,collections=None):
    from .acceptance import record_sources
    out=Path(out);records=[];failures=[];case_count=0
    for coll in map(Path,collections or (out/'fifty',out/'fresh-public/collection')):
        _,contexts=record_sources(coll)
        for m in read(coll/'MATERIALS.json.gz'):
            case_count+=1
            c=read(contexts[(m['household_id'],m['date'])]);A,B=m['A'],m['B']
            checked=check_case(c,m['proposal'],A,B)
            records.extend(checked)
            failures.extend(r for r in checked if not r['passed'])
    result=dict(passed=not failures,selected_cases=case_count,components=len(records),failures=failures,records=records,
        imports_generator_admission_or_relevance=False,scope='independent literal event/control/dependency path;not actual physical help or acceptance')
    save(out/'INDEPENDENT_CAUSAL_CHECK.json',result);return {k:v for k,v in result.items() if k not in ('records','failures')}|{'failures':failures}


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--out',required=True);p.add_argument('--collection',action='append');a=p.parse_args();print(run(a.out,a.collection))
