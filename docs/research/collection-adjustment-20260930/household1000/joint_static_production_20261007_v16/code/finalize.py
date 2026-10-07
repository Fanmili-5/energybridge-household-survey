"""Seal a checked static input release,keeping the separate EP/human gates closed."""
import collections, platform, time
from common import *
def main():
    school_guard();review=read(OUT/'WHOLE_COHORT_REVIEW.json');native=read(OUT/'NATIVE_INTERFACE_REVIEW.json');ui=read(OUT/'R72_ADAPTER_REVIEW.json')
    assert review['all_static_checks_pass'],review
    assert native['counts']['plans_checked']==20000 and not native['failures']
    assert ui['checked']==10000 and not ui['failures']
    geometry=read(OUT/'SAVED_GEOMETRY_REVIEW.json');assert geometry['households']==1000 and not geometry['failures']
    worlds=read(OUT/'WORLD_BINDINGS1000.json');pairs=read(OUT/'PAIR_BINDINGS10000.json');idf=read(OUT/'IDF_BINDINGS20000.json')
    assert len(worlds['records'])==1000 and pairs['pairs']==10000 and idf['IDF_count']==20000
    conditions=collections.Counter();quarters=collections.Counter();months=collections.Counter();residents=0;type_instances=collections.Counter()
    match=[]
    for b in worlds['records']:
        w=read(OUT/b['world_path']);residents+=w['N'];changes=w['reference_change_ledger']
        for c in changes:conditions[c['field']]+=1
        for d in w['parameter_pack']['devices']:type_instances.update(d['types'])
        for s in w['random10_date_selection']['dates']:quarters[s['quarter']]+=1;months[s['date'][5:7]]+=1
        match.append({'household_id':w['household_id'],'province':w['province'],'N':w['N'],'G':w['G'],'H6':w['H6'],'H7':w['H7'],
            'device_types':w['joint_matching']['types'],'physical_asset_count':len(w['parameter_pack']['devices']),
            'parameter_pack_sha256':w['parameter_pack_sha256'],'source_model':w['layout']['source_parameter_reference'],
            'operator_resident':w['operating_context']['operators'][0]['resident'],'reference_changes':changes,
            'statistical_source_anchor_preserved':True,'static_matching_complete':True,'EP_verified':False})
    save(OUT/'MATCHING_LEDGER1000.json',{'records':match,'residents':residents,'reference_change_counts':dict(conditions),
        'functional_device_instance_counts':dict(type_instances),'owned_national_prevalence_estimate':False})
    save(OUT/'DATE_SELECTION1000.json',{'households':1000,'target_dates':10000,'quarter_counts':dict(quarters),'month_counts':dict(months),
        'all_prior_selections_preserved':True,'EP_annual':False,'support_days_are_extra_questions':False})
    sourcefiles={}
    for b in read(OLD/'WORLD_BINDINGS1000.json')['records']:
        for p in [OLD/b['world_path'],V12/'background_idfs'/f'{b["household_id"]}.idf',Path(b['weather']['path'])]:
            sourcefiles[str(p)]=sha(p)
    for p in [SCHEMA_PATH,UP/'experiments/models/family_home/family_simple_3day.idf',UP/'energybridge/simulation/appliance_sim.py']:
        sourcefiles[str(p)]=sha(p)
    save(OUT/'SOURCE_INPUT_LOCK.json',sourcefiles)
    save(OUT/'INPUT_LOCK.json',{str(p.relative_to(OUT)):sha(p) for folder in ['code','inputs'] for p in (OUT/folder).iterdir() if p.is_file()})
    import shapely,numpy
    save(OUT/'RUNTIME.json',{'host':platform.node(),'python':sys.version,'shapely':shapely.__version__,'numpy':numpy.__version__,
        'EP_schema_sha256':sha(SCHEMA_PATH),'EP_engine_called':False,'compute_scope':'school Linux static production and actual API/schema/adapter checks'})
    delivery={'schema':'eb.joint_static_delivery.v1','status':'complete_and_checked_static_reference_inputs',
        'households':1000,'residents':residents,'K_counts':worlds['K_counts'],'device_class_counts':worlds['device_class_counts'],
        'covered_structural_combinations':len(worlds['pattern_counts']),'AB_pairs':10000,'paired_IDF_inputs':20000,
        'native_API_plan_checks':20000,'whole_cohort_static_failures':0,'original_R72_adapter_cases':10000,
        'saved_geometry_households_checked':1000,
        'counterexamples_correctly_rejected':len(read(OUT/'COUNTEREXAMPLE_REVIEW.json')['probes']),
        'reference_change_counts':dict(conditions),'EP_hold':True,'EP_runs':0,'human_answers':0,'model_API_calls':0,
        'rules_and_matching_frozen':True,'physical_service_calibration_complete':False,'collection_release':False,'training_release':False,
        'evidence_boundary':'source-anchored city reference households and explicitly designed4to6-class benchmark contexts;not observed full homes,national device prevalence,or validated human behavior',
        'next_gate':'review these saved inputs;EP runtime/service/rebound checks on school server only after user lifts existing hold',
        'completed_unix':time.time()}
    save(OUT/'DELIVERY.json',delivery)
    files={str(p.relative_to(OUT)):sha(p) for p in OUT.rglob('*') if p.is_file() and '__pycache__' not in p.parts and p.name not in ['PACKAGE_MANIFEST.json','delivery_bundle.tar.gz'] and p.suffix not in ['.log']}
    save(OUT/'PACKAGE_MANIFEST.json',{'scope':'static reference inputs and reviews,not EP/human release','files':files,'file_count':len(files),'sealed':True})
    print(delivery,flush=True)
if __name__=='__main__':main()
