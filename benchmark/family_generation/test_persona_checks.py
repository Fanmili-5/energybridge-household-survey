import copy
import unittest
from .core import digest
from .persona_checks import audit_case


class CompatibilityTests(unittest.TestCase):
    def setUp(self):
        self.date = '2025-07-01'; self.need = self.date + ':wash'
        task = {'task_id':'t', 'need_id':self.need, 'asset_id':'washer', 'kind':'washer', 'start_min':10, 'end_min':30}
        ops = [{'operation_id':'load', 'need_id':self.need, 'asset_id':'washer', 'kind':'load_washer', 'operator_id':'adult', 'start_min':0, 'end_min':10},
               {'operation_id':'unload', 'need_id':self.need, 'asset_id':'washer', 'kind':'unload_washer', 'operator_id':'adult', 'start_min':30, 'end_min':40}]
        plan = {'tasks':[task], 'operations':ops, 'controls':[]}
        self.case = {'household_id':'test', 'date':self.date, 'case_id':'case', 'bindings':{'source_A_case_sha256':'source'},
                     'context':{'needs':{'A':['fixed'], 'B':['fixed']}}, 'plans':{'A':plan, 'B':copy.deepcopy(plan)}, 'changes':[]}
        self.context = {'source':{'A_case_sha256':'source'}, 'authority':{'assets':{'washer':{'authorized_operator_ids':['adult']}}},
                        'operator_windows':{'adult':[[0, 100]]}, 'occupancy':{},
                        'needs':[{'need_id':self.need, 'release_min':0, 'deadline_min':3000}]}
        self.profile = {'devices':[{'asset_id':'washer', 'room_id':'kitchen'}], 'role_policy':{'service_policy':{'reschedule_limit_min':140}}}
        self.persona = {'role':'A', 'devices':[{'asset_id':'washer', 'kind':'washer', 'authorization':{'proposal_actions':[], 'routine_DR_eligible':True}}]}

    def check(self):
        before = digest([self.case, self.context, self.profile, self.persona])
        result = audit_case(self.case, self.context, self.profile, self.persona, {})
        self.assertEqual(before, digest([self.case, self.context, self.profile, self.persona]))
        return result['findings']

    def test_life_conflict_is_not_engineering_error_or_acceptance_label(self):
        for group in ('tasks', 'operations'):
            for x in self.case['plans']['B'][group]: x['start_min'] += 160; x['end_min'] += 160
        findings = self.check()
        self.assertTrue(any(f['category'] == 'life_conflict' for f in findings))
        self.assertFalse(any(f['category'] == 'engineering' for f in findings))
        self.assertFalse(any(f['arm'] == 'A' for f in findings))

    def test_actual_wrong_order_remains_engineering_diagnostic(self):
        self.case['plans']['B']['operations'][0].update(start_min=20, end_min=30)
        self.assertTrue(any(f['code'] == 'LOAD_AFTER_PROGRAM_START' and f['category'] == 'engineering' for f in self.check()))

    def test_cross_midnight_operations_not_reduced_modulo_24h(self):
        for group in ('tasks', 'operations'):
            for x in self.case['plans']['B'][group]: x['start_min'] += 1440; x['end_min'] += 1440
        self.context['operator_windows']['adult'].append([1440, 1540])
        self.assertFalse(any(f['code'] == 'HANDLING_OUTSIDE_ORIGINAL_AVAILABILITY' for f in self.check()))


if __name__ == '__main__': unittest.main()
