#!/usr/bin/env python3
"""Reject contradictory current status, evidence and public file manifests."""
import hashlib,json
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
PUBLIC=ROOT/'docs/household1000'
H=ROOT/'docs/research/collection-adjustment-20260930/household1000'

def read(path):return json.loads(path.read_text())
def sha(path):return hashlib.sha256(path.read_bytes()).hexdigest()

def check():
    status=read(PUBLIC/'STATUS.json');stage=H/status['active_stage']
    board=read(H/'repair_execution_20261008_v1/EXECUTION_BOARD.json')
    evidence=read(stage/'PHYSICAL_PRODUCTION_COMPLETE.json')
    if status['active_stage']=='contrast_repair_v29_20261015':
        return check_v29(status,stage,board,evidence)
    assert board['current_repair_candidate']==status['active_stage']
    assert board['current_full1000_new_worlds']==status['households']==evidence['baseline_households']==1000
    assert board['new_requirement_gate']['actual1000_type_coverage_verified']==status['actual1000_new_type_coverage_verified']is True
    assert board['new_requirement_gate']['target_counts']==status['EB_six_type_target_counts']
    assert sum(status['EB_six_type_target_counts'].values())==1000
    assert evidence['passed']and evidence['baseline_pairs']==status['AB_pairs']==10000
    assert status['IDF_inputs']==20000 and status['verified_input_bound_run_sides']==21440
    assert status['full1000_EP_completed']and status['other950_EP_executed']
    assert status['full1000_EP_allowed']==board['full1000_EP_allowed']
    assert status['final_acceptance_sha256']==sha(stage/'PHYSICAL_PRODUCTION_COMPLETE.json')
    reference=read(PUBLIC/'REFERENCE_ACCEPTANCE.json')
    audit=read(PUBLIC/'audit_20261015/SELF_AUDIT.json')
    assert reference['input_signature']==audit['physical_input_signature']
    for name,value in audit['evidence'].items():assert sha(PUBLIC/'audit_20261015'/name)==value,name
    for batch,count,physics_key in [('formal50',50,'formal50_physics'),('formal950',950,'formal950_physics')]:
        case=read(PUBLIC/f'audit_20261015/{batch}_CASE_ACCEPTANCE.json')
        protocol=read(PUBLIC/f'audit_20261015/{batch}_PROTOCOL_ACCEPTANCE.json')
        cohort=status['formal_cohorts'][batch]
        assert case['passed']and protocol['passed']and case['households']==cohort['households']==count
        assert case['cases_checked']==cohort['cases']==count*10
        assert case['release_signature']==cohort['release_sha256']
        assert case['physical_review_sha256']==evidence[physics_key]
        assert case['source_renderer_full_case_regeneration']=='pass'
        assert protocol['production_records_written']==protocol['human_answers_generated']==0
    assert status['training_release']is False and status['scientific_benchmark_admitted']is False
    assert status['real_EB6_share_estimate_exists']is False and status['physical_calibration_complete']is False
    assert board['whole_program_scientific_completion']is False and reference['human_role_validity_verified']is False
    publication=read(PUBLIC/'PUBLICATION_CHECK.json')
    assert publication['current_browser_actual_final_submission_verified']==status['new_original50']['current_V28_actual_final_browser_submission_verified']is False
    source=read(PUBLIC/'SOURCE_SNAPSHOT.json')
    for row in source['source_files']:assert sha(ROOT/row['path'])==row['published_sha256'],row['path']
    manifest=read(PUBLIC/'RELEASE_MANIFEST.json')
    assert manifest['payload_file_count_excluding_manifest']==len(manifest['payload_files_excluding_this_manifest'])
    for row in manifest['payload_files_excluding_this_manifest']:
        p=ROOT/row['path'];assert p.stat().st_size==row['bytes']and sha(p)==row['sha256'],row['path']
    return {'passed':True,'current_boards_and_evidence_consistent':True,'source_files_verified':len(source['source_files']),
            'public_payload_files_verified':len(manifest['payload_files_excluding_this_manifest']),
            'case_acceptance_scope':10000,'human_validity_claim':False,'EP_started':False}

def check_v29(status,stage,board,evidence):
    assert status['active_stage']==board['current_repair_candidate']
    assert evidence['passed'] and evidence['baseline_households']==status['households']==1000
    assert evidence['baseline_pairs']==status['AB_pairs']==10000 and status['IDF_inputs']==20000
    assert status['final_acceptance_sha256']==sha(stage/'PHYSICAL_PRODUCTION_COMPLETE.json')
    assert status['EB_six_type_target_counts']==board['new_requirement_gate']['target_counts']
    assert status['actual1000_new_type_coverage_verified'] and sum(status['EB_six_type_target_counts'].values())==1000
    summary=read(stage/'PUBLIC_CONTRAST_SUMMARY.json')
    assert summary['passed'] and summary['priority41_repaired']==41 and summary['original_equal857_accounted']==857
    assert summary['counts']['micro_requests']==0 and summary['counts']['cases']==10000
    assert summary['energy_difference_floor'] is None and summary['human_JND_validated'] is False
    assert summary['source_only_repair_no_outcome_selection'] and summary['original50_passed_before950_review']
    assert evidence['public_contrast_summary_sha256']==sha(stage/'PUBLIC_CONTRAST_SUMMARY.json')
    for batch,count,key in [('formal50',50,'formal50_physics'),('formal950',950,'formal950_physics')]:
        case=read(stage/f'FORMAL_{batch}_CASE_REVIEW.json');protocol=read(stage/f'HTTP_{batch}_REVIEW.json');browser=read(stage/f'BROWSER_{batch}_REVIEW_PUBLIC.json')
        acceptance=read(stage/(('ORIGINAL50'if batch=='formal50'else'OTHER950')+'_CONTRAST_ACCEPTANCE_PUBLIC.json'))
        cohort=status['formal_cohorts'][batch]
        assert case['passed'] and protocol['passed'] and browser['passed'] and acceptance['passed']
        assert case['cases_checked']==cohort['cases']==browser['source_case_count']==count*10
        assert case['release_signature']==cohort['release_sha256']==browser['release_signature']==evidence['formal_release_signatures'][batch]
        assert case['physical_review_sha256']==evidence[key]
        receipt_key='original50_final_acceptance_sha256'if batch=='formal50'else'other950_final_acceptance_sha256'
        assert acceptance['source_receipt_sha256']==evidence[receipt_key]
        assert acceptance['input_signature']==evidence['input_signatures']['original50'if batch=='formal50'else'other950']
        assert browser['actual_browser_cases_checked']>=(500 if count==50 else 60)
        assert browser['visible_change_text_matches_source'] and browser['current_answer_and_respondent_outside_model_input']
        assert browser['actual_submit_recovery_revision_withdrawal_passed']
        assert protocol['production_records_written']==protocol['human_answers_generated']==0
        for name,value in acceptance['public_evidence_sha256'].items():assert sha(stage/name)==value
    for scope,key in [('original50','formal50_physics'),('other950','formal950_physics'),('weather_sensitivity','weather_physics')]:
        report=read(stage/f'PHYSICS_{scope}_REVIEW.json');assert sha(stage/f'PHYSICS_{scope}_REVIEW.json')==evidence[key]
        assert report['acceptance_passed'] and not report['failures']
        assert report['input_signature_at_readback']==evidence['input_signatures'][scope]
    assert evidence['verified_input_bound_run_sides']==21440==status['verified_input_bound_run_sides']
    assert evidence['new_EP_sides']+evidence['exact_unchanged_SQL_reused_sides']==21440
    reference=read(PUBLIC/'REFERENCE_ACCEPTANCE.json');assert reference['input_signatures']==evidence['input_signatures']
    types=read(stage/'CLUSTER_COVERAGE1000_REVIEW.json');inputs=read(stage/'INPUT_AUDIT.json')
    assert types['source_private_receipt_sha256']==evidence['current_type_audit_sha256'] and inputs['source_private_receipt_sha256']==evidence['current_source_input_audit_sha256']
    assert types['accepted_for_frozen1000_reference_production'] and inputs['status']=='pass'
    assert types['actual_type_counts']==summary['current_type_counts']==status['EB_six_type_target_counts']
    parity=read(stage/'REVIEWED_SOURCE_PARITY.json');assert parity['passed'] and parity['input_signature']==evidence['input_signatures']['other950']
    assert reference['human_role_validity_verified'] is False and status['scientific_benchmark_admitted'] is False
    assert status['training_release'] is False and status['real_EB6_share_estimate_exists'] is False and status['physical_calibration_complete'] is False
    assert read(PUBLIC/'PUBLICATION_CHECK.json')['current_browser_actual_final_submission_verified'] is True
    source=read(PUBLIC/'SOURCE_SNAPSHOT.json')
    for row in source['source_files']:assert sha(ROOT/row['path'])==row['published_sha256'],row['path']
    manifest=read(PUBLIC/'RELEASE_MANIFEST.json');assert manifest['payload_file_count_excluding_manifest']==len(manifest['payload_files_excluding_this_manifest'])
    for row in manifest['payload_files_excluding_this_manifest']:
        p=ROOT/row['path'];assert p.stat().st_size==row['bytes']and sha(p)==row['sha256'],row['path']
    return {'passed':True,'current_boards_and_evidence_consistent':True,'source_files_verified':len(source['source_files']),'public_payload_files_verified':len(manifest['payload_files_excluding_this_manifest']),'case_acceptance_scope':10000,'actual_browser_pages_verified':sum(summary['actual_browser_pages_checked'].values()),'priority41_repaired':41,'original_equal857_accounted':857,'human_validity_claim':False,'EP_started':False}

if __name__=='__main__':print(json.dumps(check(),sort_keys=True))
