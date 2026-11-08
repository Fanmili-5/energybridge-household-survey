"""Offline contract tests; all fixtures are invented, never survey records."""
import copy
import unittest
from itertools import combinations
from .required_controls import allowed_masks,validate_household,POLICY_ID

def fixture(mask=('AC','WM','DR','DW'),role='D'):
    return {'benchmark_role':role,'household':{
      'controlled_function_ids':list(mask),'controlled_function_count':len(mask),
      'equipment':{'space_ac_available':{'present':True,'control_enabled':True,'energy_carrier':'electricity'}},
      'control_inventory':{'AC':{'enabled':True,'coverage_counted':True}},
      'service_contracts':{'AC':{'require_actual_service_need':True}},
      'question_coverage_blueprint':{'actual_questions_generated':False,'slots':[{'focus_functions':['AC']} for _ in range(10)]},
      'cohort_generation_policy':{'policy_id':POLICY_ID,'required_control_functions':['AC'],'AC_source_ownership_not_inferred':True}}}

class ContractTests(unittest.TestCase):
    def test_feasible_domain_and_pair_states(self):
        masks=allowed_masks();self.assertEqual(len(masks),16);self.assertEqual(len(allowed_masks('F')),11)
        self.assertTrue(all('AC' in m and 4<=len(m)<=6 for m in masks))
        fs=('AC','WM','DR','DW','WH','EV')
        states={(pair,tuple(int(f in mask) for f in pair)) for pair in combinations(fs,2) for mask in masks}
        self.assertEqual(len(states),50)
    def test_every_feasible_pattern_passes(self):
        for role in 'ABCDEF':
            for mask in allowed_masks(role):self.assertTrue(validate_household(fixture(mask,role)))
    def test_legacy_valid_no_ac_mask_rejected(self):
        with self.assertRaisesRegex(ValueError,'AC_REQUIRED'):validate_household(fixture(('WM','DR','DW','WH')))
    def test_present_but_fixed_ac_rejected(self):
        c=fixture();c['household']['control_inventory']['AC']['enabled']=False
        with self.assertRaisesRegex(ValueError,'AC_NOT_CONTROLLED'):validate_household(c)
    def test_controlled_but_missing_hardware_rejected(self):
        c=fixture();c['household']['equipment']['space_ac_available']['present']=False
        with self.assertRaisesRegex(ValueError,'AC_NOT_PRESENT'):validate_household(c)
    def test_ev_role_keeps_ev(self):
        with self.assertRaisesRegex(ValueError,'INVALID_CONTROL_MASK'):validate_household(fixture(role='F'))
    def test_missing_ac_question_exposure_rejected(self):
        c=fixture();c['household']['question_coverage_blueprint']['slots']=[{'focus_functions':['WM']} for _ in range(10)]
        with self.assertRaisesRegex(ValueError,'AC_BLUEPRINT'):validate_household(c)
    def test_weakening_required_function_rejected(self):
        c=fixture();c['household']['cohort_generation_policy']['required_control_functions']=[]
        with self.assertRaisesRegex(ValueError,'AC_POLICY'):validate_household(c)
    def test_no_outcome_is_created(self):
        c=fixture();before=copy.deepcopy(c);validate_household(c);self.assertEqual(c,before)

if __name__=='__main__':unittest.main()
