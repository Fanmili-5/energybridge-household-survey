"""Independent byte-level closure of V19 bindings; no EP or mutations."""
import collections, concurrent.futures, hashlib, json, sys
from pathlib import Path
OUT=Path(__file__).resolve().parents[1]
N=OUT.parent/'evidence_conditioned_production_20261009_v19'
def read(p):return json.loads(p.read_text())
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def check(row):
    path,expected,kind=row
    try: actual=sha(N/path)
    except Exception as exc: return kind,{'path':path,'error':repr(exc)}
    return kind,None if actual==expected else {'path':path,'expected':expected,'actual':actual}
def main():
    if sys.platform!='linux':raise RuntimeError('School Linux only')
    jobs=[];pairs={r['case_id']:r['pair_sha256'] for r in read(N/'CONSUMER_BINDINGS.json')['records']}
    for r in read(N/'ACTOR_BINDINGS.json')['records']:jobs.append((r['actor_path'],r['actor_sha256'],'actor'))
    for r in read(N/'CONSUMER_BINDINGS.json')['records']:jobs.append((r['consumer_path'],r['consumer_sha256'],'consumer'))
    for h in read(N/'IDF_BINDINGS20000.json')['households']:
        for r in h['records']:
            for s in ('A','B'):
                x=r[s];jobs.extend([(x['IDF_path'],x['IDF_sha256'],'IDF'),(x['signal_ledger_path'],x['signal_ledger_sha256'],'signal_ledger')])
    for h in read(N/'SELECTION1000.json')['records']:
        jobs.append((h['world_path'],h['world_sha256'],'world'))
        for r in h['rounds']:jobs.append((r['pair_path'],r['pair_sha256'],'pair'))
    counts=collections.Counter();errors=[]
    with concurrent.futures.ThreadPoolExecutor(max_workers=16) as pool:
        for i,(kind,error) in enumerate(pool.map(check,jobs),1):
            counts[kind]+=1
            if error:errors.append(error)
            if i%10000==0:print({'bound_files_checked':i},flush=True)
    result={'schema':'eb.independent_v19_file_closure.v1','counts':dict(counts),'failed':errors,'all_referenced_file_hashes_match':not errors,'source_delivery_sha256':sha(N/'DELIVERY.json'),'EP_started':0,'production_modified':False,'scope':'byte identity, not functional execution or physical/human validity'}
    (OUT/'FILE_BINDING_AUDIT.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n')
    print(result,flush=True)
    if errors:raise RuntimeError('Binding failures')
if __name__=='__main__':main()
