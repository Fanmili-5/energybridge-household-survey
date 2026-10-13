"""Close V23 reference-input and original50 acceptance; never starts EnergyPlus.

Physics receipts may precede the final material-only update. Their current
compiled scope and readback code must still match, every SQL and result is
rehashed, and final material bindings are checked against those results.
No human evidence or national/field-calibration claim is created here.
"""
import concurrent.futures,datetime as dt
from common import *
from ep_gate import require_reviewed_ep
from physics import scoped_rows,check_run_coverage,row_key,A_HARD_FAILURES

def main():
    school_guard();lease=require_reviewed_ep('original50');checks={};failures=[];physical_files={};unique_runs={};unique_pairs={}
    expected={'all':500,'sensitivity':200,'model_form':50}
    for scope,count in expected.items():
        rows=scoped_rows(scope);report=read(OUT/f'READBACK_{scope}_REVIEW.json');runs=read(OUT/f'EP_{scope}_REVIEW.json')['records']
        check_run_coverage(rows,runs)
        checks[scope+'_complete_current_readback']=(report.get('acceptance_passed') is True and report['requested_pairs']==count
            and report['checked_pairs']==count and report['expected_pairs']==count and not report['failures']
            and report['original_households_checked']==50 and report['complete_expected_runs_verified']
            and report['readback_code_sha256']==sha(OUT/'code/physics.py')
            and report['compiled_scope_sha256']==digest(sorted(rows,key=row_key))
            and report['run_receipts_sha256']==digest(sorted(runs,key=lambda r:(r['household_id'],r['round_index'],r['variant'],r['arm'])))
            and report['old_acceptance_report_reused'] is False and all(report[k]==0 for k in A_HARD_FAILURES))
        for c in rows:
            key=row_key(c);path=OUT/'readback'/c['variant']/c['household_id']/f'{c["round_index"]:02d}.json';r=read(path)
            if not (r['world_sha256']==c['world_sha256'] and r['pair_sha256']==c['pair_sha256'] and r['date']==c['date']
                    and r['variant']==c['variant'] and not r['energy_comparison_scope']['equal_service_net_saving_claim']):
                failures.append({'check':'current_readback_binding','key':key})
            physical_files[str(path.relative_to(OUT))]=sha(path);unique_pairs[key]=c
        for r in runs:
            key=(r['household_id'],r['round_index'],r['variant'],r['arm'])
            if key in unique_runs and unique_runs[key]!=r:raise RuntimeError('Conflicting scoped run receipts')
            unique_runs[key]=r
    def verify_run(item):
        key,r=item;c=unique_pairs[key[:3]];b=c[key[3]];sql=OUT/r['SQL_path'];receipt=sql.parent/'RUN_RECORD.json'
        ok=(sha(sql)==r['SQL_sha256'] and read(receipt)==r and r['current_ledger_sha256']==b['signal_ledger_sha256']
            and r['current_world_sha256']==c['world_sha256'] and r['current_pair_sha256']==c['pair_sha256']
            and r['physical_execution']=='verified_exact_reuse' and r['new_engine_launch'] is False
            and r['source_SQL_sha256']==r['SQL_sha256'])
        return key,ok,{str(sql.relative_to(OUT)):sha(sql),str(receipt.relative_to(OUT)):sha(receipt)}
    with concurrent.futures.ThreadPoolExecutor(max_workers=16) as pool:
        for key,ok,files in pool.map(verify_run,unique_runs.items()):
            physical_files.update(files)
            if not ok:failures.append({'check':'SQL_receipt_binding','key':key})
    checks['physical_unique_identity']=len(unique_runs)==1400 and len(unique_pairs)==700
    material=read(OUT/'MATERIALS_AUDIT.json');checks['full1000_materials']=(material['status']=='pass' and not material['failures']
        and material['counts']['actor_cards']==1000 and material['counts']['consumer_tasks']==10000
        and material['counts']['physical_pending_tasks']==9500 and material['actor_responses']==0)
    material_failures=[]
    for c in scoped_rows('all'):
        path=OUT/'readback/base7'/c['household_id']/f'{c["round_index"]:02d}.json';r=read(path)
        consumer=read(OUT/'consumers'/c['household_id']/f'{c["round_index"]:02d}.json')
        if consumer['physical']['status']!='computed_reference' or consumer['bindings']['source_pair_sha256']!=c['pair_sha256']:
            material_failures.append([c['household_id'],c['round_index'],'identity'])
        for q in consumer['quantities']:
            if q['evidence_sha256']!=digest(r) or any(abs(q[s]['value']-r['energy'][q['scope']][s])>1e-10 for s in ('A','B')):
                material_failures.append([c['household_id'],c['round_index'],'energy'])
        if consumer['after_horizon']['terminal_states']!=r['terminal_states'] or not consumer['after_horizon']['status']=='reported_model_tail':
            material_failures.append([c['household_id'],c['round_index'],'terminal'])
    checks['current50_consequences_in_materials']=not material_failures
    browser=read(OUT/'FRONTEND_BROWSER_REVIEW.json');js_files={sha(OUT/'frontend_release/households'/h['household_id']/'joint-view.js') for h in read(OUT/'SELECTION50.json')['records']}
    browser_exports=[read(OUT/r['path']) for r in browser['source_files']]
    checks['actual_browser_export_bytes']=(len(browser_exports)==2 and all(sha(OUT/r['path'])==r['sha256'] for r in browser['source_files'])
        and browser_exports[0]['input']==browser_exports[1]['input']
        and browser_exports[0]['test_feedback']!=browser_exports[1]['test_feedback']
        and all(r['human_label_count']==0 and r['formal_export_eligible'] is False for r in browser_exports))
    visible_case=browser_exports[0]['audit']['source_case'];identity=visible_case['identity']
    current_consumer=read(OUT/'consumers'/identity['role_id']/f'{identity["round_index"]:02d}.json')
    checks['browser_uses_current_case']=(all(visible_case[k]==v for k,v in current_consumer.items() if k!='bindings')
        and visible_case['physical']['status']=='computed_reference'
        and browser_exports[1]['audit']['source_case']==visible_case)
    checks['actual_original_frontend_export']=(browser['status']=='pass' and browser['actual_browser_exports_compared']>=2
        and browser['input_unchanged_when_all_answers_changed'] and browser['human_answers']==0
        and len(js_files)==1 and browser['tested_renderer_sha256'] in js_files and browser.get('current_V23_browser_verified') is True)
    weather=read(OUT/'WEATHER_SOLVER_REVIEW.json');checks['weather_failure_honestly_retained']=(weather['verification_pass']
        and weather['strict_point_reference_agreement_pass'] is False and not weather['warnings_suppressed']
        and weather['household_EP_launches']==0 and weather['weather_only_diagnostic_launches']==1)
    model=read(OUT/'MODEL_FORM_SENSITIVITY.json');checks['model_form_original_retained']=(model['households']==50 and model['verified_runs']==100
        and model['native_original_EB_reference_replaced'] is False and model['no_favorable_model_selected'])
    controls=read(OUT/'ACCEPTANCE_NEGATIVE_CONTROLS.json');checks['gate_code_bound_negative_controls']=(controls['status']=='pass'
        and controls['controls']>=23 and controls['all_expected_behaviors_verified']
        and all(sha(OUT/'code'/n)==v for n,v in controls['tested_code_sha256'].items()))
    inputs=read(OUT/'INPUT_AUDIT.json');checks['bad_B_preserved_without_human_labels']=(inputs['counts']['A_failed_operations']==0
        and inputs['counts']['B_failed_operations']>0 and inputs['counts']['B_undelivered']>0 and inputs['human_answers']==0)
    provenance=read(OUT/'REVISION_PROVENANCE.json');checks['design_and_original_dates_preserved']=not provenance['worlds_and_pairs_regenerated']
    purpose=read(OUT/'PURPOSE_CONTRACT.json');checks['purpose_and_full1000_hold']=(not purpose['full1000_EP_allowed']
        and purpose['external_human_answers']==0 and 'one global' in purpose['model'] and not purpose['coverage_is_population_ownership'])
    for k,ok in checks.items():
        if not ok:failures.append({'check':k})
    final_lease=require_reviewed_ep('original50');checks['input_seal_unchanged']=lease['files']==final_lease['files']
    if not checks['input_seal_unchanged']:failures.append({'check':'input_seal_unchanged'})
    artifact_names=['PRE_EP_SCIENTIFIC_REVIEW.json','ACCEPTANCE_NEGATIVE_CONTROLS.json','RESULT_REUSE_REVIEW.json',
        'INPUT_AUDIT.json','CALENDAR_AUDIT.json','IDF_INPUT_AUDIT.json','PHYSICAL_INPUT_AUDIT.json','MATERIALS_AUDIT.json',
        'FRONTEND_BINDINGS_REVIEW.json','FRONTEND_CLOCK_REVIEW.json','FRONTEND_BROWSER_REVIEW.json','MODEL_FORM_SENSITIVITY.json',
        'WEATHER_SOLVER_REVIEW.json','EVIDENCE_CHAIN_REVIEW.json','REVISION_PROVENANCE.json']
    artifact_names += [f'{prefix}_{scope}_REVIEW.json' for prefix in ('READBACK','EP') for scope in expected]
    artifacts={n:sha(OUT/n) for n in artifact_names};checked_at=dt.datetime.now(dt.timezone.utc).isoformat()
    report={'schema':'eb.final_reference_acceptance.v23','checked_utc':checked_at,'status':'fail' if failures else 'pass',
        'checks':checks,'failures':failures,'material_failures':material_failures,'input_signature':final_lease['review']['input_signature'],
        'input_files_checked':len(final_lease['files']),'input_files_sha256':digest(final_lease['files']),
        'artifacts':artifacts,'physical_output_files':physical_files,
        'scope':{'reference_input_households':1000,'reference_residents':2524,'AB_pairs':10000,'IDF_inputs':20000,
            'current_physical_households':50,'base_pairs':500,'sensitivity_pairs':200,'model_form_pairs':50,
            'unique_verified_physical_runs':1400,'new_household_EP_launches':0,'weather_only_diagnostic_launches':1},
        'accepted_claim':'source-aware coherent declared reference inputs; current-ledger original50 reference consequences',
        'scientific_benchmark_admitted':False,'national_behavior_validated':False,'physical_calibration_complete':False,
        'human_answers':0,'human_role_validity_verified':False,'full1000_EP_allowed':False,'other950_executed':False,
        'whole_program_scientific_completion':False,'independent_peer_review':False,
        'limitations':['aggregate controls do not identify the full detailed joint population',
            'exact clocks,preferences,coverage and service goals are given reference conditions',
            'native curve clipping and strict wetbulb point disagreement retained',
            'finite unequal terminal states; no equal-service net-saving claim',
            'human comprehension,role-information effect and independent labels absent']}
    save(OUT/'FINAL_ACCEPTANCE.json',report)
    if failures:raise RuntimeError('Final reference acceptance failed: '+str(failures[:10]))
    save(OUT/'DELIVERY.json',{'schema':'eb.reference_delivery.v23','date':'2026-10-13','stage':OUT.name,
        'design_data_version':'v22','validation_version':'v23','final_acceptance_sha256':sha(OUT/'FINAL_ACCEPTANCE.json'),
        'input_signature':report['input_signature'],'scope':report['scope'],'artifacts':artifacts,
        'final_acceptance_status':'pass','collection_release':False,'training_release':False,
        'human_answers':0,'scientific_benchmark_admitted':False,'full1000_EP_allowed':False})
    print({k:v for k,v in report.items() if k not in ('physical_output_files','artifacts')},flush=True)
if __name__=='__main__':main()
