#!/usr/bin/env python3
"""Apply the bridge to local CHFS data and audit all1000 population slots.

No raw records, donor IDs or donor money/area values leave this process.
The returned in-memory pool is reusable by subsequent local generation code.
"""
import hashlib
import json
import math
from collections import Counter
from pathlib import Path
import pandas as pd
from pandas.io.stata import StataMissingValue
from bridge_rules import derive_members,select_housing,number

HERE=Path(__file__).resolve().parent
PARENT=HERE.parent
SOURCE=PARENT/'chfs_admission_20261003'
PACKAGE=Path('/Users/fanmili/Downloads/2021/CHFS2021年调查数据-stata14版本')
BATCH='CHFS_CENSUS_BRIDGE_20261003_V1'

def sha(p):
    h=hashlib.sha256()
    with p.open('rb') as f:
        for b in iter(lambda:f.read(1024*1024),b''):h.update(b)
    return h.hexdigest()

def write(p,x):
    p.parent.mkdir(parents=True,exist_ok=True)
    p.write_text(json.dumps(x,ensure_ascii=False,indent=2,allow_nan=False)+'\n')

def normalized(v):
    if isinstance(v,StataMissingValue) or v is None or (not isinstance(v,str) and pd.isna(v)):return None
    return v

def read(kind,columns):
    return pd.read_stata(next(PACKAGE.glob(f'chfs2021_{kind}_pub_*.dta')),columns=columns,convert_categoricals=False,convert_missing=True).map(normalized)

def province(s):
    for suffix in ['壮族自治区','回族自治区','维吾尔自治区','自治区','省','市']:s=s.removesuffix(suffix)
    return s

def load_bridge_pool():
    """Return a private in-memory frame of derived source attributes, not roles."""
    hmeta=json.loads((SOURCE/'private_metadata/chfs2021_hh_pub_v0_20260131_metadata.json').read_text())['variable_labels']
    hvars=['hhid','a2000','a1008','c1001','c1002ab','c1004']
    prefixes=['c2000x_','c2000c_','c2003_','c2004_','c2008b_','c2008ba_','c2005aa1_','c2005aa2_']
    hvars +=[k for k in hmeta if any(k.startswith(t) for t in prefixes)]
    hh=read('hh',hvars)
    ind=read('ind',['hhid','pline','a1106','a1108','a2000c','a2001','a2005'])
    master=read('master_hh',['hhid','category','prov','wgt_hh','istracking','interviewtime','total_income','total_consump'])
    assert not hh.hhid.isna().any() and not hh.hhid.duplicated().any()
    assert not master.hhid.isna().any() and not master.hhid.duplicated().any()
    assert not ind[['hhid','pline']].isna().any().any() and not ind.duplicated(['hhid','pline']).any()
    assert set(hh.hhid)==set(master.hhid)==set(ind.hhid)
    combined=master.merge(hh,on='hhid',validate='one_to_one')
    city=combined[combined.category.isin([111,112])]
    members={k:g.drop(columns=['hhid','pline']).to_dict('records') for k,g in ind.groupby('hhid')}
    rows=[]
    for item in city.to_dict('records'):
        visit_year=int(pd.to_datetime(str(item['interviewtime'])).year)
        m=derive_members(members[item['hhid']],visit_year,item['a2000'])
        housing=select_housing(item)
        w=number(item['wgt_hh'])
        finance_known=number(item['total_income']) is not None and number(item['total_consump']) is not None
        record={'_local_hhid':item['hhid'],'province':province(item['prov']),
            'weight':w,'istracking':item['istracking'],'visit_year':visit_year,
            'source_household_a1008':item['a1008'],'finance_derived_totals_present':finance_known,
            **m,**housing}
        record['members_reference_time']='actual_visit_current'
        record['housing_reference_time']='actual_visit_current' if visit_year==2021 else '2021-07-end_recall'
        record['member_housing_same_reference_time']=visit_year==2021
        record['temporal_alignment_status']='same_visit_question_reference' if visit_year==2021 else 'members2022_housingJuly2021_not_synchronous'
        record['size_category']=str(m['co_resident_count']) if m['co_resident_count']<10 else '10+'
        record['generation_category']=str(m['generation_count_proxy']) if m['generation_count_proxy'] is not None and m['generation_count_proxy']<5 else ('5+' if m['generation_count_proxy'] is not None else None)
        record['member_finance_pool']=m['eligible_for_generation_matching'] and w is not None and w>0 and finance_known
        rows.append(record)
    return pd.DataFrame(rows)

def frequencies(values):return {str(k):int(v) for k,v in Counter(values).items()}

def main():
    df=load_bridge_pool()
    assert len(df)==9226
    pool=df.member_finance_pool
    stages={'member_generation_finance':pool,
        'current_dwelling_selected':pool&df.selected,
        'current_area_candidate':pool&df.area_candidate_m2.notna(),
        'area_with_declared_whole_dwelling_scope':pool&df.area_scope_supported,
        'current_H7_proxy':pool&df.room_count_h7_proxy.notna(),
        'area_and_H7_proxy':pool&df.area_scope_supported&df.room_count_h7_proxy.notna(),
        'time_aligned_area_and_H7_proxy':pool&df.area_scope_supported&df.room_count_h7_proxy.notna()&df.member_housing_same_reference_time,
        'first_interview_member_generation_finance':pool&df.istracking.eq(0)}
    authority=json.loads((PARENT/'evidence_contract_20261001/CITY_AUTHORITY_CONSTRAINTS_V2.json').read_text())
    roomrows={r['province']:r for r in authority['complete_province_generation_room_counts']}
    allocpath=PARENT/'evidence_contract_20261001/POPULATION_ALLOCATION_CANDIDATE_V2.json'
    allocation=json.loads(allocpath.read_text());assert len(allocation['slots'])==1000
    lookups={}
    national={}
    for name,mask in stages.items():
        lookup={}
        for key,g in df[mask].groupby(['province','size_category','generation_category']):
            weights=g.weight.to_numpy(dtype=float)
            lookup[key]={'source_count':len(g),'kish_effective_sample_size':round(float(weights.sum()**2/(weights@weights)),6)}
        lookups[name]=lookup
        national[name]={key:len(g) for key,g in df[mask].groupby(['size_category','generation_category'])}
    slots=[]
    for s in allocation['slots']:
        key=(s['province'],s['size_category'],s['generation_category'])
        supports={name:lookup.get(key,{'source_count':0,'kish_effective_sample_size':0.0}) for name,lookup in lookups.items()}
        globalkey=(s['size_category'],s['generation_category'])
        nationwide={name:lookup.get(globalkey,0) for name,lookup in national.items()}
        if supports['time_aligned_area_and_H7_proxy']['source_count']:route='same_province_joint_proxy_time_aligned'
        elif supports['area_and_H7_proxy']['source_count']:route='same_province_joint_proxy_temporal_sensitivity_required'
        elif supports['area_with_declared_whole_dwelling_scope']['source_count']:route='same_province_area_proxy_H7_requires_independent_matching'
        elif supports['member_generation_finance']['source_count']:route='same_province_member_proxy_housing_requires_independent_matching'
        elif nationwide['time_aligned_area_and_H7_proxy']:route='cross_province_joint_proxy_candidate_no_donor_assigned'
        elif nationwide['member_generation_finance']:route='cross_province_member_proxy_candidate_housing_pending'
        else:route='no_source_size_generation_pool_keep_slot_require_other_source_or_explicit_generation'
        r=roomrows[s['province']];gen=4 if s['generation_category']=='5+' else int(s['generation_category'])-1
        roomcounts=r['generation_room_counts'][gen];total=sum(roomcounts)
        conditional={str(i+1) if i<4 else '5+':c/total for i,c in enumerate(roomcounts)} if total else None
        slots.append({'slot_id':s['slot_id'],'province':s['province'],'target_census_size_category':s['size_category'],
            'target_exact_member_count':s['exact_member_count'],'target_census_generation_category':s['generation_category'],
            'source_support_same_province_size_generation':supports,
            'source_support_nationwide_same_size_generation_counts':nationwide,
            'source_route_candidate':route,
            'cross_province_transport_executed':False,
            'conditional_census_H7_distribution_if_ordinary_dwelling':conditional,
            'H7_population_scope':'ordinary city family households only; not assigned to this all-family slot',
            'residence_match_evidence':'CHFS co-residence proxy; exact census membership not observed',
            'matching_status':'same_province_size_generation_proxy_pool_exists' if supports['member_generation_finance']['source_count'] else 'source_gap_keep_target_slot',
            'source_record_assigned':False,'complete_role':False})
    summaries={}
    for name,mask in stages.items():
        counts=[s['source_support_same_province_size_generation'][name]['source_count'] for s in slots]
        empty=[s for s,c in zip(slots,counts) if not c]
        summaries[name]={'source_records':int(mask.sum()),'target_slots_with_source':sum(c>0 for c in counts),
            'target_slots_without_source':sum(c==0 for c in counts),'target_slots_source_count_under5':sum(c<5 for c in counts),
            'unsupported_province_counts':frequencies(s['province'] for s in empty),
            'under5_is_diagnostic_not_release_threshold':True}
    qc={'batch_id':BATCH,'source_city_classified_records':len(df),
        'residence':{'economic_vs_coresident_counts_differ_records':int(df.economic_member_count.ne(df.co_resident_count).sum()),
            'residence_complete_records':int(df.residence_complete.sum()),'reported_economic_roster_mismatch_records':int((~df.reported_roster_consistent_or_unasked).sum()),
            'respondent_not_exactly_one_records':int(df.respondent_count.ne(1).sum()),'active_member_conflict_records':int(df.active_member_conflict.sum()),
            'singleton_age_gate_counts':frequencies(df.single_age_gate),'census_exact_resident_counts_available':0},
        'generation':{'proxy_distribution_all_city':frequencies(df.generation_count_proxy.where(df.generation_count_proxy.notna(),'unknown')),
            'unknown_relationships_records':int(df.unknown_relationship_count.gt(0).sum()),
            'noncontiguous_occupied_generations_records':int(df.generation_has_unoccupied_intermediate_level.sum()),
            'rule':'count occupied distinct relation-generation levels, not max-min+1; singleton always one generation',
            'complete_family_graphs_observed':0},
        'housing':{'tenure_codes':frequencies(df.tenure_code.where(df.tenure_code.notna(),'unknown')),
            'selection_status_counts':frequencies(df.dwelling_selection_status),'area_origin_counts':frequencies(df.area_origin),
            'area_sharing_scope_counts':frequencies(df.sharing_scope),'area_candidate_records':int(df.area_candidate_m2.notna().sum()),
            'area_whole_scope_supported_records':int(df.area_scope_supported.sum()),
            'branch_overlap_records':int(df.branch_overlap.sum()),
            'current_owned_selected_slot_counts':frequencies(df.loc[df.tenure_code.eq(1)&df.selected,'current_dwelling_slot']),
            'area_field_invalid_records':int(df.area_invalid_fields.map(bool).sum()),
            'recorded_usable_consistent_with_auto0_7_records':int(df.consistent_with_source_auto0_7.sum()),
            'recorded_usable_larger_than_building_records':int(df.usable_larger_than_building.sum()),
            'room_proxy_supported_records':int(df.room_count_h7_proxy.notna().sum()),
            'room_bridge_status_counts':frequencies(df.room_bridge_status),
            'H7_exact_observed_records':0,'ordinary_dwelling_classification_observed_records':0,'physical_layout_ready_records':0},
        'temporal_alignment':{'status_counts':frequencies(df.temporal_alignment_status),
            'rule':'2022 co-residence is current at visit; housing selected by question refers toJuly2021; do not call source combination contemporaneously observed',
            'time_aligned_member_area_room_proxy_source_records':int(stages['time_aligned_area_and_H7_proxy'].sum()),
            'same_visit_reference_still_not_census_exact_members_or_H7':True},
        'route_candidate_counts':frequencies(s['source_route_candidate'] for s in slots),
        'stage_support':summaries,'strict_census_usual_residence_equivalence_claimed':False,
        'raw_records_exported':0,'source_ids_exported':0,'new_complete_roles':0,'collection_release':False,'training_release':False,
        'code_sha256':{p.name:sha(p) for p in [HERE/'bridge_rules.py',Path(__file__)]}}
    write(HERE/'BRIDGE_QC.json',qc)
    write(HERE/'SLOT_BRIDGE_AUDIT.json',{'batch_id':BATCH,'allocation_sha256':sha(allocpath),'slots':slots,
        'source_selection_contract':'no target margin changes, no cross-province silent fallback, no actual donor IDs or area/money exported',
        'joint_interpretation':'province x co-residence-proxy size x occupied generation; not exact census household reconstruction',
        'collection_release':False,'training_release':False})
    print(json.dumps({'residence':qc['residence'],'generation':qc['generation'],'housing':qc['housing'],'stage_support':summaries},ensure_ascii=False,indent=2))

if __name__=='__main__':main()
