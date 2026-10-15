"""Independently compare requested thermal controls with emitted SQL schedules."""
import argparse,collections,concurrent.futures,importlib,json,sqlite3,sys
from pathlib import Path

def worker(item):
    stage,c=item
    sys.path.insert(0,str(stage/'code'))
    from common import read,sha
    from contrast_core import control_segments
    from zone_controls import groups,idf_bindings
    p=read(stage/c['pair_path']);w=read(stage/c['world_path']);binding=idf_bindings(w,p,c)
    ds={d['asset_id']:d for d in w['parameter_pack']['devices']};checks=0;fail=[];hashes={}
    for side in ('A','B'):
        expected={};names=c[side]['signal_names'];prior=c[side]['prior_days']*1440
        for x in control_segments(p):
            if x['kind']not in ('ac_setpoint','tank_setpoint'):continue
            aid=x['asset_id'];value=x[side]
            if x['kind']=='ac_setpoint':
                controller=groups(w)[ds[aid]['room_id']][0]
                signals=[(names[controller],50. if value is None else value),
                    (names[aid+':available'],0. if value is None else 1.)]
            else:signals=[(names[aid],10. if value is None else value)]
            for name,value in signals:
                for minute in range(max(0,x['start_min']),min(4320,x['end_min']),10):
                    key=(name.upper(),(prior+minute)//10)
                    assert key not in expected or abs(expected[key]-value)<1e-8
                    expected[key]=value
        if not expected:continue
        receipt=read(stage/'runs'/c['variant']/c['household_id']/f'{c["round_index"]:02d}_{side}/RUN_RECORD.json')
        sql=stage/receipt['SQL_path'];assert sha(sql)==receipt['SQL_sha256'];hashes[side]=receipt['SQL_sha256']
        db=sqlite3.connect('file:'+str(sql)+'?mode=ro',uri=True)
        keys=sorted({k[0]for k in expected});wanted=db.execute('SELECT ReportDataDictionaryIndex,KeyValue FROM ReportDataDictionary WHERE Name="Schedule Value" AND ReportingFrequency="Zone Timestep" AND UPPER(KeyValue) IN ('+','.join('?'for _ in keys)+')',keys).fetchall()
        dictionary={i:key.upper()for i,key in wanted};actual={}
        query='''SELECT t.SimulationDays,t.Hour,t.Minute,r.ReportDataDictionaryIndex,r.Value FROM ReportData r JOIN Time t USING(TimeIndex)
          WHERE t.WarmupFlag=0 AND r.ReportDataDictionaryIndex IN ('''+','.join('?'for _ in dictionary)+')'
        for day,hour,minute,di,value in db.execute(query,list(dictionary)):
            ix=round(((day-1)*1440+hour*60+minute)/10)-1;key=(dictionary[di],ix)
            if key in expected:actual[key]=value
        db.close()
        for key,value in expected.items():
            checks+=1
            if key not in actual or abs(actual[key]-value)>1e-6:
                fail.append({'side':side,'signal':key[0],'minute':key[1]*10-prior,'expected':value,'actual':actual.get(key)})
    return {'case_id':p['case_id'],'variant':c['variant'],'checks':checks,'failures':fail,'SQL_sha256':hashes,
        'actual_IDF_thermostat_bindings':binding}

def main(stage,scope,workers):
    sys.path.insert(0,str(stage/'code'))
    from cohort_gate import require_reviewed_ep,scoped_rows
    from common import save
    lease=require_reviewed_ep(scope);rows=scoped_rows(scope)
    with concurrent.futures.ProcessPoolExecutor(max_workers=workers)as pool:records=list(pool.map(worker,[(stage,c)for c in rows],chunksize=4))
    failures=[{'case_id':r['case_id'],'variant':r['variant'],'errors':r['failures']}for r in records if r['failures']]
    report={'schema':'eb.actual_control_SQL_comparison.v30','scope':scope,'passed':not failures,
        'pairs_scanned':len(records),'thermal_schedule_samples_checked':sum(r['checks']for r in records),
        'input_signature':lease['review']['input_signature'],'failures':failures,'records':records,'EP_started':False}
    save(stage/f'CONTROL_SQL_{scope}_REVIEW.json',report)
    print({k:v for k,v in report.items()if k!='records'},flush=True)
    if failures:raise RuntimeError('Actual controls differ from system proposal;hold acceptance')
if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--stage',type=Path,required=True);p.add_argument('--scope',choices=['original50','other950','weather_sensitivity'],required=True);p.add_argument('--workers',type=int,default=16);a=p.parse_args();main(a.stage.resolve(),a.scope,a.workers)
