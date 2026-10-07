#!/usr/bin/env python3
"""Expose coupled engineering units without reading outcomes or answers."""
import argparse
import hashlib
import json
from collections import Counter, defaultdict
from pathlib import Path

HERE=Path(__file__).resolve().parent
V2=HERE.parent/'household_to_idf_v2_20261003'


def digest(value):return hashlib.sha256(json.dumps(value,sort_keys=True,ensure_ascii=False,separators=(',',':')).encode()).hexdigest()
def sha(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--contexts',type=Path,required=True)
    ap.add_argument('--output',type=Path,required=True)
    args=ap.parse_args()
    if args.output.exists():raise ValueError('immutable new output file required')
    rows=json.loads(args.contexts.read_text())
    registry=json.loads((V2/'PROTOTYPE_REGISTRY.json').read_text())
    aliases={v['role_key']:g for g in registry['groups'].values() for v in g['variants']}
    result=[];source_provinces=defaultdict(set);climate_provinces=defaultdict(set)
    for x in rows:
        key=x['prototype_request']['prototype_key'];g=aliases[key]
        variant=next(v for v in g['variants'] if v['role_key']==key);summary=variant['assembly_summary']
        # Conservatively combine identical selected layer properties even if
        # heights differ. A different source filename or alias adds no novelty.
        physical={role:summary['construction_details'][name]['ordered_layer_fingerprint']
                  for role,name in summary['constructions'].items()}
        signature=digest(physical)
        source_provinces[g['source_group_id']].add(x['site']['province'])
        epw=x['site']['coordinate_evidence']['source_epw_sha256']
        climate_provinces[epw].add(x['site']['province'])
        result.append({'slot_id':x['population_slot_id'],'case_id':x['case_id'],
                       'family_revision_key':x['population_slot_id'],
                       'profile_sha256':x['generation_binding']['profile_file_sha256'],
                       'family_sha256':x['generation_binding']['family_semantic_sha256'],
                       'housing_sha256':x['generation_binding']['housing_semantic_sha256'],
                       'source_group_id':g['source_group_id'],
                       'assembly_numeric_signature':signature,
                       'selected_assembly_height_m':summary['height_m'],
                       'climate_epw_sha256':epw,'province':x['site']['province'],
                       'actor_id':None,'scenario_family_id':None})
    if len(result)!=1000 or len({r['slot_id'] for r in result})!=1000:raise ValueError('all1000 unique slots required')
    # Connected components of source identity AND equivalent assembly identity
    # prevent two aliases/material-equivalent sources from straddling a split.
    parent={r['source_group_id']:r['source_group_id'] for r in result}
    def root(key):
        while parent[key]!=key:
            parent[key]=parent[parent[key]];key=parent[key]
        return key
    bysignature=defaultdict(set)
    for r in result:bysignature[r['assembly_numeric_signature']].add(r['source_group_id'])
    for groups in bysignature.values():
        ordered=sorted(groups)
        for group in ordered[1:]:parent[root(group)]=root(ordered[0])
    components=defaultdict(list)
    for r in result:components[root(r['source_group_id'])].append(r)
    sizes=[0]*5
    assignments={}
    for group,items in sorted(components.items(),key=lambda p:(-len(p[1]),p[0])):
        fold=min(range(5),key=lambda f:(sizes[f],f));sizes[fold]+=len(items);assignments[group]=fold
    climates=sorted(climate_provinces)
    for r in result:
        r['prototype_component_id']=root(r['source_group_id'])
        r['prototype_test_fold']=assignments[r['prototype_component_id']]
        r['climate_leave_one_context_out_fold']=climates.index(r['climate_epw_sha256'])
    material_folds=defaultdict(set);construction_folds=defaultdict(set)
    for x,r in zip(rows,result):
        g=aliases[x['prototype_request']['prototype_key']]
        summary=next(v for v in g['variants'] if v['role_key']==x['prototype_request']['prototype_key'])['assembly_summary']
        for role,name in summary['constructions'].items():
            detail=summary['construction_details'][name]
            construction_folds[(role,detail['ordered_layer_fingerprint'])].add(r['prototype_test_fold'])
            for layer in detail['outside_to_inside_layers']:
                material_folds[layer['physical_fingerprint']].add(r['prototype_test_fold'])
    source_leaks=sum(len({r['prototype_test_fold'] for r in result if r['source_group_id']==g})!=1 for g in parent)
    assembly_leaks=sum(len({r['prototype_test_fold'] for r in result if r['assembly_numeric_signature']==s})!=1 for s in bysignature)
    payload={'schema':'eb.engineering_dependency_plan.v1','contexts_path':str(args.contexts.resolve()),
        'contexts_sha256':sha(args.contexts),'prototype_registry_sha256':sha(V2/'PROTOTYPE_REGISTRY.json'),
        'builder_sha256':sha(__file__),'rows':result,
        'counts':{'retained_slots':1000,'content_source_groups':len(parent),
                  'numeric_assembly_signatures':len(bysignature),'prototype_components':len(components),
                  'prototype_fold_sizes':sizes,'climate_contexts':len(climates),
                  'actual_actors':0,'actual_scenario_families':0},
        'verification':{'source_group_split_leaks':source_leaks,'equivalent_assembly_split_leaks':assembly_leaks,
                        'pass':source_leaks==0 and assembly_leaks==0},
        'constituent_reuse_diagnostics':{'distinct_material_fingerprints':len(material_folds),
            'material_fingerprints_reused_across_folds':sum(len(v)>1 for v in material_folds.values()),
            'distinct_role_construction_fingerprints':len(construction_folds),
            'role_constructions_reused_across_folds':sum(len(v)>1 for v in construction_folds.values()),
            'unseen_individual_material_or_construction_claim_allowed':False},
        'dependence':{'source_groups_single_province':sum(len(p)==1 for p in source_provinces.values()),
                      'source_groups_multi_province':sum(len(p)>1 for p in source_provinces.values()),
                      'EPW_context_province_sets':[sorted(climate_provinces[c]) for c in climates]},
        'claim_scope':{
            'prototype_holdout':'unseen content source and complete selected catalog assembly closure under the same generator/writer; constituent materials/constructions may recur and regional differences may be confounded',
            'climate_holdout':'unseen EPW/regional context together, not an isolated causal climate effect',
            'survey_source_household_holdout':'not established; anonymous aggregate pools shared across synthetic folds',
            'human_actor_or_scenario_holdout':'pending actual identities and final recorded exposure assignments'},
        'assignments_used_admission_runtime_or_answers':False,
        'collection_release':False,'training_release':False}
    args.output.write_text(json.dumps(payload,ensure_ascii=False,indent=2)+'\n')
    print(json.dumps({'counts':payload['counts'],'verification':payload['verification']}))


if __name__=='__main__':main()
