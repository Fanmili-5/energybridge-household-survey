"""Collection presentation adapter; accepted physics inputs remain immutable."""
import argparse,hashlib,json,sys
from pathlib import Path

EXTRA_LABELS={'given_variable_short_work_reference':'有工作来源提示；给定日期变化的短时工作情景'}

def main():
    p=argparse.ArgumentParser();p.add_argument('--stage',type=Path,required=True);p.add_argument('--cohort',choices=['formal50','formal950'],required=True);a=p.parse_args()
    stage=a.stage.resolve();sys.path.insert(0,str(stage/'code'));import materials
    def read(path):return json.loads(path.read_text())
    allroles={m['reference_activity_role']for path in(stage/'worlds').glob('*.json')for m in read(path)['members']}
    assert allroles<=set(materials.LABELS)|set(EXTRA_LABELS),'Every activity role requires an explicit, evidence-bounded display label'
    materials.LABELS.update(EXTRA_LABELS)
    receipt={'schema':'eb.collection_role_label_catalog.v1','all_activity_roles':sorted(allroles),'additional_explicit_labels':EXTRA_LABELS,
        'accepted_generator_and_physical_inputs_changed':False,'reference_employment_not_promoted_to_observed_profession':True,
        'renderer_sha256':hashlib.sha256((stage/'code/materials.py').read_bytes()).hexdigest(),'adapter_sha256':hashlib.sha256(Path(__file__).read_bytes()).hexdigest()}
    (stage/'RENDERER_ROLE_CATALOG_REVIEW.json').write_text(json.dumps(receipt,ensure_ascii=False,indent=2)+'\n')
    sys.argv=['materials.py','--cohort',a.cohort];materials.main()

if __name__=='__main__':main()
