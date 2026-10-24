"""Verify the exact matched-search matrix and compute input-side family metrics.

The large native archive is hash-checked once per seed/date, not expanded six
times to count direct witnesses. This changes reporting cost, not the methods,
action domains, candidate sets, denominator or predeclared comparisons.
"""
import argparse
import statistics
from collections import Counter,defaultdict
from pathlib import Path

from benchmark.ab_generation.common import read,save,sha,digest,bound
from benchmark.ab_generation.unified.contract import config
from benchmark.ab_generation.unified.opportunities import declare
from benchmark.ab_generation.unified.semantics import mechanism
from .shared_domain_comparison import ARMS


def matrix_keys(plan,records):
    inputs=plan['comparison_records'];seeds=plan['seeds']
    dates=[(r['household_id'],r['date']) for r in inputs]
    if (len(inputs)!=24 or len(set(dates))!=24 or seeds!=list(range(8)) or
            sorted(Counter(h for h,d in dates).values())!=[3]*8):
        raise ValueError('COMPARISON_PROTOCOL_IS_NOT_FIXED_24_DATES_EIGHT_SEEDS')
    expected={(arm,seed,h,d) for arm,_ in ARMS for seed in seeds for h,d in dates}
    actual=[(r['arm'],r['seed'],r['household_id'],r['date']) for r in records]
    counts=Counter(actual)
    return dict(expected=len(expected),actual=len(actual),
        missing=sorted(expected-set(actual)),unexpected=sorted(set(actual)-expected),
        duplicates=[list(k) for k,n in sorted(counts.items()) if n>1],
        complete=set(actual)==expected and all(n==1 for n in counts.values()))


def direct_family_metrics(cat,context):
    """Re-declare inputs and count candidate literal event-root identities."""
    ledger=declare(context,cat['comparison']['configuration'])
    if ledger!=cat['input_opportunities']:
        raise ValueError('INPUT_LEDGER_REDECLARATION_DIFFERS_FROM_SEARCH_INPUT')
    hits=set()
    for row in cat.get('rows',[]):
        for c in row['components']:
            if c['event_relevance']['role']=='direct_event_request':
                hits.add((c['asset_id'],c.get('service_need_id'),mechanism(c['mechanism']),c['magnitude'].get('axis')))
    families=defaultdict(list)
    for e in ledger['entries']:
        if e['status']=='potential':
            families[e['family']].append((e['asset_id'],e['need_id'],e['mechanism'],e['axis']) in hits)
    counts={f:dict(potential=len(v),witnessed=sum(v)) for f,v in families.items()}
    ratios={f:v['witnessed']/v['potential'] for f,v in counts.items()}
    result=dict(family_counts=counts,family_potential_witness_ratios=ratios,
        macro_family_ratio=statistics.mean(ratios.values()) if ratios else None,
        potential=sum(v['potential'] for v in counts.values()),
        witnessed=sum(v['witnessed'] for v in counts.values()),
        evidence_unknown=sum(e['status']=='unknown' for e in ledger['entries']))
    if any(result[k]!=cat['independent_opportunity_coverage'][k] for k in ('potential','witnessed')):
        raise ValueError('SAVED_OPPORTUNITY_COUNTS_DISAGREE_WITH_LITERAL_WITNESSES')
    return result


def run(comparisons,out):
    comparisons,out=Path(comparisons).resolve(),Path(out).resolve()
    protocol=read(comparisons/'PROTOCOL.json');plan=protocol['plan']
    records=read(comparisons/'RESULTS.json');accounting=matrix_keys(plan,records)
    out.mkdir(parents=True,exist_ok=False)
    save(out/'MATRIX_ACCOUNTING.json',accounting)
    if not accounting['complete']:
        save(out/'SUMMARY.json',dict(status='incomplete_or_duplicate_matrix;no_complete_comparison_claim',accounting=accounting))
        return dict(complete=False,accounting=accounting)
    inputs={(r['household_id'],r['date']):r for r in plan['comparison_records']}
    changes=dict(ARMS);pins={str(comparisons/f):sha(comparisons/f) for f in ('PROTOCOL.json','RESULTS.json')}
    checked_native={};contexts={};group_sources={};metrics=[]
    for record in records:
        path=Path(record['path']).resolve()
        if not path.is_relative_to(comparisons):raise ValueError('COMPARISON_RECORD_OUTSIDE_FROZEN_RUN')
        pins[str(path)]=sha(path);cat=read(path);meta=cat['comparison']
        item=inputs[(record['household_id'],record['date'])]
        if meta['input_record']!=item or meta['arm']!=record['arm']:
            raise ValueError('COMPARISON_RECORD_IDENTITY_MISMATCH')
        base_cfg=config({**plan['base_config'],'seed':record['seed']})
        cfg=config({**base_cfg,**changes[record['arm']]})
        if meta['configuration']!=cfg:raise ValueError('COMPARISON_ARM_NOT_PREDECLARED')
        source=path.parent/'PREDECLARED.json'
        if source not in group_sources:
            group_sources[source]=read(source);pins[str(source)]=sha(source)
            if group_sources[source]['code_sha256']!=protocol['code_sha256']:
                raise ValueError('COMPARISON_GENERATOR_VERSION_MISMATCH')
            for p,h in group_sources[source]['sources'].items():
                if sha(p)!=h:raise ValueError('COMPARISON_ORIGINAL_INPUT_CHANGED')
                pins[p]=h
        group=group_sources[source]
        if (group['input_record']!=item or group['configuration']!=base_cfg or
                group['grammar_fingerprint']!=meta['shared_domain_fingerprint']):
            raise ValueError('MATCHED_DOMAIN_GROUP_MISMATCH')
        ref=cat['shared_native_domain'];native=bound(path.parent,ref['path'])
        identity=(ref['sha256'],ref['content_sha256'])
        if native not in checked_native:
            if sha(native)!=ref['sha256']:raise ValueError('FROZEN_NATIVE_ARCHIVE_CHANGED')
            checked_native[native]=identity;pins[str(native)]=ref['sha256']
        elif checked_native[native]!=identity:raise ValueError('ARMS_REFER_TO_DIFFERENT_NATIVE_DOMAIN')
        cp=item['context_path']
        if cp not in contexts:contexts[cp]=read(cp)
        metric=direct_family_metrics(cat,contexts[cp])
        if any(metric[k]!=record['mechanism_opportunities'][k] for k in ('potential','witnessed')):
            raise ValueError('COMPARISON_RESULT_SUMMARY_MISMATCH')
        metrics.append({k:record[k] for k in ('arm','seed','household_id','date')} | metric)
    byarm=defaultdict(list)
    for r in metrics:byarm[r['arm']].append(r)
    summaries={}
    for arm,rs in byarm.items():
        raw=[r for r in records if r['arm']==arm]
        ratios=[r['macro_family_ratio'] for r in rs if r['macro_family_ratio'] is not None]
        summaries[arm]=dict(runs=len(rs),macro_family_potential_witness_ratio_mean=statistics.mean(ratios) if ratios else None,
            family_metric_defined_runs=len(ratios),independent_engineering_errors=sum(r['independent_errors'] for r in raw),
            semantic_cell_witnesses=sum(r['interaction_counts'].get('feasible',0) for r in raw),
            semantic_cell_unknown_or_unexplored=sum(r['interaction_counts'].get('unknown',0)+r['interaction_counts'].get('unexplored',0) for r in raw),
            materializations=sum(r['materializations'] for r in raw),oracle_calls=sum(r['oracle_calls'] for r in raw),
            median_search_and_audit_seconds=statistics.median(r['telemetry']['wall_seconds'] for r in raw),
            median_shared_construction_seconds=statistics.median(r['shared_native_construction_seconds'] for r in raw))
    indexed={(r['arm'],r['seed'],r['household_id'],r['date']):r for r in metrics};paired=defaultdict(list)
    for r in metrics:
        if r['arm']=='ipog_base':continue
        base=indexed[('ipog_base',r['seed'],r['household_id'],r['date'])]
        if r['macro_family_ratio'] is not None and base['macro_family_ratio'] is not None:
            paired[(r['arm'],r['household_id'])].append(r['macro_family_ratio']-base['macro_family_ratio'])
    difference=[dict(arm=a,household_id=h,seed_date_runs=len(v),mean_macro_family_difference_vs_ipog=statistics.mean(v),
                     minimum=min(v),maximum=max(v)) for (a,h),v in sorted(paired.items())]
    if any(sha(p)!=h for p,h in pins.items()):raise ValueError('COMPARISON_EVIDENCE_CHANGED_DURING_REPORT')
    result=dict(complete=True,records=len(records),expected=accounting['expected'],
        native_archives_verified=len(checked_native),households=len({r['household_id'] for r in inputs.values()}),
        primary_metric='equal total vote per input-supported device family;potential is not proved joint feasibility',
        summaries=summaries,paired_household_differences=difference,
        all_prespecified_seeds_retained=True,full_numeric_coverage_claimed=False,
        population_or_human_validity_claimed=False,physical_runs=0,
        timing_scope='concurrent local wall-clock description;not isolated speed benchmark',
        statistical_inference='not performed;dates and seeds are not independent households')
    save(out/'FAMILY_METRICS.json',metrics);save(out/'SOURCE_PINS.json',pins)
    save(out/'METHOD_PINS.json',dict(helper_sha256=sha(__file__),native_archives_not_expanded_for_family_count=True,
        original_generator_code_sha256=protocol['code_sha256'],input_ledger_redeclared_and_literal_roots_counted=True))
    save(out/'SUMMARY.json',result)
    return dict(complete=True,records=len(records),native_archives_verified=len(checked_native))


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--comparisons',required=True);p.add_argument('--out',required=True)
    a=p.parse_args();print(run(a.comparisons,a.out))
