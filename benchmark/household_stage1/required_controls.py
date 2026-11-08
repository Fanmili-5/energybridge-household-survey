"""Public contract shared by the AC-required cohort builder and validators."""
from itertools import combinations

FUNCTIONS=('AC','WM','DR','DW','WH','EV')
REQUIRED_CONTROL_FUNCTIONS=('AC',)
POLICY_ID='eb.household_stage1.ac_required.v1'

def allowed_masks(role=None):
    return tuple(mask for n in (4,5,6) for mask in combinations(FUNCTIONS,n)
                 if 'AC' in mask and (role!='F' or 'EV' in mask))

def validate_household(case):
    h=case['household'];mask=tuple(h['controlled_function_ids'])
    if mask not in allowed_masks(case['benchmark_role']):raise ValueError('AC_REQUIRED_OR_INVALID_CONTROL_MASK')
    q=h['equipment']['space_ac_available'];inv=h['control_inventory']['AC']
    if q.get('present') is not True:raise ValueError('AC_NOT_PRESENT')
    if q.get('control_enabled') is not True or inv.get('enabled') is not True or inv.get('coverage_counted') is not True:
        raise ValueError('AC_NOT_CONTROLLED')
    if q.get('energy_carrier')!='electricity':raise ValueError('AC_CARRIER_INVALID')
    if h['controlled_function_count']!=len(mask):raise ValueError('CONTROL_COUNT_INVALID')
    if 'AC' not in h['service_contracts']:raise ValueError('AC_SERVICE_CONTRACT_MISSING')
    blueprint=h['question_coverage_blueprint']
    if len(blueprint['slots'])!=10 or blueprint['actual_questions_generated'] is not False:raise ValueError('BLUEPRINT_IS_NOT_TEN_PENDING_SLOTS')
    if sum('AC' in slot['focus_functions'] for slot in blueprint['slots'])<2:raise ValueError('AC_BLUEPRINT_EXPOSURE_MISSING')
    policy=h['cohort_generation_policy']
    if policy.get('policy_id')!=POLICY_ID or policy.get('required_control_functions')!=['AC'] or policy.get('AC_source_ownership_not_inferred') is not True:
        raise ValueError('AC_POLICY_OR_PROVENANCE_MISSING')
    return True
