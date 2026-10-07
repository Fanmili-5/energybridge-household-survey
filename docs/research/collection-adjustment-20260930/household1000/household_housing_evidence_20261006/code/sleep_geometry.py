"""Constructive sleeping-capacity witnesses using actualIDF door positions.

Bed frame footprint2.05x0.94m is manufacturer geometry, not Chinese ownership.
Clearance0.6/0.8m are declared engineering alternatives, not compliance rules.
No-witness is failure of this finite layout search, not proof of uninhabitability.
"""
import collections,hashlib,json,math,re,sys
from pathlib import Path
from functools import lru_cache

OUT=Path(__file__).resolve().parent.parent;BASE=OUT.parent
sys.path[:0]=json.loads((BASE/'idf_joint_production_20261005/RUNTIME.json').read_text())['stable_PYTHONPATH'].split(':')
from shapely.geometry import box,Point
from shapely.ops import unary_union

BED_LENGTH=2.05;BED_WIDTH=.94
def parse(p):return [[v.strip() for v in q.split(',')] for q in re.sub(r'!.*','',p.read_text()).split(';') if q.strip()]
def save(name,d):(OUT/name).write_text(json.dumps(d,ensure_ascii=False,indent=2,allow_nan=False)+'\n')
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()

def connectivity(W,D,beds,door,clearance):
    radius=clearance/2
    domain=box(0,0,W,D).buffer(-radius,join_style=2)
    free=domain.difference(unary_union([box(*b).buffer(radius,join_style=2) for b in beds]))
    components=[free] if free.geom_type=='Polygon' else [g for g in getattr(free,'geoms',[]) if g.geom_type=='Polygon']
    lo=max(door[0]+radius,radius);hi=min(door[1]-radius,W-radius)
    if lo>hi+1e-7:return False,None
    entries=[Point(lo+(hi-lo)*f,D-radius-1e-7) for f in [0,.25,.5,.75,1]]
    reached=[g for g in components if any(g.buffer(1e-6).covers(p) for p in entries)]
    if not reached:return False,None
    sites=[]
    for x0,y0,x1,y1 in beds:
        longY=y1-y0>x1-x0
        pts=[Point(x,y0+(y1-y0)*f) for x in [x0-radius-1e-5,x1+radius+1e-5] for f in [.25,.5,.75]] if longY else [Point(x0+(x1-x0)*f,y) for y in [y0-radius-1e-5,y1+radius+1e-5] for f in [.25,.5,.75]]
        accessible=[p for p in pts if any(g.buffer(1e-7).covers(p) for g in reached)]
        if not accessible:return False,None
        sites.append(list(accessible[0].coords)[0])
    return True,sites

@lru_cache(None)
def layout(W,D,doorlo,doorhi,k,clearance):
    pad=clearance+.02
    for dx,dy in [(BED_WIDTH,BED_LENGTH),(BED_LENGTH,BED_WIDTH)]:
        for columns in range(1,k+1):
            rows=math.ceil(k/columns);spanX=columns*dx+(columns-1)*pad;spanY=rows*dy+(rows-1)*pad
            if spanX>W+1e-8 or spanY+pad>D+1e-8:continue
            for align in [0,.5,1]:
                xstart=(W-spanX)*align
                beds=[[xstart+(i%columns)*(dx+pad),(i//columns)*(dy+pad),xstart+(i%columns)*(dx+pad)+dx,(i//columns)*(dy+pad)+dy] for i in range(k)]
                passed,sites=connectivity(W,D,beds,(doorlo,doorhi),clearance)
                if passed:return {'beds_canonical_rects_m':beds,'reachable_longside_center_points_m':sites,
                  'door_canonical_interval_m':[doorlo,doorhi],'clearance_reference_m':clearance}
    return None

def doors(rows):
    parents={r[1]:r[4] for r in rows if r[0]=='BuildingSurface:Detailed'};result={}
    for r in rows:
        if r[0]=='FenestrationSurface:Detailed' and r[2]=='Door' and not r[1].endswith('_peer') and r[1]!='entry_door':
            v=[list(map(float,r[j:j+3])) for j in range(10,len(r),3)];result[parents[r[4]]]=v
    return result

def canonical(room,verts):
    x0,y0,x1,y1=room['usable_rect_m'];W=x1-x0;D=y1-y0
    xs=[v[0] for v in verts];ys=[v[1] for v in verts]
    if max(xs)-min(xs)>.1:
        side='north' if abs(ys[0]-y1)<abs(ys[0]-y0) else 'south';lo=max(0,min(xs)-x0);hi=min(W,max(xs)-x0)
    else:
        side='east' if abs(xs[0]-x1)<abs(xs[0]-x0) else 'west';lo=max(0,min(ys)-y0);hi=min(D,max(ys)-y0);W,D=D,W
    return W,D,lo,hi,side

def to_world(rect,room,side):
    x0,y0,x1,y1=room['usable_rect_m'];W=x1-x0;D=y1-y0
    def point(x,y):
        if side=='north':return x0+x,y0+y
        if side=='south':return x0+x,y1-y
        if side=='east':return x0+y,y0+x
        return x1-y,y0+x
    coords=[point(x,y) for x,y in [(rect[0],rect[1]),(rect[2],rect[3])]]
    return [min(p[0] for p in coords),min(p[1] for p in coords),max(p[0] for p in coords),max(p[1] for p in coords)]

def evaluate(profile,world,rows,clearance=.6):
    household=profile['slot_id'];N=profile['family']['resident_count'];door=doors(rows)
    rooms=[r for r in world['rooms'] if r['using_household_ids']==[household] and r['census_room_class']=='bedroom']
    capacities=[]
    for room in rooms:
        W,D,lo,hi,side=canonical(room,door[room['room_id']]);args=[round(v,7) for v in [W,D,lo,hi]]
        found={k:layout(*args,k,clearance) for k in range(1,N+1)};cap=max([0]+[k for k,v in found.items() if v])
        capacities.append({'room':room,'side':side,'capacity':cap,'layouts':found})
    total=sum(d['capacity'] for d in capacities);members=sorted(profile['family']['members'],key=lambda m:(-m['generation_level'],m['member_id']));remaining=members[:];placed=[]
    # Allocation is a reference witness; mixing generations is separately
    # reported and does not invent missing spouse or biological parent links.
    for data in sorted(capacities,key=lambda d:(-d['capacity'],d['room']['room_id'])):
        k=min(len(remaining),data['capacity'])
        if not k:continue
        chosen=data['layouts'][k];assigned=remaining[:k];remaining=remaining[k:]
        for member,rect in zip(assigned,chosen['beds_canonical_rects_m']):
            placed.append({'member_id':member['member_id'],'generation_level':member['generation_level'],'age_years':member['age_years'],
              'room_id':data['room']['room_id'],'bed_outer_rect_m':to_world(rect,data['room'],data['side']),
              'sleep_position_evidence':'new_constructive_reference_design_not_observed','one_single_reference_bed_per_member':True})
    mixing=sum(len({b['generation_level'] for b in placed if b['room_id']==r['room_id']})>1 for r in rooms)
    minors=any(m['age_years']<18 for m in members)
    return {'household_id':household,'N':N,'G':profile['family']['generation_count'],'H7':world['target_H7'],'q_reference':world['shared_household_count_design'],
      'clearance_reference_m':clearance,'constructive_private_single_bed_capacity':total,'capacity_witness_found':total>=N and len(placed)==N,
      'room_capacities':{d['room']['room_id']:d['capacity'] for d in capacities},'beds':placed,
      'rooms_with_generation_mixing_in_this_design':mixing,'minors_need_separate_care_world':minors,
      'failure_is_finite_search_no_witness_not_proof_house_uninhabitable':True,
      'privacy_care_kitchen_activity_and_installed_services_complete':False,'actor_ready':False}

def main():
    from evidence_guard import ensure_unsealed
    ensure_unsealed(OUT)
    source=BASE/'idf_joint_production_20261005';pp=json.loads((source/'HOUSEHOLDS1000_JOINT_GEOMETRY_CANDIDATE.json').read_text())['profiles'];results=[]
    for p in pp:
        world=json.loads((source/p['housing']['world_path']).read_text())['world'];path=source/p['reference_IDF_path'];rs=parse(path)
        a=evaluate(p,world,rs,.6);b=evaluate(p,world,rs,.8)
        results.append({'household_id':p['slot_id'],'input_world_sha256':sha(source/p['housing']['world_path']),
          'input_IDF_sha256':sha(path),'baseline0_6m':a,'alternative0_8m':b})
    summary={'cases':results,'households_audited':1000,'bed_outer_footprint_m':[BED_LENGTH,BED_WIDTH],
      'bed_dimension_source':'IKEA NEIDEN article403.952.45 original manufacturer dimensions, single reference furniture scenario; no ownership frequency claim',
      'bed_dimension_URL':'https://www.ikea.com/nl/en/p/neiden-bed-frame-pine-40395245/',
      'baseline0_6m_witness_found':sum(d['baseline0_6m']['capacity_witness_found'] for d in results),
      'alternative0_8m_witness_found':sum(d['alternative0_8m']['capacity_witness_found'] for d in results),
      'clearance_scenarios_are_engineering_not_regulatory_requirements':True,
      'single_bed_arrangement_is_reference_not_all_possible_sleeping_arrangements':True,
      'no_world_or_household_resampled_or_modified':True,'complete_actor_packages':0}
    save('SLEEP_GEOMETRY_AUDIT1000.json',summary)
    print(json.dumps({k:v for k,v in summary.items() if k!='cases'},ensure_ascii=False,indent=2))

if __name__=='__main__':main()
