"""Versioned independent re-declaration, with unchanged candidate evidence.

No candidate is regenerated, added, removed or reselected. Input mechanisms,
derived semantic cells and literal numeric commands have separate ledgers.
"""
import argparse
import csv
import gzip
import json
from collections import Counter
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path
from benchmark.ab_generation.common import read,save,digest,sha
from benchmark.ab_generation.unified.opportunities import declare,coverage,RULES
from benchmark.ab_generation.unified.selection import concepts
from benchmark.ab_generation.unified.contract import code_hash
from .coverage_layers import analyse


def record_sources(collection):
    pre=read(collection/'PRE_GENERATION.json')
    for path in pre['source_sha256']:
        p=Path(path)
        if p.suffix!='.json':continue
        d=read(p)
        if isinstance(d,dict) and d.get('schema')=='eb.unified.inputs.v1':
            rows={}
            for r in d['records']:
                if (r['household_id'],r['date']) in rows:raise ValueError('DUPLICATE_INPUT_DATE_IN_FROZEN_MANIFEST')
                cp=Path(r['context_path']);cp=cp if cp.is_absolute() else p.parent/cp
                rows[(r['household_id'],r['date'])]=cp
            return pre,rows
    raise ValueError('FROZEN_INPUT_MANIFEST_NOT_FOUND')


def date_accounting(contexts,slots):
    actual=Counter((s['household_id'],s['date']) for s in slots)
    return dict(expected=len(contexts),actual=len(slots),
        missing=[list(k) for k in sorted(contexts.keys()-actual.keys())],
        unexpected=[list(k) for k in sorted(actual.keys()-contexts.keys())],
        duplicate_dates=[list(k) for k,n in sorted(actual.items()) if n>1],
        passed=set(actual)==set(contexts) and all(n==1 for n in actual.values()))


def job(task):
    slot,path,context,selected,cfg=task;cat=read(path);c=read(context)
    if (cat.get('household_id'),cat.get('date'))!=(slot['household_id'],slot['date']):
        raise ValueError('AUDIT_CATALOGUE_DATE_IDENTITY_MISMATCH')
    if any((r['household_id'],r['date'])!=(slot['household_id'],slot['date']) for r in cat.get('rows',[])):
        raise ValueError('AUDIT_CANDIDATE_DATE_IDENTITY_MISMATCH')
    layers=analyse(cat,c,selected)
    ledger=declare(c,cfg);oc=coverage(ledger,cat,selected)
    old=cat.get('input_opportunities',{}).get('entries',[]);a={e['key']:e for e in old};b={e['key']:e for e in ledger['entries']}
    changes=[]
    for k in sorted(a.keys()|b.keys()):
        before=a.get(k);after=b.get(k)
        fields=('family','need_id','mechanism','axis','status','reason')
        if before and after and all(before.get(x)==after.get(x) for x in fields):continue
        changes.append(dict(household_id=slot['household_id'],date=slot['date'],key=k,
            before={x:before.get(x) for x in fields} if before else None,
            after={x:after.get(x) for x in fields} if after else None))
    chosen=[r for r in cat.get('rows',[]) if r['id'] in selected];assignments=[]
    for r in chosen:
        ids=set(r['component_ids']);cells=[]
        for vs,ds in zip(cat.get('native_domains',[]),cat.get('factors',[])):
            index=next((i for i,v in enumerate(vs) if v and v['id'] in ids),0)
            cells.append(next(i for i,d in enumerate(ds) if index in d['ids']))
        assignments.append(cells)
    raw=[];counts=Counter()
    for t in cat.get('coverage',{}).get('coverage',[]):
        hit=any(all(x[i]==v for i,v in t['target']) for x in assignments)
        if hit and t['status']!='feasible':raise ValueError('SELECTED_TARGET_HAS_NO_FEASIBLE_WITNESS')
        counts.update([t['status'],'selected' if hit else 'not_selected'])
        raw.append(dict(household_id=slot['household_id'],date=slot['date'],target=t['target'],status=t['status'],selected=hit,
            gap=None if hit else 'declared_grammar_infeasible' if t['status']=='infeasible' else 'ten_slot_selection_tradeoff' if t['status']=='feasible' else 'search_or_evidence_unresolved'))
    checks=dict(**{k:slot.get(k) for k in ('household_id','date','status','eligible','native','raw','interaction_targets','witnessed','independent_engineering_errors')},
        selected=len(chosen),engineering_diagnostic_records=len(cat.get('engineering_diagnostics',[])),
        engineering_excluded_requests_including_duplicates=sum(e.get('request_count',1) for e in cat.get('engineering_diagnostics',[]) if isinstance(e,dict)),
        candidate_source_sha256=sha(path),input_context_sha256=sha(context),physical_status='not_computed')
    selected_metrics=[]
    for r in chosen:
        view=concepts(r,cfg.get('selection_joint_order','legacy_buckets_v1'));selected_metrics.append(dict(household_id=r['household_id'],date=r['date'],id=r['id'],
            semantic_signature=view['signature'],action_sha256=view['action'],joint_order=r['independent_units'],
            family_exposure=view['families'],life_issues=r['issues'],soft_tension=any(j['soft_preference_tension'] for j in r['judgment_context']),
            member_disagreement=any(j.get('member_opinions_differ') for j in r['judgment_context']),nominal_event_delta_kWh=r['known_event_reduction_kWh'],
            thermal_unknown=r['unknown_thermal_response'],human_fields_empty=all(r[k] is None for k in ('human_acceptance','human_score','human_reason')),
            actual_outcome_empty=r['actual_outcomes'] is None))
    return dict(opportunities=dict(household_id=slot['household_id'],date=slot['date'],**oc),crosswalk=changes,
        checks=checks,raw=raw,counts=dict(counts),selected=selected_metrics,
        candidate_ids=[r['id'] for r in cat.get('rows',[])],
        layers=layers,
        old_potential=sum(e['status']=='potential' for e in old),new_potential=oc['potential'])


def run(out,collection,label,workers=4):
    out,collection=Path(out).resolve(),Path(collection).resolve();pre,contexts=record_sources(collection)
    out.mkdir(parents=True,exist_ok=True)
    if (out/(label+'_AUDIT_PROTOCOL.json')).exists():raise ValueError('AUDIT_LABEL_ALREADY_EXISTS;PRESERVE_PREVIOUS_EVIDENCE')
    selected_ids=read(collection/'SELECTION.json')['selected_ids'];chosen=set(selected_ids)
    slots=read(collection/'GENERATION.json');tasks=[];accounting=date_accounting(contexts,slots)
    frozen_core=code_hash();pins=dict(pre['source_sha256'])
    for name in ('PRE_GENERATION.json','SELECTION.json','GENERATION.json','REPORT.json'):
        pins[str(collection/name)]=sha(collection/name)
    for slot in slots:
        path=(collection/slot['path']).resolve()
        if not path.is_relative_to(collection):raise ValueError('AUDIT_CATALOGUE_PATH_OUTSIDE_COLLECTION')
        pins[str(path)]=sha(path)
    for name in ('acceptance.py','coverage_layers.py','causal_audit.py'):
        p=Path(__file__).with_name(name);pins[str(p)]=sha(p)
    if any(sha(p)!=h for p,h in pins.items()):raise ValueError('FROZEN_AUDIT_INPUT_CHANGED')
    protocol=dict(collection=str(collection),original_generation_code_sha256=pre['code_sha256'],
        post_generation_mapping=pre.get('post_generation_mapping'),audit_code_sha256=frozen_core,
        source_pins=pins,date_accounting=accounting,selection_ids_unique=len(chosen)==len(selected_ids),
        candidates_regenerated=False,original_selection_changed=False,physical_runs=0)
    save(out/(label+'_AUDIT_PROTOCOL.json'),protocol)
    if not accounting['passed'] or len(chosen)!=len(selected_ids):
        diagnostic=dict(status='invalid_date_or_selection_identity;not_accepted',date_accounting=accounting,
            duplicate_selected_ids=[k for k,n in Counter(selected_ids).items() if n>1])
        save(out/(label+'_ADMISSION_DIAGNOSTIC.json'),diagnostic)
        return diagnostic
    for s in slots:tasks.append((s,collection/s['path'],contexts[(s['household_id'],s['date'])],chosen,pre['configuration']))
    opportunities=[];changes=[];checks=[];selection=[];counts=Counter();old=new=0;layer_rows=[];candidate_ids=[]
    with gzip.open(out/(label+'_SEMANTIC_CELL_COVERAGE.jsonl.gz'),'wt') as stream,ProcessPoolExecutor(max_workers=workers) as pool:
        for i,r in enumerate(pool.map(job,tasks,buffersize=workers*2)):
            opportunities.append(r['opportunities']);changes+=r['crosswalk'];checks.append(r['checks']);selection+=r['selected']
            counts.update(r['counts']);old+=r['old_potential'];new+=r['new_potential']
            layer_rows.append(dict(household_id=slots[i]['household_id'],date=slots[i]['date'],**r['layers']))
            candidate_ids.extend(r['candidate_ids'])
            for row in r['raw']:stream.write(json.dumps(row,sort_keys=True,separators=(',',':'))+'\n')
            save(out/(label+'_REVIEW_PROGRESS.json'),dict(completed=i+1,expected=len(slots)))
    save(out/(label+'_INPUT_OPPORTUNITY_COVERAGE.json.gz'),opportunities)
    save(out/(label+'_DENOMINATOR_CROSSWALK.json.gz'),dict(changes=changes,old_potential=old,new_potential=new,
        ledger_rules_sha256=digest(RULES),scope='input-mechanism re-declaration;candidate and numeric domains unchanged by this audit',
        original_catalogue_code_sha256=pre['code_sha256'],candidate_selection_changed=False))
    potential=[e for d in opportunities for e in d['mechanisms'] if e['status']=='potential']
    gaps=Counter(e['gap'] for e in potential if e['gap']);family={}
    for f in sorted({e['family'] for e in potential}):
        es=[e for e in potential if e['family']==f]
        family[f]=dict(potential=len(es),candidate=sum(bool(e['candidate_witness_ids']) for e in es),selected=sum(bool(e['selected_witness_ids']) for e in es))
    for suffix,rs in [('SLOT_CHECK.csv',checks),('MECHANISM_COVERAGE.csv',[
        dict(household_id=d['household_id'],date=d['date'],**{k:e.get(k) for k in ('family','asset_id','need_id','mechanism','axis','status','reason','gap')},
            candidate_witnesses=len(e['candidate_witness_ids']),selected_witnesses=len(e['selected_witness_ids'])) for d in opportunities for e in d['mechanisms']])]:
        with (out/(label+'_'+suffix)).open('w',newline='') as f:
            w=csv.DictWriter(f,fieldnames=list(rs[0]));w.writeheader();w.writerows(rs)
    f,u,s=counts['feasible'],counts['unknown']+counts['unexplored'],counts['selected']
    raw=dict(targets=f+u+counts['infeasible'],counts=dict(counts),selected_coverage_bounds=dict(lower=s/(f+u) if f+u else None,upper=s/f if f else None,known_feasible=f,unknown=u,selected=s),
        layer='derived_semantic_cell_interactions',literal_numeric_grid=False,
        cell_definition='mechanism,branch,conditional_relative_position,handling_change,event_role',
        historical_raw_grid_label_was_inaccurate=True,population_representativeness_claimed=False)
    summary=dict(potential=new,witnessed=sum(bool(e['candidate_witness_ids']) for e in potential),selected=sum(bool(e['selected_witness_ids']) for e in potential),
        gaps=dict(gaps),family_exposure=family,selected_joint_order=dict(Counter(r['joint_order'] for r in selection)),
        semantic_repeat_excess=sum(n-1 for n in Counter((r['household_id'],r['semantic_signature']) for r in selection).values()),
        raw_action_duplicates=len(selection)-len({(r['household_id'],r['action_sha256']) for r in selection}),
        coverage_gate='unresolved_mechanisms;not_full_coverage' if gaps else 'input_mechanisms_closed;semantic_and_numeric_layers_separate',
        original_catalogue_code_sha256=pre['code_sha256'],corrected_ledger_rules_sha256=digest(RULES),
        input_mechanism_evidence_unknown=sum(e['status']=='unknown' for d in opportunities for e in d['mechanisms']),
        qualified_scope='potential mechanisms;not proof of joint feasibility or physical success')
    numeric_counts={}
    for item in layer_rows:
        for strength,values in item['numeric']['by_strength'].items():
            target=numeric_counts.setdefault(strength,Counter())
            target.update({k:values[k] for k in ('syntactic_upper_bound','known_feasible','selected','feasibility_unclassified')})
    numeric={}
    for strength,values in numeric_counts.items():
        size,f,s=(values[k] for k in ('syntactic_upper_bound','known_feasible','selected'))
        numeric[strength]=dict(values,selected_coverage_bounds=dict(lower=s/size if size else None,upper=s/f if f else None))
    all_checks=[d['all_candidate_checks'] for d in layer_rows]
    numerical_report=dict(by_strength=numeric,layer='literal_numeric_commands',
        exact_conditional_feasibility_denominator=False,infeasible_subtracted=0,
        all_candidate_cases=sum(d['cases'] for d in all_checks),all_candidate_components=sum(d['components'] for d in all_checks),
        independent_candidate_and_causal_pass=all(d['passed'] for d in all_checks),
        cases_with_errors=[r for d in all_checks for r in d['cases_with_errors']],
        denominator_scope='syntactic_upper_bound_including_no_change_and_support;not_proven_joint_opportunities',
        unknown_scope='unclassified remainder includes unexplored and possibly impossible combinations',
        full_grid_coverage_claimed=False)
    save(out/(label+'_COVERAGE_LAYERS.json.gz'),layer_rows)
    save(out/(label+'_NUMERIC_EXPLORATION.json'),numerical_report)
    save(out/(label+'_SELECTED_AUDIT.json'),selection);save(out/(label+'_SEMANTIC_COVERAGE.json'),raw)
    selected_dates=Counter((r['household_id'],r['date']) for r in selection)
    duplicate_candidates=[i for i,n in Counter(candidate_ids).items() if n>1]
    missing_selected_ids=sorted(chosen-set(candidate_ids))
    source_check=dict(passed=code_hash()==frozen_core and all(sha(p)==h for p,h in pins.items()),
        audit_code_sha256=frozen_core,source_files=len(pins),checked_before_and_after=True)
    save(out/(label+'_SOURCE_CHECK.json'),source_check)
    if not source_check['passed']:raise ValueError('FROZEN_AUDIT_SOURCE_CHANGED_DURING_REVIEW')
    report=dict(report=read(collection/'REPORT.json'),opportunities=summary,semantic_coverage=raw,numeric_exploration=numerical_report,
        engineering_check_pass=all(r['independent_engineering_errors']==0 for r in checks),
        independent_all_candidate_causal_pass=numerical_report['independent_candidate_and_causal_pass'],
        complete_date_accounting=accounting['passed'] and not duplicate_candidates and not missing_selected_ids and
            all(n==10 for n in Counter(h for h,d in contexts).values()) and selected_dates==Counter(dict.fromkeys(contexts,1)),
        duplicate_candidate_ids=duplicate_candidates,selected_ids_missing_from_catalogues=missing_selected_ids,
        generation_date_accounting=accounting,source_check=source_check,
        expected_date_slots=len(contexts),
        full_coverage_claimed=False,physical_validity_claimed=False)
    save(out/(label+'_ACCEPTANCE.json'),report);return dict(slots=len(checks),selected=len(selection),gaps=dict(gaps))


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--out',required=True);p.add_argument('--collection',required=True);p.add_argument('--label',required=True);p.add_argument('--workers',type=int,default=4)
    a=p.parse_args();print(run(a.out,a.collection,a.label,a.workers))
