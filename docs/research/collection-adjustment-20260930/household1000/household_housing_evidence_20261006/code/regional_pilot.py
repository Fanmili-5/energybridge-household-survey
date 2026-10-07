"""Source-parameter-conditioned family housing pilot, keeping population fixed.

Changing opaque wall assemblies rebuilds wall-width/gross/net geometry, then
rechecks sleeping witnesses. Native floorplans are not reconstructed. A paired
old/new code-reference experiment is declared design, not observed home ages.
Free-floating winter/summer day outputs are empty-shell diagnostics only.
"""
import concurrent.futures,copy,json,math,re,sqlite3,subprocess,sys
from pathlib import Path
from sleep_geometry import evaluate,parse,sha
OUT=Path(__file__).resolve().parent.parent;BASE=OUT.parent;V7=BASE/'idf_joint_production_20261005'
sys.path.insert(0,str(V7/'code'))
import reference_world as rw
import compile_reference_idfs as compiler
ENGINE=Path('/Applications/EnergyPlus-24-1-0/energyplus')

PAIRS={'北京':['HighS_Beijing_1995','HighS_Beijing_2018'],
 '上海':['Low_Shanghai_2001','Low_Shanghai_2010'],
 '广东':['Low_Guangzhou_2003','Low_Guangzhou_2012'],'西藏':['Low_Lasa_1995','Low_Lasa_2018']}
def save(path,data):path.write_text(json.dumps(data,ensure_ascii=False,indent=2,allow_nan=False)+'\n')
def main():
    from evidence_guard import ensure_unsealed
    ensure_unsealed(OUT)
    pp=json.loads((V7/'HOUSEHOLDS1000_JOINT_GEOMETRY_CANDIDATE.json').read_text())['profiles']
    oldsleep={r['household_id']:r for r in json.loads((OUT/'SLEEP_GEOMETRY_AUDIT1000.json').read_text())['cases']}
    refs={r['model_key']:r for r in json.loads((OUT/'NATIVE_REFERENCE_REGISTRY.json').read_text())['models']}
    if (OUT/'ADDITIONAL_REGIONAL_REFERENCES.json').exists():refs.update({r['model_key']:r for r in json.loads((OUT/'ADDITIONAL_REGIONAL_REFERENCES.json').read_text())['models']})
    previous_results=json.loads((OUT/'REGIONAL_PILOT_RESULTS.json').read_text()) if (OUT/'REGIONAL_PILOT_RESULTS.json').exists() else {}
    previous={(r['case_id'],r['season']):r for r in previous_results.get('cases',[])}
    chosen=[];selection=[]
    # Freeze selection before pilot results: for each region cover available
    # G values1..3, one shared scenario and one no-witness if it exists.
    for province in PAIRS:
        pool=sorted([p for p in pp if p['province']==province],key=lambda p:p['slot_id']);byid={}
        conditions=[('G'+str(g),lambda p,g=g:p['family']['generation_count']==g) for g in [1,2,3]]
        conditions += [('shared_q_gt1',lambda p:p['housing']['shared_household_count_design']>1),
          ('baseline_sleep_no_witness',lambda p:not oldsleep[p['slot_id']]['baseline0_6m']['capacity_witness_found'])]
        for reason,condition in conditions:
            matches=[p for p in pool if condition(p)]
            if matches:
                p=matches[0];byid[p['slot_id']]=p;selection.append({'household_id':p['slot_id'],'province':province,'criterion':reason})
            else:selection.append({'household_id':None,'province':province,'criterion':reason,'reason':'not_available_in_fixed_population'})
        chosen.extend(byid.values())
    save(OUT/'PILOT_SELECTION_BEFORE_RESULTS.json',{'households':[p['slot_id'] for p in chosen],'criteria':selection,'coverage_design_not_representative_sample':True,
       'paired_code_epochs_do_not_come_from_observed_household_year':True})
    cases=[];failed=[];original_geometry_assemblies=rw.assemblies;original_compiler_assemblies=compiler.assemblies
    try:
        for p in chosen:
            for key in PAIRS[p['province']]:
                reference=refs[key];a=json.loads((OUT/'assemblies'/f'{key}.json').read_text());rw.assemblies=lambda a=a:a;compiler.assemblies=lambda a=a:a
                name=p['slot_id']+'__'+key;folder=OUT/'pilot'/name;folder.mkdir(parents=True,exist_ok=True)
                r=p['housing']['H7_independent_natural_rooms_design'];q=p['housing']['shared_household_count_design'];H6=p['housing']['H6_census_building_area_design_m2']
                try:world=rw.sized_world(r,q,H6,p['slot_id']);rows,meta=compiler.model(world)
                except ValueError as e:
                    failed.append({'household_id':p['slot_id'],'model_key':key,'reason':str(e),'population_N_G_R_H6_q_not_resampled_to_hide_failure':True});continue
                sleep=evaluate(p,world,rows,.6);alt=evaluate(p,world,rows,.8)
                if a.get('opaque_absorptance0_9_0_7_0_7_and_roughness_are_engineering_reference'):
                    meta['source_original_thermal_absorptance_preserved']=False
                    meta['additional_native_opaque_only_limitations']={'glazing_policy':a['glazing_policy'],'opaque_absorptance_roughness':'explicit_reference_not_native_measurement'}
                record={'case_id':name,'household_id':p['slot_id'],'province':p['province'],'N':p['family']['resident_count'],'G':p['family']['generation_count'],
                  'source_profile_path':str(V7/'HOUSEHOLDS1000_JOINT_GEOMETRY_CANDIDATE.json'),'source_profile_file_sha256':sha(V7/'HOUSEHOLDS1000_JOINT_GEOMETRY_CANDIDATE.json'),
                  'H7_design':r,'H6_design_m2':H6,'q_reference':q,'reference_model_key':key,'reference_model_is_actual_household':False,
                  'observed_household_year':None,'catalogue_epoch_is_code_reference_only':True,
                  'geometry_recomputed_from_selected_source_wall_thickness_and_fixed_H6':True,
                  'source_assembly_bundle_path':'assemblies/'+key+'.json','source_assembly_bundle_sha256':sha(OUT/'assemblies'/f'{key}.json'),
                  'geometry_meta':meta,'world':world,'sleep0_6m':sleep,'sleep0_8m':alt,
                  'reference_weather':reference['coordinate_confirmed_WMO_station_candidates'][0],
                  'reference_weather_is_actual_household_city_observation':False,'native_source_floorplan_preserved':False,
                  'door_and_window_positions_WWR_and_floor_RC_are_declared_reference_designs':True,
                  'People_electric_appliances_infiltration_HVAC_and_full_services_completed':False,'actor_ready':False}
                save(folder/'CASE.json',record)
                for month,day,season in [(1,1,'winter'),(7,1,'summer')]:
                    rr=copy.deepcopy(rows);period=next(r for r in rr if r[0]=='RunPeriod');period[2:8]=[str(month),str(day),'2007',str(month),str(day),'2007'];period[8]='Monday' if month==1 else 'Sunday'
                    path=folder/(season+'.idf');path.write_text('! Regional code-parameter reference empty shell; not an observed household.\n'+compiler.dump(rr))
                    cases.append({'case_id':name,'household_id':p['slot_id'],'model_key':key,'season':season,'case_path':str((folder/'CASE.json').relative_to(OUT)),
                      'IDF_path':str(path.relative_to(OUT)),'IDF_sha256':sha(path),'weather':record['reference_weather'],
                      'zone_count':len(world['rooms']),'target_rooms':[r['room_id'] for r in world['rooms'] if r['using_household_ids']==[p['slot_id']] and r['census_room_class']=='bedroom'],
                      'target_room_usable_areas':{r['room_id']:r['usable_area_m2'] for r in world['rooms'] if r['using_household_ids']==[p['slot_id']] and r['census_room_class']=='bedroom'},
                      'sleep0_6m_witness':sleep['capacity_witness_found'],'sleep0_8m_witness':alt['capacity_witness_found']})
    finally:rw.assemblies=original_geometry_assemblies;compiler.assemblies=original_compiler_assemblies
    save(OUT/'PILOT_REFERENCE_BINDINGS.json',{'bindings':cases,'family_profiles':len(chosen),'source_parameter_reference_worlds':len(cases)//2,
      'compilation_failures_preserved':failed,'season_runs_planned':len(cases),'complete_household_IDFs':0})
    def run(case):
        path=OUT/case['IDF_path'];folder=path.parent/('run_'+case['season']);folder.mkdir(exist_ok=True)
        old=previous.get((case['case_id'],case['season']))
        if old and old['IDF_sha256']==case['IDF_sha256'] and previous_results['engine_sha256']==sha(ENGINE) and old['weather']['sha256']==case['weather']['sha256'] and sha(Path(case['weather']['path']))==case['weather']['sha256'] and sha(folder/'eplusout.sql')==old['SQL_sha256']:
            return {**old,**case,'runtime_reused_after_IDF_weather_engine_and_SQL_hash_checks':True}
        result=subprocess.run([str(ENGINE),'-w',case['weather']['path'],'-d',str(folder),str(path)],capture_output=True,text=True,timeout=180)
        (folder/'console.txt').write_text(result.stdout+'\n'+result.stderr);err=(folder/'eplusout.err').read_text() if (folder/'eplusout.err').exists() else ''
        warnings=re.findall(r'\*\*\s*Warning\s*\*\*([^\n]*)',err);severe=re.findall(r'\*\*\s*(?:Severe|Fatal)\s*\*\*([^\n]*)',err)
        if result.returncode or severe:raise RuntimeError(str(folder/'eplusout.err'))
        db=sqlite3.connect(folder/'eplusout.sql')
        # This engine writes NULL for the ordinary reported-hour warmup field.
        # Require one weather environment and24 sequential hourly outputs as
        # independent guards; NULL must not erase all valid reported hours.
        assert db.execute('SELECT COUNT(*) FROM EnvironmentPeriods WHERE EnvironmentType=3').fetchone()[0]==1
        data=db.execute('SELECT d.KeyValue,r.Value,t.Hour FROM ReportData r JOIN ReportDataDictionary d USING(ReportDataDictionaryIndex) JOIN Time t USING(TimeIndex) WHERE d.Name=? AND COALESCE(t.WarmupFlag,0)=0 ORDER BY d.KeyValue,t.TimeIndex',('Zone Mean Air Temperature',)).fetchall();db.close()
        temperature={n:[v for room,v,h in data if room.upper()==n.upper()] for n in case['target_rooms']}
        assert all(len(v)==24 and all(math.isfinite(x) for x in v) for v in temperature.values())
        # Weight by actual private usable floor area; no net/gross shortcut.
        total=sum(case['target_room_usable_areas'].values());hourly=[sum(temperature[n][i]*case['target_room_usable_areas'][n] for n in temperature)/total for i in range(24)]
        return {**case,'returncode':result.returncode,'severe_or_fatal':len(severe),'warnings':warnings,'run_path':str(folder.relative_to(OUT)),
          'SQL_sha256':sha(folder/'eplusout.sql'),'target_private_area_weighted_air_temperature_C_24h':hourly,
          'mean_target_private_air_temperature_C':sum(hourly)/24,'min_C':min(hourly),'max_C':max(hourly),
          'hourly_zone_temperature_outputs':len(data),'source_parameter_weather_runtime_witness_only':True,'energy_or_household_occupancy_or_comfort_validated':False}
    with concurrent.futures.ThreadPoolExecutor(4) as pool:results=list(pool.map(run,cases))
    pairs=[]
    for p in chosen:
        for season in ['winter','summer']:
            ss=[r for r in results if r['household_id']==p['slot_id'] and r['season']==season]
            if len(ss)!=2:continue
            ss.sort(key=lambda r:refs[r['model_key']]['catalogue_reference_epoch']);old,new=ss
            differences=[b-a for a,b in zip(old['target_private_area_weighted_air_temperature_C_24h'],new['target_private_area_weighted_air_temperature_C_24h'])]
            pairs.append({'household_id':p['slot_id'],'province':p['province'],'season':season,'old_reference':old['model_key'],'new_reference':new['model_key'],
               'same_station_and_fixed_H6_N_G_R_q':True,'mean_new_minus_old_private_temperature_C':sum(differences)/24,
               'max_abs_hourly_temperature_difference_C':max(map(abs,differences)),
               'wall_thickness_changes_also_change_usable_geometry_at_fixed_H6':True,
               'not_isolated_material_effect_or_empirical_stock_validation':True})
    report={'cases':results,'paired_reference_sensitivity':pairs,'family_profiles':len(chosen),'source_parameter_reference_worlds':len(cases)//2,
      'winter_summer_empty_shell_runs':len(results),'severe_or_fatal':sum(r['severe_or_fatal'] for r in results),
      'warning_entries':sum(len(r['warnings']) for r in results),'baseline_sleep_witness_worlds':sum(r['sleep0_6m_witness'] for r in results if r['season']=='winter'),
      'alternative_sleep_witness_worlds':sum(r['sleep0_8m_witness'] for r in results if r['season']=='winter'),
      'fixed_population_anchor_no_resampling':True,'source_native_geometries_or_actual_stock_years_matched':False,
      'source_parameter_weather_reference_runs_not_complete_household_energy_or_calibration':True,
      'complete_household_IDFs':0,'actor_ready_packages':0,'engine_sha256':sha(ENGINE)}
    save(OUT/'REGIONAL_PILOT_RESULTS.json',report);print(json.dumps({k:v for k,v in report.items() if k not in ['cases','paired_reference_sensitivity']},ensure_ascii=False,indent=2))
if __name__=='__main__':main()
