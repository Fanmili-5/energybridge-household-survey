"""Read-only behavioral audit; writes findings only, never participant records or API calls."""
import json
import sys
from common import ROOT,UPSTREAM,normalize_answers,file_hash,write_json
from paired_contract import LOOKUP,prepare,validate
from proposal_contract import executable,decision_record
from verify_paired_physics import answers

def main():
    folder=ROOT/'data/web/29e1de81519e1dbb58c7961343cd64c6'
    job=json.loads((folder/'job.json').read_text());row=json.loads((folder/'sft_candidate.json').read_text())
    sys.path.insert(0,str(UPSTREAM))
    from energybridge.harness.roleplay import normalize_roleplay_acceptance_response
    try:
        normalize_roleplay_acceptance_response(json.loads(row['messages'][-1]['content']),expected_baseline=.5)
        compatibility={'accepted':True}
    except Exception as exc:
        compatibility={'accepted':False,'error_type':type(exc).__name__,'error':str(exc)}
    raw=answers();raw['H_dishwasher']='night';profile=normalize_answers(raw,list(LOOKUP),LOOKUP)
    ordinary,scenario=prepare(profile,'self_audit');scenario['decision_h']=16
    proposed=executable(ordinary);proposed['appliances']['dishwasher_start_h']=16
    early=validate(ordinary,proposed,scenario)
    scoreless=decision_record(job,{'choice':'accept',**{k:job['result'][k] for k in ('display_hash','original_plan_hash','proposal_plan_hash')}})
    raw['B05']=['none'];empty,empty_scenario=prepare(normalize_answers(raw,list(LOOKUP),LOOKUP),'self_audit')
    empty_p1=validate(empty,executable(empty),empty_scenario)
    event=job['scenario']['event'];overlaps=[]
    for d,r in job['original_plan']['devices'].items():
        if d=='ac' or not r.get('active'):continue
        start=job['result']['proposal_plan']['appliances'].get(d+'_start_h',r['start_h'])
        if start<event['end_h'] and start+r['duration_h']>event['trigger_h']:overlaps.append(d)
    a=json.loads((folder/'baseline/trace.json').read_text());b=json.loads((folder/'proposal/trace.json').read_text())
    report={'audit_scope':'current local code and saved engineering evidence; no source edits or new API generation',
       'eb_evaluator_contract':compatibility,
       'unmeasured_earliest_start':{'usual_start_h':ordinary['devices']['dishwasher']['start_h'],'assumed_earliest_h':ordinary['devices']['dishwasher']['earliest_h'],
          'accepted_proposal_start_h':early['appliances']['dishwasher_start_h'],'availability_question_present':False},
       'partial_labels_allowed':{k:scoreless[k] for k in ('choice','score','comfort_score','energy_score','vpp_score','comment')},
       'empty_intervention_allowed':{'p0':executable(empty),'p1':empty_p1},
       'vpp_semantic_difference':{'saved_case_id':job['id'],'event':event,'reduction_kwh':job['result']['prediction']['event_reduction_kwh'],
          'non_ac_devices_still_overlapping':overlaps,'upstream_non_ac_avoidance_would_pass':not overlaps},
       'physical_evidence':{'native_warning_count':a['warning_count'],'temperature_points_each':len(a['temperature']),
          'all_temperature_max_difference_c':max(abs(x['c']-y['c']) for x,y in zip(a['temperature'],b['temperature'])),
          'prefix_check':job['result']['prediction']['prefix_check']},
       'source_hashes_match_verified_run':{k:file_hash(ROOT/f)==job['result']['provenance'][k] for k,f in {'worker_sha256':'paired_worker.py','adapter_sha256':'paired_ep.py','contract_sha256':'paired_contract.py'}.items()},
       'human_export_rows':len((ROOT/'exports/plan_judgement_human_pilot_review.jsonl').read_text().splitlines()),
       'training_release':False}
    write_json(ROOT/'AUDIT_PAIRED_FINDINGS.json',report);print(json.dumps(report,ensure_ascii=False,indent=2))
if __name__=='__main__':main()
