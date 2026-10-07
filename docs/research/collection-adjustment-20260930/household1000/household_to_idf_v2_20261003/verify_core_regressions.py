#!/usr/bin/env python3
"""Reproduce v2 admission/geometry counterexamples without EnergyPlus or dta.

Use a new --output directory. Mutations are injected after the actual writer;
they exercise build_one's mandatory gate, not a separate prospective check.
Source profiles and frozen v1 artifacts are read only.
"""
import argparse,copy,hashlib,json,os,subprocess,sys
from pathlib import Path
import household_model as hm
import run_stage as rs
import geometry_gate as gate
import verify_geometry_independent as independent

def load(path):return json.loads(path.read_text())
def write(path,obj):hm.save(path,obj)
def dumps_rows(rr):return '\n\n'.join(',\n  '.join(r)+';' for r in rr)+'\n'
def put_vertices(row,points):
    start=12 if row[0].lower()=='buildingsurface:detailed' else 10
    row[start-1]=str(len(points));row[start:]=[format(v,'.15g') for p in points for v in p]

def mutate(body,mode):
    rr=gate.rows(body);surface=next(r for r in rr if r[0].lower()=='buildingsurface:detailed' and r[1]=='corridor_Wall_west_exterior_0')
    detail={'mutation':mode,'moved_surface_name':surface[1],'source_vertices':gate.vertices(surface)}
    if mode=='translated_wall':
        put_vertices(surface,[(x,y+.25,z) for x,y,z in gate.vertices(surface)]);detail['after_vertices']=gate.vertices(surface)
    elif mode=='missing_wall':rr.remove(surface)
    elif mode in ['collinear_outer','split_outer']:
        p=gate.vertices(surface);mid=lambda a,b:tuple((x+y)/2 for x,y in zip(a,b))
        if mode=='collinear_outer':put_vertices(surface,[p[0],mid(p[0],p[1]),*p[1:]])
        else:
            q=copy.deepcopy(surface);q[1]+='_legal_split';a,b=mid(p[0],p[1]),mid(p[3],p[2])
            put_vertices(surface,[p[0],a,b,p[3]]);put_vertices(q,[a,p[1],p[2],b]);rr.insert(rr.index(surface)+1,q)
    elif mode=='collinear_paired':
        surface=next(r for r in rr if r[0].lower()=='buildingsurface:detailed' and r[6].lower()=='surface')
        p=gate.vertices(surface);put_vertices(surface,[p[0],tuple((x+y)/2 for x,y in zip(p[0],p[1])),*p[1:]])
        detail.update(moved_surface_name=surface[1],source_vertices=p,after_vertices=gate.vertices(surface))
    else:
        opening=next(r for r in rr if r[0].lower()=='fenestrationsurface:detailed' and (r[2].lower()=='door' if mode=='broken_door_mate' else r[2].lower()=='window'))
        detail.update(opening_name=opening[1],opening_host=opening[4],opening_vertices=gate.vertices(opening))
        if mode=='missing_opening_host':opening[4]='nonexistent_host'
        elif mode=='offplane_opening':
            host=next(r for r in rr if r[0].lower()=='buildingsurface:detailed' and r[1]==opening[4]);hp=gate.vertices(host)
            axis=next(a for a in range(3) if max(p[a] for p in hp)-min(p[a] for p in hp)<1e-8)
            put_vertices(opening,[tuple(v+(.25 if a==axis else 0) for a,v in enumerate(p)) for p in gate.vertices(opening)])
        elif mode=='reversed_opening':put_vertices(opening,list(reversed(gate.vertices(opening))))
        elif mode=='broken_door_mate':opening[5]='nonexistent_door_mate'
        else:raise ValueError(mode)
        detail['after_opening_vertices']=gate.vertices(opening)
    return dumps_rows(rr),detail

def main(output):
    output=output.resolve()
    if output.exists():raise ValueError('use new immutable output directory')
    output.mkdir(parents=True);checks=[];details={}
    def check(name,ok,detail=None):
        checks.append({'check':name,'pass':bool(ok)})
        if detail is not None:details[name]=detail
        print(json.dumps(checks[-1]),flush=True)
    inputs=rs.example_inputs();base=copy.deepcopy(next(x for x in inputs if x['case_id']=='design_n3_g2_h72'))
    original_writer=rs.build_idf
    for mode,expected in [('normal','idf_ready'),('translated_wall','blocked'),('missing_wall','blocked'),
            ('missing_opening_host','blocked'),('offplane_opening','blocked'),('reversed_opening','blocked'),
            ('broken_door_mate','blocked'),('collinear_outer','idf_ready'),('collinear_paired','idf_ready'),('split_outer','idf_ready')]:
        item=copy.deepcopy(base);item['case_id']='gate_'+mode;mutation={}
        def writer(*args,**kwargs):
            body,ledger,index=original_writer(*args,**kwargs)
            mutation['writer_idf_sha256']=hashlib.sha256(body.encode()).hexdigest()
            if mode!='normal':body,change=mutate(body,mode);mutation.update(change)
            mutation['candidate_idf_sha256']=hashlib.sha256(body.encode()).hexdigest()
            return body,ledger,index
        rs.build_idf=writer
        try:record=rs.build_one(item,output/'geometry_pipeline',{})
        finally:rs.build_idf=original_writer
        folder=output/'geometry_pipeline/cases'/item['case_id'];proof=load(folder/'INDEPENDENT_GEOMETRY_CHECK.json')
        check('pipeline_'+mode,record['status']==expected and proof['status']==('pass' if expected=='idf_ready' else 'fail')
            and (folder/'building.idf').exists()==(expected=='idf_ready')
            and (expected=='idf_ready' or (folder/'candidate_rejected.idf').exists()),
            {'status':record['status'],'errors':record['errors'],'independent_result':proof,'mutation':mutation,
             'legacy_static_result':load(folder/'IDF_STATIC_CHECK.json')})
    readback=independent.check_sources(output/'geometry_pipeline')
    check('source_readback_skips_rejected_candidates',readback['status']=='pass' and readback['case_count']==4,readback)
    geom=independent.check_geometry(output/'geometry_pipeline')
    check('ready_geometry_readback_4_cases',geom['status']=='pass' and geom['case_count']==4,geom)

    for name,total,position,number,expected in [
        ('middle_2',2,'middle',None,False),('middle_3',3,'middle',2,True),
        ('top_2',2,'top',2,True),('top_1',1,'top',1,False),('middle_is_top',3,'middle',3,False),
        ('top_number_mismatch',3,'top',2,False),('floor_boolean',3,'middle',True,False),
        ('total_boolean',True,'middle',None,False),('number_above_total',3,'top',4,False)]:
        x=copy.deepcopy(base);x['housing']['building_total_storeys_design']=total;x['model_policy']['floor_position']=position
        if number is not None:x['model_policy']['floor_number_design']=number
        errors=hm.input_errors(x);check('floor_'+name,(not errors)==expected,errors)
    for name,section,key,value in [('huge_used','housing','H6_building_area_m2',10**400),
            ('huge_unused','extra','unused_number',10**400),('nonfinite_direct','extra','unused_number',float('nan'))]:
        x=copy.deepcopy(base);x.setdefault(section,{})[key]=value
        errors=hm.input_errors(x);check('direct_numeric_'+name,any(e.startswith('number_not_finite_binary64:') for e in errors),errors)

    valid_text=json.dumps([base],ensure_ascii=False)
    invalid_inputs={
        'huge_integer':json.dumps([base,{**copy.deepcopy(base),'case_id':'huge','unused':10**400}]),
        'nan_constant':valid_text.replace('"expected_result": "idf_ready"','"expected_result": "idf_ready", "unused": NaN'),
        'overflow_exponent':valid_text.replace('"expected_result": "idf_ready"','"expected_result": "idf_ready", "unused": 1e999'),
        'top_null':'null','top_array_scalar':'[1]', 'duplicate_ids':json.dumps([base,base])}
    env={**os.environ,'PYTHONDONTWRITEBYTECODE':'1'}
    for name,text in invalid_inputs.items():
        path=output/(name+'.input.json');path.write_text(text)
        out=output/('batch_'+name)
        proc=subprocess.run([sys.executable,str(hm.HERE/'run_stage.py'),'--inputs',str(path),'--output',str(out)],capture_output=True,text=True,env=env)
        failure=load(out/'ADMISSION_FAILURE.json') if (out/'ADMISSION_FAILURE.json').exists() else None
        check('batch_atomic_'+name,proc.returncode==0 and failure is not None and failure['IDFs_written']==0
            and failure['source_input_sha256']==hm.sha(path) and not list(out.glob('cases/*/building.idf'))
            and not list(out.glob('cases/*/STATUS.json')),{'failure':failure,'stderr':proc.stderr})

    new_missing=copy.deepcopy(base);new_missing.pop('prototype_request');new_missing['case_id']='new_missing_request'
    request,origin,errors=rs.prototype_request_for(new_missing,rs.current_prototype_registry())
    check('new_input_no_legacy_key_bypass',request is None and errors==['prototype_request_required_for_new_input'],errors)
    target_mismatch=copy.deepcopy(base);target_mismatch['prototype_request']['target']['city']='上海'
    errors=rs.prototype_target_site_errors(target_mismatch['prototype_request'],target_mismatch,rs.current_prototype_registry())
    check('prototype_site_mismatch', 'prototype_target_site_city_mismatch' in errors,errors)
    year_mismatch=copy.deepcopy(base);year_mismatch['housing']['building_year_design']=2001
    errors=rs.prototype_target_site_errors(year_mismatch['prototype_request'],year_mismatch,rs.current_prototype_registry())
    check('prototype_generated_year_mismatch','prototype_target_housing_construction_year_mismatch' in errors,errors)

    source=hm.HERE.parent/'generation_model_20261003/final_v2/FAMILY_HOUSING_CANDIDATES.json'
    profile_obj=load(source);ordinary=next(p for p in profile_obj['profiles'] if p['housing']['H5_status']=='ordinary_declared_or_matched')
    nonordinary=next(p for p in profile_obj['profiles'] if p['housing']['H5_status']!='ordinary_declared_or_matched')
    def generated(profile,path=source):
        x=copy.deepcopy(base);x['case_id']='generated_'+profile['slot_id'];x['expected_result']=None
        x['family']=copy.deepcopy(profile['family']);x['housing']=copy.deepcopy(profile['housing'])
        x['generation_binding']={'profile_file_path':str(path),'profile_file_sha256':hm.sha(path),'slot_id':profile['slot_id'],
            'family_semantic_sha256':hm.digest(x['family']),'housing_semantic_sha256':hm.digest(x['housing'])}
        return x
    item=generated(ordinary);binding=hm.verify_generation_binding(item)
    check('final_profile_binding_preserves_full_semantics',binding['status']=='pass' and item['family']==ordinary['family'] and item['housing']==ordinary['housing'],binding)
    x=copy.deepcopy(item);x['family']['reference_date']='tampered'
    check('full_family_unknown_field_tamper_rejected',hm.verify_generation_binding(x)['status']=='blocked')
    x=copy.deepcopy(item);x['housing']['H6_building_area_m2']+=1
    check('full_housing_tamper_rejected',hm.verify_generation_binding(x)['status']=='blocked')
    rejected=generated(nonordinary);record=rs.build_one(rejected,output/'generation_rejection',{})
    gfile=output/'generation_rejection/cases'/rejected['case_id']/'GENERATION_BINDING_CHECK.json'
    check('unsupported_profile_still_has_verified_generation_ledger',record['status']=='blocked' and gfile.exists() and load(gfile)['status']=='pass'
        and record['generation_binding_status']=='pass' and 'H5_not_ordinary_or_unresolved' in record['errors'],record)
    rs.audit_slots(output/'generation_rejection',[record]);slot_audit=load(output/'generation_rejection/TARGET1000_PREREQUISITE_AUDIT.json')
    check('slot_audit_separates_generated_from_actual_home',slot_audit['generated_family_housing_verified_slots']==1 and slot_audit['actual_IDF_slots']==0
        and slot_audit['conditional_context_IDF_cases']==0,{'generated_slots':slot_audit['generated_family_housing_verified_slots'],'actual_IDF_slots':slot_audit['actual_IDF_slots']})

    # Cache mutation fixture must stay inside repo; no actual generated profile
    # or frozen artifacts are edited. Read + SHA happens on every call.
    if output.is_relative_to(hm.REPO):
        cache_file=output/'synthetic_cache_profile.json';synthetic=copy.deepcopy(ordinary);synthetic['slot_id']='synthetic-cache-slot'
        write(cache_file,{'profiles':[synthetic]});cached=generated(synthetic,cache_file)
        check('cache_initial_valid',hm.verify_generation_binding(cached)['status']=='pass')
        cache_file.write_text(cache_file.read_text()+' ')
        check('cache_actual_byte_hash_change_rejected',hm.verify_generation_binding(cached)['errors']==['generation_profile_file_hash_mismatch'])
        obj=load(cache_file);obj['profiles'][0]['family']['reference_date']='changed after caching';write(cache_file,obj)
        cached['generation_binding']['profile_file_sha256']=hm.sha(cache_file)
        check('cache_updated_hash_reparses_new_semantics','generation_family_semantic_hash_mismatch' in hm.verify_generation_binding(cached)['errors'])
    else:check('cache_fixture_inside_repo_required',False)

    semantic=copy.deepcopy(base);semantic['case_id']='semantic_rejected';semantic['housing']['H5_status']='unknown';semantic['expected_result']='blocked'
    unprespecified=copy.deepcopy(base);unprespecified['case_id']='unprespecified_candidate';unprespecified['expected_result']=None
    path=output/'case_policy.input.json';write(path,[base,semantic,unprespecified]);out=output/'case_policy_batch'
    proc=subprocess.run([sys.executable,str(hm.HERE/'run_stage.py'),'--inputs',str(path),'--output',str(out)],capture_output=True,text=True,env=env)
    summary=load(out/'SUMMARY.json') if (out/'SUMMARY.json').exists() else {}
    check('semantic_refusal_continues_other_cases',proc.returncode==0 and summary.get('IDF_ready')==2 and summary.get('blocked')==1,summary)
    check('unprespecified_candidate_not_counted_as_expected_control',summary.get('expected_controls_count')==2 and summary.get('unprespecified_candidate_count')==1
        and summary.get('expected_status_all_matched') is True)
    old=hm.HERE.parent/'household_to_idf_20261003';manifest=load(old/'PACKAGE_MANIFEST.json')
    missing=[p for p,s in manifest['files'].items() if not (old/p).is_file() or hm.sha(old/p)!=s]
    check('frozen_v1_package_unchanged',not missing,{'manifest_sha256':hm.sha(old/'PACKAGE_MANIFEST.json'),'file_count':len(manifest['files']),'mismatches':missing})
    result={'schema':'eb.core_admission_regression.v2','experiment_id':hm.BATCH+'__'+output.name,'pass':all(x['pass'] for x in checks),
        'check_count':len(checks),'failed':[x for x in checks if not x['pass']],'checks':checks,'details':details,
        'code_sha256':{p.name:hm.sha(p) for p in hm.HERE.glob('*.py')},'prototype_registry_sha256':hm.sha(hm.HERE/'PROTOTYPE_REGISTRY.json'),
        'weather_registry_sha256':hm.sha(hm.HERE/'WEATHER_CATALOG.json'),'frozen_generated_profile_sha256':hm.sha(source),
        'scope':'actual mandatory-gate mutation, batch/case refusals, profile and floor/prototype binding; no E+ rerun, dta read, physical calibration or population representativeness validation'}
    write(output/'REGRESSION_CHECK.json',result);print(json.dumps({k:result[k] for k in ['pass','check_count','failed']}))
    return 0 if result['pass'] else 1

if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--output',type=Path,required=True)
    raise SystemExit(main(parser.parse_args().output))
