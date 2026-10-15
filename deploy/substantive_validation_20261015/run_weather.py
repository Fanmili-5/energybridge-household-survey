"""Previously fixed520 weather comparisons,after original50 acceptance only."""
import pathlib,subprocess,sys
REPO=pathlib.Path(__file__).resolve().parents[2]
STAGE=REPO/'docs/research/collection-adjustment-20260930/household1000/substantive_repair_v30_20261015'
sys.path.insert(0,str(STAGE/'code'))
from cohort_gate import require_original50_acceptance
require_original50_acceptance()
steps=[('physics',[str(STAGE/'code/execute_physics.py'),'--scope','weather_sensitivity','--workers','24']),
       ('substantive',[str(STAGE/'code/substantive_review.py'),'--scope','weather_sensitivity']),
       ('controls',[str(pathlib.Path(__file__).with_name('control_sql.py')),'--stage',str(STAGE),'--scope','weather_sensitivity'])]
for phase,args in steps:
    print({'weather_phase':phase,'started':True},flush=True);path=STAGE/f'WEATHER_{phase}.log'
    with path.open('w')as output:r=subprocess.run([sys.executable,*args],stdout=output,stderr=subprocess.STDOUT)
    if r.returncode:print(path.read_text()[-8000:],flush=True);raise RuntimeError('weather acceptance failed at '+phase)
    print({'weather_phase':phase,'passed':True},flush=True)
