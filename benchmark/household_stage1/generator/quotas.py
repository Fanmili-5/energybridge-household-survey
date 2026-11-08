"""Exact role totals and balanced integer country-role allocation."""
from fractions import Fraction
import math,warnings
ROLES=tuple('ABCDEF')
EB_COUNTS=dict(zip(ROLES,(97,116,73,88,91,119)))

def largest_remainder(total,weights):
    if not isinstance(total,int) or isinstance(total,bool) or total<0:raise ValueError('TOTAL_MUST_BE_NONNEGATIVE_INTEGER')
    w={k:Fraction(str(v)) for k,v in weights.items()}
    if not w or any(v<0 for v in w.values()) or sum(w.values())<=0:raise ValueError('INVALID_QUOTA_WEIGHTS')
    exact={k:total*v/sum(w.values()) for k,v in w.items()};result={k:math.floor(v) for k,v in exact.items()}
    for k in sorted(w,key=lambda k:(-(exact[k]-result[k]),k))[:total-sum(result.values())]:result[k]+=1
    return result

def plan(config):
    total=config['households'];countries=tuple(config['countries'])
    if not countries or len(set(countries))!=len(countries):raise ValueError('COUNTRY_LIST_EMPTY_OR_DUPLICATED')
    country_counts=config.get('country_counts') or largest_remainder(total,{c:1 for c in countries})
    role_counts=config.get('role_counts') or largest_remainder(total,EB_COUNTS)
    if set(role_counts)!=set(ROLES) or set(country_counts)!=set(countries):raise ValueError('QUOTA_KEYS_INVALID')
    if not isinstance(total,int) or isinstance(total,bool) or total<=0:raise ValueError('HOUSEHOLDS_MUST_BE_POSITIVE_INTEGER')
    if any(not isinstance(v,int) or isinstance(v,bool) or v<0 for v in [*country_counts.values(),*role_counts.values()]):raise ValueError('QUOTAS_MUST_BE_NONNEGATIVE_INTEGERS')
    if set(countries)-{'CN','US','GB','ES','IN','MX','AU','DE'}:raise ValueError('UNSUPPORTED_COUNTRY_ADAPTER')
    if sum(role_counts.values())!=total or sum(country_counts.values())!=total:raise ValueError('QUOTA_TOTAL_MISMATCH')
    if config.get('all_country_roles',True) and (min(country_counts.values())<6 or min(role_counts.values())<len(countries)):
        raise ValueError('INSUFFICIENT_SIZE_FOR_ALL_COUNTRY_ROLE_CELLS; increase count or explicitly use a diagnostic configuration')
    given=config.get('country_role_quotas')
    if given:
        if set(given)!=set(countries):raise ValueError('COUNTRY_ROLE_MATRIX_KEYS')
        if any(set(given[c])!=set(ROLES) or any(not isinstance(v,int) or isinstance(v,bool) or v<0 for v in given[c].values()) for c in countries):raise ValueError('COUNTRY_ROLE_MATRIX_INTEGER_KEYS')
        if any(sum(given[c].values())!=country_counts[c] for c in countries):raise ValueError('COUNTRY_ROW_QUOTA')
        if any(sum(given[c][r] for c in countries)!=role_counts[r] for r in ROLES):raise ValueError('ROLE_COLUMN_QUOTA')
        matrix=given
    else:
        import numpy as np
        from scipy.optimize import milp,Bounds,LinearConstraint
        cells=[(c,r) for c in countries for r in ROLES]
        expected=np.array([country_counts[c]*role_counts[r]/total for c,r in cells])
        lower=np.floor(expected);upper=np.ceil(expected)
        if config.get('all_country_roles',True):lower=np.maximum(lower,1)
        A=[];lo=[];hi=[]
        for c in countries:A.append([int(x==c) for x,r in cells]);lo.append(country_counts[c]);hi.append(country_counts[c])
        for r in ROLES:A.append([int(y==r) for c,y in cells]);lo.append(role_counts[r]);hi.append(role_counts[r])
        if config.get('pair_CD',True):
            for c in countries:A.append([int(x==c and r=='D')-int(x==c and r=='C') for x,r in cells]);lo.append(0);hi.append(np.inf)
        # Prefer rounding up the largest fractional cells; deterministic cell-order tie break.
        objective=1-2*(expected-np.floor(expected))+np.arange(len(cells))*1e-8
        with warnings.catch_warnings():
            warnings.filterwarnings('ignore',message='Unrecognized options detected')
            result=milp(objective,integrality=np.ones(len(cells)),bounds=Bounds(lower,upper),constraints=LinearConstraint(np.asarray(A),lo,hi),options={'threads':1,'time_limit':30})
        if result.x is None:raise ValueError('COUNTRY_ROLE_QUOTAS_INFEASIBLE')
        vals=np.rint(result.x).astype(int);matrix={c:{r:int(vals[cells.index((c,r))]) for r in ROLES} for c in countries}
    if config.get('all_country_roles',True) and any(matrix[c][r]<1 for c in countries for r in ROLES):raise ValueError('EMPTY_COUNTRY_ROLE_CELL')
    if config.get('pair_CD',True) and any(matrix[c]['D']<matrix[c]['C'] for c in countries):raise ValueError('D_QUOTA_LESS_THAN_C_MATCHED_QUOTA')
    return country_counts,role_counts,matrix
