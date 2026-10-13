"""Publish scoped status only after the frozen V19 delivery has been verified."""
import hashlib
import json
import shutil
from pathlib import Path

N=Path(__file__).resolve().parents[1]
H=N.parent
R=H/'repair_execution_20261008_v1'

def read(p):return json.loads(p.read_text())
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def save(p,v):p.write_text(json.dumps(v,ensure_ascii=False,sort_keys=True,indent=2)+'\n')

def main():
    delivery=read(N/'DELIVERY.json');review=read(N/'DELIVERY_REVIEW.json');accept=read(N/'REPAIR_ACCEPTANCE.json')
    for f,value in delivery['files'].items():assert sha(N/f)==value,f
    assert review['households']==1000 and review['pairs']==10000 and review['IDFs']==20000
    assert review['original50_reference_pairs_checked']==500 and review['sensitivity_pairs_checked']==200
    assert review['human_answers']==0 and not review['other950_EP_executed']
    assert accept['original_frontend_engineering_accepted'] and not accept['whole_program_scientific_completion']
    old=H/'profile_conditioned_production_20261008_v18/DELIVERY.json'
    assert sha(old)=='aa59bf61672d0b38a2222e1d979683a48a94e97efcca1c220d49f2661e8dfbde'
    board_path=R/'EXECUTION_BOARD.json';archive=R/'EXECUTION_BOARD_before_v19.json'
    if not archive.exists():shutil.copyfile(board_path,archive)
    board=read(board_path)
    board.update(date='2026-10-09',production=N.name,baseline_production='roleplay_mixed_static1000_20261007_v17',
        baseline_kept=True,finalized_delivery='../'+N.name+'/DELIVERY.json',finalized_delivery_sha256=sha(N/'DELIVERY.json'),
        current_repair_candidate='../CURRENT_REPAIR_CANDIDATE.json',actual_human_answers=0,
        scoped_reference_implementation_complete=True,whole_program_scientific_completion=False,
        foundation_revisions_required=False,foundation_revision_acceptance_scope='declared reference implementation and original50 development checks only',
        not_only_G6_is_pending=True,remaining_empirical_evidence=['joint activity calibration','field physics calibration and strict wetbulb reference agreement','actual human readability/role effect/holdout responses'],
        latest_reference_repair_acceptance='../'+N.name+'/REPAIR_ACCEPTANCE.json',latest_reference_repair_acceptance_sha256=sha(N/'REPAIR_ACCEPTANCE.json'),
        design_realism_verdict='reference_repairs_verified_with_declared_limits_empirical_validity_pending',
        existing_complete_flags_scope='scoped reference checks; no national joint diary, field-calibration or human-validity claim')
    definitions={
        'G1':(['WORLD_BUILD_REVIEW.json','SOURCE_EMPLOYMENT_AGGREGATES.json','INPUT_AUDIT.json'],'unknown employment preserved; activity levels are declared conditions, not fitted national frequencies'),
        'G2':(['RULE_EVIDENCE.json','INPUT_AUDIT.json','STATIC_REVIEW.json'],'dated sleep/nap/care/resource/room calendars verified; transferred school prototype and normative rest windows, not actual joint diaries'),
        'G3':(['FIELD_EVIDENCE.md','INPUT_AUDIT.json','MATERIALS_REVIEW.json'],'service/program/retrieval and transport distinctions verified; willingness, licence and subjective tradeoffs remain unobserved'),
        'G4':(['STATIC_REVIEW.json','PROPOSAL_DIAGNOSTICS.json','SELECTION1000.json'],'frozen A and six B mechanisms verified; bad/zero/increasing proposals retained without human labels'),
        'G5':(['IDF_BINDINGS20000.json','READBACK_all_REVIEW.json','READBACK_sensitivity_REVIEW.json','WEATHER_SOLVER_REVIEW.json','STRICT_WEATHER_REFERENCE_COMPARISON.json'],'actual original50 occupancy/light/power/meter/service checks; strict wetbulb point agreement failed, field calibration and other950 outcomes absent'),
        'G6':(['ACTOR_BINDINGS.json','CONSUMER_BINDINGS.json','engineering_render_records/RENDER_REVIEW.json','HUMAN_PILOT_PROTOCOL.md','pilot_materials_v19/PILOT_PLAN.json'],'original frontend and dated facts/exports/pilot templates verified; actual human comprehension, role effect and holdout answers absent')}
    for g in board['required_repairs']:
        files,limits=definitions[g['id']];human=g['id']=='G6'
        g.update(complete=not human,implementation_complete=True,scoped_verification_complete=not human,
            engineering_verification_complete=True,scientific_admission_accepted=False,
            completion_scope='source-aware reference implementation and original50 development audit',
            status='v19_reference_implementation_verified_with_limits' if not human else 'v19_original_frontend_and_bound_readability_materials_verified_actual_human_evidence_pending',
            evidence=['../'+N.name+'/'+f for f in files],remaining_evidence_or_limits=limits)
        if human:g['pilot_materials']='../'+N.name+'/pilot_materials_v19/PILOT_PLAN.json'
    for p in board['work_packages']:
        p['implementation_stage']=N.name
        p['status']='v19_reference_implementation_verified_with_declared_evidence_scope' if p['id']!='E07' else 'bound_readability_and_blank_records_complete_actual_human_evidence_pending'
    board['completion_policy'].update(complete_means_scoped_reference_repair_only=True,all_six_complete_or_empirical_benchmark_claim=False,human_evidence_cannot_be_replaced_by_engineering_or_synthetic_answers=True)
    board['execution_scope'].update(EP_now_executed=True,EP_development_households='original selected50 only',original50_pairs=500,sensitivity_pairs=200,other950_EP='held; no outcomes substituted')
    board['reference_diagnostics']={k:review[k] for k in ('proposal_mechanisms','service_goal_and_trip_counts','known_warnings_retained_and_diagnosed','strict_weather_point_reference_agreement','sensitivity_maximum_AB_energy_difference_kWh')}
    board['reference_diagnostics']['event_outcomes']=accept['statistics']['service_and_event_counts']
    save(board_path,board)
    save(H/'CURRENT_REPAIR_CANDIDATE.json',{'stage':N.name,'delivery_path':N.name+'/DELIVERY.json','delivery_sha256':sha(N/'DELIVERY.json'),
        'package_receipt':N.name+'/PACKAGE_RECEIPT.json','execution_board':'repair_execution_20261008_v1/EXECUTION_BOARD.json',
        'baseline_static_pointer_unchanged':'CURRENT_STATIC_INPUTS.json','baseline_live50_pointer_unchanged':'CURRENT_TEST50.json',
        'preview_url_when_SSH_tunnel_active':'http://127.0.0.1:18789/household50','preview_mode':'original binary frontend; server read-only, existing local download mode',
        'households':1000,'pairs':10000,'IDF_inputs':20000,'reference_EP_households':50,'reference_EP_pairs':500,
        'other950_EP_executed':False,'human_answers':0,'collection_release':False,'training_release':False,'scientific_benchmark_validity_complete':False})
    save(H/'CURRENT_DESIGN_AUDIT.json',{'schema':'eb.current_design_audit.v2','date':'2026-10-09','dataset':N.name,
        'prior_audit_path':'design_realism_audit_20261008_v1/AUDIT.json','prior_audit_preserved':True,
        'audit_path':N.name+'/REPAIR_ACCEPTANCE.json','audit_sha256':sha(N/'REPAIR_ACCEPTANCE.json'),'report_path':N.name+'/README.md',
        'verdict':'reference_repairs_verified_with_declared_limits_empirical_validation_pending',
        'foundation_revisions_required':False,'foundation_acceptance_scope':'declared reference implementation only',
        'strict_weather_point_reference_agreement':False,'field_calibration':False,'human_role_validity':False,
        'actual_human_answers':0,'formal_benchmark_admitted':False,'dataset_modified':True})
    print({'stage':N.name,'reference_implementation_verified':True,'human_answers':0,'whole_scientific_completion':False},flush=True)

if __name__=='__main__':main()
