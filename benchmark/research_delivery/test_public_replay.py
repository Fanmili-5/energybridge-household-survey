"""Provenance and information-flow checks for the public replay adapter."""
import copy
import datetime as dt
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from benchmark.ab_generation.common import read,save,sha
from . import public_replay as route


DATES=[(dt.date(2025,1,1)+dt.timedelta(days=i)).isoformat() for i in range(10)]


class PublicReplayTests(unittest.TestCase):
    def test_missing_calendar_or_duplicate_date_stops_before_compilation(self):
        with patch.object(route,'compile_life') as compile_call:
            with self.assertRaisesRegex(ValueError,'LOOKAHEAD_MISSING'):
                route.original_problem(dict(anchor=DATES[0],end_exclusive='2025-01-11'),{},DATES)
            with self.assertRaisesRegex(ValueError,'EXACT_TEN_GIVEN_DATES_REQUIRED'):
                route.original_problem(dict(anchor=DATES[0],end_exclusive='2025-02-01'),{},DATES[:-1]+[DATES[0]])
            compile_call.assert_not_called()

    def test_compilation_preserves_input_and_lookahead_is_not_extra_question(self):
        spec=dict(anchor=DATES[0],end_exclusive='2025-02-01',calendar={'original':True});before=copy.deepcopy(spec)
        def compile_call(local,world):
            self.assertEqual('2025-01-13',local['end_exclusive'])
            self.assertEqual(before['calendar'],local['calendar'])
            return dict(jobs=[dict(date=d) for d in DATES+['2025-01-11']],calendar=local['calendar'])
        with patch.object(route,'compile_life',side_effect=compile_call):problem=route.original_problem(spec,{},DATES)
        self.assertEqual(before,spec);self.assertEqual(DATES,[j['date'] for j in problem['jobs']])

    def test_source_tamper_and_path_escape_rejected(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);p=root/'data.json';save(p,{'given':1});reference=dict(path='data.json',sha256=sha(p))
            save(p,{'given':2})
            with self.assertRaisesRegex(ValueError,'SOURCE_HASH_MISMATCH'):route.checked_file(root,reference)
            with self.assertRaisesRegex(ValueError,'RESOURCE_OUTSIDE_ROOT'):
                route.checked_file(root,dict(path='../outside.json',sha256='unused'))

    def test_expected_A_is_read_after_solving_and_mismatch_is_reported(self):
        # This tests the adapter's information boundary, not solver quality.
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);record=dict(household_id='h',dates=DATES,expected_seed=0)
            problem=dict(jobs=[])
            values=dict(life={'households':[dict(household_id='h')]},world={'households':[dict(household_id='h')]},
                        portrait={'household_id':'h'},expected_problem=problem,
                        expected_A={'A':['must not become the generated plan']})
            for name,value in values.items():
                path=root/(name+'.json');save(path,value);record[name]=dict(path=path.name,sha256=sha(path))
            save(root/'inputs.json',dict(schema='eb.public_life_replay.v1',households=[record]))
            save(root/'config.json',dict(seed=0,A_target_context_mode='life_conditional_v1'))
            events=[];checked=route.checked_file
            def checked_call(base,reference):
                events.append('read:'+reference['path']);return checked(base,reference)
            def solve_call(given,portrait,**kwargs):
                self.assertEqual(problem,given)
                self.assertNotIn('read:expected_A.json',events);events.append('solve')
                return dict(status='feasible',A=['fresh generated plan'],ev_charging_steps=[],conditional_target_context={})
            with patch.object(route,'original_problem',side_effect=lambda *args:copy.deepcopy(problem)), \
                 patch.object(route,'checked_file',side_effect=checked_call), \
                 patch.object(route,'solve',side_effect=solve_call), \
                 patch.object(route,'inspect',return_value={'passed':True}), \
                 patch.object(route,'fresh_context',side_effect=lambda p,a,d,*args:dict(date=d,A=a['A'])), \
                 patch.object(route,'audited_build') as build_call:
                result=route.replay(root/'inputs.json',root/'out',root/'config.json',stage='A')
            build_call.assert_not_called()
            self.assertLess(events.index('solve'),events.index('read:expected_A.json'))
            self.assertFalse(result['expected_A_equal']);self.assertEqual(1,result['A_records'])
            self.assertEqual(['fresh generated plan'],read(root/'out/h/A_0.json.gz')['A'])
            self.assertEqual(10,result['selected_A_date_slots'])


if __name__=='__main__':unittest.main()
