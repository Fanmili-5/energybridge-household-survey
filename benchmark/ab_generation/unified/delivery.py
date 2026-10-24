"""Predeclared, local-only validation driver; never simulation or deployment."""
import argparse
import copy
import datetime as dt
import itertools
import time
import resource
from collections import Counter,defaultdict
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path
from ..common import read,save,digest,sha,seal
from ..model import apply
from .contract import config,code_hash
from .pipeline import _job,build,fresh_context
from .opportunities import coverage
from .selection import assign,concepts
from .validation import coverage_report,walkthrough,immutable


def metrics(result):
    statuses=Counter(r['status'] for r in result.get('coverage',{}).get('coverage',[]))
    diag=result.get('engineering_diagnostics',[])
    return dict(status=result['status'],rows=len(result.get('rows',[])),
        raw_requests=result.get('raw_requests',0),materializations=result.get('materialized_requests',0),
        oracle_calls=result.get('oracle_calls',0),interaction_counts=dict(statuses),
        mechanism_opportunities={k:result.get('independent_opportunity_coverage',{}).get(k) for k in ('potential','witnessed')},
        engineering_diagnostic_records=len(diag),
        engineering_excluded_request_count=sum(r.get('request_count',1) if isinstance(r,dict) else 1 for r in diag),
        independent_errors=len(result.get('independent_engineering_errors',[])),telemetry=result.get('telemetry',{}),
        physical_runs=0)


def comparison_job(task):
    record,cfg,arm,path=task;start=time.perf_counter();result=_job((record,config(cfg)))
    result['comparison']=dict(arm=arm,configuration=config(cfg),input_record=record,
        wall_seconds=time.perf_counter()-start,outcome_or_acceptance_used=False)
    save(path,result)
    return dict(arm=arm,seed=cfg['seed'],household_id=record['household_id'],date=record['date'],
                path=str(path),**metrics(result))


def comparisons(out,workers=6):
    out=Path(out);protocol=read(out/'PROTOCOL.json');base=protocol['base_config'];jobs=[]
    for seed in protocol['seeds']:
        for record in protocol['comparison_records']:
            arms=[('ipog_base',{}),('round_robin',{'search_strategy':'legacy_round_robin_adapter'}),
                  ('budget_half',{'rows_per_unit':8}),('budget_double',{'rows_per_unit':32}),
                  ('encoding_half',{'oracle_native_encoding_budget':128}),('encoding_double',{'oracle_native_encoding_budget':512})]
            for arm,change in arms:
                cfg={**base,'seed':seed,**change};key=digest([record,cfg,arm])[:24]
                jobs.append((record,cfg,arm,out/'comparisons/catalogues'/(key+'.json.gz')))
    summaries=[]
    with ProcessPoolExecutor(max_workers=workers) as pool:
        for summary in pool.map(comparison_job,jobs,buffersize=workers*2):
            summaries.append(summary);save(out/'comparisons/PROGRESS.json',summaries)
            print('comparison',len(summaries),'/',len(jobs),summary['arm'],flush=True)
    save(out/'comparisons/RESULTS.json',summaries)
    return dict(runs=len(summaries),all_prespecified_seeds_retained=True,
                independent_errors=sum(r['independent_errors'] for r in summaries))


def a_score(problem,result,portrait):
    from .a_solver import dated_targets
    targets=dated_targets(portrait,problem['anchor']);tasks={t['need_id']:t for t in (result or {}).get('tasks',[])}
    deviations=[];missing=[]
    for j in problem['jobs']:
        t=tasks.get(j['need_id']);target=targets.get((j['asset_id'],j['date'],j['need_id']),targets.get((j['asset_id'],j['date'],None),j['preferred_start_min']))
        if t is None:missing.append(j['need_id'])
        else:deviations.append(abs(t['start_min']-target))
    return dict(compiled_jobs=len(problem['jobs']),exact_identity_matched_jobs=len(deviations),
        missing_or_changed_demand_ids=missing,absolute_machine_target_deviation_min=sum(deviations),
        matching='exact need_id;unmatched demands retained;no nearest successful matching',
        behavior_validity_inferred=False)


def fresh_public(out,old):
    from .a_solver import compile_life,solve
    out,old=Path(out),Path(old);records=read(old/'public-inputs-v6/INPUTS.json')['records'];groups=defaultdict(list)
    for r in records:groups[r['household_id']].append(r)
    a_rows=[];inputs=[];base=read(out/'PROTOCOL.json')['base_config'];source_pins={}
    for hid,rs in sorted(groups.items()):
        root=old/'public-A-source/connected/life_inputs'/hid
        original=read(root/'LIFE_INPUT.json')['households'][0];world=read(root/'resource_worlds.json')['households'][0]
        portrait=read(rs[0]['portrait_path']);dates=sorted(r['date'] for r in rs)
        spec=copy.deepcopy(original)
        # Keep original calendars; explicitly bound the research horizon and
        # include next-day resources. This is not a new lifestyle or B-driven date.
        spec['end_exclusive']=(dt.date.fromisoformat(dates[-1])+dt.timedelta(days=3)).isoformat()
        if spec['end_exclusive']>original['end_exclusive']:raise ValueError('SOURCE_LOOKAHEAD_MISSING')
        problem=compile_life(spec,world)
        problem['jobs']=[j for j in problem['jobs'] if j['date'] in dates]
        problem['validation_horizon']='ten original dates;two original-calendar lookahead days;no extra program demands'
        save(out/'fresh-public/source'/hid/'PROBLEM.json.gz',problem)
        source_pins[str(root/'LIFE_INPUT.json')]=sha(root/'LIFE_INPUT.json');source_pins[str(root/'resource_worlds.json')]=sha(root/'resource_worlds.json')
        for seed in [20261022]+list(range(8)):
            start=time.perf_counter();a=solve(problem,portrait,seed=seed,deterministic_time=20)
            path=out/'fresh-public/A'/hid/(str(seed)+'.json.gz');save(path,a)
            a_rows.append(dict(household_id=hid,seed=seed,status=a['status'],path=str(path),
                cp=a_score(problem,a.get('A'),portrait),legacy=a_score(problem,problem['legacy_comparator']['A'],portrait),
                wall_seconds=time.perf_counter()-start,optimal=a.get('optimal'),
                objective=a.get('objective'),best_bound=a.get('best_bound'),input_lineage=problem['input_lineage']))
            if seed==20261022:
                if a['status']!='feasible':continue
                for date in dates:
                    c=fresh_context(problem,a,date,portrait,config(base));p=out/'fresh-public/contexts'/(hid+'__'+date+'.json.gz');save(p,c)
                    inputs.append(dict(household_id=hid,date=date,context_path=str(p.resolve()),portrait_path=rs[0]['portrait_path']))
        save(out/'fresh-public/A_COMPARISON.json',a_rows)
    save(out/'fresh-public/SOURCE_PINS.json',source_pins)
    save(out/'fresh-public/INPUTS.json',dict(schema='eb.unified.inputs.v1',mode='fresh_generation',records=inputs))
    report=build(out/'fresh-public/INPUTS.json',out/'fresh-public/collection',base,workers=6) if inputs else dict(status='no_feasible_A;not_resampled')
    return dict(A_runs=len(a_rows),feasible=sum(r['status']=='feasible' for r in a_rows),collection=report)


def review(root):
    root=Path(root);selected=set(read(root/'SELECTION.json')['selected_ids']);rows=[];all_candidates=[];exposure=Counter();unknowns=Counter()
    for slot in read(root/'GENERATION.json'):
        catalogue=read(root/slot['path']);ledger=catalogue.get('input_opportunities')
        if ledger is None:raise ValueError('INPUT_SIDE_LEDGER_MISSING')
        r=coverage(ledger,catalogue,selected);r.update(household_id=slot['household_id'],date=slot['date'])
        rows.append(r);all_candidates.extend(catalogue.get('rows',[]))
        for e in r['mechanisms']:
            if e['status']=='potential':exposure[(e['family'],'potential')]+=1
            if e['status']=='potential' and e['candidate_witness_ids']:exposure[(e['family'],'candidate')]+=1
            if e['status']=='potential' and e['selected_witness_ids']:exposure[(e['family'],'selected')]+=1
            if e['status']=='potential' and e['gap']:unknowns[e['gap']]+=1
    save(root/'INPUT_OPPORTUNITY_COVERAGE.json.gz',rows)
    chosen=[r for r in all_candidates if r['id'] in selected]
    stats=dict(potential=sum(r['potential'] for r in rows),witnessed=sum(r['witnessed'] for r in rows),selected=sum(r['selected'] for r in rows),
        gaps=dict(unknowns),family_exposure={f:{k:exposure[(f,k)] for k in ('potential','candidate','selected')} for f in sorted({f for f,k in exposure})},
        selected_joint_order=dict(Counter(r['independent_units'] for r in chosen)),
        raw_action_duplicates=len(chosen)-len({(r['household_id'],digest(r['patches'])) for r in chosen}),
        semantic_repeat_excess=sum(max(0,n-1) for n in Counter((r['household_id'],concepts(r)['signature']) for r in chosen).values()),
        diagnostics_are_not_formal_error_rate=True,
        coverage_gate='unresolved_mechanisms;not_full_coverage' if unknowns else 'all_input_mechanisms_have_witness_or_exclusion',
        physics='not_computed;not_counted_as_observed_failure')
    save(root/'OPPORTUNITY_SUMMARY.json',stats);return stats


def selection_study(root,out):
    root,out=Path(root),Path(out);rows=[]
    for s in read(root/'GENERATION.json'):rows.extend(read(root/s['path']).get('rows',[]))
    base=read(root/'PRE_GENERATION.json')['configuration'];summaries=[]
    def measure(name,selected,extra=None):
        chosen=[r for r in rows if r['id'] in set(selected)];views=[concepts(r) for r in chosen]
        return dict(arm=name,selected=len(chosen),selected_ids=selected,
            token_coverage=len(set().union(*(v['tokens'] for v in views))),
            semantic_repeat_excess=sum(max(0,n-1) for n in Counter((r['household_id'],v['signature']) for r,v in zip(chosen,views)).values()),
            family_exposure=dict(Counter(f for v in views for f in v['families'])),
            joint_orders=dict(Counter(r['independent_units'] for r in chosen)),extra=extra)
    groups=defaultdict(list)
    for r in rows:groups[(r['household_id'],r['date'])].append(r)
    for seed in range(8):
        ids=[min(rs,key=lambda r:digest([seed,'uniform',r['id']]))['id'] for rs in groups.values()]
        summaries.append(measure('uniform_seed_'+str(seed),ids))
    # Exact prior selector on the same complete candidate catalogue. Its own
    # coarse-cell compression is retained and explicitly reported.
    from ..collection_assignment import assign as original_assign
    prior=original_assign(rows,dict(seed=base['seed'],solver_node_limit=200,assignment_representatives_per_cell=2))
    save(out/'PRIOR_SELECTOR.json',prior);summaries.append(measure('prior_v4',prior['selected_ids']))
    current=read(root/'SELECTION.json');summaries.append(measure('current',current['selected_ids'],current['blocks'][0]['solver']))
    for multiplier in (0,.5,2):
        cfg={**base,**{k:base[k]*multiplier for k in ('repeat_context','repeat_family','repeat_composition')}}
        r=assign(rows,cfg);save(out/('REPEAT_'+str(multiplier)+'.json'),r);summaries.append(measure('repeat_'+str(multiplier),r['selected_ids']))
    for block in (10,25):
        r=assign(rows,{**base,'block_households':block});save(out/('BLOCK_'+str(block)+'.json'),r);summaries.append(measure('block_'+str(block),r['selected_ids']))
    # Input order and nested descriptive field changes must not add votes.
    original_views={r['id']:concepts(r) for r in rows};changed=copy.deepcopy(rows)
    for r in changed:
        for c in r['components']:c['magnitude']['descriptive_extra_axes']=['not_a_target']*10
        r['service_context']=[{'kind':'unrelated','release_min':999999,'quantity':999999}]
    invariant=all(original_views[r['id']]==concepts(r) for r in changed)
    order=assign(list(reversed(rows)),base)
    save(out/'INVARIANCE.json',dict(nested_description_invariant=invariant,input_order_selected_ids_invariant=set(order['selected_ids'])==set(current['selected_ids']),
        population_exposure_equality_required=False))
    save(out/'RESULTS.json',summaries);return dict(arms=len(summaries),nested_description_invariant=invariant)


def main():
    p=argparse.ArgumentParser();p.add_argument('--out',required=True);p.add_argument('--prior',required=True)
    p.add_argument('--stage',choices=['preflight','fresh','comparisons','fifty','review','selection'],required=True);p.add_argument('--workers',type=int,default=6)
    a=p.parse_args();out,old=Path(a.out),Path(a.prior)
    if a.stage=='preflight':
        p=read(out/'PROTOCOL.json');rs=[]
        for r in p['comparison_records']:
            if r['household_id'] not in [x['household_id'] for x in rs]:rs.append(r)
        jobs=[(r,{**p['base_config'],'rows_per_unit':4},'preflight',out/'preflight-v2'/(r['household_id']+'.json.gz')) for r in rs]
        with ProcessPoolExecutor(max_workers=a.workers) as pool:result=list(pool.map(comparison_job,jobs))
    elif a.stage=='fresh':result=fresh_public(out,old)
    elif a.stage=='comparisons':result=comparisons(out,a.workers)
    elif a.stage=='fifty':result=build(old/'inputs/fifty.json',out/'fifty',read(out/'PROTOCOL.json')['base_config'],a.workers)
    elif a.stage=='selection':result=selection_study(out/'fifty',out/'selection-study')
    else:
        result={}
        for root in [out/'fifty',out/'fresh-public/collection']:
            if root.exists():result[root.name]=dict(opportunities=review(root),raw_grid=coverage_report(root),walkthrough=walkthrough(root,root/'TWO_HOUSE_TEN_DAY.md'))
        result['protected']=immutable(out/'PROTECTED_BASELINE.json',out/'IMMUTABILITY.json')
    save(out/('STAGE_'+a.stage+'.json'),result);print(result,flush=True)


if __name__=='__main__':main()
