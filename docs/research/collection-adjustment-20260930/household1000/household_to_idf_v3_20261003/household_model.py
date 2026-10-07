#!/usr/bin/env python3
"""Explicit household-to-building contract and closed rectangular research layout."""
import hashlib
import json
import math
import re
from collections import OrderedDict
from pathlib import Path

HERE=Path(__file__).resolve().parent
REPO=next(p for p in HERE.parents if p.name=='energybridge-household-survey')
BATCH='HOUSEHOLD_TO_IDF_20261003_V3'
MODELED_H6_EVIDENCE='modeled_binned_CHFS_area_proxy_then_census_longform_group_mean_calibration'
MODELED_H6_EVIDENCES={MODELED_H6_EVIDENCE,
    'modeled_coarsened_CHFS_area_reference_with_ESS_hierarchical_shrinkage',
    'modeled_support_bounded_exponential_tilt_of_CHFS_area_reference_to_census_expected_group_mean',
    'modeled_strict_H7_CHFS_area_reference_with_empirical_endpoint_support_and_ESS_shrinkage',
    'modeled_empirical_endpoint_bounded_exponential_tilt_of_strict_H7_CHFS_area_reference_to_census_expected_group_mean'}
MODELED_H7_EVIDENCE={
    'modeled_census_ordinary_conditional_integer_calibration_with_ESS_shrunk_CHFS_association_source_association',
    'modeled_census_ordinary_conditional_integer_calibration_with_ESS_shrunk_CHFS_association_independent_size',
    'modeled_census_ordinary_conditional_integer_calibration_with_CHFS_association_source_association',
    'modeled_census_ordinary_conditional_integer_calibration_with_CHFS_association_independent_size'}
_PROFILE_CACHE=OrderedDict()

def finite_real(value):
    """The compiler computes with finite binary64 values, never arbitrary ints.

    This is a representability rule, not a demographic/building-code range.
    Counts retain their separate exact-integer semantic checks.
    """
    if not isinstance(value,(int,float)) or isinstance(value,bool):return False
    try:return math.isfinite(float(value))
    except (OverflowError,ValueError,TypeError):return False

def numeric_tree_errors(value,path='$'):
    """Apply one numerical admission policy to used and unused JSON fields."""
    errors=[]
    if isinstance(value,(int,float)) and not isinstance(value,bool):
        if not finite_real(value):errors.append('number_not_finite_binary64:'+path)
    elif isinstance(value,dict):
        for key,child in value.items():errors.extend(numeric_tree_errors(child,path+'.'+str(key)))
    elif isinstance(value,list):
        for i,child in enumerate(value):errors.extend(numeric_tree_errors(child,path+'['+str(i)+']'))
    return errors

def verify_generation_binding(item):
    """Bind modeled H6/H7 to an existing generated profile without relabeling it.

    Rehash the file every call; cache only parsing keyed by actual bytes.
    This proves profile consistency, never population validity/geography.
    """
    binding=item.get('generation_binding');errors=[]
    result={'status':'blocked','scope':'selected generated profile byte/slot/family-housing consistency only; not measured household or actual home geography/population validation',
            'errors':errors,'family_or_housing_modified':False,'empirical_calibration':False}
    try:
        if not isinstance(binding,dict):raise ValueError('generation_binding_missing_or_not_object')
        for key in ['profile_file_path','profile_file_sha256','slot_id','family_semantic_sha256','housing_semantic_sha256']:
            if not isinstance(binding.get(key),str) or not binding[key]:raise ValueError('generation_binding_field_missing:'+key)
        for key in ['profile_file_sha256','family_semantic_sha256','housing_semantic_sha256']:
            if not re.fullmatch(r'[0-9a-f]{64}',binding[key]):raise ValueError('generation_binding_invalid_sha256:'+key)
        path=Path(binding['profile_file_path']).resolve()
        if not path.is_relative_to(REPO.resolve()):raise ValueError('generation_profile_outside_repository')
        raw=path.read_bytes();actual=hashlib.sha256(raw).hexdigest()
        result.update(profile_file_path=str(path),profile_file_sha256=actual,slot_id=binding['slot_id'])
        if actual!=binding['profile_file_sha256']:raise ValueError('generation_profile_file_hash_mismatch')
        cachekey=(str(path),actual)
        if cachekey not in _PROFILE_CACHE:
            def bad(value):raise ValueError('generation_profile_nonfinite_constant:'+value)
            obj=json.loads(raw,parse_constant=bad)
            if numeric_tree_errors(obj):raise ValueError('generation_profile_number_not_finite_binary64')
            profiles=obj.get('profiles') if isinstance(obj,dict) else None
            if not isinstance(profiles,list) or not all(isinstance(p,dict) and isinstance(p.get('slot_id'),str) for p in profiles):raise ValueError('generation_profile_list_invalid')
            index={p['slot_id']:p for p in profiles}
            if len(index)!=len(profiles):raise ValueError('generation_profile_duplicate_slot_ids')
            _PROFILE_CACHE[cachekey]=index
        _PROFILE_CACHE.move_to_end(cachekey)
        while len(_PROFILE_CACHE)>8:_PROFILE_CACHE.popitem(last=False)
        profile=_PROFILE_CACHE[cachekey].get(binding['slot_id'])
        if profile is None:raise ValueError('generation_profile_slot_not_found')
        for section in ['family','housing']:
            actual_digest=digest(item[section]);source_digest=digest(profile[section])
            result[section+'_semantic_sha256']=actual_digest
            if actual_digest!=source_digest or actual_digest!=binding[section+'_semantic_sha256']:raise ValueError('generation_'+section+'_semantic_hash_mismatch')
        result['status']='pass'
    except (ValueError,TypeError,KeyError,OSError,OverflowError) as exc:errors.append(str(exc))
    return result

def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()

def digest(value):
    return hashlib.sha256(json.dumps(value,ensure_ascii=False,sort_keys=True,separators=(',',':'),allow_nan=False).encode()).hexdigest()

def save(path,value):
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
    path.write_text(json.dumps(value,ensure_ascii=False,indent=2,allow_nan=False)+'\n')

def decision(trace,key,value,evidence,inputs,rule,limits=None):
    trace.append({'decision_id':key,'value':value,'evidence_status':evidence,'input_paths':inputs,
                  'rule':rule,'limitations':limits or []})

def template_policy():
    return json.loads((HERE/'TEMPLATE_POLICY.json').read_text())

def effective_geometry(item):
    """Separate observed/modeled housing facts from an explicit shape condition."""
    h=item.get('housing',{});condition=item.get('geometry_condition');errors=[]
    facts={k:h.get(k) for k in ['dwelling_type','household_storeys','building_total_storeys_design']}
    chosen=dict(facts)
    if condition is not None:
        if not isinstance(condition,dict):errors.append('geometry_condition_not_object')
        else:
            if condition.get('kind')!='conditional_engineering_design':errors.append('geometry_condition_kind_invalid')
            if condition.get('does_not_identify_population_type') is not True:errors.append('geometry_condition_population_boundary_missing')
            for key in ['evidence_id','rationale']:
                if not isinstance(condition.get(key),str) or not condition[key].strip():errors.append('geometry_condition_'+key+'_missing')
            if condition.get('dwelling_type') not in ['apartment','single_storey_ordinary_house_design']:errors.append('geometry_condition_dwelling_type_unsupported')
            if type(condition.get('household_storeys')) is not int or condition['household_storeys']!=1:errors.append('geometry_condition_household_storeys_unsupported')
            # A conditional alternative does not override positively known scope.
            for key in ['dwelling_type','household_storeys']:
                if facts[key] is not None and facts[key]!=condition.get(key):errors.append('geometry_condition_conflicts_with_known_'+key)
            chosen.update({k:condition.get(k) for k in ['dwelling_type','household_storeys']})
    return {'housing_facts':facts,'effective_geometry':chosen,'condition':condition,
            'housing_fact_signature':digest(facts),'condition_signature':digest(condition),
            'functional_layout_status':'not_validated','population_type_identified_by_condition':False,'errors':errors}

def effective_boundary_policy(item):
    """V3 policy is a separate experimental exposure, never a housing rewrite."""
    p=dict(item['model_policy']);g=effective_geometry(item)['effective_geometry'];h=item['housing']
    one=h.get('building_total_storeys_design')==1 or g.get('dwelling_type')=='single_storey_ordinary_house_design'
    if one:
        p.update(floor_position='single_storey',floor_number_design=1 if h.get('building_total_storeys_design')==1 else None)
        if not p.get('ground_temperature_method'):
            t=template_policy()['single_storey'];p.update({k:t[k] for k in ['ground_temperature_method','ground_monthly_temperatures_C','ground_temperature_evidence']})
    return p

def input_errors(item):
    if not isinstance(item,dict):return ['input_case_not_object']
    errors=numeric_tree_errors(item)
    if errors:return sorted(set(errors))
    real=finite_real
    def require(ok,name):
        if not ok:errors.append(name)
    require(isinstance(item.get('case_id'),str) and bool(re.fullmatch(r'[A-Za-z0-9_-]{1,100}',item.get('case_id',''))),'case_id_missing_or_unsafe')
    require(item.get('expected_result') in [None,'idf_ready','blocked'],'expected_result_invalid')
    for key in ['family','housing','model_policy','site']:
        if not isinstance(item.get(key),dict):return ['input_section_missing_or_not_object:'+key]
    members=item.get('family',{}).get('resident_member_ids')
    require(isinstance(members,list) and len(members)>0,'resident_roster_missing')
    members_valid=isinstance(members,list) and all(isinstance(x,str) and x for x in members)
    if members_valid:
        require(len(members)==len(set(members)),'resident_ids_not_unique')
        require(all(isinstance(x,str) and x for x in members),'resident_id_invalid')
        require(type(item['family'].get('resident_count')) is int and item['family']['resident_count']==len(members),'resident_count_roster_mismatch')
    family=item.get('family',{})
    require(family.get('population_scope')=='city_family_household','city_family_scope_not_declared')
    require(family.get('residence_evidence') in ['matched_chfs_proxy','declared_synthetic_role','actor_supplied'],'residence_evidence_missing')
    h=dict(item.get('housing',{}));p=effective_boundary_policy(item)
    geo=effective_geometry(item);errors+=geo['errors'];h.update({k:v for k,v in geo['effective_geometry'].items() if k in ['dwelling_type','household_storeys']})
    require(h.get('H5_status')=='ordinary_declared_or_matched','H5_not_ordinary_or_unresolved')
    require(isinstance(h.get('H5_evidence'),str) and bool(h['H5_evidence'].strip()),'H5_evidence_missing')
    require(h.get('occupancy_scope')=='whole_household_private','shared_scope_not_resolved')
    require(type(h.get('household_storeys')) is int and h['household_storeys']==1,'household_multistorey_unsupported')
    require(h.get('dwelling_type') in ['apartment','single_storey_ordinary_house_design'],'dwelling_type_unsupported')
    area=h.get('H6_building_area_m2')
    require(real(area) and area>0,'H6_missing_or_invalid')
    require(h.get('H6_evidence') in ['matched_area_proxy','source_reported','declared_design',*MODELED_H6_EVIDENCES],'H6_evidence_missing')
    rooms=h.get('H7_natural_rooms_exact')
    require(isinstance(rooms,int) and not isinstance(rooms,bool) and 1<=rooms<=20,'H7_exact_missing_or_invalid')
    require(h.get('H7_evidence') in ['matched_census_conditional','source_proxy','declared_design','actor_supplied',*MODELED_H7_EVIDENCE],'H7_evidence_missing')
    modeled_h7=isinstance(h.get('H7_evidence'),str) and h['H7_evidence'] in MODELED_H7_EVIDENCE
    modeled_h6=isinstance(h.get('H6_evidence'),str) and h['H6_evidence'] in MODELED_H6_EVIDENCES
    if modeled_h6 or modeled_h7 or 'generation_binding' in item:
        errors+=['generation_binding:'+e for e in verify_generation_binding(item)['errors']]
    require(h.get('H7_definition')=='natural_rooms_excluding_kitchen_toilet_corridor_hall','H7_definition_mismatch')
    groups=h.get('sleep_groups')
    require(isinstance(groups,list) and isinstance(rooms,int) and len(groups)==rooms,'sleep_groups_H7_mismatch')
    if isinstance(groups,list) and all(isinstance(g,list) and all(isinstance(m,str) and m for m in g) for g in groups) and members_valid:
        assigned=[m for g in groups for m in g]
        require(sorted(assigned)==sorted(members),'sleep_assignment_not_exact_resident_partition')
    else:require(False,'sleep_group_format_invalid')
    ratio=p.get('gross_to_zone_floor_ratio')
    require(real(ratio) and 0<ratio<=1,'net_ratio_missing_or_invalid')
    require(p.get('net_ratio_evidence')=='declared_geometry_bridge','net_ratio_evidence_missing')
    require(p.get('floor_position') in ['middle','top','ground','single_storey'],'floor_position_missing')
    total=h.get('building_total_storeys_design');number=p.get('floor_number_design');position=p.get('floor_position')
    if total is not None:
        require(type(total) is int and total>=1,'building_total_storeys_design_invalid')
        if type(total) is int and total>=1:
            require(position!='middle' or total>=3,'middle_floor_requires_at_least_three_building_storeys')
            require(position!='top' or total>=2,'single_storey_top_requires_ground_and_roof_template_unsupported')
            require(position!='ground' or total>=2,'single_storey_ground_requires_ground_and_roof_template_unsupported')
            require(position!='single_storey' or total==1,'single_storey_boundary_conflicts_with_building_total_storeys')
    if number is not None:
        require(type(total) is int and total>=1,'floor_number_requires_known_building_total_storeys')
        require(type(number) is int and number>=1,'floor_number_design_invalid')
        if type(number) is int and type(total) is int and total>=1:
            require(1<=number<=total,'floor_number_outside_building')
            require(position!='middle' or 1<number<total,'middle_floor_number_inconsistent')
            require(position!='top' or number==total,'top_floor_number_inconsistent')
            require(position not in ['ground','single_storey'] or number==1,'ground_floor_number_inconsistent')
    require(p.get('floor_position') not in ['ground','single_storey'] or (p.get('ground_temperature_method')=='explicit_research_boundary' and
            isinstance(p.get('ground_monthly_temperatures_C'),list) and len(p['ground_monthly_temperatures_C'])==12 and all(real(v) for v in p['ground_monthly_temperatures_C'])),'ground_boundary_unresolved')
    require(p.get('wall_boundaries') in [{'west':'Adiabatic','east':'Adiabatic','south':'Outdoors','north':'Outdoors'},
            {'west':'Outdoors','east':'Outdoors','south':'Outdoors','north':'Outdoors'}],'wall_boundary_policy_missing_or_unsupported')
    require(real(p.get('north_axis_deg')) and 0<=p['north_axis_deg']<360,'orientation_missing_or_invalid')
    require(real(p.get('air_exchange_ach')) and 0<=p['air_exchange_ach']<=10,'air_exchange_missing_or_invalid')
    require(isinstance(item.get('prototype_request'),dict) or (isinstance(p.get('prototype_key'),str) and bool(p.get('prototype_key'))),'thermal_prototype_missing')
    require(item.get('operation_mode')=='building_shell_validation','operation_mode_not_supported')
    return sorted(set(errors))

def legacy_capacity_diagnostic(item):
    h=item['housing'];net=h['H6_building_area_m2']*item['model_policy']['gross_to_zone_floor_ratio']
    minimums=[max(1.5,.9*len(g)+.6) for g in h['sleep_groups']];minimum=max(4.5,sum(minimums))
    return {'policy':'frozen_v2_individual_0p9x2m_berths_and3m_service_band',
        'admission_effect':'none_in_v3','minimum_widths_m':minimums,'required_zone_area_proxy_m2':minimum*5.6,
        'available_zone_area_proxy_m2':net,'would_fail_v2_capacity_policy':net<minimum*5.6-1e-8,
        'actual_furniture_or_habitability_validated':False}

def make_layout(item,trace):
    h=item['housing'];p=item['model_policy'];area=h['H6_building_area_m2']
    net=area*p['gross_to_zone_floor_ratio'];groups=h['sleep_groups'];rooms=h['H7_natural_rooms_exact']
    policy=template_policy()['layout'];single=rooms==1
    minimum_width=2.4 if single else max(3.0,rooms*.8)
    width=max(minimum_width,math.sqrt(net*1.25));depth=net/width
    service_depth=1.2;corridor_depth=0 if single else .8;natural_start=service_depth+corridor_depth
    if depth-natural_start<(.8 if single else .6)-1e-8:
        return None,['compact_thermal_partition_support_limit_no_area_or_H7_repair']
    weights=[1+.15*len(g) for g in groups];spare=width-rooms*.8
    widths=[.8+spare*w/sum(weights) for w in weights]
    spaces=[];windows=[];doors=[];cursor=0
    for i,(g,w) in enumerate(zip(groups,widths),1):
        end=width if i==rooms else cursor+w;name=f'natural_{i}';center=(cursor+end)/2
        spaces.append({'name':name,'kind':'natural_room','rect_m':[cursor,natural_start,end,depth],
            'member_ids_sleeping':g,'bed_footprints':[],
            'function_design':'natural_room_label_with_declared_sleep_assignment_only',
            'functional_layout_status':'not_validated'})
        windows.append({'space':name,'edge':'y='+str(depth),'span_m':[center-.3,center+.3],'height_m':1.2,'sill_m':.9})
        if not single:doors.append({'from':'corridor','to':name,'edge':'y='+str(natural_start),'span_m':[center-.3,center+.3]})
        cursor=end
    if single:
        service=[('kitchen','kitchen',0,width/2),('bathroom','bath_toilet',width/2,width)]
        for name,kind,x0,x1 in service:
            spaces.append({'name':name,'kind':kind,'rect_m':[x0,0,x1,service_depth]})
            center=(x0+x1)/2;doors.append({'from':name,'to':'natural_1','edge':'y='+str(service_depth),'span_m':[center-.3,center+.3]})
        entry_to='natural_1';entry_center=(natural_start+depth)/2
    else:
        service=[('kitchen','kitchen',0,width*.35),('bathroom','bath_toilet',width*.35,width*.65),('living_hall','hall_not_H7',width*.65,width)]
        for name,kind,x0,x1 in service:
            spaces.append({'name':name,'kind':kind,'rect_m':[x0,0,x1,service_depth]})
            center=(x0+x1)/2;doors.append({'from':name,'to':'corridor','edge':'y='+str(service_depth),'span_m':[center-.3,center+.3]})
        spaces.append({'name':'corridor','kind':'circulation','rect_m':[0,service_depth,width,natural_start]})
        entry_to='corridor';entry_center=(service_depth+natural_start)/2
    for name in ['kitchen']+([] if single else ['living_hall']):
        s=next(s for s in spaces if s['name']==name);center=(s['rect_m'][0]+s['rect_m'][2])/2
        windows.append({'space':name,'edge':'y=0','span_m':[center-.3,center+.3],'height_m':1.2,'sill_m':.9})
    doors.append({'from':'entry','to':entry_to,'edge':'x=0','span_m':[entry_center-.3,entry_center+.3],
        'thermal_status':('explicit_exterior_door' if p['wall_boundaries']['west']=='Outdoors' else 'adjacent_conditioned_common_corridor_proxy_not_explicit_external_aperture')})
    for s in spaces:
        x0,y0,x1,y1=s['rect_m'];s.update(dimensions_m=[x1-x0,y1-y0],floor_area_m2=(x1-x0)*(y1-y0),functional_layout_status='not_validated')
    layout={'schema':'eb.closed_rectangular_layout.v1','layout_policy':'compact_thermal_partition_v3',
        'gross_H6_m2':area,'net_proxy_m2':net,'gross_minus_zone_floor_area_m2':area-net,
        'gross_residual_identity':'unmodeled wall/common-area bridge, not observed decomposition',
        'envelope_rect_m':[0,0,width,depth],'spaces':spaces,'windows':windows,'doors':doors,
        'H7_materialized_natural_rooms':rooms,'sleep_assignment_evidence':'declared groups attached to thermal natural-room labels; bed placement not validated',
        'corridor_width_m':corridor_depth,'capacity_rule':'furniture-independent rectangular thermal-zone and0.6m opening template support only',
        'furniture_capacity_used_for_admission':False,'legacy_capacity_diagnostic':legacy_capacity_diagnostic(item),
        'functional_layout_status':'not_validated','device_placement_status':'not_validated','collectable':False,
        'building_code_certified':False,'layout_observed':False,'entry_and_egress_code_validated':False}
    decision(trace,'zone_floor_area',net,'derived_design',['housing.H6_building_area_m2','model_policy.gross_to_zone_floor_ratio'],
        'zone area = H6 x explicitly declared net ratio',['not an official gross-to-usable measurement'])
    decision(trace,'H7_and_service_zones',{'natural':rooms,'service':len(spaces)-rooms},'designed',['housing.H7_natural_rooms_exact'],
        'natural rooms retained; single-room case has kitchen/bath and no forced hall/corridor',
        ['thermal labels and sleep attachment do not validate natural-room function or furniture'])
    decision(trace,'rectangular_layout',{'width_m':width,'depth_m':depth,'policy':'compact_thermal_partition_v3'},'designed',
        ['housing.H7_natural_rooms_exact','housing.sleep_groups','zone_floor_area','TEMPLATE_POLICY.json'],
        'thermal partition closes the fixed area with fixed H7; sleep counts do not impose rectangular bed capacity',
        ['functional_layout_status=not_validated','not observed shape','not building-code or furniture verification','not collectable'])
    return layout,[]

def layout_checks(item,layout):
    errors=[];spaces=layout['spaces'];net=layout['net_proxy_m2']
    area=0;bed_members=[];sleep_members=[]
    thermal_only=layout.get('furniture_capacity_used_for_admission') is False
    for s in spaces:
        sleep_members+=s.get('member_ids_sleeping',[])
        if thermal_only and s.get('bed_footprints'):errors.append('unexpected_furniture_in_thermal_only_layout')
        x0,y0,x1,y1=s['rect_m'];area+=(x1-x0)*(y1-y0)
        if min(x1-x0,y1-y0)<.01:errors.append('sub1cm_space')
        for bed in s.get('bed_footprints',[]):
            bed_members.append(bed['member_id'])
            a,b,c,d=bed['rect_m']
            if not(x0-1e-6<=a<c<=x1+1e-6 and y0-1e-6<=b<d<=y1+1e-6):errors.append('bed_outside_room')
        beds=s.get('bed_footprints',[])
        if not thermal_only and sorted(b['member_id'] for b in beds)!=sorted(s.get('member_ids_sleeping',[])):errors.append('room_bed_members_mismatch')
        for i,a in enumerate(beds):
            for b in beds[i+1:]:
                ra,rb=a['rect_m'],b['rect_m']
                if min(ra[2],rb[2])-max(ra[0],rb[0])>1e-7 and min(ra[3],rb[3])-max(ra[1],rb[1])>1e-7:errors.append('overlapping_beds')
    for i,a in enumerate(spaces):
        for b in spaces[i+1:]:
            ra,rb=a['rect_m'],b['rect_m']
            overlap=max(0,min(ra[2],rb[2])-max(ra[0],rb[0]))*max(0,min(ra[3],rb[3])-max(ra[1],rb[1]))
            if overlap>1e-7:errors.append('overlapping_spaces')
    if abs(area-net)>1e-6:errors.append('zone_area_not_closed')
    if sum(s['kind']=='natural_room' for s in spaces)!=item['housing']['H7_natural_rooms_exact']:errors.append('H7_changed')
    if not thermal_only and sorted(bed_members)!=sorted(item['family']['resident_member_ids']):errors.append('bed_members_not_exact_resident_partition')
    if sorted(sleep_members)!=sorted(item['family']['resident_member_ids']):errors.append('sleep_members_not_exact_resident_partition')
    graph={s['name']:set() for s in spaces};graph['entry']=set()
    for d in layout['doors']:
        if d['from'] not in graph or d['to'] not in graph:errors.append('door_connects_unknown_space');continue
        graph[d['from']].add(d['to']);graph[d['to']].add(d['from'])
    reached=set();todo=['entry']
    while todo:
        name=todo.pop()
        if name not in reached:reached.add(name);todo.extend(graph[name]-reached)
    if reached!=set(graph):errors.append('space_not_connected_to_entry')
    return sorted(set(errors))
