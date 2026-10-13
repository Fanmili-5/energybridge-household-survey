"""Observe original50 summer curve inputs without changing coefficients/limits.

Identical per-coil copies avoid a shared curve's last-call report concealing
other coils. Detailed reports distinguish actual use from automatic ratings.
"""
import collections,concurrent.futures,copy,sqlite3,subprocess,os
from common import *
from compile_inputs import get,put
from physics import ENGINE,frame
FIELDS=['total_cooling_capacity_function_of_temperature_curve_name','total_cooling_capacity_function_of_flow_fraction_curve_name',
    'energy_input_ratio_function_of_temperature_curve_name','energy_input_ratio_function_of_flow_fraction_curve_name','part_load_fraction_correlation_curve_name']

def job(c,side):
    rows=parse(OUT/c[side]['IDF_path']);curves={r[1]:r for r in rows if r[0].startswith('Curve:')};coils=[r for r in rows if r[0]=='Coil:Cooling:DX:SingleSpeed'];meta=[]
    for coil in coils:
        for field in FIELDS:
            old=get(coil,field);r=copy.deepcopy(curves[old]);name=coil[1]+'_'+old;r[1]=name;rows.append(r);put(coil,field,name)
            dims=2 if r[0]=='Curve:Biquadratic' else 1;bounds=[]
            for axis in ('x','y')[:dims]:bounds.append([float(get(r,'minimum_value_of_'+axis)),float(get(r,'maximum_value_of_'+axis))])
            meta.append({'coil':coil[1],'curve':name,'original_curve':old,'field':field,'bounds':bounds,'coefficients_and_limits_unchanged':r[2:]==curves[old][2:]})
            for v in ['Performance Curve Output Value']+[f'Performance Curve Input Variable {i+1} Value' for i in range(dims)]:rows.append(['Output:Variable',name,v,'Detailed'])
        rows.append(['Output:Variable',coil[1],'Cooling Coil Electricity Rate','Detailed'])
        rows.append(['Output:Variable',coil[1],'Cooling Coil Runtime Fraction','Detailed'])
    rows.append(['Output:Diagnostics','DisplayExtraWarnings'])
    folder=OUT/'curve_domain_diagnostic'/c['household_id']/f'{c["round_index"]:02d}_{side}';folder.mkdir(parents=True,exist_ok=True);idf=folder/'observer.idf';idf.write_text(dump(rows))
    run=folder/'run';proc=subprocess.run([str(ENGINE),'-w',c['weather']['path'],'-d',str(run),str(idf)],stdout=subprocess.PIPE,stderr=subprocess.STDOUT,text=True,env={**os.environ,'OMP_NUM_THREADS':'1'},timeout=900)
    (folder/'engine.log').write_text(proc.stdout);err=(run/'eplusout.err').read_text();assert proc.returncode==0 and not any(x in err for x in ('** Severe **','**  Fatal **'))
    db=sqlite3.connect('file:'+str(run/'eplusout.sql')+'?mode=ro',uri=True)
    data=db.execute('SELECT t.TimeIndex,d.Name,d.KeyValue,r.Value FROM ReportData r JOIN ReportDataDictionary d USING(ReportDataDictionaryIndex) JOIN Time t USING(TimeIndex) WHERE t.WarmupFlag=0 AND (d.Name LIKE "Performance Curve%" OR d.Name="Cooling Coil Electricity Rate" OR d.Name="Cooling Coil Runtime Fraction")').fetchall();db.close();steps=collections.defaultdict(dict)
    for ti,name,key,value in data:steps[ti][name,(key or '').upper()]=value
    statistics=[]
    for m in meta:
        counts=collections.Counter();ranges=[[] for _ in m['bounds']];examples=[]
        for ti,f in steps.items():
            power=f.get(('Cooling Coil Electricity Rate',m['coil'].upper()),0.)
            if power<=1e-8:continue
            xs=[f.get((f'Performance Curve Input Variable {i+1} Value',m['curve'].upper())) for i in range(len(ranges))]
            val=f.get(('Performance Curve Output Value',m['curve'].upper()))
            if any(x is None or x==-999 for x in xs) or val in (None,-999):continue
            counts['active_reported_steps']+=1
            for i,(x,(lo,hi)) in enumerate(zip(xs,m['bounds'])):
                ranges[i].append(x)
                if x<lo-1e-6 or x>hi+1e-6:
                    counts['outside_original_limits_axis'+str(i+1)]+=1
                    if len(examples)<2:examples.append({'time_index':ti,'axis':i+1,'raw_input':x,'original_bounds':[lo,hi]})
        statistics.append({**m,'counts':dict(counts),'raw_input_ranges':[[min(xs),max(xs)] if xs else None for xs in ranges],'examples':examples})
    # Observer identity check on the unchanged electricity outputs.
    def energy(sql):
        con=sqlite3.connect('file:'+str(sql)+'?mode=ro',uri=True)
        values=con.execute('SELECT t.SimulationDays,t.Hour,t.Minute,r.Value FROM ReportData r JOIN ReportDataDictionary d USING(ReportDataDictionaryIndex) JOIN Time t USING(TimeIndex) WHERE t.WarmupFlag=0 AND d.Name="Electricity:Facility" ORDER BY t.SimulationDays,t.Hour,t.Minute').fetchall();con.close();return values
    baseline=OUT/'runs/base7'/c['household_id']/f'{c["round_index"]:02d}_{side}'/'eplusout.sql';left=energy(baseline);right=energy(run/'eplusout.sql');assert len(left)==len(right)
    diff=max(abs(a[3]-b[3]) for a,b in zip(left,right));assert diff<.001
    record={'household_id':c['household_id'],'round_index':c['round_index'],'arm':side,'observer_IDF_sha256':sha(idf),'baseline_IDF_sha256':c[side]['IDF_sha256'],
        'SQL_path':str((run/'eplusout.sql').relative_to(OUT)),'SQL_sha256':sha(run/'eplusout.sql'),'unchanged_meter_max_difference_J':diff,
        'curve_statistics':statistics,'AHRI_rating_warning_lines':[s.strip() for s in err.splitlines() if 'AHRI' in s or 'out of bound' in s]}
    save(folder/'REVIEW.json',record);return record

def main():
    school_guard();rows=read(OUT/'COMPILED50.json')['records'];sel=read(OUT/'SELECTION50.json')['records'];summer={h['household_id']:next(r['round_index'] for r in h['rounds'] if 7<=int(r['date'][5:7])<=9) for h in sel}
    jobs=[(c,s) for c in rows if c['variant']=='base7' and c['round_index']==summer[c['household_id']] for s in ('A','B')];records=[]
    with concurrent.futures.ThreadPoolExecutor(max_workers=16) as pool:
        fs=[pool.submit(job,*x) for x in jobs]
        for f in concurrent.futures.as_completed(fs):records.append(f.result())
    statistics=[s for r in records for s in r['curve_statistics']];clipped=[s for s in statistics if any(k.startswith('outside') and n for k,n in s['counts'].items())]
    report={'schema':'eb.original50_actual_curve_domain_diagnostic.v1','households':50,'runs':len(records),'records':records,
        'active_curve_reports':sum(s['counts'].get('active_reported_steps',0) for s in statistics),'curves_with_out_of_limit_active_reports':len(clipped),
        'original_EB_coefficients_and_limits_changed':False,'source':'EnergyPlus24.1 CurveManager reports raw input before bound clipping; detailed per-coil identical curve copies',
        'standard_rating_domain_warning_is_separate_from_actual_operating_domain':True,'AHRI_SEER_or_manufacturer_calibration_claim':False,
        'native_clamping_is_a_reference_model_boundary_not_an_empirical_extrapolation_validation':True,'other950_executed':False,'human_answers':0}
    save(OUT/'CURVE_DOMAIN_REVIEW.json',report);print({k:v for k,v in report.items() if k!='records'},flush=True)
if __name__=='__main__':main()
