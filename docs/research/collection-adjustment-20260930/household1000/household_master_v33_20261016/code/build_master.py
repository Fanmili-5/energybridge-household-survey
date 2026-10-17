"""Build all1000 household/housing/device worlds, then select a proportional50.

This phase never creates A/B, uses human answers, launches EP or changes live
collection. Missing resources or failed worlds are retained, not substituted.
"""
import argparse,collections,copy,datetime as dt,json,sys
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path
from common import *
sys.path[:0]=read(BASE/'idf_joint_production_20261005/RUNTIME.json')['stable_PYTHONPATH'].split(':')


def bundle_id():
    names=('build_master.py','common.py','backgrounds.py','housing_conditions.py','model_matching.py','native_bundle.py','room_assignment.py','sleep_packing.py',
           'geometry.py','housing.py','surface_merge.py','geometry_review.py','shared_context.py','electrical.py','ac_resources.py','activity_model.py','worlds.py','integrity.py')
    plan=read(OUT/'MODEL_PLAN1000.json')
    inputs=[{'household_id':r['household_id'],'world':r['source_world_sha256'],'model_key':r['selected']['model_key'],
             'native':r['selected']['source_sha256'],'facet':r['facet'],
             'weather':sorted(s['sha256']for s in r['selected']['coordinate_confirmed_WMO_station_candidates'])}for r in plan['records']]
    return digest({'code':{n:sha(OUT/'code'/n)for n in names},'area_design':sha(OUT/'AREA_REALLOCATION.json'),
                   'master_inputs':inputs,'dependencies':sha(OUT/'DEPENDENCY_LOCK.json'),'schema':sha(SCHEMA_PATH)})


def reference_partition(bundle):
    """A designed100mm internal partition, distinct from native outer walls.

    The reference layout is newly constructed, not the native source floorplan.
    Keep native layer k/rho/cp, proportionally set internal layer thicknesses to
    the declared partition thickness and compile those actual layers to IDF.
    """
    b=copy.deepcopy(bundle);before=b['interior_thickness_m'];ratio=.100/before
    construction=next(r for r in b['rows']if r[0]=='Construction'and r[1]==b['names']['interior'])
    names=set(construction[2:]);changes=[]
    for r in b['rows']:
        if r[0]=='Material'and r[1]in names:
            changes.append({'name':r[1],'native_thickness_m':float(r[3]),'reference_thickness_m':float(r[3])*ratio})
            r[3]=str(float(r[3])*ratio)
    b['interior_thickness_m']=.100
    b['constructed_internal_partition']={'thickness_m':.100,'source_thickness_m':before,
        'layer_changes':changes,'material_k_rho_cp_retained':True,'partition_is_native_or_measured_asbuilt':False,
        'reason':'declared non-load-bearing partition in newly constructed reference floorplan;not native structural interior-wall geometry'}
    return b


def extract_one(row):
    from native_bundle import extract
    key=row['model_key'];p=OUT/'native_bundles'/(key+'.json')
    if sha(row['source_path'])!=row['source_sha256']:raise ValueError('Native source changed:'+key)
    for weather in row['coordinate_confirmed_WMO_station_candidates']:
        if sha(weather['path'])!=weather['sha256']:raise ValueError('Weather source changed:'+key)
    signature=digest({'source':row['source_sha256'],'extractor':sha(OUT/'code/native_bundle.py')})
    if p.exists()and read(p).get('extraction_signature')==signature:return read(p)
    try:
        selected,bundle=extract(row)
        result={'model_key':key,'selected':selected,'bundle':bundle,'passed':True,'extraction_signature':signature}
    except Exception as e:result={'model_key':key,'passed':False,'error':str(e),'extraction_signature':signature}
    save(p,result);return result


def build_one(job):
    row,profile,templates,run_root,signature=job;root=Path(run_root);hid=row['household_id'];record_path=root/'records'/(hid+'.json')
    # Same rules and same source bytes resume deterministically. Changed rules
    # get a new run directory, retaining every prior attempt and failure.
    if record_path.exists():return read(record_path)
    try:
        from backgrounds import build,context_room_counts
        from housing_conditions import apply as configure_housing_conditions
        from housing import rebuild
        from worlds import refresh
        from shared_context import configure,dated_context
        from electrical import configure as electricity
        from geometry_review import review
        from integrity import verify_fixed_family
        old=read(row['source_world_path'])
        if sha(row['source_world_path'])!=row['source_world_sha256']:raise ValueError('SOURCE_WORLD_CHANGED')
        native=read(OUT/'native_bundles'/(row['selected']['model_key']+'.json'))
        if not native['passed']:raise ValueError('NATIVE_EXTRACTION:'+native['error'])
        selected=native['selected'];w=build(configure_housing_conditions(old),selected,row['matching']);p=copy.deepcopy(profile)
        allocation=read(OUT/'AREA_REALLOCATION.json')
        if hid in allocation['configured_area_m2']:
            w['housing_area_reallocation']={'source_synthetic_area_m2':old['H6'],
                'configured_area_m2':allocation['configured_area_m2'][hid],'rule_file_sha256':sha(OUT/'AREA_REALLOCATION.json'),
                'same_original_percapita_area_bin':True,'population_weighted_total_area_unchanged':True}
            w['H6']=allocation['configured_area_m2'][hid]
            p['housing']['H6_census_building_area_design_m2']=w['H6']
        p['reference_neighbor_room_counts']=context_room_counts(w)
        p['target_bedroom_width_weight']=min(2.5,max(1.,1.+.35*(w['N']/w['H7']-1)))if w['layout']['shared_household_count_design']>1 else 1.
        capacity=[1 if i<w['N']else 0 for i in range(w['H7'])]
        for i in range(max(0,w['N']-w['H7'])):capacity[i%w['H7']]+=1
        p['target_bedroom_width_weights']=[1. if k<=1 else 1.8 for k in capacity]
        schema=read(SCHEMA_PATH)
        assembly=reference_partition(native['bundle'])
        w,rows,meta=rebuild(w,p,selected,row['facet'],assembly,templates,BASE,schema)
        w['housing_rebuild']['constructed_internal_partition']=assembly['constructed_internal_partition']
        w['housing_rebuild']['native_interior_wall_thickness_preserved']=False
        w=configure(w,rows);w=electricity(w);w=refresh(w)
        calendars={}
        if w['shared_context']['households']or w['shared_context']['nonresident_kitchen_user_id']:
            for d in w['random10_date_selection']['dates']:
                date=dt.date.fromisoformat(d['date'])
                for offset in range(3):
                    context=dated_context(w,date+dt.timedelta(days=offset));calendars[context['date']]=context
        w['shared_context']['dated_examples']=calendars
        w['housing_rebuild']['geometry_compiler_metadata']={'path':f'geometry_metadata/{hid}.json','sha256_of_content':digest(meta)}
        w['source_V30_world_file_sha256']=row['source_world_sha256']
        w['schema']='eb.household_master_world.v33'
        w['generation_manifest']={'rule_bundle_sha256':signature,'stage':'household_background_housing_devices',
            'source_world_sha256':row['source_world_sha256'],'native_source_sha256':selected['source_sha256'],
            'human_answers_consulted':False,'EP_results_consulted':False}
        w['downstream_status']={'A_B':'must_regenerate','simulation':'must_compile_and_evaluate',
            'questionnaire':'must_rebuild_after_physics','old_answers':'preserved_with_original_stimuli;not_relabelled'}
        w['parameter_pack_sha256']=digest(w['parameter_pack']);w.pop('world_content_sha256',None);w['world_content_sha256']=digest(w)
        conservation=verify_fixed_family(old,w);audit=review(w,rows)
        # Recompute the digest independently of source serializers.
        if digest({k:v for k,v in w.items()if k!='world_content_sha256'})!=w['world_content_sha256']:raise ValueError('WORLD_HASH')
        if not audit['passed']:raise ValueError('INDEPENDENT_GEOMETRY_REVIEW:'+canonical(audit))
        paths={'world':root/'worlds'/(hid+'.json'),'IDF':root/'background_idfs'/(hid+'.idf'),
               'geometry_metadata':root/'geometry_metadata'/(hid+'.json'),'card':root/'household_cards'/(hid+'.json')}
        save(paths['world'],w);atomic_text(paths['IDF'],'! V33 constructed background shell; not occupied A/B inputs.\n'+dump(rows));save(paths['geometry_metadata'],meta)
        card={'household_id':hid,'type':w['eb_reference_type_assignment'],'province':w['province'],
            'members':[{'id':m['member_id'],'age':m['age_years'],'sex':m['sex'],'relationship_code':m['ego_relation_code'],
                        'activity_role':m['reference_activity_role'],'bedroom':m['reference_home_room_id']}for m in w['members']],
            'background':w['background_context'],'H6':w['H6'],'H7':w['H7'],
            'shared_context_households':len(w['shared_context']['households']),
            'auxiliary_residents':w['shared_context']['auxiliary_residents_count'],
            'devices':[{'asset_id':d['asset_id'],'classes':d['types'],'room':d['room_id'],'installation':d['installation']}for d in w['parameter_pack']['devices']],
            'world_content_sha256':w['world_content_sha256'],'not_a_real_observed_household':True}
        save(paths['card'],card)
        changes={}
        for k in set(old)|set(w):
            if old.get(k)!=w.get(k):changes[k]={'before_sha256':digest(old.get(k)),'after_sha256':digest(w.get(k))}
        save(root/'regeneration'/(hid+'.json'),{'household_id':hid,'reason':'user-authorized all1000 background,housing and device reconstruction',
            'source_world_sha256':row['source_world_sha256'],'new_world_file_sha256':sha(paths['world']),
            'rules_sha256':signature,'changed_fields':changes,'disposition':'new_master_world;downstream_invalidated',
            'invalidated':['A','B','compiled_occupied_IDFs','simulation','questionnaire','answer_eligibility_for_new_stimulus'],
            'old_world_and_answers_deleted':False})
        result={'household_id':hid,'passed':True,'world_path':str(paths['world'].relative_to(OUT)),'world_sha256':sha(paths['world']),
            'background_IDF_path':str(paths['IDF'].relative_to(OUT)),'background_IDF_sha256':sha(paths['IDF']),
            'card_path':str(paths['card'].relative_to(OUT)),'source_world_sha256':row['source_world_sha256'],
            'type':w['eb_reference_type_assignment'],'classes':audit['classes'],'AC_units':sum('ac'in d['types']for d in w['parameter_pack']['devices']),
            'N':w['N'],'H6':w['H6'],'H7':w['H7'],'shared_households':w['layout']['shared_household_count_design'],
            'envelope_mode':w['background_context']['envelope_reference']['mode'],'conservation':conservation,'audit':audit,
            'selected_dates':[d['date']for d in w['random10_date_selection']['dates']]}
    except Exception as e:
        result={'household_id':hid,'passed':False,'error':str(e),'rules_sha256':signature}
    save(record_path,result);return result


def sample50(records,signature):
    counts=collections.Counter(r['type']for r in records);total=len(records)
    quota={k:50*v//total for k,v in counts.items()}
    for k in sorted(counts,key=lambda k:(-(50*counts[k]%total),k))[:50-sum(quota.values())]:quota[k]+=1
    selected=[]
    for kind,n in sorted(quota.items()):
        remaining=[r for r in records if r['type']==kind];cells=collections.Counter()
        for _ in range(n):
            cell=lambda r:(min(r['N'],5),len(r['classes']),r['shared_households']>1)
            row=min(remaining,key=lambda r:(cells[cell(r)],rank(signature,kind,r['household_id'],'subset50')))
            cells[cell(row)]+=1;selected.append(row);remaining.remove(row)
    return {'schema':'eb.master_subset50.v33','households':50,'class_counts':quota,'master_class_counts':dict(counts),
        'rounding':'largest remainder;within-class source-only household/device-context diversity',
        'records':selected,'same_world_paths_and_file_hashes_as_master':True,'separate_generation_occurred':False,
        'old_online50_replaced':False,'human_answers_or_B_outcomes_used':False}


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--workers',type=int,default=4);parser.add_argument('--limit',type=int,default=1000);parser.add_argument('--ids',nargs='*');args=parser.parse_args()
    plan=read(OUT/'MODEL_PLAN1000.json')
    if not plan['all_native_files_obtained']:raise RuntimeError('Native resources incomplete')
    models={r['selected']['model_key']:r['selected']for r in plan['records']}
    with ProcessPoolExecutor(max_workers=args.workers)as pool:bundles=list(pool.map(extract_one,models.values()))
    failures=[r for r in bundles if not r['passed']]
    save(OUT/'NATIVE_EXTRACTION_REVIEW.json',{'models':len(bundles),'failures':failures,'EP_started':0})
    if failures:raise RuntimeError('Native extraction failures:'+canonical(failures))
    profiles={p['slot_id']:p for p in read(BASE/'idf_joint_production_20261005/HOUSEHOLDS1000_JOINT_GEOMETRY_CANDIDATE.json')['profiles']}
    templates=[];seen=set()
    for row in plan['records']:
        if sha(row['source_world_path'])!=row['source_world_sha256']:raise ValueError('Master source world changed:'+row['household_id'])
        for d in read(row['source_world_path'])['parameter_pack']['devices']:
            if'ac'in d['types']and digest(d['parameters'])not in seen:seen.add(digest(d['parameters']));templates.append(d)
    signature=bundle_id();root=OUT/'runs'/signature[:16]
    save(root/'RUN.json',{'schema':'eb.master_build.v33','rules_sha256':signature,'seed':'SHA256 household/rule keys;no B or human outputs',
        'source_selection_sha256':plan['source_selection_sha256'],'household_limit':args.limit,'EP_started':0})
    selected=[r for r in plan['records'][:args.limit]if not args.ids or r['household_id']in args.ids]
    if args.ids and set(args.ids)!={r['household_id']for r in selected}:raise ValueError('Requested household IDs unavailable')
    jobs=[(r,profiles[r['household_id']],templates,str(root),signature)for r in selected]
    records=[]
    with ProcessPoolExecutor(max_workers=args.workers)as pool:
        for result in pool.map(build_one,jobs):
            records.append(result)
            if len(records)%25==0:print({'processed':len(records),'passed':sum(r['passed']for r in records),'failed':sum(not r['passed']for r in records)},flush=True)
    failed=[r for r in records if not r['passed']];passed=[r for r in records if r['passed']]
    if signature!=bundle_id():raise RuntimeError('Generator rules changed during build;retain run and rerun with a fresh signature')
    report={'schema':'eb.household_master_build_review.v33','households':len(records),'passed':len(passed),'failures':failed,
        'rules_sha256':signature,'records':records,'EP_started':0,'all1000_worlds_complete':len(passed)==1000,
        'whole_benchmark_or_physics_accepted':False}
    save(root/'REVIEW.json',report)
    print(canonical({**{k:v for k,v in report.items()if k not in('records','failures')},'failed_households':[r['household_id']for r in failed]}),flush=True)
    if failed:raise SystemExit(2)
    if len(records)==1000:
        save(OUT/'WORLD_BINDINGS1000.json',{'schema':'eb.world_bindings.v33','households':1000,'records':passed,'rules_sha256':signature,
            'phase':'household_background_housing_devices','A_B_or_physics_reused':False})
        save(OUT/'SUBSET50.json',sample50(passed,signature))
        summary={'schema':'eb.master_household_phase_acceptance.v33','households':1000,'worlds_written':1000,
            'AC_households':sum('ac'in r['classes']for r in passed),'class_count_distribution':dict(collections.Counter(len(r['classes'])for r in passed)),
            'six_type_counts':dict(collections.Counter(r['type']for r in passed)),
            'explicit_envelope_renovation_scenarios':sum(r['envelope_mode']=='explicit_refurbished_envelope_scenario'for r in passed),
            'rules_sha256':signature,'world_bindings_sha256':sha(OUT/'WORLD_BINDINGS1000.json'),'subset50_sha256':sha(OUT/'SUBSET50.json'),
            'raw_geometry_and_background_only':True,'full_AB_EP_questionnaire_acceptance':False,'live_50_replaced':False}
        save(OUT/'HOUSEHOLD_PHASE_REVIEW.json',summary)
        save(BASE/'CURRENT_MASTER_INPUTS.json',{'schema':'eb.current_master_inputs.v33','stage':OUT.name,
            'phase':'household_background_housing_devices','households':1000,'subset50_from_same_master':True,
            'bindings':'WORLD_BINDINGS1000.json','bindings_sha256':sha(OUT/'WORLD_BINDINGS1000.json'),
            'phase_review':'HOUSEHOLD_PHASE_REVIEW.json','EP_allowed':False,'live_questionnaire_replaced':False})

if __name__=='__main__':main()
