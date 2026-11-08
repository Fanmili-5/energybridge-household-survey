"""Harmonize existing survey records; preserve source facts and unknowns."""
from copy import deepcopy
from collections import Counter
import json,math,sys
from numbers import Real
import pyreadstat
from common import *


def enable_rows(components):
    path=V4/'inputs/enable.sav';data,meta=pyreadstat.read_sav(path,output_format='dict')
    labels=meta.variable_value_labels;out={'ES':[],'GB':[]};mapping={'Spain':'ES','United Kingdom':'GB'}
    for values in zip(*data.values()):
        x={k:None if isinstance(v,Real) and not math.isfinite(v) else v for k,v in zip(data,values)};country=mapping.get(labels['Country'].get(x['Country']))
        if country is None:continue
        groupfields=[f'S1{s}c{a}' for s in 'AB' for a in (1,2,3)]
        counts=[x[f] for f in groupfields]
        if x['H1'] not in (1,2,3,4) or x['H3'] not in (1,2,3,4,5,6) or x['H11C'] not in (1,2,4):continue
        if not all(v is not None and v>=0 and v==int(v) for v in counts) or not 1<=sum(counts)<=8 or counts[1]+counts[4]<1:continue
        row=components.seed.src.ref('ENABLE_EU',str(x['UID']),country,fact(int(sum(counts)),groupfields,'derived'),
             fact(labels['H1'][x['H1']],['H1'],code=int(x['H1'])),
             fact(labels['H3'][x['H3']],['H3'],measure='dwelling_area_band',code=int(x['H3'])),
             fact(True,['H11C'],code=int(x['H11C'])),anchors={})
        for key,field in [('dishwasher_available','H11B'),('space_ac_available','H11E')]:
            row['devices'][key]=fact(x[field] in (1,2,4),[field]) if x[field] in (1,2,4,5) else fact(None,[field],'unknown')
        if x['H11G'] in (1,2,4):row['devices']['water_heater_available']=fact(True,['H11G'],appliance_type='standalone_electric_boiler')
        row['members_summary']=fact([dict(label=('Men' if f[2]=='A' else 'Women')+'_'+str(i%3),**fact(int(v),[f])) for i,(f,v) in enumerate(zip(groupfields,counts))],groupfields,'derived',scope='original_sex_and_age_bins')
        row['known_presence']=fact({'source_home_presence_item':int(x['C4G'])},['C4G']) if x['C4G'] in (1,2,3,4,5) else fact(None,['C4G'],'unknown')
        row['geography']=fact(country,['Country'],'derived',scope='survey_country')
        row['additional_devices']={'fridge_available':fact(x['H11A'] in (1,2,4),['H11A']) if x['H11A'] in (1,2,4,5) else fact(None,['H11A'],'unknown')}
        row['source'].update(survey_year=None,survey_reference_year=None,release='Zenodo1.0,2019-10-31',release_year=2019,fieldwork_year=None,survey_year_semantics='release year does not establish fieldwork year')
        components.sources.enrich(row)
        sex={1:'male',2:'female'}.get(x['S5']);birth=int(x['S4']) if x['S4'] is not None and x['S4']!=9999 and 1900<=x['S4']<=2019 else None
        row['respondent_demographics']={'sex':fact(sex,['S5'],'observed' if sex else 'unknown'),'birth_year':fact(birth,['S4'],'observed' if birth else 'unknown')}
        row['block']=[country,row['dwelling']['observed_type']['value'],int(sum(counts)),int(x['H3'])]
        row['source_file_sha256']=sha(path)
        out[country].append(row)
    return out


def china_rows():
    path=ROOT/'inputs/CRECS2012.dta';data,meta=pyreadstat.read_dta(path,output_format='dict');out=[]
    area={1:(0,12),2:(12,30),3:(30,50),4:(50,70),5:(70,90),6:(90,120),7:(120,150),8:(150,180),9:(180,250),10:(250,None)}
    for vals in zip(*data.values()):
        x={k:None if isinstance(v,Real) and not math.isfinite(v) else v for k,v in zip(data,vals)};n=x['a1']
        if x['valid']!=1 or x['b1']!=1 or n is None or n!=int(n) or not 1<=n<=8 or x['b2'] not in range(1,6) or x['b13'] not in range(1,11):continue
        roster=[];details={};okay=True
        for i in range(1,9):
            if x[f'a2_{i}_a'] is None:continue
            y=x[f'a2_{i}_c'];job=x[f'a2_{i}_d'];person=f"{int(x['index'])}:{i}"
            if y is None or y!=int(y) or not 1900<=y<=2012:okay=False;break
            band=[max(0,2011-int(y)),2012-int(y)]
            if band[0]<18<=band[1] or band[1]>105:okay=False;break
            work={1:'employed_full_time',2:'employed_part_time',3:'not_employed',4:'retired'}.get(job)
            roster.append({'person_key':person,'birth_year':fact(int(y),[f'a2_{i}_c']),
                           'age_band':fact(band,[f'a2_{i}_c'],'derived',reference_year=2012),
                           'relationship_to_head':fact(int(x[f'a2_{i}_a']),[f'a2_{i}_a']),
                           'sex_code':fact(int(x[f'a2_{i}_b']),[f'a2_{i}_b']) if x[f'a2_{i}_b'] in (1,2) else fact(None,[f'a2_{i}_b'],'unknown')})
            details[person]={'employment':fact(work,[f'a2_{i}_d'],'observed' if work else 'unknown'),
                             'school_enrollment':fact(None,[],'unknown'),'nursery_hours':fact(None,[],'unknown'),
                             'work_hours_last_week':fact(None,[],'unknown'),'commute_hours_roundtrip':fact(None,[],'unknown'),'commute_minutes_roundtrip':fact(None,[],'unknown')}
        if not okay or len(roster)!=n or not any(r['age_band']['value'][0]>=18 for r in roster):continue
        washers=[i for i in (1,2,3) if x[f'c3_{i}b'] in (1,2,3)]
        ac=[i for i in range(1,6) if x[f'd6_{i}a'] in (2,3)]
        if not washers or not ac:continue
        devices={k:fact(None,[],'unknown') for k in KEY.values()}
        devices['washer_available']=fact(True,[f'c3_{i}b' for i in washers],reported_instances=len(washers))
        dry=[i for i in (1,2,3) if x[f'c4_{i}b'] in (1,2) or x[f'c4_{i}a'] is not None and x[f'c4_{i}a'] in range(1,12)]
        if dry:devices['dryer_available']=fact(True,[f'c4_{i}b' if x[f'c4_{i}b'] in (1,2) else f'c4_{i}a' for i in dry],reported_instances=len(dry))
        combos=[i for i in dry if x[f'c4_{i}b']==1]
        if combos:
            i=combos[0];asset=f"CRECS2012:{int(x['index'])}:washer_dryer:{i}"
            for f in ('washer_available','dryer_available'):
                devices[f]['appliance_key']=asset;devices[f]['appliance_type']='source_washer_dryer_combo'
                devices[f]['source_asset_selection']='reported combo selected for both reference services; no link to a particular C3 washer slot asserted; other source units remain background'
            devices['washer_available']['fields'].append(f'c4_{i}b')
        devices['space_ac_available']=fact(True,[f'd6_{i}a' for i in ac],appliance_type='private_reference_space_ac',source_types=[int(x[f'd6_{i}a']) for i in ac])
        heaters=[i for i in range(1,6) if x[f'd4_{i}a'] in (1,2,3)]
        if heaters:
            i=min(heaters,key=lambda i:(not(x[f'd4_{i}a']==1 and x[f'd4_{i}b']==1),i));fuel=x[f'd4_{i}b'];typ=x[f'd4_{i}a']
            carrier='electricity' if fuel==1 else 'non_electric' if fuel in (2,3,4,5) else 'unknown'
            devices['water_heater_available']=fact(True,[f'd4_{i}a',f'd4_{i}b'],energy_carrier=carrier,
                appliance_type='source_electric_storage_water_heater' if typ==1 and fuel==1 else 'instantaneous_electric_shower' if typ==2 and fuel==1 else 'source_water_heater_unspecified_storage_or_fuel',source_type=int(typ),source_fuel=int(fuel) if fuel else None)
        lo,hi=area[int(x['b13'])];ident=str(int(x['index']))
        row={'source':{'dataset':'CRECS2012','household_key':ident,'country':'CN','survey_year':2012,'survey_reference_year':2012,'fieldwork_year':2012,'release':'project supplied frozen CRECS2012','survey_year_semantics':'2012 historical survey household; no automatic aging to current year'},
             'household_size':fact(int(n),['a1']),'dwelling':{'observed_type':fact(None,[],'unknown'),
             'reference_type':fact('reference_apartment',['b2'],'benchmark_assigned',reason='urban multi-storey apartment reference; height band is not an observed morphology'),
             'size':fact({'lower_m2':lo,'upper_m2':hi,'lower_inclusive':lo==0},['b13'],code=int(x['b13']),measure='crecs_gross_floor_area_band'),
             'source_building_height_band':fact(int(x['b2']),['b2'])},'devices':devices,
             'members_summary':fact(roster,[f'a2_{i}_{s}' for i in range(1,9) for s in 'abcd'],'derived',scope='crecs_birth_year_roster'),
             'source_member_details':details,'source_person':{'age':fact(None,[],'unknown'),'employment':details[roster[0]['person_key']]['employment'],
              'source_person':roster[0]['person_key'],'teleworking_household':fact(None,[],'unknown'),'charger_type':fact(None,[],'unknown')},
             'known_presence':fact({'normally_someone_home_all_day':x['a3']==1},['a3']) if x['a3'] in (1,2) else fact(None,['a3'],'unknown'),
             'geography':fact('China urban survey households',['b1'],'derived',scope='survey urban category'),
             'additional_devices':{'fridge_available':fact(None,[],'unknown')},'anchors':{},
             'block':['CN','reference_apartment',int(n),int(x['b13'])],'source_file_sha256':sha(path)}
        out.append(row)
    return out




