"""Package a signed, controlled case bank without rerunning generation or EP."""
import argparse
import hashlib
import json
import shutil
from pathlib import Path
from answer_contract import ANSWER_INSTRUCTIONS
from release import UI_VERSION,CONTRACT_VERSION,encoded,digest

HERE=Path(__file__).resolve().parent
def sha(path):return hashlib.sha256(path.read_bytes()).hexdigest()
def read(path):return json.loads(path.read_text())
def write(path,value):path.write_bytes(encoded(value)+b'\n')

def build(source,output,cohort='reference50',lease_seconds=7200):
    source=Path(source).resolve();output=Path(output).resolve()
    prior=read(source/'FORMAL_RELEASE.json')
    assert digest({k:v for k,v in prior.items()if k!='release_sha256'})==prior['release_sha256']
    for name,expected in prior['files'].items():
        path=source/name
        assert path.resolve().is_relative_to(source)and sha(path)==expected,name
    assert not output.exists(),'Use a new immutable release directory.'
    index=read(source/'INDEX50.json');models=read(source/'DISPLAY_MODELS50.json')
    assert len(index['cases'])==prior['cases']and len(index['households'])==prior['households']
    (output/'public').mkdir(parents=True)
    for row in index['cases']:
        raw=(source/'public'/row['path']).read_bytes();case=json.loads(raw)
        assert sha(source/'public'/row['path'])==row['sha256']and case['response']is None
        assert case['household_id']==row['household_id']and case['case_id']==row['case_id']
        assert case['VPP_results']and case['impact']is not None and case['bindings']
        target=output/'public'/row['path'];target.parent.mkdir(parents=True,exist_ok=True);target.write_bytes(raw)
    for hid in index['households']:
        target=output/f'public/households/{hid}.json';target.parent.mkdir(parents=True,exist_ok=True)
        shutil.copyfile(source/f'public/households/{hid}.json',target)
        assert sha(target)==index['profiles_sha256'][hid]
    for name in ['index.html','entry.html','view.css','collection-client.js','entry.js','base.css','required-response.js','view.js']:
        shutil.copyfile(HERE/name,output/'public'/name)
    write(output/'ANSWER_INSTRUCTIONS.json',ANSWER_INSTRUCTIONS)
    write(output/'DISPLAY_MODELS50.json',models)
    index.update(schema='eb.reference_benchmark.index.v1',ui_revision=UI_VERSION,mode='reference_collection')
    index['ui_assets_sha256']={p.name:sha(p)for p in (output/'public').iterdir()if p.is_file()}
    write(output/'INDEX50.json',index)
    manifest={k:prior[k]for k in ['households','cases','source_pins','type_counts','A_stage','B_stage','physical_stage','impact_stage']}
    manifest.update(schema='eb.reference_benchmark.release.v1',cohort_id=cohort,source_release_sha256=prior['release_sha256'],
                    ui_revision=UI_VERSION,response_contract=CONTRACT_VERSION,questions_per_household=10,assignment_lease_seconds=lease_seconds,
                    human_collection_release=not prior.get('fixture_only',False),training_release=False,fixture_only=prior.get('fixture_only',False),source_case_bytes_modified=False,new_EP_runs=0,
                    full1000_deferred_by_user=True,entry_mode='open_no_invitation',timeline=False,quality_policy='manual_versioned_review_no_auto_labels')
    manifest['files']={str(p.relative_to(output)):sha(p)for p in sorted(output.rglob('*'))if p.is_file()}
    manifest['implementation_files']={p.name:sha(p)for p in sorted(HERE.iterdir())if p.is_file()}
    manifest['release_sha256']=digest(manifest)
    write(output/'FORMAL_RELEASE.json',manifest)
    return manifest

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--source',type=Path,required=True);p.add_argument('--output',type=Path,required=True)
    p.add_argument('--cohort-id',default='reference50');a=p.parse_args()
    m=build(a.source,a.output,a.cohort_id)
    print(json.dumps({k:m[k]for k in ['release_sha256','households','cases','cohort_id','questions_per_household']}))
