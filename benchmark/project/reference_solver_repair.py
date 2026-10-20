"""Audit the independently versioned, bounded v24.1 numerical fallback.

The official iteration warning is retained before fallback. It is resolved only
by a pinned execution plus independently reproduced unique-root residuals.
Multiple roots stay unresolved. This is not a universal EnergyPlus validation.
"""
import math
import struct

ENGINE_FILES={'energyplus':'ad848ba02af8d555e995d4542bd36900b5c0fe656afcfcc0065ee95f551f24ea',
    'libenergyplusapi.so.24.1.0':'a6224c83665aaeb215be1f0978633e7246e1a3443373ee65e2035441afecd012',
    'Energy+.idd':'a9bfd265fb9aa3abff2a932a328ed0033a2741160da9d58c77abc8234a39bb83'}
PATCH_SHA256='075377d45ec07f4347d08231abd609fcbda96a87f10a42adaadfeaaeb425dcbe'


def psat(temperature):
    bits=struct.unpack('Q',struct.pack('d',temperature))[0]&~((1<<28)-1)
    k=struct.unpack('d',struct.pack('Q',bits))[0]+273.15
    if k<173.15:return .001405102123874164
    if k<273.16:return math.exp(-5674.5359/k+6.3925247+k*(-.009677843+k*(.00000062215701+k*(.0000000020747825-.0000000000009484024*k)))+4.1635019*math.log(k))
    if k<=473.15:return math.exp(-5800.2206/k+1.3914993+k*(-.048640239+k*(.000041764768-.000000014452093*k))+6.5459673*math.log(k))
    return 1555073.745636215


def residual(tdb,w,p,twb,ice):
    vap=psat(twb)
    if not 0<vap<p:raise ValueError('INVALID_SATURATION_PRESSURE')
    ws=.62198*vap/(p-vap)
    value=(((2830-.24*twb)*ws-1.006*(tdb-twb))/(2830+1.86*tdb-2.1*twb)if ice else
           ((2501-2.326*twb)*ws-1.006*(tdb-twb))/(2501+1.86*tdb-4.186*twb))
    return value-w


def roots(tdb,w,p):
    if not all(map(math.isfinite,(tdb,w,p)))or not(-99<tdb<90 and w>=0 and p>0):raise ValueError('INVALID_REPAIR_INPUT')
    if residual(tdb,w,p,tdb,tdb<0)<-1e-10:raise ValueError('SUPERSATURATED_REPAIR_INPUT')
    ranges=[(-99,min(tdb,math.nextafter(0,-1)),True)]
    if tdb>=0:ranges.append((0,tdb,False))
    found=[]
    for lo,hi,ice in ranges:
        f=lambda x:residual(tdb,w,p,x,ice)
        samples=[f(lo+(hi-lo)*i/128)for i in range(129)]
        if any(b+1e-10<a for a,b in zip(samples,samples[1:])):raise ValueError('NONMONOTONE_REPAIR_BRANCH')
        if not samples[0]<=0<=samples[-1]:continue
        for _ in range(80):
            if hi-lo<=1e-7:break
            mid=(lo+hi)/2
            if f(mid)>0:hi=mid
            else:lo=mid
        found.append((lo+hi)/2)
    return found


def review(log,engine_files):
    if engine_files!=ENGINE_FILES:raise ValueError('UNRECOGNIZED_REPAIR_ENGINE')
    events=[];failures=[];clips=0
    for line in log.splitlines():
        if not line.startswith('EBTWB_'):continue
        fields=dict(x.split('=',1)for x in line.split('\t')[1:])
        if line.startswith('EBTWB_REPAIR_UNRESOLVED'):
            failures.append('bounded_wetbulb_'+fields.get('status','unknown'));continue
        if line.startswith('EBTWB_EXISTING_CLIP'):
            clips+=1;continue # preserved original saturation boundary, disclosed separately
        if not line.startswith('EBTWB_REPAIR_APPLIED'):raise ValueError('UNKNOWN_REPAIR_EVENT')
        t,w,p,old,new=map(lambda k:float(fields[k]),('tdb','w','p','old','new'))
        found=roots(t,w,p);r=residual(t,w,p,new,new<0);old_r=residual(t,w,p,old,old<0)
        if len(found)!=1 or abs(new-found[0])>2e-7 or abs(r)>1e-8 or abs(old_r)<=1e-8:
            raise ValueError('REPAIR_NOT_AN_INDEPENDENTLY_VERIFIED_UNIQUE_ROOT')
        if abs(r-float(fields['new_residual']))>1e-12 or abs(old_r-float(fields['old_residual']))>1e-12:
            raise ValueError('REPAIR_REPORTED_RESIDUAL_MISMATCH')
        events.append({'new_C':new,'old_C':old,'new_residual':r,'old_residual':old_r})
    return {'passed':not failures,'failures':sorted(set(failures)),'unique_root_repairs':len(events),
        'maximum_abs_new_humidity_residual':max((abs(e['new_residual'])for e in events),default=0),
        'original_drybulb_clips_retained':clips,'original_warnings_retained':True,
        'engine_files_sha256':engine_files,'patch_sha256':PATCH_SHA256}
