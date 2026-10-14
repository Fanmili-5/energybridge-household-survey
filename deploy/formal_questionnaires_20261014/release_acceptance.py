"""Verify every formal case against accepted, current school-world artifacts."""
import argparse,hashlib,json,math,sys,subprocess
from pathlib import Path
from server import Release

def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def read(p):return json.loads(p.read_text())
def content_sha(x):return hashlib.sha256(json.dumps(x,ensure_ascii=False,sort_keys=True,separators=(',',':'),allow_nan=False).encode()).hexdigest()

def validate_physics_receipt(physics,lease):
    review=lease['review']
    assert physics['acceptance_passed']and not physics['failures']
    assert physics['input_signature_at_readback']==review['input_signature'],'Stale physical readback'
    assert physics['expected_sides']==physics['completed_sides']==review['expected_sides'],'Incomplete physical cohort'
    assert physics['checked_pairs']==review['expected_pairs'],'Incomplete physical pairs'

def validate_case_evidence(case,pair,result):
    result_hash=content_sha(result)
    assert case['physical']['status']=='computed_reference'and case['after_horizon']['status']=='reported_model_tail'
    quantities={q['scope']:q for q in case['quantities']}
    scopes={'event','living_day','living_day_and_service_tail'}
    assert set(quantities)==scopes and len(case['quantities'])==len(scopes)
    assert len(case['physical']['channels'])==1
    for scope,channel in list(quantities.items())+[('event',case['physical']['channels'][0])]:
        assert channel['evidence_sha256']==result_hash
        for side in('A','B'):
            value=channel[side]['value']
            assert channel[side]['status']=='computed'and not isinstance(value,bool)and math.isfinite(value)
            assert value==result['energy'][scope][side],'Displayed energy differs from bound SQL readback'
            assert channel[side].get('unit',channel.get('unit'))=='kWh'
    channel=case['physical']['channels'][0]
    assert [channel['start_abs_min'],channel['end_abs_min']]==pair['event_window_min']
    assert case['after_horizon']['service_tail_min']==pair['service_tail_min']
    assert case['after_horizon']['terminal_states']==result['terminal_states']

def check(release_path,stage,node='node'):
    stage=stage.resolve();sys.path.insert(0,str(stage/'code'))
    from cohort_gate import require_reviewed_ep
    import materials
    from render_materials import EXTRA_LABELS
    assert materials.OUT.resolve()==stage,'Current stage module mismatch'
    materials.LABELS.update(EXTRA_LABELS)
    release=Release(release_path);scope={'formal50':'original50','formal950':'other950'}[release.batch]
    lease=require_reviewed_ep(scope)
    physics=read(stage/('PHYSICS_'+scope+'_REVIEW.json'));validate_physics_receipt(physics,lease)
    binding_result=json.loads(subprocess.run([node,str(Path(__file__).with_name('verify_formal_bindings.cjs')),str(release.root)],check=True,capture_output=True,text=True).stdout)
    assert binding_result['passed']and binding_result['case_bindings_verified']==len(release.rows)*10
    partition=set(read(stage/'PARTITIONS.json')[release.batch]);assert {r['household_id']for r in release.rows.values()}==partition
    selected={h['household_id']:h for h in read(stage/'SELECTION1000.json')['records']}
    count=0
    for route,row in release.rows.items():
        h=selected[row['household_id']];_,page,cases,hashes=release.household(route)
        assert sha(stage/h['world_path'])==h['world_sha256']
        world=read(stage/h['world_path']);actor=materials.actor(world)
        assert len(cases)==len(h['rounds'])==10
        for case,round_ in zip(cases,h['rounds']):
            identity=case['identity'];assert(identity['role_id'],identity['date'],identity['round_index'])==(h['household_id'],round_['date'],round_['round_index'])
            assert case['profile']['source_world_sha256']==world['world_content_sha256']
            assert case['audit']['source_pair_sha256']==round_['pair_sha256']==case['bindings']['source_pair_sha256']==sha(stage/round_['pair_path'])
            pair=read(stage/round_['pair_path'])
            result=read(stage/'readback/base7'/h['household_id']/f'{round_["round_index"]:02d}.json')
            validate_case_evidence(case,pair,result)
            expected=materials.scene(world,{**round_,'weather':h['weather']},pair,actor)
            # Node serializes 1.0 as 1. Derived presentation bindings therefore
            # use the actual shipped JS verifier above, rather than Python JSON.
            assert set(case['bindings'])==set(expected['bindings'])
            assert {k:v for k,v in case.items()if k!='bindings'}=={k:v for k,v in expected.items()if k!='bindings'},'Published role/task/impact differs from current source-renderer result'
            assert case['human_label_count']==0 and case['training_release']is False
            assert case['audit']['physical_calibration_complete']is False
            count+=1
    assert count==len(partition)*10
    for name,digest in release.manifest['files'].items():assert sha(release.root/name)==digest
    return {'passed':True,'batch':release.batch,'households':len(partition),'cases_checked':count,'release_signature':release.signature,
        'physical_review_sha256':sha(stage/('PHYSICS_'+scope+'_REVIEW.json')),'current_world_pair_SQL_readback_bindings':'pass',
        'current_content_bound_physical_receipt':'pass','source_renderer_full_case_regeneration':'pass',
        'displayed_quantities_and_terminal_states_equal_readback':'pass',
        'shipped_frontend_canonical_bindings':'pass',
        'missing_or_pending_physical_cases':0,'source_reference_cases_promoted_to_human_labels':False,'human_answers_created':0}

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--release',type=Path,required=True);p.add_argument('--stage',type=Path,required=True);p.add_argument('--output',type=Path,required=True);p.add_argument('--node',default='node');a=p.parse_args();result=check(a.release,a.stage,a.node);a.output.write_text(json.dumps(result,indent=2)+'\n');print(json.dumps(result))
