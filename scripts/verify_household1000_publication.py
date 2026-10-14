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

if __name__=='__main__':print(json.dumps(check(),sort_keys=True))
