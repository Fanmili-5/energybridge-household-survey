#!/usr/bin/env python3
"""Build traceable household-building experiments and run real annual EP witnesses."""
import argparse
import copy
import csv
import hashlib
import json
import math
import re
import shutil
import sqlite3
import subprocess
import time
from collections import Counter
from concurrent.futures import ThreadPoolExecutor,as_completed
from pathlib import Path
from household_model import HERE,REPO,BATCH,sha,digest,save,decision,input_errors,make_layout,layout_checks,numeric_tree_errors,verify_generation_binding
from idf_builder import build_idf,idf_checks
from geometry_gate import inspect_idf
from weather_rules import resolve_weather
from prototype_rules import resolve_prototype,group_from_key,target_signature,describe_target_conditions

PROTOTYPES=REPO/'docs/research/long-horizon-plan/execution/prelaunch_rigor_20260924/household_300_resolution_20260925/v2_trial_20260926/C_idf/building_300.json'
ENGINE=Path('/Applications/EnergyPlus-24-1-0/energyplus')
SEVERITY=re.compile(r'\*\*\s*(Warning|Severe|Fatal)\s*\*\*',re.I)
LEGACY_FIXTURE_PATH=HERE.parent/'household_to_idf_20261003/final_v5/EXPERIMENT_INPUTS.json'
LEGACY_FIXTURE_SHA256='3be8bf2313e098908f6d8afa3b73bc07daf786013b771da5318abeb897a26bd7'
_REGISTRY_CACHE={}

def current_prototype_registry():
    path=HERE/'PROTOTYPE_REGISTRY.json';raw=path.read_bytes();actual=hashlib.sha256(raw).hexdigest()
    if actual not in _REGISTRY_CACHE:
        _REGISTRY_CACHE.clear();_REGISTRY_CACHE[actual]=json.loads(raw)
    return _REGISTRY_CACHE[actual]

def prototype_request_for(item,registry):
    """Only exact immutable v1 fixtures receive a compatibility adapter.

    New inputs must declare their own request. No purpose/prototype-key string
    by itself grants template transport or claims a matched real dwelling.
    """
    if 'prototype_request' in item:return item['prototype_request'],{'origin':'explicit_input_request'},[]
    if sha(LEGACY_FIXTURE_PATH)!=LEGACY_FIXTURE_SHA256:return None,{},['legacy_fixture_file_hash_mismatch']
    frozen=json.loads(LEGACY_FIXTURE_PATH.read_text());signature=digest(item)
    if signature not in {digest(x) for x in frozen}:return None,{},['prototype_request_required_for_new_input']
    key=item['model_policy'].get('prototype_key')
    target={'geometry_family':'single_storey_apartment','building_form':None,'construction_year':None,
        'city':item['site'].get('city'),'province':item['site'].get('province'),'feature_evidence':{
            k:{'kind':'frozen_fixture_declared_location','evidence_id':'v1-input:'+signature} for k in ['city','province'] if item['site'].get(k) is not None}}
    req={'prototype_key':key,'target':target,'policy':{'mode':'declared_design','use_scope':'assemblies_and_height_only'}}
    try:
        gid=group_from_key(key,registry);conditions=describe_target_conditions(key,target,registry)
    except ValueError:
        # Preserve unknown-source refusal through resolve_prototype; never pick
        # a known substitute just to make the fixture compile.
        gid='unresolved_source';conditions={'unknown_features':['target.building_form','target.construction_year'],'mismatch_axes':[]}
    bound={'source_group_id':gid,'target_signature':target_signature(target),'use_scope':'assemblies_and_height_only',
        'evidence_id':'frozen_v1_fixture:'+item['case_id']+':'+signature,
        'rationale':'exact immutable conditional-design fixture compatibility; no source topology, measured locality or actor role inferred'}
    req['policy']['design_evidence']={**bound,'kind':'conditional_template_design','accepted_unknown_features':conditions['unknown_features']}
    if item.get('template_transport_evidence')=='explicit_climate_stress_experiment_not_local_stock_match':
        req['policy'].update(mode='transport',transport_evidence={**bound,'kind':'engineering_transport_design',
            'allowed_mismatches':conditions['mismatch_axes']})
    return req,{'origin':'exact_frozen_v1_fixture_adapter','source_fixture_file_sha256':LEGACY_FIXTURE_SHA256,
        'source_fixture_semantic_sha256':signature,'actual_home_geography_inferred':False},[]

def prototype_target_site_errors(request,item,registry):
    """Do not authorize one city/province while simulating a different one."""
    if not isinstance(request,dict) or not isinstance(request.get('target'),dict):return ['prototype_target_missing']
    target=request['target'];site=item['site'];errors=[]
    def label(v):
        if not isinstance(v,str):return v
        s=v.strip().casefold()
        return s[:-1] if s.endswith(('省','市')) else s
    for feature in ['city','province']:
        a,b=target.get(feature),site.get(feature)
        if a is None or b is None:errors.append('prototype_target_site_'+feature+'_unresolved');continue
        if label(a)==label(b):continue
        equivalent=False
        if feature=='city':
            # Only aliases already independently justified in the registry are
            # eligible, and their province must also match this target site.
            for group in registry['groups'].values():
                meta=group['source_metadata'];aliases={label(v) for v in meta.get('city_aliases',[])}
                if label(a) in aliases and label(b) in aliases and label(meta.get('province_label'))==label(site.get('province')):
                    equivalent=True;break
        if not equivalent:errors.append('prototype_target_site_'+feature+'_mismatch')
    year=item['housing'].get('building_year_design')
    if year is not None:
        if type(year) is not int:errors.append('housing_building_year_design_invalid')
        elif target.get('construction_year')!=year:errors.append('prototype_target_housing_construction_year_mismatch')
    return errors

def designed_site(station_id):
    c=json.loads((REPO/'simulation_resources/catalog.json').read_text())
    e=next(x for x in c['weather'] if x['id']==station_id)
    loc=next(csv.reader((REPO/e['epw']).open()))
    return {**{k:e[k] for k in ['province','city','latitude','longitude','timezone']},
        'altitude_m':float(loc[9]),'coordinate_evidence':{'status':'designed_site_equal_weather_station',
        'station_id':station_id,'source_catalog_sha256':sha(REPO/'simulation_resources/catalog.json'),
        'reason':'controlled engineering experiment, not city-household sampling'}}

def example_inputs():
    templates=json.loads(PROTOTYPES.read_text())['records']
    template=next(r for r in templates if 'Chengdu' in r['source_catalog_key'] and r['source_branch']=='verified_DeST_90zone_apartment')
    prototype_id=template['role_id'];site=designed_site('chn_561870')
    inputs=[]
    for n,g,rooms,area in [(1,1,1,50),(2,1,2,80),(3,2,2,90),(5,3,3,140),(7,3,4,180),(10,4,5,230)]:
        members=[f'm{i:02d}' for i in range(1,n+1)];groups=[[] for _ in range(rooms)]
        for i,m in enumerate(members):groups[i%rooms].append(m)
        inputs.append({'case_id':f'design_n{n}_g{g}_h7{rooms}','purpose':'prespecified size-room capacity validation, not population sample',
            'family':{'population_scope':'city_family_household','resident_count':n,'resident_member_ids':members,'generation_count_design':g,
                'residence_evidence':'declared_synthetic_role','member_semantics':'resident identifiers only; ages/full kinship/behavior not generated by this stage'},
            'housing':{'H5_status':'ordinary_declared_or_matched','H5_evidence':'declared_design_for_conditional_template_test',
                'occupancy_scope':'whole_household_private','household_storeys':1,'dwelling_type':'apartment',
                'H6_building_area_m2':area,'H6_evidence':'declared_design','H7_natural_rooms_exact':rooms,
                'H7_evidence':'declared_design','H7_definition':'natural_rooms_excluding_kitchen_toilet_corridor_hall','sleep_groups':groups},
            'site':copy.deepcopy(site),
            'model_policy':{'gross_to_zone_floor_ratio':1/1.33,'net_ratio_evidence':'declared_geometry_bridge',
                'floor_position':'middle','wall_boundaries':{'west':'Adiabatic','east':'Adiabatic','south':'Outdoors','north':'Outdoors'},
                'north_axis_deg':0,'air_exchange_ach':.5,'prototype_key':prototype_id},
            'operation_mode':'building_shell_validation','source_provenance':{'status':'fully_declared_research_input','raw_survey_household_copied':False},
            'expected_result':'idf_ready'})
    reference=inputs[2]
    for label,key,value in [('net_ratio_0p8','gross_to_zone_floor_ratio',.8),('top_floor','floor_position','top'),
                           ('orientation_90','north_axis_deg',90),('air_exchange_0p8','air_exchange_ach',.8),
                           ('four_exterior_faces','wall_boundaries',dict.fromkeys(['west','east','south','north'],'Outdoors'))]:
        x=copy.deepcopy(reference);x['case_id']='paired_'+label;x['purpose']='single-factor conditional-model sensitivity'
        x['paired_reference']=reference['case_id'];x['factor_path']='model_policy.'+key;x['model_policy'][key]=value
        inputs.append(x)
    for label,station in [('cold_weather','chn_507740'),('warm_weather','chn_594930')]:
        x=copy.deepcopy(reference);x['case_id']='paired_'+label;x['purpose']='climate stress test of fixed Chengdu prototype, not a matched local stock home'
        x['paired_reference']=reference['case_id'];x['factor_path']='site';x['site']=designed_site(station)
        x['template_transport_evidence']='explicit_climate_stress_experiment_not_local_stock_match'
        inputs.append(x)
    negatives=[
        ('unknown_H5','housing.H5_status','unknown'),
        ('missing_H5_evidence','housing.H5_evidence',None),
        ('shared_scope','housing.occupancy_scope','shared_unknown'),
        ('multistorey','housing.household_storeys',2),
        ('boolean_storeys','housing.household_storeys',True),
        ('unknown_H6','housing.H6_building_area_m2',None),
        ('topcoded_H7','housing.H7_natural_rooms_exact',None),
        ('roster_mismatch','family.resident_count',4),
        ('missing_city','site.city',None),
        ('wrong_timezone','site.timezone',9),
        ('town_target','site.city','某镇'),
        ('unknown_floor','model_policy.floor_position',None),
        ('unknown_prototype','model_policy.prototype_key','not_a_prototype')
    ]
    for label,path,value in negatives:
        x=copy.deepcopy(reference);x['case_id']='reject_'+label;x['purpose']='prespecified independent input refusal control'
        obj=x
        parts=path.split('.')
        for part in parts[:-1]:obj=obj[part]
        obj[parts[-1]]=value;x['expected_result']='blocked';inputs.append(x)
    x=copy.deepcopy(inputs[0]);x['case_id']='reject_capacity';x['housing']['H6_building_area_m2']=20;x['expected_result']='blocked';inputs.append(x)
    x=copy.deepcopy(reference);x['case_id']='reject_shanghai_weather';x['site']=designed_site('shanghai');x['expected_result']='blocked'
    inputs.append(x)
    registry=current_prototype_registry()
    for item in inputs:
        req,origin,errors=prototype_request_for(item,registry)
        if errors:raise ValueError('default_fixture_adapter:'+','.join(errors))
        item['prototype_request']=req;item['prototype_request_origin']=origin
        if item['case_id']=='reject_shanghai_weather':
            item['case_id']='reject_undeclared_shanghai_transport'
            item['purpose']='refuse undeclared Chengdu assembly transport to the declared Shanghai climate context'
    return inputs

def build_one(item,out,templates):
    safe_id=item.get('case_id') if isinstance(item.get('case_id'),str) and re.fullmatch(r'[A-Za-z0-9_-]{1,100}',item['case_id']) else 'invalid-case-'+digest(item)[:12]
    folder=out/'cases'/safe_id;folder.mkdir(parents=True)
    save(folder/'INPUT.json',item);trace=[]
    for key,obj in [('family',item.get('family')),('housing',item.get('housing')),('site',item.get('site')),('model_policy',item.get('model_policy'))]:
        decision(trace,'input_'+key,obj,'declared_input',['INPUT.json:'+key],'freeze provided fields and evidence; never resample to pass')
    record={'case_id':item.get('case_id'),'case_folder':safe_id,'expected_result':item.get('expected_result'),'input_sha256':sha(folder/'INPUT.json'),
        'experiment_id':BATCH+'__'+out.name,
        'input_semantic_sha256':digest(item),'input_scope':'declared research household-building conditional experiment',
        'status':'blocked','stage_reached':'input_admission','errors':[],'complete_actor_role':False,
        'ordinary_1000_slots_assigned':False,'collection_release':False,'training_release':False}
    errors=[]
    try:
        errors=input_errors(item)
        if 'generation_binding' in item and isinstance(item.get('family'),dict) and isinstance(item.get('housing'),dict):
            generation=verify_generation_binding(item);save(folder/'GENERATION_BINDING_CHECK.json',generation)
            errors+=['generation_binding:'+e for e in generation['errors']]
            record['generation_binding_status']=generation['status']
            record['generation_binding_check_sha256']=sha(folder/'GENERATION_BINDING_CHECK.json')
            record.update(generation_slot_id=item['generation_binding'].get('slot_id') if isinstance(item['generation_binding'],dict) else None,
                generation_profile_file_path=generation.get('profile_file_path'),generation_profile_file_sha256=generation.get('profile_file_sha256'))
            decision(trace,'generation_binding',generation,'verified_profile_consistency',['INPUT.generation_binding'],
                'actual source file byte hash plus slot and complete family/housing semantic hashes',
                ['not statistical validation','site/model context may be a separate declared engineering experiment','not actual household geography'])
        if not errors:
            weather=resolve_weather(item.get('site',{}),REPO);save(folder/'WEATHER_MATCH.json',weather)
            if weather.get('catalog'):
                record.update(weather_catalog_path=weather['catalog']['path'],weather_catalog_sha256=weather['catalog']['sha256'])
            if weather['selected'] is None:errors=['weather:'+weather['status']]
            else:
                selected=weather['selected']
                w={'epw_path':selected['epw_absolute_path'],'epw_sha256':selected['epw_sha256'],'location':selected['epw_location']}
                decision(trace,'weather_binding',{'station':selected['id'],'epw_sha256':w['epw_sha256']},'matched_weather_candidate',
                    ['input_site','weather_catalog'], 'same city and explicit geographic/full-year file policy',
                    ['typical-year input, not observed household weather','climate equivalence not certified'])
                record['stage_reached']='template_admission'
                registry=current_prototype_registry()
                request,origin,errors=prototype_request_for(item,registry)
                if not errors:
                    save(folder/'PROTOTYPE_REQUEST.json',{'request':request,'origin':origin})
                    errors+=prototype_target_site_errors(request,item,registry)
                    match=resolve_prototype(request,REPO,registry)
                    save(folder/'PROTOTYPE_MATCH.json',match)
                    errors+=['prototype:'+e for e in match['reject_reasons']]
                    if not match['eligible']:errors.append('prototype:not_eligible')
                    prototype=match['selected_catalog_row']
                    legacy_key=item['model_policy'].get('prototype_key')
                    if legacy_key and prototype and ((request.get('prototype_key') is not None and request['prototype_key']!=legacy_key) or
                            (request.get('prototype_key') is None and prototype['role_id']!=legacy_key)):
                        errors.append('prototype:conflicting_model_policy_prototype_key')
                    record.update(prototype_status=match['status'],prototype_source_group_id=match['selected_group_id'],
                        prototype_match_sha256=sha(folder/'PROTOTYPE_MATCH.json'),prototype_request_sha256=sha(folder/'PROTOTYPE_REQUEST.json'))
                    decision(trace,'prototype_admission',{'status':match['status'],'source_group_id':match['selected_group_id'],
                        'request_origin':origin,'request_sha256':sha(folder/'PROTOTYPE_REQUEST.json')},'engineering_source_eligibility',
                        ['PROTOTYPE_REQUEST.json','PROTOTYPE_MATCH.json','PROTOTYPE_REGISTRY.json'],
                        'explicit feature/design/transport evidence plus actual selected source closure and symmetric internal-wall gate',
                        ['not measured home matching','no source topology or operations inherited','not empirical calibration'])
                if not errors:
                    layout,errors=make_layout(item,trace)
                    if layout:
                        errors+=numeric_tree_errors(layout,'derived_layout')
                        if not errors:
                            save(folder/'LAYOUT.json',layout);record['stage_reached']='geometry_validation'
                            checks=layout_checks(item,layout);save(folder/'LAYOUT_CHECK.json',{'errors':checks});errors+=checks
                    if not errors:
                        record['stage_reached']='IDF_binding'
                        body,ledger,index=build_idf(item,layout,prototype,w,trace)
                        idf=folder/'building.idf';idf.write_text(body)
                        independent=inspect_idf(body,layout)
                        independent.update(input_semantic_sha256=record['input_semantic_sha256'],layout_sha256=sha(folder/'LAYOUT.json'))
                        save(folder/'INDEPENDENT_GEOMETRY_CHECK.json',independent)
                        errors+=['independent_geometry:'+e for e in independent['errors']]
                        record.update(stage_reached='independent_geometry_validation',independent_geometry_status=independent['status'],
                            independent_geometry_check_sha256=sha(folder/'INDEPENDENT_GEOMETRY_CHECK.json'),
                            independent_geometry_checker_sha256=independent['checker_sha256'])
                        static=idf_checks(body,layout);save(folder/'IDF_STATIC_CHECK.json',static);errors+=static['errors']
                        save(folder/'ASSEMBLY_BINDING.json',ledger);save(folder/'IDF_OBJECT_LINEAGE.json',index)
                        save(folder/'OPERATIONAL_BINDING_INTERFACE.json',{'member_sleep_zone':{m:s['name'] for s in layout['spaces'] for m in s.get('member_ids_sleeping',[])},
                            'allowed_zone_names':[s['name'] for s in layout['spaces']],
                            'people_gains':None,'appliance_inventory_and_power':None,'device_access_control':None,'occupancy_schedules':None,'HVAC_and_controls':None,
                            'status':'pending_explicit_operational_attachment','zero_operational_load_is_not_a_household_observation':True,
                            'next_stage_must_preserve_INPUT_family_and_housing_hashes':True})
                        record.update(idf_path=str(idf),idf_sha256=sha(idf),
                            weather_epw_path=w['epw_path'],weather_epw_sha256=w['epw_sha256'],
                            family_semantic_sha256=digest(item['family']),housing_semantic_sha256=digest(item['housing']),
                            layout_sha256=sha(folder/'LAYOUT.json'),zone_count=static['zone_count'],
                            zone_floor_area_m2=static['zone_floor_area_m2'],natural_room_count=static['H7_from_layout_semantics'],
                            H6_building_area_m2=item['housing']['H6_building_area_m2'])
                        if not errors and independent['status']=='pass':record['status']='idf_ready'
    except (ValueError,TypeError,OverflowError,ZeroDivisionError,AssertionError,KeyError,IndexError) as exc:
        errors.append('compilation_exception:'+record['stage_reached']+':'+type(exc).__name__+':'+str(exc))
    # Invalid derived calculations remain explicit diagnostic text, not NaN in
    # otherwise machine-readable evidence. The frozen admitted INPUT is intact.
    if numeric_tree_errors(trace):
        (folder/'REJECTED_DERIVED_TRACE.txt').write_text(repr(trace))
        errors.append('derived_trace_not_finite_binary64')
        trace=[{'decision_id':'invalid_derived_computation','evidence_status':'rejected',
            'diagnostic_path':'REJECTED_DERIVED_TRACE.txt','diagnostic_sha256':sha(folder/'REJECTED_DERIVED_TRACE.txt')}]
        record['status']='blocked'
    if errors:
        record['status']='blocked'
        idf=folder/'building.idf'
        if idf.exists():
            rejected=folder/'candidate_rejected.idf';idf.rename(rejected)
            record.update(rejected_candidate_idf_path=str(rejected),rejected_candidate_idf_sha256=sha(rejected))
        record.pop('idf_path',None);record.pop('idf_sha256',None)
    record['errors']=sorted(set(errors));record['trace_sha256']=digest(trace)
    save(folder/'DECISION_TRACE.json',{'batch_id':BATCH,'decisions':trace,'input_preserved_on_failure':True})
    save(folder/'STATUS.json',record)
    return record

def runtime_one(record,out,engine_info):
    started=time.monotonic();folder=out/'runtime'/record['case_id'];folder.mkdir(parents=True)
    command=[str(ENGINE),'-w',record['weather_epw_path'],'-d',str(folder),record['idf_path']]
    result={'case_id':record['case_id'],'input_idf_sha256':record['idf_sha256'],'weather_sha256':record['weather_epw_sha256'],
        'experiment_id':record['experiment_id'],
        'engine':engine_info,'command':command,'scope':'8760-hour annual free-floating thermal-shell witness; no human behavior, occupancy gains or electricity'}
    try:
        proc=subprocess.run(command,capture_output=True,text=True,timeout=240)
        (folder/'process.log').write_text(proc.stdout+'\n'+proc.stderr)
        err=(folder/'eplusout.err').read_text() if (folder/'eplusout.err').exists() else ''
        end=(folder/'eplusout.end').read_text() if (folder/'eplusout.end').exists() else ''
        counts=Counter(m.group(1).lower() for m in SEVERITY.finditer(err))
        errors=[]
        if proc.returncode!=0 or 'EnergyPlus Completed Successfully' not in end:errors.append('engine_not_completed')
        if counts['severe'] or counts['fatal']:errors.append('severe_or_fatal')
        values=[];area=None;hours=0;byzone={};location_rows=[]
        sql=folder/'eplusout.sql'
        if sql.exists():
            db=sqlite3.connect(sql)
            try:
                warm=db.execute('select count(*) from Time where coalesce(WarmupFlag,0)=0 and Interval=60').fetchone()[0]
                hours=warm
                expected_times={r[0] for r in db.execute('select TimeIndex from Time where coalesce(WarmupFlag,0)=0 and Interval=60')}
                area=db.execute('select sum(FloorArea) from Zones').fetchone()[0]
                rows=db.execute("""select d.KeyValue,min(r.Value),max(r.Value),avg(r.Value),count(*),count(r.Value),
                    count(distinct r.TimeIndex),sum(case when typeof(r.Value) in ('real','integer') then 1 else 0 end)
                    from ReportData r join ReportDataDictionary d using(ReportDataDictionaryIndex)
                    join Time t using(TimeIndex)
                    where d.Name='Zone Mean Air Temperature' and coalesce(t.WarmupFlag,0)=0 and t.Interval=60
                    group by d.KeyValue""").fetchall()
                zone_times={r[0]:set() for r in rows}
                for key,index in db.execute("""select d.KeyValue,r.TimeIndex from ReportData r
                    join ReportDataDictionary d using(ReportDataDictionaryIndex) join Time t using(TimeIndex)
                    where d.Name='Zone Mean Air Temperature' and coalesce(t.WarmupFlag,0)=0 and t.Interval=60"""):
                    zone_times[key].add(index)
                byzone={r[0]:{'minimum_C':r[1],'maximum_C':r[2],'mean_C':r[3],'hourly_count':r[4],
                    'nonnull_value_count':r[5],'distinct_hour_count':r[6],'numeric_value_count':r[7],
                    'time_index_set_matches_annual_hours':zone_times[r[0]]==expected_times} for r in rows}
                values=[x for r in rows for x in r[1:4]]
                if len(byzone)!=record['zone_count'] or any(r[4]!=8760 for r in rows):errors.append('temperature_series_count_not_full_annual')
                if any(r[5]!=8760 or r[7]!=8760 for r in rows):errors.append('temperature_series_null_or_non_numeric_values')
                if len(expected_times)!=8760 or any(r[6]!=8760 or zone_times[r[0]]!=expected_times for r in rows):errors.append('temperature_series_hour_index_set_mismatch')
                if any(not isinstance(v,(int,float)) or not math.isfinite(v) for v in values):errors.append('temperature_not_finite')
                if hours!=8760:errors.append('SQL_hour_count_not8760')
                if area is None or abs(area-record['zone_floor_area_m2'])>1e-5:errors.append('SQL_geometry_area_mismatch')
            finally:db.close()
        else:errors.append('SQL_missing')
        eio=folder/'eplusout.eio'
        if eio.exists():location_rows=[line for line in eio.read_text().splitlines() if line.lstrip().startswith('Site:Location,')]
        if not location_rows:errors.append('effective_engine_site_location_not_recorded')
        expected=json.loads((out/'cases'/record['case_id']/'WEATHER_MATCH.json').read_text())['selected']['epw_location']
        location_equal=False
        if location_rows:
            fields=next(csv.reader([location_rows[0]]))
            try:
                # Site:Location, Name, Latitude, Longitude, Time Zone, Elevation.
                actual=list(map(float,fields[2:6]))
                target=[expected[k] for k in ['latitude','longitude','timezone','altitude_m']]
                location_equal=all(abs(a-b)<=.011 for a,b in zip(actual,target))
            except ValueError:pass
        if not location_equal:errors.append('effective_engine_site_location_mismatch')
        result.update(status='pass' if not errors else 'failed',returncode=proc.returncode,
            errors=errors,severity=dict(counts),warning_lines=[line for line in err.splitlines() if re.search(r'\*\*\s*Warning\s*\*\*',line,re.I)],
            SQL_hours=hours,SQL_zone_floor_area_m2=area,zone_temperatures=byzone,
            eio_site_location_rows=location_rows,effective_location_matches_selected_epw=location_equal,
            output_hashes={p.name:sha(p) for p in folder.iterdir() if p.is_file()})
    except subprocess.TimeoutExpired:
        result.update(status='failed',errors=['engine_timeout240s'])
    except (OSError,sqlite3.Error,subprocess.SubprocessError,ValueError,TypeError,KeyError,IndexError,OverflowError,UnicodeError) as exc:
        result.update(status='failed',errors=['runtime_readback_exception:'+type(exc).__name__+':'+str(exc)])
    invalid_numbers=numeric_tree_errors(result,'runtime_result')
    if invalid_numbers:
        diagnostic=folder/'REJECTED_RUNTIME_NUMERIC_TRACE.txt'
        diagnostic.write_text(json.dumps(result,ensure_ascii=False,indent=2,allow_nan=True)+'\n')
        def finite_or_null(value):
            if isinstance(value,(int,float)) and not isinstance(value,bool):
                try:return value if math.isfinite(float(value)) else None
                except (OverflowError,ValueError):return None
            if isinstance(value,dict):return {k:finite_or_null(v) for k,v in value.items()}
            if isinstance(value,list):return [finite_or_null(v) for v in value]
            return value
        result=finite_or_null(result)
        result.update(status='failed',errors=result.get('errors',[])+['runtime_number_not_finite_binary64'],
            rejected_numeric_trace_path=str(diagnostic),rejected_numeric_trace_sha256=sha(diagnostic))
    result['elapsed_seconds']=round(time.monotonic()-started,3)
    save(folder/'RUNTIME_CHECK.json',result)
    return result

def audit_slots(out,records=None):
    root=HERE.parent;allocation=json.loads((root/'evidence_contract_20261001/POPULATION_ALLOCATION_CANDIDATE_V2.json').read_text())
    support=json.loads((root/'chfs_census_bridge_20261003/SLOT_BRIDGE_AUDIT.json').read_text())
    assert len(allocation['slots'])==len(support['slots'])==1000
    by_slot={}
    for r in records or []:
        if r.get('generation_slot_id'):by_slot.setdefault(r['generation_slot_id'],[]).append(r)
    rows=[]
    for s,b in zip(allocation['slots'],support['slots']):
        assert s['slot_id']==b['slot_id']
        cases=by_slot.get(s['slot_id'],[]);verified=[r for r in cases if r.get('generation_binding_status')=='pass'];ready=[r for r in verified if r['status']=='idf_ready']
        status='conditional_context_ready_actual_home_geography_pending' if ready else 'generated_family_housing_verified_conditional_support_blocked' if verified else 'no_generated_profile_bound_in_this_batch'
        rows.append({**s,'source_route_candidate':b['source_route_candidate'],
            'household_to_IDF_status':status,
            'generated_family_housing_bound_in_this_batch':bool(verified),
            'generated_profile_bindings':[{k:r.get(k) for k in ['generation_profile_file_path','generation_profile_file_sha256','generation_slot_id']} for r in verified],
            'conditional_context_cases':[{'case_id':r['case_id'],'case_folder':r['case_folder'],'status':r['status'],'errors':r['errors']} for r in cases],
            'conditional_context_IDF_created':bool(ready),
            'required_unassigned_fields':(['actual household city/coordinates','people/devices/HVAC/operational binding'] if verified else
                ['profile identity/complete family-housing input binding in this batch','actual household city/coordinates','conditional geometry/template support','people/devices/HVAC/operational binding']),
            'H7_conditional_if_ordinary':b['conditional_census_H7_distribution_if_ordinary_dwelling'],
            'IDF_created':False,'IDF_created_scope':'actual household geography binding, not declared climate-context compilation',
            'input_family_invented_to_fill_slot':False,'compiler_modified_upstream_family_or_housing':False})
    save(out/'TARGET1000_PREREQUISITE_AUDIT.json',{'allocation_sha256':sha(root/'evidence_contract_20261001/POPULATION_ALLOCATION_CANDIDATE_V2.json'),
        'bridge_sha256':sha(root/'chfs_census_bridge_20261003/SLOT_BRIDGE_AUDIT.json'),'slots':rows,
        'complete_upstream_input_slots':0,'complete_upstream_scope':'complete actual household geography and operational role, not profile-generation completion',
        'actual_IDF_slots':0,'actual_household_city_IDF_slots':0,
        'generated_family_housing_verified_slots':sum(s['generated_family_housing_bound_in_this_batch'] for s in rows),
        'conditional_context_IDF_slots':sum(s['conditional_context_IDF_created'] for s in rows),
        'conditional_context_IDF_cases':sum(r.get('generation_binding_status')=='pass' and r['status']=='idf_ready' for r in records or []),
        'scope':'this batch links verified generated family/housing profiles and declared climate-context compilation where present; actual household city and operational behavior remain unbound',
        'town_rural_excluded':True,'quotas_changed':False})

def main(args):
    out=args.output.resolve()
    if out.exists():raise RuntimeError('use a new output directory; prior experiments immutable')
    out.mkdir(parents=True)
    (out/'code').mkdir()
    for path in HERE.glob('*.py'):shutil.copy2(path,out/'code'/path.name)
    save(out/'ADMISSION_POLICY.json',{'batch_id':BATCH,
        'batch_policy':'invalid JSON/structure/duplicate IDs or any tree number not finite binary64 refuses whole batch before any case IDF',
        'case_policy':'well-formed batch with semantic/support/expected calculation failure records STATUS blocked and continues other cases',
        'numeric_rule':'all JSON numbers must be finitely representable as binary64; exact integer semantic checks are separate; no population/building-code bound inferred',
        'geometry_rule':'independent rectangular-prism/atomic-directed-edge/opening gate required before every idf_ready',
        'rejected_IDF_policy':'candidate_rejected.idf may preserve failed evidence; building.idf exists only for admitted candidates'})
    try:
        def reject_constant(value):raise ValueError('nonfinite_JSON_constant:'+value)
        inputs=json.loads(args.inputs.read_text(),parse_constant=reject_constant) if args.inputs else example_inputs()
        numbers=numeric_tree_errors(inputs)
        if numbers:raise ValueError(';'.join(numbers))
        if isinstance(inputs,dict):inputs=inputs.get('inputs')
        if not isinstance(inputs,list) or not inputs or not all(isinstance(x,dict) for x in inputs):raise ValueError('inputs_must_be_nonempty_array_of_objects')
        ids=[x.get('case_id') for x in inputs]
        if any(not isinstance(x,str) for x in ids):raise ValueError('all_case_ids_must_be_strings')
        if len(set(ids))!=len(ids):raise ValueError('duplicate_case_ids')
    except (ValueError,TypeError,KeyError,OverflowError,UnicodeError,OSError,RecursionError) as exc:
        save(out/'ADMISSION_FAILURE.json',{'status':'blocked','batch_id':BATCH,'experiment_id':BATCH+'__'+out.name,
            'stage_reached':'batch_input_admission','exception_type':type(exc).__name__,'errors':[str(exc)],
            'source_input_path':str(args.inputs) if args.inputs else None,
            'source_input_sha256':sha(args.inputs) if args.inputs and args.inputs.is_file() else None,'IDFs_written':0,
            'refusal_policy':'whole_batch_atomic_before_case_compilation','input_values_repaired':False})
        return
    templates={r['role_id']:r for r in json.loads(PROTOTYPES.read_text())['records']}
    save(out/'EXPERIMENT_INPUTS.json',inputs)
    save(out/'INPUT_LOCK.json',{'batch_id':BATCH,'prototype_catalog_path':str(PROTOTYPES),'prototype_catalog_sha256':sha(PROTOTYPES),
        'prototype_registry_path':str(HERE/'PROTOTYPE_REGISTRY.json'),'prototype_registry_sha256':sha(HERE/'PROTOTYPE_REGISTRY.json'),
        'weather_registry_path':str(HERE/'WEATHER_CATALOG.json' if (HERE/'WEATHER_CATALOG.json').exists() else REPO/'simulation_resources/catalog.json'),
        'weather_registry_sha256':sha(HERE/'WEATHER_CATALOG.json' if (HERE/'WEATHER_CATALOG.json').exists() else REPO/'simulation_resources/catalog.json'),
        'experiment_id':BATCH+'__'+out.name,
        'resource_catalog_path':str(REPO/'simulation_resources/catalog.json'),'resource_catalog_sha256':sha(REPO/'simulation_resources/catalog.json'),
        'code':{p.name:sha(p) for p in (out/'code').glob('*.py')},'seed':None,
        'random_sampling_used':False,'examples_population_representative':False})
    records=[]
    for item in inputs:
        record=build_one(item,out,templates);records.append(record)
        print(json.dumps({'case':record['case_id'],'status':record['status'],'errors':record['errors']},ensure_ascii=False),flush=True)
    audit_slots(out,records)
    runtime=[]
    if args.runtime:
        version=subprocess.run([str(ENGINE),'--version'],capture_output=True,text=True,check=True).stdout.strip()
        engine_info={'path':str(ENGINE),'version':version,'sha256':sha(ENGINE),'IDD_sha256':sha(ENGINE.parent/'Energy+.idd')}
        accepted=[r for r in records if r['status']=='idf_ready']
        with ThreadPoolExecutor(max_workers=2) as pool:
            tasks=[pool.submit(runtime_one,r,out,engine_info) for r in accepted]
            for task in as_completed(tasks):
                r=task.result();runtime.append(r)
                print(json.dumps({'runtime_case':r['case_id'],'status':r['status'],'errors':r['errors'],'hours':r.get('SQL_hours')},ensure_ascii=False),flush=True)
    save(out/'SUMMARY.json',{'batch_id':BATCH,'scope':'implemented household-to-building-IDF conditional research pipeline, not new1000 actor dataset',
        'batch_scope':'generated_profile_family_housing_under_declared_engineering_contexts' if any(r.get('generation_slot_id') for r in records) else 'controlled_design_fixture_thermal_shell_tests',
        'experiment_id':BATCH+'__'+out.name,
        'case_count':len(records),'IDF_ready':sum(r['status']=='idf_ready' for r in records),'blocked':sum(r['status']=='blocked' for r in records),
        'expected_controls_count':sum(r['expected_result'] in ['idf_ready','blocked'] for r in records),
        'unprespecified_candidate_count':sum(r['expected_result'] is None for r in records),
        'expected_status_all_matched':all(r['status']==r['expected_result'] for r in records if r['expected_result'] in ['idf_ready','blocked']),
        'actual_EP_annual_runs':len(runtime),'EP_annual_pass':sum(r['status']=='pass' for r in runtime),
        'records':records,'runtime':sorted(runtime,key=lambda x:x['case_id']),
        'generated_family_housing_bound_cases':sum(r.get('generation_binding_status')=='pass' for r in records),
        'conditional_context_IDFs':sum(r.get('generation_binding_status')=='pass' and r['status']=='idf_ready' for r in records),
        'actual_household_city_IDFs':0,'actual_household_city_binding_certified':False,
        'population_slots_preserved':1000,'new1000_complete_roles':0,'new1000_IDFs':0,
        'legacy_new1000_IDFs_scope':'actual household geography/complete-role binding only, excludes explicitly declared engineering-context IDFs counted separately',
        'empirical_calibration':False,'collection_release':False,'training_release':False})
    save(out/'MANIFEST.json',{'batch_id':BATCH,'files':{str(p.relative_to(out)):sha(p) for p in out.rglob('*') if p.is_file()},
        'experiment_id':BATCH+'__'+out.name,
        'source_geometry_observed':False,'source_survey_household_copied':False,'collection_release':False})
    print(json.dumps({k:v for k,v in json.loads((out/'SUMMARY.json').read_text()).items() if k not in ['records','runtime']},ensure_ascii=False),flush=True)

if __name__=='__main__':
    ap=argparse.ArgumentParser();ap.add_argument('--output',type=Path,required=True)
    ap.add_argument('--inputs',type=Path);ap.add_argument('--runtime',action='store_true')
    main(ap.parse_args())
