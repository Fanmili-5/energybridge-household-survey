"""Verify every formal case against accepted, current school-world artifacts."""
import argparse,hashlib,json,math
from pathlib import Path
from server import Release

def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def read(p):return json.loads(p.read_text())
def content_sha(x):return hashlib.sha256(json.dumps(x,ensure_ascii=False,sort_keys=True,separators=(',',':'),allow_nan=False).encode()).hexdigest()
def check(release_path,stage):
    release=Release(release_path);scope={'formal50':'original50','formal950':'other950'}[release.batch]
    physics=read(stage/('PHYSICS_'+scope+'_REVIEW.json'));assert physics['acceptance_passed']and not physics['failures']
    partition=set(read(stage/'PARTITIONS.json')[release.batch]);assert {r['household_id']for r in release.rows.values()}==partition
    selected={h['household_id']:h for h in read(stage/'SELECTION1000.json')['records']}
    count=0
    for route,row in release.rows.items():
        h=selected[row['household_id']];_,page,cases,hashes=release.household(route)
        assert len(cases)==len(h['rounds'])==10
        for case,round_ in zip(cases,h['rounds']):
            identity=case['identity'];assert(identity['role_id'],identity['date'],identity['round_index'])==(h['household_id'],round_['date'],round_['round_index'])
            assert sha(stage/h['world_path'])==h['world_sha256']
            assert case['profile']['source_world_sha256']==read(stage/h['world_path'])['world_content_sha256']
            assert case['audit']['source_pair_sha256']==round_['pair_sha256']==case['bindings']['source_pair_sha256']
            result=stage/'readback/base7'/h['household_id']/f'{round_["round_index"]:02d}.json';result_hash=content_sha(read(result))
            assert case['physical']['status']=='computed_reference'and case['after_horizon']['status']=='reported_model_tail'
            for channel in case['physical']['channels']+case['quantities']:
                assert channel['evidence_sha256']==result_hash
                for side in('A','B'):assert channel[side]['status']=='computed'and math.isfinite(channel[side]['value'])
            assert case['human_label_count']==0 and case['training_release']is False
            assert case['audit']['physical_calibration_complete']is False
            count+=1
    assert count==len(partition)*10
    for name,digest in release.manifest['files'].items():assert sha(release.root/name)==digest
    return {'passed':True,'batch':release.batch,'households':len(partition),'cases_checked':count,'release_signature':release.signature,
        'physical_review_sha256':sha(stage/('PHYSICS_'+scope+'_REVIEW.json')),'current_world_pair_SQL_readback_bindings':'pass',
        'missing_or_pending_physical_cases':0,'source_reference_cases_promoted_to_human_labels':False,'human_answers_created':0}

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--release',type=Path,required=True);p.add_argument('--stage',type=Path,required=True);p.add_argument('--output',type=Path,required=True);a=p.parse_args();result=check(a.release,a.stage);a.output.write_text(json.dumps(result,indent=2)+'\n');print(json.dumps(result))
