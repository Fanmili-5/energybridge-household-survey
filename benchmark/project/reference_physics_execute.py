"""Bounded process execution/readback; resume completed arms without rerunning.

One native engine attempt per frozen arm. Failure is terminal for that arm in
this run. A resumable manifest/attempt receipt fixes IDF, weather and engine;
neither success nor failure triggers a replacement plan or another engine try.
"""
import argparse
import json
import subprocess
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path
from benchmark.housing_simulation.pipeline import read,save,sha,seal,verify,sql_trace,portable_gzip


def execute_arm(job):
    ident,side=job['id'],job['side'];folder=Path(job['folder']);source=Path(job['source']);meta=read(source/'INPUT.json.gz')
    binding={k:job[k] for k in ('id','side','engine_sha256','weather_sha256')}
    binding.update(idf_sha256=sha(source/'model.idf'),compiled_input_sha256=sha(source/'INPUT.json.gz'))
    if binding['idf_sha256']!=meta['idf_sha256'] or sha(job['weather_path'])!=binding['weather_sha256']:raise ValueError('ARM_INPUT_CHANGED')
    result_path=folder/'RESULT.json'
    if result_path.exists():
        result=read(result_path)
        if result['id']!=ident or result['side']!=side:raise ValueError('CACHED_ARM_IDENTITY_CHANGED')
        if result['status']=='completed':
            if any(result[k]!=binding[k] for k in ('idf_sha256','engine_sha256')) or result['SQL_sha256']!=sha(folder/'out/eplusout.sql') or result['trace_sha256']!=sha(folder/'TRACE.json.gz'):raise ValueError('CACHED_ARM_BINDING_CHANGED')
        return result
    folder.mkdir(parents=True,exist_ok=True);attempt=folder/'ATTEMPT.json'
    if attempt.exists():
        if read(attempt)!=binding:raise ValueError('ATTEMPT_BINDING_CHANGED')
    else:save(attempt,binding)
    native=folder/'out';reused=native.exists();stdout=folder/'stdout.txt'
    if not reused:
        try:
            run=subprocess.run([job['engine'],'-w',job['weather_path'],'-d',str(native),str(source/'model.idf')],capture_output=True,text=True,timeout=job['timeout'])
            stdout.write_text(run.stdout+run.stderr)
        except (OSError,subprocess.TimeoutExpired) as e:
            result={**binding,'status':'readback_or_engine_failed','reason':str(e)};save(result_path,result);return result
    errors=(native/'eplusout.err').read_text() if (native/'eplusout.err').exists() else ''
    result={**binding,'status':'completed' if 'EnergyPlus Completed Successfully' in errors else 'engine_failed',
        'evaluated_interval_min':[0,meta['run_interval_min'][1]],'energy_scope':'facility electricity over evaluated interval;not automatically daily or equal-service savings',
        'warnings':[l for l in errors.splitlines() if '** Warning **' in l],
        'engine_completion_is_not_service_success':True,'human_acceptance':None,'readback_of_existing_engine_attempt':reused}
    try:
        if result['status']=='completed':
            channels=sql_trace(native/'eplusout.sql',meta['history_days'],meta.get('simulation_timestep_min',10))
            expected=list(range(0,meta['run_interval_min'][1],10))
            if any([t for t,v in c['values']]!=expected for c in channels.values()):raise ValueError('INCOMPLETE_OUTPUT_TIMELINE')
            save(folder/'TRACE.json.gz',channels)
            result.update(SQL_sha256=sha(native/'eplusout.sql'),trace_sha256=sha(folder/'TRACE.json.gz'),
                facility_energy_kWh=sum(v for t,v in channels['Electricity:Facility|']['values'])/3600000)
    except (OSError,ValueError)as e:result.update(status='readback_or_engine_failed',reason=str(e))
    save(result_path,result)
    for name in ('eplusout.eso','eplusout.mtr'):
        path=native/name
        if path.exists():path.with_suffix(path.suffix+'.gz').write_bytes(portable_gzip(path.read_bytes()));path.unlink()
    return result


def execute(compiled,out,engine,engine_sha256,workers=4):
    if type(workers)is not int or not 1<=workers<=16:raise ValueError('WORKERS_MUST_BE1_TO16')
    compiled,out,engine=map(lambda p:Path(p).resolve(),(compiled,out,engine));m=verify(compiled)
    if sha(engine)!=engine_sha256:raise ValueError('ENGINE_CHANGED')
    version=subprocess.check_output([str(engine),'--version'],text=True).strip()
    if '24.1.0-9d7789a3ac'not in version:raise ValueError('ENGINE_VERSION_UNSUPPORTED')
    if (out/'MANIFEST.json').exists():return verify(out)
    out.mkdir(parents=True,exist_ok=True);start={'compiled_manifest_sha256':sha(compiled/'MANIFEST.json'),'engine_sha256':engine_sha256,'engine_version':version}
    if (out/'EXECUTION_START.json').exists():
        if read(out/'EXECUTION_START.json')!=start:raise ValueError('RESUME_INPUTS_CHANGED')
    elif any(out.iterdir()) and not (out/'DRIVER_REPLACEMENT.json').exists():raise ValueError('EXISTING_UNBOUND_RUN_REQUIRES_EXPLICIT_ADOPTION_RECEIPT')
    else:save(out/'EXECUTION_START.json',start)
    jobs=[dict(id=r['id'],side=s,folder=str(out/r['id']/s),source=str(compiled/r['id']/s),engine=str(engine),
        engine_sha256=engine_sha256,weather_path=r['weather_path'],weather_sha256=r['weather_sha256'],timeout=600)
        for r in m['records'] if r['status']=='compiled' for s in ('A','B')]
    records=[]
    with ProcessPoolExecutor(max_workers=workers)as pool:
        for result in pool.map(execute_arm,jobs):
            records.append(result)
            if len(records)%20==0:print(json.dumps({'stage':'native_and_readback','arm_receipts':len(records),'total':len(jobs)}),flush=True)
    records.extend({'id':r['id'],'status':'compile_failed'}for r in m['records'] if r['status']!='compiled')
    verify(compiled)
    if sha(engine)!=engine_sha256:raise ValueError('ENGINE_CHANGED_DURING_EXECUTION')
    return seal(out,{'schema':'eb.housing_physics.execution.v1','engine_version':version,'compiled_manifest_sha256':start['compiled_manifest_sha256'],
        'records':records,'whole_benchmark_validated':False,'human_answers_created':0,'execution_driver_sha256':sha(Path(__file__))})
