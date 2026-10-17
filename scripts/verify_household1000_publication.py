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
    if read(PUBLIC/'STATUS.json').get('active_stage')=='reference50-v1':
        import importlib.util
        spec=importlib.util.spec_from_file_location('current_reference_publication',ROOT/'benchmark/verify_publication.py')
        current=importlib.util.module_from_spec(spec);spec.loader.exec_module(current)
        return current.check()
    status=read(PUBLIC/'STATUS.json');stage=H/status['active_stage']
    board=read(H/'repair_execution_20261008_v1/EXECUTION_BOARD.json')
    if status.get('release_scope')=='formal50_only_950_paused':
        return check_v30_50(status,stage,board)
    evidence=read(stage/'PHYSICAL_PRODUCTION_COMPLETE.json')
    if status['active_stage']=='substantive_repair_v30_20261015':
        return check_v30(status,stage,board,evidence)
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

def check_v30_50(status,stage,board):
    assert status['active_stage']==board['current_repair_candidate']
    assert not status['full1000_EP_allowed'] and not board['full1000_EP_allowed']
    assert not status['current_full1000_acceptance'] and status['formal950_public_paused']
    obs=read(stage/'SCHOOL_50_ACCEPTANCE_OBSERVED.json');sealed=read(stage/'SEALED50_LOCAL_REVIEW.json');live=read(stage/'ACTIVATION_RECEIPT50_V30.json');http=read(stage/'HTTP_FORMAL50_V30_RECHECK.json')
    assert obs['completed_before_school_outage'] and not obs['school_raw_receipt_retrieved']
    assert obs['baseline_pairs_checked']==500 and obs['sensitivity_pairs_checked']==200 and obs['actual_browser_cases_checked']==500
    assert obs['source_case_and_SQL_controls_passed'] and obs['actual_substantive_contrast_passed'] and obs['browser_submit_revise_recover_withdraw_passed']
    assert sealed['passed'] and sealed['cases_checked']==500 and sealed['payload_files_hash_checked']==501 and sealed['same_displayed_outcomes']==0
    assert sealed['actual_shipped_JS_bindings']['passed'] and sealed['actual_shipped_JS_bindings']['case_bindings_verified']==500
    assert sealed['hotwater_target_change_texts_checked']>0 and not sealed['source_SQL_or_real_browser_rerun']
    assert live['health']['formal50']['release_signature']==sealed['release_signature']==obs['release_signature']==status['formal_cohorts']['formal50']['release_sha256']
    assert live['formal950_public_paused'] and live['formal950_public_status']==503 and live['public_HTTPS50_signature_verified']
    assert live['prior_database_all_table_contents_unchanged'] and live['private_invitation_files_unchanged'] and live['credential_pepper_unchanged']
    assert live['school_observation_sha256']==sha(stage/'SCHOOL_50_ACCEPTANCE_OBSERVED.json')
    assert http['passed'] and http['production_records_written']==http['human_answers_generated']==0
    assert status['formal_cohorts']['formal50']['active'] and not status['formal_cohorts']['formal950']['active']
    assert status['school_raw_receipt_download_pending'] and not status['training_release'] and not status['scientific_benchmark_admitted']
    protocol=read(stage/'PROTOCOL_V30.json');assert protocol['version']=='v30.3' and protocol['minimum_operative_AC_request_C']==2.
    parity=read(stage/'REVIEWED_SOURCE_PARITY.json');assert parity['passed'] and parity['school_install_hash_check_observed_before_original50']
    for name,digest in parity['code_sha256'].items():assert sha(stage/'code'/name)==digest
    helpers=read(stage/'VALIDATION_HELPER_PARITY.json');assert helpers['passed']
    for name,digest in helpers['files_sha256'].items():assert sha(ROOT/name)==digest
    assert read(stage.parent/'contrast_repair_v29_20261015/ACCEPTANCE_WITHDRAWN.json')['withdrawn']
    pointer=read(H/'CURRENT_GENERATION_REQUIREMENTS.json');assert pointer['formal950_paused'] and not pointer['generation_allowed']
    source=read(PUBLIC/'SOURCE_SNAPSHOT.json')
    for row in source['source_files']:assert sha(ROOT/row['path'])==row['published_sha256'],row['path']
    manifest=read(PUBLIC/'RELEASE_MANIFEST.json');assert len(manifest['payload_files_excluding_this_manifest'])==manifest['payload_file_count_excluding_manifest']
    for row in manifest['payload_files_excluding_this_manifest']:
        p=ROOT/row['path'];assert p.stat().st_size==row['bytes'] and sha(p)==row['sha256'],row['path']
    return {'passed':True,'scope':'formal50_only_950_paused','cases':500,'actual_school_browser_pages_observed':500,'sealed_payload_files_verified':501,'same_displayed_outcomes':0,'raw_school_receipt_sync_pending':True,'public_payload_files_verified':manifest['payload_file_count_excluding_manifest'],'EP_started':False,'human_validity_claim':False}

def check_v30(status,stage,board,evidence):
    assert status['active_stage']==board['current_repair_candidate']
    assert evidence['passed'] and evidence['baseline_households']==status['households']==1000
    assert evidence['baseline_pairs']==status['AB_pairs']==10000 and status['IDF_inputs']==20000
    assert status['final_acceptance_sha256']==sha(stage/'PHYSICAL_PRODUCTION_COMPLETE.json')
    summary=read(stage/'PUBLIC_CONTRAST_SUMMARY.json')
    assert evidence['public_contrast_summary_sha256']==sha(stage/'PUBLIC_CONTRAST_SUMMARY.json')
    assert summary['passed'] and summary['counts']['cases']==summary['counts']['actual_decision_relevant_cases']==10000
    assert summary['counts']['same_displayed_outcomes']==summary['counts']['micro_requests']==0
    assert summary['priority41_repaired']==41 and summary['original_equal857_accounted']==857
    assert summary['previous_V29_equal992_now_equal_displayed']==0
    assert summary['A_reference_trajectory_used'] and not summary['B_EP_used_for_candidate_ranking']
    assert summary['other950_used_for_rule_development'] and not summary['other950_is_unseen_scientific_holdout']
    assert summary['original50_passed_before950_review'] and not summary['human_JND_validated']
    assert summary['actual_modified_A_IDFs_from_V29']==0 and summary['human_response_labels_created']==0
    protocol=read(stage/'PROTOCOL_V30.json');negative=read(stage/'CONTRAST_NEGATIVE_CONTROLS.json')
    assert protocol['version']=='v30.3' and protocol['minimum_operative_AC_request_C']==2. and protocol['thresholds_are_declared_task_design_not_human_JND_or_population_estimates']
    assert negative['passed'] and all(negative[k] for k in ('hotwater_25C_difference_recognized','orphan_unit_control_rejected','inactive_extra_AC_rejected','generic_confirmation_noop_rejected','within_event_compensated40min_heating_delay_rejected','active_but_weak0_5C_AC_request_rejected'))
    for batch,count,key,scope in [('formal50',50,'formal50_physics','original50'),('formal950',950,'formal950_physics','other950')]:
        case=read(stage/f'FORMAL_{batch}_CASE_REVIEW.json');http=read(stage/f'HTTP_{batch}_REVIEW.json');browser=read(stage/f'BROWSER_{batch}_REVIEW_PUBLIC.json')
        acceptance=read(stage/(('ORIGINAL50'if count==50 else'OTHER950')+'_CONTRAST_ACCEPTANCE_PUBLIC.json'))
        cohort=status['formal_cohorts'][batch]
        assert case['passed'] and http['passed'] and browser['passed'] and acceptance['passed']
        assert case['cases_checked']==cohort['cases']==browser['source_case_count']==count*10
        assert case['release_signature']==cohort['release_sha256']==browser['release_signature']==evidence['formal_release_signatures'][batch]
        assert case['physical_review_sha256']==evidence[key]
        receipt_key='original50_final_acceptance_sha256'if count==50 else'other950_final_acceptance_sha256'
        assert acceptance['source_receipt_sha256']==evidence[receipt_key]
        assert acceptance['input_signature']==evidence['input_signatures'][scope]
        assert acceptance['substantive_decision_contrast_passed'] and acceptance['actual_IDF_and_SQL_controls_verified']
        assert browser['actual_browser_cases_checked']==browser['consequence_cases_checked']==(500 if count==50 else 1000)
        assert browser['visible_modeled_consequences_match_source'] and browser['visible_change_text_matches_source']
        assert browser['actual_submit_recovery_revision_withdrawal_passed'] and browser['current_answer_and_respondent_outside_model_input']
        assert http['production_records_written']==http['human_answers_generated']==0
        for name,value in acceptance['public_evidence_sha256'].items():assert sha(stage/name)==value,name
    for scope,n,key in [('original50',700,'formal50_physics'),('other950',9500,'formal950_physics'),('weather_sensitivity',520,'weather_physics')]:
        report=read(stage/f'PHYSICS_{scope}_REVIEW.json');assert sha(stage/f'PHYSICS_{scope}_REVIEW.json')==evidence[key]
        assert report['acceptance_passed'] and not report['failures'] and report['checked_pairs']==report['requested_pairs']==n
        assert report['input_signature_at_readback']==evidence['input_signatures'][scope]
        for prefix,receiptkey in [('SUBSTANTIVE','substantive_evidence'),('CONTROL_SQL','control_SQL_evidence')]:
            r=read(stage/f'{prefix}_{scope}_REVIEW_PUBLIC.json')
            assert r['source_private_receipt_sha256']==evidence[receiptkey][scope]
            assert r['passed'] and not r['failures'] and r['input_signature']==evidence['input_signatures'][scope]
            assert r['pairs_checked'if prefix=='SUBSTANTIVE'else'pairs_scanned']==n
    assert evidence['verified_input_bound_run_sides']==21440==status['verified_input_bound_run_sides']
    assert evidence['new_EP_sides']+evidence['exact_unchanged_SQL_reused_sides']==21440
    assert evidence['substantive_task_contrast_verified'] and not evidence['all1000_fresh_EP_rerun']
    reference=read(PUBLIC/'REFERENCE_ACCEPTANCE.json');assert reference['input_signatures']==evidence['input_signatures']
    types=read(stage/'CLUSTER_COVERAGE1000_REVIEW.json');inputs=read(stage/'INPUT_AUDIT.json')
    assert types['source_private_receipt_sha256']==evidence['current_type_audit_sha256'] and inputs['source_private_receipt_sha256']==evidence['current_source_input_audit_sha256']
    assert types['accepted_for_frozen1000_reference_production'] and inputs['status']=='pass'
    assert types['actual_type_counts']==summary['current_type_counts']==status['EB_six_type_target_counts']==board['new_requirement_gate']['target_counts']
    parity=read(stage/'REVIEWED_SOURCE_PARITY.json');assert parity['passed'] and parity['input_signature']==evidence['input_signatures']['other950']
    for name,digest in parity['code_sha256'].items():assert sha(stage/'code'/name)==digest,name
    helpers=read(stage/'VALIDATION_HELPER_PARITY.json');assert helpers['passed'] and helpers['helpers_checked']==26
    for name,digest in helpers['files_sha256'].items():assert sha(ROOT/name)==digest,name
    withdrawn=read(stage.parent/'contrast_repair_v29_20261015/ACCEPTANCE_WITHDRAWN.json')
    assert withdrawn['withdrawn'] and withdrawn['superseded_by']==stage.name
    live=read(stage/'ACTIVATION_RECEIPT.json')
    assert all(live['health'][b]['release_signature']==evidence['formal_release_signatures'][b]for b in ('formal50','formal950'))
    assert reference['human_role_validity_verified'] is False and status['scientific_benchmark_admitted'] is False
    assert status['training_release'] is False and status['real_EB6_share_estimate_exists'] is False and status['physical_calibration_complete'] is False
    assert read(PUBLIC/'PUBLICATION_CHECK.json')['current_browser_actual_final_submission_verified'] is True
    source=read(PUBLIC/'SOURCE_SNAPSHOT.json')
    for row in source['source_files']:assert sha(ROOT/row['path'])==row['published_sha256'],row['path']
    manifest=read(PUBLIC/'RELEASE_MANIFEST.json');assert manifest['payload_file_count_excluding_manifest']==len(manifest['payload_files_excluding_this_manifest'])
    for row in manifest['payload_files_excluding_this_manifest']:
        p=ROOT/row['path'];assert p.stat().st_size==row['bytes']and sha(p)==row['sha256'],row['path']
    return {'passed':True,'current_boards_and_evidence_consistent':True,'source_files_verified':len(source['source_files']),'public_payload_files_verified':len(manifest['payload_files_excluding_this_manifest']),'case_acceptance_scope':10000,'actual_browser_pages_verified':1500,'same_displayed_outcomes':0,'human_validity_claim':False,'EP_started':False}

if __name__=='__main__':print(json.dumps(check(),sort_keys=True))
