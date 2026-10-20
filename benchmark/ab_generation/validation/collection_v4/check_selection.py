"""Read back policy arithmetic and literal catalogue provenance; no engine."""
import argparse
from collections import Counter,defaultdict
from pathlib import Path
from benchmark.ab_generation.common import read,save,verify,sha


def check(root,out):
    root=Path(root);verify(root);assignment=read(root/'ASSIGNMENT.json');policy=assignment['selection_policy']
    rows={}
    for path in sorted((root/'catalogues').glob('*.json.gz')):
        for row in read(path)['rows']:rows[row['id']]=row
    selected=[rows[i] for i in assignment['selected_ids']];dated=Counter((r['household_id'],r['date']) for r in selected)
    households=sorted({r['household_id'] for r in rows.values()})
    assert len(selected)==10*len(households) and all(v==1 for v in dated.values())
    assert all(sum(h==hid for h,_ in dated)==10 for hid in households)
    assert all(not r['engineering_issues'] and r['event_relevance']['passed'] for r in selected)
    assert all(r['actual_outcomes'] is None and r['human_acceptance'] is None and not r['actual_results_used_for_selection'] for r in rows.values())
    exposure={h:Counter() for h in households};sizes=Counter();admissions=Counter();known=Counter()
    detail_budget=defaultdict(float);budgets=defaultdict(float)
    for g in assignment['coverage']:
        budgets[(g['household'],g['budget'])]+=g['weight']
        if g['budget']=='batch_device_details':detail_budget[g['tag'].split('.')[1]]+=g['weight']
        assert not any(x in g['tag'] for x in ('amplitude=','admission=','actual_outcome','human_acceptance'))
    for amount in detail_budget.values():assert abs(amount-policy['batch_device_detail_budget']/len(detail_budget))<1e-9
    for r in selected:
        roots=[c for c in r['components'] if c['event_relevance']['role']=='direct_event_request']
        services={(c['asset_id'],c.get('service_need_id')) if c['family'] in ('washer','dryer','dishwasher','ev')
                  else (c['asset_id'],None) for c in roots}
        exposure[r['household_id']].update({c['family'] for c in roots});sizes[len(services)]+=1
        admissions[r['features']['admission']]+=1
        x=r['known_event_reduction_kWh'];known['reduction' if x>1e-9 else 'increase' if x<-1e-9 else 'zero']+=1
        pair=read(root/'pairs'/(r['id']+'.json'));assert pair['row']==r and pair['review']['passed']
    assert {h:dict(v) for h,v in exposure.items()}==assignment['family_exposure']
    expected_family_cost=sum(policy['household_family_repeat_weight']*sum(n*(n-1)/2 for n in counts.values())/(45*len({c['family'] for r in rows.values() if r['household_id']==h for c in r['components'] if c['event_relevance']['role']=='direct_event_request'})) for h,counts in exposure.items() if counts)
    expected_semantic_cost=policy['household_semantic_repeat_weight']*assignment['near_duplicate_excess']/9
    expected_composition_cost=policy['household_composition_repeat_weight']*assignment['composition_repeat_excess']/9
    cost=expected_family_cost+expected_semantic_cost+expected_composition_cost
    assert abs(cost-assignment['solver']['primary_repeat_cost'])<1e-6
    assert abs(assignment['weighted_deficits']+cost-assignment['solver']['coverage']['objective'])<1e-6
    result={'passed':True,'households':len(households),'cases':len(selected),'catalogue_unique':len(rows),
            'root_services_selected':dict(sizes),'admissions_selected':dict(admissions),'known_plan_event_selected':dict(known),
            'family_exposure':{h:dict(v) for h,v in exposure.items()},'equal_batch_device_budgets':dict(detail_budget),
            'required_deficits':assignment['required_deficits'],'near_duplicate_excess':assignment['near_duplicate_excess'],
            'repeat_cost_independent_readback':cost,'composition_repeat_excess':assignment['composition_repeat_excess'],
            'assignment_sha256':sha(root/'ASSIGNMENT.json'),'new_engine_runs':0,'population_or_human_validity_claim':False}
    save(out,result);return result


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--root',required=True);p.add_argument('--out',required=True);a=p.parse_args();print(check(a.root,a.out))
