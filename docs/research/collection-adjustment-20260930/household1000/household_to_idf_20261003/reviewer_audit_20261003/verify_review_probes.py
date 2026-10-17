#!/usr/bin/env python3
"""New reviewer probes; writes only a caller-selected tmp directory/report.

No EnergyPlus run, microdata read, mutation of implementation or final_v5.
Example: PYTHONDONTWRITEBYTECODE=1 python3 verify_review_probes.py \
  --report /private/tmp/new_review_probes.json
"""
import argparse,collections,contextlib,copy,hashlib,io,json,pathlib,shutil,sys,tempfile

ROOT=pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0,str(ROOT))
import household_model as hm
import idf_builder as ib
import run_stage as rs
import verify_geometry_independent as independent

def load(p):return json.loads(pathlib.Path(p).read_text())
def sha(p):return hashlib.sha256(pathlib.Path(p).read_bytes()).hexdigest()
def capture(fn):
    try:return {'returned':fn(),'raised':None}
    except Exception as exc:return {'raised':type(exc).__name__,'message':str(exc)}

def main(args):
    out=pathlib.Path(tempfile.mkdtemp(prefix='eb-physical-review-20261003-',dir='/private/tmp'))
    basefolder=ROOT/'final_v5/cases/design_n3_g2_h72'
    base=load(basefolder/'INPUT.json');lock=load(ROOT/'final_v5/INPUT_LOCK.json')
    catalog=load(lock['prototype_catalog_path'])['records'];byid={r['role_id']:r for r in catalog}
    w=load(basefolder/'WEATHER_MATCH.json')['selected']
    weather={'epw_path':w['epw_absolute_path'],'epw_sha256':w['epw_sha256'],'location':w['epw_location']}
    result={'schema':'eb.physical_reviewer.probes.v1','review_date_HKT':'2026-10-03',
            'reviewed_experiment_id':'HOUSEHOLD_TO_IDF_20261003_V1__final_v5',
            'temporary_output_root':str(out),'microdata_read':False,'simulations_run':False,
            'sealed_artifacts_modified':False,'implementation_modified':False,
            'reviewed_baseline_idf_path':str(basefolder/'building.idf'),
            'reviewed_baseline_idf_sha256':sha(basefolder/'building.idf'),
            'prior_package_manifest_sha256':sha(ROOT/'PACKAGE_MANIFEST.json'),
            'code_hashes':{p.name:sha(p) for p in [ROOT/'household_model.py',ROOT/'idf_builder.py',ROOT/'run_stage.py',ROOT/'verify_geometry_independent.py',ib.LEGACY_PATH]},
            'review_probe_script_sha256':sha(__file__),'probes':[]}
    huge=copy.deepcopy(base);huge['case_id']='review_integer_overflow';huge['housing']['H6_building_area_m2']=10**400
    inp=out/'huge_integer.json';inp.write_text(json.dumps([huge],allow_nan=False)+'\n')
    batch=out/'huge_integer_batch'
    def run_huge():
        with contextlib.redirect_stdout(io.StringIO()):
            rs.main(argparse.Namespace(inputs=inp,output=batch,runtime=False))
        return 'completed'
    result['probes'].append({'id':'huge_integer_refusal_path','numeric_input':'H6_building_area_m2 = 10**400 (401-digit valid JSON integer)',
       'classification':'P2 robustness / out-of-domain stop path, not population validity',
       'input_path':str(inp),'input_sha256':sha(inp),'output_root':str(batch),
       'direct_input_gate':capture(lambda:hm.input_errors(huge)),'file_loop':capture(run_huge),
       'ADMISSION_FAILURE_exists':(batch/'ADMISSION_FAILURE.json').exists(),
       'case_STATUS_exists':(batch/'cases/review_integer_overflow/STATUS.json').exists(),
       'SUMMARY_exists':(batch/'SUMMARY.json').exists()})
    body=(basefolder/'building.idf').read_text();layout=load(basefolder/'LAYOUT.json')
    rr=ib.parse_idf(body);name='corridor_Wall_west_exterior_0'
    target=next(r for r in rr if r[0].lower()=='buildingsurface:detailed' and r[1]==name)
    before=copy.deepcopy(target)
    for i in range(13,len(target),3):target[i]=str(float(target[i])+0.25)
    mutated=ib.dump(rr);tree=out/'open_shell_readback';case=tree/'cases'/'parallel_wall_shift'
    case.mkdir(parents=True);(case/'building.idf').write_text(mutated)
    for filename in ['LAYOUT.json','STATUS.json']:shutil.copy2(basefolder/filename,case/filename)
    static=ib.idf_checks(mutated,layout);readback=independent.check_geometry(tree)
    result['probes'].append({'id':'parallel_wall_shift_open_shell','classification':'P1 future general-geometry acceptance gate',
        'mutation':'Translate only the west Adiabatic corridor wall +0.25m in y. Leave all other faces and zone/layout metadata unchanged.',
        'face_name':name,'source_idf_path':str(basefolder/'building.idf'),'source_idf_sha256':sha(basefolder/'building.idf'),
        'mutated_idf_path':str(case/'building.idf'),'mutated_idf_sha256':sha(case/'building.idf'),
        'vertex_delta_m':[0,0.25,0],'before_row':before,'after_row':target,
        'writer_static_check':static,'independent_geometry':readback,
        'claim_scope':'New candidate negative control only. Does not bypass immutable manifest and does not invalidate the 13 independently verified final_v5 shapes.'})
    branches=collections.defaultdict(list)
    for record in catalog:branches[record['source_branch']].append(record)
    selected=[]
    for branch,recs in branches.items():
        unique={r['source_catalog_key']:r for r in recs};keys=sorted(unique);step=max(1,len(keys)//12)
        selected.extend(unique[k] for k in keys[::step][:12])
    sources=[]
    for record in selected:
        item=copy.deepcopy(base);item['case_id']='source_probe_'+record['role_id']
        item['model_policy']['prototype_key']=record['role_id']
        item['template_transport_evidence']='reviewer_declared_construction_swap_not_local_stock_match'
        def source_probe():
            trace=[];layout,errors=hm.make_layout(item,trace)
            if errors:return {'layout_errors':errors}
            body,binding,_=ib.build_idf(item,layout,record,weather,trace)
            rows=ib.parse_idf(body);cons={r[1]:r for r in rows if r[0].lower()=='construction'}
            layers=cons[binding['construction_map']['internal_wall']][2:]
            return {'input_errors':hm.input_errors(item),'layout_errors':hm.layout_checks(item,layout),
                    'static_errors':ib.idf_checks(body,layout)['errors'],'source_height_m':binding['source_height_m'],
                    'internal_wall_layers_symmetric':layers==layers[::-1],'construction_map':binding['construction_map'],
                    'idf_sha256':hashlib.sha256(body.encode()).hexdigest()}
        sources.append({'prototype':record['role_id'],'branch':record['source_branch'],'catalog_key':record['source_catalog_key'],
                       'source_sha256':record['source_idf_sha256'],'parent_sha256':record['parent_idf_sha256'],**capture(source_probe)})
    result['template_static_probes']={'scope':'24 explicit construction/height swaps into the same designed single-storey apartment. Static only; neither terraced geometry nor local stock matching nor annual generalization.',
                                    'results':sources,'pass_count':sum(r['raised'] is None and not r['returned'].get('input_errors') and not r['returned'].get('layout_errors') and not r['returned'].get('static_errors') for r in sources)}
    ground=[]
    for label,temp in [('declared_18C',18.0),('extreme_9999C',9999.0)]:
        item=copy.deepcopy(base);item['case_id']='ground_'+label
        item['model_policy'].update(floor_position='ground',ground_temperature_method='explicit_research_boundary',ground_monthly_temperatures_C=[temp]*12)
        layout,errs=hm.make_layout(item,[]);body,binding,_=ib.build_idf(item,layout,byid[item['model_policy']['prototype_key']],weather,[])
        ground.append({'id':label,'input_errors':hm.input_errors(item),'layout_errors':errs,'static_errors':ib.idf_checks(body,layout)['errors'],
                       'monthly_temperatures_C':[temp]*12,'annual_run_performed':False})
    result['ground_static_domain_probes']={'results':ground,'interpretation':'This IDD object has no stated min/max; 9999C is not alleged to violate an EnergyPlus field bound. The current finite-only gate does not certify a physically justified ground boundary.'}
    ready=[load(p) for p in (ROOT/'final_v5/cases').glob('*/STATUS.json') if load(p)['status']=='idf_ready']
    assemblies=[load(ROOT/'final_v5/cases'/r['case_id']/'ASSEMBLY_BINDING.json') for r in ready]
    result['dependence_inventory']={'accepted_cases':len(ready),'unique_prototypes':len({b['prototype_id'] for b in assemblies}),
       'unique_parent_hashes':len({b['parent_idf_sha256'] for b in assemblies}),'unique_selected_source_hashes':len({b['source_idf_sha256'] for b in assemblies}),
       'unique_assembly_hashes':len({b['material_rows_sha256'] for b in assemblies}),'unique_weather_hashes':len({r['weather_epw_sha256'] for r in ready}),
       'family_hash_counts':dict(collections.Counter(r['family_semantic_sha256'] for r in ready)),
       'housing_hash_counts':dict(collections.Counter(r['housing_semantic_sha256'] for r in ready)),
       'catalog_records':len(catalog),'catalog_unique_parent_hashes':len({r['parent_idf_sha256'] for r in catalog}),
       'catalog_unique_selected_source_hashes':len({r['source_idf_sha256'] for r in catalog}),
       'actual_train_test_split_or_leakage_demonstrated':False}
    record=byid[base['model_policy']['prototype_key']];source_rows=ib.parse_idf(pathlib.Path(record['parent_idf_path']).read_text())
    owned=set(record['household_owned_zones']);cons={r[1]:r for r in source_rows if r[0].lower()=='construction'}
    walls=[r for r in source_rows if r[0].lower()=='buildingsurface:detailed' and r[4] in owned and r[2].lower()=='wall' and r[6].lower()=='outdoors']
    counts=collections.Counter(r[3] for r in walls)
    result['selected_source_external_layers']={'source_path':record['parent_idf_path'],'source_sha256':record['parent_idf_sha256'],
       'owned_zones':sorted(owned),'outdoor_wall_construction_counts':dict(counts),
       'layer_order_by_construction':{name:cons[name][2:] for name in counts},
       'writer_selected_construction':assemblies[0]['construction_map']['external_wall'],
       'layer_direction_correctness_or_empirical_calibration_certified':False}
    manifest=load(ROOT/'PACKAGE_MANIFEST.json')
    mismatches=[name for name,expected in manifest['files'].items() if not (ROOT/name).exists() or sha(ROOT/name)!=expected]
    result['sealed_package_after_probe_hash_check']={'files_checked':len(manifest['files']),'mismatches':mismatches,
        'package_manifest_unchanged':sha(ROOT/'PACKAGE_MANIFEST.json')==result['prior_package_manifest_sha256']}
    args.report.parent.mkdir(parents=True,exist_ok=True)
    args.report.write_text(json.dumps(result,ensure_ascii=False,indent=2,allow_nan=False)+'\n')
    print(json.dumps({'report':str(args.report),'temporary_output_root':str(out),'huge_integer_exception':result['probes'][0]['file_loop'],
      'open_shell_static_errors':result['probes'][1]['writer_static_check']['errors'],'open_shell_independent_status':readback['status'],
      'template_static_pass':result['template_static_probes']['pass_count']},ensure_ascii=False,indent=2))

if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--report',type=pathlib.Path,required=True)
    main(parser.parse_args())
