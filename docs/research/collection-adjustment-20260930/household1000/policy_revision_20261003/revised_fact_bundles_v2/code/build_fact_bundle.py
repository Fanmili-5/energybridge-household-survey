#!/usr/bin/env python3
"""Materialize version-bound research facts and outcome-blind family folds.

This adapter does not invent devices, schedules, city residence or human labels.
Physical designs remain separate attachments and cannot overwrite role facts.
"""
import argparse
import hashlib
import json
import shutil
from collections import Counter
from pathlib import Path

HERE = Path(__file__).resolve().parent


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def digest(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
                                     separators=(',', ':'), allow_nan=False).encode()).hexdigest()


def save(path, value):
    Path(path).write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False)+'\n')


def leaves(value, path=''):
    if isinstance(value, dict) and value:
        for key, child in value.items():
            yield from leaves(child, path+'/'+key.replace('~', '~0').replace('/', '~1'))
    elif isinstance(value, list) and value:
        for index, child in enumerate(value):
            yield from leaves(child, path+'/'+str(index))
    else:
        yield path, value


def provenance(path, value, profile, profile_sha, lock_sha):
    # Conservative status classes: none of these new household values are
    # observations, even when aggregate source constraints contributed to them.
    status = 'modeled'
    basis = 'version_bound_synthetic_profile'
    if value is None:
        inapplicable = (not profile['housing'].get('census_H6_H7_applicable') and
                        (path.startswith('/housing/H6_') or path.startswith('/housing/H7_')))
        status = 'not_applicable' if inapplicable else 'unknown'
        basis = 'nonordinary_census_skip' if inapplicable else 'unidentified_value_preserved_null'
    elif 'pending' in str(value).lower() and (path.endswith('status') or path.endswith('evidence')):
        status, basis = 'pending', 'upstream_explicit_pending_state'
    elif any(x in path for x in ['/relation_design', '/sleep_groups', '/nonordinary_model_scenario',
                                  '/design_floor_area_m2', '/design_natural_rooms_exact']):
        status, basis = 'design', 'upstream_explicit_design_without_individual_observation'
    elif path in ['/family/resident_count', '/family/generation_count_design', '/housing/H7_census_bin',
                  '/housing/H5_is_ordinary_model_assigned', '/housing/vintage_category_index',
                  '/housing/building_storeys_category_index']:
        basis = 'specified_aggregate_source_constraint_and_declared_joint_model'
    evidence_key = None
    if path.startswith('/housing/'):
        leaf = path.split('/')[2]
        prefixes = [('H5_', 'H5_evidence'), ('H6_', 'H6_evidence'), ('H7_', 'H7_evidence'),
                    ('building_year_', 'building_year_evidence'), ('dwelling_type', 'dwelling_type_evidence'),
                    ('household_storeys', 'household_storeys_evidence'), ('sleep_', 'sleep_evidence')]
        evidence_key = next((key for prefix, key in prefixes if leaf.startswith(prefix)), None)
    evidence = profile['housing'].get(evidence_key) if evidence_key else None
    return {'json_pointer': path, 'value_sha256': digest(value), 'evidence_status': status,
            'basis': basis, 'upstream_evidence_text': evidence,
            'profile_file_sha256': profile_sha, 'generator_lock_sha256': lock_sha,
            'individual_source_observed': False}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--profiles', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        raise ValueError('new immutable output directory required')
    source = args.profiles.resolve()
    dataset = json.loads(source.read_text())
    lock_path = source.parent/'GENERATOR_LOCK.json'
    lock = json.loads(lock_path.read_text())
    profile_sha, lock_sha = sha(source), sha(lock_path)
    if lock.get('output_sha256') != profile_sha:
        raise ValueError('generator lock/profile mismatch')
    if lock.get('settings') != dataset.get('generation_model'):
        raise ValueError('generator settings/model mismatch')
    code_candidates = [source.parent/'code'/name for name in
                       ['generate_candidates.py', 'generate_empirical_support_candidates.py']]
    code_matches = [p for p in code_candidates if p.is_file() and sha(p) == lock.get('code_sha256')]
    if len(code_matches) != 1:
        raise ValueError('generator code snapshot mismatch')
    code_path = code_matches[0]
    profiles = dataset['profiles']
    if len(profiles) != 1000 or len({p['slot_id'] for p in profiles}) != 1000:
        raise ValueError('fixed complete1000 slots required')
    if len({p['family']['family_id'] for p in profiles}) != 1000:
        raise ValueError('unique synthetic family identity required')
    args.output.mkdir(parents=True)
    (args.output/'code').mkdir()
    for script in ['build_fact_bundle.py','verify_fact_bundle.py']:
        shutil.copy2(HERE/script,args.output/'code'/script)
    model_sha = digest(dataset['generation_model'])
    rows, projections = [], []
    for p in profiles:
        facts = {k:p[k] for k in ['family', 'housing', 'site', 'devices', 'activities']}
        field_provenance = [provenance(pointer, value, p, profile_sha, lock_sha)
                            for pointer, value in leaves(facts)]
        row = {'slot_id':p['slot_id'], 'anonymous_family_id':p['family']['family_id'],
               'profile_version':dataset['generation_model']['version'],
               'profile_file_sha256':profile_sha, 'generator_lock_sha256':lock_sha,
               'generation_model_sha256':model_sha, 'generator_code_sha256':lock['code_sha256'],
               'family_semantic_sha256':digest(p['family']), 'housing_semantic_sha256':digest(p['housing']),
               'facts':facts, 'field_provenance':field_provenance,
               'engineering_condition_is_separate_from_household_facts':True,
               'operational_attachment':None, 'physical_attachment':None,
               'functional_layout_status':'not_validated', 'actor_id':None,
               'raw_human_answer':None, 'questionnaire_collectable':False,
               'collection_release':False, 'training_release':False}
        rows.append(row)
        projection = {'slot_id':p['slot_id'], 'profile_version':row['profile_version'],
                      'fact_bundle_sha256':digest(row),
                      'display_status':'draft_fact_projection_for_research_review',
                      'reference_date':p['family']['reference_date'],
                      'family':p['family'], 'housing':p['housing'],
                      'residence_city':p['site'].get('city'),
                      'interpretation':'按本合成家庭事实扮演；模型值、未知值与另列工程条件分别显示，不能作为真实住户观察。',
                      'devices_and_activity_status':'pending', 'energy_plan':None,
                      'questionnaire_collectable':False}
        # The research projection includes no source IDs or economic amounts.
        # Fine-grained provenance stays in the scientific bundle, outside display.
        projections.append(projection)
    save(args.output/'ROLE_FACT_BUNDLES.json', {'schema':'eb.role_fact_bundle.v3',
        'profiles_path':str(source), 'profiles_sha256':profile_sha,
        'generator_lock_path':str(lock_path), 'generator_lock_sha256':lock_sha,
        'generation_model_sha256':model_sha, 'roles':rows,
        'physical_and_operational_attachments_created':False,
        'human_answers_created':0, 'collection_release':False, 'training_release':False})
    save(args.output/'FACT_DISPLAY_DRAFTS.json', {'schema':'eb.fact_display_draft.v1',
        'roles':projections, 'actual_human_exposures':0, 'collection_release':False})
    # Assign folds using only stable population slot IDs and a declared salt.
    # Revision facts and all future within-family rounds inherit the same fold.
    salt = 'EB_CITY1000_FAMILY_FOLDS_20261003_V1'
    order = sorted(profiles, key=lambda p:hashlib.sha256((salt+'|'+p['slot_id']).encode()).hexdigest())
    assignments = {p['slot_id']:i % 10 for i,p in enumerate(order)}
    fold_rows = [{'slot_id':p['slot_id'], 'family_id':p['family']['family_id'],
                  'family_revision_key':p['slot_id'], 'test_fold':assignments[p['slot_id']],
                  'province':p['province'], 'N_category':p['size_category'],
                  'G_category':p['generation_category']} for p in profiles]
    counts = Counter(r['test_fold'] for r in fold_rows)
    save(args.output/'FAMILY_FOLD_PLAN.json', {'schema':'eb.family_fold_plan.v1',
        'salt':salt, 'number_of_folds':10, 'fold_choice_is':'explicit_benchmark_design_not_population_statistic',
        'test_fold_counts':dict(sorted(counts.items())), 'rows':fold_rows,
        'assignment_used':['stable_population_slot_id', 'declared_hash_salt'],
        'assignment_did_not_use':['physical_admission', 'runtime', 'answers', 'model_predictions'],
        'within_family_revisions_and_rounds_share_fold':True,
        'scope':'unseen_synthetic_family_under_the_same_generator; actors/prototypes/climates_may_overlap',
        'training_release':False})
    save(args.output/'BUNDLE_LOCK.json', {'schema':'eb.role_bundle_lock.v1',
        'builder_sha256':sha(Path(__file__)), 'inputs':{
            str(source):profile_sha, str(lock_path):lock_sha, str(code_path):sha(code_path)},
        'outputs':{name:sha(args.output/name) for name in
                   ['ROLE_FACT_BUNDLES.json','FACT_DISPLAY_DRAFTS.json','FAMILY_FOLD_PLAN.json',
                    'code/build_fact_bundle.py','code/verify_fact_bundle.py']}})
    print(json.dumps({'roles':len(rows), 'fields':sum(len(x['field_provenance']) for x in rows),
                      'fold_sizes':dict(counts), 'collectable':0}))


if __name__ == '__main__':
    main()
