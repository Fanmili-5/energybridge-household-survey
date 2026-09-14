"""Native entry, real EP meters and human-only target integration regressions."""
import ast
from contextlib import redirect_stdout
from copy import deepcopy
from io import StringIO
import inspect
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from common import normalize_answers, write_json, digest
from paired_contract import LOOKUP, prepare, sanitize_profile, validate
from verify_paired_physics import answers
from native_runner import collection_entry, run_native, _disable_sdk_retries
from eb_execution import upstream


def request(ac_only=False):
    raw=answers()
    if ac_only:raw['B05']=['ac']
    profile=sanitize_profile(normalize_answers(raw,list(LOOKUP),LOOKUP))
    original,scenario=prepare(profile,'native-regression')
    return {'profile':profile,'original_plan':original,'scenario':scenario,
            'household_id':'native-regression-household'}


class NativeRunnerTests(unittest.TestCase):
    def test_disabled_acceptance_gate_is_not_a_fallback(self):
        from native_worker import native_plan_outcomes
        for status,expected in [('acceptance_fallback_disabled',False),('executed',False),('fallback',True),('fallback_after_rejection',True)]:
            native={'all_day_decisions':[[{'h':19,'adaptive_decision_audit':{'plan_lifecycle':{'stages':{'consented_plan':{'status':status}}}}}]]}
            self.assertEqual(native_plan_outcomes(native)[0]['fallback_used'],expected,status)

    def test_sdk_transport_retries_are_disabled_without_changing_eb_retry_loop(self):
        class Client:
            max_retries=2
            def copy(self, **kwargs):
                self.copied=kwargs
                updated=Client();updated.max_retries=kwargs['max_retries'];return updated
        original=Client();updated=_disable_sdk_retries(original)
        self.assertEqual(updated.max_retries,0)
        self.assertEqual(original.copied,{'max_retries':0})
        self.assertIs(_disable_sdk_retries(updated),updated)

    def test_unavailable_native_metrics_remain_unknown_in_storage(self):
        from native_runner import storage_snapshot
        v=storage_snapshot({'metric':float('nan'),'score':None,'nested':[float('inf'),2.5]})
        self.assertIsNone(v['metric']);self.assertIsNone(v['score'])
        self.assertEqual(v['nested'],[None,2.5])
        self.assertEqual(v['serialization']['nonfinite_as_null'],['/metric','/nested/0'])
        json.dumps(v,allow_nan=False)

    def test_current_worker_does_not_load_legacy_execution(self):
        import subprocess,sys
        proc=subprocess.run([sys.executable,'-c',"import paired_worker,sys; assert 'closed_loop' not in sys.modules; assert 'paired_ep' not in sys.modules; assert 'eb_execution' not in sys.modules; assert 'native_planning' not in sys.modules"],capture_output=True,text=True)
        self.assertEqual(proc.returncode,0,proc.stderr)

    def test_all_questionnaire_answers_reach_native_input_memory(self):
        from household_config import ensure_household_config
        from native_runner import native_boundaries
        runner,_=upstream();house=ensure_household_config(request())
        self.assertGreater(len(house['onboarding']['answers']),30)
        from energybridge.harness import memory_v3,profile_v3
        with native_boundaries(runner,house,[],[],lambda *args:None):
            inputs=runner._observable_agent_onboarding_projection(runner._run_agent_onboarding_questionnaire(house))
            memory=memory_v3.initialize_memory_v3(inputs,household_id=house['id'])
            model=profile_v3.initialize_household_model(inputs,household_id=house['id'],calendar=house['calendar'],devices=house['appliances'])
        expected={a['id'].lower() for a in inputs['answers']}
        self.assertEqual(expected,{a['id'].lower() for a in memory['onboarding']['answers']})
        self.assertTrue(expected <= {str(e.get('source_ref','')).lower() for e in model['evidence_index']})

    def test_native_callback_is_identical_to_upstream(self):
        runner,_=upstream()
        _,source=collection_entry(runner)
        original=ast.parse(inspect.getsource(runner.run_family_agent))
        derived=ast.parse(source)
        a=next(n for n in ast.walk(original) if isinstance(n,ast.FunctionDef) and n.name=='cb')
        b=next(n for n in ast.walk(derived) if isinstance(n,ast.FunctionDef) and n.name=='cb')
        self.assertEqual(ast.dump(a),ast.dump(b))

    def test_native_deadline_and_binding_contract(self):
        r=request()
        self.assertEqual(r['scenario']['evaluation_window']['end_sim_h'],24)
        self.assertEqual(r['scenario']['evaluation_window']['ev_departure_sim_h'],32)
        from household_config import ensure_household_config
        h=ensure_household_config(r)
        self.assertEqual(len(h['calendar']['days']),1)
        self.assertEqual(len(h['calendar']['household_occupancy_hourly']),1)
        self.assertEqual(r['scenario']['event']['day'],1)
        with self.assertRaises(ValueError):validate(r['original_plan'],{'execution_mode':'eb_closed_loop'},r['scenario'])
        self.assertEqual(r['scenario']['evaluation_window']['start_sim_h'],0)
        with self.assertRaises(ValueError):validate(r['original_plan'],{'execution_mode':'eb_native_loop','decisions':[]},r['scenario'])

    @unittest.skipUnless(os.environ.get('EB_TEST_NATIVE_EP')=='1','requires installed EnergyPlus')
    def test_base_template_preserves_single_day_simulation(self):
        from common import UPSTREAM, file_hash
        from paired_contract import CONTEXT
        upstream()
        from experiments.benchmark import run_persona_json
        from native_assets import idf_objects
        old_prepare = run_persona_json._prepare_run_assets
        def legacy_template(args, *a, **kw):
            args.idf = UPSTREAM/'experiments/models/family_home/family_simple_3day.idf'
            return old_prepare(args, *a, **kw)
        with tempfile.TemporaryDirectory() as tmp, redirect_stdout(StringIO()):
            r = request()
            current = run_native(Path(tmp)/'current', r, method='no_dr')
            with patch.object(run_persona_json, '_prepare_run_assets', side_effect=legacy_template):
                previous = run_native(Path(tmp)/'previous', r, method='no_dr')
            self.assertEqual(len(current['electricity']), 144)
            self.assertEqual(current['electricity'], previous['electricity'])
            self.assertEqual(current['temperature'], previous['temperature'])
            self.assertEqual(current['native']['no_dr_routine_actions'], previous['native']['no_dr_routine_actions'])
            self.assertEqual(current['native']['llm_call_count'], 0)
            self.assertEqual(previous['native']['llm_call_count'], 0)
            source = current['asset_binding']['source_template']
            self.assertEqual(source['path'], 'experiments/models/family_home/family_simple.idf')
            self.assertEqual(source['sha256'], file_hash(UPSTREAM/source['path']))
            self.assertEqual(source['simulation_days'], 1)
            self.assertEqual(r['scenario']['building']['source'], 'family_simple.idf')
            generated = list((Path(tmp)/'_run_assets'/'current').glob('*.idf'))
            self.assertEqual(len(generated), 1)
            periods = [o for o in idf_objects(generated[0].read_text()) if o[0].lower()=='runperiod']
            self.assertEqual(len(periods), 1)
            self.assertEqual(periods[0][2:4], periods[0][5:7])

    @unittest.skipUnless(os.environ.get('EB_TEST_NATIVE_EP')=='1','requires installed EnergyPlus')
    def test_repaired_assets_bind_native_ports_without_changing_controller(self):
        with tempfile.TemporaryDirectory() as tmp,redirect_stdout(StringIO()):
            r=run_native(Path(tmp)/'baseline',request(),method='no_dr')
            self.assertEqual(r['native']['llm_call_count'],0)
            self.assertEqual(len(r['electricity']),144)
            self.assertEqual(r['service_evidence']['ev']['status'],'observed')
            self.assertEqual(r['service_evidence']['water_heater']['status'],'observed')
            self.assertEqual(r['service_evidence']['water_heater']['delivered_water_status'],'unverified')
            self.assertTrue((Path(tmp)/'baseline/service_evidence.json').is_file())
            self.assertEqual(r['asset_binding']['unbound_native_device_ports'],[])
            self.assertTrue(r['asset_binding']['equipment_changes'])
            self.assertFalse(r['asset_binding']['control_changes'])
            self.assertTrue(any(row['native_device_power_kw'].get('washer',0)>0 for row in r['controls']))
            self.assertTrue(any(row['actuators'].get('washer',0)>0 for row in r['controls']))
            self.assertEqual(r['native']['day_ahead_price_metrics']['price_unit'],'normalized TOU cost/kWh')
            self.assertEqual(r['asset_binding']['tariff']['id'],'eb_tianjin_normalized_tou_v1')
            self.assertEqual(len(r['asset_binding']['tariff']['sha256']),64)
            runner,_=upstream()
            with patch('native_runner.collection_entry',return_value=(runner.run_family_agent,inspect.getsource(runner.run_family_agent))):
                original=run_native(Path(tmp)/'original',request(),method='no_dr')
            self.assertEqual(r['electricity'],original['electricity'])
            self.assertEqual(r['temperature'],original['temperature'])
            self.assertEqual(r['native']['no_dr_routine_actions'],original['native']['no_dr_routine_actions'])

    @unittest.skipUnless(os.environ.get('EB_TEST_NATIVE_EP')=='1','requires installed EnergyPlus')
    def test_complete_native_pair_saves_pending_scores_and_shown_view(self):
        from native_worker import run
        runner,_=upstream()
        from energybridge.llm.client import LLMClient
        def model(client,system,user,**kwargs):
            if force_fallback:return {'text':'{}','metrics':{'fixture':True}}
            if '[PLANNING PAYLOAD]' in user:
                payload=json.JSONDecoder().raw_decode(user.split('[PLANNING PAYLOAD]',1)[1].lstrip())[0]
                state=payload.get('observable_state',{})
                event=payload.get('event',{})
                plan={'setpoint':25.0,'appliances':{},'next_check_hour':None}
                text=json.dumps({'candidate_plans':[{'id':'fixture','plan':plan}],
                                 'selected_candidate_id':'fixture','selection_reason':'工程测试，维持设定温度。'})
            else:
                # A native optional request must still go through its own
                # validation; this fixture does not invent household labels.
                text='{}'
            return {'text':text,'metrics':{'fixture':True}}
        for force_fallback in (False,True):
            with tempfile.TemporaryDirectory() as tmp,redirect_stdout(StringIO()):
                folder=Path(tmp);r=request(ac_only=True);write_json(folder/'request.json',r)
                with patch.object(LLMClient,'chat_with_metrics',new=model), \
                     patch.object(runner,'_evaluate_vpp_plan_acceptance_gate',side_effect=AssertionError('synthetic consent gate called')), \
                     patch.object(runner,'_fallback_plan_after_vpp_rejection',side_effect=AssertionError('extra acceptance fallback called')), \
                     patch.object(runner,'_call_roleplay_acceptance_gate_llm',side_effect=AssertionError('synthetic consent called')):
                    run(folder)
                result=json.loads((folder/'outcome.json').read_text())
                if os.environ.get('EB_NATIVE_TEST_ARTIFACT'):
                    write_json(Path(os.environ['EB_NATIVE_TEST_ARTIFACT']+('-fallback' if force_fallback else '-valid')+'.json'),result)
                native=json.loads((folder/'proposal/native_result.json').read_text())
                self.assertEqual(result['execution_mode'],'eb_native_loop')
                if force_fallback:
                    self.assertTrue(any(x['fallback_used'] for x in result['provenance']['native_plan_outcomes']))
                    self.assertIn('回退安排',result['display']['execution_notice'])
                self.assertTrue(result['prediction']['comparison_check']['passed'])
                self.assertIsNone(result['prediction']['prefix_check']['passed'])
                self.assertEqual(native['vpp_plan_gate_events'],[])
                self.assertEqual(native['user_pref_scores'],[])
                self.assertEqual(native['vpp_event_log'][0]['source'],'human_pending')
                self.assertIsNone(native['vpp_event_log'][0]['score'])
                self.assertTrue(native['human_evaluation_pending'])
                self.assertEqual(digest(result['display']),result['display_hash'])
                validate(r['original_plan'],result['proposal_plan'],r['scenario'])
                self.assertFalse((folder/'decision.json').exists())
                self.assertFalse((folder/'sft_candidate.json').exists())
                self.assertTrue(list((folder/'proposal/model_calls').glob('*/request.json')))
                from paired_contract import QUESTIONS
                from proposal_contract import decision_record, candidate
                job={**r,'id':'native-feedback-fixture','result':result,'flow':'paired_ep_v1',
                     'questionnaire_snapshot':QUESTIONS,'data_origin':'synthetic_engineering_test',
                     'respondent_id':'fixture'}
                payload={key:result[key] for key in ('display_hash','original_plan_hash','proposal_plan_hash')}
                payload.update(choice='reject',score=2.5,comfort_score=2,energy_score=4.2,vpp_score=1.5,comment='工程测试反馈')
                decision=decision_record(job,payload)
                example=candidate(job,decision)
                self.assertEqual(json.loads(example['messages'][1]['content'])['display'],result['display']['participant_view'])
                self.assertEqual(json.loads(example['messages'][2]['content'])['decision'],'reject')
                self.assertEqual(example['baseline_plan_hash'],result['baseline_plan_hash'])
                with self.assertRaises(ValueError):decision_record(job,{**payload,'display_hash':'different'})

if __name__=='__main__':unittest.main()
