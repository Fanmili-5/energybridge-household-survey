"""Evidence tables with full denominators and explicit unmet release gates."""
import argparse
import ast
import csv
import itertools
import statistics
import zipfile
from collections import Counter,defaultdict
from pathlib import Path
from concurrent.futures import ProcessPoolExecutor
from benchmark.ab_generation.common import read,save,digest,sha


def family_metrics(record):
    """Equal total vote per available device family; never per AC field."""
    from benchmark.ab_generation.unified.opportunities import declare,coverage
    from .shared_domain_comparison import read_catalogue
    cat=read_catalogue(record['path']);context=read(cat['comparison']['input_record']['context_path'])
    ledger=coverage(declare(context,cat['comparison']['configuration']),cat)
    families=defaultdict(list)
    for e in ledger.get('mechanisms',[]):
        if e['status']=='potential':families[e['family']].append(bool(e['candidate_witness_ids']))
    scores={f:sum(v)/len(v) for f,v in families.items()}
    return {k:record[k] for k in ('arm','seed','household_id','date')} | dict(
        family_potential_witness_ratios=scores,
        macro_family_ratio=statistics.mean(scores.values()) if scores else None,
        evidence_unknown=sum(e['status']=='unknown' for e in ledger.get('mechanisms',[])))


def recipe_equivalence(out):
    from benchmark.ab_generation.unified import candidates as current
    from benchmark.ab_generation.unified.factorized import excluded_requests
    from benchmark.ab_generation.unified.contract import config
    out=Path(out)
    with zipfile.ZipFile(out/'BASELINE_SOURCE.zip') as archive:
        text=archive.read('benchmark/ab_generation/unified/candidates.py').decode()
    f=next(n for n in ast.parse(text).body if isinstance(n,ast.FunctionDef) and n.name=='program_grammar')
    namespace=dict(vars(current));exec(compile(ast.Module(body=[f],type_ignores=[]),'frozen_v1_program_grammar','exec'),namespace)
    old=namespace['program_grammar'];c=read(Path(current.__file__).parents[1]/'examples/control.json')
    results=[]
    for permission in ('original','immutable_handling'):
        ctx=__import__('copy').deepcopy(c)
        if permission=='immutable_handling':ctx['authority']['immutable_operator_ids']=sorted({o['operator_id'] for o in ctx['A']['operations']})
        d=next(d for d in ctx['devices'] if d['asset_id']=='washer');cfg=current.legacy_config(config())
        before={digest(r['patches']) for r in old(ctx,d,cfg)};after=set();excluded=0
        for r in current.program_grammar(ctx,d,cfg):
            if r.get('symbolic_exclusion'):
                literal=list(excluded_requests(r));excluded+=len(literal)
                if len(literal)!=r['request_count']:raise ValueError('EXCLUSION_MASK_COUNT_MISMATCH')
                after.update(digest(x['patches']) for x in literal)
            else:after.add(digest(r['patches']))
        results.append(dict(permission=permission,old_literal_count=len(before),new_with_diagnostics_literal_count=len(after),
            missing=sorted(before-after),added=sorted(after-before),excluded_coordinates=excluded,passed=before==after))
    save(out/'RECIPE_EQUIVALENCE.json',results);return results


def comparisons(out):
    out=Path(out);records=read(out/'comparisons/RESULTS.json');groups=defaultdict(list)
    for r in records:groups[r['arm']].append(r)
    from benchmark.ab_generation.unified import opportunities
    ledger_hash=digest([sha(opportunities.__file__),opportunities.RULES])
    cache=out/'comparisons'/('FAMILY_METRICS_'+ledger_hash[:12]+'.json')
    if cache.exists():family_rows=read(cache)
    else:
        with ProcessPoolExecutor(max_workers=4) as pool:family_rows=list(pool.map(family_metrics,records,chunksize=2))
        save(cache,family_rows)
    family_groups=defaultdict(list)
    for r in family_rows:family_groups[r['arm']].append(r)
    summaries={}
    for arm,rs in sorted(groups.items()):
        values=[r['mechanism_opportunities']['witnessed']/r['mechanism_opportunities']['potential']
                for r in rs if r['mechanism_opportunities']['potential']]
        summaries[arm]=dict(runs=len(rs),engineer_errors=sum(r['independent_errors'] for r in rs),
            macro_family_potential_witness_ratio_mean=statistics.mean(r['macro_family_ratio'] for r in family_groups[arm] if r['macro_family_ratio'] is not None),
            primary_metric='equal available-family budget;input-potential witness retrieval,not proved-feasible coverage',
            opportunity_witness_ratio_mean=statistics.mean(values) if values else None,
            opportunity_ratio_scope='input_potential;not_all_proved_joint_feasible',
            materializations=sum(r['materializations'] for r in rs),
            median_wall_seconds=statistics.median(r['telemetry'].get('wall_seconds',0) for r in rs),
            timing_scope=rs[0].get('timing_scope','full_generation_and_audit'),
            median_shared_native_construction_seconds=statistics.median(r['shared_native_construction_seconds'] for r in rs) if all('shared_native_construction_seconds' in r for r in rs) else None,
            total_semantic_cell_interaction_witnesses=sum(r['interaction_counts'].get('feasible',0) for r in rs),
            interaction_layer='derived_semantic_cells;not_literal_numeric_grid',
            total_unknown=sum(r['interaction_counts'].get('unknown',0)+r['interaction_counts'].get('unexplored',0) for r in rs))
    paired=[];index={(r['arm'],r['seed'],r['household_id'],r['date']):r for r in records}
    for arm in groups:
        if arm=='ipog_base':continue
        byhouse=defaultdict(list)
        for r in groups[arm]:
            b=index[('ipog_base',r['seed'],r['household_id'],r['date'])]
            byhouse[r['household_id']].append(r['mechanism_opportunities']['witnessed']-b['mechanism_opportunities']['witnessed'])
        paired.extend(dict(arm=arm,household_id=h,mean_witness_count_difference_vs_base=statistics.mean(v),
            min_difference=min(v),max_difference=max(v),seed_date_runs=len(v)) for h,v in sorted(byhouse.items()))
    bykey={(r['arm'],r['seed'],r['household_id'],r['date']):r for r in family_rows}
    family_paired=[]
    for arm in groups:
        if arm=='ipog_base':continue
        byhouse=defaultdict(list)
        for r in family_groups[arm]:
            b=bykey[('ipog_base',r['seed'],r['household_id'],r['date'])]
            if r['macro_family_ratio'] is not None and b['macro_family_ratio'] is not None:
                byhouse[r['household_id']].append(r['macro_family_ratio']-b['macro_family_ratio'])
        family_paired.extend(dict(arm=arm,household_id=h,mean_macro_family_difference_vs_base=statistics.mean(v),
            min_difference=min(v),max_difference=max(v),seed_date_runs=len(v)) for h,v in sorted(byhouse.items()))
    result=dict(summaries=summaries,paired_household_differences=paired,primary_family_paired_differences=family_paired,
        independent_ledger_version_sha256=ledger_hash,
        legacy_atomic_opportunity_witness_ratio='archived old accounting;descriptive only;corrected macro family metric is primary',
        households=8,seeds=list(range(8)),predeclared_date_slots=24,all_runs=len(records),
        full_matrix_expected=1152,full_matrix_complete=len(records)==1152,
        population_inference_or_human_validity_claimed=False,
        timing='descriptive_concurrent_local_runs;not_isolated_speed_benchmark',
        significance_tests='not_performed;days_and_seeds_not_independent_households')
    save(out/'COMPARISON_SUMMARY.json',result);return result


def tables(out):
    from benchmark.ab_generation.unified.delivery import review
    out=Path(out);root=out/'fifty';report=read(root/'REPORT.json');selected=set(read(root/'SELECTION.json')['selected_ids']);rows=[];mechanisms=[]
    summary=review(root)
    for slot in read(root/'GENERATION.json'):
        result=read(root/slot['path']);diagnostics=result.get('engineering_diagnostics',[])
        record={k:slot[k] for k in ('household_id','date','status','eligible','native','raw','interaction_targets','witnessed','independent_engineering_errors')}
        record.update(engineering_diagnostic_records=len(diagnostics),
            excluded_request_count_with_duplicates=sum(r.get('request_count',1) if isinstance(r,dict) else 1 for r in diagnostics),
            selected=sum(r['id'] in selected for r in result['rows']),
            wall_seconds=result.get('telemetry',{}).get('wall_seconds'),physical_status='not_computed')
        rows.append(record)
    for date in read(root/'INPUT_OPPORTUNITY_COVERAGE.json.gz'):
        for e in date['mechanisms']:
            mechanisms.append(dict(household_id=date['household_id'],date=date['date'],family=e['family'],asset_id=e['asset_id'],
                need_id=e['need_id'],mechanism=e['mechanism'],axis=e['axis'],status=e['status'],reason=e['reason'],gap=e['gap'],
                candidate_witnesses=len(e['candidate_witness_ids']),selected_witnesses=len(e['selected_witness_ids'])))
    for name,rs in [('FIFTY_SLOT_CHECK.csv',rows),('FIFTY_MECHANISM_COVERAGE.csv',mechanisms)]:
        with (out/name).open('w',newline='') as f:
            writer=csv.DictWriter(f,fieldnames=list(rs[0]));writer.writeheader();writer.writerows(rs)
    save(out/'FIFTY_ACCEPTANCE.json',dict(report=report,opportunities=summary,
        engineering_check_pass=all(r['independent_engineering_errors']==0 for r in rows),
        complete_date_accounting=len(rows)==500 and sum(r['selected'] for r in rows)==500,
        full_coverage_claimed=False,physical_validity_claimed=False))
    return dict(slots=len(rows),mechanism_rows=len(mechanisms),coverage_gate=summary['coverage_gate'])


def claim_gates(out):
    out=Path(out);sources=read(out/'IMMUTABILITY.json');fifty=read(out/'FIFTY_ACCEPTANCE.json')
    eq=read(out/'RECIPE_EQUIVALENCE.json');comp=read(out/'COMPARISON_SUMMARY.json');ui=read(out/'ui91-offline/DISPLAY_CHECK.json')
    e=read(out/'EXHAUSTIVE.json');fresh=read(out/'STAGE_fresh.json')
    public=read(out/'PUBLIC_FRESH_ACCEPTANCE.json');order=read(out/'ORDER_STUDY_SUMMARY.json')
    causal=read(out/'INDEPENDENT_CAUSAL_CHECK.json');freeze=read(out/'CORE_FREEZE_CHECK.json')
    portable=read(out/'PORTABILITY.json') if (out/'PORTABILITY.json').exists() else {'returncode':None}
    tests=(out/'TESTS.log').read_text()
    gates=dict(protected_sources_unchanged=sources['unchanged'],small_device_enumeration=e['passed'],
        factorized_existing_domain_lossless=all(r['passed'] for r in eq),
        independent_engineering=fifty['engineering_check_pass'],all_fifty_dates=fifty['complete_date_accounting'],
        fixed_comparison_matrix_complete=comp['full_matrix_complete'],
        fixed_factor_order_matrix_complete=order['runs']==384 and order['independent_errors']==0,
        public_fresh_sixty_dates=fresh['collection'].get('selected')==60 and public['engineering_check_pass'],
        approved_UI91_renderer=ui['returncode']==0 and ui['exact_UI91_renderer_bytes_unchanged'],
        frozen_source_unchanged=freeze['passed'],regression_suite=tests.rstrip().endswith('OK'),
        selected_causal_paths=causal['passed'],
        fresh_A_literal_check=not read(out/'INDEPENDENT_A_CHECK.json')['new_A_failures'],
        A_same_demand_comparison_complete=read(out/'A_SAME_DEMAND_COMPARISON.json')['runs']==54,
        production_oracle_enumeration=read(out/'PRODUCTION_ORACLE_CHECK.json')['passed'],
        unknown_is_not_no_opportunity=read(out/'EMPTY_DOMAIN_CHECK.json')['passed'],
        moved_directory_replay=portable['returncode']==0,
        input_mechanism_coverage_closed=not bool(fifty['opportunities']['gaps']) and not fifty['opportunities']['input_mechanism_evidence_unknown'] and not public['opportunities']['gaps'])
    result=dict(gates=gates,engineering_artifact_complete=all(v for k,v in gates.items() if k!='input_mechanism_coverage_closed'),
        input_mechanism_coverage_accepted=all(gates.values()),
        full_raw_interaction_coverage_accepted=False,
        full_coverage_accepted=False,
        coverage_scope='mechanism closure and finite raw interaction exploration are separate;unknown never omitted',
        physical_runs=0,online_changed=False,main_updated=False,population1000_started=False,
        human_and_model_validity='not_run;not_claimed',
        allowed_claim='traceable reproducible finite-model generation with independent diagnostics and disclosed bounded coverage',
        forbidden_claims=['population representativeness','real household behavior validity','observed physical failure distribution','training benefit without experiments'])
    save(out/'CLAIM_GATES.json',result);return result


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--out',required=True);p.add_argument('--stage',choices=['recipes','comparisons','tables','gates'],required=True)
    a=p.parse_args();print({'recipes':recipe_equivalence,'comparisons':comparisons,'tables':tables,'gates':claim_gates}[a.stage](a.out))
