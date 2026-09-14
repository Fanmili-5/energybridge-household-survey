from date_sampling import assigned_context
"""Option semantics, time input and unlabelled household export; no paid APIs."""
import json
import tempfile
import unittest
from pathlib import Path
from common import normalize_answers, digest
from paired_contract import LOOKUP, QUESTIONS, prepare, sanitize_profile
from verify_paired_physics import answers
from survey_time import ac_available, start_hour
from export_household_records import records
from server import Store
from test_pilot import NoExecute


class OptionAuditTests(unittest.TestCase):
    def profile(self,raw):
        return sanitize_profile(normalize_answers(raw,list(LOOKUP),LOOKUP))

    def test_whitespace_is_skipped_and_none_is_distinct(self):
        raw=answers();raw.update(X_CITY=' \n\t ',X_EXTRA_DEVICES=['none'])
        profile=self.profile(raw)
        self.assertEqual(profile['X_CITY'],{'value':None,'response_status':'skipped'})
        self.assertEqual(profile['X_EXTRA_DEVICES']['value'],['none'])
        raw['X_EXTRA_DEVICES']=[]
        self.assertEqual(self.profile(raw)['X_EXTRA_DEVICES']['response_status'],'skipped')

    def test_complete_unique_options_and_old_meanings_not_reused(self):
        for q in QUESTIONS:
            for field in [q]+q.get('fields',[]):
                values=[json.dumps(o['value']) for o in field['options']]
                self.assertEqual(len(values),len(set(values)),field['id'])
        self.assertEqual(len(LOOKUP['H_home_ev']['options']),144)
        for old,hour in [('morning',8),('noon',12),('evening',18),('night',20),('late',22)]:
            self.assertEqual(start_hour(old),hour)
        self.assertEqual(start_hour('19'),19)
        for change in ({'X_FREQ_ac':'daily'},{'X_RESTORE':'keep'}):
            with self.assertRaises(ValueError):self.profile({**answers(),**change})
        raw=answers();raw['M_MEMBERS'][0]['participation']='shared'
        with self.assertRaises(ValueError):self.profile(raw)

    def test_control_levels_keep_native_tags_and_reject_retired_ambiguous_choice(self):
        self.assertEqual([o['value'] for o in LOOKUP['A_EB_CONTROL']['options']],
                         ['high_trust_auto','confirm_required','low_auto_accept'])
        fields={f['id']:f for f in LOOKUP['M_MEMBERS']['fields']}
        self.assertEqual([o['value'] for o in fields['control']['options']],['auto','confirm','manual'])
        for option in ('high_trust_auto','confirm_required','low_auto_accept'):
            self.assertEqual(self.profile({**answers(),'A_EB_CONTROL':option})['A_EB_CONTROL']['value'],option)
        with self.assertRaises(ValueError):self.profile({**answers(),'A_EB_CONTROL':'suggestion_first'})
        raw=answers();raw['M_MEMBERS'][0]['control']='suggest'
        with self.assertRaises(ValueError):self.profile(raw)

    def test_new_times_and_overnight_ac_reach_ep_schedule(self):
        raw=answers();raw.update(H_ac='custom',H_ac_start='22',H_ac_end='8',H_home_ev='19',H_washer='8.5')
        profile=self.profile(raw);original,scenario=prepare(profile,'option_test')
        ac=original['devices']['ac']
        self.assertEqual((ac['use_start_h'],ac['use_end_h']),(22,32))
        self.assertEqual(original['devices']['home_ev']['start_h'],19)
        self.assertEqual(original['devices']['washer']['start_h'],8.5)
        self.assertEqual([h for h in range(24) if ac_available(ac,h)],list(range(8))+[22,23])
        self.assertFalse(ac_available(ac,8));self.assertTrue(ac_available(ac,24))
        from paired_ep import build_idf,objects
        from proposal_contract import executable
        with tempfile.TemporaryDirectory() as tmp:
            path=build_idf(Path(tmp),original,executable(original),scenario,profile,{'rows':[{'actuators':{}}]*576})
            schedule=next(o for o in objects(path.read_text()) if o[1:2]==['PilotACAvailability'])
            self.assertIn('Until: 08:00',schedule)
            i=schedule.index('For: AllOtherDays')
            self.assertEqual(schedule[i+1:i+7],['Until: 08:00','1','Until: 22:00','0','Until: 24:00','1'])
        raw['H_ac_end']='22'
        with self.assertRaises(ValueError):prepare(self.profile(raw),'same')
        raw['H_ac']='all_day'
        p=self.profile(raw)
        self.assertEqual(p['H_ac_start']['response_status'],'not_applicable')
        self.assertEqual(prepare(p,'same')[0]['devices']['ac']['use_end_h'],24)

    def test_export_keeps_failed_and_unevaluated_households(self):
        from regional_test_support import answers
        with tempfile.TemporaryDirectory() as tmp:
            store=Store(tmp,human_pilot=True);store.pool=NoExecute()
            from server import PARTICIPANT_UI_VERSION
            from paired_contract import CONTEXT, QUESTIONNAIRE_VERSION
            jobs=[]
            for i,status in enumerate(['queued','failed','complete']):
                store.human_pilot=i<2
                receipt=store.save_household('options_owner_'+str(i),{'questionnaire_context_hash':assigned_context('options_owner_'+str(i))["context_hash"],'answers':answers(),'request_id':'options_intake_request_'+str(i),'questionnaire_version':QUESTIONNAIRE_VERSION,'questionnaire_hash':digest(QUESTIONS),'research_consent':True,'scenario_understood':True,'research_notice_version':'eb.research_notice.v2','ui_version':PARTICIPANT_UI_VERSION})
                job=store.create('options_owner_'+str(i),{'submission_id':receipt['id'],'request_id':'options_audit_request_'+str(i),'scenario_id':CONTEXT['id'],'scenario_understood':True},paired_flow=True)
                job['status']=status
                if i==2:job['data_origin']='synthetic_engineering_test'
                store.persist(job);jobs.append(job)
            exported=list(records(tmp))
            self.assertEqual([next(iter(r['job_statuses'].values())) for r in exported],['queued','failed'])
            self.assertTrue(all(not r['decision_saved'] for r in exported))
            self.assertEqual(len(list(records(tmp,True))),3)
            self.assertEqual(exported[0]['household_record_hash'],digest(jobs[0]['household_record']))
            self.assertEqual(exported[0]['household_record']['raw_answers'],answers())
            store.db.close()

    def test_native_ep_overnight_controls_follow_custom_answers(self):
        from legacy_test_support import prepare
        from closed_loop import simulate_live
        from contextlib import redirect_stdout
        from io import StringIO
        from common import ROOT,write_json
        raw=answers();raw.update(H_ac='custom',H_ac_start='22',H_ac_end='8',H_home_ev='19',H_ac_temp='25.5',P_EV_TARGET='0.5',P_EV_RESERVE='0.4')
        profile=self.profile(raw);original,scenario=prepare(profile,'options_native_baseline')
        from evaluation_window import make_window
        scenario['evaluation_window']=make_window(original)  # historical custom-loop regression
        request={'profile':profile,'original_plan':original,'scenario':scenario,'household_id':'options_engineering'}
        folder=ROOT/'ui_audit_20260911/options_audit/native_ep_baseline'
        with redirect_stdout(StringIO()):baseline=simulate_live(folder,request)
        for control in baseline['controls']:
            self.assertEqual(control['hvac_available'],ac_available(original['devices']['ac'],control['start_h']))
        self.assertFalse(baseline['decisions'])
        write_json(folder.parent/'native_ep_report.json',{'passed':True,'real_api_calls':0,
                   'engineering_only':True,'control_rows':len(baseline['controls']),
                   'custom_ac_window':[22,32],'ev_arrival_h':19,
                   'task_energy_checks':baseline['task_energy_checks'],
                   'live_observation_sql_check':baseline['live_observation_sql_check']})

    def test_extended_ev_preferences_and_ac_comparison_end(self):
        raw=answers();raw.update(P_EV_TARGET='0.8',P_EV_RESERVE='0.6')
        original,_=prepare(self.profile(raw),'extended_ev')
        from eb_execution import upstream
        _,Suite=upstream();ev=Suite(original['eb_appliance_config'],sim_days=4,explicit_only=True)._ev
        self.assertEqual((ev.target_soc,ev.min_soc),(.8,.6))
        raw['P_EV_TARGET']='0.5'
        with self.assertRaises(ValueError):prepare(self.profile(raw),'invalid_ev')
        raw=answers();raw.update(B05=['ac'],H_ac='custom',H_ac_start='22',H_ac_end='8')
        original,scenario=prepare(self.profile(raw),'only_ac')
        self.assertEqual(scenario['evaluation_window']['end_sim_h'],24)
        self.assertIsNone(scenario['evaluation_window']['ev_departure_sim_h'])

    def test_ewh_contract_acceptance_is_not_runtime_support(self):
        from eb_execution import replay,upstream
        from proposal_contract import executable
        original,scenario=prepare(self.profile(answers()),'ewh_boundary')
        plan=executable(original)
        plan['appliances'].update(water_heater_preheat_start_h=22,water_heater_preheat_end_h=2)
        runner,_=upstream()
        self.assertEqual(runner._adaptive_v3_water_heater_action_errors(plan['appliances'],original['eb_appliance_config']),[])
        original['eb_ordinary_plan']=plan
        trace=replay(original,plan,scenario,proposal=False)
        for hour in (22,23,25):
            row=next(r for r in trace['rows'] if r['sim_h']==hour)
            self.assertEqual(row['actuators']['water_heater'],40) # Native writer cannot execute this accepted window.
        raw=answers();raw.update(H_electric_water_heater='late',D_electric_water_heater='2')
        with self.assertRaisesRegex(ValueError,'暂不支持跨夜'):prepare(self.profile(raw),'blocked_native_gap')
        self.assertIn('0',[o['value'] for o in LOOKUP['H_electric_water_heater']['options']])


if __name__=='__main__':unittest.main()
