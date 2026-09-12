from date_sampling import assigned_context
"""Regional matching, immutable input provenance and real native EP integration."""
from copy import deepcopy
from contextlib import redirect_stdout
from io import StringIO
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from common import normalize_answers,digest,write_json
from paired_contract import LOOKUP,QUESTIONS,QUESTIONNAIRE_VERSION,CONTEXT,prepare,sanitize_profile
from regional_test_support import answers
import simulation_environment as env


def request(**changes):
    profile=sanitize_profile(normalize_answers(answers(**changes),list(LOOKUP),LOOKUP))
    original,scenario=prepare(profile,'regional-offline-fixture',environment_required=True)
    return {'profile':profile,'original_plan':original,'scenario':scenario,
            'household_id':'synthetic-regional-test'}


class RegionalTests(unittest.TestCase):
    def test_cloud_and_compute_release_hashes_agree(self):
        from compute_protocol import release_hash
        self.assertEqual(release_hash(verify_resources=False),release_hash())

    def test_match_changes_physical_assets_not_raw_family_or_eb_controls(self):
        a=request();b=request(X_REGION='上海',X_CITY='上海市',X_AREA='50_89',X_FLOOR='top')
        self.assertEqual(a['original_plan'],b['original_plan'])
        self.assertNotEqual(a['scenario']['environment']['weather']['epw_sha256'],b['scenario']['environment']['weather']['epw_sha256'])
        self.assertNotEqual(a['scenario']['environment']['building']['sha256'],b['scenario']['environment']['building']['sha256'])
        self.assertEqual(b['scenario']['environment']['building']['indoor_area_m2'],70)
        self.assertFalse(b['scenario']['environment']['calibrated_to_household'])
        for r in (a,b):self.assertTrue(all(p.is_file() for p in env.verify(r['scenario']['environment'])))
        self.assertEqual(a['scenario']['tariff'],b['scenario']['tariff'])

    def test_seed_freezes_date_and_does_not_use_attitudes_or_ratings(self):
        a=request();p=deepcopy(a['profile']);p['X_INCOME']={'response_status':'answered','value':'ge30000'}
        first=env.resolve(p,'fixed');second=env.resolve(a['profile'],'fixed')
        self.assertEqual(first,second)
        self.assertIn(first['simulation_start_date'],first['date_sampling']['pool'])
        self.assertFalse(first['date_sampling']['uses_ratings'])
        dates={env.resolve(p,str(seed))['simulation_start_date'] for seed in range(20)}
        self.assertGreater(len(dates),1)

    def test_tamper_and_failed_dates_cannot_enter_compute(self):
        a=request()['scenario']['environment'];bad=deepcopy(a);bad['weather']['city']='伪造城市'
        with self.assertRaises(ValueError):env.verify(bad)
        bad['environment_hash']=digest({k:v for k,v in bad.items() if k!='environment_hash'})
        with self.assertRaises(ValueError):env.verify(bad)
        c=env.catalog();report=json.loads((env.CATALOG.parent/'validation.json').read_text())
        for row in report['results']:
            if not row['passed']:
                self.assertNotIn(row['date'],c['validated_dates'].get(row['model_id']+'|'+row['weather_id'],[]))

    def test_unsupported_answers_save_but_do_not_queue_or_call_model(self):
        from server import Store
        from test_pilot import NoExecute
        with tempfile.TemporaryDirectory() as tmp:
            store=Store(tmp,human_pilot=True);store.pool.shutdown();store.pool=NoExecute()
            try:
                raw=answers(X_REGION='outside_china',X_CITY='Tokyo')
                receipt=store.save_household('owner',{'questionnaire_context_hash':assigned_context('owner')["context_hash"],'answers':raw,'request_id':'regional_intake_test_0001',
                    'questionnaire_version':QUESTIONNAIRE_VERSION,'questionnaire_hash':digest(QUESTIONS),
                    'research_consent':True,'research_notice_version':'eb.research_notice.v1'})
                self.assertEqual(receipt['environment_readiness']['status'],'unavailable')
                self.assertEqual(store.db.household(receipt['id'])['raw_answers'],raw)
                with patch('server.subprocess.Popen') as launch:
                    with self.assertRaisesRegex(ValueError,'地区'):
                        store.create('owner',{'submission_id':receipt['id'],'request_id':'regional_generate_test_0001',
                          'scenario_id':CONTEXT['id'],'scenario_understood':True},paired_flow=True)
                    launch.assert_not_called()
                self.assertEqual(len(store.jobs),0)
            finally:store.db.close()

    def test_environment_reaches_native_onboarding_without_inventing_member_answers(self):
        from household_config import ensure_household_config
        from native_runner import native_boundaries
        from native_support import upstream
        r=request();h=ensure_household_config(r);runner,_=upstream()
        with native_boundaries(runner,h,[],[],lambda *args:None):
            projection=runner._observable_agent_onboarding_projection(runner._run_agent_onboarding_questionnaire(h))
        text=json.dumps(projection,ensure_ascii=False)
        self.assertIn('SIMULATION_ENVIRONMENT',text)
        self.assertIn('广州',text)
        self.assertIn(r['scenario']['simulation_start_date'],text)
        self.assertEqual(h['reported_members'],ensure_household_config(r)['reported_members'])

    def test_floor_is_inapplicable_for_detached_home(self):
        r=request(X_BUILDING='detached',X_FLOOR='top')
        self.assertEqual(r['profile']['X_FLOOR']['response_status'],'not_applicable')
        self.assertEqual(r['scenario']['environment']['building']['floor'],'whole')

    def test_provincial_proxy_preserves_reported_city_and_discloses_match(self):
        r=request(X_CITY='未列入站点的城市')
        e=r['scenario']['environment']
        self.assertEqual(e['reported_housing']['X_CITY'],'未列入站点的城市')
        self.assertEqual(e['weather']['province'],'广东')
        self.assertEqual(e['weather_match']['method'],'provincial_representative_proxy')
        self.assertFalse(e['weather_match']['nearest_station_claim'])
        self.assertIn('省内代表站',r['scenario']['facts'][1])

    def test_all_provincial_representatives_cover_registered_housing(self):
        c=env.catalog()
        self.assertEqual(len(c['province_representatives']),34)
        for province,wid in c['province_representatives'].items():
            for model in c['models']:
                self.assertTrue(c['validated_dates'].get(model['id']+'|'+wid),(province,model['id']))

    @unittest.skipUnless(os.environ.get('EB_TEST_NATIVE_EP')=='1','requires installed EnergyPlus')
    def test_native_baselines_use_three_real_regions_without_api(self):
        from native_runner import run_native
        for region,city,kind,floor in [('广东','广州','apartment','middle'),('上海','上海','apartment','top'),('北京','北京','detached',None)]:
            with tempfile.TemporaryDirectory() as tmp,redirect_stdout(StringIO()):
                r=request(X_REGION=region,X_CITY=city,X_BUILDING=kind,X_FLOOR=floor)
                result=run_native(Path(tmp)/'baseline',r,method='no_dr')
                self.assertEqual(result['native']['llm_call_count'],0)
                self.assertEqual(len(result['electricity']),144)
                self.assertEqual(result['asset_binding']['unbound_native_device_ports'],[])
                self.assertEqual(result['asset_binding']['simulation_environment'],r['scenario']['environment'])
                self.assertEqual(json.loads((Path(tmp)/'baseline/simulation_environment.json').read_text()),r['scenario']['environment'])

    @unittest.skipUnless(os.environ.get('EB_TEST_NATIVE_EP')=='1','requires installed EnergyPlus')
    def test_native_pair_and_human_sft_with_regional_environment(self):
        # Reuse the full native model-fixture/feedback/export assertions; substitute
        # only regional onboarding. Both accepted-candidate and fallback branches run.
        from test_native_runner import NativeRunnerTests
        def regional(ac_only=False):
            return request(B05=['ac'] if ac_only else answers()['B05'])
        with patch('test_native_runner.request',side_effect=regional), patch.dict(os.environ,USE_LLM='1',LLM_API_KEY='offline-fixture',LLM_MODEL='offline-fixture',LLM_BASE_URL='http://127.0.0.1:9/v1'):
            NativeRunnerTests('test_complete_native_pair_saves_pending_scores_and_shown_view').test_complete_native_pair_saves_pending_scores_and_shown_view()

if __name__=='__main__':unittest.main()
