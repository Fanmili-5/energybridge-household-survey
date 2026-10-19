"""Outcome-blind, household-balanced sampling of a finite request catalogue.

Strata and quotas are experimental settings, not estimated population frequencies.
The priority algorithm is specified here rather than delegated to versioned PRNGs.
"""
import copy
import datetime as dt
import itertools
from collections import Counter, defaultdict
from pathlib import Path
from .common import bound, canonical, code_hash, digest, read, save, seal, sha, verify
from .generate import DEFAULT_RULES
from .model import apply, plan_commands, program_issues, request_issues
from .opportunity import EPSILON as PROFILE_EPSILON

FEATURES = {'family', 'scope', 'admission', 'direction', 'cost_sign', 'event_sign', 'handling', 'axis', 'dose', 'composition', 'duration', 'opportunity', 'joint_support', 'day_type', 'event_direction',
            'unit_count', 'family_count', 'same_family_jobs', 'power_risk'}
SERVICE_FAILURES = {'B_EV_departure_target', 'B_hot_water_service',
                    'B_service_execution', 'B_service_completeness', 'B_declared_comfort', 'B_electrical_supply'}
STRESS_STATIC = ['CHARGE_EXCEEDS_ORIGINAL_CONNECTION']
STRESS_ADMISSIONS = {'declared_EV_shortfall_stress', 'declared_site_capacity_stress'}
SITE_STRESS_STATIC = {'SITE_KNOWN_PROFILE_EXCEEDS_SUPPLY', 'SITE_CAPACITY_NOT_CERTIFIED'}
SIGN_EPSILON = 1e-9


def require(condition, message):
    if not condition:
        raise ValueError(message)


def normalized_commands(plan):
    """Ignore ordering/internal IDs and coalesce adjacent identical controls only."""
    result = plan_commands(plan)
    groups = defaultdict(list)
    for row in result['controls']:
        row.pop('_ab_control_id', None)
        payload = {k: v for k, v in row.items() if k not in ('start_min', 'end_min')}
        groups[canonical(payload)].append(row)
    controls = []
    for key in sorted(groups):
        merged = []
        for row in sorted(groups[key], key=lambda r: (r['start_min'], r['end_min'])):
            if merged and merged[-1]['end_min'] == row['start_min']:
                merged[-1]['end_min'] = row['end_min']
            else:
                merged.append(copy.deepcopy(row))
        controls.extend(merged)
    result['controls'] = sorted(controls, key=canonical)
    for kind in ('tasks', 'operations'):
        result[kind] = sorted(result[kind], key=canonical)
    return result


def command_hash(plan):
    return digest(normalized_commands(plan))


def sign(value):
    # Experimental reporting resolution, not a test of statistical significance.
    return 'unknown' if value is None else 'positive' if value > SIGN_EPSILON else 'negative' if value < -SIGN_EPSILON else 'zero'


def validate_plan(plan):
    required = {'schema', 'seed', 'variants', 'strata', 'coverage_axes'}
    require(required <= set(plan) and not set(plan) - required - {'response_checks', 'stress_admissions'}, 'UNKNOWN_TAIL_PLAN_FIELDS')
    if 'stress_admissions' in plan:
        require(isinstance(plan['stress_admissions'], list) and len(set(plan['stress_admissions'])) == len(plan['stress_admissions'])
                and set(plan['stress_admissions']) <= STRESS_ADMISSIONS, 'INVALID_STRESS_ADMISSIONS')
    require(plan['schema'] == 'eb.ab_tail_plan.v1' and type(plan['seed']) is int, 'INVALID_TAIL_PLAN')
    require(isinstance(plan['variants'], list) and plan['variants'], 'EMPTY_TAIL_VARIANTS')
    names = []
    for variant in plan['variants']:
        require(set(variant) == {'id', 'overrides'} and isinstance(variant['id'], str) and variant['id']
                and set(variant['overrides']) <= set(DEFAULT_RULES), 'INVALID_TAIL_VARIANT')
        names.append(variant['id'])
    require(len(names) == len(set(names)), 'DUPLICATE_TAIL_VARIANT')
    require(plan['strata'] and len({s['id'] for s in plan['strata']}) == len(plan['strata']), 'EMPTY_OR_DUPLICATE_STRATA')
    for row in plan['strata']:
        require(set(row) == {'id', 'match', 'households', 'per_household', 'required'}
                and isinstance(row['id'], str) and row['id'] and isinstance(row['match'], dict)
                and set(row['match']) <= FEATURES, 'INVALID_TAIL_STRATUM')
        require(all(isinstance(v, list) and v and all(isinstance(x, str) for x in v) for v in row['match'].values()), 'INVALID_TAIL_MATCH')
        require(type(row['required']) is bool and all(type(row[k]) is int and row[k] > 0 for k in ('households', 'per_household')), 'INVALID_TAIL_QUOTA')
    require(isinstance(plan['coverage_axes'], list) and len(set(plan['coverage_axes'])) == len(plan['coverage_axes'])
            and set(plan['coverage_axes']) <= FEATURES, 'INVALID_COVERAGE_AXES')
    if 'response_checks' in plan:
        checks = plan['response_checks']
        require(set(checks) in ({'minimum_changed_kinds'}, {'minimum_changed_kinds', 'maximum_supported_no_response_fraction'}) and isinstance(checks['minimum_changed_kinds'], list)
                and bool(checks['minimum_changed_kinds'])
                and len(set(checks['minimum_changed_kinds'])) == len(checks['minimum_changed_kinds'])
                and set(checks['minimum_changed_kinds']) <= {'washer', 'dryer', 'dishwasher', 'ev', 'ac', 'water_heater'}, 'INVALID_RESPONSE_CHECKS')
        if 'maximum_supported_no_response_fraction' in checks:
            value = checks['maximum_supported_no_response_fraction']
            require(type(value) in (int, float) and 0 <= value <= 1, 'INVALID_RESPONSE_FRACTION')


def describe(context, plan_B, children, issues, unchanged=None, stress_admissions=None):
    allowed_stress = {'declared_EV_shortfall_stress'} if stress_admissions is None else set(stress_admissions)
    gate = request_issues(context, plan_B)
    families = sorted({r['family'] for r in children})
    # Authority and past/identity gates can never be waived by a stress label.
    authority = context['authority']['assets']
    gate += ['TARGET_CONTROL_NOT_AUTHORIZED' for r in children if not authority[r['asset_id']]['target_control_authorized']]
    for row in children:
        if row['family'] in ('washer', 'dishwasher'):
            issues += program_issues(context, plan_B, row['factors']['need_id'])
    issues = sorted(set(issues + gate))
    if unchanged is None:
        unchanged = command_hash(context['A']) == command_hash(plan_B)
    if not issues:
        admission = 'normal'
    elif 'declared_EV_shortfall_stress' in allowed_stress and not gate and not unchanged and families == ['ev'] and issues == STRESS_STATIC and all(
            r['factors'].get('prediction_energy_shortfall_kWh', 0) > 1e-8 for r in children):
        admission = 'declared_EV_shortfall_stress'
    elif ('declared_site_capacity_stress' in allowed_stress and context.get('electrical') and not gate and not unchanged
          and set(issues) <= SITE_STRESS_STATIC):
        admission = 'declared_site_capacity_stress'
    else:
        admission = 'static_diagnostic'
    known = all(r['prediction']['delta_cost'] is not None for r in children)
    event_known = all(r['prediction']['aligned_event_kWh'] is not None for r in children)
    def combined(key, default):
        values = {r['factors'][key] for r in children if key in r['factors']}
        return next(iter(values)) if len(values) == 1 else 'mixed' if values else default
    features = {'family': 'control' if unchanged else families[0] if len(children) == 1 else 'joint',
                'scope': 'control' if unchanged else 'single' if len(children) == 1 else 'joint',
                'admission': admission, 'direction': combined('direction', 'not_thermal'),
                'handling': combined('handling_mode', 'not_program'), 'axis': combined('thermal_axis', 'not_thermal'),
                'cost_sign': sign(sum(r['prediction']['delta_cost'] for r in children) if known else None),
                'event_sign': sign(sum(r['prediction']['aligned_event_kWh'] for r in children) if event_known else None)}
    features['dose'] = ('control' if unchanged else 'joint' if len(children) != 1 else
                        'thermal_' + format(max(r['factors']['setpoint_delta_C'] for r in children), 'g') + 'C'
                        if families[0] in ('ac', 'water_heater') else
                        'EV_' + str(max(r['factors']['ev_delay_min'] for r in children)) + 'min'
                        if families == ['ev'] else
                        'program_' + str(max(r['factors']['program_shift_min'] for r in children)) + 'min')
    features['composition'] = '+'.join(families) if families else 'control_or_preserved'
    features['duration'] = str(combined('available_duration_min', 'not_thermal'))
    statuses = [r['opportunity']['status'] for r in children]
    features['opportunity'] = ('control' if unchanged else 'supported' if statuses and all(s == 'supported' for s in statuses)
                               else 'exploratory' if statuses else 'preserved_failure')
    features['joint_support'] = ('control' if unchanged else 'single' if len(children) <= 1 else
                                 'all_supported' if all(s == 'supported' for s in statuses) else
                                 'mixed' if any(s == 'supported' for s in statuses) else 'all_exploratory')
    features['day_type'] = 'weekend' if dt.date.fromisoformat(context['date']).weekday() >= 5 else 'weekday'
    directions = {e['direction'] for e in context['events']}
    features['event_direction'] = next(iter(directions)) if len(directions) == 1 else 'mixed' if directions else 'none'
    features['unit_count'] = str(len(children))
    features['family_count'] = str(len(families))
    jobs = Counter(r['family'] for r in children if r['family'] in ('washer', 'dishwasher', 'ev'))
    features['same_family_jobs'] = 'yes' if any(n > 1 for n in jobs.values()) else 'no'
    features['power_risk'] = ('known_profile_overload' if 'SITE_KNOWN_PROFILE_EXCEEDS_SUPPLY' in issues else
                              'uncertified_upper_bound' if 'SITE_CAPACITY_NOT_CERTIFIED' in issues else 'none')
    return features, issues


def catalogue(contexts, results, stress_admissions=None):
    """All variants and joint requests; no policy winner or physical B is an input."""
    unique = {}
    context_hashes = {k: digest(c) for k, c in contexts.items()}
    A_hashes = {k: command_hash(c['A']) for k, c in contexts.items()}
    for variant, by_case in sorted(results.items()):
        for case_id, result in sorted(by_case.items()):
            context = contexts[case_id]
            require(result['context_sha256'] == context_hashes[case_id] and result['final_B_outcomes_used_for_selection'] is False,
                    'TAIL_GENERATION_BINDING_MISMATCH')
            rows = result['candidates'] + result['joint_candidates']
            require(all(r.get('actual_outcomes') is None and r.get('human_acceptance') is None for r in rows)
                    and result['human_acceptance'] is None, 'TAIL_DOWNSTREAM_OUTCOMES_FORBIDDEN')
            baseline = plan_commands(context['A'])
            for c in baseline['controls']:
                c['_ab_control_id'] = digest(c)
            singles = {r['id']: r for r in result['candidates']}
            mode = result['assignment']['mode']
            requests = []
            if mode == 'fresh_candidates':
                requests = [(r, [r], {'candidate_id': r['id']}) for r in result['candidates']]
                requests += [(r, [singles[i] for i in r['candidate_ids']], {'joint_id': r['id']}) for r in result['joint_candidates']]
            if mode != 'preserved_failure_replay':
                requests += [({'patches': [], 'static_issues': []}, [], {'baseline_control': True})]
            else:
                # Frozen original failures remain diagnostic; never replaced by a new optimum.
                requests = [({'patches': [], 'static_issues': ['PRESERVED_FAILURE_REQUIRES_ORIGINAL_AUDIT']}, [], {'preserved_failure': True})]
            for request, children, override in requests:
                B = context['retained_B_request'] if mode == 'preserved_failure_replay' else apply(baseline, request['patches'])
                B_hash = command_hash(B)
                features, issues = describe(context, B, children, list(request['static_issues']), A_hashes[case_id] == B_hash, stress_admissions)
                ident = digest({'context_sha256': context_hashes[case_id], 'B_commands_sha256': B_hash})
                alias = {'variant': variant, 'case_id': case_id, 'override': {**override, 'expected_static_issues': request['static_issues']},
                         'candidate_factors': [r['factors'] for r in children],
                         'opportunity_evidence': [r['opportunity'] for r in children]}
                if ident not in unique:
                    unique[ident] = {'sample_id': ident, 'case_id': case_id, 'household_id': context['household_id'],
                                     'split_group_id': context['household_id'], 'context_sha256': context_hashes[case_id],
                                     'B_commands_sha256': B_hash, 'features': features,
                                     'static_issues': issues, 'aliases': []}
                old = unique[ident]
                require(old['features'] == features and old['static_issues'] == issues, 'CONFLICTING_EQUIVALENT_REQUEST_ALIASES')
                old['aliases'].append(alias)
    return sorted(unique.values(), key=lambda r: r['sample_id'])


def sample_catalogue(rows, plan):
    validate_plan(plan)
    require(len({r['sample_id'] for r in rows}) == len(rows), 'DUPLICATE_CATALOGUE_EXECUTION')
    selected, coverage, assigned = [], [], set()
    for stratum in plan['strata']:
        matching = [r for r in rows if all(r['features'][k] in v for k, v in stratum['match'].items())]
        pool = [r for r in matching if r['sample_id'] not in assigned]
        assigned.update(r['sample_id'] for r in pool)  # first matching stratum owns the unit, including unselected ones
        households = defaultdict(list)
        for row in pool:
            households[row['household_id']].append(row)
        def rank(stage, ident):
            return digest(['eb.tail.priority.v1', plan['seed'], stratum['id'], stage, ident])
        chosen_h = sorted(households, key=lambda h: (rank('household', h), h))[:stratum['households']]
        hit, hh_counts = 0, []
        for h in chosen_h:
            candidates = sorted(households[h], key=lambda r: (rank('request', r['sample_id']), r['sample_id']))
            chosen = candidates[:stratum['per_household']]
            hh_counts.append({'household_id': h, 'available': len(candidates), 'selected': len(chosen)})
            for row in chosen:
                selected.append({**copy.deepcopy(row), 'stratum': stratum['id'],
                    'nominal_frame_inclusion_probability': len(chosen_h) / len(households) * len(chosen) / len(candidates),
                    'population_weight': None, 'actual_outcomes_used_for_selection': False})
            hit += len(chosen)
        wanted = stratum['households'] * stratum['per_household']
        coverage.append({'stratum': stratum['id'], 'required': stratum['required'], 'match': stratum['match'],
                         'matched_unique': len(matching), 'assigned_unique': len(pool), 'available_households': len(households),
                         'requested': wanted, 'selected': hit, 'deficit': wanted - hit, 'households': hh_counts,
                         'passed': hit == wanted})
    return {'records': selected, 'coverage': coverage,
            'selection_coverage_passed': all(r['passed'] for r in coverage if r['required']),
            'unassigned_unique': len(rows) - len(assigned), 'no_outcome_reselection': True}


def interactions(rows, selected, axes):
    """Finite-catalogue marginal/pairwise measurement, not a covering-array claim."""
    tables = []
    for size in (1, 2):
        for keys in itertools.combinations(axes, size):
            available = Counter(tuple(r['features'][k] for k in keys) for r in rows)
            hits = Counter(tuple(r['features'][k] for k in keys) for r in selected)
            tables += [{'axes': list(keys), 'levels': list(levels), 'available_unique': count,
                        'selected_unique': hits[levels]} for levels, count in sorted(available.items())]
    return tables


def sample_tail(context_root, plan_path, out):
    from .__main__ import build_batch
    context_root, out = Path(context_root), Path(out)
    verify(context_root)
    plan = read(plan_path); validate_plan(plan)
    batch = read(context_root / 'BATCH.json')
    contexts = {r['case_id']: read(bound(context_root, r['context'])) for r in batch['records']}
    require(len(contexts) == len(batch['records']), 'DUPLICATE_CASE_ID')
    require(all(c['reference']['information_set']['mode'] == 'offline_full_A_counterfactual' for c in contexts.values()),
            'TAIL_PHYSICAL_FRAME_REQUIRES_EXPLICIT_OFFLINE_A')
    out.mkdir(parents=True, exist_ok=False)
    save(out / 'PLAN.json', plan)
    variants = {}
    for v in plan['variants']:
        name = digest(v['id'])[:24]
        rules = out / ('rules/' + name + '.json'); save(rules, v['overrides'])
        folder = out / ('variants/' + name)
        build_batch(context_root / 'BATCH.json', folder, rules)
        manifest = verify(folder)
        variants[v['id']] = {r['case_id']: read(bound(folder, r['path'])) for r in manifest['records']}
    rows = catalogue(contexts, variants, plan.get('stress_admissions'))
    selection = sample_catalogue(rows, plan)
    selection.update({'schema': 'eb.ab_tail_selection.v1', 'plan_sha256': digest(plan),
        'response_checks': plan.get('response_checks'),
        'contexts_manifest_sha256': sha(context_root / 'MANIFEST.json'), 'code_sha256': code_hash(),
        'unique_catalogue_size': len(rows), 'raw_aliases': sum(len(r['aliases']) for r in rows),
        'interaction_coverage': interactions(rows, selection['records'], plan['coverage_axes']),
        'representative_population_sample': False, 'human_acceptance_inferred': False})
    save(out / 'CATALOGUE.json.gz', rows); save(out / 'SELECTION.json', selection)
    seal(out, {'schema': selection['schema'], 'contexts_manifest_sha256': selection['contexts_manifest_sha256'],
               'selection_sha256': sha(out / 'SELECTION.json'), 'code_sha256': code_hash()})
    return {k: v for k, v in selection.items() if k not in ('records', 'interaction_coverage')}


def classify_result(sample, report):
    """Validity is separate from benefits and service success; failed B is retained."""
    failures = set(report.get('failed_checks', []))
    integrity = (report.get('case_id') == sample['case_id'] and report.get('readback_status') == 'complete'
                 and 'failed_checks' in report
                 and report.get('A_reference_comparison', {}).get('passed') is True
                 and report.get('engine_status') == {'A': 'completed', 'B': 'completed'}
                 and report.get('actual_results_used_for_reselection') is False
                 and report.get('human_acceptance') is None and not failures - SERVICE_FAILURES)
    if not integrity:
        return {'status': 'quarantined_data_or_model_error', 'coverage_credit': False, 'failed_checks': sorted(failures)}
    if sample['features']['admission'] == 'declared_EV_shortfall_stress':
        valid = failures == {'B_EV_departure_target'}
        return {'status': 'declared_service_failure_observed' if valid else 'stress_expectation_missed',
                'coverage_credit': valid, 'failed_checks': sorted(failures)}
    if sample['features']['admission'] == 'declared_site_capacity_stress':
        return {'status': 'capacity_service_failure_retained' if 'B_electrical_supply' in failures else 'capacity_stress_executed_without_overload',
                'coverage_credit': True, 'failed_checks': sorted(failures)}
    return {'status': 'observed_service_failure_retained' if failures else 'executed_valid',
            'coverage_credit': True, 'failed_checks': sorted(failures)}


def coverage_report(selection_root, observations):
    selection_root = Path(selection_root); verify(selection_root)
    selection = read(selection_root / 'SELECTION.json')
    require(len({r['sample_id'] for r in observations}) == len(observations), 'DUPLICATE_EXECUTION_OBSERVATION')
    observed = {r['sample_id']: r for r in observations}
    require(set(observed) <= {r['sample_id'] for r in selection['records']}, 'UNSELECTED_EXECUTION_OBSERVATION')
    records = []
    for sample in selection['records']:
        observation = observed.get(sample['sample_id'])
        if sample['features']['admission'] == 'static_diagnostic':
            require(observation is None, 'STATIC_DIAGNOSTIC_MUST_NOT_EXECUTE')
            assessment = {'status': 'static_failure_retained_nonexecuting', 'coverage_credit': True}
        elif observation is None:
            assessment = {'status': 'missing_execution', 'coverage_credit': False}
        else:
            if observation.get('exported_B_commands_sha256') is None:
                require(observation['report'].get('readback_status') == 'incomplete', 'MISSING_EXPORTED_B_RECEIPT')
            else:
                require(observation['exported_B_commands_sha256'] == sample['B_commands_sha256'], 'SELECTED_B_EXECUTION_MISMATCH')
            assessment = classify_result(sample, observation['report'])
        records.append({'sample_id': sample['sample_id'], 'case_id': sample['case_id'], 'stratum': sample['stratum'],
                        'features': sample['features'], **assessment,
                        'observation': observation, 'human_acceptance': None})
    table = []
    for row in selection['coverage']:
        subset = [r for r in records if r['stratum'] == row['stratum']]
        credited = sum(r['coverage_credit'] for r in subset)
        table.append({**row, 'verified': credited, 'verification_deficit': row['requested'] - credited,
                      'passed': row['passed'] and credited == row['requested']})
    response = response_coverage(records, selection.get('response_checks'))
    return {'schema': 'eb.ab_tail_coverage.v1', 'passed': response['passed'] and bool(records) and all(r['passed'] for r in table if r['required'])
            and all(r['coverage_credit'] for r in records), 'coverage': table, 'records': records,
            'selection_manifest_sha256': sha(selection_root / 'MANIFEST.json'), 'no_outcome_reselection': True,
            'outcome_counts': dict(Counter(r['status'] for r in records)),
            'response_coverage': response,
            'selection_interaction_coverage': selection['interaction_coverage'],
            'population_prevalence_estimated': False, 'human_acceptance_inferred': False}


def _supported_target_assets(evidence, response):
    """Read the evidence for each target, independently of aggregate labels."""
    if 'children' in evidence:
        return set().union(*(_supported_target_assets(child, response) for child in evidence['children']))
    if 'asset_L1_kWh' in evidence:
        return {aid for aid, value in evidence['asset_L1_kWh'].items() if value > PROFILE_EPSILON}
    if evidence.get('status') == 'supported':
        return {evidence['asset_id']} if 'asset_id' in evidence else {r['asset_id'] for r in response['records']}
    return set()


def response_coverage(records, checks):
    kinds, patterns, fingerprints = Counter(), Counter(), set()
    reports, supported_targets, supported_no_response = [], 0, 0
    missing_supported = []
    missing_reports = []
    for row in records:
        report = (row.get('observation') or {}).get('report', {})
        response = report.get('targeted_response')
        if response is None:
            if checks is not None and row['coverage_credit'] and row['features'].get('admission') != 'static_diagnostic':
                missing_reports.append(row['sample_id'])
                reports.append({'sample_id': row['sample_id'], 'stratum': row['stratum'],
                                'opportunity': row['features'].get('opportunity'), 'response': None,
                                'error': 'TARGET_RESPONSE_REPORT_MISSING'})
            continue
        patterns[response['pattern']] += 1
        fingerprints.add((row['case_id'], response['B_native_trace_sha256']))
        # A device responding in a failed service arm is still a response;
        # service failures remain separately reported, never replaced.
        if row['coverage_credit']:
            kinds.update(r['kind'] for r in response['records'] if r['observable_response'])
            evidence = report.get('request_opportunity')
            if evidence:
                # Mixed joints and dependent program chains retain the support
                # of each asset; aggregate labels cannot erase this evidence.
                supported_assets = _supported_target_assets(evidence, response)
                measured = {r['asset_id']: r for r in response['records']}
                supported_targets += len(supported_assets)
                supported_no_response += sum(not measured[aid]['observable_response']
                                             for aid in supported_assets & measured.keys())
                missing_supported.extend({'sample_id': row['sample_id'], 'asset_id': aid}
                                         for aid in sorted(supported_assets - measured.keys()))
            elif row['features'].get('opportunity') == 'supported':
                supported_targets += len(response['records'])
                supported_no_response += sum(not r['observable_response'] for r in response['records'])
        reports.append({'sample_id': row['sample_id'], 'stratum': row['stratum'],
                        'opportunity': row['features'].get('opportunity'), 'response': response})
    required = (checks or {}).get('minimum_changed_kinds', [])
    missing = [k for k in required if not kinds[k]]
    bound = not missing_supported and not missing_reports
    fraction = supported_no_response / supported_targets if supported_targets and bound else None
    limit = (checks or {}).get('maximum_supported_no_response_fraction')
    fraction_passed = limit is None or (fraction is not None and fraction <= limit)
    return {'passed': not missing and bound and fraction_passed, 'required': checks is not None,
            'supported_target_count': supported_targets, 'supported_no_response_count': supported_no_response,
            'supported_target_response_binding_passed': bound,
            'missing_supported_target_responses': missing_supported,
            'missing_target_response_reports': missing_reports,
            'supported_no_response_fraction': fraction, 'maximum_supported_no_response_fraction': limit,
            'supported_response_fraction_passed': fraction_passed,
            'minimum_changed_kinds': required, 'missing_changed_kinds': missing,
            'actual_changed_kind_counts': dict(kinds), 'patterns': dict(patterns),
            'distinct_case_and_native_B_trajectories': len(fingerprints), 'records': reports,
            'no_outcome_reselection': True, 'all_selected_results_retained': True}
