"""Reselect a frozen bank without generating plans or changing its denominators."""
import argparse
from collections import Counter, defaultdict
import csv
import hashlib
from pathlib import Path
import time

from benchmark.ab_generation.common import read, save, digest
from benchmark.ab_generation.model import apply
from benchmark.ab_generation.unified.contract import entry_config, code_hash
from benchmark.ab_generation.unified.independent import audit
from benchmark.ab_generation.unified.opportunities import declare
from benchmark.ab_generation.unified.selection import assign, concepts
from benchmark.ab_generation.unified.semantics import mechanism
from .acceptance import record_sources
from .causal_audit import check_case
from .joint_order_review import attainable_orders


def file_hash(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as f:
        for block in iter(lambda: f.read(1024 * 1024), b''):
            h.update(block)
    return h.hexdigest()


def tail_flags(row):
    flags = dict(
        life_or_service_conflict=bool(row['issues']),
        soft_preference_tension=any(c['soft_preference_tension'] for c in row['judgment_context']),
        member_disagreement=any(c.get('member_opinions_differ') for c in row['judgment_context']),
        confirmation_required=row['consent_status'] == 'new_confirmation_required',
        nominal_zero=abs(row['known_event_reduction_kWh']) < 1e-8,
        nominal_reverse=row['known_event_reduction_kWh'] < -1e-8,
        thermal_unknown=bool(row['unknown_thermal_response']),
        no_change=row['independent_units'] == 0)
    if not row.get('change_axes_version'):
        return dict(small_action=any(c['relative_level'] == 'small_relative' for c in row['components']), **flags)
    axes = [c['change_axes'] for c in row['components']]
    programs = [a for a in axes if a['machine']['signed_start_shift_min'] is not None]
    thermal = [a['thermal'] for a in axes if 'thermal' in a]
    return dict(**flags,
        program_shift_le30_min=any(0<abs(a['machine']['signed_start_shift_min'])<=30 for a in programs),
        program_shift_gt120_min=any(abs(a['machine']['signed_start_shift_min'])>120 for a in programs),
        handling_retime_gt120_min=any(a['handling']['maximum_absolute_retime_min']>120 for a in axes),
        short_machine_long_handling=any(0<abs(a['machine']['signed_start_shift_min'])<=30 and a['handling']['maximum_absolute_retime_min']>120 for a in programs),
        pre_event_preparation=any(t['timing']['pre_event_preparation_min']>0 for t in thermal),
        in_event_preparation=any(t['timing']['in_event_preparation_min']>0 for t in thermal),
        cross_event_preparation=any(t['timing']['pre_event_preparation_min']>0 and t['timing']['in_event_preparation_min']>0 for t in thermal))


def summarize(rows, ids):
    chosen = set(ids)
    subset = [r for r in rows if r['id'] in chosen]
    if len(subset) != len(ids):
        raise ValueError('UNKNOWN_OR_DUPLICATE_SELECTED_ID')
    tails = Counter()
    for row in subset:
        tails.update({k: int(v) for k, v in tail_flags(row).items()})
    return dict(cases=len(subset), task_counts=dict(sorted(Counter(r['independent_units'] for r in subset).items())),
                tails=dict(tails), physical_failures_observed=0,
                actual_outcomes_empty=all(r.get('actual_outcomes') is None for r in subset))


def validate_slots(rows, ids, contexts):
    byid = {r['id']: r for r in rows}
    if len(byid) != len(rows):
        raise ValueError('DUPLICATE_CANDIDATE_ID')
    if len(set(ids)) != len(ids) or not set(ids) <= byid.keys():
        raise ValueError('UNKNOWN_OR_DUPLICATE_SELECTED_ID')
    actual = Counter((byid[i]['household_id'], byid[i]['date']) for i in ids)
    if actual != Counter({k: 1 for k in contexts}):
        raise ValueError('ORIGINAL_DATE_ACCOUNTING_FAILED')


def write_csv(path, rows):
    with Path(path).open('w', newline='', encoding='utf-8') as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0]))
        writer.writeheader()
        for row in rows:
            writer.writerow({k: digest(v) if isinstance(v, set) else v for k, v in row.items()})


def run(protocol, out):
    start = time.monotonic()
    protocol, out = Path(protocol).resolve(), Path(out).resolve()
    spec = read(protocol)
    out.mkdir(parents=True, exist_ok=False)
    collection = Path(spec['source_bank']).resolve()
    bank = collection / 'CANDIDATE_ROWS.json.gz'
    if file_hash(bank) != spec['candidate_rows_sha256']:
        raise ValueError('FROZEN_BANK_CHANGED')
    cfg = entry_config(spec['config_path'])
    if digest(cfg) != spec['config_sha256'] or code_hash() != spec['core_sha256']:
        raise ValueError('FROZEN_METHOD_CHANGED')
    _, contexts = record_sources(collection)
    rows = read(bank)
    if sorted({r['household_id'] for r in rows}) != spec['households']:
        raise ValueError('ROSTER_CHANGED')
    if set(contexts) != {(r['household_id'], r['date']) for r in rows}:
        raise ValueError('CANDIDATE_DATES_DIFFER_FROM_INPUTS')
    if len(contexts) != spec['expected_date_slots'] or any(
            sum(k[0] == h for k in contexts) != spec['dates_per_household'] for h in spec['households']):
        raise ValueError('ORIGINAL_TEN_DATES_REQUIRED')
    comparison_path = Path(spec.get('comparison_selection_path', collection / 'SELECTION.json')).resolve()
    if spec.get('comparison_selection_sha256') and file_hash(comparison_path)!=spec['comparison_selection_sha256']:
        raise ValueError('FROZEN_COMPARISON_SELECTION_CHANGED')
    source_files = [p for p in collection.iterdir() if p.is_file()] + list(contexts.values()) + [protocol, Path(spec['config_path']), comparison_path]
    source_files += list(Path(__file__).parent.glob('*.py'))
    pins = {str(p): file_hash(p) for p in source_files}
    save(out / 'SOURCE_PINS.json', pins)
    save(out / 'CURRENT_CONFIG.json', cfg)
    protected = read(spec['protected_baseline'])
    protected_bad = [p for p, h in protected.items() if file_hash(p) != h]
    if protected_bad:
        save(out / 'PROTECTED_INPUT_ERRORS.json', protected_bad)
        raise ValueError('PROTECTED_INPUTS_CHANGED_BEFORE_RUN')
    old = read(comparison_path)
    validate_slots(rows, old['selected_ids'], contexts)
    old_metrics = summarize(rows, old['selected_ids'])
    save(out / 'OLD_SELECTION_REFERENCE.json', dict(selection_sha256=file_hash(comparison_path), **old_metrics))
    original_house_metrics = {h:summarize([r for r in rows if r['household_id']==h],
        [r['id'] for r in rows if r['household_id']==h and r['id'] in set(old['selected_ids'])]) for h in spec['households']}
    original_index = {r['id']:i for i,r in enumerate(rows)}
    grouped = defaultdict(list)
    for row in rows:
        grouped[(row['household_id'], row['date'])].append(row)
    errors, causal_errors, dates, mechanisms, axis_errors = [], [], [], [], []
    component_count = 0
    print(f'Frozen inputs verified: {len(rows)} candidates / {len(contexts)} dates', flush=True)
    for index, (key, path) in enumerate(sorted(contexts.items()), 1):
        context = read(path)
        domain = declare(context, cfg)
        candidate_hits = defaultdict(list)
        annotated = []
        for original in grouped[key]:
            row = original
            if cfg['method_revision']=='delivery_v2_11':
                from benchmark.ab_generation.unified.change_axes import annotate_frozen_row
                from .axis_acceptance import check
                row=annotate_frozen_row(context, original, cfg['event'])
                row['annotation_provenance'].pop('original_selection_not_changed',None)
                row['annotation_provenance']['source_selection_preserved_on_disk']=True
                found=check(context, original, row)
                if found:axis_errors.append(dict(id=row['id'],errors=found))
            rows[original_index[row['id']]]=row
            annotated.append(row)
            concepts(row, cfg['selection_joint_order'])
            B = apply(context['A'], row['patches'])
            issues = audit(context, context['A'], B)
            if row['engineering_issues'] or issues:
                errors.append(dict(id=row['id'], errors=issues, stored_errors=row['engineering_issues']))
            if any(row.get(k) is not None for k in ('actual_outcomes', 'human_acceptance', 'human_score', 'human_reason')):
                errors.append(dict(id=row['id'], errors=['POPULATED_DOWNSTREAM_FIELDS']))
            causal = check_case(context, row, context['A'], B)
            component_count += len(causal)
            causal_errors.extend(r for r in causal if not r['passed'])
            for child in row['components']:
                if child['event_relevance']['role'] == 'direct_event_request':
                    candidate_hits[(child['asset_id'], child.get('service_need_id'), mechanism(child['mechanism']),
                                    child.get('magnitude', {}).get('axis'))].append(row['id'])
        grouped[key]=annotated
        for e in domain['entries']:
            key_tuple = (e['asset_id'], e['need_id'], e['mechanism'], e['axis'])
            mechanisms.append(dict(household_id=key[0], date=key[1], **e,
                                   witness_ids=sorted(set(candidate_hits[key_tuple]))))
        dates.append(dict(household_id=key[0], date=key[1], candidates=len(grouped[key]),
                          task_counts=sorted({r['independent_units'] for r in grouped[key]}),
                          context_sha256=file_hash(path), A_sha256=digest(context['A'])))
        if index % 50 == 0:
            print(f'Independent literal/causal audit {index}/{len(contexts)}', flush=True)
    save(out / 'INDEPENDENT_ADMISSION.json', dict(passed=not errors and not causal_errors and not axis_errors,
         cases=len(rows), components=component_count, engineering_errors=errors, causal_errors=causal_errors,axis_errors=axis_errors))
    if errors or causal_errors or axis_errors:
        raise ValueError('INDEPENDENT_ADMISSION_FAILED;NO_RESAMPLING')
    matching = attainable_orders(rows)
    save(out / 'INDEPENDENT_MATCHING.json', matching)
    print('Starting '+cfg['method_revision']+' selection on all 500 slots', flush=True)
    answer = assign(rows, cfg)
    save(out / 'SELECTION.json', answer)
    validate_slots(rows, answer['selected_ids'], contexts)
    selected = set(answer['selected_ids'])
    byid = {r['id']: r for r in rows}
    metrics = summarize(rows, answer['selected_ids'])
    available = summarize(rows, list(byid))
    household_reports = []
    for bound in matching:
        home = bound['household_id']
        subset = [r for r in rows if r['household_id'] == home]
        new_home = summarize(subset, [i for i in answer['selected_ids'] if byid[i]['household_id'] == home])
        old_home = summarize(subset, [i for i in old['selected_ids'] if byid[i]['household_id'] == home])
        missing = sorted(set(bound['available_task_counts']) - new_home['task_counts'].keys())
        household_reports.append(dict(**bound, available=summarize(subset, [r['id'] for r in subset]),
            old=old_home, original_baseline=original_house_metrics[home],selected=new_home, missing_task_counts=missing,
            distinct_count_shortfall=bound['maximum_distinct_counts'] - len(new_home['task_counts']),
            missing_reason=None if not missing else 'date_slot_competition_or_unproved_solver_bound',
            absent_counts_not_proven_impossible=True,
            available_dates_by_count={k: sorted({r['date'] for r in subset if r['independent_units'] == k}) for k in bound['available_task_counts']}))
    for date in dates:
        candidates = grouped[(date['household_id'], date['date'])]
        chosen = next(r for r in candidates if r['id'] in selected)
        date.update(selected_id=chosen['id'], selected_task_count=chosen['independent_units'],
                    old_selected_id=next(r['id'] for r in candidates if r['id'] in set(old['selected_ids'])),
                    changed_from_old=chosen['id'] not in old['selected_ids'], **tail_flags(chosen))
    for entry in mechanisms:
        entry['selected_witness_ids'] = sorted(selected.intersection(entry['witness_ids']))
        entry['gap'] = ('structure_inapplicable' if entry['status'] == 'inapplicable' else
                        'evidence_insufficient' if entry['status'] == 'unknown' else
                        'search_or_generation_unresolved' if not entry['witness_ids'] else
                        'ten_slot_selection_tradeoff' if not entry['selected_witness_ids'] else None)
    mechanism_summary = dict(statuses=dict(Counter(e['status'] for e in mechanisms)),
        potential=sum(e['status'] == 'potential' for e in mechanisms),
        witnessed=sum(e['status'] == 'potential' and bool(e['witness_ids']) for e in mechanisms),
        selected=sum(e['status'] == 'potential' and bool(e['selected_witness_ids']) for e in mechanisms),
        gaps=dict(Counter(e['gap'] for e in mechanisms if e['gap'])))
    targets = [c for block in answer['blocks'] for c in block['coverage']]
    deficits = [c for c in targets if c['deficit']]
    generation = read(collection / 'GENERATION.json')
    interactions = Counter()
    for record in generation:
        interactions.update(record['interaction_status'])
    # Replay the same deterministic optimization; not an alternative seed or a best-of run.
    print('Checking input-order replay on all 500 slots', flush=True)
    replay = assign(list(reversed(rows)), cfg)
    save(out / 'REPLAY_SELECTION.json', replay)
    replay_equal = set(replay['selected_ids']) == selected
    changed_sources = [p for p, h in pins.items() if file_hash(p) != h]
    changed_protected = [p for p, h in protected.items() if file_hash(p) != h]
    achieved = all(h['distinct_count_shortfall'] == 0 for h in household_reports)
    result = dict(schema='eb.frozen50_shadow_selection.v1',
        passed=achieved and replay_equal and not changed_sources and not changed_protected,
        scope='full original 50-household/500-date reselection;candidate-conditioned coverage,not new production',
        method_revision=cfg['method_revision'], source_core_sha256=code_hash(), seed=cfg['seed'],
        households=len(household_reports), original_dates=len(contexts), candidate_rows=len(rows),
        available=available, old=old_metrics, comparison_reinterpreted=summarize(rows,old['selected_ids']),selected=metrics,
        changed_date_choices=sum(d['changed_from_old'] for d in dates),
        all_households_achieve_independent_maximum=achieved,
        exact_count_deficits=sum(h['distinct_count_shortfall'] for h in household_reports),
        original_input_mechanisms=mechanism_summary,
        selection_targets=len(targets), selection_target_deficits=len(deficits),
        frozen_generation_interactions=dict(interactions),
        original_engineering_diagnostic_requests=sum(r['engineering'] for r in generation),
        independent_engineering_errors=len(errors), independent_causal_errors=len(causal_errors),
        independent_axis_errors=len(axis_errors),
        input_order_replay_equal=replay_equal,
        protected_files_checked=len(protected), protected_files_changed=changed_protected,
        source_files_checked=len(pins), source_files_changed=changed_sources,
        solver=[b['solver'] for b in answer['blocks']],
        semantic_repeat_excess=sum(b['semantic_repeat_excess'] for b in answer['blocks']),
        full_catalogue_retained=True, old_results_preserved=True, new_A_or_B_generated=False,
        outcome_proportions_prescribed=False, reseeding=False, actual_outcomes_used=False,
        unknown_response_not_observed_failure=True, physical_runs=0, online_changed=False,
        thousand_started=False, wall_seconds=time.monotonic()-start)
    if cfg['method_revision']=='delivery_v2_11':
        from .axis_acceptance import dimensions
        result['axis_dimensions']=dict(catalogue=dimensions(rows),selected=dimensions([byid[i] for i in selected]),
            comparison_selected=dimensions([byid[i] for i in old['selected_ids']]))
        save(out/'ANNOTATED_CANDIDATES.json.gz',rows)
    save(out / 'HOUSEHOLDS.json', household_reports)
    save(out / 'DATES.json', dates)
    save(out / 'INPUT_MECHANISMS.json.gz', mechanisms)
    save(out / 'SELECTION_DEFICITS.json', deficits)
    save(out / 'RESULT.json', result)
    write_csv(out / 'HOUSEHOLDS.csv', [dict(household_id=h['household_id'], dates=h['date_slots'],
        available_counts=';'.join(map(str, h['available_task_counts'])),
        selected_counts=';'.join(f'{k}:{v}' for k, v in h['selected']['task_counts'].items()),
        old_counts=';'.join(f'{k}:{v}' for k, v in h['old']['task_counts'].items()),
        missing_counts=';'.join(map(str, h['missing_task_counts'])),
        maximum_distinct=h['maximum_distinct_counts'], shortfall=h['distinct_count_shortfall'],
        **h['selected']['tails']) for h in household_reports])
    write_csv(out / 'DATES.csv', dates)
    return dict(passed=result['passed'], households=len(household_reports), dates=len(dates),
                candidate_rows=len(rows), task_counts=metrics['task_counts'], tails=metrics['tails'])


if __name__ == '__main__':
    p = argparse.ArgumentParser()
    p.add_argument('--protocol', required=True)
    p.add_argument('--out', required=True)
    a = p.parse_args()
    print(run(a.protocol, a.out))
