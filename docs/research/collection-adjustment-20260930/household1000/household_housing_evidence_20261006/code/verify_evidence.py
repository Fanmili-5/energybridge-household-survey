"""Independent source-semantic and world-coordinate witness checks.

Does not import the sleeping search/placement implementation. Constructs
clearance-free components from exported world bed rectangles and actualIDF
door vertices, checks membership, sizes, overlap, access and negative controls.
Implementation evidence cannot admit national stock/physical/human validity.
"""
import collections,copy,hashlib,json,math,re,sys
from pathlib import Path
OUT=Path(__file__).resolve().parent.parent;BASE=OUT.parent;V7=BASE/'idf_joint_production_20261005'
sys.path[:0]=json.loads((V7/'RUNTIME.json').read_text())['stable_PYTHONPATH'].split(':')
from shapely.geometry import box,Point,LineString
from shapely.ops import unary_union
from year_rules import derive_year
from access_parser_c import AccessParser

def read(p):return json.loads(Path(p).read_text())
def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def save(name,d):(OUT/name).write_text(json.dumps(d,ensure_ascii=False,indent=2,allow_nan=False)+'\n')
def parse(p):return [[v.strip() for v in q.split(',')] for q in re.sub(r'!.*','',Path(p).read_text()).split(';') if q.strip()]

def audit_sleep(case,world,rr,profile):
    issues=[];rooms={r['room_id']:r for r in world['rooms']};parent={r[1]:r[4] for r in rr if r[0]=='BuildingSurface:Detailed'}
    ds={parent[r[4]]:[[float(x) for x in r[i:i+3]] for i in range(10,len(r),3)] for r in rr if r[0]=='FenestrationSurface:Detailed' and r[2]=='Door' and not r[1].endswith('_peer') and r[1]!='entry_door'}
    roster={m['member_id'] for m in profile['family']['members']};bed_ids=[b['member_id'] for b in case['beds']]
    if len(set(bed_ids))!=len(bed_ids) or not set(bed_ids)<=roster:issues.append('member_assignment')
    if case['capacity_witness_found'] and set(bed_ids)!=roster:issues.append('incomplete_claimed_witness')
    if case['actor_ready']:issues.append('premature_actor_admission')
    radius=case['clearance_reference_m']/2;group=collections.defaultdict(list)
    for b in case['beds']:group[b['room_id']].append(b)
    for name,beds in group.items():
        r=rooms[name];x0,y0,x1,y1=r['usable_rect_m'];room=box(x0,y0,x1,y1)
        if r['census_room_class']!='bedroom' or r['using_household_ids']!=[profile['slot_id']]:issues.append('nonprivate_sleeping')
        rectangles=[box(*b['bed_outer_rect_m']) for b in beds]
        for b,p in zip(beds,rectangles):
            z=b['bed_outer_rect_m'];dimensions=sorted([z[2]-z[0],z[3]-z[1]])
            if max(abs(a-b) for a,b in zip(dimensions,[.94,2.05]))>1e-6:issues.append('bed_size')
            if not room.buffer(1e-6).covers(p):issues.append('bed_outside_room')
        if sum(p.area for p in rectangles)-unary_union(rectangles).area>1e-6:issues.append('overlapping_beds')
        domain=room.buffer(-radius,join_style=2).difference(unary_union([p.buffer(radius,join_style=2) for p in rectangles]))
        pieces=[domain] if domain.geom_type=='Polygon' else [g for g in getattr(domain,'geoms',[]) if g.geom_type=='Polygon']
        v=ds[name];xs=[p[0] for p in v];ys=[p[1] for p in v]
        if max(xs)-min(xs)>.1:
            lower=max(min(xs)+radius,x0+radius);upper=min(max(xs)-radius,x1-radius)
            north=abs(ys[0]-y1)<abs(ys[0]-y0);yy=y1-radius-1e-7 if north else y0+radius+1e-7
            sites=[Point(lower+(upper-lower)*f,yy) for f in [0,.25,.5,.75,1]]
        else:
            lower=max(min(ys)+radius,y0+radius);upper=min(max(ys)-radius,y1-radius)
            east=abs(xs[0]-x1)<abs(xs[0]-x0);xx=x1-radius-1e-7 if east else x0+radius+1e-7
            sites=[Point(xx,lower+(upper-lower)*f) for f in [0,.25,.5,.75,1]]
        if upper<lower-1e-6:issues.append('door_less_than_clearance')
        reached=[g for g in pieces if any(g.buffer(1e-6).covers(p) for p in sites)]
        if not reached:issues.append('entry_path_blocked')
        for b in beds:
            a,c,d,e=b['bed_outer_rect_m']
            if e-c>d-a:approaches=[Point(xx,c+(e-c)*f) for xx in [a-radius-1e-5,d+radius+1e-5] for f in [.25,.5,.75]]
            else:approaches=[Point(a+(d-a)*f,yy) for yy in [c-radius-1e-5,e+radius+1e-5] for f in [.25,.5,.75]]
            if not any(g.buffer(1e-6).covers(p) for g in reached for p in approaches):issues.append('bed_longside_unreachable')
    return sorted(set(issues))

def source_controls():
    selected={'selected':True,'tenure_code':1,'current_dwelling_slot':2}
    cases=[('current_property2_not_property1',{'c2012a_1':1980,'c2012a_2':2010,'c2000x_2':1},selected,'reported_effective_year_reference_compatible',2010),
      ('2021_after_reference',{'c2012a_2':2021,'c2000x_2':1},selected,'post_reference_year_not_2020_stock_proxy',2021),
      ('2025_projected',{'c2012a_2':2025,'c2000x_2':1},selected,'future_or_projected_year_not_completed_at_visit',2025),
      ('new_branch_unasked_value',{'c2012a_2':1990,'c2006_2':7,'c2008ab_2':1},selected,'unasked_year_value_conflict',None),
      ('new_branch_structural_unasked',{'c2006_2':7,'c2008ab_2':1},selected,'structurally_unasked_year',None),
      ('old_branch_year_independent_skip',{'c2012a_2':1990,'c2000x_2':1,'c2006_2':7,'c2008ab_2':1},selected,'reported_effective_year_reference_compatible',1990),
      ('purchase_property_question_unasked',{'c2012a_2':1990,'c2006_2':1},selected,'reported_effective_year_reference_compatible',1990),
      ('nonowned_code5_is20plus_not5years',{'c1000ak':5},{'selected':True,'tenure_code':2,'current_dwelling_slot':'nonowned'},'nonowned_reported_age_interval',None)]
    result=[]
    for label,row,sel,status,year in cases:
        got=derive_year(row,sel,2021);assert got['status']==status and got['exact_reported_year']==year,label
        if label=='nonowned_code5_is20plus_not5years':assert got['age_interval_years']==[20,None]
        assert got['energy_code_compliance_observed'] is False
        result.append({'control':label,'passed':True,'source_household_id_or_private_values':False})
    return result

def main():
    from evidence_guard import ensure_unsealed
    ensure_unsealed(OUT)
    controls=source_controls();profiles={p['slot_id']:p for p in read(V7/'HOUSEHOLDS1000_JOINT_GEOMETRY_CANDIDATE.json')['profiles']}
    audit=read(OUT/'SLEEP_GEOMETRY_AUDIT1000.json');summaries=[];beds=0
    for case in audit['cases']:
        p=profiles[case['household_id']];path=V7/p['housing']['world_path'];idf=V7/p['reference_IDF_path'];world=read(path)['world'];rr=parse(idf)
        assert sha(path)==case['input_world_sha256'] and sha(idf)==case['input_IDF_sha256']
        for variant in ['baseline0_6m','alternative0_8m']:
            c=case[variant];issues=audit_sleep(c,world,rr,p);assert not issues,(p['slot_id'],variant,issues);beds+=len(c['beds'])
        summaries.append({'household_id':p['slot_id'],'both_reference_layouts_independently_checked':True})
    first=next(c for c in audit['cases'] if c['baseline0_6m']['capacity_witness_found']);p=profiles[first['household_id']];world=read(V7/p['housing']['world_path'])['world'];rr=parse(V7/p['reference_IDF_path'])
    c=copy.deepcopy(first['baseline0_6m']);c['beds'][0]['bed_outer_rect_m']=[-50,-50,-47.95,-49.06]
    negative=[{'control':'exported_bed_moved_outside_room','rejected':bool(audit_sleep(c,world,rr,p))}]
    c=copy.deepcopy(first['baseline0_6m']);c['beds'].append(copy.deepcopy(c['beds'][0]));negative.append({'control':'overlap_and_duplicate_member_assignment','rejected':bool(audit_sleep(c,world,rr,p))})
    # Keep a correctly sized bed inside its private room, but place it across
    # the actual door threshold. Reject the path, not merely containment.
    c=copy.deepcopy(first['baseline0_6m']);bed=c['beds'][0];room=next(r for r in world['rooms'] if r['room_id']==bed['room_id']);x0,y0,x1,y1=room['usable_rect_m']
    parents={r[1]:r[4] for r in rr if r[0]=='BuildingSurface:Detailed'}
    door=next(r for r in rr if r[0]=='FenestrationSurface:Detailed' and r[2]=='Door' and not r[1].endswith('_peer') and r[1]!='entry_door' and parents[r[4]]==bed['room_id']);vertices=[[float(v) for v in door[i:i+3]] for i in range(10,len(door),3)];xs=[v[0] for v in vertices];ys=[v[1] for v in vertices]
    if max(xs)-min(xs)>.1:
        left=max(x0,min(x1-2.05,(min(xs)+max(xs))/2-1.025));north=abs(ys[0]-y1)<abs(ys[0]-y0);bottom=y1-.94 if north else y0
        bed['bed_outer_rect_m']=[left,bottom,left+2.05,bottom+.94]
    else:
        bottom=max(y0,min(y1-2.05,(min(ys)+max(ys))/2-1.025));east=abs(xs[0]-x1)<abs(xs[0]-x0);left=x1-.94 if east else x0
        bed['bed_outer_rect_m']=[left,bottom,left+.94,bottom+2.05]
    errors=audit_sleep(c,world,rr,p);assert 'entry_path_blocked' in errors and 'bed_size' not in errors and 'bed_outside_room' not in errors
    negative.append({'control':'valid_size_contained_bed_blocks_actual_room_door','rejected':True,'path_failure_checked_separately_from_containment':True})
    assert all(x['rejected'] for x in negative)
    routes=read(OUT/'MATCHING_SCENARIOS1000.json');assert len(routes['routes'])==1000 and {r['household_id'] for r in routes['routes']}==set(profiles)
    refs={r['model_key']:r for r in read(OUT/'NATIVE_REFERENCE_REGISTRY.json')['models']};registry=read(OUT/'REGIONAL_ASSEMBLY_ADMISSION.json')
    extra=read(OUT/'ADDITIONAL_REGIONAL_REFERENCES.json')
    direct_properties=0
    for r in extra['models']:
        assert sha(r['source_path'])==r['source_sha256'] and sha(OUT/r['assembly_bundle_path'])==r['assembly_bundle_sha256']
        db=AccessParser(r['source_path']);tab=db.parse_table('SYS_MATERIAL');materials={x['MATERIAL_ID']:x for x in [dict(zip(tab,row)) for row in zip(*tab.values())]}
        bundle=read(OUT/r['assembly_bundle_path']);idf_materials={row[1]:row for row in bundle['rows'] if row[0]=='Material'};constructions={row[1]:row for row in bundle['rows'] if row[0]=='Construction'}
        for evidence in bundle['opaque_layer_provenance']:
            table={'exterior':'SYS_OUTWALL_MATERIAL','interior':'SYS_INWALL_MATERIAL','floor':'SYS_MIDDLEFLOOR_MATERIAL'}[evidence['kind']];tab=db.parse_table(table)
            layers=sorted([dict(zip(tab,row)) for row in zip(*tab.values()) if dict(zip(tab,row))['STRUCT_ID']==evidence['native_used_struct_id']],key=lambda x:x['LAYER_NO'])
            compiled=constructions[bundle['names'][evidence['kind']]][2:];assert len(layers)==len(compiled)
            for raw,name in zip(layers,compiled):
                source=materials[raw['MATERIAL_ID']];expected=[raw['LENGTH']/1000,source['CONDUCTIVITY'],source['DENSITY'],source['SPECIFIC_HEAT']]
                assert max(abs(a-float(b)) for a,b in zip(expected,idf_materials[name][3:7]))<1e-10;direct_properties+=4
        inside=constructions[bundle['names']['interior']][2:];assert inside==inside[::-1],'symmetric_native_layer_identity_after_alias_deduplication'
    for r in routes['routes']:
        assert r['observed_household_effective_year'] is None and r['observed_household_city'] is None
        assert abs(sum(r['candidate_effective_year_epoch_prior_NG'])-1)<1e-10 and not r['actor_ready']
        for candidate in r['same_province_opaque_reference_and_WMO_coordinate_weather_candidates']:
            assert sha(OUT/candidate['assembly_bundle_path'])==candidate['assembly_bundle_sha256']
            for w in candidate['weather']:assert sha(w['path'])==w['sha256'] and w['distance_km']<5
    pilot=read(OUT/'REGIONAL_PILOT_RESULTS.json');seen=set()
    for r in pilot['cases']:
        assert sha(OUT/r['IDF_path'])==r['IDF_sha256'] and sha(OUT/r['run_path']/'eplusout.sql')==r['SQL_sha256']
        assert r['severe_or_fatal']==0 and r['returncode']==0 and len(r['target_private_area_weighted_air_temperature_C_24h'])==24
        if r['case_id'] in seen:continue
        seen.add(r['case_id']);c=read(OUT/r['case_path']);p=profiles[c['household_id']];w=c['world'];rr=parse(OUT/r['IDF_path'])
        assert abs(w['target_H6_unrounded_m2']-p['housing']['H6_census_building_area_design_m2'])<1e-6
        assert w['target_H7']==p['housing']['H7_independent_natural_rooms_design'] and w['shared_household_count_design']==p['housing']['shared_household_count_design']
        for label in ['sleep0_6m','sleep0_8m']:assert not audit_sleep(c[label],w,rr,p),(c['case_id'],label)
        assert not any(z[0] in ['People','ElectricEquipment','GasEquipment','ZoneHVAC:IdealLoadsAirSystem'] for z in rr)
    old=[]
    for folder in ['idf_joint_production_20261005','production_route_v6_20261004','benchmark_foundation_20261004','idf_unit_evidence_20261004','production_route_v5_20261004','end_to_end_plan_20261004','production_route_v4_20261003','construction_chain_20261003']:
        path=BASE/folder;manifest=read(path/'PACKAGE_MANIFEST.json');n=0
        for name,h in manifest['files'].items():assert sha(path/name)==h,folder+'/'+name;n+=1
        old.append({'package':folder,'manifest_sha256':sha(path/'PACKAGE_MANIFEST.json'),'files_unchanged':n})
    source=read(OUT/'YEAR_SOURCE_ADMISSION.json');holdout=read(OUT/'YEAR_JOINT_HOLDOUT.json')
    assert source['existing_owned_direct_room_area_subframe']==1779 and source['admitted_owned_joint_year_proxy_households']==1495
    assert holdout['delta_joint_minus_factorized']>0,'do_not_relabel_negative_comparison_as_superiority'
    report={'status':'passed_implementation_and_semantic_checks;not_stock_behavior_or_energy_calibration',
      'source_semantic_controls':controls,'world_coordinate_sleep_audits':len(summaries),'placed_bed_rectangles_checked_across_two_scenarios':beds,
      'sleep_negative_controls':negative,'regional_source_parameter_worlds_checked':len(seen),'runtime_season_outputs_checked':len(pilot['cases']),
      'additional_direct_native_material_properties_checked':direct_properties,
      'old_packages_content_unchanged':old,'old_package_files_checked':sum(p['files_unchanged'] for p in old),
      'population_N_G_R_area_q_anchor_preserved':True,'unidentified_source_year_city_and_stock_frequency_preserved':True,
      'complete_household_IDFs':0,'complete_actor_packages':0,'scientific_benchmark_admitted':False}
    save('VERIFICATION.json',report);print(json.dumps({k:v for k,v in report.items() if k not in ['old_packages_content_unchanged','source_semantic_controls']},ensure_ascii=False,indent=2))
if __name__=='__main__':main()
