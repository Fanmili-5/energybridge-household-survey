#!/usr/bin/env python3
"""Exercise runtime readback refusal without launching EnergyPlus."""
import argparse,json,math,os,sqlite3,sys
from pathlib import Path
from types import SimpleNamespace
HERE=Path(__file__).resolve().parents[1];sys.path.insert(0,str(HERE))
import run_stage as rs
from household_model import save,sha

def main(output):
    output=output.resolve()
    if output.exists():raise ValueError('use new output directory')
    output.mkdir(parents=True);checks=[]
    source=HERE/'core_static_v1';record=json.loads((source/'cases/design_n3_g2_h72/STATUS.json').read_text())
    selected=json.loads((source/'cases/design_n3_g2_h72/WEATHER_MATCH.json').read_text())['selected']
    zone_names=[s['name'] for s in json.loads((source/'cases/design_n3_g2_h72/LAYOUT.json').read_text())['spaces']]
    original_run=rs.subprocess.run
    annual_modes=['valid_hour_control','null_hour','duplicate_hour','non_numeric_hour','wrong_hour_index']
    for mode in ['engine_oserror','corrupt_sqlite','bad_eio_float','sql_infinite_value','invalid_sql_schema','process_unicode_error',*annual_modes]:
        out=output/mode;case=out/'cases'/record['case_id'];case.mkdir(parents=True)
        save(case/'WEATHER_MATCH.json',{'selected':selected})
        def mock_run(command,**kwargs):
            folder=Path(command[command.index('-d')+1])
            if mode=='engine_oserror':raise FileNotFoundError('synthetic absent engine')
            if mode=='process_unicode_error':raise UnicodeDecodeError('utf-8',b'\xff',0,1,'synthetic invalid output')
            (folder/'eplusout.end').write_text('EnergyPlus Completed Successfully')
            (folder/'eplusout.err').write_text('')
            if mode=='corrupt_sqlite':(folder/'eplusout.sql').write_bytes(b'not a sqlite database')
            else:
                db=sqlite3.connect(folder/'eplusout.sql')
                if mode!='invalid_sql_schema':
                    db.execute('create table Time(TimeIndex integer,WarmupFlag integer,Interval integer)')
                    db.executemany('insert into Time values(?,0,60)',[(i,) for i in range(1,8761)] if mode in annual_modes else [(1,)])
                    if mode=='wrong_hour_index':db.execute('insert into Time values(8761,0,30)')
                    db.execute('create table Zones(FloorArea real)');db.execute('insert into Zones values(?)',(record['zone_floor_area_m2'],))
                    db.execute('create table ReportDataDictionary(ReportDataDictionaryIndex integer,KeyValue text,Name text)')
                    for index,name in enumerate(zone_names if mode in annual_modes else ['natural_1'],1):
                        db.execute('insert into ReportDataDictionary values(?,?,?)',(index,name,'Zone Mean Air Temperature'))
                    db.execute('create table ReportData(ReportDataDictionaryIndex integer,TimeIndex integer,Value real)')
                    if mode in annual_modes:
                        readings=[]
                        for zone in range(1,len(zone_names)+1):
                            for hour in range(1,8761):
                                ti=8759 if mode=='duplicate_hour' and zone==1 and hour==8760 else 8761 if mode=='wrong_hour_index' and zone==1 and hour==10 else hour
                                value=None if mode=='null_hour' and zone==1 and hour==10 else 'not_numeric' if mode=='non_numeric_hour' and zone==1 and hour==10 else 20.
                                readings.append((zone,ti,value))
                        db.executemany('insert into ReportData values(?,?,?)',readings)
                    else:db.execute('insert into ReportData values(1,1,?)',(float('inf') if mode=='sql_infinite_value' else 20,))
                db.commit();db.close()
            loc=selected['epw_location'];values=[loc[k] for k in ['latitude','longitude','timezone','altitude_m']]
            if mode=='bad_eio_float':values[0]='not-a-float'
            (folder/'eplusout.eio').write_text('Site:Location,synthetic,'+','.join(map(str,values)))
            return SimpleNamespace(returncode=0,stdout='synthetic process output; no engine invoked',stderr='')
        rs.subprocess.run=mock_run
        try:result=rs.runtime_one(record,out,{'status':'mocked_readback_probe_no_EnergyPlus'})
        finally:rs.subprocess.run=original_run
        report=out/'runtime'/record['case_id']/'RUNTIME_CHECK.json';parsed=json.loads(report.read_text())
        errors=result['errors']
        if mode in ['engine_oserror','corrupt_sqlite','invalid_sql_schema','process_unicode_error']:
            ok=any(x.startswith('runtime_readback_exception:') for x in errors)
        elif mode=='sql_infinite_value':
            ok='runtime_number_not_finite_binary64' in errors and result['zone_temperatures']['natural_1']['maximum_C'] is None
            ok=ok and Path(result['rejected_numeric_trace_path']).is_file() and sha(Path(result['rejected_numeric_trace_path']))==result['rejected_numeric_trace_sha256']
        elif mode in ['null_hour','non_numeric_hour']:ok='temperature_series_null_or_non_numeric_values' in errors
        elif mode in ['duplicate_hour','wrong_hour_index']:ok='temperature_series_hour_index_set_mismatch' in errors
        elif mode=='valid_hour_control':ok=not errors
        else:ok='effective_engine_site_location_mismatch' in errors
        probe={'check':mode,'pass':ok and result['status']==('pass' if mode=='valid_hour_control' else 'failed') and parsed==result,'errors':errors,'report_sha256':sha(report)}
        if mode in ['null_hour','duplicate_hour','wrong_hour_index']:
            db=sqlite3.connect(report.parent/'eplusout.sql')
            legacy=db.execute("""select d.KeyValue,min(r.Value),max(r.Value),avg(r.Value),count(*) from ReportData r
                join ReportDataDictionary d using(ReportDataDictionaryIndex) join Time t using(TimeIndex)
                where d.Name='Zone Mean Air Temperature' and coalesce(t.WarmupFlag,0)=0 group by d.KeyValue""").fetchall();db.close()
            probe['legacy_aggregate_only_would_pass']=len(legacy)==record['zone_count'] and all(r[4]==8760 and all(math.isfinite(v) for v in r[1:4]) for r in legacy)
            probe['pass']=probe['pass'] and probe['legacy_aggregate_only_would_pass']
        checks.append(probe)
    result={'schema':'eb.runtime_readback_refusal_regression.v2','pass':all(x['pass'] for x in checks),'check_count':len(checks),'checks':checks,
        'run_stage_sha256':sha(HERE/'run_stage.py'),'script_sha256':sha(Path(__file__)),
        'scope':'mocked subprocess outputs and actual synthetic SQLite readback; no EnergyPlus invocation or annual/physical calibration claim'}
    save(output/'RUNTIME_REFUSAL_CHECK.json',result);print(json.dumps(result));return 0 if result['pass'] else 1

if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--output',type=Path,required=True)
    raise SystemExit(main(parser.parse_args().output))
