"""Update classification on all frozen B48 pairs, preserving every schedule byte value."""
import argparse,collections,shutil
from concurrent.futures import ProcessPoolExecutor
from common import *
from classify import update_pair

def one(job):
    row,run,sig=job;run=Path(run);hid=row['household_id'];record=run/'records'/(hid+'.json')
    if record.exists():return read(record)
    try:
        rounds=[];world=None
        for rr in row['rounds']:
            source=SOURCE_B/rr['path']
            if sha(source)!=rr['sha256']:raise ValueError('SOURCE_B_BYTES_CHANGED')
            p=read(source)
            if world is None:
                wp=A_STAGE/p['A_source']['world_path']
                if sha(wp)!=p['A_source']['world_sha256']:raise ValueError('SOURCE_A_WORLD_CHANGED')
                world=read(wp)
            source_ref={'stage':SOURCE_B.name,'case_path':rr['path'],'case_sha256':rr['sha256'],'rules_sha256':p['rules_sha256'],'seal_sha256':read(OUT/'INPUT_LOCK.json')['source_B_seal_sha256']}
            updated=update_pair(p,world,source_ref,sig)
            if updated['A']!=p['A']or updated['B']!=p['B']:raise ValueError('CLASSIFIER_EDITED_SCHEDULE')
            dst=run/'pairs'/hid/(p['date']+'.json');save(dst,updated)
            cl=updated['classification'];rounds.append({**rr,'path':rel(dst),'sha256':sha(dst),'comparison_group':cl['actual_actions']['comparison_group'],'classification_schema':cl['schema']})
        result={**row,'rounds':rounds,'source_B_record_sha256':digest(row),'source_B_stage':SOURCE_B.name}
        save(run/'regeneration'/(hid+'.json'),{'household_id':hid,'source_B_record_sha256':digest(row),'rules_sha256':sig,'classification_only':True,'A_and_B_schedules_preserved':True,'cases':len(rounds),'source_cases_resampled':False,'valid_B_failures_preserved':sum(not x['given_constraints_feasible']for x in rounds)})
    except Exception as e:result={'household_id':hid,'type':row['type'],'passed':False,'error':str(e),'rules_sha256':sig}
    save(record,result);return result

def main():
    parser=argparse.ArgumentParser();parser.add_argument('--workers',type=int,default=4);args=parser.parse_args();verify_inputs();sig=rules_id();run=OUT/'runs'/sig[:16]
    for p in list((OUT/'code').glob('*.py'))+[OUT/'INPUT_LOCK.json',OUT/'GENERATION_RULES.json',OUT/'USER_DECISIONS.json']:
        dest=run/'source_snapshot'/p.name;dest.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(p,dest)
    save(run/'RUN.json',{'rules_sha256':sig,'source_B':SOURCE_B.name,'classification_only':True,'households':1000,'schedule_generator_called':False})
    rows=read(SOURCE_B/'PAIR_BINDINGS10000.json')['records'];records=[]
    if len(rows)!=1000:raise ValueError('SOURCE_NOT1000')
    with ProcessPoolExecutor(max_workers=args.workers)as pool:
        for result in pool.map(one,[(r,str(run),sig)for r in rows]):
            records.append(result)
            if len(records)%100==0:print({'households':len(records),'errors':sum(not r['passed']for r in records)},flush=True)
    if sig!=rules_id():raise ValueError('CLASSIFIER_CHANGED_DURING_BUILD')
    errors=[r for r in records if not r['passed']];save(run/'BUILD_REVIEW.json',{'rules_sha256':sig,'households':len(records),'errors':errors,'classification_only':True})
    if errors:print(canonical(errors[:5]));raise SystemExit(2)
    cases=sum(len(r['rounds'])for r in records)
    if cases!=10000:raise ValueError('NOT10000')
    save(OUT/'PAIR_BINDINGS10000.json',{'schema':'eb.alternative_bindings.v49','rules_sha256':sig,'households':1000,'cases':cases,'source_B':SOURCE_B.name,'classification_only':True,'records':records})
    ids={r['household_id']for r in read(MASTER/'SUBSET50.json')['records']};subset=[r for r in records if r['household_id']in ids]
    save(OUT/'SUBSET50.json',{'schema':'eb.alternative_subset.v49','records':subset,'type_counts':dict(collections.Counter(r['type']for r in subset)),'same_master_household_ids':True,'same_pairs_and_hashes':True,'separate_generation':False})
    print({'households':1000,'cases':cases,'schedule_changes':0,'rules_sha256':sig})
if __name__=='__main__':main()
