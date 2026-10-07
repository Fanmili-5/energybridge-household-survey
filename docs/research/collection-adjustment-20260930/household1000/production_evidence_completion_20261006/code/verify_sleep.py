"""Independent world-coordinate verification; never invokes layout generation.

Horizontal clearance checks use actual IDF doors and all furniture obstacles.
They do not establish bed load, climbing ability, door swing, care or privacy.
"""
import collections,json,re,sys
from pathlib import Path
OUT=Path(__file__).resolve().parent.parent;BASE=OUT.parent;V7=BASE/'idf_joint_production_20261005';V8=BASE/'household_housing_evidence_20261006'
sys.path[:0]=json.loads((V7/'RUNTIME.json').read_text())['stable_PYTHONPATH'].split(':')
from shapely.geometry import box,Point
from shapely.ops import unary_union
def read(p):return json.loads(p.read_text())
def idf_doors(p):
 rows=[[v.strip() for v in q.split(',')] for q in re.sub(r'!.*','',p.read_text()).split(';') if q.strip()]
 parents={r[1]:r[4] for r in rows if r[0]=='BuildingSurface:Detailed'}
 return {parents[r[4]]:[list(map(float,r[j:j+3])) for j in range(10,len(r),3)] for r in rows if r[0]=='FenestrationSurface:Detailed' and r[2]=='Door' and not r[1].endswith('_peer') and r[1]!='entry_door'}
def room_errors(room,verts,frames,c):
 errors=[];boundary=box(*room['usable_rect_m']);x0,y0,x1,y1=room['usable_rect_m'];radius=c/2
 shapes=[box(*f['outer_rect_m']) for f in frames]
 for i,(f,sh) in enumerate(zip(frames,shapes)):
  if not boundary.buffer(1e-6).covers(sh):errors.append('furniture_outside_usable_room')
  dims=sorted([sh.bounds[2]-sh.bounds[0],sh.bounds[3]-sh.bounds[1]]);wanted=sorted([2.07,.965] if f['kind']=='bunk' else [2.05,.94])
  if max(abs(a-b) for a,b in zip(dims,wanted))>1e-6:errors.append('manufacturer_frame_dimension_mismatch')
  if any(sh.intersection(other).area>1e-7 for other in shapes[:i]):errors.append('floor_frame_overlap')
 domain=boundary.buffer(-radius,join_style=2).difference(unary_union([s.buffer(radius,join_style=2) for s in shapes]));parts=[domain] if domain.geom_type=='Polygon' else [g for g in getattr(domain,'geoms',[]) if g.geom_type=='Polygon']
 dx=max(v[0] for v in verts)-min(v[0] for v in verts)
 if dx>.1:
  y=sum(v[1] for v in verts)/len(verts);north=abs(y-y1)<abs(y-y0);lo=max(min(v[0] for v in verts)+radius,x0+radius);hi=min(max(v[0] for v in verts)-radius,x1-radius)
  entries=[Point(lo+(hi-lo)*t,y1-radius-1e-7 if north else y0+radius+1e-7) for t in [0,.25,.5,.75,1]] if lo<=hi+1e-7 else []
 else:
  x=sum(v[0] for v in verts)/len(verts);east=abs(x-x1)<abs(x-x0);lo=max(min(v[1] for v in verts)+radius,y0+radius);hi=min(max(v[1] for v in verts)-radius,y1-radius)
  entries=[Point(x1-radius-1e-7 if east else x0+radius+1e-7,lo+(hi-lo)*t) for t in [0,.25,.5,.75,1]] if lo<=hi+1e-7 else []
 reached=[g for g in parts if any(g.buffer(1e-6).covers(p) for p in entries)]
 if not reached:errors.append('actual_IDF_door_entry_blocked')
 for f in frames:
  a,b,d,e=f['outer_rect_m'];long_y=e-b>d-a;fractions=[.5] if f['kind']=='bunk' else [.25,.5,.75]
  sites=[Point(t,b+(e-b)*v) for t in [a-radius-1e-5,d+radius+1e-5] for v in fractions] if long_y else [Point(a+(d-a)*v,t) for t in [b-radius-1e-5,e+radius+1e-5] for v in fractions]
  if not any(g.buffer(1e-7).covers(p) for g in reached for p in sites):errors.append('no_reachable_longside_or_center_ladder')
 return errors
def check_case(profile,world,door,frames,berths,c):
 errors=[];roster={m['member_id']:m for m in profile['family']['members']};rooms={r['room_id']:r for r in world['rooms']}
 if len(berths)!=len(roster) or collections.Counter(b['member_id'] for b in berths)!=collections.Counter(roster.keys()):errors.append('resident_roster_not_exactly_once')
 ff={f['frame_id']:f for f in frames}
 if len(ff)!=len(frames):errors.append('duplicate_frame_ID')
 levels=set()
 for b in berths:
  if b['frame_id'] not in ff or b['member_id'] not in roster:errors.append('unknown_berth_reference');continue
  f=ff[b['frame_id']];level=b['level'];key=(b['frame_id'],level)
  if key in levels:errors.append('duplicate_occupied_berth');
  levels.add(key)
  if b['room_id']!=f['room_id'] or level not in ([0,1] if f['kind']=='bunk' else [0]):errors.append('invalid_frame_room_or_level')
  if level==1 and not 6<=roster[b['member_id']]['age_years']<60:errors.append('upper_age_restriction_failed')
 for room_id in set(f['room_id'] for f in frames):
  r=rooms[room_id];fs=[f for f in frames if f['room_id']==room_id]
  if r['census_room_class']!='bedroom' and room_id!='living_hall':errors.append('undeclared_sleep_room_type')
  if room_id=='living_hall' and any(not f.get('nighttime_hall_use_is_declared_rights_scenario') for f in fs):errors.append('hall_use_right_not_declared')
  errors+=room_errors(r,door[room_id],fs,c)
 return errors
def main():
 if (OUT/'PACKAGE_MANIFEST.json').exists():raise SystemExit('sealed')
 pp=read(V7/'HOUSEHOLDS1000_JOINT_GEOMETRY_CANDIDATE.json')['profiles'];old={r['household_id']:r for r in read(V8/'SLEEP_GEOMETRY_AUDIT1000.json')['cases']};new={r['household_id']:r for r in read(OUT/'MIXED_SLEEP_SCENARIOS1000.json')['cases']};fail=[];counts=collections.Counter();examples=[]
 for p in pp:
  w=read(V7/p['housing']['world_path'])['world'];dd=idf_doors(V7/p['reference_IDF_path'])
  for variant,c in [('baseline0_6m',.6),('alternative0_8m',.8)]:
   case=new[p['slot_id']][variant]
   if not case['found']:counts['finite_no_witness_'+variant]+=1;continue
   if case['route']=='sealed_single_bed_witness_retained':
    bb=old[p['slot_id']][variant]['beds'];frames=[{'frame_id':str(i),'room_id':b['room_id'],'kind':'single','outer_rect_m':b['bed_outer_rect_m']} for i,b in enumerate(bb)];berths=[dict(b,frame_id=str(i),level=0) for i,b in enumerate(bb)]
   else:frames=case['extended_reference']['frames'];berths=case['extended_reference']['berths'];examples.append((p,w,dd,frames,berths,c))
   errors=check_case(p,w,dd,frames,berths,c);counts['verified_witness_'+variant]+=not errors;counts['frames']+=len(frames);counts['berths']+=len(berths)
   if errors:fail.append({'household_id':p['slot_id'],'variant':variant,'errors':errors})
 negative=[]
 import copy
 for p,w,dd,ff,bb,c in examples:
  upper=next((b for b in bb if b['level']==1),None)
  if upper:
   q=copy.deepcopy(p);next(m for m in q['family']['members'] if m['member_id']==upper['member_id'])['age_years']=5
   negative.append({'injection':'under6_upper_berth','detected':'upper_age_restriction_failed' in check_case(q,w,dd,ff,bb,c)});break
 p,w,dd,ff,bb,c=examples[0];q=copy.deepcopy(ff);q[0]['outer_rect_m'][0]-=100
 negative.append({'injection':'frame_outside_room','detected':'furniture_outside_usable_room' in check_case(p,w,dd,q,bb,c)})
 q=copy.deepcopy(bb);q[0]['member_id']=q[1]['member_id'] if len(q)>1 else 'unknown'
 negative.append({'injection':'duplicate_or_unknown_resident','detected':'resident_roster_not_exactly_once' in check_case(p,w,dd,ff,q,c)})
 report={'counts':dict(counts),'failures':fail,'negative_controls':negative,'independent_world_coordinates_actual_IDF_doors':True,
   'door_swing_climbing_body_mass_privacy_and_care_not_validated':True,'horizontal_reference_geometric_witness_only':True}
 (OUT/'INDEPENDENT_SLEEP_VERIFICATION.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n');print(json.dumps(report,ensure_ascii=False))
 assert not fail and all(r['detected'] for r in negative)
if __name__=='__main__':main()
