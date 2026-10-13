#!/usr/bin/env python3
"""Expose the new unaccepted requirement without changing sealed V23 data."""
import json
from pathlib import Path
import shutil

STAGE = Path(__file__).resolve().parents[1]
BASE = STAGE.parent


def read(p):
    return json.loads(p.read_text())


def save(p, value):
    p.write_text(json.dumps(value, ensure_ascii=False, sort_keys=True,
                            indent=2, allow_nan=False) + '\n')


def main():
    history = STAGE / 'pointer_history'
    history.mkdir(exist_ok=True)
    paths = [BASE / name for name in ['CURRENT_STATIC_INPUTS.json', 'CURRENT_TEST50.json',
             'CURRENT_REPAIR_CANDIDATE.json', 'CURRENT_PRODUCTION_REVIEW.json']]
    paths.append(BASE / 'repair_execution_20261008_v1/EXECUTION_BOARD.json')
    for p in paths:
        prior = history / p.name
        if not prior.exists():
            shutil.copy2(p, prior)
        j = read(p)
        j['new_generation_requirement_stage'] = STAGE.name
        j['new_generation_requirement'] = STAGE.name + '/REQUIREMENT.json'
        j['new_EB_six_type_requirement_accepted'] = False
        j['satisfies_current_generation_requirements'] = False
        j['new_generation_allowed'] = False
        j['full1000_EP_allowed'] = False
        j['historical_V23_acceptance_preserved'] = True
        j['current_requirement_status'] = 'EB-six-type prerequisite unresolved;legacy acceptance is historical'
        if p.name == 'CURRENT_PRODUCTION_REVIEW.json':
            j['historical_reference_production_accepted'] = j.get('historical_reference_production_accepted',
                   j.get('complete_reference_production_accepted', False))
            j['complete_reference_production_accepted'] = False
            j['current_EP_gate_closed'] = True
            j['current_full1000_EP_gate_closed'] = True
            j['latest_candidate_synced_to_GitHub'] = False
        if p.name == 'EXECUTION_BOARD.json':
            j['historical_accepted_production'] = 'gate_repair_production_20261013_v23'
            j['production'] = STAGE.name
            j['foundation_revisions_required'] = True
            j['historical_published_source_commit'] = j.get('historical_published_source_commit',
                  j.get('published_source_commit'))
            j['source_published_to_GitHub'] = False
            j['design_realism_verdict'] = 'historical_V23_scoped_acceptance;current_EB6_requirement_pending'
            j['latest_reference_repair_acceptance_status'] = 'historical_V23_pass;not_new_requirement_acceptance'
            j['new_requirement_gate'] = {'id': 'G0_EB_six_types', 'status': 'not_accepted',
                 'quota_source': 'user-confirmed EB assigned-persona mix',
                 'required_before': 'household world generation and downstream A/B/IDF',
                 'strict_existing_cohort_maximum_assignable': 984,
                 'critical_role_preferences_missing_households': 1000,
                 'new_original50_recovery_verified': False}
            j['fixed']['EB_six_type_target_counts'] = read(STAGE / 'REQUIREMENT.json')['target_counts']
        save(p, j)
    save(BASE / 'CURRENT_GENERATION_REQUIREMENTS.json', {
        'schema': 'eb.current_generation_requirements.v24', 'date': '2026-10-13',
        'stage': STAGE.name, 'requirement_path': STAGE.name + '/REQUIREMENT.json',
        'methods_path': STAGE.name + '/METHODS.md',
        'gate_entry': STAGE.name + '/code/require_generation.py',
        'accepted': False, 'generation_allowed': False, 'EP_allowed': False,
        'historical_accepted_stage': 'gate_repair_production_20261013_v23',
        'historical_acceptance_meets_new_requirement': False})
    print(json.dumps({'current_requirement': STAGE.name,
                      'generation_allowed': False, 'EP_allowed': False,
                      'sealed_V23_files_changed': 0}))


if __name__ == '__main__':
    main()
