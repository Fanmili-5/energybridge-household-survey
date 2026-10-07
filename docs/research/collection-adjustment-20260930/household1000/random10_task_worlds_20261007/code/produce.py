"""School-only, resumable production of independently sampled three-day pairs."""
import concurrent.futures, datetime as dt, gzip, shutil, traceback
from common import *
from programs import trace,schedules,round_spec
from compile_physics import compile_idf,run,SOURCE_HVAC
from readback import sql_frame,check_meter,pair
LOADED_CODE={n:sha(OUT/'code'/n) for n in ['common.py','programs.py','compile_physics.py','readback.py','produce.py']}

def archive(folder):
    if folder.exists():
        root=OUT/'development/replaced_before_current_signature';root.mkdir(parents=True,exist_ok=True)
        target=root/(folder.parent.name+'_'+folder.name);i=1
        while target.exists():target=root/(folder.parent.name+'_'+folder.name+'_'+str(i));i+=1
        shutil.move(str(folder),str(target))

def gzsave(path,data):
    path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(gzip.compress(canonical(data).encode(),mtime=0))

def execute(physical,folder,signature):
    existing=folder/'RUN_RECORD.json'
    if existing.exists():
        r=read(existing)
        if r.get('input_signature')==signature and r['IDF_sha256']==physical['IDF_sha256'] and r['returncode']==0 and not r['severe_fatal']:
            assert sha(OUT/r['SQL_path'])==r['SQL_sha256'];return r
    archive(folder);r=run(physical,folder);r['input_signature']=signature;save(folder/'RUN_RECORD.json',r)
    assert r['returncode']==0 and not r['severe_fatal'],('EP_run_failed',folder,r['severe_fatal'])
    return r

def one_case(binding,w,case,signature,namespace=None):
    hid=binding['household_id'];index=case['round_index'];tag=f'{index:02d}' if namespace is None else namespace
    root=OUT/'episodes'/hid/tag;cp=root/'CASE.json';save(cp,case)
    origin=case['context']['episode_start_date'];a=trace(w,3,start_date=origin);b=trace(w,3,case,start_date=origin)
    nominal=schedules(w,a)
    for kind,p in [('A',a),('B',b)]:gzsave(root/(kind+'_PROGRAM.json.gz'),p)
    ab=compile_idf(w,binding,nominal,root/'A.idf',origin);ar=execute(ab,root/'A',signature)
    af,au=sql_frame(OUT/ar['SQL_path']);am=check_meter(af,au,ar['physical_components'],a['rows'])
    signals=[k for k in ['washer','dishwasher','dryer','ev','tank_setpoint_C','water_draw_fraction','ac_setpoint_C'] if any(x[k]!=y[k] for x,y in zip(a['rows'],b['rows']))]
    if signals:
        bb=compile_idf(w,binding,nominal,root/'B.idf',origin,case,b['rows']);br=execute(bb,root/'B',signature)
        bf,bu=sql_frame(OUT/br['SQL_path'])
    else:
        br={**ar,'reused_identical_A_physics':True,'identity_proof':digest({'A':a['rows'],'B':b['rows'],'case_sha256':sha(cp)}),
            'cache_reason':'identical complete episode physical signals and common initialization'};bf,bu=af,au
    result=pair(w,case,ar,br,af,bf,au,bu,a,b);result['A_meter_and_program_checks']=am;result['executed_different_signals']=signals
    result['EP_runs_executed_or_exact_cached']=2 if signals else 1;result['identical_B_reused']=not signals
    rp=root/'PAIR_RESULT.json';save(rp,result)
    return {'round_index':index,'date':case['context']['date'],'case_path':str(cp.relative_to(OUT)),'case_sha256':sha(cp),
        'paired_result_path':str(rp.relative_to(OUT)),'paired_result_sha256':sha(rp),
        'A_SQL_path':ar['SQL_path'],'A_SQL_sha256':ar['SQL_sha256'],'B_SQL_path':br['SQL_path'],'B_SQL_sha256':br['SQL_sha256'],
        'reused_identical_A':not signals,'warnings_A':ar['warnings'],'warnings_B':br['warnings'],
        'episode_dates':[origin,case['context']['episode_end_date']],'maximum_predecision_output_difference':result['maximum_predecision_output_difference'],
        'event_reduction_kWh':result['event_reduction_kWh'],'48h_reduction_kWh':result['48h_reduction_kWh']}

def one(binding):
    assert all(sha(OUT/'code'/n)==h for n,h in LOADED_CODE.items()),'running code changed;results not admitted'
    hid=binding['household_id'];w=read(OUT/binding['world_path'])
    signature=digest({'world':sha(OUT/binding['world_path']),'loaded_code':LOADED_CODE,'kernel':sha(UP/'energybridge/simulation/appliance_sim.py'),
        'HVAC':sha(SOURCE_HVAC),'weather':binding['weather']['sha256'],'engine':sha(ENGINE),'schema':sha(EP_ROOT/'Energy+.schema.epJSON')})
    completed=OUT/'production_records'/f'{hid}.json'
    if completed.exists():
        old=read(completed)
        if old.get('input_signature')==signature and not old.get('failure'):
            for row in old['rounds']:
                assert sha(OUT/row['paired_result_path'])==row['paired_result_sha256']
                assert sha(OUT/row['A_SQL_path'])==row['A_SQL_sha256']
                assert sha(OUT/row['B_SQL_path'])==row['B_SQL_sha256']
            return old
    rounds=[]
    for index in range(1,11):
        rounds.append(one_case(binding,w,round_spec(w,index),signature))
        save(OUT/'progress'/f'{hid}.json',{'household_id':hid,'input_signature':signature,'completed_rounds':len(rounds),'last_date':rounds[-1]['date']})
    assert all(sha(OUT/'code'/n)==h for n,h in LOADED_CODE.items()),'running code changed;results not admitted'
    result={'household_id':hid,'world_path':binding['world_path'],'world_sha256':binding['world_sha256'],'input_signature':signature,
        'loaded_code_sha256':LOADED_CODE,'rounds':rounds,'failure':None,'annual_EP_runs':0,'formal_human_answers':0}
    save(completed,result);return result

def safe(binding):
    try:return one(binding)
    except Exception as exc:
        result={'household_id':binding['household_id'],'failure':str(exc),'traceback':traceback.format_exc(),'household_or_date_not_replaced':True}
        save(OUT/'production_failures'/f"{binding['household_id']}.json",result);return result

def main():
    if sys.platform!='linux':raise SystemExit('All EP interfaces,pilots,and production must run on school Linux')
    guard();allbindings=read(OUT/'WORLD_BINDINGS1000.json')['records'];selected=allbindings
    if '--pilot' in sys.argv:
        wanted=['ordinary-v6-0001','ordinary-v6-0002','ordinary-v6-0139','ordinary-v6-0216'];selected=[b for b in allbindings if b['household_id'] in wanted]
    if '--ids' in sys.argv:
        wanted=sys.argv[sys.argv.index('--ids')+1].split(',');selected=[b for b in allbindings if b['household_id'] in wanted]
    workers=int(sys.argv[sys.argv.index('--workers')+1]) if '--workers' in sys.argv else 16;output=[]
    with concurrent.futures.ProcessPoolExecutor(workers) as pool:
        futures={pool.submit(safe,b):b['household_id'] for b in selected}
        for future in concurrent.futures.as_completed(futures):
            result=future.result();output.append(result)
            print({'completed_households':len(output),'planned_households':len(selected),'failed':sum(bool(x.get('failure')) for x in output),'household_id':result['household_id']},flush=True)
    report={'engine_host':'school Linux','households_requested':len(selected),'households_complete':sum(not x.get('failure') for x in output),
        'paired_rounds':sum(len(x.get('rounds',[])) for x in output),'annual_EP_runs':0,
        'A_episode_inputs':sum(len(x.get('rounds',[])) for x in output),
        'distinct_B_episode_inputs':sum(sum(not r['reused_identical_A'] for r in x.get('rounds',[])) for x in output),
        'identical_B_reuses':sum(sum(r['reused_identical_A'] for r in x.get('rounds',[])) for x in output),
        'failures':[x for x in output if x.get('failure')],'records':output,'formal_human_answers':0}
    save(OUT/('PILOT_PRODUCTION.json' if '--pilot' in sys.argv else 'PRODUCTION1000.json'),report)
    print({k:v for k,v in report.items() if k not in ['records','failures']},flush=True)
    if report['failures']:raise SystemExit(2)
if __name__=='__main__':main()
