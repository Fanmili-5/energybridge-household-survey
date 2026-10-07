#!/usr/bin/env python3
"""Independent annual SQL/error/site and copied-parent-byte readback."""
import argparse
import calendar
import csv
import hashlib
import json
import math
import re
import sqlite3
from collections import Counter
from pathlib import Path


def sha(path): return hashlib.sha256(Path(path).read_bytes()).hexdigest()
def read(path): return json.loads(Path(path).read_text())


def expected_selection(parent_summary,inputs):
    ready=sorted((r for r in parent_summary['records'] if r['status']=='idf_ready'),key=lambda r:r['case_id'])
    reasons={};missing=[]
    def add(record,reason): reasons.setdefault(record['case_id'],[]).append(reason)
    for province in sorted({x['site']['province'] for x in inputs.values()}):
        pool=[r for r in ready if inputs[r['case_id']]['site']['province']==province]
        if pool: add(pool[0],'smallest_admitted_slot_in_province:'+province)
        else: missing.append(province)
    for group in sorted({r['prototype_source_group_id'] for r in ready}):
        add(next(r for r in ready if r['prototype_source_group_id']==group),'smallest_admitted_slot_for_source_group:'+group)
    if ready:
        for field,direction in [('H6_building_area_m2','minimum'),('H6_building_area_m2','maximum'),('natural_room_count','maximum'),('resident_count','maximum')]:
            def value(r): return inputs[r['case_id']]['family']['resident_count'] if field=='resident_count' else r[field]
            extreme=min(value(r) for r in ready) if direction=='minimum' else max(value(r) for r in ready)
            add(next(r for r in ready if value(r)==extreme),direction+':'+field)
    return reasons,missing


def read_case(run,result,cached_epws):
    case_id=result['case_id'];folder=run/'cases'/case_id;runtime=run/'runtime'/case_id
    provenance=read(folder/'EXECUTION_PARENT.json');record=provenance['execution_record'];local=[]
    if not all(sha(folder/name)==value for name,value in provenance['original_files_sha256'].items()): local.append('copied_parent_files')
    if sha(Path(provenance['parent_case_path'])/'STATUS.json')!=provenance['parent_status_sha256']: local.append('original_status_bytes')
    if sha(folder/'building.idf')!=result['input_idf_sha256']: local.append('executed_idf_bytes')
    epw=record['weather_epw_path']
    if epw not in cached_epws: cached_epws[epw]=sha(epw)
    if cached_epws[epw]!=result['weather_sha256']: local.append('executed_weather_bytes')
    err=(runtime/'eplusout.err').read_text();end=(runtime/'eplusout.end').read_text()
    counts=Counter(x.lower() for x in re.findall(r'\*\*\s*(Warning|Severe|Fatal)\s*\*\*',err,re.I))
    if 'EnergyPlus Completed Successfully' not in end or counts['severe'] or counts['fatal']: local.append('engine_completion_and_severity')
    sql=sqlite3.connect(runtime/'eplusout.sql')
    try:
        annual={r[0] for r in sql.execute('select TimeIndex from Time where coalesce(WarmupFlag,0)=0 and Interval=60')}
        calendar_rows=sql.execute('select Year,Month,Day,Hour,Minute,EnvironmentPeriodIndex from Time where coalesce(WarmupFlag,0)=0 and Interval=60').fetchall()
        environments={r[0]:r[-1] for r in sql.execute('select * from EnvironmentPeriods')}
        area=sql.execute('select sum(FloorArea) from Zones').fetchone()[0]
        rows=sql.execute("""select d.KeyValue,r.TimeIndex,r.Value from ReportData r
            join ReportDataDictionary d using(ReportDataDictionaryIndex) join Time t using(TimeIndex)
            where d.Name='Zone Mean Air Temperature' and coalesce(t.WarmupFlag,0)=0 and t.Interval=60""").fetchall()
    finally: sql.close()
    byzone={}
    for zone,time_index,value in rows:
        byzone.setdefault(zone,[]).append((time_index,value))
    if len(annual)!=8760 or len(byzone)!=record['zone_count'] or any(len(v)!=8760 or {t for t,x in v}!=annual for v in byzone.values()): local.append('exact_annual_time_index_set_and_zone_hourly_count')
    expected_calendar={(2007,m,d,h,0) for m in range(1,13) for d in range(1,calendar.monthrange(2007,m)[1]+1) for h in range(1,25)}
    env_ids={r[5] for r in calendar_rows}
    if len(calendar_rows)!=8760 or {tuple(r[:5]) for r in calendar_rows}!=expected_calendar or len(env_ids)!=1 or any(environments.get(i)!=3 for i in env_ids): local.append('complete_nonleap2007_weather_run_calendar')
    if area is None or abs(area-record['zone_floor_area_m2'])>1e-5: local.append('sql_area')
    if any(not isinstance(x,(int,float)) or not math.isfinite(x) for v in byzone.values() for t,x in v): local.append('NULL_nonnumeric_or_nonfinite_temperature')
    effective=next(line for line in (runtime/'eplusout.eio').read_text().splitlines() if line.lstrip().startswith('Site:Location,'))
    fields=next(csv.reader([effective]));actual=list(map(float,fields[2:6]))
    expected=read(folder/'WEATHER_MATCH.json')['selected']['epw_location']
    if not all(abs(a-expected[k])<=.011 for a,k in zip(actual,['latitude','longitude','timezone','altitude_m'])): local.append('effective_site')
    if not all(sha(runtime/name)==value for name,value in result.get('output_hashes',{}).items()): local.append('engine_output_bytes')
    if result['status']!='pass' or result.get('SQL_hours')!=8760 or result.get('errors') or dict(counts)!=result.get('severity',{}): local.append('runtime_record_result_consistency')
    return {'case_id':case_id,'pass':not local,'errors':local,'SQL_hours':len(annual),'zones':len(byzone),
            'severity':dict(counts),'source_group_id':record['prototype_source_group_id']}


def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--run-dir',required=True,type=Path)
    ap.add_argument('--output',required=True,type=Path)
    args=ap.parse_args();run=args.run_dir.resolve();summary=read(run/'SUMMARY.json');lock=read(run/'SELECTION_LOCK.json')
    checks=[];cases=[];severity=Counter();cached_epws={}
    def check(name,ok,detail=None): checks.append({'check':name,'pass':bool(ok),'detail':detail})
    check('parent_summary_bytes',sha(lock['parent_summary_path'])==lock['parent_summary_sha256'])
    parent=Path(lock['parent_summary_path']).parent
    check('parent_inputs_actual_bytes',sha(parent/'EXPERIMENT_INPUTS.json')==lock['parent_input_sha256'])
    parent_summary=read(parent/'SUMMARY.json');inputs={x['case_id']:x for x in read(parent/'EXPERIMENT_INPUTS.json')}
    expected,missing=expected_selection(parent_summary,inputs)
    check('independent_selection_rule_and_reasons',expected==lock['reasons'] and sorted(expected)==lock['selected_cases'] and missing==lock['generated_cohort_provinces_without_admitted_case'])
    check('selected_case_set_fixed_before_runs',sorted(r['case_id'] for r in summary['runtime'])==lock['selected_cases'])
    check('engine_and_IDD_actual_bytes',sha(lock['engine']['path'])==lock['engine']['sha256'] and sha(Path(lock['engine']['path']).parent/'Energy+.idd')==lock['engine']['IDD_sha256'])
    check('execution_code_snapshot_bytes',all(sha(run/'code'/name)==value for name,value in lock['code'].items()))
    manifest=read(run/'MANIFEST.json')
    check('runtime_manifest_bytes',all(sha(run/name)==value for name,value in manifest['files'].items()))
    for result in summary['runtime']:
        try:
            case=read_case(run,result,cached_epws)
        except (OSError,ValueError,TypeError,KeyError,IndexError,sqlite3.Error,StopIteration) as exc:
            case={'case_id':result['case_id'],'pass':False,'errors':['annual_readback_exception:'+type(exc).__name__+':'+str(exc)],
                  'runtime_status':result['status'],'runtime_errors':result.get('errors'),'severity_status':'unavailable'}
        cases.append(case);severity.update(case.get('severity',{}))
    check('all_annual_case_readbacks',all(x['pass'] for x in cases),[x for x in cases if not x['pass']])
    check('summary_severity_exact',dict(severity)==summary['severity'])
    check('summary_counts_and_flags',summary['selected_cases']==len(lock['selected_cases']) and
          summary['actual_annual_runs']==len(cases) and summary['passed']==sum(r['status']=='pass' for r in summary['runtime']) and
          summary['failed']==sum(r['status']!='pass' for r in summary['runtime']) and
          summary['all_hourly_series_8760']==all(r.get('SQL_hours')==8760 for r in summary['runtime']))
    report={'experiment_id':summary['experiment_id'],'check_groups':len(checks),'checks':checks,
            'cases_read_back':len(cases),'pass':all(x['pass'] for x in checks),'cases':cases,
            'severity':dict(severity),'checker_sha256':sha(__file__),
            'scope':'actual annual engineering runtime and byte consistency, not calibrated energy or human validity'}
    if args.output.exists(): raise ValueError('new verification output required')
    args.output.write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')
    print(json.dumps({k:v for k,v in report.items() if k not in ['checks','cases']},ensure_ascii=False))
    if not report['pass']: raise SystemExit(1)


if __name__=='__main__': main()
