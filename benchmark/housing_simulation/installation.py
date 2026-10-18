"""Joint rectangle packing on a declared grid using SciPy/HiGHS MILP.

No solver result implies real-world construction compliance. An infeasibility
certificate applies only to these envelopes, grid, rotations and access strip.
"""
import math
from functools import lru_cache
import numpy as np
from scipy.optimize import Bounds, LinearConstraint, milp
from .policy import reference


class InstallationInfeasible(ValueError):pass
class InstallationUnresolved(ValueError):pass


@lru_cache(maxsize=512)
def _solve(width,height,items):
    policy=reference('installation');grid=policy['grid_m'];gap=policy['gap_m']/grid
    n=len(items)
    if not n:return ()
    # x/y are body origin coordinates on the grid; r selects a90degree rotation.
    count=3*n+4*n*(n-1)//2
    lower=np.zeros(count);upper=np.full(count,np.inf)
    for i in range(n):upper[3*i:3*i+3]=[width/grid,height/grid,1]
    upper[3*n:]=1
    rows=[];lows=[];highs=[]
    def constraint(terms,lo=-np.inf,hi=np.inf):
        row=np.zeros(count)
        for k,v in terms.items():row[k]+=v
        rows.append(row);lows.append(lo);highs.append(hi)
    dimensions=[]
    for i,(w,h,clear)in enumerate(items):
        if not all(math.isfinite(v)and v>0 for v in (w,h))or len(clear)!=4 or any(not math.isfinite(v)or v<0 for v in clear):raise ValueError('invalid footprint/clearance')
        # Clearance coordinates are left,bottom,right,top before rotation.
        left,bottom,right,top=[v/grid for v in clear]
        wi,he=w/grid,h/grid
        # CCW rotation maps clearances to top,left,bottom,right.
        dimensions.append((wi,he,left,bottom,right,top))
        x,y,r=3*i,3*i+1,3*i+2
        constraint({x:1,r:left-top},lo=left)
        constraint({y:1,r:bottom-left},lo=policy['access_strip_m']/grid+bottom)
        constraint({x:1,r:he+bottom-wi-right},hi=width/grid-wi-right)
        constraint({y:1,r:wi+right-he-top},hi=height/grid-he-top)
    big=(width+height+2*max(max(a[0],a[1])+sum(a[2])for a in items)+2)/grid
    index=3*n
    for i in range(n):
        wi,hi,li,bi,ri,ti=dimensions[i];xi,yi,oi=3*i,3*i+1,3*i+2
        for j in range(i+1,n):
            wj,hj,lj,bj,rj,tj=dimensions[j];xj,yj,oj=3*j,3*j+1,3*j+2
            # At least one disjunct is active, including both objects' clearances.
            constraint({xi:1,xj:-1,oi:hi+bi-wi-ri,oj:tj-lj,index:big},hi=big-wi-ri-lj-gap)
            constraint({xj:1,xi:-1,oj:hj+bj-wj-rj,oi:ti-li,index+1:big},hi=big-wj-rj-li-gap)
            constraint({yi:1,yj:-1,oi:wi+ri-hi-ti,oj:lj-bj,index+2:big},hi=big-hi-ti-bj-gap)
            constraint({yj:1,yi:-1,oj:wj+rj-hj-tj,oi:li-bi,index+3:big},hi=big-hj-tj-bi-gap)
            constraint({index+k:1 for k in range(4)},lo=1)
            index+=4
    # Fixed ordering and deterministic solver, no random tie-break or wall clock limit.
    objective=np.zeros(count)
    for i in range(n):objective[3*i:3*i+3]=[1+1/(i+2),2+1/(i+2),.01/(i+1)]
    result=milp(objective,integrality=np.ones(count),bounds=Bounds(lower,upper),
                constraints=LinearConstraint(np.array(rows),lows,highs),
                options={'node_limit':policy['solver_node_limit'],'mip_rel_gap':0})
    if result.status==2:raise InstallationInfeasible('INSTALLATION_GRID_INFEASIBLE:NO_INSTALLATION_SPACE')
    if result.status!=0:raise InstallationUnresolved('INSTALLATION_UNRESOLVED:solver status '+str(result.status))
    solution=[]
    for i,(w,h,clear)in enumerate(items):
        x,y,rotate=[int(round(v))for v in result.x[3*i:3*i+3]]
        if rotate:w,h=h,w;clear=(clear[3],clear[0],clear[1],clear[2])
        body=(x*grid,y*grid,x*grid+w,y*grid+h)
        envelope=(body[0]-clear[0],body[1]-clear[1],body[2]+clear[2],body[3]+clear[3])
        if envelope[0]<-1e-7 or envelope[1]<policy['access_strip_m']-1e-7 or envelope[2]>width+1e-7 or envelope[3]>height+1e-7:raise InstallationUnresolved('INSTALLATION_WITNESS_OUT_OF_BOUNDS')
        solution.append((body,envelope,rotate,tuple(clear)))
    for i,(_,a,_,_)in enumerate(solution):
        for _,b,_,_ in solution[i+1:]:
            if not(a[2]+gap*grid<=b[0]+1e-7 or b[2]+gap*grid<=a[0]+1e-7 or a[3]+gap*grid<=b[1]+1e-7 or b[3]+gap*grid<=a[1]+1e-7):raise InstallationUnresolved('INSTALLATION_WITNESS_OVERLAP')
    return tuple(solution)


def place(items,room):
    x0,y0,x1,y1=room['usable_rect_m'];items=sorted(items,key=lambda x:x['object_id'])
    data=tuple((float(x['footprint_m'][0]),float(x['footprint_m'][1]),tuple(x.get('clearance_m',[0,0,0,0])))for x in items)
    solution=_solve(x1-x0,y1-y0,data)
    return [{**item,'room_id':room['room_id'],'rect_m':[v+(x0 if k%2==0 else y0)for k,v in enumerate(body)],
             'clearance_rect_m':[v+(x0 if k%2==0 else y0)for k,v in enumerate(envelope)],
             'rotation_degrees':90*rotate,'oriented_clearance_m':list(clear),
             'solver_status':'optimal_feasible_grid','method':'joint_MILP_HiGHS'}
            for item,(body,envelope,rotate,clear)in zip(items,solution)]
