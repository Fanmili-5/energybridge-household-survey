"""Small actual-device domains with separately written mathematical truth.

This module builds no household distribution and supplies no acceptance labels.
The finite domains are fixed test instruments, not production sample quotas.
"""
import copy
import itertools
from pathlib import Path
from ..common import read


def fixtures():
    base=read(Path(__file__).parents[1]/'examples/control.json')
    for mode in ('wash_to_separate_dryer','same_machine_two_batches','midnight_transfer','calendar_conflict_retained'):
        c=copy.deepcopy(base);c['reference']['thermal']={};c['reference']['information_set']['mode']='offline_unexecuted_A_plan'
        c['reference']['ev_charging_steps']=[];c['devices']=[];c['needs']=[]
        c['A']=dict(tasks=[],operations=[],controls=[]);c['reservations']=[];c.pop('electrical',None)
        anchor=1420 if mode=='midnight_transfer' else 1080
        same=mode=='same_machine_two_batches';ids=['washer','washer' if same else 'dryer']
        for aid in sorted(set(ids)):
            c['devices'].append(dict(asset_id=aid,kind=aid,types=[aid],room_id=aid+'-room',parameters=dict(power_kw=1)))
        c['authority']=dict(immutable_operator_ids=[],assets={a:dict(authorized_operator_ids=['adult'],target_control_authorized=True) for a in ids})
        c['operator_windows']={'adult':[] if mode=='calendar_conflict_retained' else [[480,1920]]}
        for i,(nid,aid,start) in enumerate([('first',ids[0],anchor),('second',ids[1],anchor+40)]):
            t=dict(task_id=nid,need_id=nid,asset_id=aid,kind='washer' if i==0 or same else 'dryer',start_min=start,end_min=start+20,power_kw=1)
            if i==1 and not same:t['depends_on_need_id']='first'
            c['A']['tasks'].append(t)
            c['needs'].append(dict(need_id=nid,asset_id=aid,kind=t['kind'],release_min=480,deadline_min=1920,
                timer_allowed=True,maximum_preload_wait_min=120,maximum_retrieval_wait_min=120,machine_windows_min=[[0,1440]]))
            for kind,s in [('load',start-10),('unload',start+20)]:
                c['A']['operations'].append(dict(operation_id=nid+kind,need_id=nid,asset_id=aid,kind=kind,
                    operator_id='adult',room_id=aid+'-room',start_min=s,end_min=s+10))
        c['horizon_min']=[480,1920]
        for shifts in itertools.product((-20,0,20),repeat=2):
            b=copy.deepcopy(c['A'])
            for rows in (b['tasks'],b['operations']):
                for r in rows:
                    delta=shifts[0 if r['need_id']=='first' else 1];r['start_min']+=delta;r['end_min']+=delta
            first_end=anchor+20+shifts[0]+10;second_load=anchor+40+shifts[1]-10
            # Independently stated hold/transfer inequality, not an auditor call.
            truth=first_end<=second_load
            yield mode,c,b,truth


def run():
    from .independent import audit
    from .candidates import engineering_issues,issues
    from .ipog import generate
    counts={};mismatches=[];coverage_mismatches=[]
    groups={}
    for name,c,b,expected in fixtures():
        errors=audit(c,c['A'],b)
        patches=[dict(type='rows',collection=k,identity=i,rows=b[k]) for k,i in [('tasks','task_id'),('operations','operation_id')]]
        checks,_,_=issues(c,patches,['first','second'])
        generated=engineering_issues(c,b,['first','second'],checks)
        if (not errors)!=expected or (not generated)!=expected:
            mismatches.append(dict(fixture=name,expected=expected,independent=errors,generator=generated,B=b))
        counts[name]=counts.get(name,0)+1
        groups.setdefault(name,[]).append((c,b,expected))
    for name,rs in groups.items():
        good=[list(divmod(i,3)) for i,(_,_,ok) in enumerate(rs) if ok]
        def oracle(partial):
            found=[r for r in good if all(r[i]==v for i,v in partial.items())]
            return ('feasible',found[0],'independent_device_enumerator') if found else ('infeasible',None,'enumerated_all_device_values')
        result=generate([[0,1,2]]*2,oracle)
        for target in result['coverage']:
            expected=any(all(r[i]==v for i,v in target['target']) for r in good)
            if expected!=(target['witness_row'] is not None):coverage_mismatches.append(dict(fixture=name,target=target))
    # Native control axes are enumerated independently of the program fixtures.
    from ..model import control_issues
    base=read(Path(__file__).parents[1]/'examples/control.json')
    for heat,cool in itertools.product((20,24,28),(24,26,40)):
        c=copy.deepcopy(base);c['A']=dict(tasks=[],operations=[],controls=[])
        ac=next(d for d in c['devices'] if 'ac' in d['types'])
        b=copy.deepcopy(c['A']);b['controls']=[dict(asset_id=ac['asset_id'],kind='ac_setpoint',start_min=1080,end_min=1140,
            heating_setpoint_C=heat,cooling_setpoint_C=cool,heating_and_cooling_deadband_C=2)]
        expected=cool-heat>=2
        a=audit(c,c['A'],b);g=engineering_issues(c,b,(),control_issues(c,b))
        if (not a)!=expected or (not g)!=expected:mismatches.append(dict(fixture='thermal_deadband',heat=heat,cool=cool,independent=a,generator=g))
        counts['thermal_deadband']=counts.get('thermal_deadband',0)+1
    for start,end in itertools.product((1070,1080,1190),(1090,1200,1210)):
        c=copy.deepcopy(base);ev=next(d for d in c['devices'] if 'ev' in d['types'])
        c['A']=dict(tasks=[],operations=[dict(asset_id=ev['asset_id'],need_id='connection',operation_id=k,kind=k,
            start_min=a,end_min=a+10,operator_id='adult',room_id=ev['room_id']) for k,a in [('EV_plug',1070),('EV_unplug',1200)]],
            controls=[dict(asset_id=ev['asset_id'],need_id='connection',kind='ev_charge_window',start_min=1080,end_min=1090)])
        b=copy.deepcopy(c['A']);b['controls'][0].update(start_min=start,end_min=end)
        expected=1080<=start<end<=1200
        a=audit(c,c['A'],b);g=engineering_issues(c,b)
        if (not a)!=expected or (not g)!=expected:mismatches.append(dict(fixture='EV_physical_connection',start=start,end=end,independent=a,generator=g))
        counts['EV_physical_connection']=counts.get('EV_physical_connection',0)+1
    return dict(schema='eb.device_exhaustive.v2',cases=sum(counts.values()),fixtures=counts,
                engineering_mismatches=mismatches,conditional_denominator_mismatches=coverage_mismatches,
                independent_equations='wash_transfer_or_same_asset_hold_end <= next_load_start',
                scope='declared_small_device_domains;not_full_control_space_or_behavioral_validation',
                passed=not mismatches and not coverage_mismatches)
