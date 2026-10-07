#!/usr/bin/env python3
"""Independent source/profile/display/fold readback; no builder import."""
import argparse
import copy
import hashlib
import json
from collections import Counter
from pathlib import Path


def digest(value):
    payload = json.dumps(value, sort_keys=True, ensure_ascii=False,
                         separators=(',', ':'), allow_nan=False).encode()
    return hashlib.sha256(payload).hexdigest()


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def leaf_map(value, pointer=''):
    result = {}
    if isinstance(value, dict) and value:
        for key, child in value.items():
            result.update(leaf_map(child, pointer+'/'+key.replace('~','~0').replace('/','~1')))
    elif isinstance(value, list) and value:
        for index, child in enumerate(value):
            result.update(leaf_map(child, pointer+'/'+str(index)))
    else:
        result[pointer] = value
    return result


def check_bundle(bundle, profiles, display, folds):
    problems = []
    source = {p['slot_id']:p for p in profiles['profiles']}
    roles = {r['slot_id']:r for r in bundle['roles']}
    views = {r['slot_id']:r for r in display['roles']}
    fold_rows = {r['slot_id']:r for r in folds['rows']}
    if not (len(source)==len(roles)==len(views)==len(fold_rows)==1000 and len({p['family']['family_id'] for p in profiles['profiles']})==1000 and
            len(bundle['roles'])==1000 and len(display['roles'])==1000 and len(folds['rows'])==1000 and
            set(source)==set(roles)==set(views)==set(fold_rows)):
        return ['cohort_or_unique_identity_mismatch']
    model_sha = digest(profiles['generation_model'])
    rank = sorted(source, key=lambda slot:hashlib.sha256((folds['salt']+'|'+slot).encode()).hexdigest())
    expected_fold = {slot:index%10 for index,slot in enumerate(rank)}
    for slot, p in source.items():
        r, v, f = roles[slot], views[slot], fold_rows[slot]
        facts = {key:p[key] for key in ['family','housing','site','devices','activities']}
        if r['facts'] != facts or r['family_semantic_sha256'] != digest(p['family']) or r['housing_semantic_sha256'] != digest(p['housing']):
            problems.append(slot+':fact_or_semantic_binding_changed')
        if r['profile_version'] != profiles['generation_model']['version'] or r['generation_model_sha256'] != model_sha:
            problems.append(slot+':version_or_model_changed')
        if v['family'] != p['family'] or v['housing'] != p['housing'] or v['residence_city'] != p['site'].get('city'):
            problems.append(slot+':display_fact_changed')
        if v['fact_bundle_sha256'] != digest(r) or v['profile_version'] != r['profile_version']:
            problems.append(slot+':display_binding_changed')
        mapping = leaf_map(facts)
        prov = {x['json_pointer']:x for x in r['field_provenance']}
        if len(prov) != len(r['field_provenance']) or set(mapping) != set(prov):
            problems.append(slot+':provenance_coverage_changed')
        else:
            for pointer,value in mapping.items():
                entry = prov[pointer]
                if entry['value_sha256'] != digest(value) or entry['profile_file_sha256'] != bundle['profiles_sha256']:
                    problems.append(slot+':provenance_value_binding_changed')
                    break
                if entry['individual_source_observed'] is not False or entry['evidence_status'] == 'source_observed':
                    problems.append(slot+':modeled_fact_promoted_to_observation')
                    break
                if value is None and entry['evidence_status'] not in ['unknown','not_applicable']:
                    problems.append(slot+':null_status_lost')
                    break
        if r['raw_human_answer'] is not None or r['actor_id'] is not None or r['questionnaire_collectable'] or v['questionnaire_collectable'] or v['energy_plan'] is not None:
            problems.append(slot+':pending_human_or_energy_state_fabricated')
        if f['test_fold'] != expected_fold[slot] or f['family_revision_key'] != slot or f['family_id'] != p['family']['family_id']:
            problems.append(slot+':family_fold_changed')
    return problems


def check_observed_split(rows, track):
    """Validate future exposure splits; caller supplies recorded identities."""
    if track not in ['unseen_family','unseen_actor','joint_unseen_actor_family']:
        raise ValueError('unsupported split track')
    required = ['exposure_id','split','actor_id','family_revision_key','scenario_family_id']
    issues, seen, units = [], set(), {}
    keys = ['family_revision_key'] if track=='unseen_family' else ['actor_id'] if track=='unseen_actor' else ['family_revision_key','actor_id']
    for row in rows:
        if any(not row.get(k) for k in required):
            issues.append('missing_observed_identity'); continue
        if row['exposure_id'] in seen:
            issues.append('duplicate_exposure_id')
        seen.add(row['exposure_id'])
        if row['split'] not in ['train','validation','test']:
            issues.append('invalid_split')
        for key in keys:
            unit = (key,row[key])
            units.setdefault(unit,set()).add(row['split'])
    for unit,splits in units.items():
        if len(splits)>1:
            issues.append('identity_leakage:'+unit[0])
    return issues


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('directory',type=Path)
    args=parser.parse_args(); directory=args.directory
    bundle=json.loads((directory/'ROLE_FACT_BUNDLES.json').read_text())
    profiles=json.loads(Path(bundle['profiles_path']).read_text())
    generator_lock=json.loads(Path(bundle['generator_lock_path']).read_text())
    display=json.loads((directory/'FACT_DISPLAY_DRAFTS.json').read_text())
    folds=json.loads((directory/'FAMILY_FOLD_PLAN.json').read_text())
    errors=check_bundle(bundle,profiles,display,folds)
    if generator_lock.get('settings')!=profiles.get('generation_model'):
        errors.append('generator_settings_model_mismatch')
    if generator_lock.get('output_sha256')!=bundle['profiles_sha256']:
        errors.append('generator_output_profile_mismatch')
    code_directory=Path(bundle['profiles_path']).parent/'code'
    code_matches=[p for p in [code_directory/'generate_candidates.py',
                             code_directory/'generate_empirical_support_candidates.py']
                  if p.is_file() and sha(p)==generator_lock.get('code_sha256')]
    if len(code_matches)!=1:
        errors.append('generator_code_snapshot_mismatch')
    lock=json.loads((directory/'BUNDLE_LOCK.json').read_text())
    for path,value in lock['inputs'].items():
        if sha(path)!=value: errors.append('input_bytes_changed:'+path)
    for name,value in lock['outputs'].items():
        if sha(directory/name)!=value: errors.append('output_bytes_changed:'+name)
    if sha(bundle['profiles_path'])!=bundle['profiles_sha256'] or sha(bundle['generator_lock_path'])!=bundle['generator_lock_sha256']:
        errors.append('bundle_source_bytes_changed')
    probes=[]
    def probe(name, mutate, target='bundle'):
        b,v,f=copy.deepcopy(bundle),copy.deepcopy(display),copy.deepcopy(folds)
        mutate({'bundle':b,'display':v,'folds':f}[target])
        detected=check_bundle(b,profiles,v,f)
        probes.append({'name':name,'detected':bool(detected),'reasons':detected[:3]})
    probe('family_age_mutation',lambda b:b['roles'][0]['facts']['family']['members'][0].update(age_years=999))
    probe('missing_field_provenance',lambda b:b['roles'][0]['field_provenance'].pop())
    probe('modeled_promoted_observed',lambda b:b['roles'][0]['field_provenance'][0].update(evidence_status='source_observed',individual_source_observed=True))
    probe('null_lost',lambda b:b['roles'][0]['field_provenance'].__setitem__(next(i for i,x in enumerate(b['roles'][0]['field_provenance']) if x['evidence_status']=='unknown'),dict(next(x for x in b['roles'][0]['field_provenance'] if x['evidence_status']=='unknown'),evidence_status='modeled')))
    probe('fabricated_answer',lambda b:b['roles'][0].update(raw_human_answer='accept'))
    probe('display_room_mutation',lambda d:d['roles'][0]['housing'].update(H7_natural_rooms_exact=999),'display')
    probe('revision_version_mismatch',lambda b:b['roles'][0].update(profile_version='old_or_unknown'))
    probe('family_fold_mutation',lambda f:f['rows'][0].update(test_fold=(f['rows'][0]['test_fold']+1)%10),'folds')
    example=[{'exposure_id':'e1','split':'train','actor_id':'a1','family_revision_key':'f1','scenario_family_id':'s1'},
             {'exposure_id':'e2','split':'test','actor_id':'a1','family_revision_key':'f2','scenario_family_id':'s2'}]
    split_checks={
        'unseen_actor_rejects_cross_split_actor':bool(check_observed_split(example,'unseen_actor')),
        'unseen_family_allows_known_actor_with_explicit_scope':not check_observed_split(example,'unseen_family'),
        'joint_unseen_rejects_either_identity_overlap':bool(check_observed_split(example,'joint_unseen_actor_family')),
        'missing_actor_is_not_auto_assigned':bool(check_observed_split([dict(example[0],actor_id=None)],'unseen_actor'))}
    passed=not errors and all(p['detected'] for p in probes) and all(split_checks.values())
    result={'schema':'eb.fact_bundle_verification.v1','pass':passed,'roles_checked':len(bundle['roles']),
            'field_values_checked':sum(len(r['field_provenance']) for r in bundle['roles']),
            'errors':errors,'negative_controls':probes,'future_exposure_split_controls':split_checks,
            'verifier_sha256':sha(__file__),'actual_actors_or_answers_validated':0,
            'proves':'source-to-bundle/display binding and specified identity isolation only'}
    (directory/'BUNDLE_VERIFICATION.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n')
    print(json.dumps({k:result[k] for k in ['pass','roles_checked','field_values_checked','errors']}))
    raise SystemExit(0 if passed else 1)


if __name__=='__main__':main()
