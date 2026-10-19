"""Independent literal audit: all eligible requests, not only selected successes.

Imports no collection generator, admission classifier or scheduling validator.
The shared, unchanged literal patch operator materializes A/B; ordering, resource,
capability and connection checks below do not call the generation validators.
"""
import argparse
from collections import Counter,defaultdict
from pathlib import Path
from benchmark.ab_generation.common import read,save,verify
from benchmark.ab_generation.model import apply


def literal_errors(c,b,needs):
    errors=set();a=c['A'];changed=set();changed_needs=set(needs)
    for key,ident in [('tasks','task_id'),('operations','operation_id')]:
        before={r[ident]:r for r in a[key]};after={r[ident]:r for r in b[key]}
        if set(before)!=set(after) or len(after)!=len(b[key]):errors.add('ROW_IDENTITY_CHANGED')
        for rid in before.keys() & after.keys():
            old,new=before[rid],after[rid]
            if old!=new:
                changed.add((key,rid));changed_needs.add(new['need_id'])
                if min(old['start_min'],new['start_min'])<c['decision_min']:errors.add('PAST_CHANGED')
                if old['end_min']-old['start_min']!=new['end_min']-new['start_min']:errors.add('DURATION_CHANGED')
                if {k:v for k,v in old.items() if k not in ('start_min','end_min')}!={k:v for k,v in new.items() if k not in ('start_min','end_min')}:
                    errors.add('RESOURCE_OR_PROGRAM_CHANGED')
    while True:
        enlarged=changed_needs|{t['need_id'] for t in b['tasks'] if t.get('depends_on_need_id') in changed_needs}
        if enlarged==changed_needs:break
        changed_needs=enlarged
    jobs=defaultdict(list);handling=defaultdict(list);contracts={n['need_id']:n for n in c['needs']}
    for t in b['tasks']:jobs[t['need_id']].append(t)
    for o in b['operations']:handling[o['need_id']].append(o)
    for nid in changed_needs:
        if nid.endswith(':dry') and nid[:-4] in handling:continue
        tasks=jobs[nid]+jobs[nid+':dry']
        if not tasks:continue
        load=[o for o in handling[nid] if o['kind']=='load'];unload=[o for o in handling[nid] if o['kind']=='unload']
        if len(load)!=1 or len(unload)!=1:errors.add('HANDLING_CHAIN_MISSING');continue
        lo,hi=min(t['start_min'] for t in tasks),max(t['end_min'] for t in tasks)
        if load[0]['end_min']>lo:errors.add('RUN_BEFORE_LOADED')
        if unload[0]['start_min']<hi:errors.add('TAKEN_OUT_BEFORE_FINISHED')
        n=contracts[nid]
        if load[0]['start_min']<n['release_min']:errors.add('MATERIAL_NOT_READY')
        if n.get('timer_allowed') is False and load[0]['end_min']!=lo:errors.add('UNSUPPORTED_TIMER')
        for t in tasks:
            parent=t.get('depends_on_need_id')
            if parent:
                retrieved=[o for o in handling[parent] if o['kind']=='unload']
                if len(retrieved)!=1 or retrieved[0]['end_min']>load[0]['start_min']:errors.add('DRYER_BEFORE_PARENT_RETRIEVED')
        original=sorted((t for t in a['tasks'] if t['need_id'] in (nid,nid+':dry')),key=lambda t:(t['start_min'],t['end_min'],t['task_id']))
        if [t['task_id'] for t in original]!=[t['task_id'] for t in sorted(tasks,key=lambda t:(t['start_min'],t['end_min'],t['task_id']))]:
            errors.add('PROGRAM_SEQUENCE_CHANGED')
    grouped=defaultdict(list)
    for t in b['tasks']:grouped[t['asset_id']].append(t)
    for group in grouped.values():
        active=[]
        for t in sorted(group,key=lambda t:t['start_min']):
            active=[p for p in active if p['end_min']>t['start_min']]
            if any(('tasks',t['task_id']) in changed or ('tasks',p['task_id']) in changed for p in active):errors.add('MACHINE_RUNS_TWO_PROGRAMS')
            active.append(t)
    holds=defaultdict(list)
    for nid,ops in handling.items():
        load=[o for o in ops if o['kind']=='load'];unload=[o for o in ops if o['kind']=='unload']
        if len(load)==len(unload)==1:
            holds[load[0]['asset_id']].append((load[0]['start_min'],unload[0]['end_min'],nid))
    for group in holds.values():
        active=[]
        for lo,hi,nid in sorted(group):
            active=[p for p in active if p[1]>lo]
            if any(nid in changed_needs or p[2] in changed_needs for p in active):errors.add('MACHINE_LOADED_WITH_TWO_BATCHES')
            active.append((lo,hi,nid))
    devices={d['asset_id']:d for d in c['devices']}
    ev_a=defaultdict(list);ev_b=defaultdict(list)
    for target,plan in [(ev_a,a),(ev_b,b)]:
        for r in plan['controls']:
            if r['kind']=='ev_charge_window':target[(r['asset_id'],r['need_id'])].append(r)
    for r in b['controls']:
        if r['kind']=='ev_charge_window':
            key=(r['asset_id'],r['need_id'])
            if ev_a[key]==ev_b[key] and (r['end_min']<=c['horizon_min'][0] or r['start_min']>=c['horizon_min'][1]):continue
            ops=handling[r['need_id']]
            plugs=[o for o in ops if o['kind']=='EV_plug'];unplugs=[o for o in ops if o['kind']=='EV_unplug']
            if len(plugs)!=1 or len(unplugs)!=1 or r['start_min']<plugs[0]['end_min'] or r['end_min']>unplugs[0]['start_min']:
                errors.add('EV_WITHOUT_CONNECTION')
        elif r['kind']=='ac_setpoint':
            h,k=r['heating_setpoint_C'],r['cooling_setpoint_C']
            if h>=k or not 5<=h<=35 or not 15<=k<=40:errors.add('INVALID_AC_CONTROL')
        elif r['kind']=='tank_setpoint':
            if not 10<=r['value_C']<=devices[r['asset_id']]['parameters']['maximum_C']:errors.add('INVALID_TANK_CONTROL')
    if any(r['end_min']<=r['start_min'] for rows in b.values() for r in rows):errors.add('INVALID_INTERVAL')
    return sorted(errors)


def audit(root):
    root=Path(root);verify(root);selected=set(read(root/'ASSIGNMENT.json')['selected_ids'])
    ordinary=0;engineering=0;failures=[];reasons=Counter();selected_issues=Counter();seen=set();daily=[]
    for p in sorted((root/'catalogues').glob('*.json.gz')):
        d=read(p);c=read(root/'contexts'/p.name);controls=0
        # Materialize every ordinary candidate against untrimmed full A.
        # This intentionally audits unselected and service-conflicting requests.
        for row in d['rows']:
            ordinary+=1;seen.add(row['id']);b=apply(c['A'],row['patches'])
            bad=literal_errors(c,b,row['program_needs'])
            if row.get('engineering_issues'):bad.append('ENGINEERING_LABEL_IN_ORDINARY_POOL')
            if row['actual_outcomes'] is not None or row['human_acceptance'] is not None:bad.append('OUTCOME_INVENTED')
            if bad:failures.append({'id':row['id'],'errors':bad})
            if row['features']['device_count']=='0':controls+=1
            if row['id'] in selected:selected_issues.update(row['issues'])
        if controls and len(d['rows'])!=1:failures.append({'case_id':c['case_id'],'errors':['CONTROL_WITH_AVAILABLE_CHANGE']})
        for r in d['engineering_diagnostics']:
            engineering+=1;reasons.update(r['engineering_issues'])
            if r['repaired'] or r['replacement_generated']:failures.append({'case_id':c['case_id'],'errors':['ENGINEERING_REQUEST_REPAIRED_OR_REPLACED']})
        if not d['no_retries_or_replacements']:failures.append({'case_id':c['case_id'],'errors':['RETRY_POLICY_CHANGED']})
        daily.append({'case_id':c['case_id'],'eligible':len(d['rows']),'engineering':len(d['engineering_diagnostics']),'fallback':bool(controls)})
    if selected-seen:failures.append({'errors':['SELECTION_OUTSIDE_ELIGIBLE_CATALOGUE']})
    return {'schema':'eb.collection.independent_logic.v2','passed':not failures,'eligible_requests_checked':ordinary,
        'engineering_requests_retained':engineering,'engineering_reasons':dict(reasons),
        'selected':len(selected),'selected_service_issues':dict(selected_issues),'failures':failures,'days':daily,
        'new_engine_runs':0,'outcomes_used':False,'category_proportions_prescribed':False}


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--root',required=True);p.add_argument('--out',required=True);a=p.parse_args()
    result=audit(a.root);save(a.out,result);print({k:v for k,v in result.items() if k not in ('days','failures')})
    if not result['passed']:raise SystemExit(1)
