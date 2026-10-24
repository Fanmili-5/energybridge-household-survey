"""Calendar evidence and shared/member relationship counterexamples; no A/B."""
import copy
import datetime as dt
import unittest

from .core import digest
from .device_persona import generate_personas,preference_input,render_family
from .joint_sampling import VERSION2,VERSION3
from .portrait_calendar import FIELD,add_calendar_evidence,availability_source
from .portrait_v3 import audit,local_domain
from .test_joint_sampling import fixture


def context(role='B',seed=0):
    c=fixture(role,seed);c['energy_preferences']['preference_sampling']['mode']=VERSION3
    return c


def midnight_context():
    c=context();date=c['habit_days'][0]['date'];next_date=str(dt.date.fromisoformat(date)+dt.timedelta(days=1))
    mid=c['members'][0]['member_id'];asset=next(d for d in c['devices'] if 'washer' in d['types'])
    def day(date,window):
        return {'date':date,'calendars':{m['member_id']:[{'start_min':0,'end_min':1440,'activity':'home_free_activity','location':'home','room_id':asset['room_id'],'available_for_operation':True}] for m in c['members']},
                'operator_windows':{m['member_id']:(window if m['member_id']==mid else []) for m in c['members']}}
    today=day(date,[[1380,1440]]);tomorrow=day(next_date,[[0,180]])
    c['days']=[today];c['habit_days']=[copy.deepcopy(today)]
    c['declared_service_contracts']=[{'need_id':date+':wash','asset_id':asset['asset_id'],'kind':'washer','source_date':date,
       'release_min':1380,'deadline_min':1620,'duration_min':60,'machine_windows_min':[[0,1440]],'maximum_preload_wait_min':60,
       'maximum_retrieval_wait_min':60,'timer_allowed':True}]
    return c,today,tomorrow


class PortraitRelationshipTests(unittest.TestCase):
    def test_existing_next_day_restores_local_target_without_adding_habits_or_services(self):
        c,today,tomorrow=midnight_context();before=digest(c);source=preference_input(c);need=source['declared_service_contracts'][0]
        self.assertFalse(local_domain(source,need)[0])
        enriched=add_calendar_evidence(c,[today,tomorrow])
        s=preference_input(enriched);values,_=local_domain(s,need)
        self.assertTrue(values);self.assertTrue(all(t>=1440 for t in values))
        self.assertEqual(s['days'],source['days']);self.assertEqual(s['declared_service_contracts'],source['declared_service_contracts'])
        self.assertEqual(before,digest(c));self.assertEqual(len(availability_source(s)['days']),2)
        p=generate_personas(enriched);w=next(d for d in p['devices'] if d['kind']=='washer')
        self.assertEqual(w['sampled_preferences']['time_preference']['per_service'][0]['preferred_day_offset'],1)

    def test_conflicting_or_hash_tampered_neighbor_evidence_is_rejected(self):
        c,today,tomorrow=midnight_context();changed=copy.deepcopy(today);changed['operator_windows'][c['members'][0]['member_id']]=[]
        with self.assertRaisesRegex(ValueError,'DISAGREES_WITH_SELECTED'):add_calendar_evidence(c,[changed,tomorrow])
        enriched=add_calendar_evidence(c,[today,tomorrow]);enriched['energy_preferences'][FIELD]['days'][0]['operator_windows'].clear()
        with self.assertRaisesRegex(ValueError,'EVIDENCE_HASH'):generate_personas(enriched)

    def test_missing_neighbor_is_reported_without_inventing_a_day(self):
        c,today,tomorrow=midnight_context();enriched=add_calendar_evidence(c,[today])
        self.assertEqual(enriched['energy_preferences'][FIELD]['unavailable_needed_dates'],[tomorrow['date']])
        self.assertFalse(local_domain(preference_input(enriched),c['declared_service_contracts'][0])[0])

    def test_reordered_evidence_is_identical_and_outcomes_cannot_change_it(self):
        c,today,tomorrow=midnight_context();a=add_calendar_evidence(c,[today,tomorrow]);b=add_calendar_evidence(c,[tomorrow,today])
        self.assertEqual(a,b);a['outcomes']={'success':False};a['plans']={'A':'not_read','B':'not_read'}
        self.assertEqual(generate_personas(a),generate_personas(b))

    def test_late_clock_preference_does_not_mean_voluntary_next_day_deferral(self):
        from .portrait_v3 import targets
        c,today,tomorrow=midnight_context();mid=c['members'][0]['member_id']
        today['operator_windows'][mid]=[[360,1200]];c['days']=[today];c['habit_days']=[copy.deepcopy(today)]
        c['declared_service_contracts'][0].update(release_min=360,deadline_min=2880)
        tomorrow['operator_windows'][mid]=[[360,1200]]
        source=preference_input(add_calendar_evidence(c,[today,tomorrow]));asset=next(d for d in source['devices'] if 'washer' in d['types'])
        row=targets(source,asset,'washer',.99,{})['per_service'][0]
        self.assertEqual(row['selected_service_day_offset'],0);self.assertLess(row['preferred_start_min'],1440)
        self.assertGreater(row['all_original_horizon_candidate_count'],row['preference_candidate_count'])

    def test_sole_affected_member_is_the_default_not_a_second_competing_opinion(self):
        for role in 'ABCDEF':
            c=context(role);p=generate_personas(c)
            self.assertFalse(audit(p,preference_input(c))['engineering_errors'])
            for d in p['devices']:
                people=d['authorization']['affected_member_ids'];r=d['sampled_preferences']
                if len(people)!=1:continue
                self.assertEqual(r['shared_preference_resolution']['default_owner_member_id'],people[0])
                self.assertEqual(r['member_device_preferences'][people[0]]['coordinates'],r['coordinates'])
                self.assertFalse(d['member_negotiation'])

    def test_unknown_handler_does_not_create_a_preference_owner_or_permission(self):
        c=context();c['asset_authority']={};p=generate_personas(c)
        for d in p['devices']:
            if d['kind'] in ('washer','dryer','dishwasher'):
                self.assertIsNone(d['sampled_preferences']['shared_preference_resolution']['default_owner_member_id'])
                self.assertFalse(d['sampled_preferences']['member_device_preferences'])

    def test_explicit_household_declarations_condition_member_device_preferences(self):
        c=context();c['energy_preferences']['shared_appliances']={'ac':{'setpoint_preferred_min_c':26,'setpoint_preferred_max_c':26},'washer':{'shiftable':False}}
        p=generate_personas(c)
        for d in p['devices']:
            for m in d['sampled_preferences']['member_device_preferences'].values():
                if d['kind']=='ac':self.assertEqual(m['cooling_preferred_C'],26)
                if d['kind']=='washer':self.assertEqual(m['shift_willingness_fraction'],0)

    def test_latent_draws_and_authorization_unchanged_from_v2(self):
        for role in 'ABCDEF':
            c=context(role);p=generate_personas(c);c['energy_preferences']['preference_sampling']['mode']=VERSION2;q=generate_personas(c)
            self.assertEqual(p['joint_sampling']['shared_coordinates'],q['joint_sampling']['shared_coordinates'])
            for a,b in zip(p['devices'],q['devices']):
                self.assertEqual(a['sampled_preferences']['coordinates'],b['sampled_preferences']['coordinates'])
                self.assertEqual(a['authorization'],b['authorization'])

    def test_multi_member_opinions_are_not_averaged_or_forced_to_match(self):
        p=generate_personas(context());d=next(d for d in p['devices'] if d['kind']=='ac')
        r=d['sampled_preferences'];owner=r['shared_preference_resolution']['default_owner_member_id']
        other=next(mid for mid in d['authorization']['affected_member_ids'] if mid!=owner)
        self.assertNotEqual(r['member_device_preferences'][owner]['coordinates'],r['member_device_preferences'][other]['coordinates'])
        self.assertEqual(r['member_device_preferences'][other]['coordinates'],p['joint_sampling']['member_preferences'][other]['coordinates'])
        self.assertTrue(any(v['member_id']==other for v in d['member_negotiation']))
        self.assertFalse(r['shared_preference_resolution']['unanimous_agreement_claimed'])

    def test_corrupted_single_member_opinion_fails_semantic_acceptance(self):
        c=context();p=generate_personas(c);d=next(d for d in p['devices'] if d['kind']=='washer')
        owner=d['sampled_preferences']['shared_preference_resolution']['default_owner_member_id']
        d['sampled_preferences']['member_device_preferences'][owner]['shift_willingness_fraction']=-1
        self.assertIn('default_disagrees_with_its_own_member_device_opinion',audit(p,preference_input(c))['engineering_errors'])

    def test_general_member_latents_are_not_rendered_as_a_second_device_personality(self):
        p=generate_personas(context());text=render_family(p)
        self.assertIn('习惯参考来自成员',text);self.assertIn('不代表所有人已经同意',text)
        self.assertNotIn('成员1：可行窗口内',text)
        self.assertTrue(all(m['preference_context']['use'].startswith('latent_member_baseline_only') for m in p['joint_sampling']['member_preferences'].values()))


if __name__=='__main__':unittest.main()
