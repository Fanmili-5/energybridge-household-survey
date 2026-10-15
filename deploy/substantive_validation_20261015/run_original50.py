"""Ordered original50 checks. Never advances to950 and stops on any failure."""
import datetime,json,os,pathlib,subprocess,sys
REPO=pathlib.Path(__file__).resolve().parents[2]
STAGE=REPO/'docs/research/collection-adjustment-20260930/household1000/substantive_repair_v30_20261015'
sys.path.insert(0,str(STAGE/'code'))
from contrast_core import PROTOCOL
from common import save
save(STAGE/'PROTOCOL_V29.json',PROTOCOL)
phases=[('source',['repair_contrast.py','--scope','formal50']),
 ('negative_controls',['substantive_review.py','--controls']),
 ('compile',['compile_repaired.py','--scope','formal50']),
 ('physics',['execute_physics.py','--scope','original50','--workers','24']),
 ('substantive',['substantive_review.py','--scope','original50']),
 ('control_SQL',[str(pathlib.Path(__file__).with_name('control_sql.py')),'--stage',str(STAGE),'--scope','original50']),
 ('materials',['materials.py','--cohort','formal50'])]
for phase,args in phases:
    command=[sys.executable,str(STAGE/'code'/args[0])if not args[0].startswith('/')else args[0],*args[1:]]
    log=STAGE/('V30_3_'+phase+'.log')
    save(STAGE/'V30_3_PROGRESS.json',{'phase':phase,'running':True,'950_unlocked':False,'full_EP_started':False})
    print({'phase':phase,'started_utc':datetime.datetime.now(datetime.timezone.utc).isoformat()},flush=True)
    with log.open('w')as f:result=subprocess.run(command,stdout=f,stderr=subprocess.STDOUT)
    if result.returncode:
        print(log.read_text()[-9000:],flush=True);raise RuntimeError('original50 stopped at '+phase)
    print({'phase':phase,'passed':True},flush=True)
save(STAGE/'V30_3_PROGRESS.json',{'phase':'formal_materials_ready','running':False,'original50_final_acceptance':False,'950_unlocked':False,'full_EP_started':False})
