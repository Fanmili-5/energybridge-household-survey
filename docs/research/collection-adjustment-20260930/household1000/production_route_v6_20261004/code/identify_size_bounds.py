"""Partial-identification LP; no IPF full-city joint fixed as truth.

Tail means remain borrowed from all-city tails. Bounds are conditional on that
explicit assumption and known margins, NOT confidence intervals.
"""
import json
from pathlib import Path
import numpy as np
from scipy.optimize import linprog
from scipy.sparse import lil_matrix
from build_census_frame import table, normalized

OUT=Path(__file__).resolve().parent.parent

def main():
    f=json.loads((OUT/'ORDINARY_CITY_FRAME.json').read_text());provinces=f['provinces']
    size_rows=table('A0108a')[1];gen_rows=table('A0109a')[1];ng_book=table('A0501a')[0]
    all_size=np.array([size_rows[p][2::2] for p in provinces],float)
    all_gen=np.array([gen_rows[p][2::2] for p in provinces],float)
    national_ng=np.array([r[2:7] for r in ng_book.values.tolist() if isinstance(r[1],(int,float)) and normalized(r[0])!='总计'],float)
    ordinary_g=np.array(f['ordinary_generation_room_counts']).sum(2)
    people=np.array(f['ordinary_resident_counts'],float)
    hh=sum(f['ordinary_household_counts']);q=31*10*5
    index=lambda p,n,g:p*50+n*5+g
    eq=lil_matrix((31*10+31*5+10*5+31*5+31,2*q));rhs=[];row=0
    for p in range(31):
        for n in range(10):
            for g in range(5):eq[row,index(p,n,g)]=1
            rhs.append(all_size[p,n]);row+=1
    for p in range(31):
        for g in range(5):
            for n in range(10):eq[row,index(p,n,g)]=1
            rhs.append(all_gen[p,g]);row+=1
    for n in range(10):
        for g in range(5):
            for p in range(31):eq[row,index(p,n,g)]=1
            rhs.append(national_ng[n,g]);row+=1
    for p in range(31):
        for g in range(5):
            for n in range(10):eq[row,q+index(p,n,g)]=1
            rhs.append(ordinary_g[p,g]);row+=1
    for p in range(31):
        for n in range(10):
            for g in range(5):eq[row,q+index(p,n,g)]=n+1 if n<9 else f['allcity_tail_mean_size'][p]
        rhs.append(people[p]);row+=1
    ub=lil_matrix((q,2*q))
    for j in range(q):ub[j,j]=-1;ub[j,q+j]=1
    bounds=[]
    for j in range(2*q):
        n,g=(j%q)%50//5,(j%q)%5
        bounds.append((0,0 if g>n else None))
    reports=[]
    for n in range(10):
        c=np.zeros(2*q)
        for p in range(31):
            for g in range(5):c[q+index(p,n,g)]=1
        extrema=[]
        for sign in [1,-1]:
            fit=linprog(c*sign,A_ub=ub.tocsr(),b_ub=np.zeros(q),A_eq=eq.tocsr(),b_eq=np.array(rhs),bounds=bounds,method='highs')
            if not fit.success:raise RuntimeError(fit.message)
            extrema.append(float(c@fit.x))
            assert np.max(abs(eq@fit.x-rhs))<.01 and np.max(ub@fit.x)<.01
        point=float(np.array(f['ordinary_size_generation_completion'])[:,n,:].sum())
        assert extrema[0]-.1<=point<=extrema[1]+.1
        reports.append({'N_category':str(n+1) if n<9 else '10+','households_min':extrema[0],'households_max':extrema[1],
                        'expected_per1000_min':extrema[0]/hh*1000,'expected_per1000_max':extrema[1]/hh*1000,
                        'entropy_point_expected_per1000':point/hh*1000})
    body={'known_constraints':'allcity_province_N; allcity_province_G; allcity_national_NG; ordinary_province_G; ordinary_province_residents; ordinary_subset_of_allcity',
          'fullcity_joint_fixed_to_IPF':False,'only_tail_mean_transport_remains_assumed':True,'each_extremum_is_separately_feasible_not_simultaneously_attainable':True,
          'bounds_are_not_confidence_intervals':True,'all20_LPs_feasible_and_constraint_residuals_checked':True,'ordinary_N_bounds':reports}
    (OUT/'ORDINARY_SIZE_PARTIAL_IDENTIFICATION.json').write_text(json.dumps(body,ensure_ascii=False,indent=2)+'\n')
    print(json.dumps(reports,indent=2))

if __name__=='__main__':main()
