#!/usr/bin/env python3
"""Check audited foundations; refuse formal production when evidence is open."""
import argparse
import copy
import hashlib
import json
from pathlib import Path

HERE=Path(__file__).resolve().parent
def read(p):return json.loads(Path(p).read_text())
def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()

def policy_errors(contract,decision,source_report,support_report):
    errors=[]
    if contract['target']['slots']!=1000 or contract['target']['multi_person_minors_excluded']:
        errors.append('target_contract_changed')
    if set(contract['target']['exclusions'])!={'town','rural','collective_household','under20_single_person_household'}:
        errors.append('target_exclusions_changed')
    if len(contract['field_contracts'])!=len({x['field'] for x in contract['field_contracts']}):
        errors.append('duplicate_field_contract')
    for f in contract['field_contracts']:
        if any(not f.get(k) for k in ['target_unit','source','equivalence','forbidden','production_requirement']):
            errors.append('field_definition_incomplete:'+f['field'])
    required={'target_field_contract','source_bytes_and_reference_reconstruction',
        'H5_H7_and_housing_branch_to_target_bridge','calibration_influence_and_joint_distribution',
        'functional_home_and_actor_contract','observed_human_benchmark'}
    gates={g['id']:g for g in decision['gates']}
    if set(gates)!=required:errors.append('preflight_gate_set_incomplete')
    if decision['profiles']!=1000 or support_report['profiles_checked']!=decision['ordinary_profiles']:
        errors.append('population_denominator_mismatch')
    if source_report['paired_rented_room_references']==0 and gates.get('H5_H7_and_housing_branch_to_target_bridge',{}).get('status')=='pass':
        errors.append('missing_rented_room_bridge_promoted_validated')
    evidence_open=any(g.get('status') not in ['pass','documented'] for g in gates.values())
    if evidence_open and any(decision[k] for k in ['formal_1000_production_release','collection_release','training_release']):
        errors.append('unresolved_foundation_promoted_release')
    if decision['compile_rate_or_energy_outcomes_used_for_preflight']:
        errors.append('downstream_outcome_used_to_select_foundations')
    if not support_report['pass'] or support_report['generator_imported']:
        errors.append('native_reference_check_not_independent_or_failed')
    for k in ['original_rows_changed','member_references_removed','population_slots_removed']:
        if source_report['quality_quarantine'][k]!=0:errors.append('quarantine_changed_wrong_unit:'+k)
    return errors

def main():
    ap=argparse.ArgumentParser();ap.add_argument('--audit',type=Path,required=True)
    ap.add_argument('--require-formal-production',action='store_true')
    ap.add_argument('--report',type=Path);args=ap.parse_args()
    c=read(HERE/'FOUNDATION_CONTRACT.json');d=read(args.audit/'PREFLIGHT_DECISION.json')
    s=read(args.audit/'SOURCE_FRAME_AUDIT.json');a=read(args.audit/'NATIVE_AREA_SUPPORT_CHECK.json')
    errors=policy_errors(c,d,s,a)
    if sha(HERE/'FOUNDATION_CONTRACT.json')!=d['contract_sha256']:errors.append('contract_bytes_changed')
    if sha(d['profile_path'])!=d['profile_sha256']:errors.append('profile_bytes_changed')
    for report in [s,a]:
        if report['profile_sha256']!=d['profile_sha256']:errors.append('audit_profile_version_mismatch')
    if sha(args.audit/'SOURCE_FRAME_AUDIT.json')!=d['source_frame_sha256']:errors.append('source_frame_bytes_changed')
    if sha(args.audit/'NATIVE_AREA_SUPPORT_CHECK.json')!=d['native_support_sha256']:errors.append('native_support_bytes_changed')
    if sha(d['generator_lock_path'])!=d['generator_lock_sha256']:errors.append('generator_lock_bytes_changed')
    generator_lock=read(d['generator_lock_path'])
    if generator_lock['output_sha256']!=d['profile_sha256']:errors.append('generator_profile_binding_changed')
    for source in generator_lock['source_files']:
        if sha(source['path'])!=source['sha256']:errors.append('native_source_bytes_changed:'+Path(source['path']).name)
    if sha(HERE/'audit_foundation.py')!=d['audit_code_sha256']:errors.append('audit_code_bytes_changed')
    probes=[]
    for name,mutate in [
        ('claim_release_with_open_foundations',lambda x:x.update(formal_1000_production_release=True)),
        ('claim_rented_room_bridge_validated',lambda x:next(g for g in x['gates'] if g['id']=='H5_H7_and_housing_branch_to_target_bridge').update(status='pass')),
        ('use_compile_outcomes_to_select_model',lambda x:x.update(compile_rate_or_energy_outcomes_used_for_preflight=True)),
        ('lose_original_population_denominator',lambda x:x.update(profiles=999))]:
        m=copy.deepcopy(d);mutate(m)
        probes.append({'mutation':name,'detected':bool(policy_errors(c,m,s,a))})
    passed=not errors and all(x['detected'] for x in probes)
    result={'schema':'eb.foundation.preflight_verification.v1','verification_pass':passed,
        'formal_production_allowed':passed and d['formal_1000_production_release'],
        'errors':errors,'negative_controls':probes,
        'contract_sha256':sha(HERE/'FOUNDATION_CONTRACT.json'),
        'decision_sha256':sha(args.audit/'PREFLIGHT_DECISION.json'),
        'source_frame_sha256':sha(args.audit/'SOURCE_FRAME_AUDIT.json'),
        'native_support_sha256':sha(args.audit/'NATIVE_AREA_SUPPORT_CHECK.json'),
        'code_sha256':sha(__file__),
        'meaning':'verification confirms truthful refusal and artifact bindings, not scientific approval'}
    if args.report:
        if args.report.exists():raise ValueError('new_verification_report_required')
        args.report.write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n')
    print(json.dumps(result,ensure_ascii=False))
    if not passed:raise SystemExit(1)
    if args.require_formal_production and not result['formal_production_allowed']:
        print('Formal production refused: foundational evidence gates remain unresolved.')
        raise SystemExit(2)

if __name__=='__main__':main()
