#!/usr/bin/env python3
"""Allocate 1000 population slots. These are not complete household profiles.

The unobserved provincial size-generation interaction remains a modeling
assumption. Census structural zeros remain zeros. No housing/device fallback.
"""
import hashlib
import json
from pathlib import Path
import numpy as np
from scipy.optimize import Bounds, LinearConstraint, milp
from scipy.sparse import lil_matrix

HERE = Path(__file__).resolve().parent
def read(p): return json.loads(p.read_text())
def sha(p): return hashlib.sha256(p.read_bytes()).hexdigest()

def main():
    source = HERE/'CITY_AUTHORITY_CONSTRAINTS_V2.json'
    d = read(source)['modeled_population_completion']
    audit = read(HERE.parent/'city_representativeness_20261001/CITY_TARGET_AUDIT.json')
    expected = np.array(d['expected_counts_per1000'])
    target = np.zeros((10,5), dtype=int)
    for r in audit['joint_size_generation']:
        s,g = r['size_generation'].split('x')
        target[9 if s=='10_plus' else int(s)-1, 4 if g=='5_plus' else int(g)-1] = r['joint_target_1000']
    provinces = d['province_order']
    pt = np.array([r['quota_1000'] for r in audit['province_quotas']])
    assert provinces == [r['province'] for r in audit['province_quotas']]
    assert target.sum() == pt.sum() == 1000
    shape = expected.shape; n = expected.size
    # x integers; continuous d bounds absolute x-minus-expected deviations.
    rows = 31+50+31*10+31*5+2*n
    a = lil_matrix((rows, 2*n), dtype=float)
    lo = np.full(rows,-np.inf); hi = np.full(rows,np.inf)
    ids = np.arange(n).reshape(shape)
    row = 0
    for p in range(31):
        a[row,ids[p].ravel()] = 1; lo[row] = hi[row] = pt[p]; row += 1
    for s in range(10):
        for g in range(5):
            a[row,ids[:,s,g]] = 1; lo[row] = hi[row] = target[s,g]; row += 1
    # Predeclared per-province size and generation rounding envelopes.
    for p in range(31):
        for s in range(10):
            e = expected[p,s,:].sum()
            a[row,ids[p,s,:]] = 1; lo[row] = np.floor(e); hi[row] = np.ceil(e); row += 1
        for g in range(5):
            e = expected[p,:,g].sum()
            a[row,ids[p,:,g]] = 1; lo[row] = np.floor(e); hi[row] = np.ceil(e); row += 1
    for i,e in enumerate(expected.ravel()):
        a[row,i] = 1; a[row,n+i] = -1; hi[row] = e; row += 1
        a[row,i] = -1; a[row,n+i] = -1; hi[row] = -e; row += 1
    upper = np.where(expected.ravel()>0,1000,0)
    objective = np.concatenate([np.arange(n)*1e-10,np.ones(n)])
    result = milp(objective,integrality=np.r_[np.ones(n),np.zeros(n)],
        bounds=Bounds(np.zeros(2*n),np.r_[upper,np.full(n,np.inf)]),
        constraints=LinearConstraint(a.tocsc(),lo,hi),
        options={'time_limit':45,'mip_rel_gap':0})
    if not result.success:
        raise RuntimeError(f'No optimal allocation; status={result.status}; {result.message}')
    x = np.rint(result.x[:n]).astype(int).reshape(shape)
    assert np.array_equal(x.sum((1,2)),pt)
    assert np.array_equal(x.sum(0),target)
    assert (x[expected==0]==0).all()
    slots=[]
    for p,s,g in np.ndindex(shape):
        for _ in range(int(x[p,s,g])):
            slots.append({'slot_id':f'cityslot-{len(slots)+1:04d}','province':provinces[p],
                'size_category':d['size_categories'][s], 'generation_category':d['generation_categories'][g],
                'exact_member_count':s+1 if s<9 else None,
                'status':'population_slot_only; members/housing/devices/schedule/model absent'})
    assert len(slots)==1000
    size_before=expected.sum(2);gen_before=expected.sum(1)
    zero_target = (target==0)&(expected.sum(0)>0)
    assert (abs(x.sum(2)-size_before)<1+1e-9).all()
    assert (abs(x.sum(1)-gen_before)<1+1e-9).all()
    out={'batch_id':'CITY1000_POPULATION_ALLOCATION_20261001_V2',
      'status':'candidate_allocation_not_complete_roles', 'target_reference_year':2020,
      'scope':audit['scope'],'eligibility':audit['eligibility'],
      'source_sha256':sha(source),'target_audit_sha256':sha(HERE.parent/'city_representativeness_20261001/CITY_TARGET_AUDIT.json'),
      'model_assumption':d['starting_assumption'],
      'objective':'minimize absolute cell deviations from modeled IPF expectation',
      'hard_constraints':['1000 slots','province quotas','national size-generation quotas','preserve structural zeros','each province-size and province-generation within floor/ceil unrounded target'],
      'not_hard_constraints':['full unobserved joint','housing/model feasibility'],
      'solver':{'status':int(result.status),'message':result.message,'mip_gap':float(result.mip_gap)},
      'province_order':provinces,'allocated_counts':x.tolist(),'slots':slots,
      'diagnostics':{'province_L1_residual':int(abs(x.sum((1,2))-pt).sum()),
        'national_size_generation_L1_residual':int(abs(x.sum(0)-target).sum()),
        'province_size_L1_vs_unrounded_expectation':float(abs(x.sum(2)-size_before).sum()),
        'province_generation_L1_vs_unrounded_expectation':float(abs(x.sum(1)-gen_before).sum()),
        'province_size_max_absolute_vs_unrounded':float(abs(x.sum(2)-size_before).max()),
        'province_generation_max_absolute_vs_unrounded':float(abs(x.sum(1)-gen_before).max()),
        'joint_L1_vs_modeled_expectation':float(abs(x-expected).sum()),
        'positive_expected_provincial_cell_mass_allocated_zero_per1000':float(expected[x==0].sum()),
        'positive_expected_national_cell_mass_rounded_zero_per1000':float(expected.sum(0)[zero_target].sum())},
      'topcode_rule':'10+ member count remains unknown until explicitly sourced/designed; never silently set to10',
      'collection_release':False,'complete_profiles':0,'engine_calls':0,'code_sha256':sha(Path(__file__))}
    with (HERE/'POPULATION_ALLOCATION_CANDIDATE_V2.json').open('x') as f:
        json.dump(out,f,ensure_ascii=False,indent=2,allow_nan=False);f.write('\n')
    print(json.dumps({'slots':len(slots),'diagnostics':out['diagnostics'],'solver':out['solver']},ensure_ascii=False))

if __name__=='__main__':main()
