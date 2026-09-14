"""Member reports are input evidence, never member votes. No model/API calls."""
import copy
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from common import normalize_answers, digest
from paired_contract import LOOKUP, QUESTIONS, prepare, profile_components
from member_questionnaire import QUESTION
from household_config import build_household_config, ensure_household_config, bind_household
from questionnaire_persona import visible_profile
from proposal_contract import candidate
from verify_paired_physics import answers

class MemberTests(unittest.TestCase):
    def profile(self,raw=None):
        return normalize_answers(answers() if raw is None else raw,list(LOOKUP),LOOKUP)

    def test_optional_attitudes_remain_unknown_and_no_identity_or_weight(self):
        raw=answers();raw['M_MEMBERS'][1]={'routine':'home_regular'}
        p=self.profile(raw);o,s=prepare(p,'members');h=build_household_config(p,QUESTIONS,o,'test')
        m=h['reported_members'][1]
        self.assertEqual(m['member_id'],'member_2')
        self.assertEqual(m['reported_fields']['comfort'],{'value':None,'label':None,'question':'对室温变化的感受','response_status':'skipped'})
        self.assertEqual(m['source'],'household_representative_report')
        self.assertFalse(h['meta']['respondent_member_link_collected'])
        for member in h['reported_members']:
            for key in ('decision_weight','persona_id','respondent','score','acceptance_probability'):
                self.assertNotIn(key,member)
        self.assertNotIn('members',h);self.assertNotIn('acceptance_profiles',h)
        self.assertEqual(h['observable_profile'],visible_profile(p,QUESTIONS))
        self.assertIn('未填写',h['llm_prompts']['agent_context'])
        self.assertNotIn('M_MEMBERS',profile_components(p)['classification']['features'])

    def test_counts_invalid_fields_and_missing_routine_rejected(self):
        for value in ({},[{'routine':'invented'}]*3,[{'routine':'out_regular','decision_weight':1}]*3,[{'comfort':'temp_sensitive'}]*3,[True]*3):
            raw=answers();raw['M_MEMBERS']=value
            with self.subTest(value=value),self.assertRaises(ValueError):prepare(self.profile(raw),'members')
        for size,count in [('3',2),('6_plus',5)]:
            raw=answers();raw['B02']=size;raw['M_MEMBERS']=[{'routine':'mixed'} for _ in range(count)]
            with self.assertRaises(ValueError):prepare(self.profile(raw),'members')
        raw=answers();raw['B02']='6_plus';raw['M_MEMBERS']=[{'routine':'mixed'} for _ in range(7)]
        p=self.profile(raw);o,s=prepare(p,'members');h=build_household_config(p,QUESTIONS,o,'test')
        self.assertEqual(len(h['reported_members']),7)
        # Six-plus now has an explicit reported count, while old snapshots keep their mapping.
        self.assertEqual(h['schedule']['occupant_count'],7)

    def test_member_attitudes_change_context_not_physics_or_labels(self):
        p=self.profile();o,s=prepare(p,'fixed');h=build_household_config(p,QUESTIONS,o,'test')
        changed=copy.deepcopy(p);changed['M_MEMBERS']['value'][0]['comfort']='temp_sensitive'
        o2,s2=prepare(changed,'fixed');h2=build_household_config(changed,QUESTIONS,o2,'test')
        self.assertEqual(o,o2);self.assertEqual(s,s2)
        self.assertNotEqual(h['observable_profile'],h2['observable_profile'])
        self.assertEqual(profile_components(p)['classification'],profile_components(changed)['classification'])
        result={'schema_version':'eb.paired_ep.v2.7','household_config':h,'proposal_plan':{},'display':{},'display_hash':'display','original_plan_hash':'original','proposal_plan_hash':'proposal'}
        job={'id':'case','household_id':'test','respondent_id':'session','profile':p,'original_plan':o,'result':result,'data_origin':'synthetic_engineering_test','questionnaire_snapshot':QUESTIONS,'flow':'paired_ep_v1'}
        decision={'target_source':'engineering_test','choice':'reject','score':4.5,'comfort_score':4.2,'energy_score':4.8,'vpp_score':2.2,'comment':'调整时间影响家人休息'}
        row=candidate(job,decision);prompt=json.loads(row['messages'][1]['content']);target=json.loads(row['messages'][2]['content'])
        self.assertEqual(prompt['household_answers'],h['observable_profile'])
        self.assertEqual(target['decision'],'reject');self.assertEqual(target['score'],4.5)

    def test_legacy_snapshot_config_hash_is_preserved(self):
        fixture=json.loads(Path('ui_audit_20260911/fixture.json').read_text())
        if fixture.get('household_config'):
            frozen=copy.deepcopy(fixture)
            with self.assertRaises(ValueError):ensure_household_config(fixture)
            self.assertEqual(fixture,frozen)  # Historical data is not rewritten to new runtime defaults.
        questions=[q for q in QUESTIONS if q['type']!='member_list']
        p=self.profile();p.pop('M_MEMBERS');o,s=prepare(self.profile(),'legacy')
        h=build_household_config(p,questions,o,'legacy')
        self.assertEqual(h['schema_version'],'eb.respondent_household.v1')
        self.assertNotIn('reported_members',h)

    def test_member_text_reaches_actual_eb_prompt_without_a_model_call(self):
        from legacy_test_support import prepare
        from eb_execution import upstream
        from closed_loop import EBPlanner
        runner,Suite=upstream()
        from energybridge.llm.client import LLMClient
        raw=answers();raw['M_MEMBERS'][1]={'routine':'irregular','comfort':'temp_sensitive'}
        p=self.profile(raw);o,s=prepare(p,'fixed');r={'profile':p,'original_plan':o,'scenario':s,'household_id':'member_test','questionnaire_snapshot':QUESTIONS}
        loop=runner._FamilyLoop();h=bind_household(loop,r);loop.appliance_suite=Suite(h['appliances'],sim_days=5,explicit_only=True)
        with tempfile.TemporaryDirectory() as folder:
            with patch.object(LLMClient,'__init__',return_value=None), patch.object(LLMClient,'chat_with_metrics',return_value={'text':'invalid','metrics':{}}) as call:
                EBPlanner(r,Path(folder),lambda *args:None)(loop,72+s['decision_h'],{'temperature_c':25,'outdoor_c':30,'facility_w':1000,'occupancy_count':3},[],['notification'])
                text=str(call.call_args_list)
                self.assertIn('P_GRID',text);self.assertIn('P_NOTICE',text);self.assertIn('P_AC_RANGE',text);self.assertIn('P_EV_TARGET',text);self.assertIn('成员 2',text);self.assertIn('轮班或时间经常变化',text);self.assertIn('比较敏感，小幅变化也容易不舒服',text)

    def test_colleague_preferences_and_native_appliance_fields(self):
        from eb_execution import upstream
        p=self.profile();o,s=prepare(p,'preferences');h=build_household_config(p,QUESTIONS,o,'test')
        _,Suite=upstream();suite=Suite(h['appliances'],sim_days=5,explicit_only=True)
        self.assertEqual(suite._ev.target_soc,.8);self.assertEqual(suite._ev.min_soc,.2)
        self.assertEqual(h['appliances']['water_heater']['bath_required_h'],21)
        self.assertEqual(h['reported_preferences']['comfort_importance']['value'],'4')
        self.assertEqual(h['preferences'],{'notice_required_h':1.0})
        self.assertEqual(h['tags'],{'control':'confirm_required'})
        for name in ('scoring_weights','vpp_override_prob'):self.assertNotIn(name,h['preferences'])
        self.assertEqual(h['ordinary_plan']['setpoint'],25)
        self.assertEqual(h['reported_preferences']['preferred_room_temperature']['value'],'24_26')
        self.assertEqual(h['field_sources']['appliances.ev.target_soc']['question_id'],'P_EV_TARGET')
        raw=answers();raw['P_NOTICE']='24';p2=self.profile(raw);o2,s2=prepare(p2,'preferences')
        self.assertEqual(s,s2) # preference is not used to hide short-notice scenarios
        self.assertEqual(o,o2)
        raw=answers();raw.pop('P_EV_TARGET')
        with self.assertRaises(ValueError):prepare(self.profile(raw),'preferences')
        raw['B05']=['washer']
        from paired_contract import sanitize_profile
        p=sanitize_profile(self.profile(raw));prepare(p,'preferences')
        self.assertEqual(p['P_EV_TARGET']['response_status'],'not_applicable')

if __name__=='__main__':unittest.main()
