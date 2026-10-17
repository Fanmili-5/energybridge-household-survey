"""Check boundary repair and genuine inability to construct a supported request."""
import sys
from pathlib import Path
STAGE=Path(__file__).resolve().parents[1];sys.path.insert(0,str(STAGE/'code'))
from common import *
from material_opportunities import select_request
from event_proposals import make
from collections import Counter

def get(hid,date):
    rows=read(SOURCE_B/'PAIR_BINDINGS10000.json')['records'];row=next(r for r in rows if r['household_id']==hid)
    index=next(i for i,r in enumerate(row['rounds'])if r['date']==date);p=read(SOURCE_B/row['rounds'][index]['path'])
    return read(A_STAGE/p['A_source']['world_path']),p,index

def main():
    tests=[]
    w,p,index=get('ordinary-v6-0244','2025-10-21')
    assignment=select_request(w,p,p['proposal']['input_design_assignment'],Counter())
    assert assignment['target_start_min']==1140
    b,q=make(w,{**p,'input_design_assignment':assignment},index)
    assert next(t['start_min']for t in b['tasks']if t['need_id']=='2025-10-21:dishes')==1140
    assert [o for o in b['operations']if o['kind']=='load']==[o for o in p['A']['operations']if o['kind']=='load']
    tests.append('loaded_dishwasher_uses_supported_after_event_boundary')
    for key,ident in [('tasks','task_id'),('operations','operation_id')]:
        assert sorted(x[ident]for x in b[key])==sorted(x[ident]for x in p['A'][key])
    assert [o for o in b['operations']if o['kind'].startswith('EV_')]==[o for o in p['A']['operations']if o['kind'].startswith('EV_')]
    tests.append('no_new_operations_needs_or_EV_handling')
    w,p,index=get('ordinary-v6-0001','2025-03-27')
    assert select_request(w,p,p['proposal']['input_design_assignment'],Counter())is None
    tests.append('purposeful_routine_preserved_even_when_another_device_could_change')
    c=copy.deepcopy(p);c['A']['controls']=[]
    assert select_request(w,c,p['proposal']['input_design_assignment'],Counter())is None
    tests.append('outside_event_program_with_no_other_device_opportunity_retains_A')
    c=copy.deepcopy(p);c['VPP_events']=[{**p['VPP_events'][0],'direction':'up'}];c['A']['tasks']=[]
    c['A']['controls']=[{**x,'heating_setpoint_C':x['cooling_setpoint_C']-2}
                      for x in c['A']['controls']if x['kind']=='ac_setpoint']
    assignment={**p['proposal']['input_design_assignment'],'mechanism':'thermal_setpoint'}
    assert select_request(w,c,assignment,Counter())is None
    tests.append('minimum_deadband_without_other_opportunity_does_not_force_difference')
    result={'passed':True,'tests':tests,'count':len(tests),'rules_sha256':rules_id(),'human_labels_created':0}
    save(OUT/'REGRESSION_RESULTS.json',result);print(canonical(result))

if __name__=='__main__':main()
