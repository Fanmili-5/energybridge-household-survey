"""Verify and seal original50 production plus the predeclared diagnostics."""
import argparse
import collections
from concurrent.futures import ProcessPoolExecutor
from core import *
from finalize import verify_case


def checked(item):
    row,case,record,label=item
    audit=verify_case(item);config=read(ROOT/'results'/label/'RUN_CONFIG.json');setting=config['settings']
    for side in ('A','B'):
        folder=ROOT/'results'/label/row['household_id']/case['date']/side
        result=read(folder/'RESULT.json')
        expected=digest({'pair':case['source_pair_sha256'],'side':side,'pack':sha(ROOT/row['path']),
            'physics':physics_hash(),'history':setting['history'],'engine_sha256':config['engine_sha256'],
            'reference_ACH':setting['ACH'],'portal_flow_scale':setting['portal_scale']})
        if expected!=result['fingerprint']:audit['errors'].append(side+'_PHYSICAL_FINGERPRINT')
    summary=read(ROOT/record['path'])
    if summary['common_history_max_normalized_error']>1e-7:audit['errors'].append('COMMON_PREDECISION_STATE')
    if not summary['specified_initial_state']['A_B_common_state_verified']:audit['errors'].append('SPECIFIED_INITIAL_STATE')
    for side in ('A','B'):
        if summary[side]['exhaust_makeup_mass_balance']['maximum_residual_kg_s']>5e-5:audit['errors'].append(side+'_MASS_BALANCE')
    return audit


def main(workers):
    manifest=read(ROOT/'INPUT_MANIFEST.json');assert len(manifest['records'])==50
    byid={c['case_id']:(r,c)for r in manifest['records']for c in r['cases']};assert len(byid)==500
    selection=read(ROOT/'SENSITIVITY_SELECTION.json');sensitivity=read(ROOT/'SENSITIVITY_REVIEW.json')
    assert sensitivity['passed']and sensitivity['physics_sha256']==physics_hash()
    assert sensitivity['cases']==200 and sensitivity['comparisons']==632
    for name in ('CROSS_PLATFORM_REVIEW.json','REGRESSION_RESULTS.json'):
        r=read(ROOT/name);assert r['passed']and r['physics_sha256']==physics_hash(),name
    jobs=[]
    for label in ['pilot50',*selection['groups']]:
        runs=read(ROOT/'results'/label/'RUN_BINDINGS.json');review=read(ROOT/'results'/label/'REVIEW.json')
        config=read(ROOT/'results'/label/'RUN_CONFIG.json')
        assert runs['passed']and review['passed']and config['physics_sha256']==physics_hash(),label
        if label=='pilot50':
            assert config['selection_sha256']in(sha(ROOT/'SENSITIVITY_SELECTION.json'),sha(ROOT/'SENSITIVITY_SELECTION_INITIAL.json'))
        else:assert config['selection_sha256']==sha(ROOT/'SENSITIVITY_SELECTION.json')
        assert {r['case_id']for r in runs['records']}=={r['case_id']for r in review['records']}
        for record in review['records']:
            row,case=byid[record['case_id']];jobs.append((row,case,record,label))
    assert len(jobs)==1132
    with ProcessPoolExecutor(max_workers=workers)as pool:audits=list(pool.map(checked,jobs,chunksize=2))
    errors=[{'case_id':a['case_id'],'errors':a['errors']}for a in audits if a['errors']]
    save(ROOT/'ARTIFACT_READBACK50.json',{'passed':not errors,'paired_runs_verified':len(audits),'production_pairs':500,
         'diagnostic_pairs':632,'errors':errors,'physics_sha256':physics_hash(),'full1000_deferred_by_user':True})
    assert not errors,errors[:5]
    review=read(ROOT/'results/pilot50/REVIEW.json');parent=ROOT.parent/'unified_physics50_v59_20261017'
    original={r['case_id']:r for r in read(parent/'PHYSICAL_BINDINGS50.json')['records']}
    assert sha(parent/'FINAL_SEAL50.json')=='cd3bdb6dd10290449a48e88334ae0986d0bc1ff3ab0e4b36fd537b14c2b72224'
    for record in review['records']:
        old=read(parent/original[record['case_id']]['path']);new=read(ROOT/record['path'])
        assert old['source_pair_sha256']==new['source_pair_sha256']
        assert old['source_B_constraint_flags']==new['source_B_constraint_flags']
        for side in ('A','B'):
            assert old[side]['source_schedule_hash']==new[side]['source_schedule_hash']
            assert old[side]['service_outcomes']==new[side]['service_outcomes']
            assert old[side]['EV_trips']==new[side]['EV_trips']
    types=dict(collections.Counter(r['type']for r in manifest['records']))
    assert types=={'A':5,'B':15,'C':16,'D':5,'E':4,'F':5}
    assert review['counts']['cases']==review['counts']['passed']==500
    assert review['counts'].get('no_executable_request_difference')==6
    bindings={'schema':VERSION,'households':50,'pairs':500,'same_master':True,'type_counts':types,
        'master_input_households':1000,'master_input_pairs':10000,'master_physics_accepted':False,
        'full1000_deferred_by_user':True,'subset_selection':'same original proportional50;no outcome selection',
        'A_stage':'normal_A_v46_20261017','B_stage':'candidate_B_v57_20261017','records':review['records'],
        'household_ids':sorted(manifest['subset50_ids']),'input_manifest_sha256':sha(ROOT/'INPUT_MANIFEST.json'),
        'physics_sha256':physics_hash(),'schedules_modified':False,'human_labels_created':0}
    save(ROOT/'PHYSICAL_BINDINGS50.json',bindings)
    save(ROOT/'ACCEPTANCE50.json',{'schema':VERSION,'reference_replay_verified':True,'households':50,'pairs':500,
        'production_engine_runs':1000,'seasonal_diagnostic_engine_runs':1264,
        'source_A46_B57_schedules_and_execution_failures_verified_unchanged':500,
        'production_counts':review['counts'],'VPP_relations':review['whole_VPP_event_relations'],
        'mass_balance_and_metering_verified':True,'sensitivity_cases':200,'sensitivity_comparisons':632,
        'sensitivity_not_all_robust':bool(sensitivity['sensitive_case_ids']),'field_calibration_claimed':False,'human_labels_created':0,
        'questionnaire_released':False,'full1000_deferred_by_user':True})
    contract=read(ROOT/'PHYSICS_CONTRACT.json')
    contract.update(schema='eb.reference_physics_contract.v61',physics_sha256=physics_hash(),
        thermal_environment_policy_sha256=sha(ROOT/'THERMAL_ENVIRONMENT_POLICY.json'),
        spot_exhaust='same reference capacities and activity schedules;native exhaust with geometry-linked makeup transfer',
        meter_scope='Facility=HVAC+water+equipment+lights+EV;HVAC includes background exhaust;VPP controlled portfolio excludes background exhaust',
        energy_comparison='observed primary/finite-horizon energy change;task completion,recovery and thermal exposure separate;no equivalent-comfort savings claim',
        historical_sensitivity='179 distinct112vs224 plus21 early-date7vsavailable-history comparisons;no duplicate clipped-history validation',
        portal_sensitivity='200 winter/spring/summer/autumn/extreme cases at0.5x/2x;16 extremes also0.175/0.7ACH')
    save(ROOT/'PHYSICS_CONTRACT.json',contract)
    save(ROOT/'SOURCE_PROVENANCE.json',{'source_physics_stage':parent.name,'source_physics_seal_sha256':sha(parent/'FINAL_SEAL50.json'),
         'input_manifest_identical':sha(ROOT/'INPUT_MANIFEST.json')==sha(parent/'INPUT_MANIFEST.json'),
         'A_stage':'normal_A_v46_20261017','B_stage':'candidate_B_v57_20261017',
         'schedule_or_failed_execution_changes':False,'all500_replayed_under_one_model_revision':True,
         'development_probe_failures_kept':['results/diagnosis0490'],'development_probes_not_used_as_production_results':True})
    excluded={'FILE_MANIFEST50.json.gz','FINAL_SEAL50.json','FINAL_VERIFICATION50.json','LOCAL_EVIDENCE_REVIEW50.json'}
    files=[]
    for p in sorted(ROOT.rglob('*')):
        if p.is_file()and p.name not in excluded and '__pycache__'not in p.parts and not p.name.startswith('._'):
            files.append({'path':str(p.relative_to(ROOT)),'sha256':sha(p),'bytes':p.stat().st_size})
    save(ROOT/'FILE_MANIFEST50.json.gz',{'schema':VERSION,'households':50,'pairs':500,'files':files,'source_files':manifest['source_files']})
    save(ROOT/'FINAL_SEAL50.json',{'schema':VERSION,'accepted':True,'households':50,'pairs':500,'files':len(files),
        'manifest_sha256':sha(ROOT/'FILE_MANIFEST50.json.gz'),'physical_bindings_sha256':sha(ROOT/'PHYSICAL_BINDINGS50.json'),
        'input_manifest_sha256':sha(ROOT/'INPUT_MANIFEST.json'),'physics_sha256':physics_hash(),'source_code_sha256':code_hash(),
        'full1000_deferred_by_user':True,'production_engine_runs':1000,'diagnostic_engine_runs':1264})
    assert all(sha(ROOT/r['path'])==r['sha256']for r in files)
    save(ROOT/'FINAL_VERIFICATION50.json',{'passed':True,'files_verified':len(files),'production_pairs':500,'diagnostic_pairs':632,
        'seal_sha256':sha(ROOT/'FINAL_SEAL50.json'),'full1000_deferred_by_user':True})
    print(canonical({'sealed':True,'files':len(files),'seal_sha256':sha(ROOT/'FINAL_SEAL50.json')}),flush=True)


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--workers',type=int,default=8);args=p.parse_args();main(args.workers)
