#!/usr/bin/env python3
"""Plan source holdout after structural artifacts and before human outcomes.

Independent actual-IDF readback. No simulation-output columns, survey microdata,
builder import or material names in the output. Refused slots retain null actual
closures. Source + planned catalogue closure + actual-used closure are unioned.
"""
from __future__ import annotations
import argparse
import hashlib
import json
import math
import re
from collections import Counter, defaultdict
from copy import deepcopy
from decimal import Decimal, InvalidOperation
from pathlib import Path

MATERIAL_TYPES={'material','material:nomass','material:airgap',
 'windowmaterial:glazing','windowmaterial:simpleglazingsystem',
 'windowmaterial:gas'}

def sha(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()
def digest(value):return hashlib.sha256(json.dumps(value,sort_keys=True,ensure_ascii=False,separators=(',',':'),allow_nan=False).encode()).hexdigest()
def finite_tree(value):
    if isinstance(value,float) and not math.isfinite(value):return False
    if isinstance(value,dict):return all(finite_tree(v) for v in value.values())
    if isinstance(value,list):return all(finite_tree(v) for v in value)
    return True
def load(path):
    value=json.loads(Path(path).read_text())
    if not finite_tree(value):raise ValueError('nonfinite_json:'+str(path))
    return value
def normalized(value):
    text=str(value).strip()
    try:
        d=Decimal(text)
    except InvalidOperation:
        return text.casefold()
    if not d.is_finite() or not math.isfinite(float(d)):raise ValueError('nonfinite_material_field')
    return format(d.normalize(),'f')
def source_group_id(binding):
    return 'prototype_'+digest({'source_sha256':binding['source_idf_sha256'],
                               'parent_sha256':binding['parent_idf_sha256']})[:20]

def actual_closure(folder):
    """Return actual-used source role fingerprints and boundary diagnostics.

    Exact normalized input-field identity, not equality of U-value or a claim
    that omitted/default fields across all EnergyPlus versions are equivalent.
    Height/boundary differences are kept as diagnostics but do not split equal
    source assembly closures, making the material holdout conservative.
    """
    binding=load(folder/'ASSEMBLY_BINDING.json')
    objects=[[v.strip() for v in block.split(',')] for block in
             re.sub(r'!.*','',(folder/'building.idf').read_text()).split(';') if block.strip()]
    if any(r[0].casefold().startswith(('materialproperty:','constructionproperty:')) for r in objects):
        raise ValueError('unsupported_property_addon_for_closure_signature')
    mats={};cons={}
    for row in objects:
        typ=row[0].casefold()
        space=mats if typ in MATERIAL_TYPES else cons if typ=='construction' else None
        if space is not None:
            name=row[1].casefold()
            if name in space:raise ValueError('duplicate_material_or_construction_namespace')
            space[name]=row
    def construction(name):
        row=cons[name.casefold()];layers=[]
        for name in row[2:]:
            m=mats[name.casefold()]
            layers.append(digest([m[0].casefold(),*[normalized(v) for v in m[2:]]]))
        return digest(layers),layers
    used={r[3] for r in objects if r[0].casefold() in ['buildingsurface:detailed','fenestrationsurface:detailed']}
    cmap=binding['construction_map'];policy=binding['effective_boundary_policy']
    ground=policy['floor_position'] in ['ground','single_storey']
    top=policy['floor_position'] in ['top','single_storey']
    chosen={role:name for role,name in cmap.items() if role in ['external_wall','internal_wall','window'] and name in used}
    chosen.update(floor=cmap['ground_floor'] if ground else cmap['floor'],
                  ceiling_or_roof=cmap['roof'] if top else cmap['ceiling'])
    if any(name not in used for name in chosen.values()):raise ValueError('effective_horizontal_assembly_not_used')
    unresolved=used-set(cmap.values())
    if not unresolved.issubset({'Declared_Door','Declared_Interior_Door'}):
        raise ValueError('used_construction_not_in_source_or_declared_design_map')
    physical={};layerprints=[]
    for role,name in sorted(chosen.items()):
        fp,layers=construction(name);physical[role]=fp;layerprints.extend(layers)
    # Surface conditions are read from actual objects, not presumed from labels.
    boundaries=Counter((r[2],r[6]) for r in objects if r[0].casefold()=='buildingsurface:detailed')
    if ground != any(r[0].casefold()=='buildingsurface:detailed' and r[2].casefold()=='floor' and r[6].casefold()=='ground' for r in objects):
        raise ValueError('ground_selection_actual_surface_mismatch')
    if top != any(r[0].casefold()=='buildingsurface:detailed' and r[2].casefold()=='roof' and r[6].casefold()=='outdoors' for r in objects):
        raise ValueError('roof_selection_actual_surface_mismatch')
    return {'signature':digest(physical),'role_fingerprints':physical,
            'constituent_fingerprints':sorted(set(layerprints)),
            'boundary_role_signature':digest(sorted((a,b,n) for (a,b),n in boundaries.items())),
            'ground_used':ground,'outdoor_roof_used':top,
            'height_m':binding['source_height_m'],
            'source_group_id':source_group_id(binding),
            'idf_sha256':sha(folder/'building.idf'),
            'binding_sha256':sha(folder/'ASSEMBLY_BINDING.json')}

def verify_triple_split(rows):
    answer={}
    for key,name in [('source_group_id','source_group'),
                     ('assembly_numeric_signature','planned_catalog_closure'),
                     ('actual_used_assembly_signature','actual_used_closure')]:
        units=defaultdict(set)
        for row in rows:
            if row.get(key) is not None:units[row[key]].add(row['prototype_test_fold'])
        answer[name+'_split_leaks']=sum(len(folds)>1 for folds in units.values())
    answer['refused_actual_signature_not_null']=sum(row['structural_status']!='idf_ready' and row['actual_used_assembly_signature'] is not None for row in rows)
    answer['pass']=all(v==0 for v in answer.values())
    return answer

def build(planned_path,static):
    planned=load(planned_path);oldrows=planned['rows'];summary=load(static/'SUMMARY.json')
    inputs=load(static/'EXPERIMENT_INPUTS.json')
    if len(oldrows)!=1000 or len({r['slot_id'] for r in oldrows})!=1000:
        raise ValueError('all1000_unique_planned_slots_required')
    by_slot={x['population_slot_id']:x for x in inputs}
    statuses={r['case_id']:r for r in summary['records']}
    if len(inputs)!=1000 or len(by_slot)!=1000 or len(summary['records'])!=1000 or len(statuses)!=1000 or set(by_slot)!={r['slot_id'] for r in oldrows}:
        raise ValueError('all1000_static_plan_correspondence_required')
    rows=[];actual_detail={};provenance_hashes=[]
    for old in oldrows:
        slot=old['slot_id'];item=by_slot[slot];status=statuses[item['case_id']]
        folder=static/'cases'/status['case_folder']
        if not folder.resolve().is_relative_to((static/'cases').resolve()):raise ValueError('unsafe_case_path')
        if load(folder/'STATUS.json')!=status or load(folder/'INPUT.json')!=item:
            raise ValueError('static_case_readback_mismatch:'+slot)
        if sha(folder/'INPUT.json')!=status.get('input_sha256'):
            raise ValueError('static_input_bytes_mismatch:'+slot)
        if item['site'].get('coordinate_evidence',{}).get('source_epw_sha256')!=old['climate_epw_sha256']:
            raise ValueError('planned_context_weather_changed:'+slot)
        g=item.get('generation_binding',{})
        for a,b in [('profile_sha256','profile_file_sha256'),('family_sha256','family_semantic_sha256'),('housing_sha256','housing_semantic_sha256')]:
            if old[a]!=g.get(b):raise ValueError('planned_generation_binding_mismatch:'+slot+':'+a)
        if digest(item['family'])!=old['family_sha256'] or digest(item['housing'])!=old['housing_sha256']:
            raise ValueError('planned_family_or_housing_changed:'+slot)
        if g.get('slot_id')!=slot or status.get('generation_binding_status')!='pass':
            raise ValueError('generation_slot_not_verified:'+slot)
        row={**old,'planned_prototype_test_fold':old['prototype_test_fold'],
             'structural_status':status['status'],'actual_used_assembly_signature':None,
             'actual_boundary_role_signature':None,'actual_idf_sha256':None,
             'actual_ground_used':None,'actual_outdoor_roof_used':None}
        if status['status']=='idf_ready':
            detail=actual_closure(folder)
            if detail['source_group_id']!=old['source_group_id'] or status.get('prototype_source_group_id')!=old['source_group_id']:
                raise ValueError('planned_actual_source_group_mismatch:'+slot)
            if detail['idf_sha256']!=status.get('idf_sha256'):
                raise ValueError('actual_IDF_bytes_mismatch:'+slot)
            if status.get('weather_epw_sha256')!=old['climate_epw_sha256']:
                raise ValueError('planned_actual_weather_mismatch:'+slot)
            geometry=load(folder/'INDEPENDENT_GEOMETRY_CHECK.json')
            if geometry.get('status')!='pass' or geometry.get('errors')!=[] or geometry.get('idf_sha256')!=detail['idf_sha256']:
                raise ValueError('actual_geometry_readback_not_passed:'+slot)
            row.update(actual_used_assembly_signature=detail['signature'],
                       actual_boundary_role_signature=detail['boundary_role_signature'],
                       actual_idf_sha256=detail['idf_sha256'],actual_ground_used=detail['ground_used'],
                       actual_outdoor_roof_used=detail['outdoor_roof_used'])
            actual_detail[slot]=detail
        elif status['status']!='blocked':raise ValueError('unrecognized_static_status:'+slot)
        rows.append(row)
        provenance_hashes.append({'slot_id':slot,'input_sha256':sha(folder/'INPUT.json'),
                                 'status_sha256':sha(folder/'STATUS.json'),
                                 'assembly_binding_sha256':actual_detail[slot]['binding_sha256'] if slot in actual_detail else None})
    before=verify_triple_split(rows)
    parent={r['source_group_id']:r['source_group_id'] for r in rows}
    def root(key):
        while parent[key]!=key:
            parent[key]=parent[parent[key]];key=parent[key]
        return key
    def union(a,b):
        a,b=root(a),root(b)
        if a!=b:
            lo,hi=sorted([a,b]);parent[hi]=lo
    for key in ['assembly_numeric_signature','actual_used_assembly_signature']:
        buckets=defaultdict(set)
        for r in rows:
            if r[key] is not None:buckets[r[key]].add(r['source_group_id'])
        for groups in buckets.values():
            groups=sorted(groups)
            for other in groups[1:]:union(groups[0],other)
    components=defaultdict(list)
    for r in rows:components[root(r['source_group_id'])].append(r)
    # Balance all preserved slots only. Admission counts are reported afterward.
    sizes=[0]*5;assignment={}
    for group,items in sorted(components.items(),key=lambda p:(-len(p[1]),p[0])):
        fold=min(range(5),key=lambda f:(sizes[f],f));sizes[fold]+=len(items);assignment[group]=fold
    for r in rows:
        r['prototype_component_id']=root(r['source_group_id']);r['prototype_test_fold']=assignment[r['prototype_component_id']]
    verified=verify_triple_split(rows)
    if not verified['pass']:raise ValueError('triple_closure_isolation_failed')
    constituent_slots=defaultdict(set);constituent_folds=defaultdict(set);role_folds=defaultdict(set)
    rowmap={r['slot_id']:r for r in rows}
    for slot,d in actual_detail.items():
        fold=rowmap[slot]['prototype_test_fold']
        for f in d['constituent_fingerprints']:
            constituent_slots[f].add(slot);constituent_folds[f].add(fold)
        for role,f in d['role_fingerprints'].items():role_folds[(role,f)].add(fold)
    cross_constituents=sum(len(fs)>1 for fs in constituent_folds.values())
    cross_roles=sum(len(fs)>1 for fs in role_folds.values())
    ready=[sum(r['prototype_test_fold']==fold and r['structural_status']=='idf_ready' for r in rows) for fold in range(5)]
    blocked=[sizes[f]-ready[f] for f in range(5)]
    sourcecounts=[len({r['source_group_id'] for r in rows if r['prototype_test_fold']==f}) for f in range(5)]
    component_info=[{'component_id':gid,'slots':len(items),
       'ready':sum(r['structural_status']=='idf_ready' for r in items),
       'source_groups':len({r['source_group_id'] for r in items}),
       'planned_closures':len({r['assembly_numeric_signature'] for r in items}),
       'actual_used_closures':len({r['actual_used_assembly_signature'] for r in items if r['actual_used_assembly_signature']}),
       'fold':assignment[gid]} for gid,items in sorted(components.items(),key=lambda p:(-len(p[1]),p[0]))]
    neg=deepcopy(rows)
    group=Counter(r['source_group_id'] for r in neg).most_common(1)[0][0]
    victim=next(r for r in neg if r['source_group_id']==group)
    victim['prototype_test_fold']=(victim['prototype_test_fold']+1)%5
    bad=verify_triple_split(neg)
    if bad['pass']:raise ValueError('negative_fold_mutation_not_detected')
    payload={'schema':'eb.actual_engineering_dependency_plan.v1',
       'planned_path':str(planned_path.resolve()),'planned_sha256':sha(planned_path),
       'static_path':str(static.resolve()),'static_summary_sha256':sha(static/'SUMMARY.json'),
       'static_inputs_sha256':sha(static/'EXPERIMENT_INPUTS.json'),'builder_sha256':sha(__file__),
       'case_artifact_hashes':provenance_hashes,'rows':rows,
       'counts':{'retained_slots':1000,'ready':len(actual_detail),'blocked':1000-len(actual_detail),
          'source_groups':len(parent),'planned_catalog_closures':len({r['assembly_numeric_signature'] for r in rows}),
          'actual_used_closures':len({r['actual_used_assembly_signature'] for r in rows if r['actual_used_assembly_signature']}),
          'components':len(components),'largest_component_slots':max(len(items) for items in components.values()),
          'largest_component_fraction':max(len(items) for items in components.values())/1000,
          'prototype_fold_sizes':sizes,'fold_ready_counts':ready,'fold_blocked_counts':blocked,
          'fold_source_group_counts':sourcecounts,'empty_folds':sum(n==0 for n in sizes)},
       'components':component_info,'planned_fold_readback':before,'verification':verified,
       'counter_control':{'name':'one_family_fold_mutated_after_union','detected':not bad['pass'],'verification':bad},
       'constituent_reuse':{'distinct_actual_material_fingerprints':len(constituent_slots),
          'material_fingerprints_used_in_multiple_slots':sum(len(xs)>1 for xs in constituent_slots.values()),
          'material_slot_incidence_count':sum(len(xs) for xs in constituent_slots.values()),
          'material_fingerprints_crossing_folds':cross_constituents,
          'distinct_role_construction_fingerprints':len(role_folds),
          'role_construction_fingerprints_crossing_folds':cross_roles,
          'cross_fold_roles':dict(Counter(role for (role,_),fs in role_folds.items() if len(fs)>1)),
          'does_not_establish_unseen_individual_materials':True},
       'assignment_used':['source_identity','predeclared_planned_catalog_closure','actual_used_source_assembly_closure','all1000component_sizes','deterministic_lexical_ties'],
       'assignment_did_not_use':['human_labels','actor_answers','prediction_models','thermal_output_values','admission_counts_for_balancing'],
       'timing':'revised after structural IDF artifacts; before human outcomes and model selection;not prespecified before the baseline structural run',
       'claim_scope':'unseen content source and complete actually-used source assembly closure under the same generator/writer;known constituent materials, actors and climate may overlap',
       'signature_scope':'ordered source layers and normalized emitted numeric/type fields;actual floor/ground and roof/ceiling selection;ignore height/boundary differences for conservative assembly merging;declared writer door design excluded;property addons fail closed;default-semantic equivalence across omitted fields not certified',
       'source_bytes_reverified':False,
       'source_provenance_scope':'source/parent recorded SHA group recomputed;actual emitted IDF and binding/status/input/geometry byte linkage read;source/parent original files not rescanned and survey microdata never read',
       'refused_actual_signature_policy':'null because no accepted physical artifact established;planned source/closure still groups them;future admitted branch may require new plan revision',
       'population_slots_reallocated':False,'family_housing_rewritten':False,
       'human_labels_created':0,'collection_release':False,'training_release':False}
    return payload

def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--planned',type=Path,required=True)
    ap.add_argument('--static',type=Path,required=True)
    ap.add_argument('--output',type=Path,required=True)
    args=ap.parse_args()
    if args.output.exists():raise ValueError('new_immutable_output_file_required')
    report=build(args.planned,args.static)
    args.output.parent.mkdir(parents=True,exist_ok=True)
    args.output.write_text(json.dumps(report,ensure_ascii=False,indent=2,allow_nan=False)+'\n')
    print(json.dumps({'counts':report['counts'],'verification':report['verification'],
                      'constituent_reuse':report['constituent_reuse']},ensure_ascii=False))
if __name__=='__main__':main()
