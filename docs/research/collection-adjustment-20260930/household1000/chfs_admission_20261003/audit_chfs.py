#!/usr/bin/env python3
"""Read local licensed CHFS files and export aggregate source diagnostics only.

The category filter describes the published regional classification; whether
it is updated after migration is not established by the supplied documentation.
CHFS economic membership and its three-month co-residence rule are not silently
substituted for census usual residence. No microdata donor profiles are exported.
"""
from pathlib import Path
import json
import numpy as np
import pandas as pd
from pandas.io.stata import StataMissingValue
from inspect_package import HERE, PACKAGE, sha, write

DATA=PACKAGE/'CHFS2021年调查数据-stata14版本'

def read(kind,columns=None):
    path=next(DATA.glob(f'chfs2021_{kind}_pub_*.dta'))
    return pd.read_stata(path,columns=columns,convert_categoricals=False,convert_missing=True)

def num(s):
    return pd.to_numeric(s.map(lambda x: np.nan if isinstance(x,StataMissingValue) else x),errors='coerce')

def counts(s):
    return {str(k):int(v) for k,v in s.value_counts(dropna=False).items()}

def missing(s):
    return counts(s[s.map(lambda x:isinstance(x,StataMissingValue))].map(str))

def normal_prov(s):
    for suffix in ['壮族自治区','回族自治区','维吾尔自治区','自治区','省','市']:
        s=s.removesuffix(suffix)
    return s

def weighted_summary(s,w):
    good=s.notna() & w.gt(0) & np.isfinite(w)
    x=s[good].to_numpy(dtype=float);v=w[good].to_numpy(dtype=float)
    order=np.argsort(x,kind='stable');x=x[order];v=v[order]
    c=np.cumsum(v)/v.sum()
    return {'valid_n':int(good.sum()),'missing_n':int((~good).sum()),
            'negative_n':int((s[good]<0).sum()),'zero_n':int((s[good]==0).sum()),
            'weighted_mean_yuan_per_household_year':float(np.dot(x,v)/v.sum()),
            'weighted_quantiles_yuan_per_household_year':{str(q):float(x[min(np.searchsorted(c,q),len(x)-1)]) for q in [.25,.5,.75]},
            'quantile_method':'left-continuous weighted empirical CDF, household weights; no interpolation',
            'not_a_new_city_population_target':True}

def main():
    master=read('master_hh')
    hhvars=['hhid','a2000','a1008','c1001','c1004','c1000ak','c1011','c1013a','c7002',
            'c8001ab_2_mc','c8001ab_5_mc','c8001ab_19_mc','g1005']
    hhmeta=json.loads((HERE/'private_metadata/chfs2021_hh_pub_v0_20260131_metadata.json').read_text())
    indmeta=json.loads((HERE/'private_metadata/chfs2021_ind_pub_v0_20260131_metadata.json').read_text())
    mastermeta=json.loads((HERE/'private_metadata/chfs2021_master_hh_pub_v0_20260131_metadata.json').read_text())
    mindmeta=json.loads((HERE/'private_metadata/chfs2021_master_ind_pub_v0_20260131_metadata.json').read_text())
    hhvars += [k for k in hhmeta['variable_labels'] if k.startswith(('c2000c_','c2003_','c2004_','c2005aa1_','c2005aa2_','c2008b_'))]
    hh=read('hh',hhvars)
    ind=read('ind',['hhid','pline','a2000c','a2001','a2003','a2005','a2024','a3100a','a3116a','a3133','a3134'])
    mind=read('master_ind',['hhid','pline','pline_order','hhead','wgt_ind'])
    keycheck={'master_hh_duplicate_hhid':int(master.hhid.duplicated().sum()),
              'hh_duplicate_hhid':int(hh.hhid.duplicated().sum()),
              'ind_duplicate_hhid_pline':int(ind.duplicated(['hhid','pline']).sum()),
              'master_ind_duplicate_hhid_pline':int(mind.duplicated(['hhid','pline']).sum()),
              'hh_master_hh_key_symmetric_difference':len(set(hh.hhid)^set(master.hhid)),
              'ind_master_ind_key_symmetric_difference':len(set(map(tuple,ind[['hhid','pline']].to_numpy()))^set(map(tuple,mind[['hhid','pline']].to_numpy()))),
              'ind_households_without_master_hh':len(set(ind.hhid)-set(master.hhid))}
    for name,frame,keys in [('master_hh',master,['hhid']),('hh',hh,['hhid']),('ind',ind,['hhid','pline']),('master_ind',mind,['hhid','pline'])]:
        keycheck[f'{name}_missing_key_rows']=int(frame[keys].map(lambda x:isinstance(x,StataMissingValue) or pd.isna(x)).any(axis=1).sum())
    assert all(v==0 for v in keycheck.values()),keycheck
    df=master.merge(hh,on='hhid',validate='one_to_one').set_index('hhid')
    city=num(df.category).isin([111,112])
    towns=num(df.category).isin([121,122,123])
    rural=num(df.category).isin([210,220])
    w=num(df.wgt_hh)
    # Only publish years, never interview timestamps.
    visit=pd.to_datetime(df.interviewtime.astype(str),errors='coerce',format='mixed').dt.year
    ind=ind.merge(visit.rename('visit_year'),left_on='hhid',right_index=True,validate='many_to_one')
    for c in ['a2000c','a2001','a2005']:ind[c]=num(ind[c])
    ind['birth_valid']=ind.a2005.ge(1900)&ind.a2005.le(ind.visit_year)
    co=ind[ind.a2000c.isin([1,2])].copy()
    co['age_year_difference']=co.visit_year-co.a2005
    groups=co.groupby('hhid')
    df['coresident_count']=groups.size().reindex(df.index,fill_value=0)
    df['roster_count']=ind.groupby('hhid').size().reindex(df.index,fill_value=0)
    df['all_coresident_birth_known']=groups.birth_valid.all().reindex(df.index,fill_value=False)
    df['all_members_residence_known']=ind.groupby('hhid').a2000c.apply(lambda x:x.isin([1,2,3,4]).all()).reindex(df.index,fill_value=False)
    df['singleton_age']=groups.age_year_difference.first().where(df.coresident_count.eq(1))
    df['all_coresident_relationship_known']=groups.a2001.apply(lambda x:x.isin([1,2,3,4,5,6,7,8,9,10]).all()).reindex(df.index,fill_value=False)
    df['size_category']=df.coresident_count.map(lambda n:str(n) if n<10 else '10+')
    df['province_normalized']=df.prov.astype(str).map(normal_prov)
    base=city&w.gt(0)&np.isfinite(w)&df.all_members_residence_known&df.coresident_count.gt(0)
    under20=base&df.coresident_count.eq(1)&df.singleton_age.lt(20)
    age_unknown_single=base&df.coresident_count.eq(1)&~df.all_coresident_birth_known
    eligible=base&~under20&~age_unknown_single
    # This is a documented age/member/financial completeness gate, not simulation.
    joint=eligible&df.all_coresident_birth_known&df.all_coresident_relationship_known&num(df.total_income).notna()&num(df.total_consump).notna()
    def pool(mask):
        return [{'province':str(p),'size_category':str(n),'source_records':int(v)} for (p,n),v in
                df[mask].groupby(['province_normalized','size_category']).size().items()]
    citydf=df[city]
    incsum=sum(num(df[c]) for c in ['hhwage_inc','agri_inc','busi_inc','prop_inc','transfer_inc'])
    consumpsum=sum(num(df[c]) for c in ['food_con','clothing_con','resident_con','equipment_con','travel_con','educ_con','other_con','medical_con'])
    closure={}
    for label,total,parts in [('income','total_income',incsum),('consumption','total_consump',consumpsum)]:
        delta=(num(df[total])-parts).abs()
        tolerance=1e-5*num(df[total]).abs().clip(lower=1)
        closure[label]={'city_complete_component_n':int((city&parts.notna()).sum()),
                        'city_residual_exceeding_relative_1e_5_n':int((city&delta.gt(tolerance)).sum()),
                        'city_max_absolute_residual_yuan':float(delta[city].max()),
                        'tolerance_rule':'1e-5 * max(abs(total),1); float32 accumulation diagnostic, not external validity'}
    out={'batch_id':'CHFS_ADMISSION_20261003_V1','rows':{'hh':len(hh),'ind':len(ind),'master_hh':len(master),'master_ind':len(mind)},
         'variables':{'hh':len(hhmeta['variable_labels']),'ind':len(indmeta['variable_labels']),
                      'master_hh':len(mastermeta['variable_labels']),'master_ind':len(mindmeta['variable_labels'])},
         'documentation_discrepancy':{'handbook_individuals':68387,'actual_ind_and_master_ind_individuals':len(ind),
                                     'difference_from_handbook':68387-len(ind),'status':'unresolved; do not fabricate missing members or claim version cause'},
         'key_checks':keycheck,'scope':{'filter':'category in [111,112]','interpretation':'published regional city classification; category migration-update mechanism and current residence not independently verified',
         'city_records':int(city.sum()),'town_records':int(towns.sum()),'rural_records':int(rural.sum()),'unclassified_records':int((~(city|towns|rural)).sum()),
         'category_counts_all':counts(num(df.category)),'category_counts_city':counts(num(citydf.category)),
         'city_rural_zero_disagreement':int((city&~num(df.rural).eq(0)).sum()),
         'city_records_with_istowns_one':int((city&num(df.istowns).eq(1)).sum()),
         'city_province_counts':counts(citydf.province_normalized),'province_count_all':df.province_normalized.nunique(),'province_count_city':citydf.province_normalized.nunique(),
         'not_same_as_city_level_or_nonagricultural_hukou':True},
         'visit_year_counts_all':counts(visit),'visit_year_counts_city':counts(visit[city]),'visit_year_parse_missing':int(visit.isna().sum()),
         'weight':{'actual_field':'wgt_hh','label':'wgt_hhadj 家庭权重_城乡调整','handbook_pages_1based':[15,16],
                  'city_positive_finite_n':int((city&w.gt(0)&np.isfinite(w)).sum()),'city_nonpositive_or_missing_n':int((city&~(w.gt(0)&np.isfinite(w))).sum()),
                  'city_kish_effective_sample_size':float(w[city].sum()**2/np.dot(w[city],w[city])),
                  'kish_scope':'unequal-weight diagnostic only; ignores PPS clustering and stratification',
                  'not_rescaled_to_census_total':True,'individual_weights_not_used':True},
         'member_semantics':{'economic_family_count_field':'a2000; new interviews only, not census household size',
              'coresidence_field':'a2000c in [1,2]; temporary absence <=3 months counted; not census 6-month usual residence',
              'city_roster_member_count_distribution':counts(citydf.roster_count),
              'city_coresident_count_distribution':counts(citydf.coresident_count),
              'city_zero_coresidents':int((city&df.coresident_count.eq(0)).sum()),
              'city_unknown_residence_any_member':int((city&~df.all_members_residence_known).sum()),
              'city_households_with_noncoresident_economic_members':int((city&df.roster_count.gt(df.coresident_count)).sum()),
              'city_coresident_birth_any_unknown':int((city&~df.all_coresident_birth_known).sum()),
              'under20_singletons_removed':int(under20.sum()),'unknown_age_singletons_quarantined':int(age_unknown_single.sum()),
              'eligible_source_rule_n':int(eligible.sum()),'joint_member_income_consump_rule_n':int(joint.sum()),
              'joint_rule':'eligible + all co-resident birth years valid + relationship codes 1..10 + income and consumption nonmissing',
              'not_generation_or_census_membership_validation':True},
         'finance':{c:weighted_summary(num(citydf[c]),num(citydf.wgt_hh)) for c in ['total_income','total_consump']},
         'finance_provenance':{'status':'source-derived aggregates; may include source-imputed, censored and administratively substituted components',
             'income_reference':'2020 for verified annual questions; not all inputs independently time-audited',
             'consumption_reference':'source annualized aggregate: main annual flows refer to2020, rent component c1011_imp*12 uses current/July2021 monthly rent',
             'cannot_label_entire_consumption_as_pure_2020_recall':True,
             'members_reference':'current roster at 2021/2022 visit; not reconstructed 2020 residents',
             'finance_population':'all9226 city-classified economic families, including six under20 co-resident singletons excluded from slot-support cohort',
             'census_cohort_income_transport_not_done':True,'component_imputation_rate_not_yet_audited':True},
         'finance_component_closure':closure,
         'selected_missing_reason_counts_city':{c:missing(citydf[c]) for c in ['total_income','total_consump','c1001','c1004','c1011','g1005','c7002']},
         'housing':{'tenure_codes_city':counts(num(citydf.c1001)),
              'nonowned_usable_area_reported_n':int((num(citydf.c1001).isin([2,3])&num(citydf.c1004).gt(0)).sum()),
              'scope_note':'c1004 nonowned usable/exclusively occupied area; owned property slots need explicit current dwelling selection; H7 not mapped'},
         'device_scope':'C8001ab categories combine multiple appliance types; neither ownership per appliance nor counts identified',
         'raw_rows_exported':0,'new_roles_generated':0,'collection_release':False,'training_release':False,'script_sha256':sha(Path(__file__))}
    write(HERE/'CHFS_SOURCE_QC.json',out)
    write(HERE/'private_metadata/city_support_aggregates.json',{'eligible':pool(eligible),'joint':pool(joint)})
    allocation=json.loads((HERE.parent/'evidence_contract_20261001/POPULATION_ALLOCATION_CANDIDATE_V2.json').read_text())
    comparison={}
    for name,mask in [('eligible',eligible),('joint',joint)]:
        lookup={(r['province'],r['size_category']):r['source_records'] for r in pool(mask)}
        slotcounts=[lookup.get((s['province'],s['size_category']),0) for s in allocation['slots']]
        comparison[name]={'target_slots':len(slotcounts),'without_same_province_size_source':sum(n==0 for n in slotcounts),
                          'with_fewer_than_5_source_records':sum(n<5 for n in slotcounts),
                          'scope':'province x CHFS derived co-resident size only; generation/housing/source-current-residence not validated',
                          'fewer_than_5_is_descriptive_not_release_threshold':True}
        unsupported=[s for s in allocation['slots'] if not lookup.get((s['province'],s['size_category']),0)]
        comparison[name]['unsupported_target_province_counts']=counts(pd.Series([s['province'] for s in unsupported]))
        comparison[name]['unsupported_target_size_counts']=counts(pd.Series([s['size_category'] for s in unsupported]))
    new_only=eligible&num(df.istracking).eq(0)
    newlookup={(r['province'],r['size_category']):r['source_records'] for r in pool(new_only)}
    out['geography_sensitivity']={'new_interview_city_eligible_n':int(new_only.sum()),
        'new_interview_without_same_province_size_source_slots':sum(not newlookup.get((s['province'],s['size_category']),0) for s in allocation['slots']),
        'rule':'istracking==0; handbook says first-interview sampling address equals usual address',
        'not_selected_as_new_population_filter':True,
        'category_update_mechanism_still_not_documented':True}
    # Write the added sensitivity after the allocation diagnostics are calculated.
    write(HERE/'CHFS_SOURCE_QC.json',out)
    write(HERE/'SUPPORT_GAP_COMPARISON.json',{'batch_id':out['batch_id'],'allocation_sha256':sha(HERE.parent/'evidence_contract_20261001/POPULATION_ALLOCATION_CANDIDATE_V2.json'),
          'CHFS2021':comparison,'CRECS2012_previous_joint_without_same_province_size_source':302,
          'size_bridging_assumption_required':True,'cannot_claim_gap_resolved_from_this_table':True})
    print(json.dumps({k:out[k] for k in ['rows','key_checks','scope','visit_year_counts_all','weight','member_semantics','finance','housing']},ensure_ascii=False,indent=2))
    print(json.dumps(comparison,ensure_ascii=False,indent=2))

if __name__=='__main__':main()
