"""Close substantive source/physical/material evidence; never starts an engine."""
import argparse,collections,datetime,os,subprocess,sys
from pathlib import Path

def main(stage):
    sys.path.insert(0,str(stage/'code'))
    from common import read,save,sha
    from cohort_gate import require_original50_acceptance,require_reviewed_ep
    first=require_original50_acceptance();second=read(stage/'OTHER950_CONTRAST_ACCEPTANCE.json')
    assert first['passed']and second['passed']and second['substantive_decision_contrast_passed']
    reviews={};decisions={};new=reused=0
    for scope,n in [('original50',700),('other950',9500),('weather_sensitivity',520)]:
        lease=require_reviewed_ep(scope);p=read(stage/f'PHYSICS_{scope}_REVIEW.json');d=read(stage/f'SUBSTANTIVE_{scope}_REVIEW.json');ctrl=read(stage/f'CONTROL_SQL_{scope}_REVIEW.json')
        assert p['acceptance_passed']and not p['failures']and p['checked_pairs']==p['requested_pairs']==n
        assert p['input_signature_at_readback']==d['input_signature']==ctrl['input_signature']==lease['review']['input_signature']
        assert d['passed']and ctrl['passed']and not d['failures']and not ctrl['failures']
        reviews[scope]=p;decisions[scope]=d;new+=p['new_EP_sides'];reused+=p['exact_old_SQL_reused_sides']
    counts=collections.Counter();families=collections.Counter();mechanisms=collections.Counter();records=[];browser={};payload_count=0
    for batch,acc in [('formal50',first),('formal950',second)]:
        inp=read(stage/f'CONTRAST_{batch}_INPUT.json');r=read(stage/f'CONTRAST_{batch}_RELEASE_REVIEW.json');br=read(stage/f'BROWSER_{batch}_REVIEW.json')
        assert inp['passed']and r['passed']and br['passed']and br['visible_modeled_consequences_match_source']
        assert r['counts']['same_displayed_outcomes']==0 and r['counts']['actual_decision_relevant_cases']==inp['cases']
        counts.update(r['counts']);families.update(inp['families']);mechanisms.update(inp['actual_mechanisms']);records+=r['records'];browser[batch]=br['actual_browser_cases_checked']
        assert br['actual_browser_cases_checked']>=(500 if batch=='formal50'else 1000)
        for name,value in acc['evidence'].items():assert sha(stage/name)==value,name
        root=stage/('formal_release'+batch[6:]);manifest=read(root/'FORMAL_RELEASE.json')
        for name,value in manifest['files'].items():assert sha(root/name)==value;payload_count+=1
    assert counts['cases']==counts['actual_decision_relevant_cases']==10000 and counts['micro_requests']==0 and counts['same_displayed_outcomes']==0
    legacy=read(stage/'LEGACY_CONTRAST_QUEUE.json');priority={r['case_id']for r in legacy['priority41']};equal={r['case_id']for r in legacy['equal857']}
    assert {r['case_id']for r in records if r['was_equal857']}==equal
    assert {r['case_id']for r in records if r['was_priority41']}==priority
    assert all(not r['same_displayed_outcomes_now']for r in records)
    subprocess.run([sys.executable,'-B',str(stage/'code/audit_pilot.py')],check=True)
    env=dict(os.environ)
    # The compute runtime is the ancestor containing workspace/,not a guessed cwd.
    runtime=next(p for p in stage.parents if (p/'tools_v27').is_dir());env['EB_V27_TOOLS']=str(runtime/'tools_v27')
    subprocess.run([sys.executable,'-B',str(stage/'code/cluster_pilot.py')],env=env,check=True)
    inputs=read(stage/'INPUT_AUDIT.json');types=read(stage/'CLUSTER_COVERAGE1000_REVIEW.json')
    assert inputs['status']=='pass'and types['accepted_for_frozen1000_reference_production']and types['households']==1000
    original=read(stage.parent/'formal50_950_production_v28_20261014/ACTUAL_FEATURES1000.json');current=read(stage/'ACTUAL_FEATURES1000.json')
    assert {r['household_id']:r['features']for r in original['rows']}=={r['household_id']:r['features']for r in current['rows']}
    before={(c['household_id'],c['round_index']):c for c in read(stage.parent/'contrast_repair_v29_20261015/COMPILED1000.json')['records']}
    compiled=read(stage/'COMPILED1000.json')['records']
    modified={s:sum(c[s]['IDF_sha256']!=before[c['household_id'],c['round_index']][s]['IDF_sha256']for c in compiled)for s in ('A','B')}
    assert modified['A']==0
    summary={'schema':'eb.substantive_task_contrast_public.v30','passed':True,'cases':10000,'source_repaired_pairs':10000,
        'counts':dict(counts),'families':dict(families),'scenario_design_counts':dict(mechanisms),
        'A_household_policy_hardware_dates_mandatory_needs_and_common_history_unchanged':True,
        'priority41_repaired':41,'priority41_current_meaningful':41,'original_equal857_accounted':857,
        'original_equal857_still_equal_displayed':0,'previous_V29_equal992_now_equal_displayed':0,
        'source_only_repair_no_outcome_selection':False,'A_reference_trajectory_used':True,'B_EP_used_for_candidate_ranking':False,
        'energy_only_path_minimum_reference_delta_kWh':.1,'energy_difference_floor':None,
        'human_JND_validated':False,'human_response_labels_created':0,'actual_browser_pages_checked':browser,
        'actor_visible_consequences_verified':True,'actual_IDF_and_SQL_controls_verified':True,
        'original50_passed_before950_review':True,'all1000_fresh_EP_rerun':False,
        'new_EP_sides':new,'exact_unchanged_SQL_reused_sides':reused,'input_bound_run_sides':new+reused,
        'current_type_counts':types['actual_type_counts'],'all1000_type_feature_values_unchanged':True,
        'fresh_source_and_six_type_audit_passed':True,'actual_formal_payload_files_hash_checked':payload_count,
        'actual_modified_A_IDFs_from_V29':modified['A'],'actual_modified_B_IDFs_from_V29':modified['B'],
        'human_validity_proven':False,'scenario_counts_are_population_event_prevalence':False,
        'other950_used_for_rule_development':True,'other950_is_unseen_scientific_holdout':False,
        'rule_revision':'v30.3;whole-window hotwater rule and at-least2C operative AC layer;V30.1 andV30.2 failures archived'}
    assert new+reused==21440
    save(stage/'PUBLIC_CONTRAST_SUMMARY.json',summary)
    complete={'schema':'eb.substantive_physical_production_complete.v30','passed':True,'baseline_households':1000,
        'baseline_pairs':10000,'baseline_IDF_inputs':20000,'verified_input_bound_run_sides':21440,
        'formal50_physics':sha(stage/'PHYSICS_original50_REVIEW.json'),'formal950_physics':sha(stage/'PHYSICS_other950_REVIEW.json'),
        'weather_physics':sha(stage/'PHYSICS_weather_sensitivity_REVIEW.json'),
        'original50_final_acceptance_sha256':sha(stage/'ORIGINAL50_CONTRAST_ACCEPTANCE.json'),
        'other950_final_acceptance_sha256':sha(stage/'OTHER950_CONTRAST_ACCEPTANCE.json'),
        'public_contrast_summary_sha256':sha(stage/'PUBLIC_CONTRAST_SUMMARY.json'),
        'current_source_input_audit_sha256':sha(stage/'INPUT_AUDIT.json'),'current_type_audit_sha256':sha(stage/'CLUSTER_COVERAGE1000_REVIEW.json'),
        'input_signatures':{scope:p['input_signature_at_readback']for scope,p in reviews.items()},
        'formal_release_signatures':{b:read(stage/('formal_release'+b[6:])/'FORMAL_RELEASE.json')['release_signature']for b in ('formal50','formal950')},
        'substantive_evidence':{scope:sha(stage/f'SUBSTANTIVE_{scope}_REVIEW.json')for scope in reviews},
        'control_SQL_evidence':{scope:sha(stage/f'CONTROL_SQL_{scope}_REVIEW.json')for scope in reviews},
        'new_EP_sides':new,'exact_unchanged_SQL_reused_sides':reused,'all1000_fresh_EP_rerun':False,
        'school_only_physics':True,'all_scoped_physical_reviews_fresh':True,'substantive_task_contrast_verified':True,
        'human_role_validity_verified':False,'field_calibration':False,'training_release':False,'scientific_benchmark_admitted':False,
        'closed_utc':datetime.datetime.now(datetime.timezone.utc).isoformat()}
    save(stage/'PHYSICAL_PRODUCTION_COMPLETE.json',complete);print(summary,flush=True)
if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--stage',type=Path,required=True);main(p.parse_args().stage.resolve())
