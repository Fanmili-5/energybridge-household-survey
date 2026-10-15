"""Resume only the interrupted950 scope;retain and quarantine failed outputs."""
import collections,concurrent.futures,datetime,json,pathlib,shutil,sqlite3,subprocess,sys
REPO=pathlib.Path(__file__).resolve().parents[2]
STAGE=REPO/'docs/research/collection-adjustment-20260930/household1000/substantive_repair_v30_20261015'
sys.path.insert(0,str(STAGE/'code'))
from common import read,save,sha
from cohort_gate import require_reviewed_ep,scoped_rows

def inspect(c):
    bad=[]
    for side in ('A','B'):
        directory=STAGE/'runs/base7'/c['household_id']/f'{c["round_index"]:02d}_{side}'
        if not directory.exists():continue
        try:
            r=read(directory/'RUN_RECORD.json');valid=r['runtime_pass']and r['signature']['IDF_sha256']==c[side]['IDF_sha256']and sha(directory/'eplusout.sql')==r['SQL_sha256']
            if valid:
                # Disk exhaustion can leave a successful engine log and a
                # hash-consistent but truncated SQL file. Check actual coverage.
                with sqlite3.connect('file:'+str(directory/'eplusout.sql')+'?mode=ro',uri=True)as db:
                    days=db.execute('SELECT t.SimulationDays,t.Year,t.Month,t.Day,count(DISTINCT t.TimeIndex) FROM Time t JOIN ReportData r USING(TimeIndex) JOIN ReportDataDictionary d USING(ReportDataDictionaryIndex) WHERE t.WarmupFlag=0 AND d.ReportingFrequency="Zone Timestep" GROUP BY t.SimulationDays,t.Year,t.Month,t.Day ORDER BY t.SimulationDays').fetchall()
                date=datetime.date.fromisoformat(c[side]['start_date'])
                expected=[(i+1,(date+datetime.timedelta(days=i)).year,(date+datetime.timedelta(days=i)).month,(date+datetime.timedelta(days=i)).day,144)for i in range(c[side]['prior_days']+3)]
                valid=days==expected
        except Exception:valid=False
        if not valid:bad.append(directory)
    return bad

def main():
    lease=require_reviewed_ep('other950');rows=scoped_rows('other950')
    archive=STAGE/'development/storage_interruption';archive.mkdir(exist_ok=True)
    for name in ('PHYSICS_other950_REVIEW.json','PROGRESS_other950.json','OTHER950_physics.log'):
        p=STAGE/name
        if p.exists()and not(archive/name).exists():shutil.copy2(p,archive/name)
    with concurrent.futures.ThreadPoolExecutor(max_workers=16)as pool:bad=[p for result in pool.map(inspect,rows)for p in result]
    moved=[]
    for p in bad:
        target=archive/'partial_runs'/p.relative_to(STAGE/'runs');target.parent.mkdir(parents=True,exist_ok=True)
        if target.exists():target=target.with_name(target.name+'_'+datetime.datetime.now().strftime('%H%M%S'))
        p.rename(target);moved.append(str(target.relative_to(STAGE)))
    save(archive/'RECOVERY_PLAN.json',{'input_signature_unchanged':lease['review']['input_signature'],'incomplete_branches_quarantined':moved,
        'all_valid_current_SQL_receipts_retained':True,'rules_households_A_B_and_labels_unchanged':True,'new_full1000_run':False})
    print({'quarantined_incomplete_branches':len(bad),'free_GiB':round(shutil.disk_usage(STAGE).free/2**30,2)},flush=True)
    steps=[('physics',[str(STAGE/'code/run_cohort.py'),'--scope','other950','--workers','48']),
      ('substantive',[str(STAGE/'code/substantive_review.py'),'--scope','other950']),
      ('control_SQL',[str(pathlib.Path(__file__).with_name('control_sql.py')),'--stage',str(STAGE),'--scope','other950','--workers','24']),
      ('materials',[str(STAGE/'code/materials.py'),'--cohort','formal950'])]
    for label,args in steps:
        print({'recovery_phase':label,'started_utc':datetime.datetime.now(datetime.timezone.utc).isoformat()},flush=True)
        path=STAGE/f'RECOVERY_other950_{label}.log'
        with path.open('w')as f:r=subprocess.run([sys.executable,*args],stdout=f,stderr=subprocess.STDOUT)
        if r.returncode:print(path.read_text()[-9000:],flush=True);raise RuntimeError('950 remains held at '+label)
        print({'recovery_phase':label,'passed':True},flush=True)
if __name__=='__main__':main()
