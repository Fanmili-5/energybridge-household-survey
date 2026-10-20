"""Audit literal selected plans without importing the collection generator."""
import argparse
from collections import Counter
from pathlib import Path
from benchmark.ab_generation.common import read,save,verify


def state(plan,aid,key,t):
    rows=[r for r in plan['controls'] if r['asset_id']==aid and r['start_min']<=t<r['end_min'] and key in r]
    if len(rows)!=1:raise ValueError('AMBIGUOUS_LITERAL_CONTROL_STATE')
    return rows[0][key]


def audit(root):
    if read(Path(root)/'DESIGN.json')['schema']=='eb.collection.design.v3':
        from benchmark.ab_generation.validation.collection_v3.independent_semantics import audit as command_audit
        return command_audit(root)
    root=Path(root);verify(root);selected=read(root/'ASSIGNMENT.json')['selected_ids'];records=[]
    for ident in selected:
        pair=read(root/'pairs'/(ident+'.json'));row=pair['row'];a,b=pair['A'],pair['B']
        c=read(root/'contexts'/(row['case_id']+'.json.gz'));problems=[];levels=[]
        before={o['operation_id']:o for o in a['operations']}
        for op in b['operations']:
            if op==before[op['operation_id']]:continue
            if op['operator_id'] in c['authority']['immutable_operator_ids']:
                problems.append('IMMUTABLE_OTHER_HOUSEHOLD_OPERATOR_MOVED')
            if op['operator_id'] not in c['authority']['assets'][op['asset_id']]['authorized_operator_ids']:
                problems.append('UNAUTHORIZED_OPERATOR')
        for component in row['components']:
            m=component['magnitude'];family=component['family'];aid=component['asset_id']
            if family in ('washer','dishwasher','dryer'):
                ids={component['service_need_id']}
                while True:
                    more=ids|{t['need_id'] for t in a['tasks'] if t.get('depends_on_need_id') in ids}
                    more|={t['need_id'] for t in a['tasks'] if t['need_id']==component['service_need_id']+':dry' and t['asset_id']==aid}
                    if more==ids:break
                    ids=more
                tasks={t['task_id']:t for t in a['tasks'] if t['need_id'] in ids}
                machine=max(abs(t['start_min']-tasks[t['task_id']]['start_min']) for t in b['tasks'] if t['task_id'] in tasks)
                handling=[abs(o['start_min']-before[o['operation_id']]['start_min']) for o in b['operations'] if o['need_id'] in ids]
                if (machine,sum(handling),max(handling,default=0))!=(m['machine_shift_min'],m['manual_total_shift_min'],m['manual_max_shift_min']):
                    problems.append('PROGRAM_MAGNITUDE_MISMATCH')
                value=max(machine,max(handling,default=0))
                level='small' if value<=30 else 'medium' if value<90 else 'large'
            elif family=='ev':
                pauses=[p for p in row['patches'] if p['type']=='control_pause' and p['asset_id']==aid and p['need_id']==component['service_need_id']]
                if len(pauses)!=1:raise ValueError('EV_PAUSE_IDENTITY_MISMATCH')
                pause=pauses[0]['end_min']-pauses[0]['start_min']
                if pause!=m['pause_min']:problems.append('EV_REQUEST_MAGNITUDE_MISMATCH')
                nid=component['service_need_id']
                original=[w for w in a['controls'] if w['asset_id']==aid and w['kind']=='ev_charge_window' and w['need_id']==nid]
                windows=[w for w in b['controls'] if w['asset_id']==aid and w['kind']=='ev_charge_window' and w['need_id']==nid]
                steps=[s for s in c['reference']['ev_charging_steps'] if s['need_id']==nid and s['start_min']>=c['decision_min']]
                remaining=sum(s['grid_kWh'] for s in steps)
                anchor=min(s['start_min'] for s in steps);connection_end=max(w['end_min'] for w in original)
                end=min(c['horizon_min'][1],connection_end)
                rating=next(d['parameters']['charger_kw'] for d in c['devices'] if d['asset_id']==aid)
                finish=pauses[0]['end_min']
                for t in range(anchor,end,10):
                    if remaining<=1e-10:break
                    if any(w['start_min']<=t and t+10<=w['end_min'] for w in windows):
                        remaining-=min(rating/6,remaining);finish=t+10
                slack=connection_end-finish
                if abs(slack-m['service_slack_min'])>1e-9 or abs(max(0,remaining)-m['energy_shortfall_kWh'])>1e-8:
                    problems.append('EV_SLACK_OR_ENERGY_SHORTFALL_MISMATCH')
                if m.get('observation_slack_min')!=end-finish:
                    problems.append('EV_OBSERVATION_HORIZON_CONFUSED_WITH_DEPARTURE')
                level='large' if slack<30 or pause>=180 else 'small' if pause<=30 else 'medium'
            else:
                key=m['axis']+'_setpoint_C' if family=='ac' else 'value_C'
                differences=[abs(state(b,aid,key,t)-state(a,aid,key,t)) for t in range(1080,1140,10)]
                value=max(differences)
                if abs(value-m['service_delta_C'])>1e-9 or 10*sum(x>1e-9 for x in differences)!=m['duration_min']:
                    problems.append('THERMAL_REQUEST_MAGNITUDE_MISMATCH')
                changes=[abs(state(b,aid,key,t)-state(a,aid,key,t)) for t in range(c['decision_min'],c['horizon_min'][1],10)]
                if abs(max(changes)-m['actual_max_command_delta_C'])>1e-9:
                    problems.append('THERMAL_ACTUAL_COMMAND_DELTA_MISMATCH')
                low,mid=(0.5,1) if family=='ac' else (1,3)
                level='small' if value<=low else 'medium' if value<=mid else 'large'
            if level!=component['absolute_level']:problems.append('COMPONENT_INTENSITY_MISMATCH')
            levels.append(level)
        expected='none' if not levels else levels[0] if len(set(levels))==1 else 'mixed'
        if expected!=row['features']['intensity']:problems.append('JOINT_INTENSITY_MISMATCH')
        if row['actual_outcomes'] is not None or row['human_acceptance'] is not None:
            problems.append('INVENTED_OUTCOME')
        records.append({'id':ident,'passed':not problems,'failed_checks':sorted(set(problems))})
    return {'schema':'eb.collection.independent_review.v1','passed':all(r['passed'] for r in records),
        'selected':len(records),'records':records,'new_engine_runs':0,
        'checks':'literal_A_B_operations_and_temperature_commands;independently_recomputed_dose_labels;not_physical_outcomes'}


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--root',required=True);p.add_argument('--out',required=True);a=p.parse_args()
    result=audit(a.root);save(a.out,result)
    print({k:v for k,v in result.items() if k!='records'})
    if not result['passed']:raise SystemExit(1)


if __name__=='__main__':main()
