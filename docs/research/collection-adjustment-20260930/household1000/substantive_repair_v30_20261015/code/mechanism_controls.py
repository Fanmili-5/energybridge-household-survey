"""Synthetic failures within original50 inputs; these are not current B or human data."""
import copy,collections
from common import *
from execution import realize
from compile_inputs import signals

def main():
    school_guard();cases=[];seen=collections.Counter()
    for h in read(OUT/'SELECTION1000.json')['records']:
        w=read(OUT/h['world_path'])
        for row in h['rounds']:
            p=read(OUT/row['pair_path']);program=next((t for t in p['A']['tasks'] if t['kind'] in ('washer','dishwasher') and t['start_min']>=480),None)
            if program and seen['no_loading_signal']<20:
                q=copy.deepcopy(p);q['B']['operations']=[]
                sig,start,diag,plan=signals(w,q,'B');origin=7*1440
                targetids={n['need_id'] for n in q['needs_A']}
                actual=[t for t in plan['execution']['realized_tasks'] if t['need_id'] in targetids]
                assert actual==[]
                cases.append({'case_id':p['case_id'],'kind':'no_loading_signal','target_programs_actually_running':0});seen['no_loading_signal']+=1
            if program and seen['pre_start_removal_cancels_program']<20:
                plan=copy.deepcopy(p['A']);task=next(t for t in plan['tasks'] if t['need_id']==program['need_id'])
                load=next(o for o in plan['operations'] if o['kind']=='load' and o['need_id']==task['need_id'])
                unload=next(o for o in plan['operations'] if o['kind']=='unload' and o['need_id']==task['need_id'])
                shift=max(30,load['end_min']+30-task['start_min']);task['start_min']+=shift;task['end_min']+=shift
                for t in plan['tasks']:
                    if t['need_id']==task['need_id']+':dry':t['start_min']+=shift;t['end_min']+=shift
                unload.update(start_min=load['end_min']+10,end_min=load['end_min']+20)
                ws=copy.deepcopy(p['world']['operator_windows']);ws.setdefault(unload['operator_id'],[]).append([unload['start_min'],unload['end_min']])
                ex=realize(w,plan,ws,p['needs_A'])
                assert task['need_id'] not in {t['need_id'] for t in ex['realized_tasks']}
                assert any(x['failure_reason']=='unclean_batch_removed_before_program' and x['need_id']==task['need_id'] for x in ex['operations'])
                cases.append({'case_id':p['case_id'],'kind':'pre_start_removal_cancels_program','given_test_window_added':True});seen['pre_start_removal_cancels_program']+=1
            ev=next((n for n in p['needs_A'] if n['kind']=='ev' and 480<=n['trip_departure_min']<1440 and n['release_min']-n['trip_departure_min']>=40),None)
            if ev and seen['EV_away_plug_and_charge']<20:
                q=copy.deepcopy(p);q['B']=copy.deepcopy(q['A']);minute=ev['trip_departure_min']+10
                q['B']['controls']=[c for c in q['B']['controls'] if c['asset_id']!=ev['asset_id']]
                q['B']['controls'].append({'kind':'ev_charge_window','asset_id':ev['asset_id'],'start_min':minute,'end_min':minute+20,'service_date':p['date']})
                q['B']['operations'].append({'operation_id':'synthetic-away-plug','kind':'EV_plug','need_id':'synthetic-away','operator_id':w['given_transport_contract']['handling_operator_id'],'start_min':minute,'end_min':minute+10,'duration_min':10})
                who=w['given_transport_contract']['handling_operator_id'];q['world']['operator_windows'].setdefault(who,[]).append([minute,minute+10])
                sig,start,diag,plan=signals(w,q,'B');origin=7*1440
                assert any(z['absolute_min']==origin+ev['trip_departure_min'] and z['trip_departed'] for z in diag), 'actual departure is a test precondition'
                assert sum(sig[ev['asset_id']][(origin+minute)//10:(origin+minute+20)//10])==0
                assert any(o['operation_id']=='synthetic-away-plug' and o['failure_reason']=='vehicle_away' for o in plan['execution']['operations'])
                cases.append({'case_id':p['case_id'],'kind':'EV_away_plug_and_charge','charged_kWh':0});seen['EV_away_plug_and_charge']+=1
    assert all(seen[k]>=10 for k in ('no_loading_signal','pre_start_removal_cancels_program','EV_away_plug_and_charge'))
    save(OUT/'MECHANISM_NEGATIVE_CONTROLS.json',{'status':'pass','counts':dict(seen),'records':cases,
        'synthetic_diagnostics_not_actual_frozen_proposals':True,'no_EP_started':True,'human_answers':0})
    print(dict(seen),flush=True)
if __name__=='__main__':main()
