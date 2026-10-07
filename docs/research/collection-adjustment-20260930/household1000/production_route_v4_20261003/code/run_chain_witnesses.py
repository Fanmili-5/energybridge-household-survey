#!/usr/bin/env python3
"""Small isolated pipeline witnesses, not population/actor profile generation."""
import argparse
import copy
import json
import re
import sqlite3
import subprocess
import shutil
import datetime
from pathlib import Path
from typed_chain import sha,digest,rows,check_bundle,compile_gains
from source_semantics import normalize

HERE=Path(__file__).resolve().parent
ENGINE=Path('/Applications/EnergyPlus-24-1-0/energyplus')
def save(p,x):p.write_text(json.dumps(x,ensure_ascii=False,indent=2,allow_nan=False)+'\n')
def bundle_for(base):
    inp=json.loads((base/'INPUT.json').read_text());st=json.loads((base/'STATUS.json').read_text())
    phases=[{'service':'wash','start_minute':600,'end_minute':630,'input_power_W':1000,
        'power_quantity':'electrical_input_W','power_evidence':'explicit_test_design',
        'heat_fractions':{'latent':0.0,'radiant':0.0,'lost':1.0}},
        {'service':'dry','start_minute':660,'end_minute':720,'input_power_W':2000,
        'power_quantity':'electrical_input_W','power_evidence':'explicit_test_design',
        'heat_fractions':{'latent':0.0,'radiant':0.0,'lost':1.0}}]
    asset={'asset_id':'combo1','hardware_id':'one_physical_combo','class':'washer_dryer_combo','services':['wash','dry'],
        'unit_count':1,'assignment_status':'explicit_engineering_fixture','evidence_id':'typed_electrical_binding_witness_v1',
        'zone_name':'bathroom','zone_assignment_status':'engineering_gain_zone',
        'meter_scope':'declared_household_experiment_meter','installed':True,'operable':True,'control_available':True,
        'role_operator_member_id':None,'role_permission_to_shift':None,'operation_phases':phases,
        'capacity_or_performance_model':None,'power_values_are_household_measurements':False}
    return {'schema':'eb.household_idf_asset_bundle.v1','population_slot_id':st['generation_slot_id'],
        'profile_file_sha256':st['generation_profile_file_sha256'],
        'binding':{'family_sha256':digest(inp['family']),'housing_sha256':digest(inp['housing']),
            'base_input_sha256':sha(base/'INPUT.json'),'base_idf_path':st['idf_path'],'base_idf_sha256':st['idf_sha256']},
        'assets':[asset],'scope':'electric component and single-hardware multi-service witness only; fixtures are not generated ownership',
        'human_answers':None,'collection_release':False,'training_release':False}

def runtime(folder,body,weather,report):
    folder.mkdir(parents=True)
    rs=rows(body)
    steps_per_hour=int(next(r[1] for r in rs if r[0].lower()=='timestep'))
    for r in rs:
        if r[0].lower()=='runperiod':
            r[2:8]=['7','1','2023','7','1','2023']
            r[8]=datetime.date(2023,7,1).strftime('%A')
    idf=folder/'witness.idf';idf.write_text('\n'.join(',\n  '.join(r)+';' for r in rs)+'\n')
    result=subprocess.run([str(ENGINE),'-w',str(weather),'-d',str(folder/'run'),str(idf)],
        stdout=subprocess.PIPE,stderr=subprocess.STDOUT,text=True,timeout=180)
    (folder/'console.txt').write_text(result.stdout)
    err=(folder/'run/eplusout.err').read_text() if (folder/'run/eplusout.err').exists() else ''
    measured={};facility=[];intervals=[];fail=[]
    if result.returncode!=0:fail.append('engine_exit_'+str(result.returncode))
    dbpath=folder/'run/eplusout.sql'
    if dbpath.exists():
        db=sqlite3.connect(dbpath)
        data=db.execute('''SELECT d.Name,d.KeyValue,d.Units,r.Value,t.Month,t.Day,t.Hour,t.Minute,t.Interval
            FROM ReportData r JOIN ReportDataDictionary d USING(ReportDataDictionaryIndex)
            JOIN Time t USING(TimeIndex) JOIN EnvironmentPeriods e USING(EnvironmentPeriodIndex)
            WHERE t.WarmupFlag=0 AND e.EnvironmentType=3
            AND d.ReportingFrequency='Zone Timestep' ''').fetchall();db.close()
        for name,key,unit,value,month,day,hour,minute,interval in data:
            if name=='Electric Equipment Electricity Energy':
                if unit!='J':fail.append('equipment_unit_'+unit)
                measured[key]=measured.get(key,0)+value/3.6e6
                if value>1e-10:intervals.append({'key':key,'month':month,'day':day,'hour':hour,'minute':minute,'interval_minutes':interval})
            if name=='Electricity:Facility':
                if unit!='J':fail.append('facility_unit_'+unit)
                facility.append(value/3.6e6)
    else:fail.append('SQL_missing')
    for p in report['expected_phase_kWh']:
        value=measured.get(p['idf_equipment_name'].upper())
        if value is None or abs(value-p['expected_kWh'])>1e-7:fail.append('phase_energy_not_closed:'+p['idf_equipment_name'])
    if len(facility)!=24*steps_per_hour:fail.append('one_day_meter_interval_count_mismatch_declared_Timestep')
    if abs(sum(facility)-report['expected_total_kWh'])>1e-7:fail.append('facility_meter_not_equal_declared_component_energy')
    if re.search(r'\*\*\s*(Severe|Fatal)\s*\*\*',err,re.I):fail.append('Severe_or_Fatal')
    out={'pass':not fail,'errors':fail,'engine_exit':result.returncode,'idf_sha256':sha(idf),
        'EPW_sha256':sha(weather),'measured_phase_kWh':measured,'facility_kWh':sum(facility),
        'expected_total_kWh':report['expected_total_kWh'],'meter_intervals':len(facility),
        'declared_steps_per_hour':steps_per_hour,'expected_meter_intervals':24*steps_per_hour,
        'warning_markers':len(re.findall(r'\*\*\s*Warning\s*\*\*',err,re.I)),
        'active_intervals':intervals,'scope':'one-day engineered electrical component accounting; no service/physical/human calibration'}
    save(folder/'RUNTIME_READBACK.json',out)
    return out

def main():
    ap=argparse.ArgumentParser();ap.add_argument('--base-case',type=Path,required=True)
    ap.add_argument('--output',type=Path,required=True);args=ap.parse_args()
    if args.output.exists():raise ValueError('new_witness_directory_required')
    out=args.output.resolve();out.mkdir(parents=True);base=args.base_case.resolve()
    (out/'code').mkdir()
    for n in ['typed_chain.py','source_semantics.py','run_chain_witnesses.py']:
        shutil.copy2(HERE/n,out/'code'/n)
    prototype=bundle_for(base);controls=[]
    def probe(name,mutation,token):
        b=copy.deepcopy(prototype);mutation(b);r=check_bundle(b,base)
        controls.append({'name':name,'detected':any(token in e for e in r['errors']),'errors':r['errors']})
    probe('wrong_family_version',lambda b:b['binding'].update(family_sha256='0'*64),'family_sha256')
    probe('wrong_housing_version',lambda b:b['binding'].update(housing_sha256='0'*64),'housing_sha256')
    probe('wrong_profile_version',lambda b:b.update(profile_file_sha256='0'*64),'profile_version')
    probe('zone_from_other_IDF',lambda b:b['assets'][0].update(zone_name='living_unit1'),'zone_not_in_exact_IDF')
    def duplicate(b):
        a=copy.deepcopy(b['assets'][0]);a['asset_id']='combo2';b['assets'].append(a)
    probe('combo_counted_twice',duplicate,'duplicate_physical_hardware')
    probe('combo_services_overlap',lambda b:b['assets'][0]['operation_phases'][1].update(start_minute=620),'simultaneous_services')
    probe('capacity_as_input_power',lambda b:b['assets'][0]['operation_phases'][0].update(power_quantity='cooling_capacity_W'),'capacity_cannot_be_electrical')
    probe('unknown_control_promoted',lambda b:b['assets'][0].update(control_available=None),'control_available_unresolved')
    probe('central_AC_as_plugload',lambda b:b['assets'][0].update(**{'class':'cooling_building_central'}),'needs_HVAC_or_water')
    probe('water_heater_as_heat_only_plug',lambda b:b['assets'][0].update(**{'class':'water_heater_electric'}),'needs_HVAC_or_water')
    probe('unknown_meter',lambda b:b['assets'][0].update(meter_scope='unknown'),'meter_boundary_unresolved')
    probe('heat_fractions_add_energy',lambda b:b['assets'][0]['operation_phases'][0].update(heat_fractions={'latent':.5,'radiant':.5,'lost':.5}),'heat_fraction_energy_balance')
    probe('engineering_check_opens_collection',lambda b:b.update(collection_release=True),'cannot_open_collection')
    ordinary=check_bundle(prototype,base)
    controls.append({'name':'fixture_does_not_certify_function_or_actor_control','detected':ordinary['component_binding_pass'] and not ordinary['actor_role_ready'] and bool(ordinary['actor_issues'])})
    source_controls=[]
    def fixture():return {'valid':1,'b1':1,'a1':2,'a2_1_a':1,'a2_1_b':1,'a2_1_c':1970,
        'a2_2_a':8,'a2_2_b':2,'a2_2_c':1940,'b7':2,'b4':2,'b13':3,'b14':2,
        'c3_1c':4,'c4_1b':1,'d6_1a':1,'d6_1b':4}
    r=normalize(fixture())
    source_controls.extend([{'name':'gaps_in_generation_levels_count_occupied_generations','pass':r['G_proxy']==2},
        {'name':'other_owned_not_rent','pass':r['ownership_scope']=='other_owned_not_equivalent_to_rented'},
        {'name':'two_levels_not_inferred_from_total_building','pass':r['interior_levels_category']==2},
        {'name':'central_AC_capacity_skipped','pass':next(x for x in r['service_reports'] if x['family']=='cooling_service')['fields']['capacity_like_category'] is None},
        {'name':'combo_service_keeps_hardware_unlinked','pass':all(x['hardware_identity']=='unresolved_service_report' for x in r['service_reports'])}])
    missing=normalize({'valid':1,'b1':1,'a1':1})
    source_controls.append({'name':'empty_slots_not_absence_or_valid_household','pass':not missing['service_reports'] and missing['inventory_absence_status'].startswith('unknown') and not missing['member_reference_admitted']})
    invalid=fixture();invalid['c3_1c']=24;r=normalize(invalid)
    source_controls.append({'name':'undocumented_type24_not_admitted','pass':any(e['field']=='c3_1c' for e in r['invalid_type_codes']) and not any(x['family']=='washer' for x in r['service_reports'])})
    results=[]
    status=json.loads((base/'STATUS.json').read_text());weather=Path(status['weather_epw_path'])
    if sha(weather)!=status['weather_epw_sha256']:raise ValueError('weather_bytes_changed')
    for name,kind in [('combo_off','off'),('combo_two_services_lost','on'),('combo_two_services_zone_gain','gain')]:
        b=copy.deepcopy(prototype)
        if kind=='off':
            for p in b['assets'][0]['operation_phases']:p['input_power_W']=0
        if kind=='gain':
            for p in b['assets'][0]['operation_phases']:p['heat_fractions']={'latent':0.0,'radiant':.2,'lost':.1}
        body,report=compile_gains(b,base)
        if body is None:raise ValueError(report)
        folder=out/name;folder.mkdir();save(folder/'ASSET_BUNDLE.json',b);save(folder/'BINDING_CHECK.json',report)
        actual=runtime(folder/'physical',body,weather,report)
        results.append({'case':name,'binding':report,'runtime':actual})
    passed=all(c['detected'] for c in controls) and all(c['pass'] for c in source_controls) and all(r['runtime']['pass'] for r in results)
    report={'schema':'eb.household_asset_idf_chain_witnesses.v1','pass':passed,'base_case':str(base),
        'negative_and_scope_controls':controls,'source_semantic_controls':source_controls,'runtime_cases':results,
        'physical_asset_count_each_case':1,'service_phase_channels_each_case':2,'real_EP_runs':3,
        'same_electricity_with_alternative_heat_split':abs(results[1]['runtime']['facility_kWh']-results[2]['runtime']['facility_kWh'])<1e-7,
        'new_population_households_generated':0,'new_actor_ready_households':0,'observed_human_answers':0,
        'collection_release':False,'training_release':False}
    save(out/'CHAIN_VERIFICATION.json',report)
    save(out/'WITNESS_LOCK.json',{'base_INPUT_sha256':sha(base/'INPUT.json'),'base_IDF_sha256':sha(base/'building.idf'),
        'weather_sha256':sha(weather),'engine_sha256':sha(ENGINE),
        'code':{n:sha(out/'code'/n) for n in ['typed_chain.py','source_semantics.py','run_chain_witnesses.py']}})
    print(json.dumps({'pass':passed,'semantic_controls':len(controls)+len(source_controls),
        'runtime_cases':[{r['case']:r['runtime']['facility_kWh']} for r in results]},ensure_ascii=False))
    if not passed:raise SystemExit(1)

if __name__=='__main__':main()
