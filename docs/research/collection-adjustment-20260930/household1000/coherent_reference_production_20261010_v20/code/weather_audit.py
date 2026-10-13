"""Independent bounded wet-bulb reference and weather-only attribution test."""
import json,os,re,sqlite3,subprocess
from common import *
import psychrolib_reference as psy
psy.SetUnitSystem(psy.SI)
KEYS=['Site Outdoor Air Drybulb Temperature','Site Outdoor Air Wetbulb Temperature','Site Outdoor Air Humidity Ratio','Site Outdoor Air Barometric Pressure']
def compare(sql):
    db=sqlite3.connect('file:'+str(sql)+'?mode=ro',uri=True)
    rows=db.execute('SELECT t.TimeIndex,d.Name,r.Value FROM ReportData r JOIN ReportDataDictionary d USING(ReportDataDictionaryIndex) JOIN Time t USING(TimeIndex) WHERE t.WarmupFlag=0 AND d.Name LIKE "Site Outdoor Air%"').fetchall();db.close();f={}
    for i,k,v in rows:f.setdefault(i,{})[k]=v
    errors=[];examples=[];same_phase_bad=0;phase_different=0;residuals=[];bounds_bad=0
    for i,v in f.items():
        if not all(k in v for k in KEYS):continue
        ref=float(psy.GetTWetBulbFromHumRatio(v[KEYS[0]],v[KEYS[2]],v[KEYS[3]]));actual=v[KEYS[1]]
        errors.append(abs(ref-actual))
        db=v[KEYS[0]];humidity=v[KEYS[2]];pressure=v[KEYS[3]]
        residual=abs(float(psy.GetHumRatioFromTWetBulb(db,actual,pressure))-humidity);residuals.append(residual)
        dew=float(psy.GetTDewPointFromHumRatio(db,humidity,pressure))
        bounds_bad+=not dew-.05<=actual<=db+.05
        if abs(ref-actual)>.05:
            if (ref<0)!=(actual<0):phase_different+=1
            else:same_phase_bad+=1
        if abs(ref-actual)>.05:examples.append({'time_index':i,'drybulb_C':v[KEYS[0]],'humidity_ratio':v[KEYS[2]],'pressure_Pa':v[KEYS[3]],'EP_wetbulb_C':actual,'bounded_reference_wetbulb_C':ref})
    assert errors
    return {'steps':len(errors),'maximum_error_C':max(errors),'over_prespecified_0_05C':len(examples),'examples':examples[:10],
            'different_ice_water_branch_count':phase_different,'same_branch_over_0_05C':same_phase_bad,
            'maximum_returned_solution_humidity_residual_kg_kg':max(residuals),'wetbulb_thermodynamic_bounds_failures':bounds_bad}
def main():
    school_guard();manifest=read(OUT/'COMPILED50.json')['records'];c=next(c for c in manifest if c['household_id']=='ordinary-v6-0204' and c['round_index']==2 and c['variant']=='base7')
    rows=parse(OUT/c['A']['IDF_path']);minimal=[r for r in rows if r[0] in ('Version','Building','GlobalGeometryRules','Timestep','SimulationControl','RunPeriod','Site:Location')]
    minimal += [['Output:Variable','*',k,'Timestep'] for k in KEYS]+[['Output:SQLite','SimpleAndTabular']]
    path=OUT/'weather_diagnostic/minimal.idf';path.parent.mkdir(parents=True,exist_ok=True);path.write_text(dump(minimal));out=path.parent/'run'
    proc=subprocess.run(['/home/hku_user3/energybridge-compute/EnergyPlus-24-1-0/energyplus','-w',c['weather']['path'],'-d',str(out),str(path)],stdout=subprocess.PIPE,stderr=subprocess.STDOUT,text=True,env={**os.environ,'OMP_NUM_THREADS':'1'},timeout=120)
    (path.parent/'engine.log').write_text(proc.stdout);err=(out/'eplusout.err').read_text();assert proc.returncode==0,err
    minimal_comparison=compare(out/'eplusout.sql');records=[]
    for r in read(OUT/'EP_all_REVIEW.json')['records']:
        if r['arm']!='A' or not r['warnings']['psychrometric_domain']:continue
        records.append({'household_id':r['household_id'],'round_index':r['round_index'],'SQL_sha256':r['SQL_sha256'],**compare(OUT/r['SQL_path'])})
    report={'schema':'eb.independent_weather_solver_diagnostic.v2','weather_only_IDF_sha256':sha(path),'weather_sha256':c['weather']['sha256'],
        'minimal_model_has_zones_or_HVAC':False,'minimal_model_reproduced_PsyPsatFnTemp_warning':'(PsyPsatFnTemp)' in err,
        'minimal_warning_lines':[s.strip() for s in err.splitlines() if any(k in s for k in ('PsyPsatFnTemp','Input Temperature=','Routine=PsyTwb'))],
        'minimal_reported_wetbulb_comparison':minimal_comparison,'affected_A_cases':records,
        'reference':'PsychroLib2.5.0 bounded wetbulb algorithm, Meyer and Thevenard2019 JOSS DOI10.21105/joss.01137',
        'reference_code_sha256':sha(OUT/'code/psychrolib_reference.py'),
        'engine_source':'EnergyPlus24.1 Psychrometrics.cc PsyTwbFnTdbWPb uses unbounded General::Iterate and passes intermediate WBT toPsyPsatFnTemp',
        'warnings_suppressed':False,'weather_values_modified':False,'model_or_engine_modified_to_hide_warning':False,
        'strict_point_reference_agreement_pass':minimal_comparison['over_prespecified_0_05C']==0 and all(r['over_prespecified_0_05C']==0 for r in records),
        'post_diagnostic_refinement':'strict point agreement failed near0C; published ice/water latent-heat branches allow distinct roots. Retain original strict failure; verify same-branch agreement, original returned-solution humidity equation residual and dewpoint/drybulb bounds, not a larger temperature tolerance',
        'explanation':'unbounded intermediate trial caused warning; weather-only reproduction tests attribution, branch-specific equation/bounds tests returned physical quantity. This is not manufacturer or household calibration',
        'verification_pass':('(PsyPsatFnTemp)' in err and all(x['same_branch_over_0_05C']==0 and x['maximum_returned_solution_humidity_residual_kg_kg']<1e-6 and x['wetbulb_thermodynamic_bounds_failures']==0 for x in [minimal_comparison]+records))}
    save(OUT/'WEATHER_SOLVER_REVIEW.json',report);print({k:v for k,v in report.items() if k not in ('affected_A_cases','minimal_warning_lines')},flush=True)
if __name__=='__main__':main()
