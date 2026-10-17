"""Relationship-aware sleeping assignment on fixed metric rooms/portals.

Privacy reference adapts EU-SILC; it is not a Chinese co-sleep prevalence model.
Furniture dimensions and reachability retain the reviewed reference witnesses.
No resident, census room, wall, area or relationship is silently changed.
"""
import copy, hashlib, itertools, math
from functools import lru_cache
from shapely.geometry import box, Point
from shapely.ops import unary_union

FURNITURE={'single':(2.05,.94,1),'bunk':(2.07,.965,2),'double':(2.05,1.54,2)}
def doors(rows):
    parents={r[1]:r[4]for r in rows if r[0]=='BuildingSurface:Detailed'}
    return {parents[r[4]]:[list(map(float,r[j:j+3]))for j in range(10,len(r),3)]
            for r in rows if r[0]=='FenestrationSurface:Detailed'and r[2]=='Door'
            and not r[1].endswith('_peer')and r[1]!='entry_door'}
def canonical(room,verts):
    x0,y0,x1,y1=room['usable_rect_m'];W=x1-x0;D=y1-y0
    xs=[v[0]for v in verts];ys=[v[1]for v in verts]
    if max(xs)-min(xs)>.1:
        side='north'if abs(ys[0]-y1)<abs(ys[0]-y0)else'south';lo=max(0,min(xs)-x0);hi=min(W,max(xs)-x0)
    else:
        side='east'if abs(xs[0]-x1)<abs(xs[0]-x0)else'west';lo=max(0,min(ys)-y0);hi=min(D,max(ys)-y0);W,D=D,W
    return W,D,lo,hi,side
def point_world(x,y,room,side):
    x0,y0,x1,y1=room['usable_rect_m']
    return (x0+x,y0+y)if side=='north'else(x0+x,y1-y)if side=='south'else(x0+y,y0+x)if side=='east'else(x1-y,y0+x)
def rect_world(rect,room,side):
    points=[point_world(x,y,room,side)for x,y in [(rect[0],rect[1]),(rect[2],rect[3])]]
    return [min(p[0]for p in points),min(p[1]for p in points),max(p[0]for p in points),max(p[1]for p in points)]
def paths(W,D,beds,lo,hi,c):
    radius=c/2
    free=box(0,0,W,D).buffer(-radius,join_style=2).difference(unary_union([box(*b).buffer(radius,join_style=2)for b in beds]))
    parts=[free]if free.geom_type=='Polygon'else[g for g in getattr(free,'geoms',[])if g.geom_type=='Polygon']
    lo=max(lo+radius,radius);hi=min(hi-radius,W-radius)
    if lo>hi+1e-7:return None
    entries=[Point(lo+(hi-lo)*f,D-radius-1e-7)for f in [0,.25,.5,.75,1]]
    reached=[g for g in parts if any(g.buffer(1e-6).covers(p)for p in entries)];sites=[]
    for x0,y0,x1,y1 in beds:
        candidates=[Point(x,(y0+y1)/2)for x in [x0-radius-1e-5,x1+radius+1e-5]]if y1-y0>x1-x0 else[Point((x0+x1)/2,y)for y in [y0-radius-1e-5,y1+radius+1e-5]]
        available=[p for p in candidates if any(g.buffer(1e-7).covers(p)for g in reached)]
        if not available:return None
        sites.append(list(available[0].coords)[0])
    return sites
@lru_cache(None)
def furniture(W,D,lo,hi,k,c,kind):
    length,width,_=FURNITURE[kind];pad=c+.02
    for dx,dy in [(width,length),(length,width)]:
        for cols in range(1,k+1):
            nr=math.ceil(k/cols);sx=cols*dx+(cols-1)*pad;sy=nr*dy+(nr-1)*pad
            if sx>W+1e-8 or sy+pad>D+1e-8:continue
            for align in [0,.5,1]:
                start=(W-sx)*align
                beds=[[start+(i%cols)*(dx+pad),(i//cols)*(dy+pad),start+(i%cols)*(dx+pad)+dx,(i//cols)*(dy+pad)+dy]for i in range(k)]
                sites=paths(W,D,beds,lo,hi,c)
                if sites:return {'beds':beds,'access':sites}
    return None
def couples(members):
    # Only the explicit respondent/partner link is unambiguous in ego-relative data.
    ego=[i for i,m in enumerate(members)if m['ego_relation_code']==1]
    spouse=[i for i,m in enumerate(members)if m['ego_relation_code']==2]
    return {frozenset((ego[0],spouse[0]))}if len(ego)==len(spouse)==1 else set()
def care_links(w):
    byid={m['member_id']:i for i,m in enumerate(w['members'])};pairs=set();requests=[]
    c=w.get('care_contract',{})
    requests.extend((child,c.get('caregiver_id'))for child in c.get('home_care_child_ids',[]))
    for day in w.get('routine',{}).get('weekly_family_context',[]):
        requests.extend(day.get('child_bathing_assistants',{}).items())
    for child,adult in requests:
        if child in byid and adult in byid:
            i,j=byid[child],byid[adult]
            if w['members'][i]['age_years']<6 and w['members'][j]['age_years']>=18:pairs.add(frozenset((i,j)))
    return pairs

def subset_penalty(indices,members,known_couples,known_care):
    privacy=0;care=0;couple_room=0
    for i,j in itertools.combinations(indices,2):
        a,b=members[i],members[j]
        if frozenset((i,j))in known_couples:
            couple_room+=1
            continue
        if frozenset((i,j))in known_care:
            care+=1 # Given caregiver link supports a declared co-room scenario.
        elif a['age_years']<12 and b['age_years']<12:pass
        elif max(a['age_years'],b['age_years'])<18 and a['sex']==b['sex']:pass
        else:privacy+=1
    return privacy,care,couple_room
def assign_legacy(world,rows,clearance=.6):
    w=copy.deepcopy(world);hid=w['household_id'];members=w['members'];n=len(members);full=(1<<n)-1;dd=doors(rows)
    rooms=[r for r in w['layout']['rooms']if r['using_household_ids']==[hid]and r['census_room_class']=='bedroom']
    if not rooms:raise ValueError('NO_EXCLUSIVE_SLEEPING_ROOM:'+hid)
    rooms.sort(key=lambda r:r['room_id']);known=couples(members);care=care_links(w);options=[]
    for room in rooms:
        if room['room_id']not in dd:raise ValueError('NO_ROOM_PORTAL:'+room['room_id'])
        W,D,lo,hi,side=canonical(room,dd[room['room_id']]);args=tuple(round(x,7)for x in [W,D,lo,hi]);table={0:((0,0,0,0,0,0),None,[])}
        masks=range(1,full+1)if n<=8 else(sorted(sum(1<<i for i in inds)for k in range(1,min(n,max(3,math.ceil(n/len(rooms))+1))+1)for inds in itertools.combinations(range(n),k)))
        for mask in masks:
            inds=[i for i in range(n)if mask>>i&1];k=len(inds)
            minimum=12 if room['room_id']=='combined_bed_living'else 9 if k>1 else 5
            if room['usable_area_m2']+1e-6<minimum:continue
            choices=[]
            kinds=['single','bunk']+(['double']if k==2 and frozenset(inds)in known else[])
            for kind in kinds:
                eligible=[i for i in inds if 6<=members[i]['age_years']<60]
                for frames in range(math.ceil(k/FURNITURE[kind][2]),k+1):
                    upper=max(0,k-frames)if kind=='bunk'else 0
                    if kind=='single'and upper:continue
                    if kind=='double'and frames!=1:continue
                    if upper>len(eligible):continue
                    plan=furniture(*args,frames,clearance,kind)
                    if not plan:continue
                    privacy,care_shared,couple_room=subset_penalty(inds,members,known,care)
                    # Lexicographic: privacy; room crowding; bunk exposure; unused floor.
                    score=(privacy,-couple_room,-care_shared,k*k,upper,frames)
                    choices.append((score,{'kind':kind,'plan':plan,'side':side,'upper_needed':upper},inds));break
            if choices:table[mask]=min(choices,key=lambda x:x[0])
        options.append(table)
    if n>8:
        from scipy.optimize import milp,Bounds,LinearConstraint
        import numpy as np
        from scipy.sparse import lil_matrix
        candidates=[(j,mask,value)for j,table in enumerate(options)for mask,value in table.items()]
        matrix=lil_matrix((len(rooms)+n,len(candidates)));cost=[]
        for col,(j,mask,(score,option,inds))in enumerate(candidates):
            matrix[j,col]=1
            for i in inds:matrix[len(rooms)+i,col]=1
            privacy,couple,care,crowding,upper,frames=score
            cost.append(privacy*1e6+couple*1e4+care*100+crowding*10+upper*2+frames)
        result=milp(np.array(cost),integrality=np.ones(len(candidates)),bounds=Bounds(0,1),
            constraints=LinearConstraint(matrix.tocsc(),np.ones(len(rooms)+n),np.ones(len(rooms)+n)),options={'time_limit':30,'mip_rel_gap':0.})
        if result.status!=0:raise ValueError('NO_OPTIMAL_BOUNDED_GROUP_SLEEP_ASSIGNMENT:'+hid)
        chosen=sorted((candidates[i]for i,x in enumerate(result.x)if x>.5),key=lambda x:x[0])
        selected=[(rooms[j],v[1],v[2])for j,mask,v in chosen]
        score=tuple(sum(v[0][k]for j,mask,v in chosen)for k in range(6))
        states={full:(score,selected)}
    else:states={0:((0,0,0,0,0,0),[])}
    for room,table in([]if n>8 else zip(rooms,options)):
        new={}
        for used,(cost,chosen)in states.items():
            remaining=full^used;sub=remaining
            while True:
                if sub in table:
                    score,option,inds=table[sub];total=tuple(a+b for a,b in zip(cost,score));key=used|sub
                    candidate=(total,chosen+[(room,option,inds)])
                    if key not in new or candidate[0]<new[key][0]:new[key]=candidate
                if sub==0:break
                sub=(sub-1)&remaining
        states=new
    if full not in states:raise ValueError('NO_RELATIONSHIP_AWARE_FURNITURE_WITNESS:'+hid)
    score,selected=states[full];frames=[];berths=[];purposes=[];crowding=[]
    for room,option,inds in selected:
        rid=room['room_id'];purpose='sleeping'if inds else'given_study_storage_or_guest_room'
        purposes.append({'room_id':rid,'purpose':purpose,'member_ids':[members[i]['member_id']for i in inds],
            'source':'fixed-H7 reference use allocation;not observed room use'})
        if not inds:continue
        nf=len(option['plan']['beds']);upper_count=option['upper_needed']
        upper_ids=set(sorted((i for i in inds if 6<=members[i]['age_years']<60),key=lambda i:(members[i]['age_years']<18,members[i]['age_years'],members[i]['member_id']))[:upper_count])
        lower=[i for i in inds if i not in upper_ids];upper=sorted(upper_ids)
        local=[]
        for j,rect in enumerate(option['plan']['beds']):
            fid=f'{hid}:{rid}:v31-bed:{j+1}';access=option['plan']['access'][j]
            frame={'frame_id':fid,'room_id':rid,'kind':option['kind'],'outer_rect_m':rect_world(rect,room,option['side']),
                'reachable_access_point_m':list(point_world(*access,room,option['side'])),
                'center_longside_access_canonical_m':access,'nighttime_hall_use_is_declared_rights_scenario':False,
                'census_H7_class_unchanged':True,'ladder_can_be_oriented_to_reachable_center_longside':option['kind']=='bunk'}
            frames.append(frame);local.append(fid)
        if option['kind']=='double':
            for slot,i in enumerate(inds):
                m=members[i];m['reference_home_room_id']=rid
                berths.append({'member_id':m['member_id'],'age_years':m['age_years'],'room_id':rid,'frame_id':local[0],'level':0,'horizontal_berth_slot':slot})
        for level,indices in([]if option['kind']=='double'else[(0,lower),(1,upper)]):
            for j,i in enumerate(indices):
                m=members[i];m['reference_home_room_id']=rid
                berths.append({'member_id':m['member_id'],'age_years':m['age_years'],'room_id':rid,'frame_id':local[j],'level':level})
        priv,care_shared,couple_room=subset_penalty(inds,members,known,care)
        if priv>0:crowding.append({'room_id':rid,'unavoidable_shared_privacy_pairs_under_given_geometry':priv,'persons':len(inds)})
    reference={'found':True,'frames':frames,'berths':berths,'clearance_m':clearance,'room_purposes':purposes,
        'allocation_method':'exhaustive subset dynamic program for N<=8;bounded-size subset set-partition MILP for larger households',
        'larger_household_group_size_limit':max(3,math.ceil(n/len(rooms))+1)if n>8 else None,
        'double_bed_geometry':'given2.05x1.54m reference for an explicitly linked adult couple;not an OEM claim',
        'objective_lexicographic':list(score),'known_couple_links':[sorted(members[i]['member_id']for i in pair)for pair in known],
        'given_care_links':[sorted(members[i]['member_id']for i in pair)for pair in care],
        'care_co_room_preference_is_design_not_observed_sleep_or_extra_care_obligation':True,
        'unknown_other_pairwise_parentage_or_partnership_not_imputed':True,'privacy_reference':'adapted EU-SILC minimum-room categories;not Chinese observed prevalence',
        'room_area_5_single_9_double_is_historical_design_diagnostic_not_exclusion':True,
        'privacy_pressure':crowding,'privacy_pairs_globally_minimized_at_selected_geometry':True,
        'reference_design_not_observed_furniture_stock':True,'N_and_H7_and_H6_and_q_preserved':True,
        'upper_age_source_minimum6_and_design_maximum59':True,'bunk_height_m':1.305,'bunk_max_mattress_thickness_m':.11,
        'bunk_static_load_source_limit_kg':100,'unknown_body_load_and_mobility_not_admitted_by_geometry':True,
        'temporary_hall_sleepers':0,'new_bunk_frames':sum(f['kind']=='bunk'for f in frames)}
    w['layout']['sleep_reference']=reference
    for room in w['layout']['rooms']:
        if room['room_id']in{p['room_id']for p in purposes}:room['given_room_purpose']=next(p['purpose']for p in purposes if p['room_id']==room['room_id'])
    if len(berths)!=n or len({b['member_id']for b in berths})!=n:raise AssertionError('MEMBER_BERTH_COVERAGE')
    return w

def assign(world,rows,clearance=.6):
    from sleep_packing import assign as mixed_assign
    return mixed_assign(world,rows,clearance)
