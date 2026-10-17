"""Resumable, paired EnergyPlus execution with complete meters and raw provenance."""
import argparse
import collections
import gzip
import sqlite3
import subprocess
import time
import traceback
from concurrent.futures import ProcessPoolExecutor
from functools import lru_cache
from core import *
from compiler import compile_model

@lru_cache(maxsize=2)
def household(path):return read(ROOT/path)

@lru_cache(maxsize=1)
def raw_SQL_households():return set(read(ROOT/'INPUT_MANIFEST.json')['subset50_ids'])

def read_outputs(folder,date,hi):
    db=sqlite3.connect(folder/'out/eplusout.sql');channels={};meta={}
    query='''SELECT d.Name,d.KeyValue,d.Units,d.IsMeter,t.Month,t.Day,t.Hour,t.Minute,t.Interval,r.Value
       FROM ReportData r JOIN ReportDataDictionary d USING(ReportDataDictionaryIndex)
       JOIN Time t USING(TimeIndex) JOIN EnvironmentPeriods e USING(EnvironmentPeriodIndex)
       WHERE t.WarmupFlag=0 AND e.EnvironmentType=3 ORDER BY t.TimeIndex'''
    origin=dt.date.fromisoformat(date)
    for name,key,unit,is_meter,month,day,hour,minute,interval,value in db.execute(query):
        dd=min((dt.date(year,month,day)for year in(origin.year-1,origin.year,origin.year+1)),key=lambda d:abs((d-origin).days))
        end=(dd-origin).days*1440+hour*60+minute;t=end-interval
        if not 0<=t<hi:continue
        if interval!=10:raise ValueError('NON_TEN_MINUTE_OUTPUT:'+name+':'+str(interval))
        k=name+'|'+(key or '')
        channels.setdefault(k,[]).append([t,value]);meta[k]={'unit':unit,'is_meter':bool(is_meter)}
    db.close()
    for k,v in channels.items():
        if [x[0]for x in v]!=list(range(0,hi,10)):raise ValueError('OUTPUT_TIMELINE:'+k)
    required=['Electricity:Facility','Zone Mean Air Temperature']
    for name in required:
        if not any(k.split('|')[0].lower()==name.lower()for k in channels):raise ValueError('MISSING_OUTPUT:'+name)
    return {'channels':channels,'metadata':meta,'interval_min':[0,hi]}

def one_side(pack,pair,side,jobdir,engine,history):
    folder=jobdir/side;reportpath=folder/'RESULT.json'
    fingerprint=digest({'pair':pair['source_pair_sha256'],'side':side,'pack':sha(ROOT/'inputs/households'/f"{pair['household_id']}.json.gz"),'physics':physics_hash(),'history':history,'engine_sha256':sha(engine),'reference_ACH':float(os.environ.get('EB_REFERENCE_ACH','.35'))})
    if reportpath.exists():
        r=read(reportpath)
        if r.get('fingerprint')==fingerprint and r.get('engine_completed')and sha(folder/'TRACE.json.gz')==r['trace_sha256']:return r
    folder.mkdir(parents=True,exist_ok=True)
    started=time.monotonic();weather,inputs=compile_model(pack,pair,side,folder,history)
    command=[str(engine),'-w',str(weather),'-d',str(folder/'out'),str(folder/'model.idf')]
    run=subprocess.run(command,capture_output=True,text=True,timeout=300)
    (folder/'stdout.txt').write_text(run.stdout+'\n'+run.stderr)
    errpath=folder/'out/eplusout.err';errors=errpath.read_text()if errpath.exists()else run.stderr
    success=run.returncode==0 and 'EnergyPlus Completed Successfully'in errors
    result={'schema':VERSION,'case_id':pair['case_id'],'side':side,'fingerprint':fingerprint,'source_pair_sha256':pair['source_pair_sha256'],
            'engine_completed':success,'returncode':run.returncode,'elapsed_seconds':time.monotonic()-started,
            'errors':[line for line in errors.splitlines()if '** Severe **'in line or '**  Fatal  **'in line],
            'warnings':[line for line in errors.splitlines()if '** Warning **'in line],
            'input_sha256':sha(folder/'INPUT.json.gz'),'idf_sha256':inputs['idf_sha256'],'engine_sha256':sha(engine),
            'source_schedule_hash':pair['schedule_hashes'][side],'human_acceptance':None}
    if success:
        data=read_outputs(folder,pair['date'],inputs['run_interval_min'][1]);save(folder/'TRACE.json.gz',data)
        result['trace_sha256']=sha(folder/'TRACE.json.gz');result['channel_count']=len(data['channels'])
        sql=folder/'out/eplusout.sql';result['raw_SQL_sha256']=sha(sql)
        # All cases retain the exact used 10-minute values in TRACE. Full SQL
        # includes 28+ days of redundant history; retain it on the predeclared
        # same-master 50 households, independently of success or response.
        result['raw_SQL_archive_retained']=pair['household_id']in raw_SQL_households()
        result['raw_SQL_retention_rule']='original subset50 households fixed before results;all cases retain exact reported TRACE and reproducible IDF'
        if result['raw_SQL_archive_retained']:
            archive=folder/'out/eplusout.sql.gz';archive.write_bytes(gzip.compress(sql.read_bytes(),compresslevel=6,mtime=0))
            result['raw_SQL_compressed_sha256']=sha(archive)
        sql.unlink()
        (folder/'model.idf.gz').write_bytes(gzip.compress((folder/'model.idf').read_bytes(),compresslevel=1,mtime=0));(folder/'model.idf').unlink()
        for name in ('eplusout.eso','eplusout.mtr','eplusout.shd','eplusout.eio','eplusout.audit','eplusout.end','eplusout.bnd','eplusout.dxf','eplusout.sln','eplusout.dfs'):
            f=folder/'out'/name
            if f.exists():f.unlink()
        for name in ('eplusout.rdd','eplusout.mdd','eplusout.mtd'):
            f=folder/'out'/name
            if f.exists():
                (folder/'out'/(name+'.gz')).write_bytes(gzip.compress(f.read_bytes(),compresslevel=6,mtime=0));f.unlink()
    save(reportpath,result)
    return result

def job(item):
    row,case,engine,history,label=item
    try:
        if sha(ROOT/row['path'])!=row['sha256']or sha(ROOT/case['path'])!=case['sha256']:raise ValueError('EXPORTED_INPUT_HASH')
        pack=household(row['path']);pair=read(ROOT/case['path']);folder=ROOT/'results'/label/row['household_id']/case['date']
        results=[one_side(pack,pair,side,folder,Path(engine),history)for side in ('A','B')]
        result={'case_id':case['case_id'],'source_pair_sha256':case['source_pair_sha256'],'sides':results,'passed':all(r['engine_completed']for r in results),
                'path':str(folder.relative_to(ROOT))}
        save(folder/'PAIR_RUN.json',result)
        return result
    except Exception as exc:
        return {'case_id':case['case_id'],'passed':False,'error':str(exc),'traceback':traceback.format_exc()}

def main():
    p=argparse.ArgumentParser();p.add_argument('--engine',default=os.environ.get('EB_ENERGYPLUS','/Applications/EnergyPlus-24-1-0/energyplus'))
    p.add_argument('--workers',type=int,default=4);p.add_argument('--scope',choices=['smoke','pilot50','all','initialization'],default='pilot50')
    p.add_argument('--history',type=int,default=28);p.add_argument('--label');p.add_argument('--household');p.add_argument('--limit',type=int)
    args=p.parse_args();manifest=read(ROOT/'INPUT_MANIFEST.json');engine=Path(args.engine).resolve()
    version=subprocess.check_output([str(engine),'--version'],text=True).strip()
    if not version.startswith('EnergyPlus, Version 24.1.0'):raise ValueError('ENGINE_VERSION:'+version)
    label=args.label or args.scope;rows=manifest['records']
    if args.scope in('pilot50','initialization'):rows=[r for r in rows if r['household_id']in manifest['subset50_ids']]
    if args.household:rows=[r for r in rows if r['household_id']==args.household]
    jobs=[]
    for r in rows:
        cases=r['cases'][:1]if args.scope in('smoke','initialization')else r['cases']
        for c in cases:jobs.append((r,c,str(engine),args.history,label))
    if args.scope=='smoke'and not args.household:jobs=jobs[:1]
    if args.limit:jobs=jobs[:args.limit]
    save(ROOT/'results'/label/'RUN_CONFIG.json',{'scope':args.scope,'jobs':len(jobs),'history':args.history,'code_sha256':code_hash(),'physics_sha256':physics_hash(),'reference_ACH':float(os.environ.get('EB_REFERENCE_ACH','.35')),'manifest_sha256':sha(ROOT/'INPUT_MANIFEST.json'),'engine_version':version,'engine_sha256':sha(engine),'workers':args.workers})
    results=[];started=time.monotonic()
    with ProcessPoolExecutor(max_workers=args.workers)as pool:
        for r in pool.map(job,jobs,chunksize=1):
            results.append(r)
            if len(results)%10==0 or not r['passed']:
                print(canonical({'completed_pairs':len(results),'planned_pairs':len(jobs),'errors':sum(not x['passed']for x in results),'elapsed_seconds':round(time.monotonic()-started),'last_error':r.get('error')}),flush=True)
                save(ROOT/'results'/label/'PROGRESS.json',{'completed_pairs':len(results),'planned_pairs':len(jobs),'failed_pairs':sum(not x['passed']for x in results),'elapsed_seconds':time.monotonic()-started})
    report={'schema':VERSION,'scope':args.scope,'label':label,'cases':len(results),'passed':all(r['passed']for r in results),'records':results,'code_sha256':code_hash(),'input_manifest_sha256':sha(ROOT/'INPUT_MANIFEST.json'),'elapsed_seconds':time.monotonic()-started}
    save(ROOT/'results'/label/'RUN_BINDINGS.json',report);print(canonical({k:v for k,v in report.items()if k!='records'}))
    if not report['passed']:raise SystemExit(2)

if __name__=='__main__':main()
