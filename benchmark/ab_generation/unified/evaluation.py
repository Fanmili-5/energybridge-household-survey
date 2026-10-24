"""Leakage-safe household/source components and unfilled human-study protocol."""
from collections import defaultdict
from ..common import digest


def grouped_split(records,seed=0,ratios=(0.8,0.1,0.1)):
    if len(ratios)!=3 or any(r<0 for r in ratios) or abs(sum(ratios)-1)>1e-9:raise ValueError('INVALID_SPLIT_RATIOS')
    parent={}
    def find(x):
        parent.setdefault(x,x)
        if parent[x]!=x:parent[x]=find(parent[x])
        return parent[x]
    def union(a,b):parent[find(a)]=find(b)
    for r in records:
        h='household:'+r['household_id'];find(h)
        for s in r.get('source_scenario_ids',[]):union(h,'source:'+s)
        for s in r.get('matched_contrast_ids',[]):union(h,'contrast:'+s)
    groups=defaultdict(list)
    for r in records:groups[find('household:'+r['household_id'])].append(r)
    assignments={}
    for group,rows in groups.items():
        identity=sorted({r['household_id'] for r in rows})
        q=int(digest([seed,'split',identity])[:16],16)/2**64
        split='train' if q<ratios[0] else 'dev' if q<sum(ratios[:2]) else 'test'
        for r in rows:assignments[r['id']]=split
    return dict(assignments=assignments,components=len(groups),ratios_are_experimental=True,
        realized_counts=dict(__import__('collections').Counter(assignments.values())),
        exact_proportions_guaranteed=False)


def human_protocol():
    return dict(status='not_run;no_human_validity_claim',
        profile_arms=['six_class_only','shared_habits','full_profile','mismatched_profile'],
        sampling_arms=['uniform','favorable_only_control','normalized_conditional_coverage'],
        design='randomized_profile_display;common_A_B_cases;household_and_source_grouped_heldout_evaluation',
        outcomes=['comprehension','family_evidence_use','acceptance_distribution','score_calibration','reason_grounding'],
        acceptance_gold='independent_human_responses;not_generator_rules',
        preserve=['disagreement','missing_answers','negative_results'],
        power_analysis='required_after_pilot_variance;not_claimed_from_engineering_tests',
        recruitment_started=False,training_started=False)
