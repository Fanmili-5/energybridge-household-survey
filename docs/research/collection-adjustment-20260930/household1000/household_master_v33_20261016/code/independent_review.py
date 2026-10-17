"""Read back every written world and shell; recompute population and subset checks.

This reader does not invoke the generators or infer that shell checks validate
occupied A/B physics. It also rejects targeted corruptions in isolated memory.
"""
import copy,collections,datetime as dt
from common import *
import sys
sys.path[:0]=read(BASE/'idf_joint_production_20261005/RUNTIME.json')['stable_PYTHONPATH'].split(':')
from shapely.geometry import box,Point
from shapely.ops import unary_union


def access_errors(w,rows):
    problems=[];rooms={r['room_id']:r for r in w['layout']['rooms']};obstacles=collections.defaultdict(list);sites=collections.defaultdict(list)
    sleeps=[w['layout']['sleep_reference']]+[h['sleep_reference']for h in w['shared_context']['households']]
    for sleep in sleeps:
        for f in sleep['frames']:obstacles[f['room_id']].append(f['outer_rect_m']);sites[f['room_id']].append(f['reachable_access_point_m'])
    for p in w['joint_matching']['spatial_witnesses']:
        obstacles[p['room_id']].append(p['operation_envelope_rect_m']);sites[p['room_id']].append(p['reachable_operator_center_m'])
    parents={r[1]:r[4]for r in rows if r[0]=='BuildingSurface:Detailed'};doors={}
    for r in rows:
        if r[0]=='FenestrationSurface:Detailed'and r[2]=='Door'and not r[1].endswith('_peer')and r[1]!='entry_door':
            doors[parents[r[4]]]=[list(map(float,r[i:i+3]))for i in range(10,len(r),3)]
    for rid,bodies in obstacles.items():
        room=rooms[rid];boundary=box(*room['usable_rect_m']);polygons=[box(*a)for a in bodies]
        if any(not boundary.buffer(1e-7).covers(p)for p in polygons):problems.append('GEOMETRY_BODY_OUTSIDE')
        if sum(p.area for p in polygons)-unary_union(polygons).area>1e-6:problems.append('BED_OR_OPERATION_ENVELOPE_OVERLAP')
        free=boundary.buffer(-.3,join_style=2).difference(unary_union([p.buffer(.3,join_style=2)for p in polygons]))
        components=[free]if free.geom_type=='Polygon'else[g for g in getattr(free,'geoms',[])if g.geom_type=='Polygon']
        if rid not in doors:problems.append('ROOM_DOOR_MISSING');continue
        vs=doors[rid];x0,y0,x1,y1=room['usable_rect_m'];axis=0 if max(v[0]for v in vs)-min(v[0]for v in vs)>.1 else 1
        low=max(min(v[axis]for v in vs)+.3,(x0,y0)[axis]+.3);high=min(max(v[axis]for v in vs)-.3,(x1,y1)[axis]-.3)
        fixed=vs[0][1-axis];limits=(y0,y1)if axis==0 else(x0,x1)
        inward=limits[0]+.3000001 if abs(fixed-limits[0])<abs(fixed-limits[1])else limits[1]-.3000001
        entries=[]
        if low<=high:
            for t in(0,.25,.5,.75,1):
                p=[0.,0.];p[axis]=low+(high-low)*t;p[1-axis]=inward;entries.append(Point(*p))
        reachable=[c for c in components if any(c.buffer(1e-6).covers(p)for p in entries)]
        for site in sites[rid]:
            if not any(c.buffer(1e-6).covers(Point(*site))for c in reachable):problems.append('BED_OR_DEVICE_ROUTE_UNREACHABLE')
    return sorted(set(problems))


def errors(w,original,rows):
    bad=access_errors(w,rows);hid=w['household_id'];rooms={r['room_id']:r for r in w['layout']['rooms']};devices=w['parameter_pack']['devices']
    for k in('N','G','H7','province','ego_relationships','random10_date_selection','role_policy'):
        if w[k]!=original[k]:bad.append('SOURCE_ANCHOR:'+k)
    expected_area=read(OUT/'AREA_REALLOCATION.json')['configured_area_m2'].get(hid,original['H6'])
    if w['H6']!=expected_area:bad.append('SOURCE_ANCHOR:H6')
    area_bin=lambda a:next(i for i,t in enumerate([8,12,16,19,29,39,49,59,69,float('inf')])if a/w['N']<=t)
    if area_bin(w['H6'])!=area_bin(original['H6']):bad.append('PERCAPITA_AREA_BIN_CHANGED')
    if digest({k:v for k,v in w.items()if k!='world_content_sha256'})!=w['world_content_sha256']:bad.append('WORLD_CONTENT_HASH')
    if digest(w['parameter_pack'])!=w['parameter_pack_sha256']:bad.append('PARAMETER_PACK_HASH')
    classes={k for d in devices for k in d['types']}
    f=w['layout']['stock_reference_features'];high=f['building_storeys']in('8_to33','34plus')
    if high and(f['load_bearing_structure']!='steel_RC'or f['elevator']!='present'or f['housing_source']=='selfbuild'):bad.append('INCONSISTENT_HIGHRISE_BACKGROUND')
    if w['layout']['shared_household_count_design']>1 and f['kitchen']!='shared':bad.append('SHARED_HOME_KITCHEN_RIGHTS')
    if w['layout']['source_parameter_reference']['catalogue_type']not in(('HighS','HighT')if high else('Low',)):bad.append('BUILDING_FAMILY_MISMATCH')
    if not 4<=len(classes)<=6 or'ac'not in classes:bad.append('DEVICE_CLASSES')
    # Re-read scalar floor geometry from the shell rather than use compiler metadata.
    floors={r[4]:[list(map(float,r[i:i+3]))for i in range(12,len(r),3)]for r in rows if r[0]=='BuildingSurface:Detailed'and r[2]=='Floor'}
    for rid,r in rooms.items():
        p=floors.get(rid)
        if not p:bad.append('SHELL_ROOM_MISSING');continue
        area=abs(sum(a[0]*b[1]-b[0]*a[1]for a,b in zip(p,p[1:]+p[:1])))/2
        if abs(area-r['thermal_reference_area_m2'])>1e-5:bad.append('SHELL_AREA_MISMATCH')
    if abs(sum(r['gross_area_m2']*r['area_allocation_fractions'].get(hid,0)for r in rooms.values())-w['H6'])>1e-6:bad.append('ALLOCATED_AREA')
    assets=collections.Counter(d['asset_id']for d in devices)
    if max(assets.values(),default=0)>1:bad.append('DUPLICATE_ASSET')
    before={d['asset_id']:d for d in original['parameter_pack']['devices']if'ac'not in d['types']}
    after={d['asset_id']:d for d in devices if'ac'not in d['types']}
    if set(before)!=set(after):bad.append('NON_AC_ASSET_SET')
    for aid in set(before)&set(after):
        if before[aid]['parameters']!=after[aid]['parameters']:bad.append('NON_AC_HARDWARE_PARAMETERS')
        if before[aid]['types']!=after[aid]['types']:bad.append('NON_AC_FUNCTION_CHANGED')
    if w['baseline_assistance_contract'].get('enabled')is not False:bad.append('GENERIC_HELPER')
    guardian=w['background_context']['nonresident_guardian']
    if all(m['age_years']<18 for m in w['members'])and not guardian:bad.append('MINOR_HOUSEHOLD_SUPPORT')
    if w['layout']['shared_household_count_design']>1:
        aux=w['shared_context']['households']
        if len(aux)!=w['layout']['shared_household_count_design']-1:bad.append('SHARED_CONTEXT_COVERAGE')
        for h in aux:
            if len(h['members'])!=len(h['sleep_reference']['berths']):bad.append('AUXILIARY_BERTHS')
        if not w['shared_context']['dated_examples']:bad.append('SHARED_CONTEXT_DATES')
    for day in w['shared_context']['dated_examples'].values():
        reserved=day['facility_reservations']
        expected={m['member_id']for h in w['shared_context']['households']for m in h['members']}
        if set(day['member_calendars'])!=expected:bad.append('AUXILIARY_OCCUPANCY_MISSING')
        for i,a in enumerate(reserved):
            if any(a['room_id']==b['room_id']and max(a['start_min'],b['start_min'])<min(a['end_min'],b['end_min'])for b in reserved[i+1:]):bad.append('SHARED_RESERVATION_COLLISION')
        for mid,seq in day['member_calendars'].items():
            if seq[0]['start_min']!=0 or seq[-1]['end_min']!=1440 or any(a['end_min']!=b['start_min']for a,b in zip(seq,seq[1:])):bad.append('AUXILIARY_CALENDAR_GAP')
        for r in reserved:
            mid=r.get('person_id')
            if mid in day['member_calendars']:
                seq=day['member_calendars'][mid]
                for t in range(r['start_min'],r['end_min'],10):
                    slot=next(i for i in seq if i['start_min']<=t<i['end_min'])
                    if slot['location']!='home'or slot['room_id']!=r['room_id']:bad.append('SHARED_BOOKING_PERSON_LOCATION')
    byid={m['member_id']:m for m in w['members']};frames={f['frame_id']:f for f in w['layout']['sleep_reference']['frames']}
    slots=collections.Counter()
    for b in w['layout']['sleep_reference']['berths']:
        f=frames[b['frame_id']];age=byid[b['member_id']]['age_years'];slots[(b['frame_id'],b['level'],b.get('horizontal_berth_slot',0))]+=1
        if age<3 and f['kind']!='crib':bad.append('INFANT_BED_TYPE')
        if f['kind']=='crib'and age>=3:bad.append('CRIB_AGE')
        if b['level']==1 and(f['kind']!='bunk'or not 6<=age<60):bad.append('UPPER_BUNK_AGE')
    if any(v!=1 for v in slots.values()):bad.append('BED_SLOT_DOUBLE_BOOKED')
    for d in devices:
        if d['circuit']not in w['parameter_pack']['circuit_limit_kw']:bad.append('CIRCUIT_BINDING')
        elif d['max_electric_kw']>w['parameter_pack']['circuit_limit_kw'][d['circuit']]+1e-8:bad.append('BRANCH_CAPACITY')
    needed=sum(d['max_electric_kw']for d in devices if d['circuit']!='EV_bay')+w['parameter_pack']['background_reserved_kw']
    if needed>w['parameter_pack']['home_service_limit_kw']+1e-8:bad.append('MAINS_CAPACITY')
    return sorted(set(bad))


def main():
    bindings=read(OUT/'WORLD_BINDINGS1000.json');subset=read(OUT/'SUBSET50.json');fail=[];classes=collections.Counter();types=collections.Counter();area_old=area_new=weights=0.;examples=[];shared_example=None
    for name,expected in read(OUT/'DEPENDENCY_LOCK.json')['files_relative_to_household1000'].items():
        if sha(BASE/name)!=expected:fail.append(('dependency',name))
    source={r['household_id']:r for r in read(BASE/'substantive_repair_v30_20261015/SELECTION1000.json')['records']}
    for r in bindings['records']:
        w=read(OUT/r['world_path']);old=read(BASE/'substantive_repair_v30_20261015'/source[r['household_id']]['world_path']);rows=parse(OUT/r['background_IDF_path'])
        if sha(OUT/r['world_path'])!=r['world_sha256']:fail.append((r['household_id'],'WORLD_FILE_HASH'))
        if sha(OUT/r['background_IDF_path'])!=r['background_IDF_sha256']:fail.append((r['household_id'],'SHELL_FILE_HASH'))
        bad=errors(w,old,rows);fail.extend((r['household_id'],e)for e in bad)
        classes[len({k for d in w['parameter_pack']['devices']for k in d['types']})]+=1;types[w['eb_reference_type_assignment']]+=1
        weights+=w['population_weight'];area_old+=old['H6']*w['population_weight'];area_new+=w['H6']*w['population_weight']
        if len(examples)<1:examples.append((w,old,rows))
        if w['shared_context']['households']and shared_example is None:shared_example=(w,old,rows)
    byid={r['household_id']:r for r in bindings['records']}
    if abs(area_old-area_new)>1e-7:fail.append(('population','WEIGHTED_AREA_CHANGED'))
    if len(byid)!=1000:fail.append(('master','HOUSEHOLD_COUNT'))
    if len({r['household_id']for r in subset['records']})!=50:fail.append(('subset','SUBSET_COUNT'))
    for r in subset['records']:
        if r!=byid.get(r['household_id']):fail.append((r['household_id'],'SUBSET_NOT_MASTER_BYTES'))
    actual=dict(collections.Counter(r['type']for r in subset['records']))
    if actual!={'A':5,'B':15,'C':16,'D':5,'E':4,'F':5}:fail.append(('subset','PROPORTIONAL_TYPE_COUNTS'))
    w,old,rows=examples[0];controls=[]
    for name,mutate,expected in[
        ('remove_AC',lambda x:x['parameter_pack'].update(devices=[d for d in x['parameter_pack']['devices']if'ac'not in d['types']]),'DEVICE_CLASSES'),
        ('change_family_area',lambda x:x.update(H6=x['H6']+1),'SOURCE_ANCHOR:H6'),
        ('restore_automatic_helper',lambda x:x['baseline_assistance_contract'].update(enabled=True),'GENERIC_HELPER')]:
        corrupted=copy.deepcopy(w);mutate(corrupted);detected=errors(corrupted,old,rows)
        if expected not in detected:fail.append(('negative_control',name))
        controls.append({'control':name,'rejected':expected in detected})
    if shared_example:
        sw,so,sr=shared_example;corrupted=copy.deepcopy(sw);day=next(iter(corrupted['shared_context']['dated_examples'].values()))
        day['member_calendars'].pop(next(iter(day['member_calendars'])))
        rejected='AUXILIARY_OCCUPANCY_MISSING'in errors(corrupted,so,sr)
        controls.append({'control':'remove_neighbor_presence','rejected':rejected})
        if not rejected:fail.append(('negative_control','remove_neighbor_presence'))
        corrupted=copy.deepcopy(sw);day=next(iter(corrupted['shared_context']['dated_examples'].values()))
        day['facility_reservations'].append(copy.deepcopy(day['facility_reservations'][0]))
        rejected='SHARED_RESERVATION_COLLISION'in errors(corrupted,so,sr)
        controls.append({'control':'double_book_shared_bath','rejected':rejected})
        if not rejected:fail.append(('negative_control','double_book_shared_bath'))
    report={'schema':'eb.master_independent_world_readback.v33','passed':not fail,'households_checked':len(bindings['records']),
        'subset_checked':len(subset['records']),'subset_type_counts':actual,'six_type_counts':dict(types),'device_class_counts':dict(classes),
        'weighted_mean_source_area_m2':area_old/weights,'weighted_mean_new_area_m2':area_new/weights,
        'failures':fail,'negative_controls':controls,'world_bindings_sha256':sha(OUT/'WORLD_BINDINGS1000.json'),
        'source_to_new_roster_roomcount_policy_dates_unchanged':True,
        'individual_area_changes':read(OUT/'AREA_REALLOCATION.json'),'weighted_total_area_and_percapita_bins_unchanged':abs(area_old-area_new)<1e-7,
        'EP_started':0,'AB_or_human_validation_claimed':False}
    save(OUT/'INDEPENDENT_WORLD_REVIEW.json',report);print(canonical(report))
    if fail:raise SystemExit(2)

if __name__=='__main__':main()
