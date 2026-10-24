"""Read-only fixed-bank review of exact joint-task coverage and retained tails."""
import argparse
import copy
from collections import Counter,defaultdict
from pathlib import Path

from benchmark.ab_generation.common import read,save,sha,digest
from benchmark.ab_generation.model import apply
from benchmark.ab_generation.unified.contract import config,entry_config,code_hash
from benchmark.ab_generation.unified.selection import assign
from benchmark.ab_generation.unified.independent import audit
from .acceptance import record_sources
from .causal_audit import check_case


def attainable_orders(rows):
    """Independent maximum matching: one witnessed task count per date slot."""
    import numpy as np
    from scipy.sparse import csr_matrix
    from scipy.sparse.csgraph import maximum_bipartite_matching
    result=[]
    for home in sorted({r['household_id'] for r in rows}):
        subset=[r for r in rows if r['household_id']==home]
        counts=sorted({r['independent_units'] for r in subset});days=sorted({r['date'] for r in subset})
        supports={(r['independent_units'],r['date']) for r in subset}
        graph=csr_matrix(np.array([[(k,d) in supports for d in days] for k in counts],dtype=np.int8))
        matching=maximum_bipartite_matching(graph,perm_type='column')
        result.append(dict(household_id=home,available_task_counts=counts,date_slots=len(days),
            maximum_distinct_counts=int(sum(v>=0 for v in matching)),
            witness=[dict(tasks=k,date=days[int(v)]) for k,v in zip(counts,matching) if v>=0]))
    return result


def run(protocol,out):
    protocol,out=Path(protocol).resolve(),Path(out).resolve();spec=read(protocol)
    out.mkdir(parents=True,exist_ok=False);collection=Path(spec['source_bank'])
    bank=collection/'CANDIDATE_ROWS.json.gz'
    if sha(bank)!=spec['candidate_rows_sha256']:raise ValueError('FROZEN_BANK_CHANGED')
    rows=[r for r in read(bank) if r['household_id'] in spec['households']]
    before=digest(rows);pre,contexts=record_sources(collection)
    paths={k:p for k,p in contexts.items() if k[0] in spec['households']}
    pins={str(protocol):sha(protocol),str(bank):sha(bank),str(Path(__file__)):sha(__file__)}
    pins.update({str(p):sha(p) for p in paths.values()})
    expected=Counter({k:1 for k in paths})
    if any(sum(k[0]==h for k in expected)!=10 for h in spec['households']):
        raise ValueError('ORIGINAL_TEN_DATES_REQUIRED')
    literal=[];causal=[];loaded={k:read(p) for k,p in paths.items()}
    for row in rows:
        c=loaded[(row['household_id'],row['date'])]
        errors=audit(c,c['A'],apply(c['A'],row['patches']))
        if errors:literal.append(dict(id=row['id'],errors=errors))
        causal.extend(r for r in check_case(c,row) if not r['passed'])
    if literal or causal:
        save(out/'ADMISSION_FAILURE.json',dict(literal=literal,causal=causal))
        raise ValueError('INDEPENDENT_FROZEN_BANK_ADMISSION_FAILED')
    available=attainable_orders(rows);save(out/'INDEPENDENT_MATCHING.json',available)
    cfg=entry_config();save(out/'CURRENT_CONFIG.json',cfg)
    arms=[]
    settings=[('legacy_policy',{**cfg,'selection_joint_order':'legacy_buckets_v1'})]
    settings += [('exact_repeat_'+str(m),{**cfg,**{k:cfg[k]*m for k in ('repeat_family','repeat_composition','repeat_context')}})
                 for m in spec['repeat_multipliers']]
    byid={r['id']:r for r in rows}
    for name,setting in settings:
        answer=assign(rows,setting);save(out/(name+'.json'),answer)
        selected=[byid[k] for k in answer['selected_ids']]
        if Counter((r['household_id'],r['date']) for r in selected)!=expected:
            raise ValueError('SELECTION_DATE_ACCOUNTING_FAILED:'+name)
        counts=[]
        for home in available:
            chosen=Counter(r['independent_units'] for r in selected if r['household_id']==home['household_id'])
            counts.append(dict(**home,selected_task_counts=dict(sorted(chosen.items())),
                missing_task_counts=sorted(set(home['available_task_counts'])-chosen.keys()),
                achieves_independent_maximum=len(chosen)==home['maximum_distinct_counts']))
        if name.startswith('exact') and not all(r['achieves_independent_maximum'] for r in counts):
            raise ValueError('EXACT_POLICY_UNDER_INDEPENDENT_COVERAGE_BOUND:'+name)
        arm=dict(arm=name,selected=len(selected),by_household=counts,
            task_counts=dict(sorted(Counter(r['independent_units'] for r in selected).items())),
            life_or_service_conflict=sum(bool(r['issues']) for r in selected),
            nominal_zero=sum(abs(r['known_event_reduction_kWh'])<1e-8 for r in selected),
            nominal_reverse=sum(r['known_event_reduction_kWh']< -1e-8 for r in selected),
            small_action_present=sum(any(c['relative_level']=='small_relative' for c in r['components']) for r in selected),
            thermal_unknown=sum(bool(r['unknown_thermal_response']) for r in selected),
            human_and_physical_fields_empty=all(all(r.get(k) is None for k in ('human_acceptance','human_score','human_reason','actual_outcomes')) for r in rows),
            full_catalogue_retained=True,solver=[b['solver'] for b in answer['blocks']])
        arms.append(arm)
    final=assign(list(reversed(rows)),cfg)
    reference=read(out/'exact_repeat_1.json')
    replay=set(final['selected_ids'])==set(reference['selected_ids'])
    if not replay or before!=digest(rows):raise ValueError('REPLAY_OR_INPUT_MUTATION')
    if any(sha(p)!=h for p,h in pins.items()):raise ValueError('FROZEN_SOURCES_CHANGED')
    result=dict(passed=True,source_core_sha256=code_hash(),households=len(spec['households']),
        original_dates=len(expected),candidate_rows=len(rows),independent_literal_errors=literal,
        independent_causal_errors=causal,arms=arms,input_order_replay=replay,
        A_B_and_catalogue_unchanged=True,source_files_unchanged=True,
        new_A_or_B_generated=False,source_sha256=pins,physical_runs=0,online_changed=False,
        coverage_scope='independently checked frozen candidate witnesses;not proof of complete search space',
        no_proportions_or_success_filter=True,human_or_population_validity_claimed=False)
    save(out/'RESULT.json',result)
    save(out/'PUBLIC_RESULT.json',{k:v for k,v in result.items() if k!='source_sha256'})
    return dict(passed=True,households=len(spec['households']),dates=len(expected),candidates=len(rows),
                arms=len(arms),new_A_or_B=False,physical_runs=0)


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--protocol',required=True);p.add_argument('--out',required=True)
    a=p.parse_args();print(run(a.protocol,a.out))
