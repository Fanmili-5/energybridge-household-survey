#!/usr/bin/env python3
"""Targeted independent regression fixtures for reviewed household-to-IDF fixes.

Run: python3 verify_regressions.py --run-dir final_v5
The test invokes current admission/QA APIs and mutates already generated shell
artifacts. Strict JSON cases run with runtime=False in temporary directories.
No EnergyPlus simulation or CHFS microdata read is performed.
"""
import argparse
import contextlib
import copy
import hashlib
import importlib.util
import io
import json
import pathlib
import sys
import tempfile

HERE=pathlib.Path(__file__).resolve().parent

def sha(path):return hashlib.sha256(pathlib.Path(path).read_bytes()).hexdigest()
def parse(text):
    text='\n'.join(line.split('!',1)[0] for line in text.splitlines())
    return [[v.strip() for v in obj.split(',')] for obj in text.split(';') if obj.strip()]
def dump(rows):return '\n\n'.join(',\n  '.join(row)+';' for row in rows)+'\n'
def serializable(value):
    return json.loads(json.dumps(value,ensure_ascii=False,allow_nan=False))

def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--run-dir',type=pathlib.Path,default=HERE/'final_v5')
    ap.add_argument('--source-dir',type=pathlib.Path,default=HERE)
    args=ap.parse_args();run_dir=args.run_dir.resolve();source_dir=args.source_dir.resolve()
    sys.path.insert(0,str(source_dir))
    import household_model as hm
    import idf_builder as ib
    import run_stage as rs
    checks=[]
    def check(name,fn):
        try:
            passed,detail=fn()
            checks.append({'check_id':name,'passed':bool(passed),'detail':serializable(detail)})
        except Exception as exc:
            checks.append({'check_id':name,'passed':False,'raised':type(exc).__name__,'detail':str(exc)})
    def rejection(item,expected):
        errors=hm.input_errors(item)
        return expected in errors,{'errors':errors,'expected_reason':expected}
    def layout_rejection(item,layout,expected):
        errors=hm.layout_checks(item,layout)
        return expected in errors,{'errors':errors,'expected_reason':expected}
    def idf_rejection(rows,layout,prefix,boolean=False):
        actual=ib.idf_checks(dump(rows),layout)
        ok=any(e.startswith(prefix) for e in actual['errors'])
        if boolean:ok=ok and actual['no_inherited_occupancy_devices_or_multipliers'] is False
        return ok,{'errors':actual['errors'],'expected_reason_prefix':prefix,
                   'no_inherited_occupancy_devices_or_multipliers':actual['no_inherited_occupancy_devices_or_multipliers']}
    cases=[]
    for status_path in sorted((run_dir/'cases').glob('*/STATUS.json')):
        status=json.loads(status_path.read_text())
        if status['status']=='idf_ready':
            folder=status_path.parent
            cases.append((folder,json.loads((folder/'INPUT.json').read_text()),json.loads((folder/'LAYOUT.json').read_text())))
    def positive_inputs():
        bad={p.name:hm.input_errors(item) for p,item,_ in cases if hm.input_errors(item)}
        return len(cases)==13 and not bad,{'admitted_case_count':len(cases),'rejected_admitted_cases':bad}
    def positive_layouts():
        bad={p.name:hm.layout_checks(item,layout) for p,item,layout in cases if hm.layout_checks(item,layout)}
        return len(cases)==13 and not bad,{'admitted_case_count':len(cases),'layout_failures':bad}
    check('final_positive_inputs',positive_inputs)
    check('final_positive_layouts',positive_layouts)
    folder,item,layout=next(x for x in cases if x[0].name=='design_n3_g2_h72')
    single=next(x[1] for x in cases if x[0].name=='design_n1_g1_h71')
    for label,path,value,expected in [
        ('boolean_storeys','housing.household_storeys',True,'household_multistorey_unsupported'),
        ('missing_H5_evidence','housing.H5_evidence',None,'H5_evidence_missing'),
        ('blank_H5_evidence','housing.H5_evidence','  ','H5_evidence_missing'),
        ('numeric_H5_evidence','housing.H5_evidence',1,'H5_evidence_missing'),
        ('boolean_net_ratio','model_policy.gross_to_zone_floor_ratio',True,'net_ratio_missing_or_invalid'),
        ('mixed_sleep_identifier','housing.sleep_groups',[[1],['m02','m03']],'sleep_group_format_invalid'),
        ('nonhashable_member','family.resident_member_ids',[{'id':'m01'}],'sleep_group_format_invalid'),
        ('unsafe_case_id','case_id','../escape','case_id_missing_or_unsafe'),
        ('missing_case_id','case_id',None,'case_id_missing_or_unsafe')]:
        bad=copy.deepcopy(item);obj=bad;parts=path.split('.')
        for key in parts[:-1]:obj=obj[key]
        obj[parts[-1]]=value
        check('input_'+label,lambda bad=bad,expected=expected:rejection(bad,expected))
    bad=copy.deepcopy(single);bad['family']['resident_count']=True
    check('input_boolean_resident_count',lambda:rejection(bad,'resident_count_roster_mismatch'))
    bad_ground=copy.deepcopy(item);bad_ground['model_policy'].update(floor_position='ground',ground_temperature_method='explicit_research_boundary',ground_monthly_temperatures_C=[None]*12)
    check('input_null_ground_temperature',lambda:rejection(bad_ground,'ground_boundary_unresolved'))
    # Exercise the actual strict-file admission layer, including exponent
    # overflow that json.parse_constant alone cannot catch.
    def strict_admission(raw,reason):
        with tempfile.TemporaryDirectory(prefix='idf-regression-admission-',dir='/private/tmp') as task_tmp:
            task=pathlib.Path(task_tmp);source=task/'input.json';source.write_text(raw);out=task/'out'
            with contextlib.redirect_stdout(io.StringIO()):
                rs.main(argparse.Namespace(inputs=source,output=out,runtime=False))
            artifact=out/'ADMISSION_FAILURE.json'
            data=json.loads(artifact.read_text()) if artifact.exists() else None
            idfs=list(out.rglob('*.idf'))
            ok=data is not None and data.get('status')=='blocked' and data.get('IDFs_written')==0 and not idfs and any(e.startswith(reason) for e in data.get('errors',[]))
            return ok,{'expected_reason_prefix':reason,'raw_input':raw,'raw_input_sha256':sha(source),'ADMISSION_FAILURE':data,'IDF_count':len(idfs),'EnergyPlus_requested':False}
    finite_json=json.dumps([single],ensure_ascii=False,separators=(',',':'))
    raw_cases={
        'nan_constant':finite_json.replace('"H6_building_area_m2":50','"H6_building_area_m2":NaN'),
        'infinity_constant':finite_json.replace('"H6_building_area_m2":50','"H6_building_area_m2":Infinity'),
        'negative_infinity_constant':finite_json.replace('"H6_building_area_m2":50','"H6_building_area_m2":-Infinity'),
        'exponent_overflow':finite_json.replace('"H6_building_area_m2":50','"H6_building_area_m2":1e999'),
        'negative_exponent_overflow':finite_json.replace('"H6_building_area_m2":50','"H6_building_area_m2":-1e999'),
        'unused_nested_overflow':'[{"unused_metadata":{"nested":[1e999]},'+finite_json[2:],
        'top_level_scalar':'"household"','top_level_null':'null','top_level_object_without_inputs':'{}',
        'array_of_nonobjects':'[1,2]','empty_array':'[]','missing_case_id':'[{"housing":{}}]',
        'duplicate_case_ids':json.dumps([single,single],ensure_ascii=False),
        'invalid_json_syntax':'{"inputs":['}
    for label,raw in raw_cases.items():
        if label.endswith('constant'):reason='nonfinite_JSON_constant:'
        elif label.endswith('overflow'):reason='nonfinite_JSON_number_after_parse'
        elif label=='missing_case_id':reason='all_case_ids_must_be_strings'
        elif label=='duplicate_case_ids':reason='duplicate_case_ids'
        elif label=='invalid_json_syntax':reason='Expecting'
        else:reason='inputs_must_be_nonempty_array_of_objects'
        check('strict_JSON_'+label,lambda raw=raw,reason=reason:strict_admission(raw,reason))
    # Tamper a layout after generation while preserving total room geometry.
    bad=copy.deepcopy(layout);natural=next(s for s in bad['spaces'] if len(s.get('bed_footprints',[]))>=2)
    natural['bed_footprints'].append(copy.deepcopy(natural['bed_footprints'][0]))
    check('layout_duplicate_bed_member',lambda:layout_rejection(item,bad,'bed_members_not_exact_resident_partition'))
    overlap=copy.deepcopy(layout);natural=next(s for s in overlap['spaces'] if len(s.get('bed_footprints',[]))>=2)
    natural['bed_footprints'][1]['rect_m']=natural['bed_footprints'][0]['rect_m'].copy()
    check('layout_distinct_members_overlapping_beds',lambda:layout_rejection(item,overlap,'overlapping_beds'))
    missing=copy.deepcopy(layout);next(s for s in missing['spaces'] if s.get('bed_footprints'))['bed_footprints'].pop()
    check('layout_missing_resident_bed',lambda:layout_rejection(item,missing,'bed_members_not_exact_resident_partition'))
    room_mismatch=copy.deepcopy(layout);next(s for s in room_mismatch['spaces'] if s.get('bed_footprints'))['member_ids_sleeping']=[]
    check('layout_room_bed_member_mismatch',lambda:layout_rejection(item,room_mismatch,'room_bed_members_mismatch'))
    disconnected=copy.deepcopy(layout);disconnected['doors']=[d for d in disconnected['doors'] if d['to']!='natural_1']
    check('layout_disconnected_natural_room',lambda:layout_rejection(item,disconnected,'space_not_connected_to_entry'))
    missing_entry=copy.deepcopy(layout);missing_entry['doors']=[d for d in missing_entry['doors'] if d['from']!='entry']
    check('layout_missing_entry',lambda:layout_rejection(item,missing_entry,'space_not_connected_to_entry'))
    ghost=copy.deepcopy(layout);ghost['doors'].append({'from':'entry','to':'unknown_space','edge':'x=0','span_m':[2.1,2.9]})
    check('layout_unknown_door_space',lambda:layout_rejection(item,ghost,'door_connects_unknown_space'))
    # Mutate actual text artifacts, not a regenerated mirror of the writer.
    original_rows=parse((folder/'building.idf').read_text())
    rr=copy.deepcopy(original_rows);next(r for r in rr if r[0].lower()=='zone')[7]='3'
    check('IDF_multiplier_rejection_and_boolean',lambda:idf_rejection(rr,layout,'zone_multiplier_not1:',boolean=True))
    missing_con=copy.deepcopy(original_rows);next(r for r in missing_con if r[0].lower()=='fenestrationsurface:detailed')[3]='NoSuchConstruction'
    check('IDF_missing_construction',lambda:idf_rejection(missing_con,layout,'surface_construction_missing:'))
    door_mismatch=copy.deepcopy(original_rows);door=next(r for r in door_mismatch if r[0].lower()=='fenestrationsurface:detailed' and r[2]=='Door' and r[5]);mate=next(r for r in door_mismatch if r[1]==door[5]);mate[10]=str(float(mate[10])-.1)
    check('IDF_door_vertex_mismatch',lambda:idf_rejection(door_mismatch,layout,'door_pair_vertex_mismatch:'))
    missing_wall=copy.deepcopy(original_rows);missing_wall.remove(next(r for r in missing_wall if r[0].lower()=='buildingsurface:detailed' and r[1].startswith('corridor_Wall_west')))
    check('IDF_missing_exterior_boundary_face',lambda:idf_rejection(missing_wall,layout,'zone_surface_not_closed:'))
    bad_normals=copy.deepcopy(original_rows);target=next(r for r in bad_normals if r[0].lower()=='buildingsurface:detailed' and r[6]=='Surface');points=[target[i:i+3] for i in range(12,len(target),3)];target[12:]=[v for p in reversed(points) for v in p]
    check('IDF_same_direction_interzone_normals',lambda:idf_rejection(bad_normals,layout,'paired_face_normals_not_opposite:'))
    wrong_coordinate=copy.deepcopy(original_rows);next(r for r in wrong_coordinate if r[0].lower()=='globalgeometryrules')[3]='World'
    check('IDF_world_geometry_disables_building_axis',lambda:idf_rejection(wrong_coordinate,layout,'building_orientation_not_applied'))
    duplicated_face=copy.deepcopy(original_rows);duplicated_face.append(copy.deepcopy(next(r for r in duplicated_face if r[0].lower()=='buildingsurface:detailed')))
    check('IDF_duplicate_geometry_name',lambda:idf_rejection(duplicated_face,layout,'duplicate_geometry_object_name'))
    def lineage():
        errors=[];checked=0
        required_by_type={'building':{'orientation','solver_settings'},'globalgeometryrules':{'orientation','solver_settings'},'zone':{'rectangular_layout','source_height_m'},'buildingsurface:detailed':{'rectangular_layout','source_height_m','boundaries','thermal_assemblies'},'zoneinfiltration:designflowrate':{'air_exchange_ach'},'site:location':{'weather_binding'},'timestep':{'solver_settings'},'runperiod':{'solver_settings'}}
        for path,inp,lay in cases:
            object_rows=parse((path/'building.idf').read_text());index=json.loads((path/'IDF_OBJECT_LINEAGE.json').read_text());decisions={d['decision_id']:d for d in json.loads((path/'DECISION_TRACE.json').read_text())['decisions']}
            if len(object_rows)!=len(index):errors.append(path.name+':object_index_count_mismatch');continue
            for position,(row,entry) in enumerate(zip(object_rows,index)):
                checked+=1;ids=set(entry['source_decision_ids']);typ=row[0].lower()
                if entry['object_index']!=position or entry['type']!=row[0] or entry['name']!=row[1]:errors.append(path.name+':index_row_identity')
                if not ids<=set(decisions):errors.append(path.name+':dangling_decision_reference')
                required=required_by_type.get(typ,set())
                if typ=='fenestrationsurface:detailed':required={'rectangular_layout','source_height_m','door_panel_design' if row[2]=='Door' else 'thermal_assemblies'}
                if row[1] in ['Declared_Interior_Door','Declared_Door']:required={'door_panel_design'}
                if not required<=ids:errors.append(path.name+':lineage_missing:'+row[1])
            if decisions['orientation']['value']!=inp['model_policy']['north_axis_deg']:errors.append(path.name+':orientation_value_mismatch')
            if 'zone_floor_area' not in decisions['rectangular_layout']['input_paths']:errors.append(path.name+':area_decision_unreachable')
        return not errors,{'case_count':len(cases),'object_rows_checked':checked,'errors':errors}
    check('field_object_lineage_closure',lineage)
    def entry_binding():
        errors=[];counts={}
        for path,inp,lay in cases:
            rr=parse((path/'building.idf').read_text());walls={r[1]:r for r in rr if r[0].lower()=='buildingsurface:detailed'};entries=[d for d in lay['doors'] if d['from']=='entry'];doors=[r for r in rr if r[0].lower()=='fenestrationsurface:detailed' and r[2]=='Door' and r[1].endswith('_entry')]
            if len(entries)!=1:errors.append(path.name+':logical_entry_count');continue
            outside=inp['model_policy']['wall_boundaries']['west']=='Outdoors'
            if outside:
                if entries[0]['thermal_status']!='explicit_exterior_door' or len(doors)!=1:errors.append(path.name+':outdoor_entry_not_explicit')
                for d in doors:
                    host=walls[d[4]]
                    if host[6]!='Outdoors' or host[4]!='corridor' or d[5]:errors.append(path.name+':outdoor_entry_wrong_host')
                    pts=[tuple(map(float,d[i:i+3])) for i in range(10,len(d),3)]
                    if any(abs(p[0])>1e-6 for p in pts) or abs(min(p[1] for p in pts)-2.1)>1e-6 or abs(max(p[1] for p in pts)-2.9)>1e-6:errors.append(path.name+':outdoor_entry_geometry')
            elif entries[0]['thermal_status']!='adjacent_conditioned_common_corridor_proxy_not_explicit_external_aperture' or doors:errors.append(path.name+':adiabatic_entry_scope')
            counts[path.name]={'outdoor_entry':outside,'IDF_exterior_door_count':len(doors)}
        return not errors,{'cases':counts,'errors':errors}
    check('all_four_faces_entry_vs_adiabatic_entry',entry_binding)
    sources={p.name:sha(p) for p in [source_dir/'household_model.py',source_dir/'idf_builder.py',source_dir/'run_stage.py',source_dir/'weather_rules.py']}
    snapshot={p.name:sha(p) for p in (run_dir/'code').glob('*.py') if p.name in sources}
    physical_match=all(sources[name]==snapshot.get(name) for name in sources)
    check('all_main_code_matches_final_runtime_snapshot',lambda:(physical_match,{'compared':sorted(sources),'runner_mismatch_allowed':False}))
    def experiment_identity():
        expected=hm.BATCH+'__'+run_dir.name;errors=[];artifact_count=0
        paths=[run_dir/'SUMMARY.json',run_dir/'INPUT_LOCK.json',run_dir/'MANIFEST.json',*(run_dir/'cases').glob('*/STATUS.json'),*(run_dir/'runtime').glob('*/RUNTIME_CHECK.json')]
        for path in paths:
            artifact_count+=1
            if json.loads(path.read_text()).get('experiment_id')!=expected:errors.append(str(path.relative_to(run_dir)))
        return not errors,{'expected_experiment_id':expected,'artifact_count':artifact_count,'mismatched_artifacts':errors}
    check('experiment_id_consistency',experiment_identity)
    result={'scope':'targeted fixes and corrupted-input/artifact refusals; no EnergyPlus or survey microdata','status':'pass' if all(c['passed'] for c in checks) else 'fail','check_count':len(checks),'passed_check_count':sum(c['passed'] for c in checks),'failed_check_ids':[c['check_id'] for c in checks if not c['passed']],'checked_source_directory':str(source_dir),'current_code_sha256':sources,'runtime_code_snapshot_sha256':snapshot,'runner_diff_scope':'none; all four main modules must match final runtime snapshot','checker_sha256':sha(__file__),'microdata_read':False,'EnergyPlus_requested':False,'checks':checks}
    (run_dir/'REGRESSION_CHECK.json').write_text(json.dumps(result,ensure_ascii=False,indent=2,allow_nan=False)+'\n')
    print(json.dumps({k:result[k] for k in ['status','check_count','passed_check_count','failed_check_ids']},ensure_ascii=False))
    return 0 if result['status']=='pass' else 1

if __name__=='__main__':raise SystemExit(main())
