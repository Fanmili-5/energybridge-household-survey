"""Local, read-only audit against an already sealed 50-household release.

No sampling, no simulator import, no survey writes. All 500 pairs stay in the
denominator; snapshots of old outcomes are copied, not recalculated.
"""
import argparse
from collections import Counter, defaultdict
import gzip
import json
from pathlib import Path

from .core import HERE, digest, read, require, save, sha, seal
from .device_persona import generate_personas, render_family
from .portrait_inputs import from_formal
from .persona_checks import audit_case
from .decision_conditions import contract_input

EXAMPLES = ('ordinary-v6-0653', 'ordinary-v6-0250')


def behavior_signature(profile, exclude_kinds=()):
    """Ignores wording, IDs, dates, exact times/amounts and identical AC counts."""
    return digest(sorted({digest([d['kind'], sorted(r['rule_id'] for r in d['conditional_preferences']),
        d['authorization']['mode'], d['authorization']['standing_consent_actions'],
        d['authorization']['proposal_actions'], d['authorization']['requires_new_explicit_consent'],
        sorted({digest(m['tags']) for m in d.get('inherited_preferences', {}).get('affected_member_profiles', [])})])
        for d in profile['devices'] if d['kind'] not in exclude_kinds}))


def diversity(profiles):
    groups = defaultdict(list); per_device = defaultdict(list); matched = defaultdict(list)
    for hid, p in profiles.items():
        sig = behavior_signature(p); groups[p['role'], sig].append(hid)
        inventory = sorted({d['kind'] for d in p['devices']})
        matched[p['role'], tuple(inventory)].append(hid)
        for d in p['devices']:
            per_device[d['kind']].append(digest(sorted(r['rule_id'] for r in d['conditional_preferences'])))
    return {'households': len(profiles), 'structural_behavior_sets': len(groups),
        'structural_sets_without_AC': len({(p['role'], behavior_signature(p, ('ac',))) for p in profiles.values()}),
        'signature_definition': 'active decision-rule IDs and per-action consent;ignores prose,names,IDs,ages,dates,numeric times/bounds and repeated identical ACs',
        'by_role': {r: {'households': sum(len(v) for (role, sig), v in groups.items() if role == r),
                        'structural_sets': sum(role == r for role, sig in groups),
                        'largest_equal_group': max(len(v) for (role, sig), v in groups.items() if role == r)} for r in sorted({p['role'] for p in profiles.values()})},
        'per_device': {k: {'assets': len(v), 'condition_sets_ignoring_role_and_wording': len(set(v))} for k, v in sorted(per_device.items())},
        'same_role_same_device_classes': [{'role': role, 'device_classes': list(inv), 'households': ids,
            'structural_sets': len({behavior_signature(profiles[h]) for h in ids})} for (role, inv), ids in matched.items() if len(ids) > 1],
        'equal_groups': [{'role': r, 'households': ids} for (r, sig), ids in groups.items() if len(ids) > 1],
        'uniqueness_target_or_population_claim': False}


def validate(artifacts, output, *, published=None):
    artifacts = Path(artifacts).resolve(); output = Path(output).resolve()
    require(not output.is_relative_to(artifacts), 'AUDIT_OUTPUT_MUST_NOT_BE_SOURCE')
    output.mkdir(parents=True, exist_ok=False)
    method_hashes = {name:sha(HERE/name) for name in ('device_persona.py', 'decision_conditions.py', 'portrait_inputs.py',
        'persona_checks.py', 'validate_device_personas.py', 'DEVICE_PERSONA_RULES.json', 'ENERGY_PORTRAIT_RULES.json', 'ENERGY_PORTRAIT_SOURCES.json')}
    release = artifacts / 'release-complete500-ui91-physics-v5-rounds'
    raw_root = artifacts / 'A-source-complete500-v1'
    context_root = artifacts / 'collection-complete500-v1/contexts'
    sources = {}
    def load(path):
        path = path.resolve(); sources.setdefault(str(path), sha(path))
        if path.suffix == '.gz':
            with gzip.open(path, 'rt') as f: return json.load(f)
        return read(path)
    formal = load(release / 'FORMAL_RELEASE.json'); index = load(release / 'INDEX50.json')
    require(digest({k:v for k,v in formal.items() if k != 'release_sha256'}) == formal['release_sha256'], 'RELEASE_SIGNATURE_MISMATCH')
    require(sha(release / 'INDEX50.json') == formal['files']['INDEX50.json'], 'FORMAL_INDEX_HASH_MISMATCH')
    published = load(Path(published) if published else HERE.parent / 'releases/reference50-v4-ui91-complete/MANIFEST.json')
    require(published['release_sha256'] == formal['release_sha256'], 'WRONG_FORMAL_RELEASE')
    subset = load(raw_root / 'SUBSET50.json'); rows = {r['household_id']: r for r in subset['records']}
    profiles = {}; results = []; frames = []; snapshots = []; errors = []
    # Validate two named households first, then all remaining households. This
    # ordering does not fit rules to B outcomes: generate reads declarations only.
    household_ids = list(EXAMPLES) + [h for h in index['households'] if h not in EXAMPLES]
    require(len(index['cases']) == 500 and len(household_ids) == 50, 'EXPECTED_SEALED_50_X_10')
    for hid in household_ids:
        try:
            profile_path = release / 'public/households' / (hid + '.json'); profile = load(profile_path)
            require(sha(profile_path) == index['profiles_sha256'][hid], 'PROFILE_HASH_MISMATCH')
            days = []; calendar_map = {}; cases = []; contexts = []
            case_rows = [r for r in index['cases'] if r['household_id'] == hid]
            a_rows = {r['date']: r for r in rows[hid]['cases']}
            require(len(case_rows) == 10 and set(a_rows) == {r['date'] for r in case_rows}, 'TEN_FORMAL_DATES_REQUIRED')
            for row in case_rows:
                raw_path = raw_root / a_rows[row['date']]['path']; raw = load(raw_path)
                require(sha(raw_path) == a_rows[row['date']]['sha256'], 'RAW_CALENDAR_HASH_MISMATCH')
                for d in raw['days']:
                    a = d['activity']; value = {'date': d['date'], 'calendars': a['member_calendars'], 'operator_windows': a['operator_windows_min']}
                    require(d['date'] not in calendar_map or calendar_map[d['date']] == value, 'CONTEXT_CALENDARS_DISAGREE')
                    calendar_map[d['date']] = value
                days.append(calendar_map[row['date']])
                context = load(context_root / (hid + '__' + row['date'] + '.json.gz'))
                case_path = release / 'public' / row['path']; case = load(case_path)
                require(sha(case_path) == row['sha256'], 'CASE_HASH_MISMATCH')
                require(context['source']['A_case_sha256'] == case['bindings']['source_A_case_sha256'], 'A_LINEAGE_MISMATCH')
                require(sha(raw_path) == context['source']['A_case_sha256'], 'CALENDAR_NOT_FROM_CASE_SOURCE_A')
                def declared(needs):
                    return {n['need_id']:contract_input(n,row['date']) for n in needs if n['need_id'].startswith(row['date'] + ':')}
                require(declared(context['needs']) == declared(case['context']['needs']['A']), 'DISPLAY_SERVICE_DECLARATION_MISMATCH')
                contexts.append(context); cases.append(case)
                physical = case['physical_review']
                snapshots.append({'case_id': case['case_id'], 'source_case_path': row['path'], 'source_case_sha256': row['sha256'],
                    'outcome_status': case['outcome_status'], 'physical_review': {k: physical[k] for k in ('status', 'audit_status', 'failed_checks') if k in physical},
                    'VPP_results': case['VPP_results'],
                    'original_outcomes_sha256': digest({k: case[k] for k in ('impact', 'physical_review', 'VPP_results', 'outcome_status')}),
                    'status': 'unchanged_sealed_source_retained;summary_only;not_recomputed_or_used_for_persona'})
            source = from_formal(profile, days, rows[hid]['type'], contexts)
            persona = generate_personas(source)
            # Determinism + independence of selected day/A/B/outcomes/answers.
            changed = dict(source, days=source['days'][-1:], plans={'A':'mutated', 'B':'mutated'}, outcomes='mutated', answers='mutated')
            require(persona == generate_personas(changed), 'PREFERENCE_DEPENDS_ON_CASE_OR_LABELS')
            profiles[hid] = persona
            save(output / 'profiles' / (hid + '.json'), persona)
            (output / 'profiles' / (hid + '.family.md')).write_text(render_family(persona))
            (output / 'profiles' / (hid + '.brief.md')).write_text(render_family(persona, brief=True))
            if hid in EXAMPLES: save(output / 'examples' / (hid + '.input.json'), source)
            frames.append({'household_id': hid, 'formal_dates': sorted(a_rows), 'profile_dates': persona['bindings']['calendar_dates'], 'aligned': True})
            for case, context in zip(cases, contexts):
                result = audit_case(case, context, profile, persona, calendar_map)
                result['household_id'] = hid; results.append(result)
        except (ValueError, KeyError, TypeError) as error:
            errors.append({'household_id': hid, 'status': 'engineering_diagnostic_retained', 'reason': str(error)})
    require(all(sha(path) == expected for path, expected in sources.items()), 'SOURCE_MUTATED_DURING_AUDIT')
    require(all(sha(HERE/name) == expected for name, expected in method_hashes.items()), 'METHOD_CHANGED_DURING_AUDIT')
    counts = {arm: {code: sum(any(f['arm'] == arm and f['code'] == code for f in r['findings']) for r in results)
                  for code in sorted({f['code'] for r in results for f in r['findings'] if f['arm'] == arm})} for arm in ('A', 'B')}
    d = diversity(profiles)
    report = {'schema': 'eb.device_persona.release_audit.v3', 'date': '2026-10-21',
        'method_files_sha256': method_hashes,
        'formal_release_sha256': formal['release_sha256'], 'requested_households': 50, 'compiled_households': len(profiles),
        'requested_AB_pairs': 500, 'checked_AB_pairs': len(results), 'engineering_diagnostics': errors,
        'calendar_frames': frames, 'diversity': d, 'AB_case_counts_by_finding': counts,
        'two_households': {hid: [r for r in results if r['household_id'] == hid] for hid in EXAMPLES},
        'sources_verified_unchanged': len(sources), 'source_hashes': sources,
        'retained_all_source_AB_and_outcomes': len(snapshots) == 500, 'selection_or_resampling': False,
        'existing_outcome_summary': {'source_rows_retained': len(snapshots),
            'outcome_status': dict(Counter(s['outcome_status'] for s in snapshots)),
            'source_physical_audit_status': dict(Counter(s['physical_review'].get('audit_status', 'unspecified') for s in snapshots)),
            'source_VPP_target_met': dict(Counter(str(v['target_met']) for s in snapshots for v in s['VPP_results']))},
        'online_changed': False, 'EP_runs': 0, 'population1000_started': False,
        'limits': ['not a measured preference predictor', 'shared conditions may repeat',
                   'no new physical calculation or human acceptance label', 'proposal eligibility is not obtained consent']}
    save(output / 'REPORT.json', report); save(output / 'DIVERSITY50.json', d)
    save(output / 'SUMMARY.json', {'schema':'eb.device_persona.shadow_validation.v3', 'requested':50, 'constructed':len(profiles),
        'records':[{'household_id':hid,'status':'persona_constructed' if hid in profiles else 'engineering_diagnostic_retained'} for hid in household_ids]})
    save(output / 'AB_CHECKS500.json', results); save(output / 'EXISTING_OUTCOMES500.json', snapshots)
    seal(output, {'formal_release_sha256': formal['release_sha256'], 'EP_runs': 0, 'online_changed': False})
    return report


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--artifacts', type=Path, required=True); p.add_argument('--out', type=Path, required=True)
    a = p.parse_args(); report = validate(a.artifacts, a.out)
    print(json.dumps({k: report[k] for k in ('compiled_households', 'checked_AB_pairs', 'engineering_diagnostics', 'AB_case_counts_by_finding', 'sources_verified_unchanged')}, ensure_ascii=False))


if __name__ == '__main__': main()
