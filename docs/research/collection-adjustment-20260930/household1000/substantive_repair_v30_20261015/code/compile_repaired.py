"""Compile only source-defined changed pairs; independently preserve every A."""
import concurrent.futures,copy,os
from common import *
from physics import compile_job
PARENT=BASE/'contrast_repair_v29_20261015'

def deduplicate(c):
    """Preserve exact bytes while avoiding duplicate multi-GB immutable inputs."""
    for side in ('A','B'):
        b=c[side]
        for field,hashfield in [('IDF_path','IDF_sha256'),('native_IDF_path','native_IDF_sha256'),('signal_ledger_path','signal_ledger_sha256')]:
            target=OUT/b[field];expected=b[hashfield]
            for parent in (OUT/'development/rule_revision_v30_2',PARENT,BASE/'formal50_950_production_v28_20261014'):
                old=parent/b[field]
                if not old.exists():continue
                if os.path.samefile(old,target):break
                if old.stat().st_size!=target.stat().st_size or sha(old)!=expected:continue
                assert sha(target)==expected
                temporary=target.with_name(target.name+'.dedup.'+str(os.getpid()))
                os.link(old,temporary);temporary.replace(target);break
    return c

def job(item):
    h,rr,variant=item
    if variant!='weather_linear7':return deduplicate(compile_job((h,rr,variant)))
    from compile_inputs import compile_one
    from curve_observer import attach
    w=read(OUT/h['world_path']);p=read(OUT/rr['pair_path']);background=parse(V12/'background_idfs'/f'{h["household_id"]}.idf')
    arms={side:compile_one(w,p,side,background,prior_days=7,inlet='fixed15',variant=variant,weather_path=h['weather']['path'])for side in('A','B')}
    for b in arms.values():
        native=OUT/b['IDF_path'];rows=parse(native);b['native_IDF_sha256']=sha(native);b['native_IDF_path']=b['IDF_path'];b['curve_observation_meta']=attach(rows)
        observed=OUT/'idfs'/('observed_'+variant)/h['household_id']/native.name;observed.parent.mkdir(parents=True,exist_ok=True)
        tmp=observed.with_suffix('.tmp');tmp.write_text(dump(rows));tmp.replace(observed);b['IDF_path']=str(observed.relative_to(OUT));b['IDF_sha256']=sha(observed)
    return deduplicate({'household_id':h['household_id'],'round_index':rr['round_index'],'date':rr['date'],'variant':variant,
       'world_path':h['world_path'],'world_sha256':h['world_sha256'],'pair_path':rr['pair_path'],'pair_sha256':rr['pair_sha256'],'weather':h['weather'],**arms})

def main(scope):
    school_guard();report=read(OUT/f'CONTRAST_{scope}_INPUT.json');assert report['passed']
    changes=set(report['changed_case_ids']);selected=read(OUT/'SELECTION1000.json')['records'];by={h['household_id']:h for h in selected}
    updates={};jobs=[]
    for name in('COMPILED1000.json','COMPILED_SENSITIVITY50.json','COMPILED_WEATHER_SENSITIVITY.json'):
        manifest=read(OUT/name)
        for i,c in enumerate(manifest['records']):
            rr=next(r for r in by[c['household_id']]['rounds']if r['round_index']==c['round_index'])
            if read(OUT/rr['pair_path'])['case_id']not in changes:continue
            if c['variant']=='temperature_flat7':continue
            h=by[c['household_id']]
            if c['variant']=='weather_linear7':h={**h,'weather':c['weather']}
            jobs.append((name,i,c,(h,rr,c['variant'])))
        updates[name]=manifest
    with concurrent.futures.ProcessPoolExecutor(max_workers=16)as pool:
        for (name,i,old,_),new in zip(jobs,pool.map(job,[x[-1]for x in jobs])):
            for key in('IDF_sha256','native_IDF_sha256','signal_ledger_sha256'):
                assert old['A'][key]==new['A'][key],('FROZEN_A_PHYSICS_CHANGED',old['household_id'],key)
            updates[name]['records'][i]=new
    from model_form_diagnostic import prepare
    bases={(c['household_id'],c['round_index']):c for c in updates['COMPILED1000.json']['records']}
    for i,c in enumerate(updates['COMPILED_SENSITIVITY50.json']['records']):
        if c['variant']!='temperature_flat7':continue
        base=bases[c['household_id'],c['round_index']]
        if read(OUT/base['pair_path'])['case_id']not in changes:continue
        new=deduplicate(prepare(base));assert c['A']['IDF_sha256']==new['A']['IDF_sha256'];updates['COMPILED_SENSITIVITY50.json']['records'][i]=new
    for name,manifest in updates.items():save(OUT/name,manifest)
    # Every manifest is rebound to the current pair, even if an unchanged
    # physical modifier happens to yield the same exact IDF.
    save(OUT/f'COMPILE_{scope}_REVIEW.json',{'passed':True,'source_changed_pairs':len(changes),'variants_compiled':len(jobs),
       'A_physical_inputs_identical_to_parent':True,'EP_started':False})
    print({'compiled_changed_pairs':len(changes),'variants':len(jobs),'A_unchanged':True,'EP_started':False},flush=True)
if __name__=='__main__':
    import argparse
    p=argparse.ArgumentParser();p.add_argument('--scope',choices=['formal50','formal950'],required=True);a=p.parse_args();main(a.scope)
