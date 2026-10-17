#!/usr/bin/env python3
"""Pure field-level CRECS2012 semantics, keeping reports separate from assets."""
import math

AREA_INTERVALS={1:(0,12),2:(12,30),3:(30,50),4:(50,70),5:(70,90),
    6:(90,120),7:(120,150),8:(150,180),9:(180,250),10:(250,None)}
LEVEL={1:0,2:0,3:1,4:1,5:-1,6:-1,7:0,8:2,9:-2}

def num(v):
    if isinstance(v,bool):return None
    try:
        x=float(v)
        return x if math.isfinite(x) else None
    except (TypeError,ValueError):return None

def code(v,allowed):
    x=num(v)
    return int(x) if x is not None and x.is_integer() and int(x) in allowed else None

def interval(v):
    k=code(v,AREA_INTERVALS)
    if k is None:return None
    lo,hi=AREA_INTERVALS[k]
    return {'code':k,'lower_m2':lo,'upper_m2':hi,'lower_closed':False,'upper_closed':hi is not None,
        'value_status':'source_reported_interval_not_exact_area'}

def contains(i,x):return i is not None and x is not None and i['lower_m2']<x and (i['upper_m2'] is None or x<=i['upper_m2'])

def normalize(row):
    members=[]
    for i in range(1,9):
        rel=code(row.get(f'a2_{i}_a'),range(1,12))
        if rel is None:continue
        year=code(row.get(f'a2_{i}_c'),range(1900,2013))
        members.append({'relation_to_head_code':rel,'sex_code':code(row.get(f'a2_{i}_b'),[1,2]),
            'birth_year_known':year is not None,'source_age_interval':None if year is None else [max(0,2012-year-1),2012-year],
            'generation_level_proxy':LEVEL.get(rel)})
    n=code(row.get('a1'),range(1,9));levels=[m['generation_level_proxy'] for m in members]
    roster_ok=n is not None and len(members)==n and sum(m['relation_to_head_code']==1 for m in members)==1
    births_ok=all(m['birth_year_known'] for m in members)
    g=1 if n==1 and roster_ok else len(set(levels)) if roster_ok and None not in levels else None
    singleton_ok=n!=1 or (len(members)==1 and births_ok and members[0]['source_age_interval'][0]>=20)
    gross,usable=interval(row.get('b13')),interval(row.get('b14'))
    impossible_area_order=bool(gross and usable and gross['upper_m2'] is not None and usable['lower_m2']>=gross['upper_m2'])
    # Count positive room reports only. Empty slots do not certify zero rooms.
    rooms={kind:sum(num(row.get(f'b15_{kind}_{i}a')) is not None and num(row.get(f'b15_{kind}_{i}a'))>0
        for i in range(1,limit+1)) for kind,limit in [('kt',5),('ws',5),('sf',5),('dxs',3),('gl',3)]}
    reports=[];invalid=[]
    def add(stem,slots,type_suffix,types,family,extras):
        for i in range(1,slots+1):
            key=f'{stem}_{i}{type_suffix}';raw=row.get(key);kind=code(raw,types)
            if kind is None:
                if num(raw) is not None:invalid.append({'field':key,'reason':'code_outside_questionnaire_options'})
                continue
            fields={k:code(row.get(f'{stem}_{i}{suffix}'),valid) for k,(suffix,valid) in extras.items()}
            statuses={k:'source_categorical_observation' if fields[k] is not None else
                'invalid_code' if num(row.get(f'{stem}_{i}{suffix}')) is not None else 'unknown_or_unasked'
                for k,(suffix,valid) in extras.items()}
            reports.append({'report_key':f'{stem}_slot{i}','family':family,'type_code':kind,
                'positive_report':True,'ownership':None,'installed':None,'operable':None,
                'control_available':None,'role_permission_to_shift':None,
                'source_reference_year':2012,'electrical_input_power_W':None,
                'hardware_identity':'unresolved_service_report','fields':fields,'field_status':statuses})
    add('c2_dbx',3,'b',range(1,9),'refrigerator',{'capacity_category':('c',range(1,6))})
    add('c3',3,'c',range(1,6),'washer',{'capacity_category':('d',range(1,6)),
        'frequency_category':('e',range(1,8)),'duration_category':('f',range(1,8))})
    add('c4',3,'b',[1,2],'drying_service',{'capacity_category':('c',range(1,6)),
        'frequency_category':('d',range(1,8)),'duration_category':('f',range(1,8))})
    add('d4',5,'a',[1,2],'hot_water_service',{'fuel_code':('b',range(1,8)),
        'storage_volume_category':('j__1',range(1,6))})
    add('d6',5,'a',[1,2,3],'cooling_service',{'capacity_like_category':('b',range(1,8)),
        'cooled_room_type':('e',range(1,8)),'heating_capability':('f',[1,2]),
        'duration_category':('g',range(1,10)),'summer_days_category':('h',range(1,8)),
        'thermostat_present_code':('i',[1,2])})
    for r in reports:
        if r['family']=='cooling_service' and r['type_code'] in [1,2]:
            r['fields']['capacity_like_category']=None # b-d explicitly skipped.
            r['field_status']['capacity_like_category']='not_applicable_branch_skip'
        if r['family']=='hot_water_service' and r['type_code']==2:
            r['fields']['storage_volume_category']=None
            r['field_status']['storage_volume_category']='not_applicable_branch_skip'
    return {'city_labeled':code(row.get('valid'),[1])==1 and code(row.get('b1'),[1,2,3])==1,
        'N':n,'G_proxy':g,'member_reference_admitted':bool(roster_ok and births_ok and singleton_ok),
        'roster_ok':roster_ok,'births_ok':births_ok,'singleton_age_admitted':singleton_ok,
        'gross_area_interval':gross,'usable_area_interval':usable,'impossible_area_interval_order':impossible_area_order,
        'ownership_scope':{1:'self_owned',2:'other_owned_not_equivalent_to_rented'}.get(code(row.get('b7'),[1,2]),'unknown'),
        'interior_levels_category':code(row.get('b4'),range(1,6)),
        'rooms_positive_reports':rooms,'H7_census_observed':None,
        'service_reports':reports,'invalid_type_codes':invalid,
        'inventory_absence_status':'unknown_if_no_positive_report',
        'household_weight':None,'source_year':2012,'proxy_bridge_to2020_validated':False}

def inventory_signature(r):
    """Joint lower-bound report counts, not a physical appliance inventory."""
    def n(fam,types=None):return sum(x['family']==fam and (types is None or x['type_code'] in types) for x in r['service_reports'])
    return {'washer_reports':n('washer'),'independent_dryer_reports':n('drying_service',[2]),
        'combo_service_reports':n('drying_service',[1]),'split_AC_reports':n('cooling_service',[3]),
        'household_central_AC_reports':n('cooling_service',[2]),'building_central_AC_reports':n('cooling_service',[1]),
        'refrigerator_reports':n('refrigerator'),
        'electric_hot_water_reports':sum(x['family']=='hot_water_service' and x['fields']['fuel_code'] in [1,6] for x in r['service_reports'])}
