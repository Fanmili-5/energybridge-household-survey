"""Fetch explicit original DeST Lasa reference models, never a nearest city.
Catalogue spelling Lasa is retained; original ENVIRONMENT determines province.
"""
import hashlib,json,subprocess,urllib.request
from pathlib import Path
OUT=Path(__file__).resolve().parent.parent;REPO=OUT.parents[4]
ENDPOINT='https://svr.dest.net.cn/api/v1/load_model_file'
def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def main():
    from evidence_guard import ensure_unsealed
    ensure_unsealed(OUT)
    catalogue=REPO/'artifacts/private_research/eb-dest-catalog-20260925.json';mapping=json.loads(catalogue.read_text())['names_mapping'];results=[]
    for year in [1995,2018]:
        kind='Low-rise apartment';location='Lasa';key=kind+'_'+location+'_'+str(year);file_id=mapping[key]
        folder=REPO/'artifacts/private_research/household_housing_evidence_20261006/native'/file_id;folder.mkdir(parents=True,exist_ok=True)
        archive=folder/(file_id+'.accdb.7z');source=folder/(file_id+'.accdb')
        try:
            if not archive.exists():
                payload=json.dumps({'data':{'building_type':kind,'location':location,'year':year}}).encode()
                req=urllib.request.Request(ENDPOINT,data=payload,headers={'Content-Type':'application/json'})
                archive.write_bytes(urllib.request.urlopen(req,timeout=45).read())
            members=subprocess.check_output(['bsdtar','-tf',str(archive)],text=True).splitlines();assert members==[source.name]
            if not source.exists():
                with source.open('wb') as f:subprocess.run(['bsdtar','-xOf',str(archive),source.name],stdout=f,check=True)
            assert source.stat().st_size>1000000
            result={'model_key':file_id,'catalogue_key':key,'catalogue_snapshot_path':str(catalogue),'catalogue_snapshot_sha256':sha(catalogue),
              'original_endpoint':ENDPOINT,'download_date_HKT':'2026-10-06','archive_sha256':sha(archive),'source_path':str(source),'source_sha256':sha(source),
              'original_Access_source_obtained':True,'unavailable_historical_R_destep_runtime_not_reinstalled':True,
              'whole_native_IDF_converted':False,'native_geometry_or_stock_frequency_admitted':False}
        except Exception as e:result={'model_key':file_id,'original_endpoint':ENDPOINT,'error':str(e),'native_match_admitted':False}
        results.append(result)
    (OUT/'NATIVE_GAP_ACQUISITION.json').write_text(json.dumps({'sources':results},ensure_ascii=False,indent=2)+'\n')
    print(json.dumps([{'model_key':r['model_key'],'obtained':r.get('original_Access_source_obtained',False),'error':r.get('error')} for r in results],ensure_ascii=False))
if __name__=='__main__':main()
