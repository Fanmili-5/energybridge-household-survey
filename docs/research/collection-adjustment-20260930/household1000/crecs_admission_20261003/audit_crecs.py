#!/usr/bin/env python3
"""CRECS source admission with aggregate QC and questionnaire-grounded rules.

No microdata rows are written to public outputs, no profiles are generated,
and no rural 2013 microdata are loaded. No invented zero/ownership/clock data.
"""
import hashlib
import json
from pathlib import Path
import re
import numpy as np
import pandas as pd

HERE=Path(__file__).resolve().parent
def read(p):return json.loads(p.read_text())
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def write(p,x):
    with p.open('x') as f:json.dump(x,f,ensure_ascii=False,indent=2,allow_nan=False);f.write('\n')
def counts(s):
    return {str(k) if pd.notna(k) else 'system_missing':int(v) for k,v in s.value_counts(dropna=False).sort_index().items()}
def coded(s,codes):return s.isin(codes)
def decode(t):
    if not isinstance(t,str):return t
    try:
        c=t.encode('latin1').decode('gb18030')
        if sum('\u4e00'<=x<='\u9fff' for x in c)>sum('\u4e00'<=x<='\u9fff' for x in t):return c
    except UnicodeError:pass
    return t
def group(fid,step,year,fields,pages,unit,rule,status='auxiliary_same_record_observation'):
    return {'id':fid,'generation_step':step,'year':year,'fields':fields,
            'questionnaire_pages_1based':pages,'measurement':unit,'rule':rule,'admission':status}

def main():
    manifest=read(HERE/'PACKAGE_MANIFEST.json')
    for e in manifest['entries']:
        if 'local_file' in e:assert sha(HERE/e['local_file'])==e['sha256']
    d12=pd.read_stata(HERE/'private_raw/CRECS2012.dta',convert_categoricals=False)
    d14=pd.read_stata(HERE/'private_raw/CRECS2014.dta',convert_categoricals=False)
    m12=read(HERE/'private_metadata/CRECS2012_stata_metadata.json')
    m14=read(HERE/'private_metadata/CRECS2014_stata_metadata.json')
    assert m12['value_labels']['B1']=={'1':'城市（县级市及以上）','2':'乡镇','3':'农村'}
    city=d12.loc[(d12.valid==1)&(d12.b1==1)].copy()
    assert len(d12)==1450 and len(city)==928 and len(d14)==3863
    assert d12['index'].notna().all() and not d12['index'].duplicated().any()
    assert d14.id.notna().all() and not d14.id.duplicated().any()
    weights={y:[k for k,v in m['variable_labels'].items() if re.search(r'(^weight$|^wgt|^wt$|权重|抽样权)',k+' '+v,re.I)]
             for y,m in [(2012,m12),(2014,m14)]}
    assert not weights[2012] and not weights[2014]
    size=coded(city.a1,range(1,9))
    relation_cols=[f'a2_{i}_a' for i in range(1,9)]
    roster=city[relation_cols].isin(range(1,12)).sum(axis=1)
    same=size&(roster==city.a1)
    area=coded(city.b13,range(1,11))&coded(city.b14,range(1,11))
    income=coded(city.f1a,range(1,19))
    complete=size&area&income
    strict=complete&same
    recognized={
        'washer_type_reported':city[[f'c3_{i}c' for i in range(1,4)]].isin([1,2,3,4,5,24]).any(axis=1),
        'dryer_or_combo_reported':city[[f'c4_{i}b' for i in range(1,4)]].isin([1,2]).any(axis=1),
        'AC_type_reported':city[[f'd6_{i}a' for i in range(1,6)]].isin([1,2,3]).any(axis=1),
        'water_heater_type_reported':city[[f'd4_{i}a' for i in range(1,6)]].isin([1,2,3]).any(axis=1)}
    province_counts=city.province.map(decode).value_counts(dropna=False)
    device_pair=[]
    for s in range(1,9):
        mask=city.a1==s
        if not mask.any():continue
        device_pair.append({'size':s,'source_records':int(mask.sum()),
            'reported_type_counts':{k:int((v&mask).sum()) for k,v in recognized.items()},
            'not_ownership_rate':True,'not_current_city_target':True})
    joint=city.loc[strict,['a1','b13','b14','f1a']].groupby(['a1','b13','b14','f1a'],dropna=False).size()
    # Full joint support is retained locally; public output contains no rare wide cells.
    private_joint=[{'size':int(s),'gross_area_bin':int(g),'usable_area_bin':int(u),
                    'annual_net_income_bin':int(i),'sample_count':int(n)} for (s,g,u,i),n in joint.items()]
    private_out=HERE/'private_metadata/CRECS2012_city_joint_support.json'
    write(private_out,{'observation_year':2012,'unweighted':True,'cohort_n':int(strict.sum()),'cells':private_joint})
    absent={y:{'dishwasher_named_fields':[k for k,v in m['variable_labels'].items() if re.search(r'洗碗|dishwash',k+' '+v,re.I)],
               'home_EV_charging_named_fields':[k for k,v in m['variable_labels'].items() if re.search(r'充电桩|电动汽车|家庭充电|家用充电|home.?charg',k+' '+v,re.I)]}
            for y,m in [(2012,m12),(2014,m14)]}
    scope14=[k for k,v in m14['variable_labels'].items() if re.search(r'城乡属性|居住地类型|样本类型|^urban$|^rural$|^s37a$',k+' '+v,re.I)]
    assert not scope14
    special14={k:{str(c):int((d14[k]==c).sum()) for c in codes} for k,codes in {
        'a62':[9999996,9999997,9999998,9999999],
        'a63':[97,98,99],'e86_1':[9996,9998,9999],
        'e86_2':[9996,9998,9999],'e86_3':[9996,9998,9999]}.items()}
    qc={'batch_id':'CRECS_SOURCE_QC_20261003_V1','package_sha256':manifest['archive']['sha256'],
        'source_read_scope':'CRECS2012 and CRECS2014 only; aggregate QC, no rows in public outputs',
        'years':{'2012':{'rows':len(d12),'variables':len(d12.columns),'id_field':'index',
            'id_duplicate_count':int(d12['index'].duplicated().sum()),
            'serial_duplicate_count':int(d12.serial.duplicated().sum()),
            'valid_counts':counts(d12.valid),'location_counts':counts(d12.b1),
            'city_selection_rule':'valid==1 AND b1==1','city_rows':len(city),
            'city_definition':'survey-reported city (county-level city or above); not verified identical to census statistical-city code',
            'city_province_count':len(province_counts),'city_records_by_province':{str(k):int(v) for k,v in province_counts.items()},
            'size_counts_city':counts(city.a1),'gross_area_bin_counts_city':counts(city.b13),
            'usable_area_bin_counts_city':counts(city.b14),
            'complete_size_area_income_bin_rows':int(complete.sum()),
            'roster_matches_size':int(same.sum()),'roster_less_than_size':int((size&(roster<city.a1)).sum()),
            'roster_more_than_size':int((size&(roster>city.a1)).sum()),'unknown_or_invalid_size':int((~size).sum()),
            'joint_support_with_roster_check_rows':int(strict.sum()),'joint_support_cells':len(joint),
            'joint_support_private_file':str(private_out.relative_to(HERE)),
            'whole_day_home_answer_counts':counts(city.a3),
            'reported_device_type_counts':{k:int(v.sum()) for k,v in recognized.items()},
            'size_reported_device_association':device_pair,
            'empty_device_slots_mean':'absence of a reported type; not verified no ownership; preserve unknown',
            'weight_fields_in_supplied_file':weights[2012]},
          '2013':{'microdata_read':False,'admission':'excluded rural population'},
          '2014':{'rows':len(d14),'variables':len(d14.columns),'id_duplicate_count':int(d14.id.duplicated().sum()),
            'questionnaire_title_year':2015,'energy_reference_year':2014,
            'survey_year_evidence':'PDF cover: CGSS2015; E2/E60/A62 explicitly refer to2014; do not conflate fieldwork and reference year',
            'city_town_split_fields_in_supplied_file':scope14,
            'weight_fields_in_supplied_file':weights[2014],
            'city_subset_generated':False,'city_selection_rule':None,
            'hukou_must_not_be_used_as_city_selector':True,'documented_special_value_counts':special14,
            'count_fields':['e17_1','e17_2','e21_1','e21_2','e56','e59']}},
        'missing_named_fields':absent,'profiles_generated':0,'engine_calls':0,
        'collection_release':False,'code_sha256':sha(Path(__file__))}
    write(HERE/'CRECS_SOURCE_QC.json',qc)
    fields=[
      group('crecs12_scope',1,2012,['valid','index','b1'],[3],'household record; survey location categories',
            'Select valid==1,b1==1 only; index is unique, serial is not. Do not equate city label with census statistical-city coding.', 'admitted_auxiliary_city_labeled_subset'),
      group('crecs12_members',2,2012,['a1']+[f'a2_{i}_{k}' for i in range(1,9) for k in ['a','b','c','d','e','f','g','i','k']],[2],
            'usual residents >6months; excludes visitors, active military and boarding students; roster up to8',
            'Preserve same-record members. Require reported size-roster agreement. Relationships are to household head, not a fully observed parent/spouse graph. Do not automatically age households from2012 to2020.'),
      group('crecs12_housing_bins',3,2012,['b13','b14'],[3],'both are area category codes1..10, not m2',
            'Questionnaire has merged response categories for B13 and B14. Both retain intervals and open topcode; no midpoint/exact geometry silently assigned.'),
      group('crecs12_rooms',3,2012,[f'b15_{r}_{i}{k}' for r,maxi in [('kt',5),('ws',5),('sf',5),('dxs',3),('gl',3)] for i in range(1,maxi+1) for k in ['a','b','c','d','e']],[4],
            'room area m2, window direction/count/frame/glass; rooms by type',
            'Living halls are excluded from census H7. Study/meeting rooms and basement/attic require a semantic bridge; slot count is not a direct H7 observation. No floorplan adjacency is observed.'),
      group('crecs12_building',4,2012,['b2','b3','b4','b9','b10','b11','b12'],[3],
            'building-storey band, dwelling floor, dwelling levels, vintage/material/height bands',
            'Do not equate dwelling-floor with building-storeys; 2012 and2020 storey cutpoints differ. Materials do not supply thickness, U-value or exact IDF.'),
      group('crecs12_assets',5,2012,[f'c3_{i}{k}' for i in range(1,4) for k in ['a','b','c','d','e','f','g']]+[f'c4_{i}{k}' for i in range(1,4) for k in ['a','b','c','d','e','f']],[8],
            'washer and dryer/combo slots, capacity/frequency/duration categories',
            'Reported type is positive evidence. Empty slots are unknown absence/skip/nonresponse. A washer-dryer combo is one physical asset with two services. No dishwasher fields located.'),
      group('crecs12_HVAC_hotwater',5,2012,[f'd4_{i}{k}' for i in range(1,6) for k in ['a','b']]+[f'd6_{i}{k}' for i in range(1,6) for k in ['a','b','c','e','f','g','h','i']],[14,16],
            'heater fuel/type, AC system type, cooling capacity band, use duration/region/controller',
            'Central building AC is not privately owned split AC. Cooling-capacity bins are not electric input power. Electric/solar-electric heater fuel stays separate from gas and solar.'),
      group('crecs12_schedule',6,2012,['a3','a3a','a3b','b6','c3_1e','c3_1f','c4_1d','c4_1f','d6_1g','d6_1h'],[2,3,8,16],
            'whole-day-home counts and use-frequency/duration categories',
            'Supports activity-budget bounds; does not observe task clock time, named operator, willingness, allowed intervention window or laundry/dish material releases.'),
      group('crecs12_economics',7,2012,['f1a','f1b','f1c','f1d','f1e','f1f','f1g','f2a','f2i'],[22],
            'annual household net income/expenses as bins in10k yuan; meter and bill responsibility',
            'Keep annual household basis and2012 price/reference year. Do not convert bins to exact monthly salary or current income; meter boundary is not remote-control consent.'),
      group('crecs14_members',2,2014,['a63']+[f'a0103_{i}' for i in range(1,15)]+[f'a0104_{i}' for i in range(1,15)],[8,25],
            'respondent-level CGSS sampling; broad family roster plus co-eating/co-residence/economic-independence flags',
            'Use residence flags and A63, not all roster entries as residents. Household weights cannot be replaced by person weights. Supplied file lacks resolved city selection; hold city donor use.', 'questionnaire_and_schema_only_city_admission_held'),
      group('crecs14_housing',3,2014,['a11','e3','e4','e5','e6','e7','e8','e9'],[11,43],
            'inside-unit building area m2, vintage/windows/retrofit bands',
            'Inside-unit building area is neither census whole building area nor usable area; do not multiply/divide by1.33 without a field-specific bridge.', 'questionnaire_and_schema_only_city_admission_held'),
      group('crecs14_assets',5,2014,['e21_1','e21_2','e22d','e22f','e22g','e56','e57a','e57b','e59','e60d','e60h','e60j','e60k'],[46,47,52,53],
            'explicit appliance counts; power/capacity, frequency/time, AC region/temperature bands',
            'Count!=listed slot count (AC details max4, water heater max2). Preserve99 nonresponse. AC nominal bands are cooling capacity. Do not backfill absent dishwasher/home-charge fields.', 'questionnaire_and_schema_only_city_admission_held'),
      group('crecs14_economics',7,2014,['a62','e76_1','e86_1','e86_2','e86_3','e87_1','e87_2'],[25,55,56,57],
            '2014 annual household income/expense, monthly electricity kWh/expense incl seasonal summaries',
            'Decode documented special codes (including9999996-9999999 income and9996/9998/9999 electricity) before numbers. Monthly recall is not smart-meter load or hourly task data.', 'questionnaire_and_schema_only_city_admission_held'),
      group('crecs_A',8,None,[],[],'synthetic annual A activities',
            'Build after household/asset freeze using sourced frequency and designed clock/operator/material rules; preserve unknowns. No observed annual task diary exists here.','not_observed_requires_generator'),
      group('crecs_B',9,None,[],[],'ten role-specific counterfactual scenarios',
            'B selects only A tasks/assets and verified constraints. CRECS policy opinions are not acceptance of EnergyBridge scenarios; cannot use them as collected answers.','not_observed_requires_generator'),
      group('crecs_physics',10,None,[],[],'EnergyPlus/equipment service and energy outcomes',
            'Physical service checks require geometry, equipment models, weather and complete state transitions; CRECS alone does not provide calibrated hourly load.','not_observed_requires_models'),
      group('crecs_actor',11,None,[],[],'actor role card and10 questionnaires',
            'Describe assigned role faithfully; monetary amounts/time precision require explicit design provenance. Answers remain null until human collection; no real household identifying fields.','not_observed_requires_collection_package')]
    for f in fields:
        if f['year']:
            meta=m12 if f['year']==2012 else m14
            missing=set(f['fields'])-set(meta['variable_labels'])
            assert not missing,(f['id'],missing)
            f['source_variable_labels']={k:meta['variable_labels'][k] for k in f['fields']}
    intervals=[(0,12),(12,30),(30,50),(50,70),(70,90),(90,120),(120,150),(150,180),(180,250),(250,None)]
    contract={'batch_id':'CRECS_FIELD_SOURCE_RULES_20261003_V1','steps_covered':list(range(1,12)),
      'package_manifest_sha256':sha(HERE/'PACKAGE_MANIFEST.json'),'QC_sha256':sha(HERE/'CRECS_SOURCE_QC.json'),
      'rules':fields,'area_codebook_2012':{str(i+1):{'lower_m2':lo,'upper_m2':hi,'lower_closed':False,
          'upper_closed':hi is not None,'source':'B13/B14 shared response cell; PDF p3 rendered inspection'} for i,(lo,hi) in enumerate(intervals)},
      'global_rules':['city-labeled source support != weighted national-city distribution',
        '2012/2014 observed household co-occurrence !=2020/2026 distribution',
        'survey observations remain separate from modeled transport, experiment design, physics, actor answers',
        'CFPS microdata not accessed; CRECS2013 rural data not used',
        'no silent clock, capacity, exact amount, control permission, floorplan or home-charge imputation'],
      'collection_release':False}
    write(HERE/'FIELD_SOURCE_RULES.json',contract)
    print(json.dumps({'city2012':len(city),'roster_checked_joint_support':int(strict.sum()),
                     '2014':len(d14),'field_groups':len(fields),'steps_covered':contract['steps_covered'],
                     'weights_found':weights,'collection_release':False},ensure_ascii=False))

if __name__=='__main__':main()
