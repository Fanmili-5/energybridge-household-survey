"""Reject forged consequences even when their evidence hash is unchanged."""
import argparse,copy,json
from pathlib import Path
from server import Release
from release_acceptance import read,validate_case_evidence,validate_physics_receipt

def rejects(call):
    try:call()
    except (AssertionError,KeyError):return True
    raise AssertionError('Tampered evidence was accepted')

def run(release_path,stage):
    release=Release(release_path);row=next(iter(release.rows.values()))
    _,_,cases,_=release.household(row['route']);case=cases[0]
    selected=next(h for h in read(stage/'SELECTION1000.json')['records']if h['household_id']==row['household_id'])
    round_=selected['rounds'][0];pair=read(stage/round_['pair_path'])
    result=read(stage/'readback/base7'/row['household_id']/f'{round_["round_index"]:02d}.json')
    scope={'formal50':'original50','formal950':'other950'}[release.batch]
    physics=read(stage/('PHYSICS_'+scope+'_REVIEW.json'));lease={'review':read(stage/('PRE_EP_'+scope+'.json'))}
    validate_physics_receipt(physics,lease);validate_case_evidence(case,pair,result)
    checks={}
    bad=copy.deepcopy(physics);bad['input_signature_at_readback']='invented-stale-signature'
    checks['stale_physical_signature']=rejects(lambda:validate_physics_receipt(bad,lease))
    bad=copy.deepcopy(physics);bad['completed_sides']-=1
    checks['missing_physical_side']=rejects(lambda:validate_physics_receipt(bad,lease))
    for field in ['energy','missing_scope','duplicate_scope','terminal_state','event_window']:
        altered=copy.deepcopy(case)
        if field=='energy':altered['quantities'][0]['A']['value']+=1
        elif field=='missing_scope':altered['quantities'].pop()
        elif field=='duplicate_scope':altered['quantities'].append(copy.deepcopy(altered['quantities'][0]))
        elif field=='terminal_state':altered['after_horizon']['terminal_states']={}
        else:altered['physical']['channels'][0]['end_abs_min']+=10
        checks[field]=rejects(lambda:validate_case_evidence(altered,pair,result))
    return {'passed':True,'batch':release.batch,'rejected_controls':checks,'positive_actual_case_checked':True,
            'human_answers_generated':0,'production_records_written':0,'EP_started':False}

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--release',type=Path,required=True);p.add_argument('--stage',type=Path,required=True);a=p.parse_args()
    print(json.dumps(run(a.release,a.stage),sort_keys=True))
