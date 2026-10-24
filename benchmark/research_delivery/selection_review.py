"""Same-catalogue weighted coverage and actual household block-order audit."""
import argparse
import statistics
from collections import Counter
from pathlib import Path
from benchmark.ab_generation.common import read,save,digest
from benchmark.ab_generation.unified.selection import concepts,goals,select_block


def run(out):
    out=Path(out);root=out/'fifty';rows=[]
    for s in read(root/'GENERATION.json'):rows.extend(read(root/s['path']).get('rows',[]))
    cfg=read(root/'PRE_GENERATION.json')['configuration'];views=[concepts(r) for r in rows]
    targets=goals(rows,views);total=sum(t['weight'] for t in targets)
    def measure(ids):
        ids=set(ids);covered=set();chosen=[]
        for r,v in zip(rows,views):
            if r['id'] not in ids:continue
            chosen.append(r)
            covered.update((r['household_id'],t) for t in v['tokens']);covered.update((None,t) for t in v['tokens'])
        return dict(selected=len(chosen),weighted_goal_fraction=sum(t['weight'] for t in targets if (t['household'],t['tag']) in covered)/total,
            semantic_repeat_excess=sum(n-1 for n in Counter((r['household_id'],concepts(r)['signature']) for r in chosen).values()),
            family_date_exposure=dict(Counter(f for r in chosen for f in concepts(r)['families'])))
    arms=[]
    for a in read(out/'selection-study/RESULTS.json'):arms.append(dict(arm=a['arm'],**measure(a['selected_ids'])))
    original=read(root/'SELECTION.json')['household_order'];order_arms=[]
    # Block size held at ten; reverse only the HOUSEHOLD processing order.
    # This differs from reversing input rows, which assign() canonicalizes.
    for name,homes in [('original',original),('reversed',list(reversed(original)))]:
        carry=set();ids=[];blocks=[]
        for start in range(0,len(homes),10):
            selected=select_block([r for r in rows if r['household_id'] in set(homes[start:start+10])],{**cfg,'block_households':10},carry)
            ids+=selected['selected_ids'];blocks.append(selected)
            for r in rows:
                if r['id'] in set(selected['selected_ids']):carry.update((None,t) for t in concepts(r)['tokens'])
        save(out/'selection-review'/('HOUSEHOLD_ORDER_'+name+'.json'),dict(order=homes,selected_ids=ids,blocks=blocks))
        order_arms.append(dict(order=name,**measure(ids)))
    ledger=read(root/'INPUT_OPPORTUNITY_COVERAGE.json.gz');available=Counter()
    for day in ledger:
        available.update({e['family'] for e in day['mechanisms'] if e['status']=='potential'})
    for a in arms+order_arms:
        a['exposure_per_input_potential_family_date']={f:n/available[f] if available[f] else None for f,n in a['family_date_exposure'].items()}
    result=dict(same_catalogue_arms=arms,household_order_arms=order_arms,available_family_dates=dict(available),
        measurement='weighted frozen selection goals,not raw descriptor count;potential is not joint feasibility',
        one_factor_order_change='block size ten fixed;only order reversed',
        seed=cfg['seed'],outcomes_or_acceptance_used=False)
    save(out/'SELECTION_REVIEW.json',result);return result


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--out',required=True);a=p.parse_args();print(run(a.out))
