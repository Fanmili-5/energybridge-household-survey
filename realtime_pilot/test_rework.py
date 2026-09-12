"""Regression evidence for native fallback, display and human-label contract."""
import ast
from contextlib import redirect_stdout
from copy import deepcopy
from io import StringIO
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from common import ROOT, UPSTREAM, normalize_answers
from paired_contract import LOOKUP, QUESTIONS, prepare
from questionnaire_persona import visible_profile
from verify_paired_physics import answers
from eb_execution import upstream
from eb_controller_adapter import native_fallback, control_context
from closed_loop import display_trajectory
from proposal_contract import decision_record

from legacy_test_support import prepare


class ReworkTests(unittest.TestCase):
    def request(self):
        profile=normalize_answers(answers(),list(LOOKUP),LOOKUP)
        original,scenario=prepare(profile,'rework-regression')
        # Historical custom-loop regression; not evidence for the native entry.
        from evaluation_window import make_window
        scenario['evaluation_window']=make_window(original)
        return {'profile':profile,'original_plan':original,'scenario':scenario,
                'observable_profile':visible_profile(profile,QUESTIONS)}

    def test_fallback_matches_extracted_native_closure(self):
        runner,_=upstream();loop=runner._FamilyLoop();context=control_context(loop)
        source=ast.parse((UPSTREAM/'experiments/benchmark/family_runner.py').read_text())
        branch=next(n for n in ast.walk(source) if isinstance(n,ast.If) and isinstance(n.test,ast.Name) and n.test.id=='vpp_active' and any(isinstance(x,ast.Assign) and any(isinstance(t,ast.Name) and t.id=='fb_sp' for t in x.targets) for x in n.body))
        body=ast.Module(body=[branch],type_ignores=[]);code=compile(ast.fix_missing_locations(body),'<pinned EB fallback>','exec')
        event={'trigger_h':90,'end_h':91}
        for now in (89,90,90.5,91):
            for temp in (20,24,29):
                env={'vpp_active':90<=now<91,'_run_sp_max':context['maximum_c'],'_run_sp_min':context['minimum_c'],
                     '_ac_sp_default':context['default_c'],'agent_memory_protective':context['protective'],
                     '_protective_mode':context['protective'],'temp':temp}
                exec(code,env)
                actual=native_fallback(loop,now,temp,event)
                self.assertEqual(actual,{'setpoint':env['fb_sp'],'next_check_hour':env['fb_nch'],'appliances':{}})

    def test_power_change_and_unfinished_task_are_visible(self):
        request=self.request();original=request['original_plan']
        def run(power, completed):
            return {'controls':[{'start_h':94,'end_h':96,'hvac_available':False,'cooling_setpoint':40,'actuators':{'ev':power}}],
                    'decisions':[],'execution':{'services':{'washer':[{'day':3,'completed':completed}]}}}
        display=display_trajectory(original,run(.5,True),run(1,False),request['scenario'],{})
        ev=next(r for r in display['rows'] if r['device_id']=='home_ev')
        self.assertTrue(ev['changed']);self.assertIn('3.500 kW',ev['original']);self.assertIn('7.000 kW',ev['proposal'])
        washer=next(r for r in display['service_rows'] if r['device']=='洗衣机')
        self.assertIn('已完成',washer['original']);self.assertIn('尚未完成',washer['proposal'])

    def test_api_failure_uses_fallback_and_logs_failed_attempt(self):
        from closed_loop import EBPlanner
        runner,Suite=upstream();request=self.request();loop=runner._FamilyLoop()
        loop.appliance_suite=Suite(request['original_plan']['eb_appliance_config'],sim_days=4,explicit_only=True)
        from energybridge.llm.client import LLMClient
        with tempfile.TemporaryDirectory() as directory:
            planner=EBPlanner(request,Path(directory),lambda *args:None)
            with patch.object(LLMClient,'chat_with_metrics',side_effect=TimeoutError('fixture')):
                plan,explanation=planner(loop,92+1/3,{'temperature_c':25,'outdoor_c':30,'facility_w':1000},[],['next_check'])
            self.assertTrue(planner.last_audit['fallback_used']);self.assertEqual(len(planner.calls),1)
            self.assertEqual(planner.calls[0]['status'],'failed');self.assertIn('回退',explanation)
            prompt=json.loads((Path(directory)/'round_001/call_1_request.json').read_text())
            self.assertIn('current clock=20:20',prompt['user_prompt'])
            self.assertTrue((Path(directory)/'round_001/call_1_error.json').exists())

    def test_four_scores_required_only_for_new_contract(self):
        hashes={k:'same' for k in ('display_hash','original_plan_hash','proposal_plan_hash')}
        job={'result':dict(hashes),'data_origin':'synthetic_engineering_test'}
        payload={**hashes,'choice':'reject'}
        self.assertIsNone(decision_record(job,payload)['score'])
        job['result']['feedback_contract']={'required_scores':['score','comfort_score','energy_score','vpp_score']}
        with self.assertRaises(ValueError):decision_record(job,payload)
        scores={'score':3,'comfort_score':2,'energy_score':4,'vpp_score':2}
        result=decision_record(job,{**payload,**scores})
        self.assertEqual({k:result[k] for k in scores},scores)

    def test_reason_is_required_only_when_declared_by_feedback_contract(self):
        hashes={k:'same' for k in ('display_hash','original_plan_hash','proposal_plan_hash')}
        scores={'score':3,'comfort_score':2,'energy_score':4,'vpp_score':2}
        job={'result':{**hashes,'feedback_contract':{'required_scores':list(scores),'required_comment':True}},
             'data_origin':'synthetic_engineering_test'}
        with self.assertRaisesRegex(ValueError,'最主要原因'):
            decision_record(job,{**hashes,**scores,'choice':'reject','comment':'   '})
        result=decision_record(job,{**hashes,**scores,'choice':'reject','comment':'影响晚饭时间'})
        self.assertEqual(result['comment'],'影响晚饭时间')
        self.assertEqual(result['comment_status'],'answered')

    def test_real_ep_completes_with_invalid_model_and_retains_exact_prompts(self):
        from common import write_json
        from legacy_paired_worker import run_legacy as run
        runner,_=upstream()
        from energybridge.llm.client import LLMClient
        with tempfile.TemporaryDirectory() as directory,redirect_stdout(StringIO()):
            folder=Path(directory);write_json(folder/'request.json',self.request())
            with patch.object(LLMClient,'chat_with_metrics',return_value={'text':'not json','metrics':{'fixture':True}}):
                run(folder)
            result=json.loads((folder/'outcome.json').read_text())
            from paired_contract import VERSION
            self.assertEqual(result['schema_version'],VERSION)
            for branch in ('baseline','proposal'):
                trace=json.loads((folder/branch/'trace.json').read_text())
                self.assertEqual(trace['evaluation_window']['end_sim_h'],104)
                self.assertEqual(trace['ev_departure']['sim_h'],104)
                departure=trace['ev_departure']
                self.assertEqual(departure['target_met'],departure['soc']>=departure['target_soc']-1e-6)
                if branch=='baseline':self.assertTrue(departure['target_met'])
                else:
                    # Native fallback issues no new appliance commands at
                    # midnight. Do not silently reapply P0 to guarantee success.
                    self.assertFalse(departure['target_met'])
                    ev=next(row for row in result['display']['service_rows'] if row['device']=='家用电动车充电')
                    self.assertIn('未达到',ev['proposal'])
                self.assertAlmostEqual(trace['task_energy_checks']['ev']['native_charge_kwh'],trace['task_energy_checks']['ev']['metered_kwh'],places=6)
                self.assertTrue(trace['water_outcome']['draws'])
                self.assertEqual(trace['water_outcome']['demand_schedule'],'shared research template')
                self.assertGreater(result['prediction'][branch if branch=='proposal' else 'original']['next_day_kwh'],0)
            decisions=result['proposal_plan']['decisions']
            self.assertGreaterEqual(len(decisions),3)
            self.assertTrue(all(d['controller']['fallback_used'] for d in decisions))
            self.assertEqual(result['provenance']['fallback_rounds'],len(decisions))
            self.assertTrue(result['prediction']['prefix_check']['passed'])
            self.assertFalse(result['provenance']['source_changed_during_run'])
            self.assertIn('paired_ep.py',result['provenance']['source_files_at_start'])
            self.assertEqual(result['display']['service_rows'],result['display']['participant_view']['service_rows'])
            first=json.loads((folder/'planning/round_001/planning_input.json').read_text())
            call=json.loads((folder/'planning/round_001/call_1_request.json').read_text())
            self.assertEqual(first['user_prompt'],call['user_prompt']);self.assertIn('CURRENT DECISION CLOCK',call['user_prompt'])
            repairs=list((folder/'planning/round_001').glob('call_*_request.json'))
            self.assertGreaterEqual(len(repairs),2)
            # No labels were manufactured as a side effect of fallback.
            self.assertFalse((folder/'decision.json').exists());self.assertFalse((folder/'sft_candidate.json').exists())
            from proposal_contract import candidate
            request=self.request()
            job={'id':'fixture','result':result,'data_origin':'synthetic_engineering_test','flow':'paired_ep_v1',
                 'profile':request['profile'],'questionnaire_snapshot':QUESTIONS,'household_id':'engineering-household',
                 'respondent_id':'engineering-respondent','original_plan':request['original_plan']}
            scores={'score':3,'comfort_score':2,'energy_score':4,'vpp_score':2}
            decision=decision_record(job,{'choice':'reject','comment':'工程测试回答',**scores,
                **{k:result[k] for k in ('display_hash','original_plan_hash','proposal_plan_hash')}})
            row=candidate(job,decision)
            self.assertEqual(json.loads(row['messages'][1]['content'])['display'],result['display']['participant_view'])
            self.assertEqual(json.loads(row['messages'][2]['content']),{'decision':'reject','comment':'工程测试回答',**scores})
            self.assertEqual(row['assessment_stage'],'after_simulated_trajectory_before_real_execution')
            self.assertEqual(row['feedback_completeness'],'four_scores');self.assertFalse(row['training_release'])

if __name__=='__main__':unittest.main()
