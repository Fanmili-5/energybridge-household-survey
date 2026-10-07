"""Resumable production; all failures retained, no successful-family replacement."""
import concurrent.futures, datetime as dt, gzip, shutil, traceback
from common import *
from programs import trace,write_schedules,round_spec,START
from compile_physics import compile_idf,run,SOURCE_HVAC
from readback import sql_frame,check_meter,pair,annual_energy
LOADED_CODE={n:sha(OUT/'code'/n) for n in ['common.py','programs.py','compile_physics.py','readback.py','produce.py']}

def archive(folder):
    if folder.exists():
        root=OUT/'development/replaced_before_current_signature';root.mkdir(parents=True,exist_ok=True)
        target=root/(folder.parent.name+'_'+folder.name);i=1
        while target.exists():target=root/(folder.parent.name+'_'+folder.name+'_'+str(i));i+=1
        shutil.move(str(folder),str(target))
def gzsave(path,data):
    path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(gzip.compress(canonical(data).encode(),mtime=0))

def one(binding):
    assert all(sha(OUT/'code'/n)==h for n,h in LOADED_CODE.items()),'running code changed;stop before continuing'
    hid=binding['household_id'];w=read(OUT/binding['world_path']);signature=digest({'world':w['world_content_sha256'],'loaded_code':LOADED_CODE,'kernel':sha(UP/'energybridge/simulation/appliance_sim.py'),'HVAC':sha(SOURCE_HVAC),'weather':binding['weather']['sha256']})
    completed=OUT/'production_records'/f'{hid}.json'
    if completed.exists():
        old=read(completed)
        if old.get('input_signature')==signature and not old.get('failure'):
            assert sha(OUT/old['annual']['SQL_path'])==old['annual']['SQL_sha256']
            return old
    a=trace(w);base_csv=OUT/'schedules'/hid/'A.csv';cols=write_schedules(w,a,base_csv)
    gzsave(OUT/'programs'/hid/'A_PROGRAM_LEDGER.json.gz',{k:v for k,v in a.items() if k!='rows'})
    base=compile_idf(w,binding,base_csv,cols,OUT/'idfs'/hid/'A.idf',dt.date(2026,6,30));folder=OUT/'runs'/hid/'A';existing=folder/'RUN_RECORD.json'
    if existing.exists() and read(existing).get('input_signature')==signature and not read(existing)['severe_fatal']:annual=read(existing)
    else:
        archive(folder);annual=run(base,folder);annual['input_signature']=signature;save(folder/'RUN_RECORD.json',annual)
    assert annual['returncode']==0 and not annual['severe_fatal'],('annual_run_failed',hid)
    aframe,aunits=sql_frame(OUT/annual['SQL_path']);annenergy=annual_energy(OUT/annual['SQL_path']);meter=check_meter(aframe,aunits,annual['physical_components'],a['rows'])
    save(OUT/'annual_results'/f'{hid}.json',{'world_content_sha256':w['world_content_sha256'],'SQL_path':annual['SQL_path'],'SQL_sha256':annual['SQL_sha256'],'annual_energy':annenergy,'prefix_meter_checks':meter})
    rounds=[];runs=[]
    for index in range(1,11):
        case=round_spec(w,index);rpath=OUT/'rounds'/hid/f'{index:02d}.json';save(rpath,case);endday=case['context']['evaluation_end_day_index'];b=trace(w,endday+1,case)
        signals=[k for k in ['washer','dishwasher','dryer','ev','tank_setpoint_C','water_draw_fraction','ac_setpoint_C'] if any(x[k]!=y[k] for x,y in zip(a['rows'],b['rows']))]
        gzsave(OUT/'programs'/hid/f'B{index:02d}_PROGRAM_LEDGER.json.gz',{k:v for k,v in b.items() if k!='rows'})
        if not signals:
            shifted={**annual,'reused_identical_A_physics':True,'cache_reason':'all executed physical signal values identical oncomplete simulatedprefix;not a new run'};bframe,bunits=aframe,aunits
        else:
            csvpath=OUT/'schedules'/hid/f'B{index:02d}.csv';bcols=write_schedules(w,b,csvpath,annual_base=a['rows'],selected_signals=signals)
            if w['assets']['ev']['present']:
                assert abs(b['states'][-1]['EV_SOC_after_step']-a['states'][len(b['rows'])-1]['EV_SOC_after_step'])<1e-10,'postprefix EV state not recovered;annual suffix reuse forbidden'
            physical=compile_idf(w,binding,csvpath,bcols,OUT/'idfs'/hid/f'B{index:02d}.idf',dt.date(2026,6,30),base_schedule=base_csv,base_columns=cols,case=case,desired_rows=b['rows'])
            rfolder=OUT/'runs'/hid/f'B{index:02d}';existing=rfolder/'RUN_RECORD.json'
            if existing.exists() and read(existing).get('input_signature')==signature and read(existing).get('case_sha256')==sha(rpath) and not read(existing)['severe_fatal']:shifted=read(existing)
            else:
                archive(rfolder);shifted=run(physical,rfolder);shifted.update({'input_signature':signature,'case_sha256':sha(rpath)});save(rfolder/'RUN_RECORD.json',shifted)
            assert shifted['returncode']==0 and not shifted['severe_fatal'],('branch_run_failed',hid,index)
            bframe,bunits=sql_frame(OUT/shifted['SQL_path']);runs.append({'round_index':index,**shifted})
        result=pair(w,case,annual,shifted,aframe,bframe,aunits,bunits,a,b);rp=OUT/'paired_results'/hid/f'{index:02d}.json';save(rp,result)
        rounds.append({'round_index':index,'case_path':str(rpath.relative_to(OUT)),'case_sha256':sha(rpath),'paired_result_path':str(rp.relative_to(OUT)),'paired_result_sha256':sha(rp),'B_SQL_path':shifted['SQL_path'],'B_SQL_sha256':shifted['SQL_sha256'],'reused_identical_A':not signals})
    assert all(sha(OUT/'code'/n)==h for n,h in LOADED_CODE.items()),'running code changed;results not admitted'
    result={'household_id':hid,'world_path':binding['world_path'],'world_sha256':binding['world_sha256'],'input_signature':signature,'loaded_code_sha256':LOADED_CODE,'annual':annual,'annual_energy':annenergy,'new_branch_runs':runs,'rounds':rounds,'failure':None,'formal_human_answers':0}
    save(completed,result);return result

def safe(binding):
    try:return one(binding)
    except Exception as exc:
        result={'household_id':binding['household_id'],'failure':str(exc),'traceback':traceback.format_exc(),'family_not_replaced':True}
        save(OUT/'production_failures'/f"{binding['household_id']}.json",result);return result
def main():
    guard();allbindings=read(OUT/'WORLD_BINDINGS1000.json')['records'];selected=allbindings
    if '--pilot' in sys.argv:
        wanted=['ordinary-v6-0001','ordinary-v6-0002','ordinary-v6-0139','ordinary-v6-0216'];selected=[b for b in allbindings if b['household_id'] in wanted]
    if '--ids' in sys.argv:
        wanted=sys.argv[sys.argv.index('--ids')+1].split(',');selected=[b for b in allbindings if b['household_id'] in wanted]
    output=[]
    workers=int(sys.argv[sys.argv.index('--workers')+1]) if '--workers' in sys.argv else 4
    executor=concurrent.futures.ProcessPoolExecutor if '--processes' in sys.argv else concurrent.futures.ThreadPoolExecutor
    with executor(workers) as pool:
        for result in pool.map(safe,selected):
            output.append(result);n=len(output)
            if n%20==0 or len(selected)<10:print({'completed':n,'planned':len(selected),'failed':sum(x.get('failure') is not None for x in output)},flush=True)
    report={'households_requested':len(selected),'households_complete':sum(not x.get('failure') for x in output),'failures':[x for x in output if x.get('failure')],
            'annual_inputs_run':sum(not x.get('failure') for x in output),'paired_rounds':sum(len(x.get('rounds',[])) for x in output),'new_B_inputs_run':sum(len(x.get('new_branch_runs',[])) for x in output),'identical_B_reuses':sum(sum(r['reused_identical_A'] for r in x.get('rounds',[])) for x in output),'records':output,'formal_human_answers':0}
    save(OUT/('PILOT_PRODUCTION.json' if '--pilot' in sys.argv else 'PRODUCTION1000.json'),report)
    print({k:v for k,v in report.items() if k not in ['records','failures']},flush=True)
if __name__=='__main__':main()
