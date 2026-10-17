"""Revise input opportunities only for the 500 old identical-command requests."""
import argparse, collections, shutil
from concurrent.futures import ProcessPoolExecutor
from common import *
from material_opportunities import select_request
from event_proposals import make
from classify import classify, INTENT_PROPOSAL_KEYS, INTENT_CHANGE_KEYS
from assess import assess, integrity
from events import response_reference
from temporal import event_relations


def signals(plan, w):
    result = {}
    for d in w['parameter_pack']['devices']:
        if 'ac' not in d['types']: continue
        controls = [x for x in plan['controls'] if x['kind'] == 'ac_setpoint' and x['asset_id'] == d['asset_id']]
        channels = {k: [] for k in ('available', 'fan_mode', 'heat_sp', 'cool_sp')}
        for t in range(-1440, 4320, 10):
            x = next((x for x in controls if x['start_min'] <= t < x['end_min']), None)
            for key, value in [('available', int(x is not None)), ('fan_mode', x.get('fan_operating_mode', 0) if x else 0),
                               ('heat_sp', x['heating_setpoint_C'] if x else 5.), ('cool_sp', x['cooling_setpoint_C'] if x else 50.)]:
                channels[key].append(value)
        result[d['asset_id']] = channels
    return result


def plan_requests(rows):
    noids = {r['case_id'] for r in read(SOURCE_B / 'NO_COMMAND_CHANGE_CASES.json')['records']}
    result = {}
    for row in rows:
        if not any(r['case_id'] in noids for r in row['rounds']): continue
        family_counts = collections.Counter()
        pairs = {r['case_id']: read(SOURCE_B / r['path']) for r in row['rounds']}
        for old in pairs.values(): family_counts.update(old['proposal']['requested_portfolio_families'])
        w = None
        for rr in row['rounds']:
            if rr['case_id'] not in noids: continue
            old = pairs[rr['case_id']]
            if w is None: w = read(A_STAGE / old['A_source']['world_path'])
            choice = select_request(w, old, old['proposal']['input_design_assignment'], family_counts)
            result[rr['case_id']] = choice
            if choice: family_counts[choice['family']] += 1
    if set(result) != noids: raise ValueError('NOT_ALL500_REVIEWED')
    return {'schema': 'eb.material_input_revision_plan.v50', 'assignments': result,
            'planned_before_any_new_B_candidate': True, 'old_command_equivalence_scopes_revision': True,
            'physical_response_constraint_outcome_or_acceptance_used': False,
            'no_minimum_changed_count_or_bad_case_quota': True}


def one(job):
    row, requests, run, sig = job
    run = Path(run); hid = row['household_id']; output = run / 'records' / (hid + '.json')
    if output.exists(): return read(output)
    try:
        rounds = []; audit = []; world = None
        for index, rr in enumerate(row['rounds']):
            source = SOURCE_B / rr['path']
            if sha(source) != rr['sha256']: raise ValueError('SOURCE_PAIR_CHANGED')
            inherited = {**rr, 'path': '../' + SOURCE_B.name + '/' + rr['path'],
                         'inherited_B49_pair': True, 'source_B49_sha256': rr['sha256']}
            choice = requests.get(rr['case_id'])
            if choice is None:
                rounds.append(inherited)
                if rr['case_id'] in requests: audit.append({'case_id': rr['case_id'], 'status': 'retained_routine_or_no_supported_A_opportunity'})
                continue
            old = read(source)
            if old['classification']['actual_actions']['any_command_change']: raise ValueError('CHANGED_B_SELECTED_FOR_REPAIR')
            if world is None:
                path = A_STAGE / old['A_source']['world_path']
                if sha(path) != old['A_source']['world_sha256']: raise ValueError('A_WORLD_CHANGED')
                world = read(path)
            context = {**old, 'input_design_assignment': choice}
            candidate_checks = []
            def observe(level, candidate):
                errors = integrity(world, context, candidate)
                if errors: raise ValueError('CANDIDATE_INTEGRITY:' + canonical(errors))
                candidate_checks.append({'level': LEVELS[level], 'command_sha256': digest(candidate), 'integrity_errors': errors})
            plan, proposal = make(world, context, index, candidate_observer=observe)
            if proposal['same_command_as_A']:
                # An input opportunity can still collapse at the requested dose.
                # No stronger dose, retry, or second mechanism is chosen after B.
                rounds.append(inherited)
                audit.append({'case_id': rr['case_id'], 'status': 'retained_selected_request_still_unchanged',
                              'directive': choice, 'candidate_checks': candidate_checks})
                continue
            pair = copy.deepcopy(old)
            check = assess(world, context, plan)
            if check['integrity_errors']: raise ValueError('GENERATED_INVALID_REQUEST')
            pair.update(schema='eb.alternative_pair.v50', B=plan, proposal=proposal,
                        B_frozen_sha256=digest(plan), assessment_B=check,
                        HVAC_signals_B=signals(plan, world),
                        VPP_response_reference=response_reference(world, context, plan, old['VPP_events'], check),
                        event_relations=event_relations(context, plan, old['VPP_events']),
                        source_B={'stage': SOURCE_B.name, 'case_path': rr['path'], 'case_sha256': rr['sha256'],
                                  'seal_sha256': read(OUT / 'INPUT_LOCK.json')['source_B_seal_sha256']},
                        rules_sha256=sig, source_generation_rules_sha256=sig,
                        classification_only_update=False,
                        selection_or_regeneration_based_on_B_outcome='old_identical_commands_only;not_VPP_delivery_feasibility_or_acceptance')
            pair['classification'] = classify(pair, world)
            pair['proposal']['raw_generated_proposal_sha256'] = digest(proposal)
            for key in INTENT_PROPOSAL_KEYS: pair['proposal'].pop(key, None)
            for change in pair['proposal']['changes']:
                for key in INTENT_CHANGE_KEYS: change.pop(key, None)
            pair['proposal']['classification_record'] = 'classification'
            pair['material_revision'] = {'source_comparison_group': 'identical_commands',
                                         'A_input_directive': choice, 'all_original_demands_events_and_actions_retained': True,
                                         'stronger_dose_or_new_candidate_retry_after_results': False}
            pair.pop('pair_content_sha256', None); pair['pair_content_sha256'] = digest(pair)
            path = run / 'pairs' / hid / (old['date'] + '.json'); save(path, pair)
            rounds.append({**rr, 'path': rel(path), 'sha256': sha(path), 'inherited_B49_pair': False,
                           'source_B49_sha256': rr['sha256'], 'mechanism': proposal['realized_mechanism'],
                           'intensity': proposal['intensity_design'],
                           'given_constraints_feasible': check['given_constraints_feasible'],
                           'comparison_group': pair['classification']['actual_actions']['comparison_group']})
            audit.append({'case_id': rr['case_id'], 'status': 'revised_from_supported_A_opportunity',
                          'directive': choice, 'candidate_checks': candidate_checks,
                          'given_constraint_conflicts_kept': check['constraint_flags']})
        result = {**row, 'rounds': rounds, 'source_B_record_sha256': digest(row), 'source_B_stage': SOURCE_B.name}
        save(run / 'revision_log' / (hid + '.json'), {'household_id': hid, 'cases': audit, 'no_filler_actions': True})
    except Exception as error:
        result = {'household_id': hid, 'type': row['type'], 'passed': False, 'error': str(error)}
    save(output, result)
    return result


def main():
    parser = argparse.ArgumentParser(); parser.add_argument('--workers', type=int, default=4)
    args = parser.parse_args(); verify_inputs(); sig = rules_id(); run = OUT / 'runs' / sig[:16]
    if (OUT / 'FINAL_SEAL.json').exists(): raise ValueError('ALREADY_SEALED')
    for p in list((OUT / 'code').glob('*.py')) + [OUT / 'INPUT_LOCK.json', OUT / 'GENERATION_RULES.json', OUT / 'USER_DECISIONS.json']:
        dest = run / 'source_snapshot' / p.name; dest.parent.mkdir(parents=True, exist_ok=True); shutil.copyfile(p, dest)
    rows = read(SOURCE_B / 'PAIR_BINDINGS10000.json')['records']
    requests = plan_requests(rows); save(OUT / 'INPUT_REVISION_PLAN.json', requests)
    save(run / 'RUN.json', {'rules_sha256': sig, 'source_B': SOURCE_B.name, 'source_A': A_STAGE.name,
                           'original_9500_changed_B_frozen': True, 'all10000_preserved': True})
    records = []
    with ProcessPoolExecutor(max_workers=args.workers) as pool:
        for r in pool.map(one, [(r, requests['assignments'], str(run), sig) for r in rows]):
            records.append(r)
            if len(records) % 100 == 0: print({'households': len(records), 'errors': sum(not r['passed'] for r in records)}, flush=True)
    if rules_id() != sig: raise ValueError('CODE_CHANGED_DURING_BUILD')
    errors = [r for r in records if not r['passed']]
    save(run / 'BUILD_REVIEW.json', {'households': len(records), 'errors': errors, 'rules_sha256': sig})
    if errors: print(canonical(errors[:10])); raise SystemExit(2)
    save(OUT / 'PAIR_BINDINGS10000.json', {'schema': 'eb.alternative_bindings.v50', 'rules_sha256': sig,
                                        'households': 1000, 'cases': 10000, 'source_B': SOURCE_B.name,
                                        'records': records, 'all_cases_retained_in_total_dataset': True,
                                        'inherited_cases_are_exact_B49_source_references': True})
    ids = {r['household_id'] for r in read(MASTER / 'SUBSET50.json')['records']}
    subset = [r for r in records if r['household_id'] in ids]
    save(OUT / 'SUBSET50.json', {'schema': 'eb.alternative_subset.v50', 'records': subset,
                               'type_counts': dict(collections.Counter(r['type'] for r in subset)),
                               'same_master_household_ids': True, 'same_pairs_and_hashes': True,
                               'separate_generation': False})
    print(canonical({'built': OUT.name, 'households': 1000, 'cases': 10000, 'rules_sha256': sig}))


if __name__ == '__main__': main()
