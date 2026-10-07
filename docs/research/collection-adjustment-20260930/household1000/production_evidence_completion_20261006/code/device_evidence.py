"""Specific same-source appliances; grouped flags never create instances.

City-labeledCRECS2012 supplies historical auxiliary positive reports. Missing
slots remain unknown and reported counts are lower bounds. Coarsened complete
patterns retain within-source associations; no private source identifiers or
exact private areas/incomes are exported into generated reference routes.
"""
import collections,hashlib,json,math
from pathlib import Path
import numpy as np,pandas as pd
OUT=Path(__file__).resolve().parent.parent;BASE=OUT.parent;SOURCE=BASE/'crecs_admission_20261003'
LEVEL={1:0,2:0,3:-1,4:1,5:1,6:2,7:-1,8:-2,9:0}
def save(name,d):(OUT/name).write_text(json.dumps(d,ensure_ascii=False,indent=2,allow_nan=False)+'\n')
def integer(x):return int(x) if isinstance(x,(int,float)) and math.isfinite(x) and x==int(x) else None
def bin_area(x):return int(np.searchsorted([12,30,50,70,90,120,150,180,250],x,side='left'))+1
def code(row,k,allowed):
    v=integer(row.get(k));return v if v in allowed else None
def decode(x):
    try:return x.encode('latin1').decode('gb18030')
    except (UnicodeError,AttributeError):return x
def devices(row):
    result=[]
    for i in range(1,4):
        if code(row,f'c3_{i}c',range(1,6)) is not None:
            result.append({'class':'washer','source_slot':i,'type_code':code(row,f'c3_{i}c',range(1,6)),
              'capacity_bin':code(row,f'c3_{i}d',range(1,6)),'frequency_bin':code(row,f'c3_{i}e',range(1,8)),
              'duration_bin':code(row,f'c3_{i}f',range(1,8)),'water_temperature_bin':code(row,f'c3_{i}g',range(1,5)),
              'source_field_prefix':f'c3_{i}','questionnaire_PDF_page':8})
        if code(row,f'c4_{i}b',[1,2]) is not None:
            result.append({'class':'washer_dryer_combo_report' if integer(row[f'c4_{i}b'])==1 else 'dryer',
              'source_slot':i,'combo_report_is_not_an_extra_independent_washer':integer(row[f'c4_{i}b'])==1,
              'frequency_bin':code(row,f'c4_{i}d',range(1,8)),'duration_bin':code(row,f'c4_{i}f',range(1,8)),
              'source_field_prefix':f'c4_{i}','questionnaire_PDF_page':8})
        if code(row,f'c2_dbx_{i}b',range(1,9)) is not None:
            result.append({'class':'refrigerator','source_slot':i,'type_code':code(row,f'c2_dbx_{i}b',range(1,9)),
              'volume_bin':code(row,f'c2_dbx_{i}c',range(1,6)),'source_field_prefix':f'c2_dbx_{i}','questionnaire_PDF_page':7})
    for i in range(1,6):
        if code(row,f'd4_{i}a',[1,2]) is not None:
            result.append({'class':'water_heater','source_slot':i,'type_code':code(row,f'd4_{i}a',[1,2]),
              'fuel_code':code(row,f'd4_{i}b',range(1,8)),'frequency_bin':code(row,f'd4_{i}c',range(1,9)),
              'duration_bin':code(row,f'd4_{i}d',range(1,8)),'purpose_code':code(row,f'd4_{i}f',range(1,5)),
              'storage_volume_bin':code(row,f'd4_{i}j__1',range(1,6)) if integer(row[f'd4_{i}a'])==1 else None,
              'storage_question_unasked_for_instantaneous_type':integer(row[f'd4_{i}a'])==2,
              'source_field_prefix':f'd4_{i}','questionnaire_PDF_page':14})
        if code(row,f'd6_{i}a',[1,2,3]) is not None:
            result.append({'class':'building_central_AC' if integer(row[f'd6_{i}a'])==1 else 'household_central_AC' if integer(row[f'd6_{i}a'])==2 else 'split_AC',
              'source_slot':i,'type_code':code(row,f'd6_{i}a',[1,2,3]),
              'cooling_capacity_like_bin_not_electric_input':code(row,f'd6_{i}b',range(1,8)) if integer(row[f'd6_{i}a'])==3 else None,
              'unasked_central_capacity_value_conflict':integer(row[f'd6_{i}a']) in [1,2] and code(row,f'd6_{i}b',range(1,8)) is not None,
              'capacity_question_unasked_for_central_type':integer(row[f'd6_{i}a']) in [1,2],
              'coverage_room_code':code(row,f'd6_{i}e',range(1,8)),'has_heating_report':code(row,f'd6_{i}f',[1,2]),
              'daily_cooling_duration_bin':code(row,f'd6_{i}g',range(1,10)),
              'annual_cooling_days_bin':code(row,f'd6_{i}h',range(1,8)),'thermostat_report':code(row,f'd6_{i}i',[1,2]),
              'source_field_prefix':f'd6_{i}','questionnaire_PDF_page':16})
    return result
def physical_lower_bound(assets):
    c=collections.Counter(a['class'] for a in assets)
    return sum(c.values())-c['washer']-c['washer_dryer_combo_report']+max(c['washer'],c['washer_dryer_combo_report'])
def main():
    if (OUT/'PACKAGE_MANIFEST.json').exists():raise SystemExit('sealed')
    raw=SOURCE/'private_raw/CRECS2012.dta';df=pd.read_stata(raw,convert_categoricals=False);city=df[(df.valid==1)&(df.b1==1)];records=[];reasons=collections.Counter()
    for row in city.to_dict('records'):
        N=integer(row['a1']);rels=[code(row,f'a2_{i}_a',range(1,12)) for i in range(1,9)];known=[r for r in rels if r is not None]
        if N is None or N!=len(known):reasons['resident_roster_inconsistent_or_unknown']+=1;continue
        # Nonkin/other relation does not identify a generational level.
        G=len({LEVEL[r] for r in known}) if all(r in LEVEL for r in known) else None
        assets=devices(row);record={'N':N,'G':G,'province':decode(row['province']),'gross_area_bin':code(row,'b13',range(1,11)),
          'heating_source_code':code(row,'d1',range(1,6)),'assets':assets,
          'empty_slots_are_unknown_not_absence':True,'full_asset_counts':None,'source_reference_year':2012}
        records.append(record)
    assert len(city)==928 and records
    pp=json.loads((BASE/'idf_joint_production_20261005/HOUSEHOLDS1000_JOINT_GEOMETRY_CANDIDATE.json').read_text())['profiles'];routes=[];matchcounts=collections.Counter()
    for p in pp:
        N=p['family']['resident_count'];G=p['family']['generation_count'];area=bin_area(p['housing']['H6_census_building_area_design_m2'])
        stages=[('same_province_NG_area',[r for r in records if (r['province'],r['N'],r['G'],r['gross_area_bin'])==(p['province'],N,G,area)]),
          ('national_NG_area',[r for r in records if (r['N'],r['G'],r['gross_area_bin'])==(N,G,area)]),
          ('national_NG',[r for r in records if (r['N'],r['G'])==(N,G)]),
          ('national_N',[r for r in records if r['N']==N]),('national_size_transport',[r for r in records])]
        stage,pool=next((s,pool) for s,pool in stages if pool);matchcounts[stage]+=1
        patterns=collections.Counter(json.dumps({'assets':r['assets'],'heating_source_code':r['heating_source_code']},sort_keys=True,ensure_ascii=False) for r in pool)
        # Deterministic quantile of the empirical coarsened-pattern pool is
        # a reference donor-prior draw, never a new source-household fact.
        q=(int(hashlib.sha256(('EB_DEVICE_PRIOR20261006|'+p['slot_id']).encode()).hexdigest(),16)%1000000+.5)/1000000;running=0
        for encoded,count in sorted(patterns.items()):
            running+=count/len(pool)
            if running>=q:chosen=json.loads(encoded);support=count;break
        for i,asset in enumerate(chosen['assets']):
            asset.update({'report_reference_id':p['slot_id']+'-asset-report-ref-'+str(i+1),'source_year':2012,
             'observed_for_generated_household':False,'historical_auxiliary_matched_report':True,
             'installed_in_generated_housing':False,'device_model_power_curves_or_clock_schedule_supplied_by_survey':False,
             'remote_control_capability_or_permission_observed':False})
        routes.append({'household_id':p['slot_id'],'province':p['province'],'N':N,'G':G,'match_route':stage,'source_pool_count':len(pool),
          'selected_coarsened_pattern_count':support,'auxiliary_reported_assets':chosen['assets'],'positive_asset_service_report_count':len(chosen['assets']),
          'distinct_physical_asset_lower_bound_count':physical_lower_bound(chosen['assets']),
          'washer_combo_crossmodule_instance_identity_unresolved':any(a['class']=='washer_dryer_combo_report' for a in chosen['assets']),
          'source_heating_code':chosen['heating_source_code'],'unreported_extra_assets_or_true_total_unknown':True,
          'transport2012_to2020_and_city_label_to_census_city_ordinary_not_observed':True,'observed2020_asset_prevalence':None,
          'household_service_or_installed_device_IDF_complete':False})
    summary={'source_city_labeled_records':len(city),'roster_consistent_auxiliary_records':len(records),'excluded':dict(reasons),
      'source_generation_proxy_known':sum(r['G'] is not None for r in records),'no_survey_weight_field_available':True,
      'historical_auxiliary_positive_reported_slots_by_class':dict(collections.Counter(a['class'] for r in records for a in r['assets'])),
      'routes1000_by_support':dict(matchcounts),'specific_appliances_derived_from_CHFS_group_flags':0,
      'invalid24_or3_multitype_codes_not_silently_admitted_as_specific_type':True,'source2013_rural_microdata_not_loaded':True,
      'source_private_IDs_exact_areas_incomes_or_records_exported':False,'national2020_single_asset_ownership_distribution_identified':False}
    save('SPECIFIC_DEVICE_SOURCE_ADMISSION.json',summary);save('DEVICE_PRIOR_ROUTES1000.json',{'routes':routes,'summary':summary,'not_installed_household_assets_or_true_population_prevalence':True})
    print(json.dumps(summary,ensure_ascii=False,indent=2))
if __name__=='__main__':main()
