"""Behavioral checks for configuration, search status and complete recipe inputs."""
import copy,json,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
from ortools.sat.python import cp_model
from . import test_daily_problem as fixtures
from .household_routine_A import solve_programmes
from .eb_primary import sample_A
from .v9_date_adapter import build_problem,generate_day_baseline
from .generate_native import DailyBaselineError
from .generate_cohort import worker
from .candidate_completion import configuration,CompletionContext,append_witness
from .cohort_coverage import load
from .generation_pipeline import compare_plans

class GenerationRecipeTests(unittest.TestCase):
    def problem(self):
        case,reference,cfg=fixtures.NativeDailyTests().fixture(ev=True)
        return case,reference,cfg,build_problem(case,'2007-07-16',reference,days=7,service_date='2007-07-18')
    def require_native(self):
        if not fixtures.NATIVE.exists():self.skipTest('EB_NATIVE_SOURCE required for actual pinned-source execution')
    def test_configured_A_budget_reaches_actual_solver(self):
        self.require_native();case,reference,cfg,_=self.problem();cfg['A_deterministic_time']=.75
        real=cp_model.CpSolver;solvers=[]
        def factory():
            solver=real();solvers.append(solver);return solver
        with patch('benchmark.ab_generation.household_routine_A.cp_model.CpSolver',side_effect=factory):
            out=generate_day_baseline(case,'2007-07-18',reference,cfg,fixtures.MANIFEST,native_appliance_source_path=fixtures.NATIVE)
        self.assertEqual('accepted_plan_only',out['status'])
        self.assertEqual(.75,solvers[0].parameters.max_deterministic_time)
        self.assertEqual(.75,out['A_solver_execution']['deterministic_time_budget'])
    def test_unknown_feasible_and_invalid_are_not_proven_infeasible(self):
        self.require_native();_,_,_,problem=self.problem()
        for code,name,expected in [(cp_model.UNKNOWN,'UNKNOWN','search_unresolved'),(cp_model.FEASIBLE,'FEASIBLE','feasible_not_proven_optimal'),(cp_model.MODEL_INVALID,'MODEL_INVALID','model_invalid'),(cp_model.INFEASIBLE,'INFEASIBLE','infeasible')]:
            with self.subTest(status=name),patch('benchmark.ab_generation.household_routine_A.cp_model.CpSolver') as factory:
                factory.return_value.Solve.return_value=code;factory.return_value.StatusName.return_value=name
                result=sample_A(problem,fixtures.NATIVE,10,deterministic_time=.1)
            self.assertEqual(expected,result['status'])
            self.assertEqual(name,result['causes'][0]['solver_status'])
            self.assertEqual(name=='INFEASIBLE',result['daily_programme_domain_proven_infeasible'])
            self.assertIsNone(result['A'])
    def test_empty_programme_domain_has_explicit_proof_scope(self):
        _,_,_,problem=self.problem();problem=copy.deepcopy(problem)
        problem['jobs'][0]['deadline_min']=problem['jobs'][0]['release_min']
        tasks,reason=solve_programmes(problem,1)
        self.assertIsNone(tasks);self.assertEqual('INFEASIBLE',reason['solver_status'])
        self.assertEqual('empty_declared_programme_domain',reason['proof_scope'])
    def test_direct_solver_rejects_invalid_budgets(self):
        _,_,_,problem=self.problem()
        for value in [True,0,-1,float('nan'),float('inf')]:
            with self.subTest(value=str(value)),self.assertRaisesRegex(ValueError,'INVALID_A_DETERMINISTIC_TIME'):solve_programmes(problem,1,deterministic_time=value)
    def test_legacy_sample_call_keeps_explicit_default(self):
        self.require_native();_,_,_,problem=self.problem();result=sample_A(problem,fixtures.NATIVE,10)
        self.assertEqual('feasible',result['status'])
        self.assertEqual('OPTIMAL',result['household_routine_schedule']['solver_status'])
    def test_worker_retains_unresolved_status_in_failure_record(self):
        with tempfile.TemporaryDirectory() as temp:
            case={'household':{'country':'CN','role_id':'role-example'}}
            error=DailyBaselineError('2007-07-18',{'status':'search_unresolved','result':{'causes':[{'solver_status':'UNKNOWN'}]}})
            with patch('benchmark.ab_generation.generate_cohort.generate',side_effect=error):
                result=worker((0,case,[],{},'a'*64,temp,'unused',{}))
            self.assertEqual('search_unresolved',result['baseline_status'])
            self.assertFalse(result['daily_programme_domain_proven_infeasible'])
            self.assertEqual('UNKNOWN',load(Path(temp)/'0000/FAILURE.json')['baseline_causes'][0]['solver_status'])
    def test_completion_budget_config_is_strict(self):
        with tempfile.TemporaryDirectory() as temp:
            path=Path(temp)/'config.json'
            for value in [{'invented':1},{'attempts_per_cell':False},{'oracle_deterministic_time':0}]:
                path.write_text(json.dumps(value))
                with self.assertRaises(ValueError):configuration(path)
        self.assertEqual(3,configuration()['attempts_per_country'])
    def test_source_hash_mismatch_stops_before_native_loading(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);(root/'PRE_RUN.json').write_text(json.dumps({'source_sha256':'0'*64,'configuration':{}}))
            source=root/'source.jsonl';source.write_text('{}\n')
            with self.assertRaisesRegex(ValueError,'HOUSEHOLD_MANIFEST_CHANGED'):CompletionContext(root,source,'not-opened')
    def test_extra_candidate_append_deduplicates_without_losing_other_dates(self):
        with tempfile.TemporaryDirectory() as temp:
            path=Path(temp)/'extra.json.gz'
            self.assertTrue(append_witness(path,'d1',{'id':'x'}));self.assertFalse(append_witness(path,'d1',{'id':'x'}))
            self.assertTrue(append_witness(path,'d2',{'id':'y'}))
            self.assertEqual([('d1',1),('d2',1)],[(d['date'],len(d['rows'])) for d in load(path)])
    def test_plan_comparison_uses_actual_plan_hashes_not_gzip_identity(self):
        with tempfile.TemporaryDirectory() as temp:
            a,b=Path(temp)/'a',Path(temp)/'b';a.mkdir();b.mkdir()
            row=dict(case_id='synthetic',date='d',A_sha256='a',B_sha256='b',pair_file_sha256='x')
            (a/'PAIR_INDEX.jsonl').write_text(json.dumps(row)+'\n')
            row['pair_file_sha256']='different-container';(b/'PAIR_INDEX.jsonl').write_text(json.dumps(row)+'\n')
            self.assertTrue(compare_plans(a,b)['all_current_A_B_plans_equal'])
            row['B_sha256']='changed';(b/'PAIR_INDEX.jsonl').write_text(json.dumps(row)+'\n')
            self.assertFalse(compare_plans(a,b)['all_current_A_B_plans_equal'])
if __name__=='__main__':unittest.main()
