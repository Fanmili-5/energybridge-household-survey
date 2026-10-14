"""Invented protocol-only stimulus, never a claimed browser/human observation."""
import argparse,json
from pathlib import Path
from server import Release
from store import MODEL_FIELDS,digest

def main():
    p=argparse.ArgumentParser();p.add_argument('--release',type=Path,required=True);p.add_argument('--output',type=Path,required=True);a=p.parse_args()
    release=Release(a.release);route=next(iter(release.rows));_,_,cases,hashes=release.household(route);case=cases[0]
    fields={k:'invented protocol-only fixture: '+k for k in sorted(MODEL_FIELDS)}
    stimulus={'schema':'eb.joint_b.displayed_input.v1','date':case['identity']['date'],'fields':fields,'display_assignment':case['display_assignment'],'history':[]}
    record={'schema':'eb.role_response.v1','questionnaire_ui_version':'eb.formal_role_questionnaire.20261014.1',
        'status':'engineering_fixture','human_label_count':0,'training_release':False,'respondent':{'age_years':None,'gender':None},
        'test_feedback':{'decision':'accept','decision_status':'answered','score':None,'comfort_score':None,'energy_score':None,'vpp_score':None,'comment':'invented protocol test, not a human answer'},
        'input':stimulus,'audit':{'source_case':case,'source_binding':{'source_package_sha256':hashes[0]},'collection_linkage':{},
            'presentation':{'rendered_snapshot':fields,'model_input_sha256':digest(stimulus),'rendered_snapshot_sha256':digest(fields),
                'fixture_scope':'schema/HTTP only; no actual browser stimulus or human observation'}}}
    a.output.write_text(json.dumps(record,ensure_ascii=False)+'\n');a.output.chmod(0o600)
    print(json.dumps({'batch':release.batch,'fixture_scope':'invented protocol only','human_answers':0}))

if __name__=='__main__':main()
