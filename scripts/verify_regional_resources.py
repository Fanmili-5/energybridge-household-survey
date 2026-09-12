"""Offline EP matrix; expose only individually successful model/weather/date pairs."""
from __future__ import annotations
import argparse
from concurrent.futures import ThreadPoolExecutor
from contextlib import redirect_stdout
from datetime import date,timedelta
import hashlib
import json
from pathlib import Path
import re
import sqlite3
import subprocess
import sys
import tempfile
from types import SimpleNamespace

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'realtime_pilot'))
from common import UPSTREAM,file_hash
from simulation_environment import localize_idf
from audit_upstream_appliance_binding import extract_function
from audit_device_interface_controls import method
from validation_cache import context as validation_context,reusable

def case(model,weather,day,ep,folder):
    folder.mkdir(parents=True,exist_ok=False)
    (folder/'stage.json').write_text(json.dumps({'ep_started':False,'stage':'resource_precheck'}))
    from shutil import copyfile
    with tempfile.TemporaryDirectory(prefix='eb-regional-') as tmp:
        tmp=Path(tmp);template=tmp/'template.idf';copyfile(ROOT/model['idf'],template)
        loc=localize_idf(template,ROOT/weather['epw'],ROOT/weather['ddy'])
        ns={'Path':Path,'date':date,'timedelta':timedelta}
        src=UPSTREAM/'energybridge/data/day_ahead.py'
        extract_function(src,'_idf_field',ns)
        gen=extract_function(src,'generate_runperiod_idf',ns)
        idf=gen(template,tmp,start_date=date.fromisoformat(day),days=1)
        idf.write_text(idf.read_text()+'\nOutput:SQLite,SimpleAndTabular;\nOutput:Variable,*,Electric Equipment Electricity Energy,Timestep;\n')
        sys.path.insert(0,str(ep))
        from pyenergyplus.api import EnergyPlusAPI
        api=EnergyPlusAPI();state=api.state_manager.new_state();ex=api.exchange
        api.runtime.set_console_output_status(state,False)
        init=method(UPSTREAM/'experiments/benchmark/family_runner.py','_FamilyLoop','init',{})
        loop=SimpleNamespace(ready=False);handles={};errors=[]
        def callback(s):
            try:
                if not init(loop,ex,s):return
                if not handles:
                    handles.update({k:getattr(loop,'h_'+k) for k in ('washer','dishwasher','dryer','refrigerator','ev','ewh_sp','cool','heat','hvac_avail')})
                    if any(v<0 for v in handles.values()):raise ValueError('Missing actuator')
                if ex.warmup_flag(s) or ex.kind_of_sim(s)!=3:return
                hour=round(ex.current_time(s),8);on=18<=hour<19
                for key in ('washer','dishwasher','dryer','refrigerator','ev'):
                    ex.set_actuator_value(s,handles[key],.5 if on else 0)
                for key,value in [('ewh_sp',40),('cool',26),('heat',18),('hvac_avail',1)]:ex.set_actuator_value(s,handles[key],value)
            except Exception as e:errors.append(repr(e));api.runtime.stop_simulation(s)
        api.runtime.callback_end_system_timestep_after_hvac_reporting(state,callback)
        with (tmp/'console.txt').open('w') as log,redirect_stdout(log):
            (folder/'stage.json').write_text(json.dumps({'ep_started':True,'stage':'energyplus'}))
            code=api.runtime.run_energyplus(state,['-w',str(ROOT/weather['epw']),'-d',str(tmp),str(idf)])
        api.state_manager.delete_state(state)
        err=(tmp/'eplusout.err').read_text(errors='replace')
        (folder/'eplusout.err').write_text(err)
        if code or errors or re.search(r'\*\*\s*(Severe|Fatal)\s*\*\*',err):raise ValueError((code,errors,err[-1500:]))
        if 'not fully enclosed' in err:raise ValueError('Geometry is not enclosed')
        con=sqlite3.connect(tmp/'eplusout.sql')
        rows=con.execute('''SELECT d.Name,d.KeyValue,d.Units,t.Hour,t.Minute,r.Value
          FROM ReportData r JOIN ReportDataDictionary d USING(ReportDataDictionaryIndex)
          JOIN Time t USING(TimeIndex) JOIN EnvironmentPeriods e USING(EnvironmentPeriodIndex)
          WHERE t.WarmupFlag=0 AND e.EnvironmentType=3 AND d.ReportingFrequency='Zone Timestep' ORDER BY t.TimeIndex''').fetchall();con.close()
        meters={}
        for name,key,unit,h,m,val in rows:
            if name=='Electric Equipment Electricity Energy':meters.setdefault(key,[]).append((h+m/60,val))
        expected={'CLOTHESWASHER_APPLIANCE':1.,'DISHWASHER_APPLIANCE':.75,'CLOTHESDRYER_APPLIANCE':1.5,'REFRIGERATOR_APPLIANCE':.1,'EV_CHARGER':3.5}
        energy={}
        for name,kwh in expected.items():
            points=meters[name];total=sum(v for _,v in points)/3.6e6
            if len(points)!=144 or abs(total-kwh)>1e-6 or any(not(18<h<=19.00001) for h,v in points if v>1e-7):
                raise ValueError(('Bad electrical binding',name,len(points),total))
            energy[name]=total
        result={'passed':True,'ep_started':True,'model_id':model['id'],'weather_id':weather['id'],'date':day,
          'model_sha256':model['sha256'],'weather_sha256':weather['epw_sha256'],
          'prepared_idf_sha256':file_hash(idf),'localization':loc,'handles':handles,'device_kwh':energy,
          'timestep_rows':144,'severe':0,'fatal':0,'zone_not_enclosed':False,
          'warning_messages':len(re.findall(r'\*\*\s*Warning\s*\*\*',err))}
        (folder/'result.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n')
        return result

def main():
    p=argparse.ArgumentParser();p.add_argument('--ep-root',type=Path,default=Path('/Applications/EnergyPlus-24-1-0'))
    p.add_argument('--output',type=Path,default=ROOT/'artifacts/regional_resource_validation')
    p.add_argument('--case',nargs=3,metavar=('MODEL','WEATHER','DATE'));p.add_argument('--workers',type=int,default=4)
    p.add_argument('--resume-report',type=Path)
    p.add_argument('--date-plan',type=Path,help='Station-specific candidate dates from build_date_plan.py')
    p.add_argument('--dates',nargs='+',default=['2007-07-01','2007-07-15','2007-08-01'])
    args=p.parse_args();catalog_path=ROOT/'simulation_resources/catalog.json';c=json.loads(catalog_path.read_text())
    def no_network(event,_):
        if event in ('socket.connect','socket.getaddrinfo'):raise RuntimeError('Offline EP validation')
    sys.addaudithook(no_network)
    if args.case:
        m,w,d=args.case
        case(next(r for r in c['models'] if r['id']==m),next(r for r in c['weather'] if r['id']==w),d,args.ep_root,args.output)
        return
    args.output.mkdir(parents=True,exist_ok=False);initial=file_hash(catalog_path)
    current_context=validation_context(ROOT,args.ep_root)
    previous={};old_context=None
    if args.resume_report:
        previous_report=json.loads(args.resume_report.read_text());old_context=previous_report.get('validation_context')
        for row in previous_report['results']:
            if row['passed']:previous[(row['model_id'],row['weather_id'],row['date'])]=row
    plan=json.loads(args.date_plan.read_text()) if args.date_plan else None
    if plan and (plan.get('version')!='eb.candidate_date_plan.v1' or plan.get('season') not in ('summer','winter','spring','autumn')):
        raise ValueError('Unsupported seasonal candidate plan')
    dates_by_weather={}
    for w in c['weather']:
        if plan:
            row=plan['weather'].get(w['id'])
            if row and row['weather_sha256']!=w['epw_sha256']:raise ValueError('Date plan uses a different EPW')
            dates_by_weather[w['id']]=[r['date'] for r in row['candidates']] if row else []
        else:dates_by_weather[w['id']]=args.dates
    jobs=[(m,w,d) for m in c['models'] for w in c['weather'] for d in dates_by_weather[w['id']]]
    def run(job):
        m,w,d=job;folder=args.output/(m['id']+'__'+w['id']+'__'+d)
        cached=previous.get((m['id'],w['id'],d))
        if reusable(cached,m,w,old_context,current_context):
            return cached
        cmd=[sys.executable,str(Path(__file__).resolve()),'--ep-root',str(args.ep_root),'--output',str(folder),'--case',m['id'],w['id'],d]
        try:proc=subprocess.run(cmd,capture_output=True,text=True,timeout=90)
        except subprocess.TimeoutExpired:
            stage=json.loads((folder/'stage.json').read_text()) if (folder/'stage.json').exists() else {'ep_started':False}
            return {'passed':False,**stage,'model_id':m['id'],'weather_id':w['id'],'date':d,'failure':'Validation exceeded 90 seconds; excluded from sampling'}
        if proc.returncode:
            stage=json.loads((folder/'stage.json').read_text()) if (folder/'stage.json').exists() else {'ep_started':False}
            return {'passed':False,**stage,'model_id':m['id'],'weather_id':w['id'],'date':d,
                    'failure':'EP validation failed; excluded from available date pool',
                    'detail':proc.stderr[-2500:]}
        return json.loads((folder/'result.json').read_text())
    results=[]
    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        for r in pool.map(run,jobs):
            results.append(r)
            if len(results)%75==0:print(f'{len(results)}/{len(jobs)} EP cases checked; {sum(r["passed"] for r in results)} passed',flush=True)
    if file_hash(catalog_path)!=initial:raise ValueError('Catalog changed during validation')
    if validation_context(ROOT,args.ep_root)!=current_context:raise ValueError('Validation code or EnergyPlus changed during run')
    # Preserve old resources before publishing a new catalog or report.
    from resource_versions import freeze
    freeze(catalog_path)
    for row in c['models']:
        if file_hash(ROOT/row['idf'])!=row['sha256']:raise ValueError('Model changed during test')
        row['status']='verified' if any(r['passed'] and r['model_id']==row['id'] for r in results) else 'unavailable'
    for row in c['weather']:
        if file_hash(ROOT/row['epw'])!=row['epw_sha256'] or file_hash(ROOT/row['ddy'])!=row['ddy_sha256']:raise ValueError('Weather changed during test')
        row['status']='verified' if any(r['passed'] and r['weather_id']==row['id'] for r in results) else 'unavailable'
    c['readiness']='engineering_matrix_verified_not_household_calibrated'
    c['validated_dates']={}
    for r in results:
        if r['passed']:c['validated_dates'].setdefault(r['model_id']+'|'+r['weather_id'],[]).append(r['date'])
    report={'matrix_finished':True,'passed_cases':sum(r['passed'] for r in results),'failed_cases':sum(not r['passed'] for r in results),'cases':len(results),'models':len(c['models']),'weather_stations':len(c['weather']),
            'validation_context':current_context,'ep_started_cases':sum(bool(r.get('ep_started')) for r in results),
            'date_plan':plan,
            'paid_api_calls':0,'test_script_sha256':file_hash(__file__),'results':results,
            'scope':'Requested dates per registered model/weather pair. Prechecks and EP starts counted separately. No LLM planning-quality or real-home calibration claim.'}
    target=ROOT/'simulation_resources/validation.json';target.write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')
    c['validation_sha256']=file_hash(target)
    catalog_path.write_text(json.dumps(c,ensure_ascii=False,indent=2)+'\n')
    print('Matrix complete; only successful combinations made available.',flush=True)

if __name__=='__main__':main()
