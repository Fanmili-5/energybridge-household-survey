"""Saved-witness geometry review without importing any placement generator."""
import collections, concurrent.futures
from common import *
from shapely.geometry import box,Point,LineString
from shapely.ops import unary_union
def reachable(room,portal,obstacles,site):
    radius=.3;x0,y0,x1,y1=room['usable_rect_m']
    free=box(x0,y0,x1,y1).buffer(-radius,join_style=2).difference(unary_union([box(*r).buffer(radius,join_style=2) for r in obstacles]))
    parts=[free] if free.geom_type=='Polygon' else [g for g in getattr(free,'geoms',[]) if g.geom_type=='Polygon']
    xs=[p[0] for p in portal];ys=[p[1] for p in portal]
    if max(xs)-min(xs)>.1:
        low=max(min(xs)+radius,x0+radius);high=min(max(xs)-radius,x1-radius)
        yy=y0+radius+1e-7 if abs(ys[0]-y0)<=abs(ys[0]-y1) else y1-radius-1e-7
        edge=LineString([(low,yy),(high,yy)]) if low<=high else None
    else:
        low=max(min(ys)+radius,y0+radius);high=min(max(ys)-radius,y1-radius)
        xx=x0+radius+1e-7 if abs(xs[0]-x0)<=abs(xs[0]-x1) else x1-radius-1e-7
        edge=LineString([(xx,low),(xx,high)]) if low<=high else None
    return edge is not None and any(g.buffer(1e-6).covers(Point(*site)) and g.buffer(1e-6).intersects(edge) for g in parts)
def one(b):
    w=read(OUT/b['world_path']);rows=parse(OUT/'idfs'/w['household_id']/'01_A.idf');rooms={r['room_id']:r for r in w['layout']['rooms']}
    surfaces={r[1]:r for r in rows if r[0]=='BuildingSurface:Detailed'};portals={}
    for r in rows:
        if r[0]=='FenestrationSurface:Detailed' and r[2]=='Door' and not r[1].endswith('_peer') and r[1]!='entry_door':
            portals[surfaces[r[4]][4]]=[list(map(float,r[j:j+3])) for j in range(10,len(r),3)]
    occupied=collections.defaultdict(list);errors=[];counts=collections.Counter()
    for f in w['layout']['sleep_reference']['frames']:occupied[f['room_id']].append(f['outer_rect_m']);counts['bed_frames']+=1
    for p in w['joint_matching']['spatial_witnesses']:
        rid=p['room_id'];r=rooms[rid];body=p['body_rect_m'];env=p['operation_envelope_rect_m']
        if not box(*r['usable_rect_m']).buffer(1e-8).covers(box(*env)):errors.append('ENVELOPE_OUTSIDE_ROOM')
        if not box(*env).buffer(1e-8).covers(box(*body)):errors.append('BODY_OUTSIDE_ENVELOPE')
        if any(box(*env).intersection(box(*o)).area>1e-8 for o in occupied[rid]):errors.append('FLOOR_RESOURCE_OVERLAP')
        occupied[rid].append(env);counts['fixture_witnesses']+=1
    for p in w['joint_matching']['spatial_witnesses']:
        rid=p['room_id']
        if rid not in portals or not reachable(rooms[rid],portals[rid],occupied[rid],p['reachable_operator_center_m']):errors.append('FIXTURE_PORTAL_CONNECTIVITY')
    for rid,sites in w['joint_matching']['sleep_metric_access_witnesses'].items():
        for site in sites:
            if rid not in portals or not reachable(rooms[rid],portals[rid],occupied[rid],site):errors.append('BED_PORTAL_CONNECTIVITY')
            counts['metric_bed_access_sites']+=1
    for d in w['parameter_pack']['devices']:
        if 'ac' in d['types']:
            install=d['installation'];r=rooms[d['room_id']]
            if d['served_rooms']!=[r['room_id']]:errors.append('AC_SERVED_ZONE')
            if install['units_on_wall']*install['reserved_width_each_m']>install['wall_length_available_m']+1e-8:errors.append('AC_WALL_LENGTH')
    return {'household_id':w['household_id'],'errors':sorted(set(errors)),'counts':dict(counts)}
def main():
    school_guard();bs=read(OUT/'WORLD_BINDINGS1000.json')['records']
    with concurrent.futures.ProcessPoolExecutor(max_workers=16) as pool:results=list(pool.map(one,bs))
    counts=collections.Counter()
    for r in results:counts.update(r['counts'])
    failures=[r for r in results if r['errors']]
    save(OUT/'SAVED_GEOMETRY_REVIEW.json',{'households':len(results),'counts':dict(counts),'failures':failures,'EP_started':0,
        'review_does_not_import_generator':True,'scope':'final metric rectangles and actual saved IDF portals;reference600mm access and declared non-swing doors;not structural/asbuilt/code certification'})
    print({'geometry_households':len(results),'failures':len(failures)},flush=True)
    if failures:raise RuntimeError(str(failures[:5]))
if __name__=='__main__':main()
