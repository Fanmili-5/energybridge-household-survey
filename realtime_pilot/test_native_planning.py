"""Native source parity and model-response regressions; no external API calls."""
import ast
from contextlib import redirect_stdout
from io import StringIO
from copy import deepcopy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from common import UPSTREAM, normalize_answers
from paired_contract import LOOKUP, prepare
from verify_paired_physics import answers
from eb_execution import upstream
from household_config import bind_household, ensure_household_config
from closed_loop import EBPlanner, execution_explanation
from native_planning import runtime_errors, resolve


def portfolio(plan):
    return json.dumps({'candidate_plans':[{'id':'own_plan','plan':plan}],
        'selected_candidate_id':'own_plan','selection_reason':'测试方案，以执行结果为准。'})


from legacy_test_support import prepare


class NativePlanningTests(unittest.TestCase):
    def setUp(self):
        self.runner, Suite = upstream()
        profile = normalize_answers(answers(), list(LOOKUP), LOOKUP)
        original, scenario = prepare(profile, 'native-planning-regression')
        from evaluation_window import make_window
        scenario['evaluation_window']=make_window(original)
        scenario.update(decision_h=18,event={'id':'regression','trigger_h':19,'end_h':19.5,'day':4})
        self.request = {'profile':profile,'original_plan':original,'scenario':scenario,
                        'household_id':'engineering-native-planning'}
        house = ensure_household_config(self.request)
        self.config = house['appliances']
        self.loop = self.runner._FamilyLoop()
        bind_household(self.loop, self.request)
        self.loop.appliance_suite = Suite(self.config,sim_days=5,explicit_only=True)
        self.loop.no_vpp_daily_plan_by_day = {3:deepcopy(original['eb_ordinary_plan'])}
        self.event = {'id':'regression','trigger_h':91,'end_h':91.5,'day':4}
        self.bounds = {'minimum_c':23,'maximum_c':28}
        self.good = deepcopy(original['eb_ordinary_plan'])
        self.good.update(next_check_hour=None)
        self.good['appliances'].update(washer_start_h=20,dishwasher_start_h=20,
            dryer_start_h=22,water_heater_preheat=False,
            ev_charge_start_h=self.config['ev']['arrival_h'],ev_charge_end_h=8)
        self.observed = {'temperature_c':26,'outdoor_c':33,'facility_w':5000,'occupancy_count':3}

    def check(self, plan, now=90, event=True):
        return runtime_errors(plan,loop=self.loop,config=self.config,sim_h=now,
            horizon=104,bounds=self.bounds,event=self.event if event else None)

    def test_checks_match_actual_native_policy_closure(self):
        tree = ast.parse((UPSTREAM/'experiments/benchmark/family_runner.py').read_text())
        node = next(n for n in ast.walk(tree) if isinstance(n,ast.FunctionDef) and n.name=='_hard_policy_errors')
        module = ast.fix_missing_locations(ast.Module(body=[deepcopy(node)],type_ignores=[]))
        for now in (90,91,92):
            event = self.event if now<91.5 else None
            scope = dict(vars(self.runner),loop=self.loop,appliance_config=self.config,
                sim_h=now,hod=now%24,adaptive_agent=True,vpp_event=event,
                vpp_active=bool(event and now>=91))
            exec(compile(module,'native_policy_closure','exec'),scope)
            bad = deepcopy(self.good)
            bad['appliances'].update(washer_start_h=19,water_heater_preheat=True)
            bad['appliances'].pop('water_heater_preheat_temp_c',None)
            bad['appliances'].pop('washer_skip',None)
            for plan in (self.good,bad):
                native = self.runner._adaptive_v3_plan_control_errors(plan,sim_h=now,
                    total_sim_hours=104,setpoint_min_c=23,setpoint_max_c=28)
                native += scope['_hard_policy_errors'](plan['appliances'])
                self.assertEqual(self.check(plan,now,event is not None),native)

    def test_regression_missing_temperature_and_event_overlap_are_not_accepted(self):
        bad = deepcopy(self.good)
        bad['appliances'].update(washer_start_h=19,water_heater_preheat=True,
            water_heater_preheat_start_h=17,water_heater_preheat_end_h=21.5)
        bad['appliances'].pop('water_heater_preheat_temp_c',None)
        errors = self.check(bad)
        self.assertTrue(any('water_heater_preheat_temp_c' in e for e in errors),errors)
        self.assertTrue(any('washer' in e and 'overlaps VPP' in e for e in errors),errors)
        self.assertTrue(any('water_heater' in e and 'overlaps VPP' in e for e in errors),errors)
        self.assertEqual(self.check(self.good),[])

    def run_planner(self, responses):
        from energybridge.llm.client import LLMClient
        replies = [{'text':portfolio(plan),'metrics':{}} for plan in responses]
        with tempfile.TemporaryDirectory() as tmp:
            planner = EBPlanner(self.request,Path(tmp),lambda *_:None)
            with patch.object(LLMClient,'chat_with_metrics',side_effect=replies):
                plan, _ = planner(self.loop,90,self.observed,[],['notification'])
            folder = Path(tmp)/'round_001'
            saved = {name:json.loads((folder/name).read_text()) for name in
                ['planning_input.json','planning_audit.json','constraint_scope.json']}
            return plan,planner,saved

    def test_actual_planner_preserves_constraints_and_runs_evidence_review(self):
        plan,planner,saved = self.run_planner([self.good,self.good])
        self.assertEqual(plan['appliances'],self.good['appliances'])
        self.assertEqual([c['purpose'] for c in planner.calls],['initial_planning','evidence_review'])
        ids = saved['constraint_scope.json']['preserved_constraint_ids']
        self.assertIn('washer_outside_vpp_window',ids)
        self.assertIn('water_heater_outside_vpp_window_when_preheating',ids)
        self.assertTrue(saved['planning_audit.json']['evidence_review_attempted'])
        self.assertFalse(planner.last_audit['fallback_used'])

    def test_actual_planner_sends_invalid_actions_back_to_model(self):
        bad = deepcopy(self.good)
        bad['appliances'].update(water_heater_preheat=True,
            water_heater_preheat_start_h=20,water_heater_preheat_end_h=22)
        bad['appliances'].pop('water_heater_preheat_temp_c',None)
        plan,planner,saved = self.run_planner([bad,self.good])
        self.assertEqual(plan['appliances'],self.good['appliances'])
        self.assertEqual([c['purpose'] for c in planner.calls],['initial_planning','semantic_repair'])
        self.assertTrue(saved['planning_audit.json']['semantic_replan_attempted'])
        self.assertFalse(planner.last_audit['fallback_used'])

    def test_repeated_invalid_output_stops_and_uses_native_fallback(self):
        bad=deepcopy(self.good)
        bad['appliances'].update(water_heater_preheat=True)
        bad['appliances'].pop('water_heater_preheat_temp_c',None)
        plan,planner,saved=self.run_planner([bad,bad])
        self.assertTrue(planner.last_audit['fallback_used'])
        self.assertIsNone(saved['planning_audit.json']['selected_executable_plan'])
        self.assertEqual(len(planner.calls),2)
        self.assertNotEqual(plan,bad)

    def test_review_failure_keeps_native_valid_selection(self):
        from energybridge.llm.client import LLMClient, LLMCallError
        error=LLMCallError(failure_type='APIConnectionError',metrics={
            'attempts':1,'provider_failures':1,'latency_seconds':2.1,
            'url':'https://private.invalid','api_key':'DO_NOT_SAVE'})
        with tempfile.TemporaryDirectory() as tmp:
            planner=EBPlanner(self.request,Path(tmp),lambda *_:None)
            with patch.object(LLMClient,'chat_with_metrics',side_effect=[
                    {'text':portfolio(self.good),'metrics':{}},error]):
                plan,_=planner(self.loop,90,self.observed,[],['notification'])
            self.assertEqual(plan['appliances'],self.good['appliances'])
            self.assertFalse(planner.last_audit['fallback_used'])
            failure=json.loads((Path(tmp)/'round_001/call_2_error.json').read_text())
            self.assertEqual(failure['failure_type'],'APIConnectionError')
            self.assertEqual(failure['metrics']['provider_failures'],1)
            self.assertNotIn('DO_NOT_SAVE',json.dumps(failure))
            self.assertNotIn('private.invalid',json.dumps(failure))

    def test_native_ev_rejection_is_visible_without_model_benefit_claim(self):
        suite=self.loop.appliance_suite
        initial=deepcopy(self.good['appliances'])
        initial.update(ev_charge_start_h=17,ev_charge_end_h=8)
        self.runner._adaptive_v3_apply_appliance_actions(suite,initial,89)
        short=deepcopy(initial)
        short.update(ev_charge_start_h=19.5,ev_charge_end_h=23.882)
        report=self.runner._adaptive_v3_apply_appliance_actions(suite,short,90)
        self.assertIn({'service':'ev','reason':'existing_target_window_preserved'},report['rejections'])
        decision={'application':report,'explanation':'电动车已经避峰，每次节省20元。'}
        before=deepcopy(decision)
        visible=execution_explanation(decision)
        self.assertIn('保留已有充电窗口',visible)
        self.assertIn('未执行本次调整',visible)
        self.assertNotIn('节省20元',visible)
        self.assertEqual(decision,before)

    def test_unchanged_valid_plan_is_not_forced_to_change_after_event(self):
        _,_,saved = self.run_planner([self.good,self.good])
        inputs = saved['planning_input.json']['inputs']
        inputs['event'] = {}
        inputs['explicit_constraints'] = [c for c in inputs['explicit_constraints']
            if 'outside_vpp_window' not in c['constraint_id']]
        inputs['observable_state']['ordinary_plan'] = deepcopy(self.good)
        result = resolve(portfolio(self.good),inputs=inputs,loop=self.loop,
            config=self.config,sim_h=92,horizon=104,bounds=self.bounds,event=None,
            ask=lambda *_args,**_kw:self.fail('no event review should run'))
        self.assertEqual(result['selected_executable_plan']['appliances'],self.good['appliances'])

    def test_real_ep_receives_model_repair_and_retains_review_audit(self):
        from common import write_json
        from legacy_paired_worker import run_legacy as run
        from energybridge.llm.client import LLMClient
        bad = deepcopy(self.good)
        bad['appliances'].update(water_heater_preheat=True,
            water_heater_preheat_start_h=20,water_heater_preheat_end_h=22)
        bad['appliances'].pop('water_heater_preheat_temp_c',None)
        calls = []
        def fake_model(_client, system, user, **kwargs):
            calls.append(user)
            # First model response reproduces the missing-temperature failure;
            # subsequent responses are deterministic, explicitly valid fixtures.
            return {'text':portfolio(bad if len(calls)==1 else self.good),
                    'metrics':{'fixture':True}}
        with tempfile.TemporaryDirectory() as tmp, redirect_stdout(StringIO()):
            folder = Path(tmp)
            write_json(folder/'request.json',self.request)
            with patch.object(LLMClient,'chat_with_metrics',new=fake_model):
                run(folder)
            result = json.loads((folder/'outcome.json').read_text())
            self.assertEqual(result['simulation_status'],'paired_energyplus_complete')
            self.assertEqual(result['provenance']['fallback_rounds'],0)
            self.assertTrue(result['prediction']['prefix_check']['passed'])
            self.assertFalse(result['provenance']['eb_execution']['household_scorer_called'])
            self.assertIn('native_planning.py',result['provenance']['source_files_at_start'])
            purposes = [c['purpose'] for c in result['timings']['llm']['attempts']]
            self.assertIn('semantic_repair',purposes)
            self.assertIn('evidence_review',purposes)
            decisions = result['proposal_plan']['decisions']
            self.assertTrue(all(not d['application']['rejections'] for d in decisions),
                            [d['application']['rejections'] for d in decisions])
            washer = next(r for r in result['display']['rows'] if r['device_id']=='washer')
            self.assertTrue(washer['changed'])
            self.assertIn('20:00',washer['proposal'])
            self.assertFalse((folder/'decision.json').exists())


if __name__=='__main__':
    unittest.main()
