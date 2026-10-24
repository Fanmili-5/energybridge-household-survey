"""Meaningful counterexamples for opt-in sampling and original pipeline safety."""
import copy
import datetime as dt
from pathlib import Path
import tempfile
import unittest

from .core import HERE, digest, read, save, sha, generate
from .device_persona import generate_personas, preference_input, render_family
from .joint_sampling import (VERSION, RULES, configuration, coordinates, normal,
                             feasible_starts, apply_to_life)


def fixture(role='B', seed=0):
    c=copy.deepcopy(next(c for c in read(HERE/'examples/energy_portrait/input.json')['households'] if c['role']==role))
    c['energy_preferences']={'preference_sampling':{'mode':VERSION,'seed':seed}}
    c['asset_authority']={'assets':{d['asset_id']:{'authorized_operator_ids':[c['members'][0]['member_id']],
                                                'registered_operator_id':c['members'][0]['member_id']} for d in c['devices']}}
    return c


class JointSamplingTests(unittest.TestCase):
    def test_exact_replay_and_substantial_seed_variation(self):
        c=fixture(); before=digest(c); p=generate_personas(c)
        self.assertEqual(p,generate_personas(c)); self.assertEqual(before,digest(c))
        signatures=[]
        for seed in range(8):
            c['energy_preferences']['preference_sampling']['seed']=seed
            q=generate_personas(c)['joint_sampling']
            signatures.append(digest([(d['tradeoff'],d.get('cooling_preferred_C'),d.get('readiness_priority')) for d in q['devices']]))
        self.assertEqual(len(set(signatures)),8)

    def test_all_six_classes_and_members_remain_in_class(self):
        for role in 'ABCDEF':
            c=fixture(role); p=generate_personas(c)
            expected=read(HERE/'DEVICE_PERSONA_RULES.json')['EB_roles'][role]['source_path'].rsplit('/',1)[-1][:-5]
            self.assertTrue(all(m['persona_id']==expected for m in p['household_preferences']['member_profiles']))
            self.assertTrue(all(m['role']==role for m in p['joint_sampling']['member_preferences'].values()))
            if role not in 'DF': self.assertFalse(any(d['authorization']['standing_consent_actions'] for d in p['devices']))

    def test_explicit_cross_class_override_is_diagnostic(self):
        c=fixture(); c['energy_preferences']['member_personas']={c['members'][0]['member_id']:'basic_role_d_commuter_ideal_dr'}
        with self.assertRaisesRegex(ValueError,'CANNOT_CHANGE_HOUSEHOLD_CLASS'):generate_personas(c)

    def test_unselected_days_and_A_B_results_cannot_change_draw(self):
        c=fixture(); p=generate_personas(c)
        c['services']=[];c['plans']={'A':'changed','B':'changed'};c['answers']=[1];c['outcomes']={'success':True}
        c['days']=c['days'][-1:]
        self.assertEqual(p,generate_personas(c))

    def test_reordering_does_not_change_draw_or_device_preferences(self):
        c=fixture(); a=generate_personas(c)['joint_sampling']
        c['members'].reverse();c['devices'].reverse();c['habit_days'].reverse()
        b=generate_personas(c)['joint_sampling']
        self.assertEqual(a['devices'],b['devices']);self.assertEqual(a['member_preferences'],b['member_preferences'])

    def test_changed_calendar_does_not_assign_a_new_personality(self):
        c=fixture(); a=generate_personas(c)['joint_sampling']
        for day in c['habit_days']:
            for cal in day['calendars'].values():
                for e in cal:
                    if e['activity']=='home_work': e['activity']='home_free_activity'
        b=generate_personas(c)['joint_sampling']
        self.assertEqual(a['shared_coordinates'],b['shared_coordinates'])
        self.assertEqual(a['member_preferences'],b['member_preferences'])

    def test_missing_authorization_and_mode_bounds_stay_missing(self):
        c=fixture('F'); c['existing_policy']['permissions']['automatic_within_declared_bounds']=False
        for d in generate_personas(c)['devices']:
            self.assertFalse(d['authorization']['standing_consent_actions'])
            self.assertNotIn('change_heating_setpoint',d['authorization']['standing_consent_actions'])
            self.assertNotIn('change_tank_setpoint_preserving_draw_service',d['authorization']['standing_consent_actions'])

    def test_single_and_multiple_members_no_operator_rights_invented(self):
        for role in 'ABCDEF':
            c=fixture(role); c['asset_authority']={}
            p=generate_personas(c)
            self.assertEqual({(d['asset_id'],k) for d in c['devices'] for k in d['types']},{(d['asset_id'],d['kind']) for d in p['devices']})
            for d in p['devices']:
                if d['kind'] in ('washer','dishwasher'):self.assertFalse(d['sampled_preferences']['time_preference']['preferred_start_min'])

    def test_actual_single_member_family_and_member_opinions(self):
        c=fixture('A'); mid=c['members'][0]['member_id']; c['members']=c['members'][:1]
        c['existing_policy']['holder']['person_id']=mid
        for day in c['days']+c.get('habit_days',[]):
            day['calendars']={mid:day['calendars'][mid]}
            day['operator_windows']={mid:day.get('operator_windows',{}).get(mid,[])}
        p=generate_personas(c)
        self.assertEqual(set(p['joint_sampling']['member_preferences']),{mid})
        multi=generate_personas(fixture('B'))['joint_sampling']['member_preferences']
        self.assertGreater(len({digest(m['coordinates']) for m in multi.values()}),1)
        self.assertTrue(all('preference_context' in m and m['preference_context']['confirmation_preferred'] for m in multi.values()))
        text=render_family(p)
        self.assertIn(str(c['members'][0]['age_years'])+'岁',text)
        self.assertIn('原登记确认人',text)

    def test_automatic_combo_has_no_independent_dryer_draw(self):
        c=fixture('B'); washer=next(d for d in c['devices'] if 'washer' in d['types']); washer['types']=['washer','dryer']
        c['devices']=[d for d in c['devices'] if 'dryer' not in d['types'] or d is washer]
        mid=c['members'][0]['member_id'];date=c.get('habit_days',c['days'])[0]['date']
        n={'asset_id':washer['asset_id'],'kind':'washer','need_id':date+':laundry','source_date':date,
           'release_min':0,'deadline_min':1440,'duration_min':60,'maximum_preload_wait_min':120,
           'maximum_retrieval_wait_min':120,'timer_allowed':True,'machine_windows_min':[[0,1440]],'wash_only_delivery':'auto combo wash then dry'}
        c['asset_authority']['assets']={d['asset_id']:{'authorized_operator_ids':[mid],'registered_operator_id':mid} for d in c['devices']}
        c['declared_service_contracts']=[n,{**n,'kind':'dryer','need_id':n['need_id']+':dry','upstream_need_id':n['need_id'],'duration_min':30}]
        p=generate_personas(c); w=next(d['sampled_preferences'] for d in p['devices'] if d['kind']=='washer'); d=next(d['sampled_preferences'] for d in p['devices'] if d['kind']=='dryer')
        self.assertEqual(w['coordinates'],d['coordinates'])
        for root,child in zip(w['time_preference']['per_service'],d['time_preference']['per_service']):
            if root['preferred_start_min'] is not None:self.assertEqual(child['preferred_start_min'],root['preferred_start_min']+60)
        self.assertFalse(d['time_preference']['independent_dryer_time_sampled'])

    def test_loading_validation_and_exact_common_factor(self):
        c=fixture(); rules=read(RULES)
        for value in (-.1,1.1,float('nan'),True):
            with self.assertRaises(ValueError):configuration({'mode':VERSION,'seed':0,'loading':value})
        for loading in (0,.35,.7,.9,1):
            cfg=configuration({'mode':VERSION,'seed':0,'loading':loading})
            x=coordinates(cfg,c['household_id'],['a'],rules); y=coordinates(cfg,c['household_id'],['b'],rules)
            self.assertTrue(all(0<=v<=1 for v in x.values()))
            self.assertEqual(x==y,loading==1)

    def test_published_transform_matches_independent_reference_formula(self):
        # stdlib NormalDist is a separate normal-CDF implementation from SciPy.
        from statistics import NormalDist
        import math
        rules=read(RULES); cfg=configuration({'mode':VERSION,'seed':7,'loading':.7}); hid='math-check';scope=['device','washer']
        actual=coordinates(cfg,hid,scope,rules)
        for dim in rules['dimensions']:
            z=.7*normal(7,hid,['household',dim])+math.sqrt(1-.7**2)*normal(7,hid,[scope,dim])
            self.assertAlmostEqual(actual[dim],NormalDist().cdf(z),places=14)

    def test_cross_midnight_and_empty_domain_no_redraw(self):
        c=preference_input(fixture());aid=next(d['asset_id'] for d in c['devices'] if 'washer' in d['types'])
        date=c['days'][0]['date']; mid=c['members'][0]['member_id']
        c['days']=[{'date':date,'operator_windows':{mid:[[1380,1440]]},'calendars':{}},
                   {'date':str(dt.date.fromisoformat(date)+dt.timedelta(days=1)),'operator_windows':{mid:[[0,300]]},'calendars':{}}]
        n={'asset_id':aid,'source_date':date,'release_min':1440,'deadline_min':1740,'duration_min':60,
           'maximum_preload_wait_min':60,'maximum_retrieval_wait_min':60,'timer_allowed':True,'machine_windows_min':[[0,300]]}
        values,reason=feasible_starts(c,n);self.assertTrue(values);self.assertGreater(min(values),1440);self.assertIsNone(reason)
        n['deadline_min']=1450;self.assertEqual(feasible_starts(c,n)[0],[])
        c['asset_authority']['assets'][aid]['authorized_operator_ids']=[]
        c['asset_authority']['assets'][aid].pop('registered_operator_id')
        n['deadline_min']=1740;self.assertIn('unknown',feasible_starts(c,n)[1])

    def test_missing_machine_window_not_invented_from_A_commands(self):
        c=preference_input(fixture()); n={'asset_id':c['devices'][0]['asset_id'],'source_date':c['days'][0]['date'],
                                        'release_min':0,'deadline_min':1440,'duration_min':60,'load_min':100}
        self.assertEqual(feasible_starts(c,n)[1],'missing_declared_program_or_machine_window')

    def test_frozen_profile_reused_and_tampering_rejected(self):
        c=fixture(); p=generate_personas(c)
        c['frozen_joint_sampling']=p['joint_sampling']
        self.assertEqual(p['joint_sampling'],generate_personas(c)['joint_sampling'])
        c['frozen_joint_sampling']['devices'][0]['tradeoff']='tampered'
        with self.assertRaisesRegex(ValueError,'FROZEN_HASH'):generate_personas(c)

    def test_no_legacy_profile_sampling_and_no_life_mutation(self):
        c=fixture(); del c['energy_preferences']['preference_sampling']
        self.assertNotIn('joint_sampling',generate_personas(c))
        life={'member_calendars':{'x':'unchanged'},'mobility':{'target_soc':.85},'program_policies':[]}
        old=copy.deepcopy(life);result,changes=apply_to_life(life,generate_personas(c))
        self.assertEqual(result,old);self.assertEqual(life,old);self.assertEqual(changes,[])

    def test_soft_cooling_cannot_break_existing_heating_deadband(self):
        p=generate_personas(fixture('B'));d=next(x for x in p['joint_sampling']['devices'] if x['kind']=='ac')
        life={'thermostat_policies':[{'asset_id':d['asset_id'],'cooling_setpoint_C':30,'heating_setpoint_C':d['cooling_preferred_C']}]}
        result,changes=apply_to_life(life,p)
        self.assertEqual(result,life)
        self.assertEqual(changes[0]['reason'],'original_heating_deadband_conflict')

    def test_original_scheduler_consumes_frozen_soft_inputs_only(self):
        from .connect import connect
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp); cfg=read(HERE/'examples/batch.json')
            save(root/'pool.json',read(HERE/'examples/REFERENCE_POOL.json'))
            cfg['pool']={'path':'pool.json','sha256':sha(root/'pool.json')}
            cfg['preference_sampling']={'mode':VERSION};save(root/'input.json',cfg)
            generate(root/'input.json',root/'families'); result=connect(root/'families',root/'connected')
            self.assertEqual(result['requested'],6);self.assertEqual(result['constructed'],6,result['records'])
            for row in result['records']:
                hid=row['household_id']; family=read(root/'families/families'/f'{hid}.json')
                projection,_=apply_to_life(family['life'],family['energy_use_profile'])
                actual=read(root/'connected/life_inputs'/hid/'LIFE_INPUT.json')['households'][0]
                for field in ('member_calendars','mobility','tank_policy','comfort_requirements'):
                    self.assertEqual(actual.get(field),family['life'].get(field))
                self.assertEqual(actual['program_policies'],projection['program_policies'])
                for old,new in zip(family['life']['program_policies'],actual['program_policies']):
                    self.assertEqual({k:v for k,v in old.items() if k!='preferred_start_min'}, {k:v for k,v in new.items() if k!='preferred_start_min'})
                portrait=read(root/'connected'/row['energy_portrait'])
                self.assertEqual(portrait['family_device_profile']['joint_sampling'],family['energy_use_profile']['joint_sampling'])


if __name__=='__main__':unittest.main()
