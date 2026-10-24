"""Two same-role, same-hardware households; original twenty A/B pairs unchanged."""
import argparse
from collections import Counter
import copy
import gzip
import json
from pathlib import Path

from .core import HERE, digest, read, require, save, seal, sha
from .device_persona import generate_personas, render_family
from .portrait_inputs import from_formal
from .persona_checks import audit_case

EXAMPLES = ('ordinary-v6-0696', 'ordinary-v6-0756')


def validate(artifacts, before_root, output):
    artifacts, before_root, output = map(lambda p: Path(p).resolve(), (artifacts, before_root, output))
    require(not output.is_relative_to(artifacts) and not output.is_relative_to(before_root), 'OUTPUT_MUST_NOT_OVERWRITE_SOURCE')
    output.mkdir(parents=True, exist_ok=False)
    inputs = {}
    def load(path):
        inputs[str(path)] = sha(path)
        if str(path).endswith('.gz'):
            with gzip.open(path, 'rt') as f: return json.load(f)
        return read(path)
    methods = {str(p.relative_to(HERE)): sha(p) for p in HERE.glob('*.py')}
    methods.update({str(p.relative_to(HERE)): sha(p) for p in HERE.glob('*SOURCES.json')})
    methods.update({name: sha(HERE / name) for name in ('DEVICE_PERSONA_RULES.json', 'ENERGY_PORTRAIT_RULES.json')})
    release = artifacts / 'release-complete500-ui91-physics-v5-rounds'
    raw_root = artifacts / 'A-source-complete500-v1'
    context_root = artifacts / 'collection-complete500-v1/contexts'
    formal = load(release / 'FORMAL_RELEASE.json'); index = load(release / 'INDEX50.json')
    require(digest({k:v for k,v in formal.items() if k != 'release_sha256'}) == formal['release_sha256'], 'FORMAL_RELEASE_SIGNATURE')
    require(inputs[str(release / 'INDEX50.json')] == formal['files']['INDEX50.json'], 'FORMAL_INDEX_HASH')
    rows = {r['household_id']: r for r in load(raw_root / 'SUBSET50.json')['records']}
    records, audits, comparisons, soft_differences = [], [], [], []
    signatures, role_classes = [], []
    for hid in EXAMPLES:
        profile = load(release / 'public/households' / (hid + '.json'))
        require(inputs[str(release / 'public/households' / (hid + '.json'))] == index['profiles_sha256'][hid], 'FORMAL_PROFILE_HASH')
        source_row = rows[hid]; role_classes.append(source_row['type'])
        world = load(raw_root / source_row['A_world_path'])
        require(inputs[str(raw_root / source_row['A_world_path'])] == source_row['A_world_sha256'], 'HARDWARE_SOURCE_HASH')
        # Ignore only asset identity, room placement and operator. Preserve the
        # complete parameter object and model family, not just device categories.
        hardware = sorted(digest({k: d.get(k) for k in ('types', 'parameters', 'model_family', 'max_electric_kw')})
                          for d in world['parameter_pack']['devices'])
        signatures.append(digest(hardware))
        daymap, days, contexts, cases, protected = {}, [], [], [], []
        selected = [r for r in index['cases'] if r['household_id'] == hid]
        require(len(selected) == 10, 'TEN_ORIGINAL_DATES_REQUIRED')
        for row in selected:
            raw_row = next(r for r in source_row['cases'] if r['date'] == row['date'])
            raw = load(raw_root / raw_row['path'])
            require(inputs[str(raw_root / raw_row['path'])] == raw_row['sha256'], 'RAW_A_SOURCE_HASH')
            for d in raw['days']:
                a = d['activity']; value = {'date': d['date'], 'calendars': a['member_calendars'], 'operator_windows': a['operator_windows_min']}
                require(d['date'] not in daymap or daymap[d['date']] == value, 'NEIGHBOR_CALENDAR_CONFLICT')
                daymap[d['date']] = value
            days.append(daymap[row['date']])
            context = load(context_root / (hid + '__' + row['date'] + '.json.gz'))
            case = load(release / 'public' / row['path'])
            require(inputs[str(release / 'public' / row['path'])] == row['sha256'], 'FORMAL_CASE_HASH')
            require(context['source']['A_case_sha256'] == raw_row['sha256'] == case['bindings']['source_A_case_sha256'], 'A_LINEAGE_MISMATCH')
            contexts.append(context); cases.append(case)
            protected.append({'case_id': case['case_id'], 'plans_sha256': digest(case['plans']),
                              'calendar_sha256': digest(daymap[row['date']]),
                              'service_needs_sha256': digest(case['context']['needs']),
                              'outcomes_sha256': digest({k: case[k] for k in ('impact', 'physical_review', 'VPP_results', 'outcome_status')})})
        context = from_formal(profile, days, source_row['type'], contexts)
        original = digest(context)
        after = generate_personas(context)
        changed = copy.deepcopy(context); changed['plans'] = {'A': 'not read', 'B': 'not read'}
        changed['outcomes'] = 'not read'; changed['answers'] = 'not read'
        changed['days'] = changed['days'][-1:]
        require(after == generate_personas(changed), 'PREFERENCE_DEPENDS_ON_PLANS_LABELS_OR_SELECTED_DAY')
        require(original == digest(context), 'CONTEXT_WAS_CHANGED')
        before = load(before_root / (hid + '.json'))
        require(before['role'] == after['role'] and before['household_id'] == hid, 'BEFORE_IDENTITY_MISMATCH')
        require({(d['asset_id'], d['kind']) for d in before['devices']} == {(d['asset_id'], d['kind']) for d in after['devices']}, 'DEVICE_SET_CHANGED')
        require(before['context_evidence'] == after['context_evidence'], 'LIFE_CONTEXT_CHANGED')
        save(output / 'inputs' / (hid + '.json'), context)
        save(output / 'before' / (hid + '.json'), before)
        save(output / 'after' / (hid + '.json'), after)
        for suffix in ('brief.md', 'family.md'):
            src = before_root / (hid + '.' + suffix)
            inputs[str(src)] = sha(src)
            (output / 'before' / (hid + '.' + suffix)).write_text(src.read_text())
            (output / 'after' / (hid + '.' + suffix)).write_text(render_family(after, brief=suffix == 'brief.md'))
        pairs = [audit_case(case, c, profile, after, daymap) for case, c in zip(cases, contexts)]
        for case, findings in zip(cases, pairs):
            for d in after['devices']:
                if d['kind'] in ('washer', 'dishwasher') and d['inherited_preferences']['habit_clock_origin'] == 'EB_household_soft_reference':
                    reference_minute = round(d['inherited_preferences']['shared_reference']['preferred_h'] * 60)
                    for task in case['plans']['A']['tasks']:
                        if task['asset_id'] == d['asset_id'] and task['kind'] == d['kind'] and task['need_id'].startswith(case['date'] + ':') and task['start_min'] != reference_minute:
                            soft_differences.append({'case_id':case['case_id'], 'kind':d['kind'],
                                'A_start_min':task['start_min'], 'EB_soft_preferred_min':reference_minute,
                                'meaning':'new_declared_soft_preference_differs_from_original_A;not_engineering_error_or_observed_habit',
                                'A_changed':False})
                auth = d['authorization']
                if auth['member_confirmation_required_ids'] and any(x['asset_id'] == d['asset_id'] for x in case['changes']):
                    findings['findings'].append({'arm': 'B', 'category': 'needs_additional_consent',
                        'code': 'AFFECTED_MEMBER_CONFIRMATION_PENDING', 'asset_id': d['asset_id'],
                        'kind': d['kind'], 'member_ids': auth['member_confirmation_required_ids'],
                        'origin': 'experimental_member_consensus;not_human_rejection_label'})
        audits += pairs
        comparisons.append({'household_id': hid, 'before_source_sha256': inputs[str(before_root / (hid + '.json'))],
                            'EB_household_id': after['household_preferences']['EB_household_id'],
                            'member_assignments': [{k:m[k] for k in ('member_id', 'persona_id', 'assignment_rule', 'assignment_origin')}
                                                   for m in after['household_preferences']['member_profiles']],
                            'before_after': [{'asset_id': d['asset_id'], 'kind': d['kind'],
                                'before': {k: next(b for b in before['devices'] if b['asset_id'] == d['asset_id'] and b['kind'] == d['kind'])[k]
                                           for k in ('habit', 'adjustment_preference', 'authorization')},
                                'after': {k: d[k] for k in ('habit', 'adjustment_preference', 'authorization')}} for d in after['devices']]})
        records.append({'household_id': hid, 'role': source_row['type'], 'dates': sorted(d['date'] for d in days),
                        'hardware_signature': signatures[-1], 'original_case_bindings': protected,
                        'unchanged_members_devices_calendar_A_B_outcomes': True})
    require(len(set(signatures)) == 1 and len(set(role_classes)) == 1, 'EXAMPLES_NOT_SAME_ROLE_AND_HARDWARE')
    require(all(sha(p) == h for p,h in inputs.items()), 'SOURCE_CHANGED_DURING_VALIDATION')
    require(all(sha(HERE / p) == h for p,h in methods.items()), 'METHOD_CHANGED_DURING_VALIDATION')
    counts = {arm: dict(Counter(f['code'] for p in audits for f in p['findings'] if f['arm'] == arm)) for arm in ('A', 'B')}
    report = {'schema': 'eb.household_preferences.pair_validation.v1', 'date': '2026-10-22',
              'formal_release_sha256': formal['release_sha256'], 'households': records,
              'same_role_and_exact_hardware_parameters': True, 'checked_original_AB_pairs': len(audits),
              'finding_counts_not_distinct_case_counts': counts, 'source_hashes': inputs, 'method_hashes': methods,
              'A_soft_reference_differences':soft_differences,
              'all_source_files_verified_unchanged': True, 'deterministic_and_independent_of_AB_labels': True,
              'online_changed': False, 'EP_runs': 0, 'population1000_started': False,
              'limits': ['two-household engineering validation only;not empirical preference validation',
                         'member allocation is a declared experimental recipe, not inferred real psychology',
                         'source clocks remain soft preferences, not new deadlines or a replacement A']}
    save(output / 'REPORT.json', report); save(output / 'COMPARISON.json', comparisons); save(output / 'AB_CHECKS20.json', audits)
    save(output / 'SUMMARY.json', {'requested': 2, 'constructed': 2,
        'records': [{'household_id': h, 'status': 'local_preference_profile_constructed'} for h in EXAMPLES]})
    seal(output, {'EP_runs': 0, 'online_changed': False, 'source_release_sha256': formal['release_sha256']})
    return report


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--artifacts', type=Path, required=True)
    p.add_argument('--before', type=Path, required=True)
    p.add_argument('--out', type=Path, required=True)
    a = p.parse_args(); r = validate(a.artifacts, a.before, a.out)
    print(json.dumps({k:r[k] for k in ('same_role_and_exact_hardware_parameters', 'checked_original_AB_pairs',
                                     'finding_counts_not_distinct_case_counts', 'all_source_files_verified_unchanged')}, ensure_ascii=False))


if __name__ == '__main__': main()
