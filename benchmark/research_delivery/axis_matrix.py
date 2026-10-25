"""Descriptive joint-axis gaps; never supplies quotas or changes selection."""
import argparse
from collections import defaultdict

from benchmark.ab_generation.common import read, save
from .axis_acceptance import band


def matrix(rows, selected_ids, household=False):
    selected=set(selected_ids);groups=defaultdict(list)
    for row in rows:
        for child in row['components']:
            a=child['change_axes'];shift=a['machine']['signed_start_shift_min']
            if shift is None:continue
            key=(row['household_id'] if household else None,child['family'],
                 band(shift),band(a['handling']['maximum_absolute_retime_min']))
            groups[key].append(row)
    result=[]
    for (home,family,machine,handling),pool in sorted(groups.items()):
        ids={r['id'] for r in pool};hits=ids&selected
        result.append(dict(household_id=home,family=family,machine=machine,handling=handling,
            candidate_action_instances=len(pool),candidate_cases=len(ids),
            selected_action_instances=sum(r['id'] in selected for r in pool),selected_cases=len(hits),
            candidate_home_dates=len({(r['household_id'],r['date']) for r in pool}),
            missing_from_selection=not hits,
            reason=None if hits else 'witnessed_in_frozen_pool;not_a_predeclared_pairwise_selection_target'))
    return dict(pairs=result,available_pairs=len(result),selected_pairs=sum(not r['missing_from_selection'] for r in result),
        missing_pairs=sum(r['missing_from_selection'] for r in result),
        scope='observed_family_machine_handling_pairs;descriptive_not_a_new_acceptance_target',
        repetitions_not_independent_observations=True,selector_or_inputs_changed=False)


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--rows',required=True);p.add_argument('--selection',required=True)
    p.add_argument('--out',required=True);p.add_argument('--household',action='store_true');a=p.parse_args()
    save(a.out,matrix(read(a.rows),read(a.selection)['selected_ids'],a.household))
