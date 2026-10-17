#!/usr/bin/env python3
"""Read frozen annual witnesses; write new warning review only, no engine run."""
import argparse,collections,csv,hashlib,json,math,re
from pathlib import Path
from reproduce_wetbulb import solve
HERE=Path(__file__).resolve().parents[1]

def sha(path):return hashlib.sha256(path.read_bytes()).hexdigest()
def load(path):return json.loads(path.read_text())
def category(message):
    if 'PsyPsatFnTemp' in message:return 'wetbulb_iteration_psat_out_of_range'
    if 'WetBulb not converged' in message:return 'wetbulb_iteration_not_converged'
    if 'Standard Time Meridian' in message:return 'civil_timezone_vs_geographic_meridian'
    return 'unclassified_warning'

def blocks(text):
    lines=text.splitlines();result=[]
    for i,line in enumerate(lines):
        if not re.search(r'\*\*\s*Warning\s*\*\*',line):continue
        raw=[line]
        for following in lines[i+1:]:
            if '**   ~~~   **' in following:raw.append(following)
            else:break
        content='\n'.join(raw);recurring=line.lstrip().startswith('*************')
        occurrences=re.search(r'This error occurred (\d+) total times',content)
        result.append({'category':category(line),'line_1based':i+1,'recurring_summary':recurring,
            'reported_occurrence_count':int(occurrences.group(1)) if occurrences else None,'raw_block':content,
            'reported_simulation_interval':(re.search(r'Simulation time=([^\n]+)',content).group(1) if 'Simulation time=' in content else None)})
    return result

def weather_stress(epw):
    rows=list(csv.reader(epw.open()));header=rows[0];data=rows[8:];events=[]
    invalid=[]
    for i,row in enumerate(data):
        if len(row)!=35 or not(-70<=float(row[6])<=70 and 0<=float(row[8])<=100 and 31000<=float(row[9])<=120000):invalid.append(i+9)
        prev=data[i-1]
        for fraction in [.25,.5,.75,1.]:
            tdb,rhpct,pressure=[float(prev[k])*(1-fraction)+float(row[k])*fraction for k in [6,8,9]]
            solution=solve(tdb,rhpct/100,pressure)
            if not solution['out_of_range_trials'] and solution['converged']:continue
            events.append({'EPW_current_record':{'line_1based':i+9,'year':int(row[0]),'month':int(row[1]),'day':int(row[2]),
                'hour':int(row[3]),'minute':int(row[4]),'raw_csv_fields':row},
                'EPW_previous_record':{'line_1based':i+8 if i else len(rows),'raw_csv_fields':prev},
                'current_hour_interpolation_weight':fraction,'original_interpolated_tdb_RHpct_P':[tdb,rhpct,pressure],
                'diagnostic_solution':solution,
                'interpretation':'isolated official-equation translation sufficient to trigger warning condition; not full compiled-engine or empirical temperature validation'})
    return {'epw_path':str(epw),'epw_sha256':sha(epw),'LOCATION_fields':header,'quarter_hour_inputs_scanned':len(data)*4,
        'simple_required_input_range_invalid_lines':invalid,'range_check_is_not_meteorological_quality_validation':True,
        'out_of_range_trial_count':sum(len(x['diagnostic_solution']['out_of_range_trials']) for x in events),
        'nonconverged_calls':sum(not x['diagnostic_solution']['converged'] for x in events),'warning_condition_events':events}

def main(root,report):
    annual=root/'annual_witnesses_v1';summary=load(annual/'SUMMARY.json');case_results=[];stats=collections.Counter();weather_cases=collections.defaultdict(list)
    stress_paths={};temps=[];binding_errors=[]
    for runtime in sorted(summary['runtime'],key=lambda x:x['case_id']):
        folder=annual/'runtime'/runtime['case_id'];error=folder/'eplusout.err';text=error.read_text();parsed=blocks(text)
        epw=Path(runtime['command'][2]);idf=Path(runtime['command'][-1]);case=idf.parent;input_case=load(case/'INPUT.json');binding=load(case/'ASSEMBLY_BINDING.json')
        actual_epw=sha(epw);actual_idf=sha(idf)
        if actual_epw!=runtime['weather_sha256'] or actual_idf!=runtime['input_idf_sha256']:binding_errors.append(runtime['case_id'])
        per_category=[]
        for kind in sorted({x['category'] for x in parsed}):
            group=[x for x in parsed if x['category']==kind];primary=[x for x in group if not x['recurring_summary']];recurring=[x for x in group if x['recurring_summary']]
            count=sum(x['reported_occurrence_count'] or 0 for x in recurring) if recurring else len(primary)
            per_category.append({'category':kind,'primary_warning_headers':len(primary),'recurring_summary_headers':len(recurring),
                'deduplicated_reported_occurrences':count,'count_definition':'recurring total includes primary and hidden subsequent calls; timezone has no recurring summary, so uses logged primary count'})
            stats[kind+':cases']+=1;stats[kind+':primary_headers']+=len(primary);stats[kind+':recurring_headers']+=len(recurring);stats[kind+':reported_occurrences']+=count
            if kind.startswith('wetbulb_'):stress_paths[str(epw)]=epw
        completion=re.search(r'Completed Successfully--\s+(\d+) Warning;\s+(\d+) Severe',text)
        endcount=int(completion.group(1)) if completion else None
        if parsed:stats['warning_cases']+=1;weather_cases[str(epw)].append(runtime['case_id'])
        else:stats['no_logged_warning_cases']+=1
        stats['raw_warning_headers_including_summary_duplicates']+=len(parsed);stats['completed_summary_warning_occurrences']+=endcount or 0
        lo=min(z['minimum_C'] for z in runtime['zone_temperatures'].values());hi=max(z['maximum_C'] for z in runtime['zone_temperatures'].values());temps.extend([lo,hi])
        numeric=any(x['category'].startswith('wetbulb_') for x in parsed);timezone=any(x['category']=='civil_timezone_vs_geographic_meridian' for x in parsed)
        label='annual_complete_with_psychrometric_warnings' if numeric else 'annual_complete_with_civil_timezone_heuristic_warning' if timezone else 'annual_complete_no_logged_warning'
        case_results.append({'case_id':runtime['case_id'],'review_label':label,'frozen_runtime_status':runtime['status'],
            'error_path':str(error),'error_sha256':sha(error),'runtime_check_path':str(folder/'RUNTIME_CHECK.json'),'runtime_check_sha256':sha(folder/'RUNTIME_CHECK.json'),
            'idf_path':str(idf),'idf_sha256':actual_idf,'epw_path':str(epw),'epw_sha256':actual_epw,
            'source_group_id':load(case/'STATUS.json').get('prototype_source_group_id'),'source_idf_sha256':binding['source_idf_sha256'],
            'context_city':input_case['site']['city'],'context_province':input_case['site']['province'],
            'warning_blocks':parsed,'categories':per_category,'engine_completed_summary_warning_occurrences':endcount,
            'zone_mean_temperature_range_C':[lo,hi],'numerical_clean_certified':False,
            'supported_diagnosis':'weather-input-driven 24.1 wet-bulb iteration mechanism' if numeric else 'longitude heuristic/civil UTC+8 discrepancy' if timezone else 'no warning in frozen err',
            'geometry_cause_found':False,'source_EPW_invalid_input_at_warning_found':False,
            'use_boundary':'retain complete engineering execution evidence; numeric warning cases require targeted verification before wetbulb/moisture/heat-risk/calibrated physical use; never measured family energy or general calibration'})
    weather_results=[weather_stress(epw) for epw in stress_paths.values()]
    sources={name:{'official_url':'https://raw.githubusercontent.com/NREL/EnergyPlus/v24.1.0/src/EnergyPlus/'+name,'downloaded_byte_sha256':sha(Path('/private/tmp/eplus24_warning_source')/name)}
        for name in ['Psychrometrics.cc','Psychrometrics.hh','PsychCacheData.hh','General.cc','WeatherManager.cc','HeatBalanceSurfaceManager.cc']}
    timezone_paths={x['epw_path'] for x in case_results if any(c['category']=='civil_timezone_vs_geographic_meridian' for c in x['categories'])}
    timezone_reviews=[]
    for path in sorted(timezone_paths):
        loc=next(csv.reader(Path(path).open()));longitude=float(loc[7]);civil=float(loc[8]);geographic=next(i for i in range(-12,13) if i*15-7.5<longitude<=i*15+7.5)
        timezone_reviews.append({'epw_path':path,'LOCATION_fields':loc,'longitude_deg':longitude,'declared_civil_UTC_offset':civil,
            'official_GetSTM_geographic_meridian_result':geographic,'official_warning_difference_hours':abs(civil-geographic),
            'solar_hour_angle_meridian_longitude_correction_deg':civil*15-longitude,
            'diagnosis':'civil timezone differs from nearest geographic 15degree zone; UTC+8 is independently supported for Urumqi; not proof of metadata defect or wrong solar results',
            'forbidden_metadata_shortcut':'do not change UTC+8 to UTC+6 just to suppress warning',
            'civil_time_primary_source':'https://www.hko.gov.hk/en/gts/time/time_text.htm',
            'remaining_unknown':'independent solar/radiation timestamp alignment and downstream quantitative impact not evaluated'})
    result={'schema':'eb.annual_warning_review.v2','experiment_id':summary['experiment_id']+'__WARNING_REVIEW_20261003',
        'annual_summary_path':str(annual/'SUMMARY.json'),'annual_summary_sha256':sha(annual/'SUMMARY.json'),'engine_version':'EnergyPlus24.1.0-9d7789a3ac',
        'all_117_annual_runs_completed':len(case_results)==117 and all(x['frozen_runtime_status']=='pass' for x in case_results),
        'review_case_count':len(case_results),'warning_counts':dict(stats),'temperature_range_C':[min(temps),max(temps)],'binding_errors':binding_errors,
        'not_numerical_clean':True,'new_annual_runs':0,'official_source_tag':'v24.1.0','official_sources':sources,
        'formula_translation_limitations':['uses official finite/cache-quantized equations with the default non-IF97 branch; no compiled-engine build flag certification',
            'isolated calls do not reproduce engine cache history, all side effects, whole solver or physical truth',
            'Python/C++ floating evaluation yields roughly4e-4C difference in first Xining huge trial; explicit measured log remains authoritative',
            'EPW line/hour/30minute field is preserved; displayed warning interval start matches reconstructed interpolation input, no timestamp metadata repaired',
            'no upstream issue specifically confirming these exact inputs or a fixed engine version was identified'],
        'weather_stress_diagnostics':weather_results,'timezone_reviews':timezone_reviews,'weather_warning_case_groups':dict(weather_cases),'cases':case_results,
        'review_script_sha256':sha(Path(__file__)),'formula_script_sha256':sha(Path(__file__).parent/'reproduce_wetbulb.py'),
        'frozen_core_IDFs_EPW_simulation_outputs_modified':False,'source_microdata_read':False,
        'claim_boundary':'completion/full finite hourly output with disclosed warnings; no numerical-clean, solar/time-axis calibration, full-household-load or empirical physical calibration claim'}
    if report.exists():raise ValueError('review output already exists; keep evidence immutable')
    report.write_text(json.dumps(result,ensure_ascii=False,indent=2,allow_nan=False)+'\n')
    print(json.dumps({'case_count':len(case_results),'warning_counts':dict(stats),'stress':[(Path(x['epw_path']).parent.name,x['out_of_range_trial_count'],x['nonconverged_calls']) for x in weather_results],'binding_errors':binding_errors},ensure_ascii=False))

if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--root',type=Path,default=HERE);parser.add_argument('--report',type=Path,required=True)
    args=parser.parse_args();main(args.root.resolve(),args.report.resolve())
