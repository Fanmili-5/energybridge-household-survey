"""Verify all bindings, record source domains and package the actual artifacts."""
import collections,tarfile
from common import *
from worlds import USAGE_KEYS
def no_usage(p):
    return not (set(p)&USAGE_KEYS) and all(no_usage(v) for v in p.values() if isinstance(v,dict))
def main():
    school_guard();sel=read(OUT/'SELECTION1000.json');ib=read(OUT/'IDF_BINDINGS20000.json');idx={h['household_id']:h for h in sel['records']};fail=[];count=0;classes=collections.Counter()
    assert len(idx)==1000 and ib['IDF_count']==20000 and ib['failed']==[]
    world_contents={};member_count=0
    for h in ib['households']:
        sh=idx[h['household_id']];w=read(OUT/sh['world_path']);types={k for d in w['parameter_pack']['devices'] for k in d['types']};classes[len(types)]+=1
        assert sha(OUT/sh['world_path'])==sh['world_sha256']
        assert digest({k:v for k,v in w.items() if k!='world_content_sha256'})==w['world_content_sha256']
        assert digest(w['parameter_pack'])==w['parameter_pack_sha256']==sh['parameter_pack_sha256']
        world_contents[h['household_id']]=w;member_count+=len(w['members'])
        if any(not no_usage(d['parameters']) for d in w['parameter_pack']['devices']) or any('config' in a for a in w['assets'].values()):fail.append([h['household_id'],'LEGACY_ACTIVE_PARAMETERS'])
        for c,r in zip(h['records'],sh['rounds']):
            if c['pair_sha256']!=r['pair_sha256'] or sha(OUT/r['pair_path'])!=r['pair_sha256']:fail.append([h['household_id'],r['round_index'],'PAIR_BINDING'])
            p=read(OUT/r['pair_path'])
            assert digest({k:v for k,v in p.items() if k!='pair_content_sha256'})==p['pair_content_sha256']
            assert p['world_sha256']==w['world_content_sha256'] and p['parameter_pack_sha256']==w['parameter_pack_sha256']
            for s in ('A','B'):
                b=c[s];count+=1
                if sha(OUT/b['IDF_path'])!=b['IDF_sha256'] or b['parameter_pack_sha256']!=w['parameter_pack_sha256']:fail.append([h['household_id'],r['round_index'],s,'IDF_BINDING'])
    assert count==20000 and not fail,(count,fail[:5])
    actor_index={}
    for b in read(OUT/'ACTOR_BINDINGS.json')['records']:
        assert sha(OUT/b['actor_path'])==b['actor_sha256']
        a=read(OUT/b['actor_path']);w=world_contents[b['household_id']]
        assert a['world_content_sha256']==w['world_content_sha256'] and a['parameter_pack_sha256']==w['parameter_pack_sha256']
        actor_index[b['household_id']]=a
    assert len(actor_index)==1000
    for b in read(OUT/'CONSUMER_BINDINGS.json')['records']:
        assert sha(OUT/b['consumer_path'])==b['consumer_sha256']
        c=read(OUT/b['consumer_path']);hid=c['identity']['role_id'];i=c['identity']['round_index'];s=idx[hid]['rounds'][i-1]
        assert c['identity']['case_id']==b['case_id']==s['case_id'] and c['identity']['date']==s['date']
        assert c['audit']['source_pair_sha256']==b['pair_sha256']==s['pair_sha256']
        assert c['profile']['profile']==actor_index[hid]['profile']
        assert c['profile']['source_world_sha256']==world_contents[hid]['world_content_sha256']
        assert c['human_label_count']==0 and c['collection_release'] is False and c['training_release'] is False
    rr=read(OUT/'READBACK_all_REVIEW.json');ss=read(OUT/'READBACK_sensitivity_REVIEW.json');mr=read(OUT/'MATERIALS_REVIEW.json');fr=read(OUT/'engineering_render_records/RENDER_REVIEW.json');wr=read(OUT/'WEATHER_SOLVER_REVIEW.json')
    clock_review=read(OUT/'FRONTEND_CLOCK_REVIEW.json');assert clock_review['status']=='pass' and clock_review['actual_cases_checked']==500 and clock_review['axis_hours']==24
    assert rr['checked_pairs']==500 and rr['failures']==[] and ss['checked_pairs']==200 and ss['failures']==[] and fr['status']=='pass' and wr['verification_pass']
    sr=read(OUT/'STATIC_REVIEW.json');stats=collections.Counter()
    for p in (OUT/'readback/base7').rglob('*.json'):
        r=read(p)
        for s in ('A','B'):
            hot=r['services'][s].get('hot_water',[]);ev=r['services'][s].get('EV',{})
            stats[s+'_hot_water_goal_failed_pairs']+=bool(hot and any(not x['temperature_pass'] for x in hot))
            stats[s+'_EV_target_failed_pairs']+=bool(ev and any(not x['target_pass'] for x in ev['goals']))
            stats[s+'_EV_trip_shortfall_pairs']+=bool(ev and any(x['shortfall_kWh']>1e-6 for x in ev['trips']))
            stats[s+'_EV_reserve_failed_pairs']+=bool(ev and any(not x['reference_reserve_pass'] for x in ev['trips']))
    source=read(OUT/'SOURCE_EMPLOYMENT_AGGREGATES.json')
    review={'schema':'eb.repaired_delivery_review.v18','households':len(idx),'members':member_count,'pairs':10000,'IDFs':count,
        'all_IDF_pair_world_parameter_hash_bindings_checked':True,'legacy_usage_aliases_active':0,'device_coverage_counts':dict(classes),
        'all_world_content_parameter_actor_consumer_bindings_checked':True,
        'all500_frontend24h_axes_and_full_operation_endpoints_checked':True,
        'original50_reference_pairs_checked':500,'sensitivity_pairs_checked':200,
        'maximum_pre_notice_difference':rr['maximum_pre_notice_difference'],'maximum_meter_residual_J':rr['maximum_meter_residual_J'],
        'service_goal_and_trip_counts':dict(stats),'proposal_mechanisms':sr['proposal_mechanisms'],
        'source_employment_admitted_households':source['frame_qc']['accepted_source_proxy_households'],
        'source_employment_members':source['co_resident_members'],'raw_source_rows_exported':0,
        'actor_cards':mr['actor_cards'],'consumer_tasks':mr['consumer_tasks'],'original_frontend_cases_rendered':fr['actual_cases_rendered'],
        'human_answers':0,'other950_EP_executed':False,'joint_diary_calibration':False,'physical_calibration':False,
        'known_warnings_retained_and_diagnosed':rr['warning_categories'],'weather_solver_refined_verification':wr['verification_pass'],
        'strict_weather_point_reference_agreement':wr['strict_point_reference_agreement_pass'],
        'sensitivity_maximum_AB_energy_difference_kWh':ss['sensitivity']['maximum_absolute_A_minus_B_energy_difference_kWh'],
        'human_readability_and_role_effect_measured':False,'collection_release':False,'training_release':False}
    save(OUT/'DELIVERY_REVIEW.json',review)
    names=['SOURCE_EMPLOYMENT_AGGREGATES.json','PROTOCOL.json','WORLD_BINDINGS1000.json','WORLD_BUILD_REVIEW.json','SELECTION1000.json','SELECTION50.json',
           'STATIC_REVIEW.json','INPUT_AUDIT.json','IDF_BINDINGS20000.json','COMPILED50.json','EP_all_REVIEW.json','EP_sensitivity_REVIEW.json','READBACK_all_REVIEW.json','READBACK_sensitivity_REVIEW.json',
           'WEATHER_SOLVER_REVIEW.json','STRICT_WEATHER_REFERENCE_COMPARISON.json','ACTOR_BINDINGS.json','CONSUMER_BINDINGS.json','MATERIALS_REVIEW.json','DELIVERY_REVIEW.json',
           'README.md','FIELD_EVIDENCE.md','HUMAN_PILOT_PROTOCOL.md','HUMAN_RECORD_TEMPLATE.json','engineering_render_records/RENDER_REVIEW.json','FRONTEND_CLOCK_REVIEW.json']
    paths=[OUT/n for n in names]+list((OUT/'code').glob('*'))
    bindings={str(p.relative_to(OUT)):sha(p) for p in paths if p.is_file()}
    save(OUT/'DELIVERY.json',{'schema':'eb.household_repaired_delivery.v18','stage':OUT.name,'files':bindings,
          'worlds':1000,'paired_tasks':10000,'IDF_inputs':20000,'original50_reference_outcomes':500,
          'location':'school Linux; dataset package mirrored locally','other950_EP':'held, no outcomes substituted',
          'scope':'source-anchored city ordinary residential reference task worlds and human roleplay materials; not actual observed households or preferences',
          'human_answers':0,'collection_release':False,'training_release':False,'scientific_benchmark_validity_complete':False})
    paths=[OUT/n for n in names]+[OUT/'DELIVERY.json']
    for folder in ['worlds','pairs','actors','consumers','collection_materials','readback','frontend_release','code']:paths.extend(p for p in (OUT/folder).rglob('*') if p.is_file() and '__pycache__' not in p.parts)
    with tarfile.open(OUT/'DATASET_v18.tar.gz','w:gz') as t:
        for p in sorted(set(paths)):t.add(p,arcname=str(p.relative_to(OUT)))
    save(OUT/'PACKAGE_RECEIPT.json',{'file':'DATASET_v18.tar.gz','sha256':sha(OUT/'DATASET_v18.tar.gz'),'bytes':(OUT/'DATASET_v18.tar.gz').stat().st_size,
           'IDFs_and_SQL_remain_on_school':True,'engineering_synthetic_answers_not_in_dataset':True,'delivery_sha256':sha(OUT/'DELIVERY.json')})
    print(review,flush=True);print(read(OUT/'PACKAGE_RECEIPT.json'),flush=True)
if __name__=='__main__':main()
