"""Serial greedy adapter on the SAME compiled jobs/targets as CP-SAT.

The original life.Scheduler remains unchanged. This controlled adapter keeps its
scan/latest-load/earliest-retrieval rule but aligns qualifications and continuous
windows with the new contract. It is not an exact historical reproduction.
"""
import argparse
import copy
import math
import time
from pathlib import Path
from benchmark.ab_generation import life
from benchmark.ab_generation.common import read,save,digest
from benchmark.ab_generation.energy import batch_energy
from benchmark.ab_generation.unified.a_solver import dated_targets
from benchmark.ab_generation.unified.delivery import a_score
from .a_review import inspect,contained


class Serial(life.Scheduler):
    def __init__(self,p,portrait,seed):
        super().__init__(p['world'],p['days'],{**life.LIFE_RULES,'seed':seed})
        self.p=p;self.portrait=portrait;self.targets=dated_targets(portrait,p['anchor'])
        for o in p['fixed_operations']:
            self.operations.append(copy.deepcopy(o))
            for t in range(o['start_min'],o['end_min'],10):self.person_busy.add((o['operator_id'],t))
        ev=next((d for d in p['world']['devices'] if d['kind']=='ev'),None)
        self.steps=[{**s,'grid_kWh':s['battery_kWh']/ev['parameters']['efficiency']} for s in p['EV']['charge_events']] if ev else []
        for s in self.steps:self.known_power_W[s['start_min']]+=s['grid_kWh']*6000

    def allowed(self,member,aid):
        if not super().allowed(member,aid):return False
        d=self.assets[aid];mid=member['member_id']
        if d.get('operator_id') and mid!=d['operator_id']:return False
        if d.get('normal_operator_ids') is not None and mid not in d['normal_operator_ids']:return False
        if not d.get('operator_id') and d.get('normal_operator_ids') is None and member['household_id']!=self.p['household_id']:return False
        return True

    def program(self,j):
        aid,nid=j['asset_id'],j['need_id'];policy=j['policy'];duration=policy['duration_min']
        release,deadline=j['release_min'],min(self.limit,j['deadline_min'])
        parent=j.get('depends_on_need_id')
        if parent:
            upstream=next((o for o in self.operations if o['need_id']==parent and o['kind']=='unload'),None)
            if not upstream:return dict(need_id=nid,status='unserved',reason='UPSTREAM_UNSERVED')
            release=max(release,upstream['end_min'])
        energy=batch_energy(j,policy,self.assets[aid]['parameters']);watts=math.ceil(energy.get('power_kw',self.assets[aid]['parameters']['power_kw'])*1000-1e-8)
        loads=self.slots(aid,release,deadline-duration);unloads=self.slots(aid,release+duration+10,deadline)
        machine=[(day['base_min']+a,day['base_min']+z) for day in self.days.values() for a,z in policy['machine_windows_min']]
        pref=next((d for d in self.portrait.get('joint_sampling',{}).get('devices',[]) if d['asset_id']==aid),{})
        coords=pref.get('coordinates',{});mw=1+round(9*coords.get('routine_stability',.5));hw=1+round(9*coords.get('manual_burden',.5))
        target=self.targets.get((aid,j['date'],nid),self.targets.get((aid,j['date'],None),j['preferred_start_min']))
        best=None
        for start in range(release+10,deadline-duration,10):
            if not contained(start,start+duration,machine):continue
            ls=[s for s in loads if s[0]+10<=start and start-s[0]-10<=policy['maximum_preload_wait_min']]
            us=[s for s in unloads if s[0]>=start+duration and s[0]-start-duration<=policy['maximum_retrieval_wait_min']]
            if not ls or not us:continue
            lt=max(s[0] for s in ls);ut=min(s[0] for s in us)
            l=min((s for s in ls if s[0]==lt),key=lambda s:digest([self.rules['seed'],nid,'load',s[1]]))
            u=min((s for s in us if s[0]==ut),key=lambda s:digest([self.rules['seed'],nid,'unload',s[1]]))
            if not policy['timer_allowed'] and l[0]+10!=start:continue
            if any(max(l[0],a)<min(u[0]+10,z) for a,z in self.asset_holds[aid]):continue
            if self.supply_W and any(self.known_power_W[t]+watts>self.supply_W+1e-6 for t in range(start,start+duration,10)):continue
            candidate=(mw*abs(start-target)+hw*(start-l[0]-10+u[0]-start-duration),start,l,u)
            if best is None or candidate<best:best=candidate
        if best is None:return dict(need_id=nid,status='unserved',reason='GREEDY_NO_COMPLETE_SLOT;not_infeasibility_proof')
        _,start,l,u=best;self.reserve(aid,nid,'load',l);self.reserve(aid,nid,'unload',u)
        self.tasks.append(dict(task_id=nid,need_id=nid,asset_id=aid,kind=j['kind'],start_min=start,end_min=start+duration,**energy,
            **({'depends_on_need_id':parent} if parent else {})))
        self.asset_holds[aid].append((l[0],u[0]+10))
        for t in range(start,start+duration,10):self.known_power_W[t]+=watts
        return dict(need_id=nid,status='scheduled')


def run(out):
    out=Path(out);records=[]
    roster=read(out/'fresh-public/INPUTS.json')['records'];profiles={r['household_id']:r['portrait_path'] for r in roster}
    for hid,pp in sorted(profiles.items()):
        p=read(out/'fresh-public/source'/hid/'PARALLEL_PROBLEM.json.gz');portrait=read(pp);before=digest(p)
        for seed in [20261022]+list(range(8)):
            start=time.perf_counter();s=Serial(p,portrait,seed);ledger=[]
            pending=sorted(p['jobs'],key=lambda j:(j['release_min'],j['need_id']));done=set()
            while pending:
                at=next((i for i,j in enumerate(pending) if not j.get('depends_on_need_id') or j['depends_on_need_id'] in done),None)
                if at is None:raise ValueError('DEPENDENCY_CYCLE_IN_COMPILED_JOBS')
                j=pending.pop(at);ledger.append(s.program(j));done.add(j['need_id'])
            A=dict(tasks=s.tasks,operations=s.operations,controls=p['controls'])
            check=inspect(p,A,s.steps);cp=read(out/'fresh-public/A'/hid/(str(seed)+'.json.gz'))
            row=dict(household_id=hid,seed=seed,wall_seconds=time.perf_counter()-start,
                compiled_jobs_sha256=digest(p['jobs']),portrait_sha256=digest(portrait),
                greedy=check,greedy_score=a_score(p,A,portrait),CP_score=a_score(p,cp['A'],portrait),
                CP_optimal=cp['optimal'],CP_objective=cp['objective'],CP_bound=cp['best_bound'])
            save(out/'same-demand-greedy'/hid/(str(seed)+'.json.gz'),dict(A=A,service_ledger=ledger,EV_steps=s.steps,summary=row))
            records.append(row)
        if digest(p)!=before:raise ValueError('COMPARISON_MUTATED_INPUT')
    result=dict(records=records,runs=len(records),same_jobs_and_targets=True,
        greedy_fully_served=sum(r['greedy']['passed'] for r in records),CP_feasible=54,
        controlled_adapter='old serial scan rule with aligned windows,qualification,targets and job-local objective weights;not original byte replay',
        EV_difference='serial fixes original nominal charging first;CP jointly schedules charging and programs;method-level difference,not isolated solver-speed claim',
        raw_historical_comparator_retained='INDEPENDENT_A_CHECK.json;different compilation/horizon must not be interpreted as same-demand superiority',
        temporal_and_population_generalization_claimed=False)
    save(out/'A_SAME_DEMAND_COMPARISON.json',result);return {k:v for k,v in result.items() if k!='records'}


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--out',required=True);a=p.parse_args();print(run(a.out))
