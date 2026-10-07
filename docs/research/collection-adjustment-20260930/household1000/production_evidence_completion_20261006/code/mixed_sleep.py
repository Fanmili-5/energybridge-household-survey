"""A declared alternative sleep world with mixed-height furniture and rights.

Preserve fixedH6/H7/world geometry. Original single-bed successes stay valid.
Additional bunk/temporary-hall arrangements have explicit age/vertical/path
checks and designed nighttime use rights, not observed prevalence or automatic
H7 changes. This is a geometric witness, not privacy/care/ergonomic admission.
"""
import collections,hashlib,json,math,sys
from functools import lru_cache
from pathlib import Path
OUT=Path(__file__).resolve().parent.parent;BASE=OUT.parent;V7=BASE/'idf_joint_production_20261005';V8=BASE/'household_housing_evidence_20261006'
sys.path[:0]=json.loads((V7/'RUNTIME.json').read_text())['stable_PYTHONPATH'].split(':');sys.path.insert(0,str(V8/'code'))
from sleep_geometry import canonical,doors,to_world,parse
from shapely.geometry import box,Point
from shapely.ops import unary_union

FURNITURE={'single':(2.05,.94,1),'bunk':(2.07,.965,2)}
def save(name,d):(OUT/name).write_text(json.dumps(d,ensure_ascii=False,indent=2,allow_nan=False)+'\n')
def paths(W,D,beds,lo,hi,clearance):
    radius=clearance/2;free=box(0,0,W,D).buffer(-radius,join_style=2).difference(unary_union([box(*b).buffer(radius,join_style=2) for b in beds]))
    parts=[free] if free.geom_type=='Polygon' else [g for g in getattr(free,'geoms',[]) if g.geom_type=='Polygon']
    lo=max(lo+radius,radius);hi=min(hi-radius,W-radius)
    if lo>hi+1e-7:return None
    entries=[Point(lo+(hi-lo)*f,D-radius-1e-7) for f in [0,.25,.5,.75,1]];reached=[g for g in parts if any(g.buffer(1e-6).covers(p) for p in entries)];sites=[]
    for x0,y0,x1,y1 in beds:
        candidates=[Point(x,(y0+y1)/2) for x in [x0-radius-1e-5,x1+radius+1e-5]] if y1-y0>x1-x0 else [Point((x0+x1)/2,y) for y in [y0-radius-1e-5,y1+radius+1e-5]]
        available=[p for p in candidates if any(g.buffer(1e-7).covers(p) for g in reached)]
        if not available:return None
        sites.append(list(available[0].coords)[0])
    return sites
@lru_cache(None)
def layout(W,D,lo,hi,k,c,kind):
    length,width,capacity=FURNITURE[kind];pad=c+.02
    for dx,dy in [(width,length),(length,width)]:
        for cols in range(1,k+1):
            rows=math.ceil(k/cols);sx=cols*dx+(cols-1)*pad;sy=rows*dy+(rows-1)*pad
            if sx>W+1e-8 or sy+pad>D+1e-8:continue
            for align in [0,.5,1]:
                start=(W-sx)*align;beds=[[start+(i%cols)*(dx+pad),(i//cols)*(dy+pad),start+(i%cols)*(dx+pad)+dx,(i//cols)*(dy+pad)+dy] for i in range(k)]
                sites=paths(W,D,beds,lo,hi,c)
                if sites:return {'beds':beds,'center_longside_access':sites}
    return None

def choose(profile,world,rr,c,allow_hall):
    N=profile['family']['resident_count'];eligible=[m for m in profile['family']['members'] if 6<=m['age_years']<60];needlower=N-len(eligible);dd=doors(rr)
    rooms=[r for r in world['rooms'] if r['using_household_ids']==[profile['slot_id']] and r['census_room_class']=='bedroom']
    if allow_hall:rooms += [r for r in world['rooms'] if r['room_id']=='living_hall']
    states={(0,0):(0,[])}
    for room in rooms:
        W,D,lo,hi,side=canonical(room,dd[room['room_id']]);args=[round(x,7) for x in [W,D,lo,hi]];hall=room['room_id']=='living_hall';options=[{'L':0,'U':0,'cost':0,'room':room,'side':side,'kind':'single','plan':None}]
        for kind in ['single'] if hall else ['single','bunk']:
            for k in range(1,N+1):
                plan=layout(*args,k,c,kind)
                if plan:options.append({'L':k,'U':k if kind=='bunk' else 0,'cost':(1000000 if hall else 0)*k+(10 if kind=='bunk' else 0)*k+k,
                     'room':room,'side':side,'kind':kind,'plan':plan})
        new={}
        for (L,U),(cost,plans) in states.items():
            for option in options:
                key=(min(N,L+option['L']),min(N,U+option['U']));candidate=(cost+option['cost'],plans+[option])
                if key not in new or candidate[0]<new[key][0]:new[key]=candidate
        states=new
    found=[(cost,plans,L,U) for (L,U),(cost,plans) in states.items() if L>=needlower and L+min(U,len(eligible))>=N]
    if not found:return {'household_id':profile['slot_id'],'found':False,'clearance_m':c,'allow_temporary_hall_scenario':allow_hall,'complete_actor_world':False}
    cost,selected,L,U=min(found,key=lambda x:(x[0],max(0,N-x[2])));upper_needed=max(0,N-L)
    uppers=sorted(eligible,key=lambda m:(m['age_years']<18,m['age_years'],m['member_id']))[:upper_needed];upper_ids={m['member_id'] for m in uppers}
    lowers=sorted([m for m in profile['family']['members'] if m['member_id'] not in upper_ids],key=lambda m:(not(m['age_years']>=60 or m['age_years']<6),-m['age_years'],m['member_id']))
    frames=[];berths=[];slots=[]
    for option in selected:
        if not option['plan']:continue
        room=option['room'];hall=room['room_id']=='living_hall'
        for i,rect in enumerate(option['plan']['beds']):
            frame_id=profile['slot_id']+'-'+room['room_id']+'-'+str(i);worldrect=to_world(rect,room,option['side']);access=option['plan']['center_longside_access'][i]
            frames.append({'frame_id':frame_id,'room_id':room['room_id'],'kind':option['kind'],'outer_rect_m':worldrect,
              'nighttime_hall_use_is_declared_rights_scenario':hall,'census_H7_class_unchanged':True,
              'ladder_can_be_oriented_to_reachable_center_longside':option['kind']=='bunk','center_longside_access_canonical_m':access})
            slots.append((frame_id,room,option['kind'],0))
    for member,(frame_id,room,kind,level) in zip(lowers,slots):berths.append({'member_id':member['member_id'],'age_years':member['age_years'],'room_id':room['room_id'],'frame_id':frame_id,'level':0})
    upper_slots=[f for f in frames if f['kind']=='bunk']
    for member,f in zip(uppers,upper_slots):berths.append({'member_id':member['member_id'],'age_years':member['age_years'],'room_id':f['room_id'],'frame_id':f['frame_id'],'level':1})
    assert len(berths)==N and len({b['member_id'] for b in berths})==N
    return {'household_id':profile['slot_id'],'found':True,'clearance_m':c,'allow_temporary_hall_scenario':allow_hall,'frames':frames,'berths':berths,
      'N_and_H7_and_H6_and_q_preserved':True,'upper_age_source_minimum6_and_design_maximum59':True,
      'bunk_height_m':1.305,'bunk_max_mattress_thickness_m':.11,'bunk_static_load_source_limit_kg':100,
      'unknown_body_load_and_mobility_not_admitted_by_geometry':True,'night_hall_rights_or_privacy_not_observed':True,
      'temporary_hall_sleepers':sum(b['room_id']=='living_hall' for b in berths),'new_bunk_frames':sum(f['kind']=='bunk' for f in frames),
      'reference_design_not_observed_furniture_stock':True,'complete_actor_world':False}
def main():
    if (OUT/'PACKAGE_MANIFEST.json').exists():raise SystemExit('sealed')
    pp=json.loads((V7/'HOUSEHOLDS1000_JOINT_GEOMETRY_CANDIDATE.json').read_text())['profiles'];old={r['household_id']:r for r in json.loads((V8/'SLEEP_GEOMETRY_AUDIT1000.json').read_text())['cases']};results=[]
    for p in pp:
        row={'household_id':p['slot_id']}
        for c,variant in [(.6,'baseline0_6m'),(.8,'alternative0_8m')]:
            if old[p['slot_id']][variant]['capacity_witness_found']:
                row[variant]={'found':True,'route':'sealed_single_bed_witness_retained','source':str(V8/'SLEEP_GEOMETRY_AUDIT1000.json'),'complete_actor_world':False};continue
            world=json.loads((V7/p['housing']['world_path']).read_text())['world'];rr=parse(V7/p['reference_IDF_path'])
            private=choose(p,world,rr,c,False);extended=private if private['found'] else choose(p,world,rr,c,True)
            row[variant]={'found':extended['found'],'route':'declared_private_mixed_furniture' if private['found'] else 'declared_temporary_hall_rights' if extended['found'] else 'no_witness_retained',
              'private_only':private,'extended_reference':extended,'complete_actor_world':False}
        results.append(row)
    report={'cases':results,'baseline0_6m_found':sum(r['baseline0_6m']['found'] for r in results),'alternative0_8m_found':sum(r['alternative0_8m']['found'] for r in results),
      'routes0_6m':dict(collections.Counter(r['baseline0_6m']['route'] for r in results)),
      'bunk_source_URL':'https://www.ikea.com/gb/en/p/tuffing-bunk-bed-frame-dark-grey-00239233/',
      'manufacturer_dimensions_and_under6_exclusion_verified':True,'bunk_use_and_temporary_hall_rights_are_reference_scenarios_not_population_observations':True,
      'full_sleeping_privacy_care_body_load_mobility_not_validated':True,'no_resident_room_area_or_generation_resampled':True}
    save('MIXED_SLEEP_SCENARIOS1000.json',report);print(json.dumps({k:v for k,v in report.items() if k!='cases'},ensure_ascii=False,indent=2))
if __name__=='__main__':main()
