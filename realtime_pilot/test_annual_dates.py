"""Annual intake dates, immutable contexts, and seasonal native EP without paid API."""
from copy import deepcopy
from contextlib import redirect_stdout
from io import StringIO
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from common import digest,write_json
from date_sampling import assigned_context,verify_context,annual_sample
from test_simulation_environment import request
import simulation_environment as env


def context_for_month(month):
    return next(c for i in range(10000) if (c:=assigned_context('annual-fixture-'+str(i)))['date'][5:7]==f'{month:02d}')

def annual_request(month,**changes):
    from paired_contract import prepare
    r=request(**changes)
    r['original_plan'],r['scenario']=prepare(r['profile'],'annual-offline',environment_required=True,context=context_for_month(month))
    return r

class AnnualDatesTests(unittest.TestCase):
    def test_uniform_calendar_context_freezes_and_spans_all_months(self):
        contexts=[assigned_context('participant-'+str(i)) for i in range(2000)]
        self.assertEqual({c['date'][5:7] for c in contexts},{f'{i:02d}' for i in range(1,13)})
        self.assertGreater(len({c['date'] for c in contexts}),350)
        self.assertEqual(contexts[0],assigned_context('participant-0'))
        self.assertNotIn('participant-0',json.dumps(contexts[0]))
        self.assertEqual(contexts[0]['date_probability'],1/365)
        bad=deepcopy(contexts[0]);bad['date']='2007-02-29'
        bad['context_hash']=digest({k:v for k,v in bad.items() if k!='context_hash'})
        with self.assertRaises(ValueError):verify_context(bad)

    def test_annual_environment_checks_weather_and_frozen_sampling(self):
        for month in (1,4,7,10):
            r=annual_request(month);e=r['scenario']['environment']
            self.assertTrue(all(p.is_file() for p in env.verify(e)))
            self.assertEqual(e['simulation_start_date'],r['scenario']['questionnaire_context']['date'])
            self.assertEqual(e['date_sampling']['validation_status_at_assignment'],'pending_case_baseline')
            from paired_contract import prepare
            _,again=prepare(r['profile'],'different-vpp-seed',context=r['scenario']['questionnaire_context'])
            self.assertEqual(again['environment'],e)
            bad=deepcopy(e);bad['date_sampling']['selected_weather']['mean_dry_bulb_c']+=1
            bad['environment_hash']=digest({k:v for k,v in bad.items() if k!='environment_hash'})
            with self.assertRaises(ValueError):env.verify(bad)

    def test_context_required_and_stored_separately_from_raw_answers(self):
        from test_household_intake import HouseholdIntakeTests
        t=HouseholdIntakeTests();t.setUp()
        try:
            payload=t.payload();bad=deepcopy(payload);bad.pop('questionnaire_context_hash')
            with self.assertRaisesRegex(ValueError,'日期'):t.store.save_household('owner',bad)
            bad['questionnaire_context_hash']=assigned_context('other')['context_hash']
            with self.assertRaises(ValueError):t.store.save_household('owner',bad)
            receipt=t.store.save_household('owner',payload)
            row=t.store.household_owned(receipt['id'],'owner')
            self.assertEqual(row['raw_answers'],payload['answers'])
            self.assertEqual(row['household_record']['questionnaire_context'],assigned_context('owner'))
            job=t.store.create('owner',t.generate(receipt['id']),paired_flow=True)
            self.assertEqual(job['scenario']['questionnaire_context'],row['questionnaire_context'])
            self.assertEqual(t.store.db.document(job['id'],'questionnaire_submission.json')['questionnaire_context'],row['questionnaire_context'])
        finally:t.tearDown()

    def test_baseline_failure_cannot_start_planning_or_resample(self):
        from native_worker import run
        with tempfile.TemporaryDirectory() as tmp:
            folder=Path(tmp);r=annual_request(1);write_json(folder/'request.json',r)
            with patch('native_worker.run_native',side_effect=RuntimeError('fixture EP failure')) as native,patch('runtime_config.load_model_environment'):
                with self.assertRaises(RuntimeError):run(folder)
            self.assertEqual(native.call_count,1)
            self.assertEqual(native.call_args.kwargs['method'],'no_dr')
            v=json.loads((folder/'date_validation.json').read_text())
            self.assertFalse(v['planning_started']);self.assertEqual(v['status'],'failed')
            self.assertEqual(v['date'],r['scenario']['simulation_start_date'])
            self.assertFalse((folder/'outcome.json').exists())

    @unittest.skipUnless(os.environ.get('EB_TEST_NATIVE_EP')=='1','requires installed EnergyPlus')
    def test_native_non_summer_days_no_model_calls(self):
        from native_runner import run_native
        for month in (1,4,10):
            with tempfile.TemporaryDirectory() as tmp,redirect_stdout(StringIO()):
                r=annual_request(month,X_REGION='北京',X_CITY='北京',X_BUILDING='detached',X_FLOOR=None)
                out=run_native(Path(tmp)/'baseline',r,method='no_dr')
                self.assertEqual(out['native']['llm_call_count'],0)
                self.assertEqual(len(out['electricity']),round(r['scenario']['evaluation_window']['end_sim_h']*6))
                self.assertEqual(out['asset_binding']['simulation_environment'],r['scenario']['environment'])

    @unittest.skipUnless(os.environ.get('EB_TEST_NATIVE_EP')=='1','requires installed EnergyPlus')
    def test_native_winter_pair_feedback_and_sft_using_offline_model_fixture(self):
        from test_native_runner import NativeRunnerTests
        from regional_test_support import answers
        def winter(ac_only=False):
            return annual_request(1,B05=['ac'] if ac_only else answers()['B05'],X_REGION='北京',X_CITY='北京')
        with patch('test_native_runner.request',side_effect=winter),patch.dict(os.environ,USE_LLM='1',LLM_API_KEY='offline-fixture',LLM_MODEL='offline-fixture',LLM_BASE_URL='http://127.0.0.1:9/v1'):
            NativeRunnerTests('test_complete_native_pair_saves_pending_scores_and_shown_view').test_complete_native_pair_saves_pending_scores_and_shown_view()
