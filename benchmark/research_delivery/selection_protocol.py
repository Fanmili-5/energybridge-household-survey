"""Frozen-bank selection comparisons with explicit signature provenance.

No candidate generation, physical evaluation, label fitting or outcome-based
replacement. Every arm uses the same complete bank and day slots. Diagnostics
and failed solver arms are retained, never retried under a different seed.
"""
import argparse
import copy
from collections import Counter,defaultdict
from contextlib import nullcontext
from pathlib import Path
from unittest.mock import patch

from benchmark.ab_generation.common import read,save,digest,sha
from benchmark.ab_generation.unified import selection
from benchmark.ab_generation.collection_assignment import assign as prior_assign
from .semantic_links import signature,VERSION


def view_scope(version):
    if version=='device_linked_candidate2':return patch.object(selection,'judgment_signature',signature)
    if version=='frozen_v2':
        from benchmark.ab_generation.unified import semantics
        legacy=getattr(semantics,'legacy_judgment_signature',semantics.judgment_signature)
        return patch.object(selection,'judgment_signature',legacy)
    if version=='linked_v3':
        from benchmark.ab_generation.unified import semantics
        if not hasattr(semantics,'LINKED_SIGNATURE_VERSION'):
            raise ValueError('LINKED_V3_NOT_INSTALLED_IN_THIS_RUNTIME')
        return nullcontext()
    raise ValueError('UNKNOWN_SELECTION_SIGNATURE')


def signature_provenance(version,rows):
    if version=='device_linked_candidate2':return VERSION
    if version=='frozen_v2':return 'eb.plan_semantics.v2'
    if version=='linked_v3':
        from benchmark.ab_generation.unified import semantics
        if not hasattr(semantics,'LINK_VERSION'):
            raise ValueError('LINKED_V3_NOT_INSTALLED_IN_THIS_RUNTIME')
        for row in rows:
            if row.get('judgment_context_version')!=semantics.LINK_VERSION:
                raise ValueError('LINKED_V3_REQUIRES_ALL_ROWS_EXPLICITLY_BOUND')
            semantics.linked_contexts(row)
        return semantics.LINKED_SIGNATURE_VERSION
    raise ValueError('UNKNOWN_SELECTION_SIGNATURE')


def selection_accounting(rows,ids,expected_dates):
    known={r['id']:r for r in rows};counts=Counter(ids)
    unknown=sorted(set(ids)-known.keys());duplicates=sorted(i for i,n in counts.items() if n>1)
    # Metrics on unique known records accompany, never conceal, an invalid arm.
    valid=[i for i in ids if i in known]
    unique=list(dict.fromkeys(valid))
    dates=Counter((known[i]['household_id'],known[i]['date']) for i in valid)
    return dict(passed=not unknown and not duplicates and dates==expected_dates,
        unknown_ids=unknown,duplicate_ids=duplicates,metric_ids=unique,
        missing_dates=[list(k) for k in sorted(expected_dates.keys()-dates.keys())],
        extra_dates=[list(k) for k in sorted(dates.keys()-expected_dates.keys())],
        multiple_cases_per_date=[list(k) for k,n in sorted(dates.items()) if n>1])


def weight_totals(targets):
    result=defaultdict(float)
    for t in targets:
        if t['tag'].startswith('detail.'):
            key='global_detail:'+t['tag'].split('.')[1]
        else:key=str(t['household'])+':'+t['tag'].split('=')[0].split('.')[0]
        result[key]+=t['weight']
    return dict(result)


def measure(rows,ids,targets,views):
    byid={r['id']:r for r in rows};selected=[byid[i] for i in ids]
    exposed=Counter(f for i in ids for f in views[i]['families'])
    covered={(r['household_id'],tag) for r in selected for tag in views[r['id']]['tokens']}
    covered|={(None,tag) for r in selected for tag in views[r['id']]['tokens']}
    total=sum(t['weight'] for t in targets)
    return dict(selected=len(selected),weighted_coverage_fraction=sum(t['weight'] for t in targets if (t['household'],t['tag']) in covered)/total if total else None,
        semantic_repeat_excess=sum(n-1 for n in Counter((r['household_id'],views[r['id']]['signature']) for r in selected).values()),
        family_date_exposure=dict(exposed),joint_order=dict(Counter(r['independent_units'] for r in selected)),
        life_or_service_pressure=sum(bool(r['issues']) for r in selected),
        soft_tension=sum(any(j['soft_preference_tension'] for j in r['judgment_context']) for r in selected),
        nominal_zero=sum(abs(r['known_event_reduction_kWh'])<1e-8 for r in selected),
        nominal_reverse=sum(r['known_event_reduction_kWh']< -1e-8 for r in selected),
        thermal_unknown=sum(r['unknown_thermal_response'] for r in selected),
        answer_and_actual_fields_empty=all(all(r.get(k) is None for k in ('human_acceptance','human_score','human_reason','actual_outcomes')) for r in selected))


def run(collection,out,version='device_linked_candidate2',rows_cache=None):
    collection,out=Path(collection),Path(out);out.mkdir(parents=True,exist_ok=False)
    slots=read(collection/'GENERATION.json')
    expected_dates=Counter({(s['household_id'],s['date']):1 for s in slots})
    if len(expected_dates)!=len(slots):raise ValueError('DUPLICATE_DATE_SLOT')
    if any(s.get('independent_engineering_errors')!=0 for s in slots):
        save(out/'UNRESOLVED_ADMISSION.json',dict(status='independent_admission_not_verified',slots=slots))
        return dict(status='admission_unresolved;no_selection_performed')
    pins={str(collection/f):sha(collection/f) for f in ('PRE_GENERATION.json','GENERATION.json','SELECTION.json')};rows=[]
    if rows_cache:
        cache=Path(rows_cache);rows=read(cache);pins[str(cache)]=sha(cache)
        # The caller must supply the cache written by semantic_links for this
        # exact complete bank. Its source pins remain an explicit dependency.
        source_pins=read(cache.parent/'SOURCE_PINS.json')
        if any(sha(p)!=h for p,h in source_pins.items()):raise ValueError('CACHED_BANK_SOURCE_CHANGED')
        expected={str(collection/s['path']):sha(collection/s['path']) for s in slots}
        if source_pins!=expected:raise ValueError('CACHE_DOES_NOT_BIND_THIS_COMPLETE_BANK')
        if sha(cache)!=read(cache.parent/'METHOD_PINS.json')['rows_sha256']:raise ValueError('CACHED_ROWS_CHANGED')
        pins.update(source_pins)
    else:
        for slot in slots:
            path=collection/slot['path'];pins[str(path)]=sha(path);rows.extend(read(path).get('rows',[]))
    if len({r['id'] for r in rows})!=len(rows):raise ValueError('DUPLICATE_CANDIDATE_ID')
    if any(any(r.get(k) is not None for k in ('human_acceptance','human_score','human_reason','actual_outcomes')) for r in rows):
        raise ValueError('OUTCOME_OR_ANSWER_IN_SELECTION_BANK')
    pre=read(collection/'PRE_GENERATION.json')
    cfg=pre.get('post_generation_mapping',{}).get('configuration',pre['configuration'])
    old=read(collection/'SELECTION.json')
    signature_version=signature_provenance(version,rows)
    groups=defaultdict(list)
    for r in rows:groups[(r['household_id'],r['date'])].append(r)
    missing=sorted(expected_dates.keys()-groups.keys())
    if missing:
        save(out/'UNRESOLVED_ADMISSION.json',dict(status='missing_given_day_candidates',missing_dates=missing,
            expected_dates=len(expected_dates),available_dates=len(groups),replacement_generated=False))
        return dict(status='given_slots_unresolved;no_selection_performed',missing_dates=missing)
    plan=dict(signature=version,effective_signature_version=signature_version,source_pins=pins,configuration=cfg,
        frozen_selection_origin=str(collection/'SELECTION.json'),
        original_native_generator_configuration=pre['configuration'],
        uniform_seeds=list(range(8)),repeat_multipliers=[0,.5,1,2],block_sizes=[10,25,50],
        household_order_at_fixed_block_10=['original','reversed'],
        all_arms_same_full_candidate_bank=True,primary_measure='coverage weights fixed from full bank,not each selected subset',
        no_physical_or_human_outcomes=True,helper_sha256=sha(__file__),signature_helper_sha256=sha(Path(__file__).with_name('semantic_links.py')))
    save(out/'PROTOCOL.json',plan);results=[]
    with view_scope(version):
        views={r['id']:selection.concepts(r,cfg.get('selection_joint_order','legacy_buckets_v1')) for r in rows};targets=selection.goals(rows,list(views.values()))
        save(out/'FROZEN_TARGETS.json',targets)
        def invoke(function):
            try:return function()
            except Exception as error:
                return dict(status='selection_error;not_physical_failure',selected_ids=[],
                            error=type(error).__name__+':'+str(error),retried=False)
        def record(name,answer):
            if callable(answer):answer=invoke(answer)
            ids=answer.get('selected_ids',[]);save(out/(name+'.json'),answer)
            accounting=selection_accounting(rows,ids,expected_dates)
            entry=dict(arm=name,date_accounting_pass=accounting['passed'],
                accounting={k:v for k,v in accounting.items() if k!='metric_ids'},
                **measure(rows,accounting['metric_ids'],targets,views))
            results.append(entry);save(out/'PROGRESS.json',results)
        for seed in range(8):
            ids=[min(rs,key=lambda r:digest([seed,'uniform',r['id']]))['id'] for rs in groups.values()]
            record('uniform_'+str(seed),dict(selected_ids=ids,seed=seed,rule='minimum_seeded_hash_per_given_date'))
        record('prior_v4',lambda:prior_assign(rows,dict(seed=cfg['seed'],solver_node_limit=cfg['selection_nodes'],assignment_representatives_per_cell=2)))
        record('frozen_original_selection',old)
        base=invoke(lambda:selection.assign(rows,cfg));record('repeat_1',base)
        for multiplier in (0,.5,2):
            varied={**cfg,**{k:cfg[k]*multiplier for k in ('repeat_context','repeat_family','repeat_composition')}}
            record('repeat_'+str(multiplier),lambda:selection.assign(rows,varied))
        for block in (10,25,50):
            record('block_'+str(block),base if block==cfg['block_households'] else lambda:selection.assign(rows,{**cfg,'block_households':block}))
        home_order=base.get('household_order',old['household_order'])
        for name,homes in [('original',home_order),('reversed',list(reversed(home_order)))]:
            carry=set();ids=[];blocks=[]
            for offset in range(0,len(homes),10):
                subset=set(homes[offset:offset+10]);answer=invoke(lambda:selection.select_block([r for r in rows if r['household_id'] in subset],{**cfg,'block_households':10},carry))
                ids+=answer['selected_ids'];blocks.append(answer)
                for rid in answer['selected_ids']:carry.update((None,t) for t in views[rid]['tokens'])
            record('household_order_'+name,dict(selected_ids=ids,blocks=blocks,household_order=homes,block_households=10))
        modified=copy.deepcopy(rows)
        for row in modified:
            row['service_context']=[dict(kind='unrelated',release_min=999999)]
            for c in row['components']:
                c['magnitude']['descriptive_extra_axes']=['not_a_selection_target']*100
        after={r['id']:selection.concepts(r,cfg.get('selection_joint_order','legacy_buckets_v1')) for r in modified}
        changed_targets=selection.goals(modified,list(after.values()))
        reversed_rows=invoke(lambda:selection.assign(list(reversed(rows)),cfg))
        invariant=dict(descriptive_fields_exact_views_equal=views==after,
            target_definitions_and_weights_equal=digest(targets)==digest(changed_targets),
            input_order_selected_ids_equal=bool(base['selected_ids']) and set(reversed_rows['selected_ids'])==set(base['selected_ids']),
            total_weight_groups=weight_totals(targets),
            fields_mutated=['magnitude.descriptive_extra_axes','unrelated service_context'],
            scope='declared fields only;not proof of absence of every possible coverage bias')
        save(out/'INVARIANCE.json',invariant)
    if any(sha(p)!=h for p,h in pins.items()):raise ValueError('FROZEN_INPUT_CHANGED_DURING_SELECTION_STUDY')
    save(out/'RESULTS.json',results)
    return dict(arms=len(results),all_dates_accounted=all(r['date_accounting_pass'] for r in results),
                all_answers_empty=all(r['answer_and_actual_fields_empty'] for r in results),invariance=invariant)


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--collection',required=True);p.add_argument('--out',required=True)
    p.add_argument('--signature',default='device_linked_candidate2');p.add_argument('--rows-cache')
    a=p.parse_args();print(run(a.collection,a.out,a.signature,a.rows_cache))
