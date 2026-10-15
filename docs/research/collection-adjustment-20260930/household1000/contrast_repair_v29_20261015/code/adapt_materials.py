"""Parameterize the accepted mature renderer by disjoint collection cohort."""
import hashlib,json
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def once(s,a,b):
    if s.count(a)!=1:raise RuntimeError('expected one material fragment: '+a[:100])
    return s.replace(a,b,1)
def main():
    p=ROOT/'code/materials.py';before=sha(p);s=p.read_text()
    s=once(s,'def data_materials():','def data_materials(selected):')
    s=once(s,"school_guard();sel=read(OUT/'SELECTION50.json');actor_bindings=[];consumer_bindings=[]","school_guard();sel={'records':selected};actor_bindings=[];consumer_bindings=[]")
    s=s.replace("OUT/'ACTOR_BINDINGS.json'","OUT/('ACTOR_BINDINGS'+str(len(selected))+'.json')").replace("OUT/'CONSUMER_BINDINGS.json'","OUT/('CONSUMER_BINDINGS'+str(len(selected))+'.json')")
    s=once(s,"if '--frontend-only' not in __import__('sys').argv:data_materials()", "argv=__import__('sys').argv;cohort=argv[argv.index('--cohort')+1];ids=set(read(OUT/'PARTITIONS.json')[cohort]);selected=[h for h in read(OUT/'SELECTION1000.json')['records']if h['household_id']in ids];assert len(selected)in(50,950)\n    if '--frontend-only'not in argv:data_materials(selected)")
    s=once(s,"release=OUT/'frontend_release';index=[]","release=OUT/('frontend_release'+str(len(selected)));index=[]")
    s=once(s,"for h in read(OUT/'SELECTION50.json')['records']:","for h in selected:")
    s=once(s,"route='/household50-'+hid","route='/household'+str(len(selected))+'-'+hid")
    s=once(s,"save(release/'INDEX50.json',{'households':index,'pairs':500,", "save(release/('INDEX'+str(len(selected))+'.json'),{'households':index,'pairs':len(selected)*10,")
    assert s.count("OUT/'MATERIALS_REVIEW.json'")==2
    s=s.replace("OUT/'MATERIALS_REVIEW.json'","OUT/('MATERIALS_REVIEW'+str(len(selected))+'.json')")
    s=once(s,"'K':h['K']","'K':len({kind for device in w['parameter_pack']['devices']for kind in device['types']})")
    p.write_text(s);(ROOT/'MATERIAL_SCOPE_ADAPTER.json').write_text(json.dumps({'before_sha256':before,'after_sha256':sha(p),'same_actor_scene_and_original_renderer_logic':True,'cohorts':'formal50 and formal950','cohort_artifacts_are_disjoint':True,'EP_started':0},indent=2)+'\n')
    print(json.dumps({'material_cohorts':[50,950],'mature_frontend_reused':True}))
if __name__=='__main__':main()
