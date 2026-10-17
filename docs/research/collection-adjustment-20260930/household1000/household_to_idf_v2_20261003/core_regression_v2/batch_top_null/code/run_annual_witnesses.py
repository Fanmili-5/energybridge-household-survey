#!/usr/bin/env python3
"""Run a deterministic coverage witness set from an immutable static cohort.

Select smallest admitted slot per province and per source group, then four
input extremes. This tests engineering coverage, not population energy means.
All static refusals remain in the parent denominator. Selection is persisted
before EnergyPlus runs and never changed in response to runtime outcomes.
"""
import argparse
import json
import shutil
import subprocess
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from household_model import sha, save
from run_stage import ENGINE, runtime_one

HERE = Path(__file__).resolve().parent


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--parent', required=True, type=Path)
    ap.add_argument('--output', required=True, type=Path)
    ap.add_argument('--workers', type=int, default=4, choices=[1, 2, 3, 4])
    args = ap.parse_args()
    parent, out = args.parent.resolve(), args.output.resolve()
    if out.exists(): raise ValueError('new immutable witness directory required')
    summary = json.loads((parent/'SUMMARY.json').read_text())
    inputs = {x['case_id']:x for x in json.loads((parent/'EXPERIMENT_INPUTS.json').read_text())}
    ready = sorted((r for r in summary['records'] if r['status']=='idf_ready'), key=lambda r:r['case_id'])
    selected, reasons = {}, {}
    def add(record, reason):
        selected[record['case_id']] = record
        reasons.setdefault(record['case_id'], []).append(reason)
    provinces = sorted({x['site']['province'] for x in inputs.values()})
    missing = []
    for province in provinces:
        pool = [r for r in ready if inputs[r['case_id']]['site']['province']==province]
        if pool: add(pool[0], 'smallest_admitted_slot_in_province:'+province)
        else: missing.append(province)
    for group in sorted({r['prototype_source_group_id'] for r in ready}):
        add(next(r for r in ready if r['prototype_source_group_id']==group), 'smallest_admitted_slot_for_source_group:'+group)
    if ready:
        for field, direction in [('H6_building_area_m2','minimum'),('H6_building_area_m2','maximum'),
                                 ('natural_room_count','maximum'),('resident_count','maximum')]:
            def value(r):
                return inputs[r['case_id']]['family']['resident_count'] if field=='resident_count' else r[field]
            extreme = min(value(r) for r in ready) if direction=='minimum' else max(value(r) for r in ready)
            add(next(r for r in ready if value(r)==extreme), direction+':'+field)
    out.mkdir(parents=True)
    (out/'code').mkdir()
    for path in HERE.glob('*.py'): shutil.copy2(path, out/'code'/path.name)
    version = subprocess.run([str(ENGINE),'--version'],capture_output=True,text=True,check=True).stdout.strip()
    engine = {'path':str(ENGINE),'version':version,'sha256':sha(ENGINE),'IDD_sha256':sha(ENGINE.parent/'Energy+.idd')}
    experiment = 'HOUSEHOLD_TO_IDF_V2_ANNUAL__'+out.name
    executions = []
    for case_id, record in sorted(selected.items()):
        source = parent/'cases'/case_id
        if sha(source/'building.idf')!=record['idf_sha256'] or sha(record['weather_epw_path'])!=record['weather_epw_sha256']:
            raise ValueError('parent_IDF_or_EPW_binding_mismatch:'+case_id)
        destination = out/'cases'/case_id
        shutil.copytree(source,destination)
        copied = {p.name:sha(p) for p in destination.iterdir() if p.is_file()}
        original = {p.name:sha(p) for p in source.iterdir() if p.is_file()}
        if copied!=original: raise ValueError('copied_case_bytes_mismatch:'+case_id)
        execution = {**record,'idf_path':str(destination/'building.idf'),'experiment_id':experiment}
        executions.append(execution)
        save(destination/'EXECUTION_PARENT.json',{'parent_case_path':str(source),'parent_status_sha256':sha(source/'STATUS.json'),
            'original_files_sha256':original,'selection_reasons':reasons[case_id],
            'execution_record':execution,'only_execution_path_and_experiment_id_changed':True})
    save(out/'SELECTION_LOCK.json',{'experiment_id':experiment,'parent_summary_path':str(parent/'SUMMARY.json'),
        'parent_summary_sha256':sha(parent/'SUMMARY.json'),'parent_input_sha256':sha(parent/'EXPERIMENT_INPUTS.json'),
        'parent_cohort_cases':summary['case_count'],'parent_ready':len(ready),'parent_refused':summary['blocked'],
        'selection_rule':__doc__,'selected_cases':sorted(selected),'reasons':reasons,
        'generated_cohort_provinces_without_admitted_case':missing,'code':{p.name:sha(p) for p in (out/'code').glob('*.py')},
        'engine':engine,'max_concurrent_engines':args.workers,'selection_uses_runtime_results':False})
    results = []
    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        jobs = {pool.submit(runtime_one,r,out,engine):r for r in executions}
        for job in as_completed(jobs):
            try:
                result = job.result()
            except Exception as exc:
                record=jobs[job]
                result={'case_id':record['case_id'],'status':'failed',
                        'errors':['runtime_worker_exception:'+type(exc).__name__+':'+str(exc)],
                        'experiment_id':experiment,'engine':engine,
                        'input_idf_sha256':record['idf_sha256'],'weather_sha256':record['weather_epw_sha256']}
                save(out/'runtime'/record['case_id']/'WORKER_FAILURE.json',result)
            results.append(result)
            print(json.dumps({'case':result['case_id'],'status':result['status'],'hours':result.get('SQL_hours'),
                              'errors':result['errors']},ensure_ascii=False),flush=True)
    severity = Counter()
    for result in results: severity.update(result.get('severity',{}))
    save(out/'SUMMARY.json',{'experiment_id':experiment,'scope':'annual free-floating shell engineering coverage witnesses',
        'selected_cases':len(executions),'actual_annual_runs':len(results),'passed':sum(r['status']=='pass' for r in results),
        'failed':sum(r['status']!='pass' for r in results),'source_groups':len({r['prototype_source_group_id'] for r in executions}),
        'climate_contexts':len({r['weather_epw_sha256'] for r in executions}),
        'provinces':len({inputs[r['case_id']]['site']['province'] for r in executions}),
        'generated_cohort_provinces_without_admitted_case':missing,'severity':dict(severity),
        'all_hourly_series_8760':all(r.get('SQL_hours')==8760 for r in results),
        'not_all1000_annual_simulations':True,'national_energy_or_human_validity_estimated':False,
        'operational_load_attached':False,'collection_release':False,'training_release':False,
        'runtime':sorted(results,key=lambda r:r['case_id'])})
    save(out/'MANIFEST.json',{'files':{str(p.relative_to(out)):sha(p) for p in out.rglob('*') if p.is_file()},
                            'experiment_id':experiment})
    print(json.dumps({k:v for k,v in json.loads((out/'SUMMARY.json').read_text()).items() if k!='runtime'},ensure_ascii=False),flush=True)


if __name__=='__main__': main()
