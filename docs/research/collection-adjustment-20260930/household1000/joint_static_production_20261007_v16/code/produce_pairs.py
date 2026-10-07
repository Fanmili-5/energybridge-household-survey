"""Whole-cohort static paired input production, without EP or model calls."""
import collections, concurrent.futures
from common import *
from plans import pair
from validate import validate
def one(b):
    w=read(OUT/b['world_path']);usage=collections.Counter();records=[]
    for i in range(10):
        p=pair(w,i,usage,validate);errors=validate(p)
        if errors:raise RuntimeError((p['case_id'],errors))
        path=OUT/'pairs'/w['household_id']/f'{i+1:02d}.json';save(path,p)
        records.append({'case_id':p['case_id'],'round_index':i+1,'date':p['date'],'pair_path':str(path.relative_to(OUT)),
            'pair_sha256':sha(path),'proposal_family':p['proposal']['family'],'parameter_pack_sha256':w['parameter_pack_sha256'],
            'static_errors':errors,'human_answers':0,'EP_results':None})
    return {'household_id':w['household_id'],'records':records}
def main():
    school_guard();bs=read(OUT/'WORLD_BINDINGS1000.json')['records'];results=[];errors=[]
    with concurrent.futures.ProcessPoolExecutor(max_workers=16) as pool:
        futures={pool.submit(one,b):b['household_id'] for b in bs}
        for f in concurrent.futures.as_completed(futures):
            try:results.append(f.result())
            except Exception as e:errors.append({'household_id':futures[f],'error':str(e)})
    results.sort(key=lambda x:x['household_id']);flat=[r for h in results for r in h['records']]
    save(OUT/'PAIR_BINDINGS10000.json',{'households':results,'pairs':len(flat),'failed_households':errors,
        'proposal_families':dict(collections.Counter(r['proposal_family'] for r in flat)),'EP_started':0,'human_answers':0,'model_API_calls':0})
    print({'pairs':len(flat),'failed_households':len(errors)},flush=True)
    if errors:raise RuntimeError(str(errors[:10]))
if __name__=='__main__':main()
