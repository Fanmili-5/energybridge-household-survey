"""Automatic pre-EP evidence, implementation and purpose audit; no engine launch."""
import collections
from common import *
from ep_gate import input_signature
def main():
 school_guard();fails=[];checks={};purpose=read(OUT/'PURPOSE_CONTRACT.json');phys=read(OUT/'REFERENCE_PHYSICS_CONTRACT.json')
 evidence=read(OUT/'RULE_EVIDENCE.json');sources={s['id']:s for s in evidence['sources']}
 checks['primary_evidence_registry']=all(i in sources for i in ('S01','S11','S12','S13','S15','S16','S17','S18','S19','S20'))
 expected={'worlds':1000,'residents':2524,'episodes_per_world':10,'coverage_counts':[333,333,334]}
 checks['purpose_scope']=all(purpose[k]==v for k,v in expected.items()) and not purpose['coverage_is_population_ownership'] and purpose['external_human_answers']==0
 checks['shared_role_response_target']=purpose['estimand'].startswith('p(actor answer Y | assigned reference') and 'one global' in purpose['model'] and 'per-household' in purpose['model']
 checks['source_and_unknown_separation']=read(OUT/'CALENDAR_AUDIT.json')['unknown_employment_members']==1259 and read(OUT/'CALENDAR_AUDIT.json')['adult_code2_correct_has_work']==86
 checks['all1000_static_integrity']=read(OUT/'STATIC_REVIEW.json')['pairs']==10000 and not read(OUT/'INPUT_AUDIT.json')['failures'] and not read(OUT/'CALENDAR_AUDIT.json')['failures']
 checks['original50_physical_inputs']=read(OUT/'PHYSICAL_INPUT_AUDIT.json')['status']=='pass' and read(OUT/'PHYSICAL_INPUT_AUDIT.json')['diagnostic_IDFs_checked']==1300
 checks['all20000_IDF_bindings']=read(OUT/'IDF_BINDINGS20000.json')['IDF_count']==20000 and not read(OUT/'IDF_BINDINGS20000.json')['failed'] and not read(OUT/'IDF_INPUT_AUDIT.json')['failures']
 checks['single_causal_vehicle_ledger']=read(OUT/'VEHICLE_CAUSAL_NEGATIVE_CONTROLS.json')['status']=='pass'
 checks['realization_negative_controls']=read(OUT/'MECHANISM_NEGATIVE_CONTROLS.json')['status']=='pass'
 repair=read(OUT/'ACCEPTANCE_NEGATIVE_CONTROLS.json')
 checks['three_acceptance_repairs']=repair['status']=='pass' and repair['all_expected_behaviors_verified'] and repair['controls']>=23 and repair['EP_runs']==0 and all(sha(OUT/'code'/n)==v for n,v in repair['tested_code_sha256'].items())
 checks['design_not_resampled']=not read(OUT/'REVISION_PROVENANCE.json')['worlds_and_pairs_regenerated']
 checks['full1000_still_held']=not purpose['full1000_EP_allowed']
 chain=read(OUT/'EVIDENCE_CHAIN_REVIEW.json')
 checks['source_to_claim_review']=len(chain['rows'])==8 and chain['human_answers']==0 and not chain['full1000_EP_allowed'] and all(r['support'] and r['unknown'] for r in chain['rows'])
 checks['no_overwritten_bath_work']=read(OUT/'BATH_COMMITMENT_AUDIT.json')['status']=='pass' and read(OUT/'BATH_COMMITMENT_AUDIT.json')['counts']['household_days']==30000
 checks['same1000_role_materials']=read(OUT/'MATERIALS_AUDIT.json')['status']=='pass' and read(OUT/'MATERIALS_AUDIT.json')['counts']['consumer_tasks']==10000
 ui=read(OUT/'FRONTEND_BROWSER_REVIEW.json')
 checks['actual_browser_answer_isolation']=ui['status']=='pass' and ui['actual_browser_exports_compared']>=2 and ui['input_unchanged_when_all_answers_changed'] and ui['human_answers']==0
 checks['all500_browser_canonical_bindings']=read(OUT/'FRONTEND_BINDINGS_REVIEW.json')['status']=='pass' and read(OUT/'FRONTEND_BINDINGS_REVIEW.json')['case_bindings_verified']==500
 checks['shared_repaired_export_code']=len({sha(OUT/'frontend_release/households'/h['household_id']/'joint-view.js') for h in read(OUT/'SELECTION50.json')['records']})==1
 checks['same_original_frontend_axis']=read(OUT/'FRONTEND_CLOCK_REVIEW.json')['actual_cases_checked']==500 and not read(OUT/'FRONTEND_CLOCK_REVIEW.json')['question_contract_changed']
 curve=phys['temperature_curves']
 checks['bounded_native_model_input']=read(OUT/'REFERENCE_MODEL_AUDIT.json')['status']=='pass'
 checks['honest_original_curve_boundary']=not curve['coefficients_changed'] and not curve['bounds_widened'] and not phys['physical_calibration'] and curve['fit_or_manufacturer_data_origin'].startswith('unknown') and 'never relabel' in curve['production_result_policy']
 checks['finite_window_no_net_saving_claim']=not phys['window']['equal_service_net_savings_claim'] and not phys['window']['equal_state_recovery_claim']
 actual50={h['household_id'] for h in read(OUT/'SELECTION50.json')['records']};old50={h['household_id'] for h in read(PILOT/'SELECTION50.json')['records']}
 checks['original50_execution_scope']=actual50==old50 and len(actual50)==50 and purpose['production_gate'].endswith('no full1000 launch by default')
 texts=(OUT/'PRODUCTION_LOGIC_CHAIN.md').read_text()
 checks['complete_logic_and_estimation_scope']=all(k in texts for k in ['人口/住房统计框 →','先于计划的服务目的','范围外真实设备性能','不是卧室调查数','完整08→次08','Phase-2','812个','模型输入','共享模型'])
 for k,ok in checks.items():
  if not ok:fails.append({'check':k,'severity':'critical_reference_production','resolution':'correct evidence,method or output and rerun review; do not bypass'})
 signature,files=input_signature()
 current_output=(read(OUT/'READBACK_all_REVIEW.json') if (OUT/'READBACK_all_REVIEW.json').exists() else {})
 current50=(current_output.get('acceptance_passed') is True and current_output.get('readback_code_sha256')==sha(OUT/'code/physics.py') and current_output.get('checked_pairs')==500)
 report={'schema':'eb.pre_EP_scientific_and_purpose_review.v23','date':'2026-10-13','checks':checks,
 'critical_reference_findings':fails,'purpose_recheck_passed':checks['purpose_scope'] and checks['shared_role_response_target'] and checks['complete_logic_and_estimation_scope'],
 'reference_production_accepted':not fails,'allowed_EP_scopes':['original50'] if not fails else [],
 'input_signature':signature,'input_files':files,
 'accepted_claim':'traceable, internally coherent, declared reference worlds anchored to city ordinary-residential census controls, for later assigned-role responses',
 'not_accepted_claims':['validated off-design OEM performance','national detailed household behavior','actual resident consent','human role validity','predictive model performance','formal benchmark release'],
 'unresolved_external_evidence':['human role comprehension and role-information effect','independent heldout human answers','actual load/building/equipment calibration if field claims are wanted'],
 'physical_output_status':'current-ledger original50 readback passed; exact SQL reuse documented; final material/receipt closure separately required' if current50 else 'current ledger readback pending; exact physical input identity permits documented SQL reuse, not old acceptance reuse',
 'current_original50_readback_passed':current50,
 'national_behavior_validated':False,'formal_benchmark_release':False,'human_answers':0,
 'independent_peer_review':False,'full1000_EP_allowed':False}
 save(OUT/'PRE_EP_SCIENTIFIC_REVIEW.json',report);print({'reference_production_accepted':not fails,'checks':checks,'critical':fails,'allowed_EP_scopes':report['allowed_EP_scopes']},flush=True)
 if fails:raise RuntimeError(str(fails))
if __name__=='__main__':main()

