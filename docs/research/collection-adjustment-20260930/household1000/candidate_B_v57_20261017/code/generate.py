"""Finalize B56 joint explanations and SOC timing; retain every executable command."""
import argparse,collections,shutil
from concurrent.futures import ProcessPoolExecutor
from common import *
from joint_nodes import reconcile
from ev_continuity import continuous_reference
from events import response_reference

def schedule_payload(plan):
    p=copy.deepcopy(plan);p.pop('program_request_plans',None)
    for t in p['tasks']:t.pop('request_formation',None)
    return p

def revise(w,old,sig,ref):
    p=copy.deepcopy(old);node=reconcile(p)
    ev=continuous_reference(w,p,p['B'])
    previous=old['EV_continuous_reference']
    if ev['status']!='not_installed'and any(ev[k]!=previous[k]for k in('A','B','events','initial_energy_kWh','interval_min','changed_need_ids')):raise ValueError('EV_PHYSICAL_TRAJECTORY_CHANGED')
    p['EV_continuous_reference']=ev
    p['VPP_response_reference']=response_reference(w,p,p['B'],p['VPP_events'],p['assessment_B'],ev)
    for e in p['classification']['actual_actions']['events']:e['EV_event_state_reference']['continuous_reference_sha256']=digest(ev)
    p.update(schema='eb.alternative_pair.v57',rules_sha256=sig,source_generation_rules_sha256=sig,
      revision_parent={'stage':PARENT_B.name,'case_path':ref['path'],'case_sha256':ref['sha256'],'seal_sha256':sha(PARENT_B/'FINAL_SEAL.json')},
      semantic_finalization={'schema':'eb.joint_node_SOC_time.v57','node_audit':node,'B56_executable_schedule_preserved':True,'A46_and_daily_demands_preserved':True,'only_associations_and_continuous_time_interpretation_changed':True,'no_outcome_selection':True},
      original_schedule_generation={'stage':PARENT_B.name,'rules_sha256':old['rules_sha256'],'proposal_strength_schema':old['proposal']['strength_schema']},
      B_frozen_sha256=digest(p['B']),classification_only_update=False)
    p.pop('pair_content_sha256',None);p['pair_content_sha256']=digest(p)
    if schedule_payload(p['B'])!=schedule_payload(old['B']):raise ValueError('B56_EXECUTABLE_SCHEDULE_CHANGED')
    return p

def one(job):
    row,run,sig=job;run=Path(run);world=None;rounds=[];counts=collections.Counter()
    for rr in row['rounds']:
        src=PARENT_B/rr['path']
        if sha(src)!=rr['sha256']:raise ValueError('PARENT_PAIR_CHANGED')
        old=read(src)
        if world is None:
            wp=A_STAGE/old['A_source']['world_path']
            if sha(wp)!=old['A_source']['world_sha256']:raise ValueError('A46_WORLD_CHANGED')
            world=read(wp)
        p=revise(world,old,sig,rr);path=run/'pairs'/row['household_id']/(p['date']+'.json.gz');path.parent.mkdir(parents=True,exist_ok=True)
        path.write_bytes(gzip.compress((canonical(p)+'\n').encode(),compresslevel=6,mtime=0))
        item={**rr,'path':rel(path),'sha256':sha(path),'parent_B56_sha256':rr['sha256']};rounds.append(item)
        counts['cases']+=1;counts['stale_A_anchors_corrected']+=len(p['semantic_finalization']['node_audit']['stale_original_A_anchors'])
        v=p['VPP_response_reference']['EV_continuous_impact']
        if ev_installed:=v['status']!='not_installed':counts['EV_actual_match_earlier_than_confirmation']+=v['actual_stable_SOC_match_min']is not None and v['post_intervention_SOC_confirmation_min']is not None and v['actual_stable_SOC_match_min']<v['post_intervention_SOC_confirmation_min']
    result={**row,'rounds':rounds};save(run/'records'/(row['household_id']+'.json'),result);return result,dict(counts)

def main():
    parser=argparse.ArgumentParser();parser.add_argument('--workers',type=int,default=4);a=parser.parse_args();verify_inputs();sig=rules_id();run=OUT/'runs'/sig[:16]
    if (OUT/'FINAL_SEAL.json').exists():raise ValueError('SEALED_STAGE')
    for f in list((OUT/'code').glob('*.py'))+[OUT/'INPUT_LOCK.json',OUT/'GENERATION_RULES.json']:
        d=run/'source_snapshot'/f.name;d.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(f,d)
    rows=read(PARENT_B/'PAIR_BINDINGS10000.json')['records'];results=[];counts=collections.Counter()
    save(run/'RUN.json',{'rules_sha256':sig,'source':PARENT_B.name,'all_cases_used':True,'schedule_search_or_repair':False})
    with ProcessPoolExecutor(max_workers=a.workers)as pool:
        for i,(row,c)in enumerate(pool.map(one,[(r,str(run),sig)for r in rows]),1):
            results.append(row);counts.update(c)
            if i%200==0:print({'households':i},flush=True)
    assert rules_id()==sig and len(results)==1000 and counts['cases']==10000
    save(OUT/'PAIR_BINDINGS10000.json',{'schema':'eb.alternative_bindings.v57','rules_sha256':sig,'records':results,'households':1000,'cases':10000,'all10000_used_as_one_dataset':True,'source_B':PARENT_B.name})
    ids={r['household_id']for r in read(PARENT_B/'SUBSET50.json')['records']};subset=[r for r in results if r['household_id']in ids]
    save(OUT/'SUBSET50.json',{'schema':'eb.alternative_subset.v57','records':subset,'type_counts':dict(collections.Counter(r['type']for r in subset)),'same_pairs_and_hashes':True,'separate_generation':False})
    save(OUT/'BUILD_REVIEW.json',{'passed':True,'rules_sha256':sig,'counts':dict(counts),'no_case_filtered_or_rescheduled':True});print(canonical(dict(counts)))
if __name__=='__main__':main()
