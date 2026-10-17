"""Build all1000 paired alternatives; subset50 reuses those exact records."""
import argparse
import collections
import shutil
from concurrent.futures import ProcessPoolExecutor
from common import *
from event_proposals import make
from events import for_case,response_reference
from assess import assess
from planner import allocate
from temporal import event_relations
from functools import lru_cache
@lru_cache(maxsize=1)
def assignments():return read(OUT/'INPUT_COVERAGE_PLAN.json')['assignments']

def signals(plan,w):
    result={}
    for d in w['parameter_pack']['devices']:
        if 'ac'not in d['types']:continue
        relevant=[c for c in plan['controls']if c['asset_id']==d['asset_id']and c['kind']=='ac_setpoint']
        channels={k:[]for k in('available','fan_mode','heat_sp','cool_sp')}
        for minute in range(-1440,4320,10):
            x=next((c for c in relevant if c['start_min']<=minute<c['end_min']),None)
            for k,v in [('available',int(x is not None)),('fan_mode',x.get('fan_operating_mode',0)if x else 0),('heat_sp',x['heating_setpoint_C']if x else 5.),('cool_sp',x['cooling_setpoint_C']if x else 50.)]:channels[k].append(v)
        result[d['asset_id']]=channels
    return result

def one(job):
    row,run,sig=job;run=Path(run);hid=row['household_id'];rp=run/'records'/(hid+'.json')
    if rp.exists():return read(rp)
    try:
        wp=A_STAGE/row['A_world_path']
        if sha(wp)!=row['A_world_sha256']:raise ValueError('A_WORLD_BYTES_CHANGED')
        w=read(wp);rounds=[]
        for index,r in enumerate(row['cases']):
            p=A_STAGE/r['path']
            if sha(p)!=r['sha256']:raise ValueError('A_CASE_BYTES_CHANGED')
            c=read(p);c['VPP_events']=for_case(w,c);c['input_design_assignment']=assignments()[c['case_id']];plan,proposal=make(w,c,index)
            checkA=assess(w,c,c['A']);checkB=assess(w,c,plan)
            if checkA['integrity_errors']or checkA['constraint_flags']:raise ValueError('A_REAUDIT_FAILED:'+canonical(checkA))
            if checkB['integrity_errors']:raise ValueError('GENERATOR_INTEGRITY_ERROR:'+canonical(checkB['integrity_errors']))
            pair={'schema':'eb.alternative_pair.v48','case_id':c['case_id'],'household_id':hid,'date':c['date'],
                  'decision_min':DECISION,'primary_evaluation_min':[480,1920],'service_tail_end_min':4320,
                  'A_source':{'stage':A_STAGE.name,'case_path':r['path'],'case_sha256':r['sha256'],
                              'world_path':row['A_world_path'],'world_sha256':row['A_world_sha256'],
                              'annual_A_path':row['annual_A_path'],'annual_A_sha256':row['annual_A_sha256'],
                              'HVAC_components_path':row['HVAC_components_path'],'HVAC_components_sha256':row['HVAC_components_sha256']},
                  'source_world_content_sha256':c['source_world_content_sha256'],'parameter_pack_sha256':c['parameter_pack_sha256'],
                  'common_history_start_date':c['common_history_start_date'],'days':c['days'],
                  'thermal_control_context':c['thermal_control_context'],'needs_A':c['needs_A'],'needs_B':copy.deepcopy(c['needs_A']),
                  'A':c['A'],'A_frozen_sha256':digest(c['A']),'B':plan,'proposal':proposal,
                  'HVAC_signal_start_min':-1440,'HVAC_signal_step_min':10,
                  'HVAC_signals_A':c['HVAC_signals'],'HVAC_signals_B':signals(plan,w),
                  'assessment_A':checkA,'assessment_B':checkB,'VPP_events':c['VPP_events'],'VPP_response_reference':response_reference(w,c,plan,c['VPP_events'],checkB),
                  'event_relations':event_relations(c,plan,c['VPP_events']),'human_response':{'accepted':None,'scores':None,'reason':None},
                  'physical_results':None,'questionnaire_stimulus':None,'release_to_collection':False,
                  'rules_sha256':sig,'selection_or_regeneration_based_on_B_outcome':False}
            pair['pair_content_sha256']=digest(pair)
            path=run/'pairs'/hid/(c['date']+'.json');save(path,pair)
            rounds.append({'case_id':c['case_id'],'date':c['date'],'path':rel(path),'sha256':sha(path),
                           'mechanism':proposal['realized_mechanism'],'intensity':proposal['intensity_design'],
                           'given_constraints_feasible':checkB['given_constraints_feasible']})
        result={'household_id':hid,'type':row['type'],'passed':True,'A_record_sha256':digest(row),'rounds':rounds}
        save(run/'regeneration'/(hid+'.json'),{'household_id':hid,'rules_sha256':sig,'A_record_sha256':digest(row),'cases':len(rounds),
                                             'valid_B_failures_kept':sum(not r['given_constraints_feasible']for r in rounds),'source_cases_resampled':False})
    except Exception as error:
        result={'household_id':hid,'passed':False,'error':str(error),'rules_sha256':sig}
    save(rp,result);return result

def main():
    parser=argparse.ArgumentParser();parser.add_argument('--workers',type=int,default=4);parser.add_argument('--limit',type=int,default=1000);args=parser.parse_args()
    verify_inputs();sig=rules_id();run=OUT/'runs'/sig[:16]
    for p in list((OUT/'code').glob('*.py'))+[OUT/'INPUT_LOCK.json',OUT/'GENERATION_RULES.json']:
        dst=run/'source_snapshot'/p.name;dst.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(p,dst)
    save(run/'RUN.json',{'rules_sha256':sig,'household_limit':args.limit,'physical_results_pending':True,'human_labels_generated':0})
    rows=read(A_STAGE/'A_BINDINGS10000.json')['records'][:args.limit];records=[]
    save(OUT/'INPUT_COVERAGE_PLAN.json',allocate(rows))
    with ProcessPoolExecutor(max_workers=args.workers)as pool:
        for r in pool.map(one,[(row,str(run),sig)for row in rows]):
            records.append(r)
            if len(records)%25==0:print({'households':len(records),'generation_errors':sum(not r['passed']for r in records)},flush=True)
    if rules_id()!=sig:raise ValueError('CODE_CHANGED_DURING_RUN')
    failures=[r for r in records if not r['passed']]
    save(run/'BUILD_REVIEW.json',{'households':len(records),'generation_errors':failures,'rules_sha256':sig})
    if failures:print(canonical(failures[:5]));raise SystemExit(2)
    if len(records)==1000:
        save(OUT/'PAIR_BINDINGS10000.json',{'schema':'eb.alternative_bindings.v48','households':1000,'cases':10000,'rules_sha256':sig,'records':records})
        ids={r['household_id']for r in read(MASTER/'SUBSET50.json')['records']};subset=[r for r in records if r['household_id']in ids]
        save(OUT/'SUBSET50.json',{'schema':'eb.alternative_subset.v48','records':subset,'type_counts':dict(collections.Counter(r['type']for r in subset)),
                                'same_master_household_ids':True,'same_pairs_and_hashes':True,'separate_generation':False})
    print({'households_written':len(records),'cases_written':sum(len(r['rounds'])for r in records),'rules_sha256':sig},flush=True)

if __name__=='__main__':main()
