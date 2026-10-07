"""Prespecified continuous typical-weather history; retain convergence failures."""
import concurrent.futures,collections,subprocess,sqlite3,re
from common import *
ENGINE=Path('/Applications/EnergyPlus-24-1-0/energyplus')
RUN_CACHE={}
def run(task):
 r,initial,years=task;hid=r['household_id'];folder=OUT/'ground_history'/(hid+'_initial'+str(initial)+('' if years==5 else '_Y'+str(years)));folder.mkdir(parents=True,exist_ok=True);rows=parse(V10/r['IDF_path'])
 rows=[z for z in rows if z[0]!='RunPeriod'];rows.append(obj('RunPeriod',{'name':'continuous_typical_history2018_'+str(2017+years),'begin_month':1,'begin_day_of_month':1,'begin_year':2018,'end_month':12,'end_day_of_month':31,'end_year':2017+years,
  'day_of_week_for_start_day':'Monday','use_weather_file_holidays_and_special_days':'No','use_weather_file_daylight_saving_period':'No','apply_weekend_holiday_rule':'No','use_weather_file_rain_indicators':'Yes','use_weather_file_snow_indicators':'Yes','treat_weather_as_actual':'No'}))
 fields=SCHEMA['properties']['Foundation:Kiva']['legacy_idd']['fields'];index=fields.index('initial_indoor_air_temperature')+1
 for z in rows:
  if z[0]=='Foundation:Kiva':z[index]=initial
 path=folder/'input.idf';path.write_text('! Repeated typical-weather continuous5year ground-history diagnostic;not actual calendar weather.\n'+dump(rows));runfolder=folder/'run';runfolder.mkdir(exist_ok=True)
 print({'started':hid,'initial_indoor_C':initial,'continuous_years':years},flush=True)
 old=RUN_CACHE.get((hid,initial,years));sqlpath=runfolder/'eplusout.sql'
 if old and old['IDF_sha256']==sha(path) and old['weather_sha256']==sha(r['weather']['path']) and old['engine_sha256']==sha(ENGINE) and sqlpath.exists() and old['SQL_sha256']==sha(sqlpath):resultcode=0
 else:
  result=subprocess.run([str(ENGINE),'-w',r['weather']['path'],'-d',str(runfolder),str(path)],capture_output=True,text=True,timeout=1800);(runfolder/'console.txt').write_text(result.stdout+'\n'+result.stderr);resultcode=result.returncode
 err=(runfolder/'eplusout.err').read_text();sf=re.findall(r'\*\*\s*(?:Severe|Fatal)\s*\*\*([^\n]*)',err);assert not sf and resultcode==0,err
 db=sqlite3.connect(runfolder/'eplusout.sql');data=db.execute('SELECT d.KeyValue,t.Year,t.Month,t.Day,t.Hour,r.Value FROM ReportData r JOIN ReportDataDictionary d USING(ReportDataDictionaryIndex) JOIN Time t USING(TimeIndex) WHERE COALESCE(t.WarmupFlag,0)=0 AND d.Name="Zone Mean Air Temperature" ORDER BY t.TimeIndex,d.KeyValue').fetchall();db.close()
 assert data;series=collections.defaultdict(list)
 for key,year,month,day,h,value in data:series[year,key].append([month,day,h,value])
 assert len({year for year,key in series})==years
 save(folder/'hourly_temperature.json',{'series':[{'year':year,'zone':key,'hourly':v} for (year,key),v in series.items()]})
 meta={'household_id':hid,'initial_indoor_reference_C':initial,'continuous_years':years,'returncode':0,'severe_fatal':0,'warnings':re.findall(r'\*\*\s*Warning\s*\*\*([^\n]*)',err),
  'IDF_path':str(path.relative_to(OUT)),'IDF_sha256':sha(path),'SQL_path':str((runfolder/'eplusout.sql').relative_to(OUT)),'SQL_sha256':sha(runfolder/'eplusout.sql'),
  'hourly_path':str((folder/'hourly_temperature.json').relative_to(OUT)),'hourly_sha256':sha(folder/'hourly_temperature.json'),'weather_path':r['weather']['path'],'weather_sha256':r['weather']['sha256'],'engine_sha256':sha(ENGINE)}
 print({'finished':hid,'initial_indoor_C':initial,'warnings':len(meta['warnings'])},flush=True);return meta
def main():
 guard();records=read(V10/'JOINT_WORLD_BINDINGS.json')['records'];selection=read(V10/'GROUND_EXPERIMENT_SELECTION.json')['household_IDs']
 if '--all-one-storey' in sys.argv:selection=[r['household_id'] for r in records if r['one_storey_roof_ground']]
 extended='--extend-failed' in sys.argv;years=10 if extended else 5
 if extended:selection=[p['household_id'] for p in read(OUT/'GROUND_HISTORY_RESULTS.json')['pairs'] if not p['lastyear_perturbation_tolerance_met']]
 selected=[r for r in records if r['household_id'] in selection]
 if not extended:assert len(selected)==(61 if '--all-one-storey' in sys.argv else 2)
 if (OUT/'GROUND_HISTORY_RESULTS.json').exists():
  prior=read(OUT/'GROUND_HISTORY_RESULTS.json');RUN_CACHE.update({(r['household_id'],r['initial_indoor_reference_C'],r.get('continuous_years',5)):r for r in prior['runs']})
 save(OUT/('GROUND_EXTENSION_SELECTION.json' if extended else 'GROUND_ALL61_SELECTION.json'),{'selected_household_IDs':selection,'selection':'every fixed-threshold failed case;do not drop failures' if extended else 'all fixed61one-storey profiles,no selection on output','comparison':[10,30],'continuous_years':years,'lastyear_maxdiff_threshold_C':.1,'adaptive_iteration_for_numerical_convergence_not_statistical_significance':extended})
 tasks=[(r,initial,years) for r in selected for initial in [10,30]]
 with concurrent.futures.ThreadPoolExecutor(4) as pool:results=list(pool.map(run,tasks))
 pairs=[]
 for hid in selection:
  m=[r for r in results if r['household_id']==hid];a,b=[read(OUT/r['hourly_path'])['series'] for r in m];aa={(r['year'],r['zone']):r['hourly'] for r in a};bb={(r['year'],r['zone']):r['hourly'] for r in b};assert set(aa)==set(bb);years=sorted({y for y,k in aa});report=[]
  for year in years:
   dif=[]
   for y,k in aa:
    if y!=year:continue
    assert len(aa[y,k])==len(bb[y,k])
    for v1,v2 in zip(aa[y,k],bb[y,k]):assert v1[:3]==v2[:3];dif.append(abs(v1[3]-v2[3]))
   report.append({'year_label_in_repeated_weather_simulation':year,'max_abs_zone_hourly_initial10_vs30_difference_C':max(dif),'hourly_zone_values_compared':len(dif)})
  passed=report[-1]['max_abs_zone_hourly_initial10_vs30_difference_C']<=.1
  pairs.append({'household_id':hid,'years':report,'lastyear_tolerance_design_C':.1,'lastyear_perturbation_tolerance_met':passed})
 save(OUT/('GROUND_EXTENDED_RESULTS.json' if extended else 'GROUND_HISTORY_RESULTS.json'),{'runs':results,'pairs':pairs,'passed_tested_cases':sum(r['lastyear_perturbation_tolerance_met'] for r in pairs),
  'numerical_initialization_diagnostic_not_measured_soil_or_wholehome_calibration':True,'profile_geometry_selection_covered':len(selected),'other_occupancy_soil_or_exposure_cases_not_admitted':True,'threshold_frozen_before_first_pair_results':True,'all61_expansion_after_first2_development_checks':len(selected)==61})
 print({'covered':len(selected),'passed':sum(r['lastyear_perturbation_tolerance_met'] for r in pairs),'worst_lastyear_difference_C':max(r['years'][-1]['max_abs_zone_hourly_initial10_vs30_difference_C'] for r in pairs)})
if __name__=='__main__':main()
