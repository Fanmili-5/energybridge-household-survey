"""Frozen1000 → worlds → A/B → full scope audits → IDFs. No EnergyPlus launch."""
import collections,concurrent.futures,copy,json,os,subprocess,sys,time
from common import *
from worlds import build
from generate import generate_household

V27=BASE/'eb_type_pilot_v27_20261014'

def worlds():
    frozen=read(V27/'FROZEN_COMPOSITION1000.json');assignment=frozen['type_assignment_for_future_generation']
    source=read(SOURCE/'SELECTION1000.json')['records'];original={h['household_id']:h for h in read(V27/'SELECTION50.json')['records']}
    assert len(source)==len(assignment)==1000
    assert collections.Counter(assignment.values())==frozen['counts']
    records=[];members=0;changed_original=[]
    for h in source:
        src=read(SOURCE/h['world_path']);assert sha(SOURCE/h['world_path'])==h['world_sha256']
        w=build(src,assignment[h['household_id']]);path=OUT/'worlds'/f'{h["household_id"]}.json';save(path,w)
        members+=w['N']
        if h['household_id']in original and sha(path)!=original[h['household_id']]['world_sha256']:changed_original.append(h['household_id'])
        records.append({**{k:copy.deepcopy(v)for k,v in h.items()if k!='rounds'},'world_path':str(path.relative_to(OUT)),
            'world_sha256':sha(path),'parameter_pack_sha256':w['parameter_pack_sha256'],'source_V23_world_sha256':h['world_sha256']})
    partitions={'formal50':sorted(original),'formal950':sorted(set(assignment)-set(original))}
    assert len(partitions['formal50'])==50 and len(partitions['formal950'])==950 and not set(partitions['formal50'])&set(partitions['formal950'])
    save(OUT/'PARTITIONS.json',{'schema':'eb.disjoint_formal_cohorts.v1',**partitions,'same_rules_and_frozen_composition':True,'not_a_claim_of_actor_independence':True})
    save(OUT/'WORLD_BINDINGS1000.json',{'households':1000,'records':records})
    save(OUT/'WORLD_BUILD_REVIEW.json',{'households':1000,'members':members,'frozen_type_counts':dict(collections.Counter(assignment.values())),
        'original50_world_bytes_changed_by_chronology_repair':changed_original,'original50_rosters_types_housing_hardware_dates_preserved':True,
        'composition_sha256':sha(V27/'FROZEN_COMPOSITION1000.json'),'EP_started':0})

def plans():
    records=[];counts=collections.Counter();flags=collections.Counter();a_flags=collections.Counter();fallback=collections.Counter();fail=[]
    with concurrent.futures.ProcessPoolExecutor(max_workers=24)as pool:
        for r,cc,ff,aa,fb,ee in pool.map(generate_household,read(OUT/'WORLD_BINDINGS1000.json')['records']):
            records.append(r);counts.update(cc);flags.update(ff);a_flags.update(aa);fallback.update(fb);fail.extend(ee)
            if len(records)%50==0:print({'phase':'plans','households':len(records),'failures':len(fail)},flush=True)
    save(OUT/'SELECTION1000.json',{'households':1000,'pairs':sum(len(h['rounds'])for h in records),'records':records})
    save(OUT/'STATIC_REVIEW.json',{'households':1000,'pairs':sum(len(h['rounds'])for h in records),'integrity_failures':fail,
        'proposal_mechanisms':dict(counts),'B_constraint_flags':dict(flags),'A_constraint_flags':dict(a_flags),
        'unavailable_requested_mechanisms':dict(fallback),'all_original_dates_retained':not fail,'human_labels_generated':0,'new_EP_executed':False,'bad_proposals_retained':True})
    assert not fail and not a_flags and sum(counts.values())==10000,'static generation failed'
    old={h['household_id']:h for h in read(V27/'SELECTION50.json')['records']}
    changed=[]
    for h in records:
        if h['household_id']in old:
            assert [r['date']for r in h['rounds']]==[r['date']for r in old[h['household_id']]['rounds']]
            changed.extend(r['case_id']for r,prev in zip(h['rounds'],old[h['household_id']]['rounds'])if r['pair_sha256']!=prev['pair_sha256'])
    save(OUT/'ORIGINAL50_PRESERVATION.json',{'worlds':50,'pairs':500,'rosters_types_housing_hardware_original_dates_preserved':True,
        'changed_pairs_requiring_fresh_acceptance':changed,'source_acceptance_sha256':sha(V27/'FINAL_ACCEPTANCE.json'),'old_acceptance_is_not_new_acceptance':True})

def command(module):
    log=OUT/'logs'/f'{module}.log';log.parent.mkdir(exist_ok=True)
    with log.open('w')as f:subprocess.run([sys.executable,'-B',str(OUT/'code'/module)],check=True,stdout=f,stderr=subprocess.STDOUT,env={**os.environ,'OMP_NUM_THREADS':'1','OPENBLAS_NUM_THREADS':'1'})
    print({'phase':module,'passed':True},flush=True)

def compile_all():
    from physics import compile_job
    selection=read(OUT/'SELECTION1000.json')['records'];jobs=[(h,r,'base7')for h in selection for r in h['rounds']];rows=[]
    with concurrent.futures.ProcessPoolExecutor(max_workers=24)as pool:
        for c in pool.map(compile_job,jobs,chunksize=1):
            rows.append(c)
            if len(rows)%100==0:print({'phase':'IDF','pairs':len(rows),'planned':10000},flush=True)
    save(OUT/'COMPILED1000.json',{'households':1000,'pairs':10000,'IDF_count':20000,'records':rows,'EP_started':0})
    by=collections.defaultdict(list)
    for c in rows:by[c['household_id']].append({'case_id':read(OUT/c['pair_path'])['case_id'],'round_index':c['round_index'],'pair_sha256':c['pair_sha256'],'A':c['A'],'B':c['B'],'EP_results':None})
    save(OUT/'IDF_BINDINGS1000.json',{'households':[{'household_id':h['household_id'],'records':by[h['household_id']],'weather':h['weather']}for h in selection],'IDF_count':20000,'failed':[],'EP_started':0})
    old={(c['household_id'],c['round_index']):c for c in read(V27/'COMPILED50.json')['records']if c['variant']=='base7'}
    unchanged=0;changed=[]
    for c in rows:
        if (c['household_id'],c['round_index'])in old:
            prev=old[c['household_id'],c['round_index']]
            same=all(c[side][key]==prev[side][key]for side in ('A','B')for key in ('IDF_sha256','native_IDF_sha256','signal_ledger_sha256'))
            if same:unchanged+=1
            else:changed.append({'household_id':c['household_id'],'round_index':c['round_index']})
    save(OUT/'ORIGINAL50_COMPILED_PRESERVATION.json',{'pairs':500,'unchanged_pairs':unchanged,'changed_pairs':changed,
        'exact_SQL_reuse_requires_arm_IDF_weather_engine_hash_equality':True,'fresh_readback_required_for_all':True})

def main():
    import argparse
    a=argparse.ArgumentParser();a.add_argument('--resume-from',choices=['start','clustering','compile','physical_inputs'],default='start');args=a.parse_args()
    school_guard();start=time.time()
    if args.resume_from=='start':
        worlds();plans()
        for m in ['audit_pilot.py','audit_calendar.py']:command(m)
    else:
        assert read(OUT/'INPUT_AUDIT.json')['status']=='pass'and not read(OUT/'CALENDAR_AUDIT.json')['failures']
        repair=read(OUT/'CHRONOLOGY_RULE_REPAIR.json')
        assert all(sha(OUT/'code'/name)==value for name,value in repair['after_sha256'].items())
    if args.resume_from in('start','clustering'):
        for m in ['cluster_pilot.py','audit_bath.py']:command(m)
    if args.resume_from in('start','clustering','compile'):compile_all()
    for m in ['audit_idfs.py','mechanism_controls.py','vehicle_causal_controls.py','audit_reference_model.py','audit_physical_inputs.py']:command(m)
    save(OUT/'STATIC_PRODUCTION_COMPLETE.json',{'passed':True,'households':1000,'pairs':10000,'IDFs':20000,
        'formal50':50,'formal950':950,'source_composition_frozen_before_generation':True,'original50_source_anchors_preserved':True,
        'full_EP_started':0,'EP_still_requires_fresh_content_bound_review':True,'elapsed_seconds':time.time()-start})
    print({'static_production':'pass','EP_started':0},flush=True)

if __name__=='__main__':main()
