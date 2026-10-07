"""Read actual IDFs independently: orientations, closed volumes, paired faces,
gross/net/shared conservation, census margins and unchanged family anchors.

Engine conversion is syntax/field verification, not thermal/behavioral validity.
"""
import collections,hashlib,json,math,re,subprocess,concurrent.futures
from pathlib import Path
import numpy as np
import jsonschema
from shapely.geometry import Polygon,box
from shapely.ops import unary_union

OUT=Path(__file__).resolve().parent.parent;BASE=OUT.parent
ENGINE=Path('/Applications/EnergyPlus-24-1-0/energyplus')
def read(p):return json.loads(p.read_text())
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def save(name,d):(OUT/name).write_text(json.dumps(d,ensure_ascii=False,indent=2,allow_nan=False)+'\n')
def parse(path):return [[x.strip() for x in p.split(',')] for p in re.sub(r'!.*','',path.read_text()).split(';') if p.strip()]
def normal_area(v):
    v=np.array(v,float);vector=sum((np.cross(a,b) for a,b in zip(v,np.roll(v,-1,axis=0))),np.zeros(3))/2
    return vector,float(np.linalg.norm(vector)),v.mean(0)

def main():
    body=read(OUT/'HOUSEHOLDS1000_JOINT_GEOMETRY_CANDIDATE.json');anchor=read(BASE/'production_route_v6_20261004/HOUSEHOLDS1000_JOINT_CANDIDATE.json')
    frame=read(BASE/'production_route_v6_20261004/ORDINARY_CITY_FRAME.json');bindings=read(OUT/'IDF_REFERENCE_BINDINGS1000.json')['bindings'];count=0;diagnostics=[]
    def check(cond,label):
        nonlocal count
        if not cond:raise AssertionError(label)
        count+=1
    check(len(bindings)==len(body['profiles'])==1000,'1000_reference_cases')
    check([p['family'] for p in body['profiles']]==[p['family'] for p in anchor['profiles']],'exact_original1000_family_rosters_and_attributes_preserved')
    check(sum(p['family']['resident_count'] for p in body['profiles'])==2524,'2524_population_target_residents')
    check([p['province'] for p in body['profiles']]==[p['province'] for p in anchor['profiles']],'province_identity_preserved')
    aliases={b['household_id']:b for b in bindings};aux=0
    for profile in body['profiles']:
        name=profile['slot_id'];binding=aliases[name];w=read(OUT/binding['world_path'])['world'];h=profile['housing']
        check(sha(OUT/binding['IDF_path'])==binding['IDF_sha256'] and sha(OUT/binding['world_path'])==binding['world_sha256'],'input_world_IDF_locks:'+name)
        W,D=w['metric_outer_rect_m'][2:];shapes=[box(*r['gross_rect_m']) for r in w['rooms']]
        check(abs(sum(p.area for p in shapes)-unary_union(shapes).area)<1e-6,'gross_room_tiles_no_overlap:'+name)
        check(abs(unary_union(shapes).area-W*D)<1e-6,'gross_tiles_cover_actual_outer_footprint:'+name)
        q=len(w['households']);common=sum(r['gross_area_m2'] for r in w['rooms'] if len(r['using_household_ids'])>1);private={hh['household_id']:sum(r['gross_area_m2'] for r in w['rooms'] if r['using_household_ids']==[hh['household_id']]) for hh in w['households']}
        check(abs(common+sum(private.values())-W*D)<1e-6,'common_private_outer_area_conservation:'+name)
        check(abs(private[name]+common/q-h['H6_census_building_area_design_m2'])<1e-6,'target_H6_from_actual_area_components:'+name)
        rcount=sum(r['census_room_class'] in ['bedroom','study','other_natural_room','living_natural_room'] and r['using_household_ids']==[name] for r in w['rooms'])
        check(rcount==h['H7_independent_natural_rooms_design'],'exclusive_natural_H7_from_actual_world:'+name)
        pc=h['H6_census_building_area_design_m2']/profile['family']['resident_count'];b=h['percap_area_bin_index']
        lower=[1,9,13,17,20,30,40,50,60,70][b];upper=[8,12,16,19,29,39,49,59,69,math.inf][b]
        check(lower-1e-9<=pc<=upper+1e-9,'actual_A_per_resident_within_selected_percap_bin:'+name)
        check(h['H7_exact_tail_is_design']==(rcount>=10),'tail_count_design_flag_matches_actual_H7:'+name)
        check(sum(r['usable_area_m2'] for r in w['rooms'])<W*D,'usable_and_building_area_remain_distinct:'+name)
        aux+=q-1
        rows=parse(OUT/binding['IDF_path']);zones={r[1]:r for r in rows if r[0].lower()=='zone'};rooms={r['room_id']:r for r in w['rooms']}
        check(set(zones)==set(rooms),'IDF_functional_room_inventory:'+name)
        for z,r in rooms.items():check(abs(float(zones[z][10])-r['usable_area_m2'])<1e-7 and abs(float(zones[z][9])-r['usable_area_m2']*2.9)<1e-7,'IDF_explicit_usable_area_volume:'+name+':'+z)
        surfaces={r[1]:r for r in rows if r[0].lower()=='buildingsurface:detailed'};openings={r[1]:r for r in rows if r[0].lower()=='fenestrationsurface:detailed'}
        volumes=collections.defaultdict(float);area_vectors=collections.defaultdict(lambda:np.zeros(3));orientation=0
        for s in surfaces.values():
            v=np.array(list(map(float,s[12:])),float).reshape(-1,3);vector,area,centroid=normal_area(v);zone=s[4];rect=rooms[zone]['thermal_centerline_rect_m'];center=np.array([(rect[0]+rect[2])/2,(rect[1]+rect[3])/2,2.9/2])
            check(area>1e-8 and float(vector@(centroid-center))>1e-8,'outward_surface_normal:'+name+':'+s[1]);orientation+=1
            volumes[zone]+=float(vector@centroid)/3;area_vectors[zone]+=vector
            if s[6].lower()=='surface':
                peer=surfaces[s[7]];vp=np.array(list(map(float,peer[12:])),float).reshape(-1,3);pvec,parea,_=normal_area(vp)
                check(peer[7]==s[1] and peer[4]!=zone and set(map(tuple,np.round(v,7)))==set(map(tuple,np.round(vp,7))) and np.linalg.norm(vector+pvec)<1e-6,'reciprocal_opposite_paired_wall:'+name+':'+s[1])
        for z,r in rooms.items():
            expected=r['thermal_reference_area_m2']*2.9
            check(abs(volumes[z]-expected)<1e-5 and np.linalg.norm(area_vectors[z])<1e-5,'independent_closed_centerline_geometric_volume:'+name+':'+z)
        for f in openings.values():
            parent=surfaces[f[4]];v=np.array(list(map(float,f[10:])),float).reshape(-1,3);fv,area,_=normal_area(v);pv=np.array(list(map(float,parent[12:])),float).reshape(-1,3);pvec,pa,_=normal_area(pv)
            check(area>0 and float(fv@pvec)>0,'subsurface_same_outward_orientation_as_parent:'+name+':'+f[1])
            # For a vertical rectangle compare the horizontal free coordinate
            # and z in the parent's plane, not unrelated2D polygon projections.
            fixed=0 if abs(np.ptp(pv[:,0]))<1e-8 else 1;free=1-fixed
            check(np.max(abs(v[:,fixed]-pv[0,fixed]))<1e-7 and v[:,free].min()>=pv[:,free].min()-1e-7 and v[:,free].max()<=pv[:,free].max()+1e-7 and v[:,2].min()>=pv[:,2].min()-1e-7 and v[:,2].max()<=pv[:,2].max()+1e-7,'door_window_within_parent_plane:'+name+':'+f[1])
            if f[5]:
                peer=openings[f[5]];vp=np.array(list(map(float,peer[10:])),float).reshape(-1,3)
                check(peer[5]==f[1] and set(map(tuple,np.round(v,7)))==set(map(tuple,np.round(vp,7))),'reciprocal_door_subsurfaces:'+name+':'+f[1])
        # A target can reach each own natural room, kitchen and toilet without
        # passing through another household's exclusive rooms.
        accessible={r['room_id'] for r in w['rooms'] if name in r['using_household_ids']};edges=collections.defaultdict(set)
        for e in w['access']:
            if e['from'] in accessible and e['to'] in accessible:edges[e['from']].add(e['to']);edges[e['to']].add(e['from'])
        reached={'corridor'};todo=['corridor']
        while todo:
            for n in edges[todo.pop()]-reached:reached.add(n);todo.append(n)
        check(reached==accessible,'target_access_without_other_household_private_room:'+name)
        check(not any(r[0].lower() in ['people','electricequipment','zonehvac:idealloadsairsystem'] for r in rows),'no_invented_services_in_reference_shell:'+name)
        materials={r[1]:r for r in rows if r[0].lower()=='material'};core=materials['Reference_RC_core_120mm']
        check([float(core[k]) for k in [3,4,5,6]]==[.12,1.74,2500.,920.],'declared_RC_reference_replacement:'+name)
        check(all(s[3]=='Reference_RC_floor_165mm' for s in surfaces.values() if s[2] in ['Floor','Ceiling']),'no_misnamed_native_RC_floor_used:'+name)
        own_usable=sum(r['usable_area_m2'] for r in w['rooms'] if r['using_household_ids']==[name]);common_usable=sum(r['usable_area_m2'] for r in w['rooms'] if len(r['using_household_ids'])>1)
        diagnostics.append({'household_id':name,'target_H6_m2':h['H6_census_building_area_design_m2'],'H7':rcount,'q_reference_design':q,
          'own_usable_m2':own_usable,'common_accessible_usable_m2':common_usable,'target_equal_share_allocated_usable_m2':own_usable+common_usable/q,
          'whole_unit_usable_m2':w['usable_total_area_m2'],'whole_outer_gross_m2':W*D,
          'parent_gross_to_usable_ratio':w['usable_total_area_m2']/(W*D),'outward_surfaces_checked':orientation,
          'number_of_target_population_households_in_this_world':1,'auxiliary_context_households':q-1})
    pc=collections.Counter(p['housing']['percap_area_bin_index'] for p in body['profiles']);rr=collections.Counter(min(p['housing']['H7_independent_natural_rooms_design'],10) for p in body['profiles'])
    check([pc[k] for k in range(10)]==body['result']['percap_area_quota'],'all_percap_area_quotas')
    check([rr[k] for k in range(1,11)]==body['result']['room_quota'],'all_detailed_H7_quotas')
    check(sum(p['housing']['H6_census_building_area_design_m2'] for p in body['profiles'])==body['result']['H6_total_m2'],'unweighted_finite_cohort_H6_total_reported_separately')
    weights=np.array([p['relative_population_weight'] for p in body['profiles']]);areas=np.array([p['housing']['H6_census_building_area_design_m2'] for p in body['profiles']])
    check(abs(weights@areas/weights.sum()-92.17)<=.0049+1e-8,'official_rounded_H6_mean_on_population_weighted_estimand')
    check(sum(p['housing']['H7_independent_natural_rooms_design'] for p in body['profiles'])==body['result']['exact_reference_room_total']==2500,'rounded_source_national_room_moment_reference')
    check([p['relative_population_weight'] for p in body['profiles']]==[p['relative_population_weight'] for p in anchor['profiles']],'population_weights_preserved')
    for k,province in enumerate(frame['provinces']):
        pp=[p for p in body['profiles'] if p['province']==province]
        for g in range(1,6):
            for r in range(1,6):
                actual=sum(p['family']['generation_count']==g and min(p['housing']['H7_independent_natural_rooms_design'],5)==r for p in pp)
                target=frame['ordinary_generation_room_counts'][k][g-1][r-1]/frame['official_households']*1000
                check(math.floor(target)<=actual<=math.ceil(target),'province_G_H7_control:'+province+':'+str(g)+':'+str(r))
        for b in range(10):
            actual=sum(p['housing']['percap_area_bin_index']==b for p in pp);target=frame['ordinary_percap_area10_counts'][k][b]/frame['official_households']*1000
            check(math.floor(target)<=actual<=math.ceil(target),'province_percap_area_control:'+province+':'+str(b))
    # Convert all IDFs through the installed engine; validate returned epJSON
    # using its actual24.1 schema. Each process has a separate output directory.
    schema=read(ENGINE.parent/'Energy+.schema.epJSON');validator=jsonschema.Draft7Validator(schema)
    def conversion(b):
        path=OUT/b['IDF_path'];out=OUT/'conversion'/b['household_id'];out.mkdir(parents=True,exist_ok=True)
        result=subprocess.run([str(ENGINE),'--convert-only','-d',str(out),str(path)],capture_output=True,text=True,timeout=30)
        ep=out/path.with_suffix('.epJSON').name
        if result.returncode or not ep.exists():raise RuntimeError('engine_native_IDF_conversion_failed:'+b['household_id']+':'+result.stdout+result.stderr)
        data=read(ep);errors=list(validator.iter_errors(data))
        if errors:raise RuntimeError('native_conversion_schema_error:'+b['household_id']+':'+errors[0].message)
        return {'household_id':b['household_id'],'native_epJSON_path':str(ep.relative_to(OUT)),'sha256':sha(ep),'native_conversion_and_schema_valid':True}
    with concurrent.futures.ThreadPoolExecutor(4) as pool:converted=list(pool.map(conversion,bindings))
    save('IDF_NATIVE_CONVERSION1000.json',{'cases':converted,'native_conversions':1000,'all_version24_1_schema_valid':True,
                                        'full_runtime_or_empirical_energy_validation':False})
    frozen=0
    for folder in ['production_route_v5_20261004','idf_unit_evidence_20261004','end_to_end_plan_20261004','production_route_v4_20261003','construction_chain_20261003','benchmark_foundation_20261004','production_route_v6_20261004']:
        root=BASE/folder
        for rel,expected in read(root/'PACKAGE_MANIFEST.json')['files'].items():check(sha(root/rel)==expected,'frozen_input:'+folder+'/'+rel);frozen+=1
    results=read(OUT/'IDF_DIAGNOSTIC_RESULTS.json')
    check(all(x['severe_or_fatal']==0 and x['wrong_whole_unit_meter_as_target_rejected'] for x in results['cases']),'diagnostic_runtime_and_shared_meter_checks')
    check(all(x['relative_mean_residual']<.001 for x in results['cases']),'opaque_UA_operator_numeric_residuals')
    negative=read(OUT/'SUBSURFACE_FILM_NEGATIVE_CONTROL.json');check(negative['guard_rejected'],'actual_subsurface_film_negative_control_rejected')
    smoke=read(OUT/'SHELL_RUNTIME_COVERAGE.json');covered={n:c for c in smoke['cases'] for n in c['bound_households']}
    check(len(covered)==1000 and smoke['byte_unique_reference_shells_run']==len({b['IDF_sha256'] for b in bindings}),'all_unique_windowed_shells_have_current_runtime_coverage')
    for b in bindings:
        c=covered[b['household_id']]
        check(c['input_IDF_sha256']==b['IDF_sha256'] and c['severe_or_fatal']==0,'runtime_witness_bound_to_current_IDF:'+b['household_id'])
    check(all('Floor Area' in m or 'Entered Zone Volumes' in m for c in smoke['cases'] for m in c['warnings']),'runtime_geometry_warnings_only_declared_area_volume_convention')
    save('WORLD_AREA_ACCESS_AUDIT1000.json',{'households':diagnostics,'total_population_target_households':1000,
      'auxiliary_context_households':aux,'auxiliary_are_not_sample_expansion_or_real_resident_records':True,
      'gross_usable_thermal_centerline_scopes_kept_separate':True,'source_unknowns_not_filled_by_reference_geometry':True,
      'physical_energy_services_and_sleeping_world_complete':False})
    summary={'independent_assertions':count,'reference_world_and_IDF_geometry_audited':1000,
      'native_engine_conversions_and_schema_checks':1000,'family_anchors_and_persons_preserved':2524,
      'auxiliary_context_households':aux,'new_diagnostic_runs':results['new_EnergyPlus_diagnostic_runs'],
      'frozen_files_unchanged':frozen,'reference_IDF_shells':1000,'complete_household_IDFs':0,
      'byte_unique_reference_IDFs':len({b['IDF_sha256'] for b in bindings}),
      'windowed_free_floating_shell_runtime_bindings_covered':1000,'successful_positive_diagnostic_runs':results['new_EnergyPlus_diagnostic_runs'],
      'negative_control_runs_expected_rejection':1,'runtime_warning_entries':smoke['total_warning_entries'],
      'national_stock_morphology_or_climate_representativeness_validated':False,
      'scientific_benchmark_admitted':False,'collection_release':False,'training_release':False}
    save('VERIFICATION.json',summary);print(json.dumps(summary,ensure_ascii=False,indent=2))

if __name__=='__main__':main()
