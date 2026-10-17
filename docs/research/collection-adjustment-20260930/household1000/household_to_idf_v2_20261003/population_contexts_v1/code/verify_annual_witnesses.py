#!/usr/bin/env python3
"""Independent annual SQL/error/site and copied-parent-byte readback."""
import argparse
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


def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--run-dir',required=True,type=Path)
    ap.add_argument('--output',required=True,type=Path)
    args=ap.parse_args();run=args.run_dir.resolve();summary=read(run/'SUMMARY.json');lock=read(run/'SELECTION_LOCK.json')
    checks=[];cases=[];severity=Counter();cached_epws={}
    def check(name,ok,detail=None): checks.append({'check':name,'pass':bool(ok),'detail':detail})
    check('parent_summary_bytes',sha(lock['parent_summary_path'])==lock['parent_summary_sha256'])
    check('selected_case_set_fixed_before_runs',sorted(r['case_id'] for r in summary['runtime'])==lock['selected_cases'])
    check('engine_and_IDD_actual_bytes',sha(lock['engine']['path'])==lock['engine']['sha256'] and sha(Path(lock['engine']['path']).parent/'Energy+.idd')==lock['engine']['IDD_sha256'])
    check('execution_code_snapshot_bytes',all(sha(run/'code'/name)==value for name,value in lock['code'].items()))
    manifest=read(run/'MANIFEST.json')
    check('runtime_manifest_bytes',all(sha(run/name)==value for name,value in manifest['files'].items()))
    for result in summary['runtime']:
        case_id=result['case_id'];folder=run/'cases'/case_id;runtime=run/'runtime'/case_id
        provenance=read(folder/'EXECUTION_PARENT.json');record=provenance['execution_record'];local=[]
        if not all(sha(folder/name)==value for name,value in provenance['original_files_sha256'].items()): local.append('copied_parent_files')
        if sha(Path(provenance['parent_case_path'])/'STATUS.json')!=provenance['parent_status_sha256']: local.append('original_status_bytes')
        if sha(folder/'building.idf')!=result['input_idf_sha256']: local.append('executed_idf_bytes')
        epw=record['weather_epw_path']
        if epw not in cached_epws: cached_epws[epw]=sha(epw)
        if cached_epws[epw]!=result['weather_sha256']: local.append('executed_weather_bytes')
        err=(runtime/'eplusout.err').read_text();end=(runtime/'eplusout.end').read_text()
        counts=Counter(x.lower() for x in re.findall(r'\*\*\s*(Warning|Severe|Fatal)\s*\*\*',err,re.I));severity.update(counts)
        if 'EnergyPlus Completed Successfully' not in end or counts['severe'] or counts['fatal']: local.append('engine_completion_and_severity')
        sql=sqlite3.connect(runtime/'eplusout.sql')
        hours=sql.execute('select count(*) from Time where coalesce(WarmupFlag,0)=0 and Interval=60').fetchone()[0]
        area=sql.execute('select sum(FloorArea) from Zones').fetchone()[0]
        rows=sql.execute("""select d.KeyValue,count(*),min(r.Value),max(r.Value),avg(r.Value)
            from ReportData r join ReportDataDictionary d using(ReportDataDictionaryIndex)
            join Time t using(TimeIndex) where d.Name='Zone Mean Air Temperature'
            and coalesce(t.WarmupFlag,0)=0 group by d.KeyValue""").fetchall();sql.close()
        if hours!=8760 or len(rows)!=record['zone_count'] or any(r[1]!=8760 for r in rows): local.append('hourly_count')
        if area is None or abs(area-record['zone_floor_area_m2'])>1e-5: local.append('sql_area')
        if any(not math.isfinite(x) for r in rows for x in r[2:]): local.append('nonfinite_temperature')
        effective=next(line for line in (runtime/'eplusout.eio').read_text().splitlines() if line.lstrip().startswith('Site:Location,'))
        fields=next(csv.reader([effective]));actual=list(map(float,fields[2:6]))
        expected=read(folder/'WEATHER_MATCH.json')['selected']['epw_location']
        if not all(abs(a-expected[k])<=.011 for a,k in zip(actual,['latitude','longitude','timezone','altitude_m'])): local.append('effective_site')
        if not all(sha(runtime/name)==value for name,value in result['output_hashes'].items()): local.append('engine_output_bytes')
        cases.append({'case_id':case_id,'pass':not local,'errors':local,'SQL_hours':hours,
                      'zones':len(rows),'severity':dict(counts),'source_group_id':record['prototype_source_group_id']})
    check('all_annual_case_readbacks',all(x['pass'] for x in cases),[x for x in cases if not x['pass']])
    check('summary_severity_exact',dict(severity)==summary['severity'])
    report={'experiment_id':summary['experiment_id'],'check_groups':len(checks),'checks':checks,
            'cases_read_back':len(cases),'pass':all(x['pass'] for x in checks),'cases':cases,
            'severity':dict(severity),'checker_sha256':sha(__file__),
            'scope':'actual annual engineering runtime and byte consistency, not calibrated energy or human validity'}
    if args.output.exists(): raise ValueError('new verification output required')
    args.output.write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')
    print(json.dumps({k:v for k,v in report.items() if k not in ['checks','cases']},ensure_ascii=False))
    if not report['pass']: raise SystemExit(1)


if __name__=='__main__': main()
