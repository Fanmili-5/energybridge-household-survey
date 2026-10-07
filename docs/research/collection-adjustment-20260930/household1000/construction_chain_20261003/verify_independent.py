#!/usr/bin/env python3
"""Independent source-stage and runtime readback, no builder imports."""
import argparse
import collections
import datetime
import hashlib
import json
import re
import sqlite3
from pathlib import Path
import pandas as pd

HERE=Path(__file__).resolve().parent
def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def load(p):return json.loads(Path(p).read_text())
def digest(v):return hashlib.sha256(json.dumps(v,sort_keys=True,ensure_ascii=False,separators=(',',':'),allow_nan=False).encode()).hexdigest()
def parsed(p):return [[x.strip() for x in s.split(',')] for s in re.sub(r'!.*','',p.read_text()).split(';') if s.strip()]

def main():
    ap=argparse.ArgumentParser();ap.add_argument('--references',type=Path,required=True)
    ap.add_argument('--witnesses',type=Path,required=True);ap.add_argument('--output',type=Path,required=True);args=ap.parse_args()
    if args.output.exists():raise ValueError('new_verification_output_required')
    errors=[];checks=[]
    def check(name,ok):checks.append({'name':name,'pass':bool(ok)});errors.extend([] if ok else [name])
    lock=load(args.references/'REFERENCE_LOCK.json')
    for path,h in lock['inputs'].items():check('input_bytes:'+Path(path).name,sha(path)==h)
    for path,h in lock['outputs'].items():check('reference_bytes:'+path,sha(args.references/path)==h)
    for path,h in lock['code'].items():check('code_bytes:'+path,sha(args.references/'code'/path)==h)
    source=next(Path(p) for p in lock['inputs'] if p.endswith('CRECS2012.dta'))
    raw=pd.read_stata(source,convert_categoricals=False);city=raw[(raw.valid==1)&(raw.b1==1)]
    rel=[f'a2_{i}_a' for i in range(1,9)]
    inroster=city[rel].isin(range(1,12));n=city.a1
    valid=n.isin(range(1,9)) & (inroster.sum(axis=1)==n) & city[rel].eq(1).sum(axis=1).eq(1)
    for i in range(1,9):valid &= (~inroster[f'a2_{i}_a'])|city[f'a2_{i}_c'].isin(range(1900,2013))
    single=n.eq(1)
    single_adult=pd.Series(False,index=city.index)
    for i in range(1,9):single_adult |= inroster[f'a2_{i}_a'] & (city[f'a2_{i}_c']<=1991)
    valid &= (~single)|single_adult
    bounds={1:(0,12),2:(12,30),3:(30,50),4:(50,70),5:(70,90),6:(90,120),7:(120,150),8:(150,180),9:(180,250),10:(250,None)}
    area=city.b13.isin(bounds)&city.b14.isin(bounds)
    order=pd.Series(True,index=city.index)
    for ix,r in city.iterrows():
        if r.b13 in bounds and r.b14 in bounds:
            upper=bounds[r.b13][1];lower=bounds[r.b14][0]
            if upper is not None and lower>=upper:order.at[ix]=False
    admitted=valid & area & order
    level={1:0,2:0,3:1,4:1,5:-1,6:-1,7:0,8:2,9:-2}
    gknown=pd.Series(False,index=city.index)
    for ix,r in city.iterrows():
        rr=[r[c] for c in rel if r[c] in range(1,12)]
        gknown.at[ix]=(r.a1==1 and len(rr)==1) or bool(rr and all(v in level for v in rr))
    audit=load(args.references/'JOINT_SOURCE_AUDIT.json')['source_stages']
    for name,count in [('city_labeled',len(city)),('roster_birth_single_age_checked',int(valid.sum())),
        ('member_area_interval_checked',int(admitted.sum())),('generation_proxy_known',int((admitted&gknown).sum()))]:
        check('independent_source_stage:'+name,audit[name]['records']==count)
    support=load(args.references/'SLOT1000_REFERENCE_SUPPORT.json');profiles=load(next(Path(p) for p in lock['inputs'] if p.endswith('FAMILY_HOUSING_CANDIDATES.json')))
    check('full1000_unique_source_support',len(support['rows'])==1000 and {r['slot_id'] for r in support['rows']}=={r['slot_id'] for r in profiles['profiles']})
    wlock=load(args.witnesses/'WITNESS_LOCK.json');base=Path(load(args.witnesses/'CHAIN_VERIFICATION.json')['base_case'])
    for name,h in wlock['code'].items():check('runtime_code_snapshot:'+name,sha(args.witnesses/'code'/name)==h)
    check('base_IDF_immutable',sha(base/'building.idf')==wlock['base_IDF_sha256'])
    check('base_INPUT_immutable',sha(base/'INPUT.json')==wlock['base_INPUT_sha256'])
    summary=[]
    for folder in sorted(p for p in args.witnesses.iterdir() if (p/'ASSET_BUNDLE.json').exists()):
        b=load(folder/'ASSET_BUNDLE.json');idf=folder/'physical/witness.idf';rs=parsed(idf)
        check(folder.name+':family_binding',b['binding']['family_sha256']==digest(load(base/'INPUT.json')['family']))
        check(folder.name+':housing_binding',b['binding']['housing_sha256']==digest(load(base/'INPUT.json')['housing']))
        equipment=[r for r in rs if r[0].lower()=='electricequipment']
        check(folder.name+':one_combo_two_channels',len(b['assets'])==1 and len(equipment)==2)
        check(folder.name+':no_HVAC_or_water_service_claim',not any(r[0].lower().startswith(('waterheater:','zonehvac:')) for r in rs))
        dt=int(next(r[1] for r in rs if r[0].lower()=='timestep'))
        period=next(r for r in rs if r[0].lower()=='runperiod')
        expected_weekday=datetime.date(int(period[4]),int(period[2]),int(period[3])).strftime('%A')
        check(folder.name+':calendar_weekday',period[8]==expected_weekday)
        db=sqlite3.connect(folder/'physical/run/eplusout.sql')
        data=db.execute('''SELECT d.Name,d.KeyValue,d.Units,r.Value,t.Month,t.Day,t.Interval
            FROM ReportData r JOIN ReportDataDictionary d USING(ReportDataDictionaryIndex)
            JOIN Time t USING(TimeIndex) JOIN EnvironmentPeriods e USING(EnvironmentPeriodIndex)
            WHERE t.WarmupFlag=0 AND e.EnvironmentType=3 AND d.ReportingFrequency='Zone Timestep' ''').fetchall();db.close()
        phase_energy=collections.defaultdict(float);meter=[]
        for name,key,unit,value,month,day,interval in data:
            if name not in ['Electric Equipment Electricity Energy','Electricity:Facility']:continue
            check(folder.name+':meter_calendar_interval',month==7 and day==1 and interval==60/dt and unit=='J')
            if name=='Electricity:Facility':meter.append(value/3.6e6)
            else:phase_energy[key]+=value/3.6e6
        expected=0
        for k,p in enumerate(b['assets'][0]['operation_phases']):
            e=p['input_power_W']*(p['end_minute']-p['start_minute'])/60000;expected+=e
            check(folder.name+':phase'+str(k),abs(phase_energy[b['assets'][0]['asset_id'].upper()+'_PHASE'+str(k)]-e)<1e-7)
        check(folder.name+':facility_closure',len(meter)==24*dt and abs(sum(meter)-expected)<1e-7)
        err=(folder/'physical/run/eplusout.err').read_text()
        check(folder.name+':no_fatal_severe',not re.search(r'\*\*\s*(Severe|Fatal)\s*\*\*',err))
        summary.append({'case':folder.name,'measured_kWh':sum(meter),'expected_kWh':expected,'steps_per_hour':dt,
            'meter_intervals':len(meter),'warning_markers':len(re.findall(r'\*\*\s*Warning\s*\*\*',err))})
    result={'schema':'eb.construction_chain_independent_verification.v1','pass':not errors,'check_count':len(checks),
        'failed':errors,'checks':checks,'runtime':summary,'builder_or_source_semantics_imported':False,
        'scope':'independent aggregate source-stage and actual IDF/SQL electricity/calendar readback; not population transport or device service validity',
        'collection_release':False,'training_release':False}
    args.output.write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n')
    print(json.dumps({k:result[k] for k in ['pass','check_count','failed','runtime']},ensure_ascii=False))
    if not result['pass']:raise SystemExit(1)

if __name__=='__main__':main()
