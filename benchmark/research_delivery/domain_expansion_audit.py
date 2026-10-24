"""Audit an explicit native-domain expansion without treating it as same-domain.

Old and new complete catalogues remain authoritative. SHA-256 identities bind
literal commands; relative labels may change when their declared domain grows.
No candidates are regenerated, repaired, appended or selected here.
"""
import argparse
from collections import Counter
from pathlib import Path

from benchmark.ab_generation.common import read, save, sha


def native_index(catalogue):
    result={}
    for group,cells in zip(catalogue.get('native_domains',[]),catalogue.get('factors',[])):
        for cell in cells:
            for index in cell['ids']:
                row=group[index]
                if row:result[row['id']]=dict(role='factor',family=row['family'],mechanism=row['mechanism'],
                    relative_level=row.get('relative_level'),cell=cell['label'],unit=row['unit'])
    for row in catalogue.get('support_native_domain',[]):
        if row:result.setdefault(row['id'],dict(role='support',family=row['family'],mechanism=row['mechanism'],
            relative_level=row.get('relative_level'),cell=None,unit=row['unit']))
    return result


def compare(old,new):
    a,b=native_index(old),native_index(new)
    common=a.keys()&b.keys();removed=sorted(a.keys()-b.keys());added=b.keys()-a.keys()
    relabelled=Counter();partitions=Counter()
    for key in common:
        if a[key]!=b[key]:
            left,right=a[key],b[key]
            relabelled[(left['family'],left['role'],right['role'],str(left['relative_level']),str(right['relative_level']))]+=1
        partitions[(a[key]['unit'],str(a[key]['cell']),str(b[key]['cell']))]+=1
    return dict(old_literal_commands=len(a),new_literal_commands=len(b),removed_old_ids=removed,
        added_literal_commands=len(added),added_by_family=dict(Counter(b[k]['family'] for k in added)),
        label_crosswalk=[dict(family=k[0],old_role=k[1],new_role=k[2],old_relative=k[3],new_relative=k[4],count=v)
                         for k,v in sorted(relabelled.items())],
        semantic_partition_crosswalk=[dict(unit=k[0],old_cell=k[1],new_cell=k[2],common_literal_values=v)
                                      for k,v in sorted(partitions.items())],
        old_semantic_interaction_targets=len(old.get('coverage',{}).get('coverage',[])),
        new_semantic_interaction_targets=len(new.get('coverage',{}).get('coverage',[])),
        semantic_target_counts_not_numeric_domain_sizes=True,
        original_A_unchanged=old.get('A_commands_sha256')==new.get('A_commands_sha256'),
        original_context_unchanged=old.get('context_sha256')==new.get('context_sha256'),
        old_input_ledger_keys={e['key'] for e in old.get('input_opportunities',{}).get('entries',[])},
        new_input_ledger_keys={e['key'] for e in new.get('input_opportunities',{}).get('entries',[])})


def run(before,after,out):
    before,after,out=map(Path,(before,after,out));checks=[]
    a={(r['household_id'],r['date']):r for r in read(before/'GENERATION.json')}
    b={(r['household_id'],r['date']):r for r in read(after/'GENERATION.json')}
    if a.keys()!=b.keys():raise ValueError('COMPARISON_ROSTER_OR_DATES_CHANGED')
    for key in sorted(a):
        left,right=before/a[key]['path'],after/b[key]['path']
        old,new=read(left),read(right);record=compare(old,new)
        record['input_ledger_keys_preserved']=record.pop('old_input_ledger_keys')==record.pop('new_input_ledger_keys')
        record.update(household_id=key[0],date=key[1],old_catalogue_sha256=sha(left),new_catalogue_sha256=sha(right),
                      passed=not record['removed_old_ids'] and record['original_A_unchanged'] and
                             record['original_context_unchanged'] and record['input_ledger_keys_preserved'])
        checks.append(record);save(out.with_name(out.stem+'_PROGRESS.json'),dict(completed=len(checks),expected=len(a)))
        del old,new
    result=dict(slots=len(checks),all_passed=all(r['passed'] for r in checks),checks=checks,
        old_literal_commands=sum(r['old_literal_commands'] for r in checks),
        new_literal_commands=sum(r['new_literal_commands'] for r in checks),
        removed_old_literal_commands=sum(len(r['removed_old_ids']) for r in checks),
        helper_sha256=sha(__file__),same_domain_comparison=False,
        scope='explicit native-domain expansion;not solver superiority or human validity')
    save(out,result)
    return {k:v for k,v in result.items() if k!='checks'}


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--before',required=True);p.add_argument('--after',required=True);p.add_argument('--out',required=True)
    a=p.parse_args();print(run(a.before,a.after,a.out))
