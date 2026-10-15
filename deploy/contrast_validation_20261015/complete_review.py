"""Close independently scoped receipts without starting EP or changing source inputs."""
import argparse,collections,hashlib,json,sys,os,subprocess
from pathlib import Path

def run(stage):
    sys.path.insert(0,str(stage/'code'))
    from common import read,save,sha
    from cohort_gate import require_reviewed_ep,require_original50_acceptance,audit_inputs
    first=require_original50_acceptance();second=read(stage/'OTHER950_CONTRAST_ACCEPTANCE.json');assert second['passed']
    payload_files=0
    for batch in('formal50','formal950'):
        root=stage/('formal_release'+batch[6:]);manifest=read(root/'FORMAL_RELEASE.json')
        for name,value in manifest['files'].items():assert sha(root/name)==value;payload_files+=1
    reviews={};new=0;reused=0
    for scope in('original50','other950','weather_sensitivity'):
        lease=require_reviewed_ep(scope);p=read(stage/f'PHYSICS_{scope}_REVIEW.json')
        assert p['acceptance_passed']and p['input_signature_at_readback']==lease['review']['input_signature']
        assert p['checked_pairs']==p['requested_pairs']and not p['failures']
        assert audit_inputs(scope)['passed']
        if scope!='original50':assert lease['review']['original50_final_acceptance_sha256']==sha(stage/'ORIGINAL50_CONTRAST_ACCEPTANCE.json')
        reviews[scope]=p;new+=p['new_EP_sides'];reused+=p['exact_old_SQL_reused_sides']
    assert second['input_signature']==reviews['other950']['input_signature_at_readback']
    for acceptance in(first,second):
        for name,value in acceptance['evidence'].items():assert sha(stage/name)==value
    counts=collections.Counter();mechanisms=collections.Counter();records=[];changes=0
    for batch in('formal50','formal950'):
        r=read(stage/f'CONTRAST_{batch}_RELEASE_REVIEW.json');assert r['passed'];counts.update(r['counts']);records+=r['records'];inp=read(stage/f'CONTRAST_{batch}_INPUT.json');changes+=inp['changed_pairs'];mechanisms.update(inp['actual_mechanisms'])
    assert counts['cases']==10000 and counts['micro_requests']==0 and counts['repaired_priority41']==41
    legacy=read(stage/'LEGACY_CONTRAST_QUEUE.json');assert {r['case_id']for r in records if r['was_equal857']}=={r['case_id']for r in legacy['equal857']}
    assert {r['case_id']for r in records if r['was_priority41']}=={r['case_id']for r in legacy['priority41']}
    equal_classes=collections.Counter(r['class']for r in records if r['was_equal857']);equal_current=sum(r['same_displayed_outcomes_now']for r in records if r['was_equal857'])
    priority=collections.Counter(r['class']for r in records if r['was_priority41'])
    # B changes also invalidate old pair-hash provenance in type receipts,
    # although the type extractor uses frozen calendars/needs/policies.
    subprocess.run([sys.executable,'-B',str(stage/'code/audit_pilot.py')],check=True)
    env={**os.environ,'EB_V27_TOOLS':'/home/hku_user3/energybridge-compute/research_runs/household1000_random10_20261007_v1/tools_v27'}
    subprocess.run([sys.executable,'-B',str(stage/'code/cluster_pilot.py')],env=env,check=True)
    type_audit=read(stage/'INPUT_AUDIT.json');types=read(stage/'CLUSTER_COVERAGE1000_REVIEW.json')
    assert type_audit['status']=='pass'and types['accepted_for_frozen1000_reference_production']and types['households']==1000
    prior=read(stage.parent/'formal50_950_production_v28_20261014/ACTUAL_FEATURES1000.json')
    current=read(stage/'ACTUAL_FEATURES1000.json')
    assert {r['household_id']:r['features']for r in current['rows']}=={r['household_id']:r['features']for r in prior['rows']}
    summary={'schema':'eb.task_contrast_public_summary.v29','passed':True,'cases':10000,'source_repaired_pairs':changes,'counts':dict(counts),'priority41_repaired':41,'priority41_final_classes':dict(priority),
      'original_equal857_accounted':857,'original_equal857_current_classes':dict(equal_classes),'original_equal857_still_equal_displayed':equal_current,
      'A_household_policy_hardware_dates_mandatory_needs_and_common_history_unchanged':True,'source_only_repair_no_outcome_selection':True,
      'same_outcome_tasks_explicitly_annotated':True,'energy_difference_floor':None,'human_JND_validated':False,'human_response_labels_created':0,
      'actual_browser_pages_checked':{b:read(stage/f'BROWSER_{b}_REVIEW.json')['actual_browser_cases_checked']for b in('formal50','formal950')},
      'original50_passed_before950_review':True,'all1000_fresh_EP_rerun':False,'new_EP_sides':new,'exact_unchanged_SQL_reused_sides':reused,'input_bound_run_sides':new+reused,
      'fresh_source_and_six_type_audit_passed':True,'all1000_type_feature_values_unchanged':True,'current_type_counts':types['actual_type_counts']}
    summary.update(actual_formal_payload_files_hash_checked=payload_files,scenario_design_counts=dict(mechanisms),scenario_counts_are_population_event_prevalence=False)
    assert new+reused==21440
    save(stage/'PUBLIC_CONTRAST_SUMMARY.json',summary)
    complete={'schema':'eb.contrast_physical_production_complete.v29','passed':True,'baseline_households':1000,'baseline_pairs':10000,'baseline_IDF_inputs':20000,
      'formal50_physics':sha(stage/'PHYSICS_original50_REVIEW.json'),'formal950_physics':sha(stage/'PHYSICS_other950_REVIEW.json'),'weather_physics':sha(stage/'PHYSICS_weather_sensitivity_REVIEW.json'),
      'original50_final_acceptance_sha256':sha(stage/'ORIGINAL50_CONTRAST_ACCEPTANCE.json'),'other950_final_acceptance_sha256':sha(stage/'OTHER950_CONTRAST_ACCEPTANCE.json'),
      'public_contrast_summary_sha256':sha(stage/'PUBLIC_CONTRAST_SUMMARY.json'),'parent_V28_complete_sha256':sha(stage.parent/'formal50_950_production_v28_20261014/PHYSICAL_PRODUCTION_COMPLETE.json'),
      'current_source_input_audit_sha256':sha(stage/'INPUT_AUDIT.json'),'current_type_audit_sha256':sha(stage/'CLUSTER_COVERAGE1000_REVIEW.json'),
      'input_signatures':{scope:p['input_signature_at_readback']for scope,p in reviews.items()},
      'formal_release_signatures':{batch:read(stage/('formal_release'+batch[6:])/'FORMAL_RELEASE.json')['release_signature']for batch in('formal50','formal950')},
      'school_only_physics':True,'all_scoped_physical_reviews_fresh':True,'new_EP_sides':new,'exact_unchanged_SQL_reused_sides':reused,'verified_input_bound_run_sides':new+reused,
      'human_role_validity_verified':False,'field_calibration':False,'training_release':False,'scientific_benchmark_admitted':False}
    save(stage/'PHYSICAL_PRODUCTION_COMPLETE.json',complete);print(json.dumps(summary,ensure_ascii=False),flush=True)
if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--stage',type=Path,required=True);a=p.parse_args();run(a.stage.resolve())
