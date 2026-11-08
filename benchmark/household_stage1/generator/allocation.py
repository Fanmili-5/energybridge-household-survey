"""Constrained control coverage; no human outcomes are an optimization input."""
from collections import Counter,defaultdict
from itertools import combinations
import hashlib,json,warnings
from ..required_controls import FUNCTIONS,allowed_masks
from .quotas import largest_remainder

def allocate(engine,cases,config,role_counts):
    import numpy as np
    from scipy.optimize import milp,Bounds,LinearConstraint
    from scipy.sparse import coo_matrix
    cov=config['coverage'];variables=[]
    for i,c in enumerate(cases):
        for mask in allowed_masks(c['benchmark_role']):
            if c['source']['dataset']=='ECA2025' and 'EV' in mask and c['source_record_fields']['off_street_parking']!='Yes':continue
            variables.append((i,mask))
    index=defaultdict(list)
    for j,(i,m) in enumerate(variables):
        c=cases[i];co=c['source']['country'];r=c['benchmark_role']
        for k in [('case',i),('case_mask',i,m),('country_mask',co,m),('role_mask',r,m),('size',len(m)),('role_size',r,len(m)),('cell_size',co,r,len(m))]:index[k].append(j)
        for f in m:
            index[('cell_function',co,r,f)].append(j)
            if len(m)<6:index[('nonfull_function',r,f)].append(j)
        if len(m)<6:
            for p in combinations(m,2):index[('nonfull_pair',r,p)].append(j)
    rr=[];cc=[];vv=[];lo=[];hi=[]
    def con(k,a,b=np.inf):
        cols=index[k]
        if not cols and a>0:raise ValueError('CONTROL_COVERAGE_HAS_NO_COMPATIBLE_OPTION:'+str(k))
        row=len(lo);rr.extend([row]*len(cols));cc.extend(cols);vv.extend([1.]*len(cols));lo.append(a);hi.append(b)
    for i in range(len(cases)):con(('case',i),1,1)
    sizes=largest_remainder(len(cases),{'4':1,'5':1,'6':1})
    if len(cases)==1000 and config.get('v9_cardinality_compatibility',False):sizes={'4':333,'5':333,'6':334}
    for n,count in sizes.items():con(('size',int(n)),count,count)
    for r,total in role_counts.items():
        for n in (4,5,6):con(('role_size',r,n),total//3,(total+2)//3)
        if cov['role_minimum_pattern_count']:
            for m in allowed_masks(r):con(('role_mask',r,m),cov['role_minimum_pattern_count'])
        if cov['nonfull_function_minimum']:
            for f in FUNCTIONS:con(('nonfull_function',r,f),cov['nonfull_function_minimum'])
        if cov['nonfull_pair_minimum']:
            for p in combinations(FUNCTIONS,2):con(('nonfull_pair',r,p),cov['nonfull_pair_minimum'])
    for co in config['countries']:
        if cov['country_all_masks']:
            if sum(c['source']['country']==co for c in cases)<16:raise ValueError('AT_LEAST16_HOUSEHOLDS_NEEDED_FOR_ALL_COUNTRY_MASKS:'+co)
            for m in allowed_masks():con(('country_mask',co,m),1)
        for r in 'ABCDEF':
            total=sum(c['source']['country']==co and c['benchmark_role']==r for c in cases)
            if not total:continue
            for n in (4,5,6):con(('cell_size',co,r,n),total//3,(total+2)//3)
            if cov['cell_function_minimum']:
                for f in FUNCTIONS:con(('cell_function',co,r,f),cov['cell_function_minimum'])
    pairs=defaultdict(list)
    for i,c in enumerate(cases):
        if c.get('cd_pair_id'):pairs[c['cd_pair_id']].append(i)
    for pair,indices in pairs.items():
        if len(indices)!=2:raise ValueError('UNPAIRED_CD:'+pair)
        left,right=indices
        for m in allowed_masks():
            a=index[('case_mask',left,m)];b=index[('case_mask',right,m)];cols=a+b
            if not cols:continue
            row=len(lo);rr.extend([row]*len(cols));cc.extend(cols);vv.extend([1.]*len(a)+[-1.]*len(b));lo.append(0);hi.append(0)
    matrix=coo_matrix((vv,(rr,cc)),shape=(len(lo),len(variables))).tocsc()
    def cost(i,m):
        c=cases[i];equipment=c['household']['equipment'];key=engine.a.KEY
        installs=sum(not equipment[key[f]]['present'] for f in m)
        tie=int(hashlib.sha256(json.dumps([str(config['seed']),c['case_id'],m]).encode()).hexdigest()[:12],16)/16**12
        return 100*installs+tie
    with warnings.catch_warnings():
        warnings.filterwarnings('ignore',message='Unrecognized options detected')
        result=milp(np.array([cost(i,m) for i,m in variables]),integrality=np.ones(len(variables)),bounds=Bounds(0,1),constraints=LinearConstraint(matrix,lo,hi),
          options={'time_limit':float(config.get('solver_time_limit_seconds',55)),'mip_rel_gap':.01,'threads':1,'random_seed':int(hashlib.sha256(str(config['seed']).encode()).hexdigest()[:7],16)})
    if result.x is None:raise ValueError('NO_INTEGER_CONTROL_ASSIGNMENT_WITHIN_DECLARED_BUDGET:'+str(result.message))
    x=np.rint(result.x);v=matrix@x
    if np.max(abs(x-result.x))>1e-5 or not(np.all(v>=np.asarray(lo)-1e-5) and np.all(v<=np.asarray(hi)+1e-5)):raise ValueError('INVALID_INTEGER_SOLUTION')
    assigned={cases[i]['case_id']:list(m) for j,(i,m) in enumerate(variables) if x[j]==1}
    report={'solver_status':int(result.status),'message':result.message,'optimality_claim':bool(result.success and result.mip_gap<=1e-9),'solver_success_within_requested_gap':bool(result.success),'requested_mip_relative_gap':.01,'mip_gap':float(result.mip_gap),
      'all_integral_constraints_recomputed':True,'variables':len(variables),'constraints':len(lo),'cardinality_targets':sizes,
      'objective':'prefer fewer experimental installations subject to declared coverage; never acceptance, savings, or later outcomes',
      'reproducibility':'freeze the returned control assignment; replay does not require cross-version solver tie equivalence'}
    return assigned,report
