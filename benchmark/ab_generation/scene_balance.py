"""Matched external-event controls without changing covered request categories."""
import argparse,json,copy
from pathlib import Path
from collections import Counter,defaultdict
from concurrent.futures import ProcessPoolExecutor
from .scene_coverage import CompletionContext,scene_context,root_catalogue,qualified,request,record_raw_cells
from .cohort_coverage import load,write_gzip,simple_tokens
from .generate_cohort import save
from .common import digest

_WORK=None

def init(batch,households,native,allocation,quotas,out,max_changes):
    global _WORK
    ctx=CompletionContext(batch,households,native)
    selected={(d['index'],d['row']['date']):d for d in load(allocation)}
    _WORK=(ctx,selected,quotas,Path(out),max_changes)

def balance_group(group):
    from ortools.sat.python import cp_model
    ctx,selected,quotas,out,max_changes=_WORK
    country,role=group
    houses=[h for h in ctx.status if h['country']==country and h['role']==role]
    used=Counter();present=Counter();slots=[];current_cells=Counter()
    for h in houses:
        for path in sorted((ctx.root/f"{h['index']:04}").glob('*_PAIR.json.gz')):
            if 'INITIAL' in path.name:continue
            pair=load(path);old=pair['selected_proposal'];slot=(h['index'],pair['date'])
            now=selected.get(slot,{}).get('row',old)
            current_cells.update(now['raw_root_cells'])
            if now['id']!=old['id']:used[h['index']]+=1
            if now.get('scene_event'):present[now['scene_event']['start_min']]+=1
            if now['id']==old['id'] and len(old['components'])==1 and old['components'][0]['family']=='ac':
                slots.append(dict(index=h['index'],date=pair['date'],row=old))
    candidates=[];attempts=0;by_slot=defaultdict(list);by_event=defaultdict(list);by_house=defaultdict(list)
    for slot in sorted(slots,key=lambda s:(s['index'],s['date'])):
        if used[slot['index']]>=max_changes:continue
        old=slot['row'];wanted=set(old['raw_root_cells'])
        for start,want in sorted(quotas.items()):
            if present[start]>=want:continue
            base,bound,c,cfg=scene_context(ctx,slot['index'],slot['date'],start)
            g,raw=root_catalogue(c,cfg)
            cells=sorted((v for v in raw if v['family']=='ac' and v['admissible_raw_alternatives']),
                         key=lambda v:(v['key'] not in wanted,v['key']))
            found_keys=set()
            for cell in cells:
                f=cell['factor'];desc=next(d for d in g['descriptors'][f] if d['label']==cell['label'])
                found=None
                for j in desc['ids']:
                    attempts+=1;r=request(c,[g['values'][f][j]],cfg,None)
                    if not qualified(r):continue
                    record_raw_cells(dict(factors=g['descriptors'],native_domains=g['values'],rows=[r]))
                    if simple_tokens(r)==simple_tokens(old):found=r;break
                if found is None:continue
                found.update(scene_event=cfg['event'],scene_id=digest([ctx.pre['source_sha256'],slot['index'],slot['date'],cfg['event']]),
                    scene_policy='evening_scene_grid_v1',scene_purpose='matched_event_clock_control',
                    matched_original_proposal_id=old['id'])
                j=len(candidates);candidates.append((slot,start,found))
                by_slot[(slot['index'],slot['date'])].append(j);by_event[start].append(j);by_house[slot['index']].append(j)
                found_keys.update(found['raw_root_cells'])
                # Keep an exact raw-cell match when available; otherwise retain
                # bounded diverse alternatives for a joint protected-cell solve.
                if set(found['raw_root_cells'])==wanted or len(found_keys)>=3:break
    model=cp_model.CpModel();x=[model.new_bool_var('control_'+str(j)) for j in range(len(candidates))]
    for key,js in sorted(by_slot.items()):model.add(sum(x[j] for j in js)<=1)
    for start,want in sorted(quotas.items()):model.add(sum(x[j] for j in by_event[start])==want-present[start])
    for index,js in sorted(by_house.items()):model.add(sum(x[j] for j in js)<=max_changes-used[index])
    for cell,n in sorted(current_cells.items()):
        delta=[x[j]*((cell in r['raw_root_cells'])-(cell in slot['row']['raw_root_cells']))
               for j,(slot,start,r) in enumerate(candidates)
               if (cell in r['raw_root_cells'])!=(cell in slot['row']['raw_root_cells'])]
        if delta:model.add(n+sum(delta)>=1)
    changed_cells=[x[j] for j,(slot,start,r) in enumerate(candidates)
                   if set(r['raw_root_cells'])!=set(slot['row']['raw_root_cells'])]
    # Strictly prioritize preserving existing cell assignments, then a fixed tie.
    big=1+len(candidates)*1000
    model.minimize(big*sum(changed_cells)+sum(x[j]*(int(digest([ctx.cfg['seed'],'control-tie',r['id']])[:8],16)%1000)
                                                for j,(slot,start,r) in enumerate(candidates)))
    solver=cp_model.CpSolver();solver.parameters.num_search_workers=1;solver.parameters.random_seed=ctx.cfg['seed']
    solver.parameters.max_deterministic_time=10
    status=solver.solve(model)
    if status not in (cp_model.FEASIBLE,cp_model.OPTIMAL):
        save(out/(country+'_'+role+'_FAILURE.json'),dict(status=solver.status_name(status),candidates=len(candidates),
            available_per_event={k:len(v) for k,v in by_event.items()},required={k:v-present[k] for k,v in quotas.items()}))
        raise ValueError(f'EVENT_BALANCE_UNRESOLVED:{country}:{role}:{solver.status_name(status)}')
    results=[];changed=0
    for j,(slot,start,r) in enumerate(candidates):
        if not solver.value(x[j]):continue
        results.append(dict(index=slot['index'],country=country,role=role,row=r));present[start]+=1
        changed+=set(r['raw_root_cells'])!=set(slot['row']['raw_root_cells'])
    result=dict(country=country,role=role,added=len(results),event_counts=dict(present),literal_trials=attempts,
        candidate_edges=len(candidates),solver_status=solver.status_name(status),optimal=status==cp_model.OPTIMAL,
        existing_raw_country_coverage_and_basic_tokens_preserved=True,raw_cell_assignment_changes=changed,rows=results)
    write_gzip(out/(country+'_'+role+'.json.gz'),result)
    return {k:v for k,v in result.items() if k!='rows'}

def balance(batch,households,native,discovered,workers=8,max_changes=4):
    root=Path(discovered);allocation=root/'ALLOCATION.json.gz'
    if load(root/'ALLOCATION_RESULT.json')['status'] not in ('FEASIBLE','OPTIMAL'):raise ValueError('NO_FEASIBLE_CORE_ALLOCATION')
    selected=load(allocation);counts=Counter()
    for d in selected:
        if d['row'].get('scene_event'):counts[(d['country'],d['role'],d['row']['scene_event']['start_min'])]+=1
    quotas={s:max(v for (c,r,t),v in counts.items() if t==s) for _,_,s in counts}
    out=root/'balanced_controls';out.mkdir(exist_ok=False)
    ctx=CompletionContext(batch,households,native);groups=sorted({(h['country'],h['role']) for h in ctx.status})
    save(root/'BALANCE_PRE_RUN.json',dict(schema='eb.matched_event_clock_panel.v1',quotas_per_country_role=quotas,
        groups=groups,policy='same count for every declared country-role stratum at each supplemental event time',
        no_observed_event_frequency_claim=True,max_changed_per_household=max_changes))
    logs=[]
    with ProcessPoolExecutor(max_workers=workers,initializer=init,
            initargs=(batch,households,native,allocation,quotas,out,max_changes)) as pool:
        for record in pool.map(balance_group,groups):
            logs.append(record);print(json.dumps(dict(stage='matched_event_controls',done=len(logs),total=len(groups),added=sum(d['added'] for d in logs))),flush=True)
    combined={(d['index'],d['row']['date']):d for d in selected}
    for p in sorted(out.glob('*.json.gz')):
        for d in load(p)['rows']:
            key=(d['index'],d['row']['date'])
            if key in combined and combined[key]['row'].get('scene_event'):raise ValueError('BALANCE_REPLACED_CORE_SCENE')
            combined[key]=d
    write_gzip(root/'ALLOCATION_BALANCED.json.gz',[combined[k] for k in sorted(combined)])
    final=dict(schema='eb.matched_event_clock_panel.v1',status='passed',added_controls=sum(d['added'] for d in logs),
        supplemental_event_questions=len(groups)*sum(quotas.values()),quotas_per_country_role=quotas,groups=logs,
        household_source_and_A_unchanged=True,old_raw_country_coverage_and_basic_tokens_preserved=True)
    ctx.verify_source();save(root/'BALANCE_RESULT.json',final);return final

def main():
    p=argparse.ArgumentParser(description=__doc__)
    for n in ('batch','households','native-source','discovered'):p.add_argument('--'+n,required=True,type=Path)
    p.add_argument('--workers',type=int,default=8);p.add_argument('--max-changes',type=int,default=4)
    a=p.parse_args()
    if not 1<=a.workers<=8:p.error('workers must be1..8')
    result=balance(a.batch,a.households,a.native_source,a.discovered,a.workers,a.max_changes)
    print(json.dumps({k:v for k,v in result.items() if k!='groups'}),flush=True)
if __name__=='__main__':main()
