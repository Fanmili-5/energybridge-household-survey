"""Repair source-defined subprecision proposals, without consulting EP outcomes."""
import collections,copy,datetime as dt,math
from common import *
from contrast_core import metrics,invariant_errors,PROTOCOL
from generate import candidates,finish,change_ac
from execution import realize,post_operation_care
from type_model import permission_audit

PARENT=BASE/'formal50_950_production_v28_20261014'

def normalized_candidates(w,old):
    base=copy.deepcopy(old);base['B']=copy.deepcopy(base['A']);out=[]
    for q in candidates(w,base):
        if q['proposal']['family']=='AC_control_tradeoff':
            event=q['event_window_min'][0];aid=q['proposal']['target_asset_ids'][0];bound=w['role_policy']['thermal']['temporary_increase_C']
            group=q['design_condition'];step=PROTOCOL['minimum_temperature_request_C']
            if group=='constraint_challenge':delta=math.ceil((bound+step)/step-1e-9)*step
            elif bound<step-1e-8:continue
            elif group=='near_boundary':delta=math.floor(bound/step+1e-9)*step
            else:delta=max(step,math.floor(bound/2/step+1e-9)*step)
            q=copy.deepcopy(base);c=next(c for c in q['A']['controls']if c['asset_id']==aid and c['kind']=='ac_setpoint'and overlap((c['start_min'],c['end_min']),(event,event+60)))
            change_ac(q,c,event,delta);q=finish(q,group,'AC_control_tradeoff',delta,[aid],event,'predeclared0.5C encoding grid within unchanged role bound;out-of-bound challenge remains explicit')
        if not q['constraint_assessment']['integrity_errors']and metrics(q)['admitted']:out.append(q)
    return out

def repair_one(w,old):
    before=metrics(old)
    if before['admitted']:return copy.deepcopy(old),False
    pool=normalized_candidates(w,old)
    same=[q for q in pool if q['design_condition']==old['design_condition']]
    pool=same or pool
    if not pool:raise RuntimeError('No source-coherent visible candidate;no household/need edits allowed:'+old['case_id'])
    def order(q):
        m=metrics(q)
        return(q['proposal']['family']!=old['proposal']['family'],len(q['proposal']['target_asset_ids']),
               len(permission_audit(w,q)['issues']),max(m['program_shifts_min']+[0]),rank(old['case_id'],q['proposal'],'v29-source-only-repair'))
    q=min(pool,key=order)
    q['coverage_assignment']={**old['coverage_assignment'],'realized_mechanism':q['design_condition'],
       'unavailable_design_level_not_new_assets_or_dates':not bool(same),'applicable_candidates':len(pool)}
    q['service_execution_reference']={s:realize(w,q[s],q['world']['operator_windows'],q['needs_A'])for s in('A','B')}
    for side in('A','B'):
        executed={**q[side],'operations':q['service_execution_reference'][side]['physical_visit_operations']}
        q['post_operation_care'][side]=post_operation_care(w,dt.date.fromisoformat(q['date']),executed,q['common_A_departure_care_bookings'],3)
        if q['post_operation_care'][side]:q['constraint_assessment']['constraint_flags'][side].append('POST_OPERATION_ADULT_PRESENCE_CONTRACT')
    q['policy_assessment']=permission_audit(w,q)
    q['contrast_repair']={'schema':'eb.source_only_repair.v29','old_pair_content_sha256':old['pair_content_sha256'],
      'old_proposal':old['proposal'],'source_rule':'subprecision input-only threshold,then predeclared valid candidate pool',
      'EP_outcomes_used_for_selection':False,'family_or_policy_changed':False,'protocol_sha256':digest(PROTOCOL)}
    q.pop('pair_content_sha256',None);q['pair_content_sha256']=digest(q)
    return q,True

def run(scope):
    school_guard();ids=set(read(OUT/'PARTITIONS.json')[scope]);selected=read(OUT/'SELECTION1000.json');old_selected={h['household_id']:h for h in read(PARENT/'SELECTION1000.json')['records']};changed=[];counts=collections.Counter();fail=[];evidence=[]
    for h in selected['records']:
        if h['household_id']not in ids:continue
        w=read(OUT/h['world_path']);oldh=old_selected[h['household_id']]
        for rr,oldrr in zip(h['rounds'],oldh['rounds']):
            original=read(PARENT/oldrr['pair_path']);q,did_change=repair_one(w,original)
            errors=invariant_errors(q,original,w,oldh['world_sha256'])
            if errors:fail.append({'case_id':q['case_id'],'errors':errors});continue
            if did_change:
                save(OUT/rr['pair_path'],q);rr['pair_sha256']=sha(OUT/rr['pair_path']);changed.append(q['case_id'])
            evidence.append({'case_id':q['case_id'],'household_id':h['household_id'],'round_index':rr['round_index'],'pair_sha256':rr['pair_sha256'],
                 'repaired':did_change,'before':metrics(original),'after':metrics(q),'old_pair_sha256':oldrr['pair_sha256'],'proposal':q['proposal']})
            counts[q['design_condition']]+=1
    if fail:save(OUT/f'CONTRAST_{scope}_INPUT_FAILURES.json',fail);raise RuntimeError(str(fail[:3]))
    save(OUT/'SELECTION1000.json',selected)
    report={'schema':'eb.contrast_cohort_input.v29','scope':scope,'passed':True,'cases':len(evidence),'changed_pairs':len(changed),'changed_case_ids':changed,
       'actual_mechanisms':dict(counts),'A_needs_household_policy_and_dates_unchanged':True,'no_EP_outcome_selection':True,'records':evidence,
       'protocol_sha256':digest(PROTOCOL),'EP_started':False}
    save(OUT/f'CONTRAST_{scope}_INPUT.json',report);print({k:v for k,v in report.items()if k not in('records','changed_case_ids')},flush=True)
    return report

if __name__=='__main__':
    import argparse
    p=argparse.ArgumentParser();p.add_argument('--scope',choices=['formal50','formal950'],required=True);a=p.parse_args();run(a.scope)
