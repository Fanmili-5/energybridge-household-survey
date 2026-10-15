"""Regenerate B from frozen A with an operative path; no actor answers."""
import collections,concurrent.futures,copy,datetime as dt
from common import *
from contrast_core import metrics,invariant_errors
from decision_contrast import baseline_context,source_evidence,energy
from generate import candidates,finish
from zone_controls import repair_legacy,change_room,validate_plan,groups
from execution import post_operation_care
from plans import reserve
from type_model import permission_audit
PARENT=BASE/'contrast_repair_v29_20261015'
SOURCE_B=BASE/'formal50_950_production_v28_20261014'

def extra_candidates(w,base,context):
    out=[];lo,hi=base['primary_evaluation_min'];done=set()
    for c in base['A']['controls']:
        aid=c['asset_id'];kind=c['kind'];event=max(540,c['start_min'])
        if c['end_min']<=event or event>=hi-20:continue
        if kind=='ac_setpoint':
            room=next(d['room_id']for d in w['parameter_pack']['devices']if d['asset_id']==aid)
            if aid!=groups(w)[room][0]or room in done:continue
            keys={f'V16_AC_{i}_COIL'for i,d in enumerate(w['parameter_pack']['devices'])if 'ac'in d['types']and d['room_id']==room}
            starts=[t for t in range(event,min(c['end_min'],hi)-29,10)if energy(context,'Cooling Coil Electricity Energy',t,min(t+60,c['end_min']),keys)>=.1]
            if not starts:continue
            event=starts[0];done.add(room)
            for delta in (2.,4.):
                q=copy.deepcopy(base);aids=change_room(q,aid,event,event+60,increase=delta)
                group='inconvenient_but_doable'if delta<=w['role_policy']['thermal']['temporary_increase_C']else'constraint_challenge'
                out.append(finish(q,group,'active_shared_zone_AC_request',delta,aids,event,
                    'shared zone controller;frozen A cooling is active;larger or out-of-bound system requests remain actor-evaluated'))
        elif kind=='ev_charge_window'and c['start_min']>=lo:
            for mode in ('delay60','short10'):
                q=copy.deepcopy(base);z=next(x for x in q['B']['controls']if x==c)
                if mode=='delay60':z['start_min']+=60
                else:z['end_min']=z['start_min']+10
                if z['start_min']>=z['end_min']:continue
                out.append(finish(q,'inconvenient_but_doable'if mode=='delay60'else'service_risk',
                    'EV_active_charge_delay'if mode=='delay60'else'EV_insufficient_charge_request',60 if mode=='delay60'else 10,[aid],event,
                    'actual reference charge trajectory must change;trip and access target retained;target failure is not automatic rejection'))
    ev=next((d for d in w['parameter_pack']['devices']if 'ev'in d['types']),None)
    if ev:
        q=copy.deepcopy(base);nid=q['date']+':additional_EV_handling_request';operator=ev['operator_id']
        try:
            plug=reserve(q['B']['operations'],q['world']['operator_windows'],'EV_plug',nid,lo+60,hi-80,1140,operator)
            unplug=reserve(q['B']['operations'],q['world']['operator_windows'],'EV_unplug',nid,plug['end_min']+40,hi-10,plug['end_min']+40,operator)
            if not any(x['asset_id']==ev['asset_id']and overlap((x['start_min'],x['end_min']),(plug['end_min'],unplug['start_min']))for x in q['A']['controls']):
                q['B']['controls'].append({'asset_id':ev['asset_id'],'kind':'ev_charge_window','start_min':plug['end_min'],'end_min':unplug['start_min']})
            q=finish(q,'negotiation','additional_EV_handling_request',20,[ev['asset_id']],plug['start_min'],
                'system asks two additional concrete site actions;no new mandatory trip or presumed need;execution and resource burden exposed')
            q['proposal']['additional_request_need_ids']=[nid];q['proposal']['additional_manual_request_is_given_not_observed']=True;out.append(q)
        except ValueError:pass
    return out

def repair_household(h):
    w=read(OUT/h['world_path']);updated=copy.deepcopy(h);records=[]
    for rr in updated['rounds']:
        old=read(PARENT/rr['pair_path']);source=read(SOURCE_B/rr['pair_path']);context=baseline_context(h,rr)
        base=copy.deepcopy(old);base['B']=copy.deepcopy(base['A']);base.pop('pair_content_sha256',None)
        pool=[repair_legacy(w,source)]
        for p in candidates(w,base):
            try:pool.append(repair_legacy(w,p))
            except ValueError:continue
        pool+=extra_candidates(w,base,context)
        admitted=[]
        for q in pool:
            q['B']['changed_controls']=[c for c in q['B']['controls']if c not in q['A']['controls']]
            from checks import assess
            q['constraint_assessment']=assess(q)
            if q['constraint_assessment']['integrity_errors']or not metrics(q)['admitted']:continue
            try:validate_plan(w,q['A']);validate_plan(w,q['B'])
            except ValueError:continue
            evidence,a,b=source_evidence(w,q,context)
            if evidence['passed']:admitted.append((q,evidence,a,b))
        if not admitted:raise RuntimeError('NO_DECISION_RELEVANT_REQUEST_WITH_FROZEN_WORLD:'+old['case_id'])
        def ordering(item):
            q=item[0];return(q['proposal']['family']=='additional_EV_handling_request',
                q['design_condition']!=source['design_condition'],q['proposal']['family']!=source['proposal']['family'],
                len(q['proposal']['target_asset_ids']),rank(q['case_id'],q['proposal'],'v30-source-selection'))
        q,evidence,a,b=min(admitted,key=ordering)
        q['coverage_assignment']={**source.get('coverage_assignment',{}),'desired_mechanism':source['design_condition'],
            'realized_mechanism':q['design_condition'],'applicable_operative_candidates':len(admitted),
            'unavailable_design_level_not_new_assets_or_dates':not any(x[0]['design_condition']==source['design_condition']for x in admitted)}
        q['proposal'].update(A_physical_context_used=True,B_consequences_consulted=False,human_outputs_consulted=False)
        q['service_execution_reference']={'A':a,'B':b};q['decision_contrast_source']=evidence;q['post_operation_care']={}
        for side,ex in (('A',a),('B',b)):
            executed={**q[side],'operations':ex['physical_visit_operations']}
            gaps=post_operation_care(w,dt.date.fromisoformat(q['date']),executed,q['common_A_departure_care_bookings'],3)
            q['post_operation_care'][side]=gaps
            if gaps:q['constraint_assessment']['constraint_flags'][side].append('POST_OPERATION_ADULT_PRESENCE_CONTRACT')
        q['policy_assessment']=permission_audit(w,q);q['source_rules_sha256']=sha(Path(__file__))
        q['contrast_repair']={'schema':'eb.substantive_source_repair.v30','old_pair_sha256':sha(PARENT/rr['pair_path']),
            'original_V28_proposal':source['proposal'],'A_reference_trace_used':True,'B_EP_used_for_selection':False,
            'household_policy_needs_A_and_devices_changed':False,'human_answer_generated':False}
        q.pop('pair_content_sha256',None);q['pair_content_sha256']=digest(q)
        errors=invariant_errors(q,old,w,h['world_sha256'])
        if errors:raise RuntimeError((q['case_id'],errors))
        save(OUT/rr['pair_path'],q);rr['pair_sha256']=sha(OUT/rr['pair_path'])
        records.append({'case_id':q['case_id'],'household_id':h['household_id'],'round_index':rr['round_index'],
            'pair_sha256':rr['pair_sha256'],'proposal':q['proposal'],'source_decision_paths':evidence,
            'metrics':metrics(q),'old_pair_sha256':sha(PARENT/rr['pair_path'])})
    return updated,records

def run(scope):
    school_guard()
    if scope=='formal950':
        from cohort_gate import require_original50_acceptance
        require_original50_acceptance()
    ids=set(read(OUT/'PARTITIONS.json')[scope]);selection=read(OUT/'SELECTION1000.json');jobs=[h for h in selection['records']if h['household_id']in ids]
    replacements={};records=[]
    with concurrent.futures.ProcessPoolExecutor(max_workers=12)as pool:
        for h,rs in pool.map(repair_household,jobs,chunksize=1):
            replacements[h['household_id']]=h;records+=rs
            if len(replacements)%10==0:print({'source_households':len(replacements),'expected':len(jobs)},flush=True)
    selection['records']=[replacements.get(h['household_id'],h)for h in selection['records']];save(OUT/'SELECTION1000.json',selection)
    report={'schema':'eb.substantive_source_admission.v30','passed':True,'scope':scope,'cases':len(records),
        'changed_pairs':len(records),'changed_case_ids':[r['case_id']for r in records],
        'actual_mechanisms':dict(collections.Counter(r['proposal']['mechanism']for r in records)),
        'families':dict(collections.Counter(r['proposal']['family']for r in records)),
        'A_needs_household_policy_and_dates_unchanged':True,'B_EP_outcome_selection':False,'EP_started':False,'records':records}
    save(OUT/f'CONTRAST_{scope}_INPUT.json',report);print({k:v for k,v in report.items()if k not in ('records','changed_case_ids')},flush=True)
if __name__=='__main__':
    import argparse
    p=argparse.ArgumentParser();p.add_argument('--scope',choices=['formal50','formal950'],required=True);run(p.parse_args().scope)
