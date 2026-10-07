#!/usr/bin/env python3
"""2020 national household reference quotas, not 1000 generated households.

Integer rounding only. Does not infer joint provinces/ages/housing or 2025 cells.
"""
import collections as C,hashlib,json,time
from pathlib import Path
import numpy as np
from scipy.optimize import milp,LinearConstraint,Bounds

HERE=Path(__file__).resolve().parent
ROOT=HERE.parent
REPO=next(p for p in HERE.parents if p.name=='energybridge-household-survey')
STRUCTURE=REPO/'docs/research/long-horizon-plan/execution/three_track_report_v1/evidence/household_size_generation_2020.json'
NATIONAL=[[125490007,0,0,0,0],[110685779,36004280,0,0,0],[5134646,93163291,5403045,0,0],[1834602,42919633,20215417,131334,0],[701437,7315318,21906684,589759,154],[293766,1453830,12552955,824670,446],[139356,386946,3439349,622936,721],[89363,130530,1102904,234231,610],[53700,48137,476038,76840,345],[192367,49694,431790,60245,268]]
RURAL=[[44036073,0,0,0,0],[41935105,13865649,0,0,0],[2217427,31094815,2420003,0,0],[737989,15471812,8374076,75018,0],[153695,3392156,8977834,333318,80],[50737,737297,5645999,448269,263],[26579,198061,1790367,345769,433],[17442,64438,583635,136272,381],[11470,23180,243558,44861,226],[42587,20889,221514,33290,152]]

def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def write(p,x):
    with p.open('x') as f:json.dump(x,f,ensure_ascii=False,sort_keys=True,indent=2);f.write('\n')
def lr(weights,n=1000):
    total=sum(weights);q=[w*n//total for w in weights]
    order=sorted(range(len(weights)),key=lambda i:(-(weights[i]*n%total),-weights[i],i))
    for i in order[:n-sum(q)]:q[i]+=1
    return q

def solve(source,targets,retained=None):
    expected=source.flatten()/source.sum()*1000;k=len(expected)
    # x-p+n = expected, integer x and nonnegative L1 residuals p,n.
    eq=np.zeros((k,3*k));eq[:,:k]=np.eye(k);eq[:,k:2*k]=-np.eye(k);eq[:,2*k:]=np.eye(k)
    rows=[eq];rhs=[expected]
    for axis,quota in targets.items():
        for value,count in enumerate(quota):
            mask=np.zeros(source.shape);sl=[slice(None)]*3;sl[axis]=value;mask[tuple(sl)]=1
            row=np.zeros(3*k);row[:k]=mask.flatten();rows.append(row[None,:]);rhs.append(np.array([count]))
    lower=np.zeros(3*k);upper=np.full(3*k,np.inf);upper[:k]=np.where(source.flatten()>0,1000,0)
    if retained is not None:lower[:k]=retained.flatten()
    if np.any(lower>upper):return {'success':False,'reason':'retained_in_structural_zero'}
    matrix=np.concatenate(rows);value=np.concatenate(rhs)
    cost=np.r_[np.zeros(k),np.ones(2*k)]
    result=milp(cost,integrality=np.r_[np.ones(k),np.zeros(2*k)],bounds=Bounds(lower,upper),
        constraints=LinearConstraint(matrix,value,value),options={'time_limit':15,'mip_rel_gap':0})
    if not result.success:return {'success':False,'status':int(result.status),'message':result.message}
    counts=np.rint(result.x[:k]).astype(int).reshape(source.shape)
    return {'success':True,'counts':counts.tolist(),'L1_rounding_counts':float(np.abs(counts.flatten()-expected).sum()),
        'max_cell_rounding_count':float(np.abs(counts.flatten()-expected).max())}

def main():
    start=time.monotonic();x=json.loads(STRUCTURE.read_text());assert sha(STRUCTURE)=='37a0ef154d297801557bde5e7b55520f623a0e0c66b09829fcd1384738d6098d'
    city=np.array(x['city']['matrix'],dtype=np.int64);town=np.array(x['town']['matrix'],dtype=np.int64);rural=np.array(RURAL,dtype=np.int64);national=np.array(NATIONAL,dtype=np.int64)
    assert np.array_equal(city+town+rural,national)
    assert national.sum()==494157423 and rural.sum()==183772719
    assert np.array_equal(national.sum(axis=0),[244615023,181471659,65528182,2540015,2544])
    source=np.stack([city,town,rural]);targets={axis:lr(source.sum(axis=tuple(j for j in range(3) if j!=axis)).tolist()) for axis in range(3)}
    free=solve(source,targets);assert free['success'],free
    counts=np.array(free['counts'])
    for axis,q in targets.items():assert np.array_equal(counts.sum(axis=tuple(j for j in range(3) if j!=axis)),q)
    assert counts.sum()==1000 and not np.any(counts[source==0])
    old=np.zeros(source.shape,dtype=int);old_files=sorted((ROOT/'round2/boundary_v7/mapped_old300').glob('*.json'))
    assert len(old_files)==300
    for path in old_files:
        p=json.loads(path.read_text());old[0,p['family_size']-1,p['generation_design']-1]+=1
    retained=solve(source,targets,old)
    old_conflicts=[]
    for s,n,g in np.argwhere(old>counts):old_conflicts.append({'settlement':['city','town','rural'][s],'size_category':int(n+1),'generation_category':int(g+1),'old300':int(old[s,n,g]),'unconstrained_quota':int(counts[s,n,g])})
    rows=[]
    for s,n,g in np.argwhere(source>0):
        rows.append({'settlement':['city','town','rural'][s],'size_category':'10+' if n==9 else int(n+1),
            'generation_category':'5+' if g==4 else int(g+1),'source_households':int(source[s,n,g]),
            'expected_of1000':float(source[s,n,g]/source.sum()*1000),'reference_quota':int(counts[s,n,g])})
    data={'batch_id':'NATIONAL_REFERENCE_202010_1000_CHECK_20261001','unit':'family_households','reference_date':'2020-11-01',
        'generated_profiles':0,'generated_A':0,'generated_B':0,'physics':0,'population_target_claim':'2020 reference counts only; not 2025 or 2026',
        'national_matrix':NATIONAL,'rural_matrix':RURAL,'city_matrix':city.tolist(),'town_matrix':town.tolist(),
        'transcription':'national A0501 and rural A0501c manually read; all 50 cells independently reconcile city+town+rural',
        'source_households_total':int(source.sum()),'settlement_source_counts':source.sum(axis=(1,2)).tolist(),
        'settlement_labels':['city','town','rural'],'settlement_quotas':targets[0],
        'national_size_quotas':targets[1],'national_generation_quotas':targets[2],
        'free_integer_reference':free,'cell_rows':rows,
        'unrepresented_structure_mass':float(source[counts==0].sum()/source.sum()),
        'minimum_mean_size_lower_bound':float(sum((n+1)*counts[:,n,:].sum() for n in range(10))/1000),
        'mean_bound_note':'10+ coded10 is a lower bound, not an exact mean; no member ages generated',
        'retain_old300_structure_only':retained,'old300_against_free_quota_conflicts':old_conflicts,
        'retention_scope':'city x size x generation only; ignores missing home windows and all housing/assets/model checks',
        'latest2025_household_mean':2.52,'latest2025_urban_population_percent_not_household_quota':67.74,
        'latest2025_url':'https://www.stats.gov.cn/zt_18555/zdtjgz/cydc/2025cydc/tzgg/202605/t20260522_1963788.html',
        'latest2025_joint_household_targets_in_this_run':None,
        'code_sha256':sha(__file__),'structure_json_sha256':sha(STRUCTURE),
        'source_image_sha256':{p.name:sha(p) for p in HERE.glob('*.jpg')},'wall_seconds':round(time.monotonic()-start,3),
        'collection_release':False,'training_release':False}
    write(HERE/'REFERENCE_QUOTAS.json',data)
    print(json.dumps({k:data[k] for k in ['settlement_quotas','national_size_quotas','national_generation_quotas','unrepresented_structure_mass','minimum_mean_size_lower_bound','old300_against_free_quota_conflicts','wall_seconds']},ensure_ascii=False));print('retain300',retained['success'])

if __name__=='__main__':main()
