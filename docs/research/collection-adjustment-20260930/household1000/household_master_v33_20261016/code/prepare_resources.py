"""Pin all1000 source worlds; acquire missing public native references only.

Requests contain public catalogue names, never household or respondent data.
"""
import concurrent.futures,hashlib,json,subprocess,urllib.request
from pathlib import Path
from common import OUT,BASE,REPO,read,save,sha
from native_registry import build
from model_matching import choose
from housing_conditions import apply


def acquire(row):
    key=row['model_key'];directory=OUT/'native'/key;directory.mkdir(parents=True,exist_ok=True)
    archive=directory/(key+'.accdb.7z');source=directory/(key+'.accdb')
    try:
        if not source.exists():
            if not archive.exists():
                kind={'HighS':'High-rise apartment(slab type)','HighT':'High-rise apartment(tower type)','Low':'Low-rise apartment'}[row['catalogue_type']]
                city=row['catalogue_key'].rsplit('_',2)[-2]
                req=urllib.request.Request('https://svr.dest.net.cn/api/v1/load_model_file',
                    data=json.dumps({'data':{'building_type':kind,'location':city,'year':row['catalogue_reference_epoch']}}).encode(),
                    headers={'Content-Type':'application/json'})
                with urllib.request.urlopen(req,timeout=40)as response:content=response.read()
                if not content.startswith(b"7z\xbc\xaf\x27\x1c"):raise ValueError('Not a7zip model archive')
                partial=archive.with_suffix('.partial');partial.write_bytes(content);partial.replace(archive)
            names=subprocess.check_output(['bsdtar','-tf',str(archive)],text=True).splitlines()
            if names!=[source.name]:raise ValueError('Unexpected archive members')
            partial=source.with_suffix('.partial')
            with partial.open('wb')as f:subprocess.run(['bsdtar','-xOf',str(archive),source.name],check=True,stdout=f)
            partial.replace(source)
        return {'model_key':key,'obtained':True,'source_path':str(source),'source_sha256':sha(source),
                'public_endpoint':'https://svr.dest.net.cn/api/v1/load_model_file',
                'archive_sha256':sha(archive)if archive.exists()else None}
    except Exception as error:return {'model_key':key,'obtained':False,'error':str(error)}


def main():
    source=BASE/'substantive_repair_v30_20261015';selection=read(source/'SELECTION1000.json')
    metadata=read(BASE/'household_housing_evidence_20261006/NATIVE_REFERENCE_REGISTRY.json')['models']+read(BASE/'household_housing_evidence_20261006/ADDITIONAL_REGIONAL_REFERENCES.json')['models']
    catalogue=read(REPO/'artifacts/private_research/eb-dest-catalog-20260925.json')['names_mapping']
    registry=build(metadata,catalogue,OUT/'native');files={}
    for p in (REPO/'artifacts').rglob('*.accdb'):files.setdefault(p.stem,p)
    for p in (OUT/'native').rglob('*.accdb'):files[p.stem]=p
    records=[];models={}
    for h in selection['records']:
        path=source/h['world_path']
        if sha(path)!=h['world_sha256']:raise ValueError('Source world changed:'+h['household_id'])
        w=apply(read(path));selected,facet,matching=choose(w,registry)
        models[selected['model_key']]=selected
        records.append({'household_id':w['household_id'],'source_world_path':str(path),'source_world_sha256':sha(path),
                        'selected':selected,'facet':facet,'matching':matching})
    missing=[m for k,m in models.items()if k not in files];receipts=[]
    print(json.dumps({'source_households':len(records),'distinct_models':len(models),'missing_models':len(missing)}),flush=True)
    with concurrent.futures.ThreadPoolExecutor(max_workers=4)as pool:
        for i,result in enumerate(pool.map(acquire,missing)):
            receipts.append(result)
            save(OUT/'NATIVE_ACQUISITION.json',{'records':receipts,'requested':len(missing),'completed':len(receipts)})
            if result['obtained']:files[result['model_key']]=Path(result['source_path'])
            if(i+1)%20==0:print(json.dumps({'downloaded_or_failed':i+1,'failed':sum(not x['obtained']for x in receipts)}),flush=True)
    failures=[r for r in receipts if not r['obtained']]
    for row in records:
        s=row['selected'];p=files.get(s['model_key'])
        if p:s.update(source_path=str(p),source_sha256=sha(p),native_original_available=True)
    save(OUT/'MODEL_PLAN1000.json',{'schema':'eb.master_native_plan.v33','records':records,'source_selection_sha256':sha(source/'SELECTION1000.json'),
        'failures':failures,'households':len(records),'all_native_files_obtained':not failures,'EP_started':0})
    print(json.dumps({'planned_households':len(records),'acquisition_failures':failures}),flush=True)
    if failures:raise SystemExit(2)

if __name__=='__main__':main()
