"""Package only authorized derived research inputs; no live service or secrets."""
import tarfile
from common import *
REMOTE_ROOT='/home/hku_user3/energybridge-compute/research_runs/household1000_taskworld_20261007_v13'
def main():
    guard();prefix='workspace/energybridge-household-survey/';files={}
    def add(p):
        p=Path(p).resolve();name=prefix+str(p.relative_to(REPO));files[name]=p
    for p in (OUT/'code').glob('*.py'):add(p)
    for p in (OUT/'worlds').glob('*.json'):add(p)
    for p in (V12/'background_idfs').glob('*.idf'):add(p)
    add(V7/'RUNTIME.json');add(UP/'energybridge/simulation/appliance_sim.py');add(UP/'experiments/models/family_home/family_simple_3day.idf')
    add(OUT/'ASSEMBLY_PROTOCOL.json')
    records=read(OUT/'WORLD_BINDINGS1000.json');original=read(OUT/'WORLD_BINDINGS1000.json');weather=[]
    for r in records['records']:
        source=Path(r['weather']['path']);assert sha(source)==r['weather']['sha256']
        name='weather/'+r['weather']['sha256']+'.epw';files[name]=source
        if name not in [x['staged_path'] for x in weather]:weather.append({'original_path':str(source),'staged_path':name,'sha256':sha(source)})
        r['weather']['source_original_path']=str(source);r['weather']['path']=REMOTE_ROOT+'/'+name
    save(OUT/'SCHOOL_WORLD_BINDINGS1000.json',records)
    staged_name=prefix+str((OUT/'WORLD_BINDINGS1000.json').relative_to(REPO));files[staged_name]=OUT/'SCHOOL_WORLD_BINDINGS1000.json'
    manifest={'schema':'eb.school_taskworld_input_bundle.v1','remote_root':REMOTE_ROOT,'files':{n:sha(p) for n,p in files.items()},
              'weather_mapping':weather,'original_local_binding_sha256':sha(OUT/'WORLD_BINDINGS1000.json'),'no_credentials_raw_microdata_or_live_databases':True,
              'school_EP_root':'/home/hku_user3/energybridge-compute/EnergyPlus-24-1-0','workers_initial':16,'no_model_API_calls':True}
    save(OUT/'SCHOOL_INPUT_MANIFEST.json',manifest)
    archive=OUT/'school_input_bundle.tar.gz'
    with tarfile.open(archive,'w:gz') as tar:
        for name,p in files.items():tar.add(p,arcname=name,recursive=False)
        tar.add(OUT/'SCHOOL_INPUT_MANIFEST.json',arcname='SCHOOL_INPUT_MANIFEST.json')
    save(OUT/'SCHOOL_UPLOAD_BINDING.json',{'archive':archive.name,'archive_sha256':sha(archive),'archive_bytes':archive.stat().st_size,'remote_root':REMOTE_ROOT,'files':len(files),'weather_inputs':len(weather)})
    print({'files':len(files),'archive_bytes':archive.stat().st_size,'weather_inputs':len(weather),'remote_root':REMOTE_ROOT})
if __name__=='__main__':main()
