"""Semantic counterexamples; do not invoke any A/B generation or simulator."""
import copy
import unittest
from unittest.mock import patch

from .core import HERE,read,digest,construct
from .device_persona import generate_personas,preference_input,render_family
from .joint_sampling import VERSION2,apply_to_life
from .portrait_v2 import (targets,projection,machine_willingness,time_fields,render_dated,audit)
from .test_joint_sampling import fixture


def v2fixture(role='B',seed=0):
    c=fixture(role,seed);c['energy_preferences']['preference_sampling']['mode']=VERSION2
    return c


class PortraitSemanticTests(unittest.TestCase):
    def test_original_1930_case_is_not_mapped_to_1150(self):
        t=read(HERE/'examples/REFERENCE_POOL.json')['templates'][0]
        family=construct(t,'family-joint-demo-000001','A',{'mode':VERSION2,'seed':20261019,'loading':.7})
        p=family['energy_use_profile'];w=next(d for d in p['joint_sampling']['devices'] if d['kind']=='washer')
        self.assertEqual(w['time_preference']['per_service'][0]['preferred_start_min'],1170)
        self.assertNotIn('weekday',w['time_preference']['preferred_start_min'])
        life=copy.deepcopy(family['life']);new,log=apply_to_life(life,p)
        old=next(p for p in life['program_policies'] if p['kind']=='washer')
        projected=next(p for p in new['program_policies'] if p['kind']=='washer')
        self.assertEqual(old['preferred_start_min']['weekday'],projected['preferred_start_min']['weekday'])
        self.assertTrue(any(r.get('status')=='pending_A_interface' for r in log))

    def test_next_day_target_is_preserved_and_not_accepted_as_today(self):
        row={'source_date':'2025-07-01','reason':None,**time_fields('2025-07-01',1830)}
        values,states=projection([row])
        self.assertEqual(row['preferred_start_at'],'2025-07-02T06:30')
        self.assertEqual(row['preferred_day_offset'],1);self.assertNotIn('weekday',values)
        self.assertIn('offset',states['weekday']['reason'])

    def test_differing_dates_and_missing_dates_are_not_clock_unions(self):
        rows=[{'source_date':'2025-07-01','preferred_start_min':1170},{'source_date':'2025-07-02','preferred_start_min':1200}]
        self.assertEqual(projection(rows)[0],{})
        rows[1]['preferred_start_min']=None
        self.assertEqual(projection(rows)[1]['weekday']['reason'],'dated_target_missing')

    def test_equal_dated_targets_can_use_original_interface_losslessly(self):
        rows=[{'source_date':'2025-07-01','preferred_start_min':1170},{'source_date':'2025-07-02','preferred_start_min':1170}]
        self.assertEqual(projection(rows)[0],{'weekday':1170})

    def test_handling_sensitivity_does_not_reduce_machine_shift_willingness(self):
        low={'routine_stability':.2,'manual_burden':0};high={**low,'manual_burden':1}
        self.assertEqual(machine_willingness(low,{}),machine_willingness(high,{}))
        self.assertAlmostEqual(machine_willingness(high,{}),.8)
        self.assertEqual(machine_willingness(high,{'shiftable':False}),0)

    def test_can_discuss_machine_shift_and_dislike_handling_simultaneously(self):
        from .portrait_v2 import habit
        p=generate_personas(v2fixture());r=next(d for d in p['joint_sampling']['devices'] if d['kind']=='washer')
        r.update(routine_sensitive=False,handling_change_sensitive=True,preferred_shift_limit_min=40)
        text=habit(r)
        self.assertIn('机器改时有商量余地',text);self.assertIn('不愿增加装取',text)
        self.assertIn('40分钟',text)

    def test_same_latent_stream_across_versions_all_six_classes(self):
        for role in 'ABCDEF':
            c=v2fixture(role);a=generate_personas(c)['joint_sampling']
            c['energy_preferences']['preference_sampling']['mode']='within_class_joint_v1';b=generate_personas(c)['joint_sampling']
            self.assertEqual(a['shared_coordinates'],b['shared_coordinates'])
            for x,y in zip(a['devices'],b['devices']):self.assertEqual(x['coordinates'],y['coordinates'])
            for mid in a['member_preferences']:self.assertEqual(a['member_preferences'][mid]['coordinates'],b['member_preferences'][mid]['coordinates'])

    def test_explicit_household_cooling_wins_over_default_reference(self):
        c=v2fixture();c['energy_preferences']['shared_appliances']={'ac':{'setpoint_preferred_min_c':26,'setpoint_preferred_max_c':26}}
        p=generate_personas(c)
        for d in p['devices']:
            if d['kind']=='ac':
                self.assertEqual(d['sampled_preferences']['cooling_preferred_C'],26)
                self.assertEqual(d['sampled_preferences']['cooling_support_origin'],'explicit_shared_declaration')

    def test_bad_shared_temperature_is_diagnostic_not_clipped_or_resampled(self):
        c=v2fixture();c['energy_preferences']['shared_appliances']={'ac':{'setpoint_preferred_min_c':40,'setpoint_preferred_max_c':40}}
        with self.assertRaisesRegex(ValueError,'40C_is_not'):generate_personas(c)

    def test_explicit_clock_and_impossible_preference_window_retain_source(self):
        c=preference_input(v2fixture());a=next(d for d in c['devices'] if 'washer' in d['types']);date=c['days'][0]['date'];mid=c['members'][0]['member_id']
        for day in c['days']:day['operator_windows'][mid]=[[360,1200]]
        n={'need_id':date+':wash','source_date':date,'asset_id':a['asset_id'],'kind':'washer','release_min':360,'deadline_min':1200,
           'duration_min':60,'machine_windows_min':[[360,1200]],'maximum_preload_wait_min':60,'maximum_retrieval_wait_min':60,'timer_allowed':True}
        c['declared_service_contracts']=[n];old=digest(c)
        x=targets(c,a,'washer',.01,{'preferred_h':15})
        self.assertEqual(x['per_service'][0]['preferred_start_min'],900)
        x=targets(c,a,'washer',.99,{'preferred_h':2,'earliest_h':1,'latest_h':3})
        self.assertIsNone(x['per_service'][0]['preferred_start_min']);self.assertIn('no_local_opportunity',x['per_service'][0]['reason'])
        self.assertEqual(old,digest(c))

    def test_member_views_are_preserved_not_averaged_or_imposed_on_other_rooms(self):
        c=v2fixture();p=generate_personas(c);m=p['joint_sampling']['member_preferences']
        self.assertEqual(set(m),{x['member_id'] for x in c['members']})
        for d in p['devices']:
            self.assertTrue(all(v['member_id'] in d['authorization']['affected_member_ids'] for v in d['member_negotiation']))
            self.assertTrue(all('needs_negotiation' in v['status'] for v in d['member_negotiation']))

    def test_text_does_not_present_dated_candidates_as_stable_habits(self):
        c=v2fixture();p=generate_personas(c);text=render_family(p)
        self.assertIn('每日候选时刻另按日期列示',text)
        self.assertIn('不是硬限制或拒绝标签',text)
        self.assertNotIn('工作日11:50',text)
        for d in p['devices']:
            for r in d['sampled_preferences'].get('time_preference',{}).get('per_service',[]):
                if r['preferred_start_min'] is not None:self.assertIn(r['source_date'],render_dated(p))

    def test_dated_service_display_keeps_soc_water_and_next_day_requirements(self):
        from .portrait_v2 import service_text
        text=service_text({'release_min':1020,'deadline_min':2190,'required_departure_soc':.85,'quantity':2.5,'unit':'kWh'})
        self.assertIn('原期限次日12:30',text);self.assertIn('SOC 85%',text);self.assertIn('2.5 kWh',text)
        self.assertIn('40.5556℃',service_text({'target_C':40.55555555}))

    def test_member_discussion_uses_only_preferences_relevant_to_each_device(self):
        p=generate_personas(v2fixture())
        for d in p['devices']:
            if d['kind'] in ('ac','water_heater'):
                self.assertFalse(any(set(v['fields']) & {'routine_sensitive','handling_change_sensitive'} for v in d['member_negotiation']))
        c=preference_input(v2fixture());d=p['devices'][0]
        d['decision_conditions']['service_contracts'].append({'need_id':'invented'})
        self.assertIn('original_service_contract_changed',audit(p,c)['engineering_errors'])

    def test_semantic_audit_detects_corruption_and_missing_reason(self):
        c=v2fixture();p=generate_personas(c);self.assertFalse(audit(p,preference_input(c))['engineering_errors'])
        d=next(d for d in p['devices'] if d['kind']=='washer')
        d['sampled_preferences']['shift_willingness_fraction']=-1
        self.assertIn('handling_mixed_into_machine_willingness',audit(p,preference_input(c))['engineering_errors'])

    def test_frames_do_not_resample_from_plans_outcomes_answers_or_selected_date(self):
        c=v2fixture();a=generate_personas(c);c['plans']={'A':'garbage','B':'garbage'};c['answers']='garbage';c['outcomes']='garbage';c['days']=c['days'][-1:]
        self.assertEqual(a,generate_personas(c))

    def test_frozen_v2_profile_and_legacy_are_both_supported(self):
        c=v2fixture();p=generate_personas(c);c['frozen_joint_sampling']=p['joint_sampling']
        self.assertEqual(p['joint_sampling'],generate_personas(c)['joint_sampling'])
        c['frozen_joint_sampling']['member_preferences'].clear()
        with self.assertRaisesRegex(ValueError,'FROZEN_HASH'):generate_personas(c)


if __name__=='__main__':unittest.main()
