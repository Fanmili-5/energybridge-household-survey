"""Apply the frozen original50-accepted rules, without a full1000 rerun."""
import datetime,pathlib,subprocess,sys
REPO=pathlib.Path(__file__).resolve().parents[2]
STAGE=REPO/'docs/research/collection-adjustment-20260930/household1000/substantive_repair_v30_20261015'
sys.path.insert(0,str(STAGE/'code'))
from common import save,sha
from cohort_gate import require_original50_acceptance
first=require_original50_acceptance()
phases=[('source',['repair_contrast.py','--scope','formal950']),
 ('compile',['compile_repaired.py','--scope','formal950']),
 ('physics',['execute_physics.py','--scope','other950','--workers','48']),
 ('substantive',['substantive_review.py','--scope','other950']),
 ('control_SQL',[str(pathlib.Path(__file__).with_name('control_sql.py')),'--stage',str(STAGE),'--scope','other950','--workers','24']),
 ('materials',['materials.py','--cohort','formal950'])]
for phase,args in phases:
    command=[sys.executable,str(STAGE/'code'/args[0])if not args[0].startswith('/')else args[0],*args[1:]]
    save(STAGE/'OTHER950_PROGRESS.json',{'phase':phase,'running':True,'original50_acceptance_sha256':sha(STAGE/'ORIGINAL50_CONTRAST_ACCEPTANCE.json'),'full1000_EP_rerun':False})
    print({'phase':phase,'started_utc':datetime.datetime.now(datetime.timezone.utc).isoformat()},flush=True)
    log=STAGE/('OTHER950_'+phase+'.log')
    with log.open('w')as f:r=subprocess.run(command,stdout=f,stderr=subprocess.STDOUT)
    if r.returncode:print(log.read_text()[-10000:],flush=True);raise RuntimeError('950 stopped at '+phase)
    print({'phase':phase,'passed':True},flush=True)
save(STAGE/'OTHER950_PROGRESS.json',{'phase':'formal_materials_ready','running':False,'full1000_EP_rerun':False})
