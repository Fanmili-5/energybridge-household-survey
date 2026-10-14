"""Case-free aggregates from frozen school receipts; never publishes task data."""
import collections,hashlib,json
from pathlib import Path

STAGE=Path(__file__).resolve().parents[1]
RECEIPTS=STAGE/'development/school_receipts'
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def read(n):return json.loads((RECEIPTS/n).read_text())
def save(n,d):
    (STAGE/n).write_text(json.dumps(d,ensure_ascii=False,indent=2)+'\n')
def evidence(names):return {n:sha(RECEIPTS/n)for n in names}

def main():
    a=read('FINAL_ACCEPTANCE.json');f=read('FROZEN_COMPOSITION1000.json')
    assert a['new_original50_reference_acceptance_passed']and f['original50_acceptance_sha256']==sha(RECEIPTS/'FINAL_ACCEPTANCE.json')
    assert sum(f['counts'].values())==1000 and not f['full1000_EP_allowed']
    save('PILOT_ACCEPTANCE_SUMMARY.json',{
        **{k:v for k,v in a.items()if k!='acceptance_inputs'},
        'actual_input_files_bound':len(a['acceptance_inputs']),
        'public_transformation':'removed private per-case file-hash map; full receipt retained on school',
        'private_receipt_sha256':sha(RECEIPTS/'FINAL_ACCEPTANCE.json'),
        'source_reports_sha256':evidence(['INPUT_AUDIT.json','CALENDAR_AUDIT.json','IDF_INPUT_AUDIT.json',
            'READBACK_all_REVIEW.json','READBACK_sensitivity_REVIEW.json','READBACK_model_form_REVIEW.json',
            'WEATHER_SOLVER_REVIEW.json','FRONTEND_BROWSER_REVIEW.json','FINAL_RULE_REGRESSION.json',
            'ACCEPTANCE_NEGATIVE_CONTROLS.json'])})
    s=read('COMPOSITION_SUPPORT1000.json')
    failure_counts=collections.Counter((typ,msg.split(':',1)[0])for h in s['candidate_rule_failures']for typ,msg in h['unsupported_rule_candidates'].items())
    save('FROZEN_COMPOSITION_SUMMARY.json',{
        **{k:v for k,v in f.items()if k!='type_assignment_for_future_generation'},
        'shares':{k:v/1000 for k,v in f['counts'].items()},
        'support':{k:v for k,v in s.items()if k not in ['unmatched','candidate_rule_failures']},
        'unmatched_households':len(s['unmatched']),
        'unsupported_candidate_households':len(s['candidate_rule_failures']),
        'unsupported_candidates':[{'type':t,'reason':r,'count':n}for (t,r),n in sorted(failure_counts.items())],
        'per_household_assignment_is_frozen_privately':True,
        'private_receipt_sha256':sha(RECEIPTS/'FROZEN_COMPOSITION1000.json'),
        'public_transformation':'removed private per-household assignments; retained method/counts/support/sensitivity/code hashes'})
    i=read('INPUT_AUDIT.json');st=read('STATIC_REVIEW.json');cal=read('CALENDAR_AUDIT.json')
    save('GENERATION50_SUMMARY.json',{'schema':'eb.original50_generation_summary.v27',
        'counts':i['counts'],'actual_type_counts':i['actual_type_counts'],
        'source_structural_anchors_unchanged':i['matched_source_structure_unchanged'],
        'source_employment_unknown_preserved':True,
        'distinct_actual_feature_rows_within_type':i['distinct_actual_feature_rows_within_type'],
        'proposal_mechanisms':st['proposal_mechanisms'],'unavailable_requested_mechanisms':st['unavailable_requested_mechanisms'],
        'A_constraint_flags':st['A_constraint_flags'],'B_constraint_flags':st['B_constraint_flags'],
        'all_original_dates_retained':st['all_original_dates_retained'],
        'bad_proposals_retained':True,'human_labels_generated':0,
        'calendar':{k:v for k,v in cal.items()if k not in ['records','failures']},
        'evidence_classification':{
            'direct_aggregate_statistics':'2020 census city ordinary-residential province/generation/room controls',
            'model_completion':'joint household size/generation and integer synthetic roster;not observed cell table',
            'matched_source_proxy':'CHFS household membership/relationship/coarsened age/work;unknown stays unknown',
            'reference_engineering':'matched housing prototype, EB device parameters, native bounded curves and weather',
            'researcher_given':'functional4to6 assets, activity clocks, EV access/licence, role preferences/permissions, protected services, q and type quotas',
            'human_observation':'none;acceptance/scores/reasons not generated'},
        'status':'pass','source_reports_sha256':evidence(['INPUT_AUDIT.json','STATIC_REVIEW.json','CALENDAR_AUDIT.json'])})
    allr=read('READBACK_all_REVIEW.json');sen=read('READBACK_sensitivity_REVIEW.json');mod=read('MODEL_FORM_SENSITIVITY.json');weather=read('WEATHER_SOLVER_REVIEW.json')
    comps=sen['sensitivity']['comparisons'];by={}
    for c in sorted(set(x['comparison']for x in comps)):
        xs=[x for x in comps if x['comparison']==c]
        by[c]={'households':len(xs),'max_absolute_A_minus_B_change_kWh':max(abs(x['A_minus_B_energy_difference_kWh'])for x in xs),
               'max_absolute_normal_A_energy_change_kWh':max(abs(x['living_day_A_energy_difference_kWh'])for x in xs)}
    weather_public={k:v for k,v in weather.items()if k not in ['comparisons','warning_records','affected_A_cases']}
    weather_public['affected_A_cases_count']=len(weather['affected_A_cases'])
    weather_public['minimal_reported_wetbulb_comparison']={k:v for k,v in weather['minimal_reported_wetbulb_comparison'].items()if k!='examples'}
    save('PHYSICS50_SUMMARY.json',{
        'households':50,'AB_pairs':500,'unique_household_engine_runs':1400,
        'run_variants':{'base7':1000,'prior14_seasonal7_seasonal14_extra':300,'nominal_temperature_modifier_diagnostic':100},
        'all':{k:v for k,v in allr.items()if k not in ['records','failures']},
        'sensitivity':by,'model_form':{k:v for k,v in mod.items()if k not in ['comparisons','records']},
        'native_curve_bound_clipping_disclosed':True,'native_model_not_replaced_by_diagnostic':True,
        'weather_diagnostic':weather_public,
        'weather_verification_claim':'weather-only attribution and returned-equation/bounds consistency; strict cross-branch point agreement remains false',
        'manufacturer_performance_or_household_field_calibration':False,
        'source_reports_sha256':evidence(['READBACK_all_REVIEW.json','READBACK_sensitivity_REVIEW.json','MODEL_FORM_SENSITIVITY.json','WEATHER_SOLVER_REVIEW.json'])})
    cluster=read('CLUSTER_COVERAGE50_REVIEW.json')
    save('CLUSTER_COVERAGE50_SUMMARY.json',{
        **{k:v for k,v in cluster.items()if k not in ['reference_mapping','ambiguous']},
        'ambiguous_count':len(cluster['ambiguous']),
        'private_actual_world_projection_records_removed':True,
        'source_report_sha256':sha(RECEIPTS/'CLUSTER_COVERAGE50_REVIEW.json')})
    for n in ['FRONTEND_BINDINGS_REVIEW.json','FRONTEND_CLOCK_REVIEW.json',
              'FRONTEND_BROWSER_REVIEW.json','ACCEPTANCE_NEGATIVE_CONTROLS.json','FINAL_RULE_REGRESSION.json']:
        d=read(n);assert not any(k in d for k in ['records','assignment','input_files'])
        # These reports are already case-free and part of the accepted input
        # signature. Preserve their actual bytes rather than reserialize them.
        (STAGE/n).write_bytes((RECEIPTS/n).read_bytes())
    save('FRONTEND50_SUMMARY.json',{'materials':read('MATERIALS_REVIEW.json'),
        'browser':read('FRONTEND_BROWSER_REVIEW.json'),'clock':read('FRONTEND_CLOCK_REVIEW.json'),
        'binding':read('FRONTEND_BINDINGS_REVIEW.json'),
        'current_public_live_site_updated':False,'new_materials_staged_and_verified_on_school':True,
        'human_trial_completed':False,'synthetic_export_fixtures_are_engineering_tests_only':True})
    print({'original50_acceptance':True,'frozen_counts':f['counts'],'public_case_free_reports':11})

if __name__=='__main__':main()
