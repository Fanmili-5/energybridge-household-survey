"""Mixed adult/child bed packing coupled to household room assignment.

Dimensions are explicit reference envelopes, not a product or safety certificate.
Cribs are never assigned to adults; double frames require a known adult couple;
upper bunks require an explicitly eligible6--59-year-old reference occupant.
"""
import copy,itertools,math
from functools import lru_cache
from room_assignment import doors,canonical,paths,rect_world,point_world,couples,care_links,subset_penalty

SIZES={'single':(2.05,.94),'bunk':(2.07,.965),'double':(2.05,1.54),'crib':(1.30,.70)}


def configurations(indices,members,known):
    if not indices:yield [];return
    i,*rest=indices;age=members[i]['age_years'];kind='crib'if age<3 else'single'
    for tail in configurations(rest,members,known):yield [(kind,[i])]+tail
    for j in rest:
        b=members[j]['age_years'];remaining=[k for k in rest if k!=j]
        if frozenset((i,j))in known and min(age,b)>=18:
            for tail in configurations(remaining,members,known):yield [('double',[i,j])]+tail
        if min(age,b)>=3 and(6<=age<60 or 6<=b<60):
            upper=i if 6<=age<60 else j;lower=j if upper==i else i
            for tail in configurations(remaining,members,known):yield [('bunk',[lower,upper])]+tail


@lru_cache(maxsize=100000)
def pack(W,D,lo,hi,kinds,clearance):
    gap=clearance+.02;n=len(kinds)
    if sum(SIZES[k][0]*SIZES[k][1]for k in kinds)>W*D+1e-8:return None
    for perm in itertools.permutations(range(n)):
        # Equivalent frames need not be permuted among themselves.
        if any(kinds[perm[j]]==kinds[perm[j-1]]and perm[j]<perm[j-1]for j in range(1,n)):continue
        for turns in itertools.product((0,1),repeat=n):
            dims=[]
            for i in perm:
                a,b=SIZES[kinds[i]];dims.append((a,b)if turns[i]else(b,a))
            for cuts in range(1<<max(0,n-1)):
                groups=[];start=0
                for j in range(n):
                    if j==n-1 or cuts>>j&1:groups.append(list(range(start,j+1)));start=j+1
                widths=[sum(dims[j][0]for j in g)+gap*(len(g)-1)for g in groups]
                heights=[max(dims[j][1]for j in g)for g in groups]
                if max(widths,default=0)>W+1e-7 or sum(heights)+gap*(len(groups)-1)+clearance>D+1e-7:continue
                for align in(0.,.5,1.):
                    boxes=[];order=[];y=0.
                    for g,width,height in zip(groups,widths,heights):
                        x=(W-width)*align
                        for j in g:
                            dx,dy=dims[j];boxes.append([x,y,x+dx,y+dy]);order.append(perm[j]);x+=dx+gap
                        y+=height+gap
                    access=paths(W,D,boxes,lo,hi,clearance)
                    if access:return {'beds':boxes,'access':access,'configuration_order':order}
    return None


def assign(world,rows,clearance=.6):
    w=copy.deepcopy(world);hid=w['household_id'];members=w['members'];n=len(members);dd=doors(rows)
    rooms=sorted((r for r in w['layout']['rooms']if r['census_room_class']=='bedroom'and r['using_household_ids']==[hid]),key=lambda r:r['room_id'])
    known=couples(members);care=care_links(w);limit=n if n<=8 else min(n,max(3,math.ceil(n/len(rooms))+1));tables=[]
    for room in rooms:
        if room['room_id']not in dd:raise ValueError('NO_SLEEP_ROOM_DOOR:'+room['room_id'])
        W,D,lo,hi,side=canonical(room,dd[room['room_id']]);coords=tuple(round(x,7)for x in(W,D,lo,hi));table={0:((0,0,0,0,0,0),None,[])}
        for k in range(1,limit+1):
            minimum=12 if room['room_id']=='combined_bed_living'else 5 if k==1 else 9
            if room['usable_area_m2']+1e-6<minimum:continue
            for inds in itertools.combinations(range(n),k):
                choices=[]
                configs=sorted(configurations(list(inds),members,known),key=lambda c:(sum(t=='bunk'for t,_ in c),len(c)))
                for config in configs:
                    kinds=tuple(t for t,_ in config);layout=pack(*coords,kinds,clearance)
                    if not layout:continue
                    privacy,care_shared,couple_room=subset_penalty(inds,members,known,care)
                    upper=sum(t=='bunk'for t,_ in config)
                    score=(privacy,-couple_room,-care_shared,k*k,upper,len(config))
                    choices.append((score,{'plan':layout,'config':config,'side':side},list(inds)))
                    break # sorted by all configuration-dependent score terms
                if choices:table[sum(1<<i for i in inds)]=min(choices,key=lambda x:x[0])
        tables.append(table)
    full=(1<<n)-1
    if n<=8:
        states={0:((0,0,0,0,0,0),[])}
        for room,table in zip(rooms,tables):
            new={}
            for used,(score,selected)in states.items():
                for mask,(cost,option,inds)in table.items():
                    if used&mask:continue
                    key=used|mask;total=tuple(a+b for a,b in zip(score,cost))
                    if key not in new or total<new[key][0]:new[key]=(total,selected+[(room,option,inds)])
            states=new
        if full not in states:raise ValueError('NO_MIXED_BED_ROOM_ASSIGNMENT:'+hid)
        score,selected=states[full]
    else:
        import numpy as np
        from scipy.optimize import milp,Bounds,LinearConstraint
        from scipy.sparse import lil_matrix
        options=[(j,mask,value)for j,table in enumerate(tables)for mask,value in table.items()];A=lil_matrix((len(rooms)+n,len(options)));cost=[]
        for col,(j,mask,(score,option,inds))in enumerate(options):
            A[j,col]=1
            for i in inds:A[len(rooms)+i,col]=1
            p,co,ca,c,u,f=score;cost.append(p*1e6+co*1e4+ca*100+c*10+u*2+f)
        result=milp(np.array(cost),integrality=np.ones(len(options)),bounds=Bounds(0,1),
            constraints=LinearConstraint(A.tocsc(),np.ones(len(rooms)+n),np.ones(len(rooms)+n)),options={'time_limit':20,'mip_rel_gap':0.})
        if result.status!=0:raise ValueError('NO_MIXED_BED_MILP_ASSIGNMENT:'+hid)
        chosen=sorted((options[i]for i,x in enumerate(result.x)if x>.5),key=lambda x:x[0]);selected=[(rooms[j],v[1],v[2])for j,mask,v in chosen]
        score=tuple(sum(v[0][k]for j,mask,v in chosen)for k in range(6))
    frames=[];berths=[];purposes=[];crowding=[]
    for room,option,inds in selected:
        rid=room['room_id'];purposes.append({'room_id':rid,'purpose':'sleeping'if inds else'given_study_storage_or_guest_room','member_ids':[members[i]['member_id']for i in inds]})
        if not option:continue
        plan=option['plan']
        for j,(rect,access,ci)in enumerate(zip(plan['beds'],plan['access'],plan['configuration_order'])):
            kind,occupants=option['config'][ci];fid=f'{hid}:{rid}:v33-bed:{j+1}'
            frames.append({'frame_id':fid,'room_id':rid,'kind':kind,'outer_rect_m':rect_world(rect,room,option['side']),
                'reachable_access_point_m':list(point_world(*access,room,option['side'])),
                'reference_dimension_m':list(SIZES[kind]),'geometry_is_product_or_safe_sleep_certification':False})
            for slot,i in enumerate(occupants):
                m=members[i];m['reference_home_room_id']=rid
                berths.append({'member_id':m['member_id'],'age_years':m['age_years'],'room_id':rid,'frame_id':fid,
                    'level':slot if kind=='bunk'else 0,'horizontal_berth_slot':slot if kind=='double'else 0})
        privacy,_,_=subset_penalty(inds,members,known,care)
        if privacy:crowding.append({'room_id':rid,'unavoidable_shared_privacy_pairs_under_given_geometry':privacy,'persons':len(inds)})
    w['layout']['sleep_reference']={'found':True,'frames':frames,'berths':berths,'clearance_m':clearance,'room_purposes':purposes,
        'allocation_method':'mixed bed configurations plus room set partition;N<=8 full subsets;larger households bounded groups with optimal MILP',
        'larger_household_maximum_group_size':limit if n>8 else None,'objective_lexicographic':list(score),
        'known_couple_links':[sorted(members[i]['member_id']for i in p)for p in known],
        'given_care_links':[sorted(members[i]['member_id']for i in p)for p in care],
        'unknown_other_pairwise_parentage_or_partnership_not_imputed':True,'privacy_pressure':crowding,
        'reference_design_not_observed_furniture_stock':True,'temporary_hall_sleepers':0,
        'new_bunk_frames':sum(f['kind']=='bunk'for f in frames),'upper_age_minimum6_maximum59_is_design':True,
        'crib_under3_reference_only_not_safety_certificate':True,'reference_frame_dimensions':SIZES,
        'bunk_height_m':1.305,'bunk_max_mattress_thickness_m':.11}
    if len(berths)!=n or len({b['member_id']for b in berths})!=n:raise ValueError('SLEEP_COVERAGE')
    return w
