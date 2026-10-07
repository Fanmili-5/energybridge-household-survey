"""Original random dates, mixed proposal conditions; never select human outcomes."""
import argparse,collections,concurrent.futures,copy,datetime as dt,importlib.util,sys
from pathlib import Path
OUT=Path(__file__).resolve().parents[1];BASE=OUT.parent;SRC=BASE/'joint_static_production_20261007_v16'
spec=importlib.util.spec_from_file_location('opportunity_rules',BASE/'contrast50_20261007_v1/code/generate.py')
op=importlib.util.module_from_spec(spec);spec.loader.exec_module(op)
from common import read,save,sha,digest,rank
from assess import assess
from project_actors import project

PROTOCOL={'version':'roleplay_mixed_v17','target':'one shared role-conditioned model predicting assigned-actor choice,scores,conditions and language',
 'date_rule':'preserve each original frozen2025quarter-stratified10dates;no date resampling for B feasibility or outcomes',
 'condition_assignment':'coverage design target5 statically compatible and5 constraint/service-risk challenges;compatible count=min(5,input-opportunity dates);remaining dates challenges;not population frequency or human label balance',
 'compatible_levels':{'shift_min':[30,60],'ac_increase_C':[1.]},
 'challenge_levels':{'program_minutes_past_deadline':[30,60],'AC_degrees_above_given_limit':[1.,2.],'EV_available_charging_minutes':[10,20],'WH_heating_target_C':[30.,35.]},
 'hard_gate':'world/bindings/common demands/state/prefix/integer clocks/physical object integrity;Bdeadline and AC reference bound conflicts retained as annotations',
 'risk_gate':'EV energy-window and WH heating-target mismatch annotated;actual SOC/temperature read back;not pre-labelled physical failure',
 'event_rule':'60min designed event tied to fixed A opportunity;fallback existing AC request at18:30;notice60min earlier;EBmock.5kW goal;not measured China dispatch',
 'B_selection':'least-used representable family within each condition,SHA tie-break;no EP result or human response consulted',
 'A_rule':'same source/designed demands and activity;common WH availability covers last immutable draw;no physical capacity or roster edits',
 'physics_scope':'counterfactual model preview conditional on requested temporal/thermal actions;not actual consent or execution',
 'human_labels':None,'human_answers':0,'collection_release':False,'training_release':False}

def finish(p,family,amount,asset,condition):
    p['B']['changed_controls']=[c for c in p['B']['controls'] if c not in p['A']['controls']]
    p['proposal']={'family':family,'amount':amount,'target_asset_id':asset,'origin':'predeclared V17 rule-generated research proposal,not agent LLM output',
                   'energy_cost_or_human_outputs_consulted':False,'LLM_call_occurred':False,'protocol_sha256':digest(PROTOCOL)}
    p['design_condition']=condition;p['decision_abs_min']=p['event_window_min'][0]-60
    p['constraint_assessment']=assess(p)
    return p

def challenges(w,date):
    base=op.baseline(w,date);out=[]
    for t in base['A']['tasks']:
        if t['start_min']>=1440 or t['kind'] not in ['washer','dishwasher']:continue
        linked=[x for x in base['A']['tasks'] if x['need_id'] in [t['need_id'],t['need_id']+':dry']]
        needs={n['need_id']:n for n in base['needs_A']};last=max(linked,key=lambda x:x['end_min'])
        for late in [30,60]:
            q=copy.deepcopy(base);delta=needs[last['need_id']]['deadline_min']+late-last['end_min']
            for x in q['B']['tasks']:
                if x['need_id'] in [z['need_id'] for z in linked]:x['start_min']+=delta;x['end_min']+=delta
            E=t['start_min']//30*30;q['event_window_min']=[E,E+60]
            q=finish(q,'program_deadline_overrun',late,t['asset_id'],'constraint_challenge')
            if not q['constraint_assessment']['integrity_errors']:out.append(q)
    devices={d['asset_id']:d for d in w['parameter_pack']['devices']}
    for c in base['A']['controls']:
        if c['start_min']>=1440:continue
        E=c['start_min']//30*30
        if c['kind']=='ac_setpoint':
            for excess in [1.,2.]:
                q=copy.deepcopy(base);q['event_window_min']=[E,E+60];changed=[]
                for z in q['B']['controls']:
                    lo,hi=max(E,z['start_min']),min(E+60,z['end_min'])
                    if z['kind']!='ac_setpoint' or lo>=hi:changed.append(z);continue
                    if z['start_min']<lo:changed.append({**z,'end_min':lo})
                    changed.append({**z,'start_min':lo,'end_min':hi,'value_C':devices[z['asset_id']]['reference_upper_setpoint_C']+excess})
                    if hi<z['end_min']:changed.append({**z,'start_min':hi})
                q['B']['controls']=changed;q=finish(q,'ac_above_given_limit',excess,c['asset_id'],'constraint_challenge')
                if not q['constraint_assessment']['integrity_errors']:out.append(q)
        elif c['kind']=='ev_charge_window':
            for duration in [10,20]:
                q=copy.deepcopy(base);q['event_window_min']=[E,E+60]
                for z in q['B']['controls']:
                    if z==c:z['start_min']=z['end_min']-duration
                q=finish(q,'ev_short_charge_window',duration,c['asset_id'],'service_risk_challenge')
                if not q['constraint_assessment']['integrity_errors']:out.append(q)
        elif c['kind']=='tank_setpoint':
            for target in [30.,35.]:
                q=copy.deepcopy(base);q['event_window_min']=[E,E+60]
                for z in q['B']['controls']:
                    if z==c:z['value_C']=target
                q=finish(q,'hotwater_low_heat_target',target,c['asset_id'],'service_risk_challenge')
                if not q['constraint_assessment']['integrity_errors']:out.append(q)
    if not out:
        # An inactive existing AC can be requested; no appliance or need is invented.
        ac=next(d for d in devices.values() if 'ac' in d['types'])
        q=copy.deepcopy(base);q['event_window_min']=[1110,1170]
        q['B']['controls'].append({'asset_id':ac['asset_id'],'kind':'ac_setpoint','start_min':1110,'end_min':1170,'value_C':ac['reference_upper_setpoint_C']+1.})
        q=finish(q,'ac_request_when_A_inactive',1.,ac['asset_id'],'constraint_challenge')
        assert not q['constraint_assessment']['integrity_errors'],q['constraint_assessment'];out.append(q)
    return out

def one(h):
    w=read(SRC/h['world_path']);source_sha=sha(SRC/h['world_path']);w['source_V16_world_file_sha256']=source_sha
    if w['assets']['water_heater']['present']:
        before=w['routine']['tank_heat_window_min'][1];end=max(before,w['routine']['bath_start_min']+10*w['N'])
        w['routine']['tank_heat_window_min'][1]=end
        w['parameter_pack']['control_defaults']['water_heater']['pre_heat_window_end_h']=end/60
        w['assets']['water_heater']['config']['pre_heat_window_end_h']=end/60
        w['reference_change_ledger'].append({'field':'reference_WH_heat_end_min','before':before,'after':end,'rule':'common needs-first availability;physical tank/power/demand unchanged'})
    w['parameter_pack_sha256']=digest(w['parameter_pack']);w['protocol_sha256']=digest(PROTOCOL)
    w['world_content_sha256']=digest({k:v for k,v in w.items() if k!='world_content_sha256'})
    weather=op.weather_lookup(h['weather']['path']);goods={}
    for i,row in enumerate(h['rounds']):
        date=dt.date.fromisoformat(row['date']);goods[i]=op.candidates(w,date,weather)
    eligible=[i for i,v in goods.items() if v];compatible=set(sorted(eligible,key=lambda i:rank('v17-condition',w['household_id'],h['rounds'][i]['date']))[:5])
    save(OUT/'worlds'/f'{w["household_id"]}.json',w);save(OUT/'actors'/f'{w["household_id"]}.json',project(w,read(SRC/'actors'/f'{w["household_id"]}.json')))
    usage=collections.Counter();records=[]
    for i,row in enumerate(h['rounds']):
        date=dt.date.fromisoformat(row['date']);qs=goods[i] if i in compatible else challenges(w,date)
        assert qs,(w['household_id'],date)
        q=copy.deepcopy(min(qs,key=lambda x:(usage[x['proposal']['family']],rank('v17-B',x['case_id'],x['proposal']['family'],x['proposal']['amount'],x['proposal']['target_asset_id']))))
        family=q['proposal']['family'];usage[family]+=1
        if i in compatible:q=finish(q,family,q['proposal']['amount'],q['proposal']['target_asset_id'],'statically_compatible')
        q['round_index']=i+1;q['date_selection']=copy.deepcopy(w['random10_date_selection']['dates'][i])
        q['constraint_assessment']=assess(q)
        assert not q['constraint_assessment']['integrity_errors'],q['constraint_assessment']
        assert (not q['constraint_assessment']['constraint_or_service_risk_flags'])==(i in compatible)
        assert q['A']!=q['B'];path=OUT/'pairs'/w['household_id']/f'{i+1:02d}.json';save(path,q)
        records.append({'round_index':i+1,'date':str(date),'pair_path':str(path.relative_to(OUT)),'pair_sha256':sha(path),'proposal_family':family,'design_condition':q['design_condition'],'event_window_min':q['event_window_min']})
    return {**h,'world_path':f'worlds/{w["household_id"]}.json','world_sha256':sha(OUT/'worlds'/f'{w["household_id"]}.json'),'parameter_pack_sha256':w['parameter_pack_sha256'],'rounds':records,'compatible_input_dates':len(eligible),'compatible_rounds':len(compatible),'K':len({k for d in w['parameter_pack']['devices'] for k in d['types']})}

if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--scope',choices=['selected50','full1000-static'],default='selected50');args=parser.parse_args()
    assert sys.platform=='linux' and not (OUT/'SELECTION50.json').exists() and not (OUT/'SELECTION1000.json').exists()
    save(OUT/'PROTOCOL.json',PROTOCOL)
    if args.scope=='selected50':rows=read(BASE/'pilot50_frontend_20261007_v1/SELECTION50.json')['records']
    else:
        ps={x['household_id']:x['records'] for x in read(SRC/'PAIR_BINDINGS10000.json')['households']}
        rows=[{**h,'rounds':ps[h['household_id']]} for h in read(SRC/'WORLD_BINDINGS1000.json')['records']]
    with concurrent.futures.ProcessPoolExecutor(max_workers=16) as pool:results=list(pool.map(one,rows))
    selection={'households':len(results),'pairs':10*len(results),'records':results,'source_dates':'original V16 frozenquarter-random dates;unchanged','scope':args.scope}
    file='SELECTION50.json' if args.scope=='selected50' else 'SELECTION1000.json';save(OUT/file,selection)
    save(OUT/'EXECUTION_AUTHORIZATION.json',{'user_instruction':'修改；好数据与不满足的坏数据都要','scope':'mixed-proposal shared generator;EP selected50only','selection_sha256':sha(OUT/file),'EP_scope_hold_lifted_for_selected50':args.scope=='selected50','full1000_EP_authorized':False,'human_collection_release':False,'training_release':False})
    print({'households':len(results),'pairs':10*len(results),'compatible':sum(h['compatible_rounds'] for h in results),'challenge':sum(10-h['compatible_rounds'] for h in results),'no_human_or_EP_result_selection':True},flush=True)
