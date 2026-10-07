#!/usr/bin/env python3
"""Compare target slots to same-province/size CRECS2012 source support.

This diagnoses availability, never equates source frequency with target
frequency. Generation, city coding, period transport and model support remain
unresolved. No automatic cross-province donor fallback is performed.
"""
import hashlib
import json
from pathlib import Path
import pandas as pd

HERE=Path(__file__).resolve().parent
def read(p):return json.loads(p.read_text())
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def decode(t):
    if not isinstance(t,str):return t
    try:return t.encode('latin1').decode('gb18030')
    except UnicodeError:return t
def main():
    allocation=HERE.parent/'evidence_contract_20261001/POPULATION_ALLOCATION_CANDIDATE_V2.json'
    a=read(allocation)
    d=pd.read_stata(HERE/'private_raw/CRECS2012.dta',convert_categoricals=False)
    c=d[(d.valid==1)&(d.b1==1)].copy()
    r=c[[f'a2_{i}_a' for i in range(1,9)]].isin(range(1,12)).sum(axis=1)
    good=c.a1.isin(range(1,9))&(r==c.a1)&c.b13.isin(range(1,11))&c.b14.isin(range(1,11))&c.f1a.isin(range(1,19))
    c['province_normalized']=c.province.map(decode).replace({'宁夏回族自治区':'宁夏'})
    assert set(c.province_normalized)<=set(a['province_order'])
    cells=[]
    for p in a['province_order']:
        for s in ['1','2','3','4','5','6','7','8','9','10+']:
            slots=[v for v in a['slots'] if v['province']==p and v['size_category']==s]
            mask=(c.province_normalized==p)&(c.a1==int(s) if s!='10+' else c.a1>=10)
            cells.append({'province':p,'size_category':s,'target_slots':len(slots),
                'city_label_source_records':int(mask.sum()),
                'roster_size_area_income_consistent_records':int((mask&good).sum()),
                'generation_specific_support':'not assessed; cannot assume supported',
                'automatic_fallback_performed':False})
    assert sum(x['target_slots'] for x in cells)==1000
    no_prov=[p for p in a['province_order'] if not (c.province_normalized==p).any()]
    out={'batch_id':'CRECS_CITY_SOURCE_SUPPORT_20261003_V1',
         'allocation_sha256':sha(allocation),'source_dta_sha256':sha(HERE/'private_raw/CRECS2012.dta'),
         'source_reference_year':2012,'target_reference_year':2020,
         'comparison':'same-province/size support in unweighted city-labeled sample; not census-city equivalence or model feasibility',
         'source_city_rows':len(c),'consistent_joint_source_rows':int(good.sum()),
         'target_slots':1000,'cells':cells,
         'gaps':{'target_slots_without_any_same_province_size_city_source':sum(x['target_slots'] for x in cells if not x['city_label_source_records']),
                 'target_slots_without_consistent_same_province_size_joint_source':sum(x['target_slots'] for x in cells if not x['roster_size_area_income_consistent_records']),
                 'provinces_without_city_labeled_source':no_prov,
                 'target_slots_in_provinces_without_city_labeled_source':sum(v['province'] in no_prov for v in a['slots']),
                 'target_slots_with_fewer_than5_consistent_records':sum(x['target_slots'] for x in cells if x['roster_size_area_income_consistent_records']<5)},
         'minimum5_rule':'diagnostic small-pool flag only; not a statistical representativeness or release threshold',
         'profiles_generated':0,'collection_release':False,'code_sha256':sha(Path(__file__))}
    with (HERE/'SUPPORT_GAP_MATRIX.json').open('x') as f:json.dump(out,f,ensure_ascii=False,indent=2);f.write('\n')
    print(json.dumps(out['gaps'],ensure_ascii=False))

if __name__=='__main__':main()
