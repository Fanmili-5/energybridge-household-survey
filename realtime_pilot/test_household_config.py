"""Verify custom household identity and evidence propagation, without presets."""
from copy import deepcopy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from common import normalize_answers,digest,UPSTREAM
from paired_contract import QUESTIONS,LOOKUP,prepare,CONTEXT
from verify_paired_physics import answers
from household_config import build_household_config,bind_household,ensure_household_config
from household_classification import feature_record
from eb_execution import upstream
from test_pilot import NoExecute
from server import Store

class HouseholdConfigTests(unittest.TestCase):
    def test_selected_devices_survive_json_and_native_device_initialization(self):
        from paired_contract import sanitize_profile
        from eb_execution import physical_defaults
        raw=answers();raw['B05']=['washer','home_ev']
        profile=sanitize_profile(normalize_answers(raw,list(LOOKUP),LOOKUP))
        original,scenario=prepare(profile,'selected-devices')
        config=ensure_household_config({'profile':profile,'original_plan':original,
            'scenario':scenario,'household_id':'selected-device-household'})
        saved=json.loads(json.dumps(config))
        self.assertEqual({d for d,c in saved['appliances'].items() if c['present']},{'washer','ev'})
        self.assertEqual(profile['H_ac_temp']['response_status'],'not_applicable')
        runner,Suite=upstream()
        suite=Suite(saved['appliances'],sim_days=4,explicit_only=True)
        runner._adaptive_v3_apply_appliance_actions(suite,saved['ordinary_plan']['appliances'],0)
        self.assertIsNotNone(suite)
        self.assertEqual(suite._ev.target_soc,float(raw['P_EV_TARGET']))
        self.assertEqual(suite._ev.min_soc,float(raw['P_EV_RESERVE']))
        for key in ('capacity_kwh','daily_drive_kwh'):
            self.assertEqual(saved['appliances']['ev'][key],physical_defaults()['ev'][key])
        raw['H_washer']='off'
        with self.assertRaises(ValueError):
            prepare(sanitize_profile(normalize_answers(raw,list(LOOKUP),LOOKUP)),'old-off-choice')

    def request(self,raw=None,identity='respondent_a'):
        profile=normalize_answers(raw or answers(),list(LOOKUP),LOOKUP)
        original,scenario=prepare(profile,'fixed-event')
        return {'profile':profile,'original_plan':original,'scenario':scenario,'household_id':identity}

    def test_preset_structures_but_no_preset_content_or_members(self):
        fixed=list((UPSTREAM/'energybridge/roleplay/households').glob('household_s*.json'))
        self.assertEqual(len(fixed),5)
        for file in fixed:
            row=json.loads(file.read_text());self.assertIn('appliances',row);self.assertIn('members',row)
        request=self.request();config=ensure_household_config(request)
        self.assertEqual(config['id'],'respondent_a');self.assertIsNone(config['meta']['preset_household_id'])
        for key in ('members','acceptance_profiles','scoring_policy'):self.assertNotIn(key,config)
        self.assertEqual(config['preferences'],{'notice_required_h':1.0})
        self.assertEqual(set(config['tags']),{'control'})
        self.assertEqual(config['appliances'],request['original_plan']['eb_appliance_config'])
        self.assertEqual(config['tags']['control'],'confirm_required')

    def test_native_memory_calendar_and_device_inputs_receive_this_household(self):
        runner,Suite=upstream();request=self.request();loop=runner._FamilyLoop();config=bind_household(loop,request)
        loop.appliance_suite=Suite(config['appliances'],sim_days=4,explicit_only=True)
        memory=loop.agent_preference_memory
        self.assertEqual(memory['owner']['household_id'],'respondent_a')
        onboarding={q['id']:q for q in memory['onboarding']['answers']}
        self.assertEqual(onboarding['a_eb_control']['selected_option_ids'],['confirm_required'])
        self.assertNotIn('thermostat_flexibility',onboarding)
        event=request['scenario']['event'];cal=runner._agent_observable_calendar_context(config,event)
        self.assertTrue(cal['available']);self.assertIn('washer',cal['appliance_deadlines'])
        self.assertEqual(cal['constraints']['next_departure_h'],8)
        from closed_loop import EBPlanner
        from energybridge.llm.client import LLMClient
        with tempfile.TemporaryDirectory() as folder:
            planner=EBPlanner(request,Path(folder),lambda *args:None)
            with patch.object(LLMClient,'chat_with_metrics',return_value={'text':'invalid','metrics':{}}):
                planner(loop,72+request['scenario']['decision_h'],{'temperature_c':25,'outdoor_c':30,'facility_w':1000,'occupancy_count':3},[],['notification'])
            saved=json.loads((Path(folder)/'round_001/planning_input.json').read_text())
            text=json.dumps(saved,ensure_ascii=False)
            self.assertIn('明确同意',text);self.assertIn('confirm_required',text)
            self.assertIn('washer',text);self.assertIn('unreported_preferences',saved['inputs']['observable_profile'])
            self.assertEqual(saved['household_config_hash'],digest(config))

    def test_fact_changes_and_attitude_changes_do_not_assign_a_class(self):
        a=self.request();ca=ensure_household_config(a)
        raw=answers();raw.update(H_ac_temp='27',P_COMFORT='5')
        b=self.request(raw);cb=ensure_household_config(b)
        self.assertEqual(cb['ordinary_plan']['setpoint'],27)
        self.assertNotEqual(ca['answers_hash'],cb['answers_hash'])
        self.assertNotEqual(ca['reported_preferences']['comfort_importance'],cb['reported_preferences']['comfort_importance'])
        self.assertEqual(ca['id'],cb['id'])
        raw=answers();raw['P_COST']='1';c=self.request(raw);cc=ensure_household_config(c)
        self.assertEqual(cc['reported_preferences']['cost_importance']['value'],'1')
        self.assertEqual(ca['appliances'],cc['appliances'])
        self.assertEqual(feature_record(a['profile']),feature_record(c['profile']))
        other=self.request(identity='respondent_b');self.assertNotEqual(ensure_household_config(other)['id'],ca['id'])
        self.assertFalse(cc['meta']['classification_used_for_configuration'])

    def test_missing_attitude_and_stale_config_rejected(self):
        raw=answers();raw.pop('P_COMFORT')
        with self.assertRaises(ValueError):self.request(raw)
        request=self.request();ensure_household_config(request)
        request['household_config']['tags']['price']='low_incentive'
        with self.assertRaises(ValueError):ensure_household_config(request)

    def test_job_request_and_saved_household_have_same_snapshot(self):
        with tempfile.TemporaryDirectory() as folder:
            store=Store(folder);store.pool.shutdown();store.pool=NoExecute()
            job=store.create('session-owner',{'request_id':'household_config_test_001','answers':answers(),
                'scenario_id':CONTEXT['id'],'scenario_understood':True},paired_flow=True)
            saved=json.loads((Path(folder)/job['id']/'household_config.json').read_text())
            request=json.loads((Path(folder)/job['id']/'request.json').read_text())
            self.assertEqual(saved,job['household_config']);self.assertEqual(saved,request['household_config'])
            self.assertEqual(job['household_id'],saved['id']);self.assertEqual(job['household_config_hash'],digest(saved))
            self.assertEqual(request['household_config_hash'],job['household_config_hash'])
            submission=json.loads((Path(folder)/job['id']/'questionnaire_submission.json').read_text())
            self.assertEqual(submission['raw_answers'],answers())
            self.assertEqual(submission['normalized_answers'],request['profile'])
            self.assertEqual(digest(submission),request['submission_hash'])
            self.assertEqual(submission['household_config_hash'],digest(saved))
            reloaded=Store(folder);reloaded.pool.shutdown()
            self.assertEqual(reloaded.jobs[job['id']]['submission_hash'],digest(submission))

    def test_stale_questionnaire_is_rejected_before_job_creation(self):
        with tempfile.TemporaryDirectory() as folder:
            store=Store(folder);store.pool.shutdown();store.pool=NoExecute()
            payload={'request_id':'stale_questionnaire_001','answers':answers(),
                'scenario_id':CONTEXT['id'],'scenario_understood':True,
                'questionnaire_version':'eb.persona_questionnaire.v3.3'}
            with self.assertRaisesRegex(ValueError,'问卷版本已更新'):
                store.create('owner',payload,paired_flow=True)
            self.assertEqual(list(Path(folder).glob('*/job.json')),[])
            self.assertEqual(store.db.jobs(),[])

if __name__=='__main__':unittest.main()
