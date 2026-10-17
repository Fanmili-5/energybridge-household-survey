"""Revision planning must preserve the whole dataset and never invent unsupported actions."""
import sys
from pathlib import Path
from unittest.mock import patch
STAGE=Path(__file__).resolve().parents[1];sys.path.insert(0,str(STAGE/'code'))
from common import *
import generate

def main():
    rows=read(SOURCE_B/'PAIR_BINDINGS10000.json')['records'];tests=[]
    original=read(OUT/'INPUT_REVISION_PLAN.json')
    replay=generate.plan_requests(list(reversed(rows)))
    assert replay==original
    tests.append('revision_plan_reproduces_independent_of_household_iteration_order')
    unchanged={k for k,v in original['assignments'].items()if v is None}
    revisions={k for k,v in original['assignments'].items()if v is not None}
    source_noops={r['case_id']for r in read(SOURCE_B/'NO_COMMAND_CHANGE_CASES.json')['records']}
    assert len(unchanged)==100 and len(revisions)==90 and not unchanged&revisions and unchanged|revisions==source_noops
    tests.append('exact90_revisions_leave100_existing_B_requests_in_the_original190')
    with patch.object(generate,'select_request',return_value=None):
        try:
            generate.plan_requests(rows)
        except ValueError as error:
            assert 'CANNOT_BE_MET_WITH_SUPPORTED_REQUESTS' in str(error)
        else: raise AssertionError('Unsupported requests must not be invented to meet the quota')
    tests.append('unsupported_quantity_target_fails_instead_of_fabricating_actions')
    binding=read(OUT/'PAIR_BINDINGS10000.json');actual_revised=set();actual_noops=set()
    for row in binding['records']:
        for rr in row['rounds']:
            if not rr['inherited_source_pair']:actual_revised.add(rr['case_id'])
            if rr['comparison_group']=='identical_commands':actual_noops.add(rr['case_id'])
    assert actual_revised==revisions and actual_noops==unchanged
    tests.append('published_case_groups_follow_the_pre_B_plan_without_retries_or_extra_changes')
    assert binding['cases']==10000 and len(binding['records'])==1000
    assert all(len(h['rounds'])==10 for h in binding['records'])
    assert original['all10000_used_as_one_dataset']
    tests.append('all10000_original_cases_remain_together_in_one_manifest')
    result={'passed':True,'count':len(tests),'tests':tests,'rules_sha256':rules_id(),'human_labels_created':0}
    save(OUT/'REGRESSION_RESULTS.json',result);print(canonical(result))

if __name__=='__main__':main()
