"""Check proposed exclusions against a separate relaxed time-grid enumerator."""
from pathlib import Path
from collections import Counter
from benchmark.ab_generation.common import read, save
from benchmark.ab_generation.unified.service_bounds import event_exclusion
from .acceptance import record_sources


def enumerate_relaxed_earliest(c, nid, seen=frozenset()):
    if nid in seen:
        raise ValueError('CYCLE')
    need = next(n for n in c['needs'] if n['need_id'] == nid)
    stages = [t for t in c['A']['tasks'] if t['need_id'] == nid]
    asset = stages[0]['asset_id']
    stages += [t for t in c['A']['tasks'] if t['need_id']==nid+':dry' and t['asset_id']==asset]
    load = next(o for o in c['A']['operations'] if o['need_id']==nid and o['kind']=='load')
    unload = next(o for o in c['A']['operations'] if o['need_id']==nid and o['kind']=='unload')
    first, last = min(t['start_min'] for t in stages), max(t['end_min'] for t in stages)
    ld, ud = load['end_min']-load['start_min'], unload['end_min']-unload['start_min']
    parent_ids = {t['depends_on_need_id'] for t in stages if t.get('depends_on_need_id')}
    parents = [enumerate_relaxed_earliest(c, p, seen | {nid}) for p in parent_ids]
    if first < c['decision_min']:
        return first, unload['end_min'] if unload['start_min'] < c['decision_min'] else max(c['decision_min'], last)+ud
    if load['start_min'] < c['decision_min']:
        start = max(c['decision_min'], load['end_min'])
        return start, start+last-first+ud
    starts = []
    # Only original facts set this finite inspection horizon. Enumerate all
    # grid pairs, ignoring calendars/resources just as a relaxed proof requires.
    stop = max(c['horizon_min'][1], need['deadline_min'], last+ud)+1440
    for l in range(((max(c['decision_min'], need['release_min'])+9)//10)*10, stop, 10):
        if any(end > l for _,end in parents):
            continue
        for m in range(l+ld, stop, 10):
            starts.append(m)
    if not starts:
        raise ValueError('INSPECTION_HORIZON_INSUFFICIENT;NOT_INFEASIBILITY')
    start = min(starts)
    return start, start+last-first+ud


def run(source, out):
    source, out = Path(source), Path(out)
    _, contexts = record_sources(source/'public-new-A/collection')
    progress = read(source/'public-joint-gap-review/PROGRESS.json')
    records = []
    for slot in progress:
        c = read(contexts[(slot['household_id'], slot['date'])])
        for r in read(slot['path'])['records']:
            if r['status'] != 'infeasible':
                continue
            proof = event_exclusion(c, r['need_id'], {'start_min':1080,'end_min':1140})
            independent, end = enumerate_relaxed_earliest(c, r['need_id'])
            records.append(dict(household_id=r['household_id'], date=r['date'],
                need_id=r['need_id'], mechanism=r['mechanism'], certificate=proof,
                independent_grid_earliest_min=independent,
                passed=proof is not None and independent>=1140 and
                    independent==proof['certificate']['earliest_start_min']))
    result = dict(records=records, count=len(records), passed=all(r['passed'] for r in records),
                  earliest_counts=dict(Counter(r['independent_grid_earliest_min'] for r in records)),
                  scope='direct-event exclusion from original release/complete-chain facts;not simulation')
    save(out/'INDEPENDENT_PRECEDENCE_PROOFS.json', result)
    return {k:v for k,v in result.items() if k!='records'}


if __name__ == '__main__':
    import argparse
    p=argparse.ArgumentParser();p.add_argument('--source',required=True);p.add_argument('--out',required=True)
    a=p.parse_args();print(run(a.source,a.out))
