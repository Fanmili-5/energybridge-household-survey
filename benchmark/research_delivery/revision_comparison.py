"""Before/after evidence: same input and native grid, explicit ledger changes."""
import argparse
from collections import Counter
from pathlib import Path

from benchmark.ab_generation.common import read, save, sha, digest


def run(before, after, out):
    before, after, out = map(Path, (before, after, out))
    old = {(r['household_id'],r['date']):r for r in read(before/'GENERATION.json')}
    new = {(r['household_id'],r['date']):r for r in read(after/'GENERATION.json')}
    if old.keys() != new.keys():
        raise ValueError('COMPARISON_DATES_CHANGED')
    checks, changes, counts = [], [], Counter()
    for key in sorted(old):
        a, b = read(before/old[key]['path']), read(after/new[key]['path'])
        equal = {field:digest(a[field])==digest(b[field]) for field in
                 ('native_domains','native_templates','factors','context_sha256','A_commands_sha256')}
        x = {r['key']:r for r in a['input_opportunities']['entries']}
        y = {r['key']:r for r in b['input_opportunities']['entries']}
        equal['input_ledger_keys'] = x.keys()==y.keys()
        for k in sorted(x.keys() | y.keys()):
            left, right = x.get(k), y.get(k)
            if left and right and (left['status'],left['reason']) == (right['status'],right['reason']):
                continue
            changes.append(dict(household_id=key[0],date=key[1],key=k,before=left,after=right))
        before_hit = a['independent_opportunity_coverage']
        after_hit = b['independent_opportunity_coverage']
        counts.update(dict(before_potential=before_hit['potential'],after_potential=after_hit['potential'],
                           before_witnessed=before_hit['witnessed'],after_witnessed=after_hit['witnessed']))
        checks.append(dict(household_id=key[0],date=key[1],equal=equal,
            before_sha256=sha(before/old[key]['path']),after_sha256=sha(after/new[key]['path']),
            before_rows=len(a['rows']),after_rows=len(b['rows']),
            before_interaction_witnesses=old[key]['witnessed'],after_interaction_witnesses=new[key]['witnessed']))
    result = dict(checks=checks,denominator_crosswalk=changes,counts=dict(counts),
        input_keys_A_and_native_grid_unchanged=all(all(r['equal'].values()) for r in checks),
        certificate_on_every_new_exclusion=all(r['after'] and r['after'].get('independent_input_exclusion') for r in changes),
        scientific_scope='same native grid;mechanism query and input-ledger proof changes;not behavioral superiority')
    save(out,result)
    return dict(slots=len(checks),ledger_changes=len(changes),counts=dict(counts),
                input_keys_A_and_native_grid_unchanged=result['input_keys_A_and_native_grid_unchanged'])


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--before',required=True);p.add_argument('--after',required=True);p.add_argument('--out',required=True)
    a=p.parse_args();print(run(a.before,a.after,a.out))
