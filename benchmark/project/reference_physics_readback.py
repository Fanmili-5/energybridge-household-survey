"""Correct native Sum/Avg report aggregation without another engine attempt.

Keep the original sealed run intact. Link its immutable native files into a new
derived run, replace only TRACE/RESULT, and bind both original SQL and run hash.
This changes no engine input, scalar energy, temperature, A/B plan or selection.
"""
import argparse
import json
import os
import shutil
import sqlite3
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path
from benchmark.housing_simulation.pipeline import read,save,seal,sha,verify


def correct_arm(job):
    source,target=Path(job['source']),Path(job['target']);target.mkdir(parents=True)
    for path in sorted(source.rglob('*')):
        if not path.is_file()or path.name in ('TRACE.json.gz','RESULT.json'):continue
        new=target/path.relative_to(source);new.parent.mkdir(parents=True,exist_ok=True);os.link(path,new)
    result=read(source/'RESULT.json');changes=[]
    if result['status']=='completed':
        trace=read(source/'TRACE.json.gz')
        if result['trace_sha256']!=sha(source/'TRACE.json.gz')or result['SQL_sha256']!=sha(source/'out/eplusout.sql'):raise ValueError('ORIGINAL_RUN_CORRUPTED')
        with sqlite3.connect('file:'+str(source/'out/eplusout.sql')+'?mode=ro',uri=True)as db:
            kinds={name+'|'+(key or ''):kind for name,key,kind in db.execute('SELECT Name,KeyValue,Type FROM ReportDataDictionary')}
        for name,c in trace.items():
            kind=kinds[name]
            if kind not in ('Sum','Avg'):raise ValueError('UNKNOWN_NATIVE_AGGREGATION')
            if 'native_aggregation'in c:
                if c['native_aggregation']!=kind:raise ValueError('AGGREGATION_TYPE_CHANGED')
            else:
                native=c.get('native_timestep_min',10);report=c.get('report_timestep_min',10)
                if kind=='Sum'and c['unit']!='J'and report!=native:
                    factor=report/native;c['values']=[[t,v*factor]for t,v in c['values']];changes.append(name)
                c['native_aggregation']=kind
        save(target/'TRACE.json.gz',trace)
        result.update(trace_sha256=sha(target/'TRACE.json.gz'),source_trace_sha256=sha(source/'TRACE.json.gz'),
            corrected_cumulative_channels=changes,aggregation_source='native SQL ReportDataDictionary.Type',
            engine_reexecuted=False)
    save(target/'RESULT.json',result);return result


def correct(compiled,source,out,workers=4):
    compiled,source,out=map(lambda p:Path(p).resolve(),(compiled,source,out));verify(compiled);m=verify(source)
    if m['compiled_manifest_sha256']!=sha(compiled/'MANIFEST.json'):raise ValueError('COMPILED_SOURCE_MISMATCH')
    out.mkdir(parents=True,exist_ok=False)
    jobs=[{'source':str(source/r['id']/r['side']),'target':str(out/r['id']/r['side'])} for r in m['records'] if 'side'in r]
    with ProcessPoolExecutor(max_workers=workers)as pool:records=list(pool.map(correct_arm,jobs))
    records.extend(r for r in m['records'] if 'side'not in r)
    verify(source)
    result=seal(out,{'schema':'eb.housing_physics.execution.v1','engine_version':m['engine_version'],
        'compiled_manifest_sha256':m['compiled_manifest_sha256'],'source_native_runs_manifest_sha256':sha(source/'MANIFEST.json'),
        'readback_code_sha256':sha(Path(__file__)),'records':records,'new_engine_attempts':0,'human_answers_created':0,
        'whole_benchmark_validated':False})
    return {'arm_receipts':len(records),'arms_with_cumulative_channels_corrected':sum(bool(r.get('corrected_cumulative_channels'))for r in records),'new_engine_attempts':0,'runs_manifest_sha256':sha(out/'MANIFEST.json')}


if __name__=='__main__':
    p=argparse.ArgumentParser()
    for name in ('compiled','source','out'):p.add_argument('--'+name,required=True)
    p.add_argument('--workers',type=int,default=4);a=p.parse_args();print(json.dumps(correct(a.compiled,a.source,a.out,a.workers)))
