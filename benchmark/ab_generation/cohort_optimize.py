"""Bounded joint reselection of residual same-role raw-cell country gaps."""
from pathlib import Path
from collections import Counter,defaultdict
import argparse,json
from ortools.sat.python import cp_model
from . import cohort_coverage as m

def state_from_ledger(root):
    return m.state_from_ledger(root)

def refine(root,native_source,deterministic_time=2.0):
    root=Path(root);state=state_from_ledger(root);initial,ledger=m.report(state)
    indices=set()
    for role,entries in ledger.items():
        for cell in entries:
            if cell['selected_goal_met']:continue
            missing=set(cell['witness_countries'])-set(cell['selected_countries'])
            indices.update(e['index'] for e in cell['examples'] if e['country'] in missing)
    # Existing extra witnesses may come from a later household than the three
    # retained raw examples. Include those exact witness households as well.
    for house in state['rows']:
        p=root/str(house['index']).zfill(4)/'COVERAGE_EXTRA_CANDIDATES.json.gz'
        if p.exists():indices.add(house['index'])
    logs=[];changed=set()
    for index in sorted(indices):
        house=next(h for h in state['rows'] if h['index']==index);role=house['role'];country=house['country']
        goals=[key for key,countries in state['raw'][role].items() if country in state['pool'][role].get(key,set()) and not state['chosen'][role][key][country] and m.country_count(state['chosen'][role][key])<min(2,len(countries))]
        if not goals:continue
        slots=[s for s in state['slots'].values() if s['index']==index];old_counts=Counter(k for s in slots for k in s['row']['raw_root_cells'])
        protected=[key for key,count in old_counts.items() if state['chosen'][role][key][country]==count and m.country_count(state['chosen'][role][key])<=min(2,len(state['raw'][role][key]))]
        by_key={}
        for day in m.catalogues_with_extras(root/str(index).zfill(4)):
            old=next(s['row']['id'] for s in slots if s['row']['date']==day['date'])
            for row in day['rows']:
                key=(row['date'],tuple(row['raw_root_cells']),tuple(sorted(m.simple_tokens(row))))
                if key not in by_key or row['id']==old or by_key[key]['id']!=old and row['id']<by_key[key]['id']:by_key[key]=row
        candidates=list(by_key.values());model=cp_model.CpModel();x=[model.new_bool_var('r'+str(j)) for j in range(len(candidates))]
        for slot in slots:model.add(sum(x[j] for j,row in enumerate(candidates) if row['date']==slot['row']['date'])==1)
        for token in sorted(state['required'][index]):model.add(sum(x[j] for j,row in enumerate(candidates) if token in m.simple_tokens(row))>=1)
        for key in protected:model.add(sum(x[j] for j,row in enumerate(candidates) if key in row['raw_root_cells'])>=1)
        hits=[]
        for k,key in enumerate(goals):
            hit=model.new_bool_var('hit'+str(k));covered=[x[j] for j,row in enumerate(candidates) if key in row['raw_root_cells']]
            model.add_max_equality(hit,covered or [0]);hits.append(hit)
        model.maximize(sum(hits));solver=cp_model.CpSolver();solver.parameters.num_search_workers=1;solver.parameters.random_seed=20261022;solver.parameters.max_deterministic_time=deterministic_time
        status=solver.solve(model);gain=int(round(solver.objective_value)) if status in (cp_model.FEASIBLE,cp_model.OPTIMAL) else 0
        record=dict(index=index,active_candidates=len(candidates),goals=len(goals),new_country_hits=gain,status=solver.status_name(status),optimal=status==cp_model.OPTIMAL)
        if gain:
            model.add(sum(hits)==gain)
            old_ids={s['row']['id'] for s in slots};model.minimize(sum(x[j] for j,row in enumerate(candidates) if row['id'] not in old_ids))
            first=[row for j,row in enumerate(candidates) if solver.value(x[j])]
            second=solver.solve(model);selected=[row for j,row in enumerate(candidates) if solver.value(x[j])] if second in (cp_model.FEASIBLE,cp_model.OPTIMAL) else first
            before={key:min(min(2,len(countries)),m.country_count(state['chosen'][role][key])) for key,countries in state['raw'][role].items()}
            for slot in slots:
                new=next(row for row in selected if row['date']==slot['row']['date'])
                if new['id']!=slot['row']['id']:changed.add((index,new['date']));m.adopt(state,slot,new)
            if any(state['base_counts'][index][token]<=0 for token in state['required'][index]):raise ValueError('HOUSEHOLD_BASE_COVERAGE_LOST')
            if any(min(min(2,len(countries)),m.country_count(state['chosen'][role][key]))<before[key] for key,countries in state['raw'][role].items()):raise ValueError('GLOBAL_ATTAINED_COUNTRY_GOAL_LOST')
        logs.append(record);print(json.dumps(record),flush=True)
    # Reuse the same source audit, fresh native replay and previous-pair archive.
    result=m.review(root,True,native_source,state=state,passes=0)
    result.update(initial=initial,reselected_slots=len(changed),optimizer='bounded household CP-SAT joint reselection',optimizer_log=logs,global_optimality_claimed=False)
    (root/'COHORT_COVERAGE_REVIEW.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n')
    (root/'COHORT_CP_REVIEW.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n')
    return result

def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--batch',required=True,type=Path);parser.add_argument('--native-source',required=True);parser.add_argument('--deterministic-time',type=float,default=2)
    args=parser.parse_args()
    if args.deterministic_time<=0:parser.error('deterministic time must be positive')
    answer=refine(args.batch,args.native_source,args.deterministic_time)
    print(json.dumps({k:v for k,v in answer.items() if k not in {'selection_history','optimizer_log','initial'}}))
if __name__=='__main__':main()
