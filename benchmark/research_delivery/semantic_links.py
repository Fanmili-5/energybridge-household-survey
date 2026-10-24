"""Candidate v3 signature: bind judgment relations to their device action.

An isolated, versioned selection revision while v2.8 generation is frozen.
No actions, profiles, dates, targets or coverage weights change. The old proxy
is retained as a comparator. This is not a claim of human semantic equivalence.
"""
import argparse
from collections import Counter,defaultdict
from pathlib import Path
from unittest.mock import patch

from benchmark.ab_generation.common import read,save,digest,canonical,sha
from benchmark.ab_generation.unified import selection
from benchmark.ab_generation.unified.semantics import judgment_signature as v2_signature,mechanism

VERSION='eb.device_linked_judgment_signature.v3_candidate2'


def linked_contexts(row):
    components=row.get('components',[]);judgments=row.get('judgment_context',[])
    if len(components)!=len(judgments):raise ValueError('JUDGMENT_COMPONENT_COUNT_MISMATCH')
    pairs=[]
    # request() emits both arrays from the same ordered children loop. Validate
    # the original asset association, rather than grouping opinions into a bag.
    for component,judgment in zip(components,judgments):
        if component['asset_id']!=judgment.get('asset_id'):
            raise ValueError('JUDGMENT_COMPONENT_ORDER_MISMATCH')
        if judgment.get('component_id',component['id'])!=component['id']:
            raise ValueError('JUDGMENT_EXPLICIT_COMPONENT_MISMATCH')
        pairs.append((component,judgment))
    return pairs


def relation_nodes(row):
    nodes=[]
    for component,judgment in linked_contexts(row):
        magnitude=component['magnitude'];signed=magnitude.get('signed_machine_shift_min')
        slack=magnitude.get('service_slack_min')
        node=dict(family=component['family'],mechanism=mechanism(component['mechanism']),
            axis=magnitude.get('axis','program'),event_role=component['event_relevance']['role'],
            relative_position=component.get('relative_level'),
            machine_direction=None if signed is None else 'earlier' if signed<0 else 'later' if signed>0 else 'unchanged',
            handling_changed=bool(magnitude.get('manual_total_shift_min')),
            service_margin='unknown' if slack is None else 'shortfall' if slack<0 else 'under_30' if slack<30 else 'ample')
        # Existing member-position semantics now see ONLY their associated
        # action; same-asset multi-batch shifts cannot contaminate each other.
        local=dict(components=[component],judgment_context=[judgment],issues=[])
        node['member_and_permission_relations']=v2_signature(local,{}, {})
        nodes.append(node)
    return sorted(nodes,key=canonical)


def signature(row,details,axes):
    return digest(dict(version=VERSION,detail={f:sorted(v) for f,v in details.items()},
                       axes=axes,device_linked_positions=relation_nodes(row),issues=sorted(set(row['issues']))))


def audit_rows(rows):
    old={r['id']:selection.concepts(r) for r in rows}
    with patch.object(selection,'judgment_signature',signature):
        new={r['id']:selection.concepts(r) for r in rows}
    groups=defaultdict(list);signature_groups=defaultdict(list)
    for row in rows:
        view=old[row['id']]
        key=canonical([row['household_id'],row['date'],sorted(view['tokens']),view['signature'],view['composition'],view['families']])
        groups[key].append(row)
        signature_groups[(row['household_id'],view['signature'])].append(row)
    split=[]
    for pool in groups.values():
        ns={new[r['id']]['signature'] for r in pool}
        if len(ns)<2:continue
        examples={}
        for row in pool:
            examples.setdefault(new[row['id']]['signature'],dict(case_id=row['id'],nodes=relation_nodes(row)))
        split.append(dict(household_id=pool[0]['household_id'],date=pool[0]['date'],
                          candidate_ids=[r['id'] for r in pool],new_groups=len(ns),examples=list(examples.values())))
    invariant=all(all(old[r['id']][k]==new[r['id']][k] for k in ('tokens','families','composition','action')) for r in rows)
    return dict(candidates=len(rows),same_date_objective_equivalent_pools=len(groups),
        pools_split=len(split),candidate_rows_in_split_pools=sum(len(r['candidate_ids']) for r in split),
        household_signature_groups_split=sum(len({new[r['id']]['signature'] for r in pool})>1 for pool in signature_groups.values()),
        features_weights_and_literal_actions_unchanged=invariant,split_pools=split,
        old_signature_version='eb.plan_semantics.v2',candidate_version=VERSION,
        human_equivalence_validated=False,official_bank_changed=False)


def run(collection,out,reselect=False):
    collection,out=Path(collection),Path(out);out.mkdir(parents=True,exist_ok=False)
    rows=[];sources={}
    for slot in read(collection/'GENERATION.json'):
        path=collection/slot['path'];sources[str(path)]=sha(path);rows.extend(read(path).get('rows',[]))
    save(out/'SOURCE_PINS.json',sources)
    save(out/'CANDIDATE_ROWS.json.gz',rows)
    save(out/'METHOD_PINS.json',dict(version=VERSION,helper_sha256=sha(__file__),
        selection_sha256=sha(selection.__file__),rows_sha256=sha(out/'CANDIDATE_ROWS.json.gz'),
        official_sources_unchanged=True))
    report=audit_rows(rows);save(out/'SEMANTIC_LINK_AUDIT.json',report)
    if reselect:
        cfg=read(collection/'PRE_GENERATION.json')['configuration']
        old=read(collection/'SELECTION.json');byid={r['id']:r for r in rows}
        with patch.object(selection,'judgment_signature',signature):
            revised=selection.assign(rows,cfg)
        save(out/'CANDIDATE_SELECTION.json',revised)
        changed=[]
        old_dates={(byid[i]['household_id'],byid[i]['date']):i for i in old['selected_ids']}
        for i in revised['selected_ids']:
            key=(byid[i]['household_id'],byid[i]['date'])
            if old_dates[key]!=i:changed.append(dict(household_id=key[0],date=key[1],old=old_dates[key],candidate=i))
        report['selection_probe']=dict(selected=len(revised['selected_ids']),changed_dates=changed,
            weights_targets_and_solver_budget_unchanged=True,actual_outcomes_or_answers_used=False,
            official_materials_unchanged=True,
            old_family_exposure=dict(Counter(f for i in old['selected_ids'] for f in selection.concepts(byid[i])['families'])),
            candidate_family_exposure=dict(Counter(f for i in revised['selected_ids'] for f in selection.concepts(byid[i])['families'])))
        save(out/'SEMANTIC_LINK_AUDIT.json',report)
    changed=[p for p,h in sources.items() if sha(p)!=h]
    if changed:raise ValueError('FROZEN_CATALOGUE_CHANGED_DURING_LINK_AUDIT')
    return {k:v for k,v in report.items() if k not in ('split_pools','selection_probe')}


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--collection',required=True);p.add_argument('--out',required=True);p.add_argument('--reselect',action='store_true')
    a=p.parse_args();print(run(a.collection,a.out,a.reselect))
