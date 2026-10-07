#!/usr/bin/env python3
"""Audit city-only aggregate targets. Generates no household/A/B/model."""
import collections as C,hashlib,importlib.util,json
from pathlib import Path

HERE=Path(__file__).resolve().parent;ROOT=HERE.parent
REPO=next(p for p in HERE.parents if p.name=='energybridge-household-survey')
BASE=REPO/'docs/research/long-horizon-plan/execution/prelaunch_rigor_20260924'
def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def read(p):return json.loads(Path(p).read_text())
def quota(weights,n):
    total=sum(weights);parts=[divmod(w*n,total) for w in weights];out=[a for a,b in parts]
    for i in sorted(range(len(weights)),key=lambda i:(-parts[i][1],-weights[i],i))[:n-sum(out)]:out[i]+=1
    return out
def cell(p):return str(p['family_size'])+'x'+str(p['generation_design'])

def main():
    lock=read(ROOT/'INPUT_LOCK.json')
    for k in ['structure_code','structure_json','single_age_json','province_reference']:
        assert sha(lock['files'][k]['path'])==lock['files'][k]['sha256']
    spec=importlib.util.spec_from_file_location('city_structure_audit',BASE/'build_city_structure_candidate.py');module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    module.N=1000;structure=module.build();target=C.Counter(str(p['size_category'])+'x'+str(p['generation_category']) for p in structure['families'])
    province=read(BASE/'city_provinces_300_candidate.json')['province_distribution']
    pq=quota([p['eligible_city_family_households'] for p in province],1000);provtarget={p['province']:q for p,q in zip(province,pq)}
    old=[read(p) for p in sorted((ROOT/'round2/boundary_v7/mapped_old300').glob('*.json'))]
    new=[]
    for path in sorted((ROOT/'candidate_v2/roles').glob('*.json')):
        if int(path.stem.split('-')[1])<=300:continue
        p=read(path)['profile'];new.append({'family_size':p['family_size'],'generation_design':p['generation_category'],'province':p['province']})
    current=old+new;actual=C.Counter(cell(p) for p in current);provcurr=C.Counter(p['province'] for p in current)
    assert len(old)==300 and len(new)==700 and sum(target.values())==1000 and sum(provtarget.values())==1000
    rows=[{'size_generation':k,'joint_target_1000':target[k],'prior300plus700':actual[k],'residual':actual[k]-target[k]} for k in sorted(set(target)|set(actual))]
    oldcell=C.Counter(cell(p) for p in old);oldprovince=C.Counter(p['province'] for p in old)
    conflicts=[{'cell':k,'old300':v,'direct_rounding_target1000':target[k]} for k,v in oldcell.items() if v>target[k]]
    size=C.Counter();gen=C.Counter()
    for p in structure['families']:size[str(p['size_category'])]+=1;gen[str(p['generation_category'])]+=1
    result={'batch_id':'CITY_TARGET_AUDIT_20261001_V1','scope':'China census city family households only; excludes town/rural/collective',
        'eligibility':'preserves current exclusion of under20 one-person households; this is not all city households',
        'target_reference_date':'2020-11-01','total_city_households':structure['census_city_total'],
        'eligible_city_households':structure['adjusted_denominator'],'n':1000,'joint_size_generation':rows,
        'structure_cell_L1_count_residual':sum(abs(r['residual']) for r in rows),'structure_one_person_target':size['1'],
        'size_quotas':dict(size),'generation_quotas':dict(gen),
        'province_quotas':[{**p,'quota_1000':q,'prior300plus700':provcurr[p['province']],
            'residual':provcurr[p['province']]-q,'old300':oldprovince[p['province']]} for p,q in zip(province,pq)],
        'province_L1_count_residual':sum(abs(provcurr[p]-q) for p,q in provtarget.items()),
        'old300_cells_exceeding_direct_rounding':conflicts,
        'retention_note':'a rounding conflict does not prove old roles impossible; joint integer allocation can explicitly constrain retention and report cost',
        '2025_mean_2_52_applicable_to_city_only':False,'2025_urban_population_67_74_is_city_household_share':False,
        'national_scope_preparation_withdrawn':'../national_representativeness_20261001/DO_NOT_USE.md',
        'generated_profiles':0,'annual_A':0,'B':0,'physics':0,'collection_release':False,
        'sources':{k:lock['files'][k] for k in ['structure_code','structure_json','single_age_json','province_reference']},
        'code_sha256':sha(__file__),'target_is_full_joint_household_distribution':False}
    with (HERE/'CITY_TARGET_AUDIT.json').open('x') as f:json.dump(result,f,ensure_ascii=False,sort_keys=True,indent=2);f.write('\n')
    print(json.dumps({k:result[k] for k in ['scope','size_quotas','generation_quotas','structure_cell_L1_count_residual','province_L1_count_residual','old300_cells_exceeding_direct_rounding']},ensure_ascii=False))
if __name__=='__main__':main()
