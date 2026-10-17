#!/usr/bin/env python3
"""Read real SQLite/raw warnings independently; no engine invocation."""
import argparse,calendar,collections,hashlib,json,math,re,sqlite3
from pathlib import Path

def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()

def main(run,output):
    summary=json.loads((run/'SUMMARY.json').read_text());results=[]
    expected={(2007,m,d,h,0) for m in range(1,13) for d in range(1,calendar.monthrange(2007,m)[1]+1) for h in range(1,25)}
    for r in summary['runtime']:
        folder=run/'runtime'/r['case_id'];sql=folder/'eplusout.sql'
        con=sqlite3.connect('file:'+str(sql.resolve())+'?mode=ro',uri=True);errors=[]
        # EnergyPlus stores NULL rather than 0 for ordinary non-warmup records.
        time=con.execute('SELECT t.TimeIndex,t.Year,t.Month,t.Day,t.Hour,t.Minute FROM Time t JOIN EnvironmentPeriods e USING(EnvironmentPeriodIndex) WHERE e.EnvironmentType=3 AND t.Interval=60 AND COALESCE(t.WarmupFlag,0)=0').fetchall()
        indices={v[0] for v in time};calendar_set={tuple(v[1:]) for v in time}
        if len(time)!=8760 or len(indices)!=8760 or calendar_set!=expected:errors.append('annual_calendar_or_unique_hour_set_invalid')
        zones={};dictionary=con.execute("SELECT ReportDataDictionaryIndex,KeyValue FROM ReportDataDictionary WHERE Name='Zone Mean Air Temperature' AND ReportingFrequency='Hourly'").fetchall()
        for index,name in dictionary:
            values=con.execute('SELECT TimeIndex,Value,typeof(Value) FROM ReportData WHERE ReportDataDictionaryIndex=?',(index,)).fetchall()
            actual=[v for v in values if v[0] in indices]
            ok=len(actual)==8760 and len({v[0] for v in actual})==8760 and {v[0] for v in actual}==indices and all(v[2] in ['real','integer'] and math.isfinite(v[1]) for v in actual)
            if not ok:errors.append('invalid_zone_hourly_values:'+name)
            nums=[v[1] for v in actual if isinstance(v[1],(int,float)) and math.isfinite(v[1])]
            zones[name]={'actual_hourly_rows':len(actual),'unique_hours':len({v[0] for v in actual}),'finite_complete':ok,'minimum_C':min(nums) if nums else None,'maximum_C':max(nums) if nums else None,'mean_C':sum(nums)/len(nums) if nums else None}
        layout=json.loads((run/'cases'/r['case_id']/'LAYOUT.json').read_text())
        if {v.upper() for v in zones}!={s['name'].upper() for s in layout['spaces']}:errors.append('zone_layout_set_mismatch')
        con.close();raw=(folder/'eplusout.err').read_text();counts=collections.Counter(re.findall(r'\*\*\s*(Warning|Severe|Fatal)\s*\*\*',raw))
        warning_blocks=[];lines=raw.splitlines()
        for i,line in enumerate(lines):
            if not re.search(r'\*\*\s*Warning\s*\*\*',line):continue
            block=[line];j=i+1
            while j<len(lines) and ('**   ~~~   **' in lines[j] or '**  Fatal  **' in lines[j]):block.append(lines[j]);j+=1
            warning_blocks.append({'line':i+1,'raw_block':block})
        results.append({'case_id':r['case_id'],'runtime_status':r['status'],'actual_SQL_sha256':sha(sql),'actual_err_sha256':sha(folder/'eplusout.err'),'actual_annual_hours':len(time),'calendar_exact_2007':calendar_set==expected,'zone_results':zones,'warnings':warning_blocks,'raw_severity_markers':dict(counts),'errors':errors})
    result={'scope':'real annual SQL/warning readback and ground design sensitivity; not empirical/functional calibration','source_summary_path':str(run/'SUMMARY.json'),'source_summary_sha256':sha(run/'SUMMARY.json'),'verifier_sha256':sha(Path(__file__)),'actual_runs':len(results),'all_complete':bool(results) and all(not r['errors'] for r in results),'warning_cases':sum(bool(r['warnings']) for r in results),'raw_warning_markers':sum(r['raw_severity_markers'].get('Warning',0) for r in results),'numerical_clean_all_cases':False,'ground_design_C':[10,18,25],'ground_temperatures_source':'predeclared conditional boundary, not measured local soil/floor or EPW undisturbed temperature','frozen_outputs_modified':False,'results':results}
    output.write_text(json.dumps(result,ensure_ascii=False,indent=2,allow_nan=False)+'\n');print(json.dumps({k:v for k,v in result.items() if k!='results'},ensure_ascii=False))

if __name__=='__main__':
    ap=argparse.ArgumentParser();ap.add_argument('--run',type=Path,required=True);ap.add_argument('--output',type=Path,required=True);args=ap.parse_args();main(args.run.resolve(),args.output.resolve())
