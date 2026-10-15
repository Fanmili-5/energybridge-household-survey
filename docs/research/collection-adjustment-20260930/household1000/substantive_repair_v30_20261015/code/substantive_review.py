"""Independent negative controls and full scoped post-EP decision audit."""
import argparse,collections,copy
from common import *
from contrast_core import metrics
from decision_contrast import source_evidence,outcome_evidence,PARENT
from zone_controls import validate_plan,repair_legacy,idf_bindings

def controls():
    source=BASE/'formal50_950_production_v28_20261014'
    def case(cid):
        h=next(h for h in read(source/'SELECTION1000.json')['records']if h['household_id']==cid.split(':')[0])
        rr=next(rr for rr in h['rounds']if rr['case_id']==cid)
        return read(source/h['world_path']),read(source/rr['pair_path'])
    w,p=case('ordinary-v6-0004:2025-01-21')
    assert metrics(p)['admitted']and 'hotwater_temperature_tradeoff'in metrics(p)['dimensions']
    w,p=case('ordinary-v6-0010:2025-07-26')
    try:validate_plan(w,p['B'])
    except ValueError:orphan_rejected=True
    else:raise RuntimeError('Legacy orphan control unexpectedly admitted')
    fixed=repair_legacy(w,p);assert validate_plan(w,fixed['B'])
    w,p=case('ordinary-v6-0001:2025-03-22')
    c=read(OUT/'A_context'/p['household_id']/f'{p["round_index"]:02d}.json')
    assert metrics(p)['admitted']and not source_evidence(w,p,c)[0]['passed']
    r=read(PARENT/'readback/base7'/p['household_id']/f'{p["round_index"]:02d}.json')
    assert not outcome_evidence(p,r)['passed']
    w,p=case('ordinary-v6-0004:2025-10-24')
    c=read(OUT/'A_context'/p['household_id']/f'{p["round_index"]:02d}.json')
    assert p['proposal']['family']=='hotwater_preheat_tradeoff'and p['proposal']['amount']==40
    assert not source_evidence(w,p,c)[0]['passed']
    w,p=case('ordinary-v6-0001:2025-04-23')
    c=read(OUT/'A_context'/p['household_id']/f'{p["round_index"]:02d}.json')
    assert not source_evidence(w,p,c)[0]['passed']
    r=read(PARENT/'readback/base7'/p['household_id']/f'{p["round_index"]:02d}.json')
    assert not outcome_evidence(p,r)['passed']
    # An ordinary no-op with generic permission issues is never an admission.
    q=copy.deepcopy(p);q['B']=copy.deepcopy(q['A']);q['policy_assessment']['issues']=['confirmation_required_before_implementation']
    assert not source_evidence(w,q,c)[0]['passed']and not metrics(q)['admitted']
    previous=OUT/'development/rule_revision_v30_2'
    h=next(h for h in read(previous/'SELECTION1000.json')['records']if h['household_id']=='ordinary-v6-0104')
    rr=next(rr for rr in h['rounds']if rr['date']=='2025-09-16')
    weak=read(previous/rr['pair_path']);w=read(OUT/h['world_path']);c=read(OUT/'A_context'/h['household_id']/f'{rr["round_index"]:02d}.json')
    assert metrics(weak)['admitted']and not source_evidence(w,weak,c)[0]['passed']
    actual=read(previous/'readback/base7'/h['household_id']/f'{rr["round_index"]:02d}.json')
    assert not outcome_evidence(weak,actual)['passed']
    out={'schema':'eb.substantive_negative_controls.v30','passed':True,'hotwater_25C_difference_recognized':True,
        'orphan_unit_control_rejected':orphan_rejected,'shared_zone_projection_checked':True,
        'nonbinding_EV_window_rejected':True,'inactive_extra_AC_rejected':True,
        'within_event_compensated40min_heating_delay_rejected':True,
        'active_but_weak0_5C_AC_request_rejected':True,
        'generic_confirmation_noop_rejected':True,'actor_labels_generated':0,'EP_started':False}
    save(OUT/'CONTRAST_NEGATIVE_CONTROLS.json',out);print(out,flush=True)

def post(scope):
    from cohort_gate import require_reviewed_ep,scoped_rows
    lease=require_reviewed_ep(scope);rows=scoped_rows(scope);records=[];failures=[];bindings=[]
    for c in rows:
        p=read(OUT/c['pair_path']);w=read(OUT/c['world_path'])
        r=read(OUT/'readback'/c['variant']/c['household_id']/f'{c["round_index"]:02d}.json')
        assert r['pair_sha256']==c['pair_sha256']
        binding=idf_bindings(w,p,c);bindings+=binding;proof=outcome_evidence(p,r)
        if not proof['passed']:failures.append({'case_id':p['case_id'],'variant':c['variant'],'error':'NO_ACTUAL_DECISION_CONTRAST'})
        records.append({'case_id':p['case_id'],'variant':c['variant'],'passed':proof['passed'],'proof':proof,
            'readback_sha256':sha(OUT/'readback'/c['variant']/c['household_id']/f'{c["round_index"]:02d}.json')})
    baseline=[r for r in records if r['variant']=='base7']
    out={'schema':'eb.actual_substantive_contrast_review.v30','scope':scope,'passed':not failures,
        'pairs_checked':len(records),'baseline_pairs':len(baseline),'actual_control_bindings_checked':len(bindings),
        'failures':failures,'counts':dict(collections.Counter(k['kind']for r in baseline for k in r['proof']['paths'])),
        'input_signature':lease['review']['input_signature'],'human_validity_proven':False,
        'actor_answers_generated':0,'B_outcomes_used_for_ranking':False,'records':records}
    save(OUT/f'SUBSTANTIVE_{scope}_REVIEW.json',out)
    save(OUT/f'ACTUAL_CONTROL_BINDINGS_{scope}.json',{'passed':True,'records':bindings})
    print({k:v for k,v in out.items()if k!='records'},flush=True)
    if failures:raise RuntimeError('Substantive acceptance failed;do not regenerate isolated cases or unlock950')
if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--controls',action='store_true');p.add_argument('--scope',choices=['original50','other950','weather_sensitivity']);a=p.parse_args()
    controls()if a.controls else post(a.scope)
