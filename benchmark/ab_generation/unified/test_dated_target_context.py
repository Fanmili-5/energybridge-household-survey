import copy
import itertools
import unittest

from .dated_target_context import derive, local_candidates, qualified_members


def fixture():
    policy = dict(duration_min=20, machine_windows_min=[[0,1440]], timer_allowed=True,
                  maximum_preload_wait_min=20, maximum_retrieval_wait_min=20)
    job = dict(need_id='wash', asset_id='w', kind='washer', date='2025-01-01',
               release_min=1400, deadline_min=1510, policy=policy)
    world = dict(devices=[dict(asset_id='w',room_id='r',kind='washer',using_household_ids=['h'])],
                 members=[dict(member_id=m, household_id='h', can_operate_asset_ids=['w']) for m in ('a','b')])
    days = {'2025-01-01':dict(base_min=0, reservations=[], operator_windows={'a':[[1400,1440]],'b':[]}),
            '2025-01-02':dict(base_min=1440, reservations=[], operator_windows={'a':[],'b':[[1440,1510]]})}
    problem = dict(household_id='h',anchor='2025-01-01',world=world,days=days,jobs=[job])
    profile = dict(household_id='h',joint_sampling=dict(devices=[dict(asset_id='w',kind='washer',
                   coordinates={'time_orientation':.8},time_preference={'per_service':[]})]))
    return problem, profile


class ConditionalTargets(unittest.TestCase):
    def test_cross_midnight_domain_matches_independent_triple_enumeration(self):
        p,_=fixture();job=p['jobs'][0]
        slots=list(range(1400,1510,10));expected=set()
        # Independent literal temporal inequalities, without generator helpers.
        for load,start,unload in itertools.product(slots,repeat=3):
            if load+10<=start and start-load-10<=20 and start+20<=unload and unload-start-20<=20 and unload+10<=1510:
                expected.add(start)
        actual,_=local_candidates(p,job)
        self.assertEqual({r['start_min'] for r in actual},expected)
        self.assertTrue(any(r['start_min']<1440<r['end_min'] for r in actual))
        self.assertTrue(any(r['loader']!=r['retriever'] for r in actual))

    def test_registered_handler_restriction_is_not_relaxed(self):
        p,_=fixture();p['world']['devices'][0]['operator_id']='a'
        actual,_=local_candidates(p,p['jobs'][0])
        self.assertEqual([r['start_min'] for r in actual],[1410])
        self.assertTrue(all(r['loader']==r['retriever']=='a' for r in actual))
        p['days']['2025-01-01']['operator_windows']['a']=[[1400,1420]]
        self.assertEqual(local_candidates(p,p['jobs'][0])[0],[])

    def test_normal_assignment_and_external_members_respected(self):
        p,_=fixture();asset=p['world']['devices'][0]
        p['world']['members'].append(dict(member_id='helper',household_id='other',can_operate_asset_ids=['w']))
        asset['using_household_ids'].append('other')
        self.assertEqual(qualified_members(p,asset),['a','b'])
        asset['normal_operator_ids']=['helper']
        self.assertEqual(qualified_members(p,asset),['helper'])
        asset['operator_id']='a'
        self.assertEqual(qualified_members(p,asset),[])

    def test_no_new_draw_owner_consent_or_input_mutation(self):
        p,profile=fixture();before=copy.deepcopy((p,profile));r=derive(p,profile)
        self.assertEqual((p,profile),before);self.assertEqual(r,derive(p,profile))
        self.assertEqual(r['new_random_draws'],0)
        self.assertFalse(r['rows'][0]['reference_member_assigned'])
        self.assertFalse(r['rows'][0]['execution_consent'])
        altered=copy.deepcopy(p);altered.update(legacy_comparator={'A':'changed'},answers=True,B='changed',outcomes={'success':True})
        self.assertEqual(r,derive(altered,profile))

    def test_original_known_target_kept_and_missing_coordinate_stays_unknown(self):
        p,profile=fixture();d=profile['joint_sampling']['devices'][0]
        d['time_preference']['per_service']=[dict(source_date='2025-01-01',need_id='wash',preferred_start_min=1430)]
        self.assertEqual(derive(p,profile)['rows'][0]['target_min'],1430)
        d['time_preference']['per_service']=[];d['coordinates']={}
        self.assertEqual(derive(p,profile)['rows'][0]['reason'],'missing_frozen_time_coordinate')

    def test_dryer_target_follows_actual_local_retrieval_not_just_wash_end(self):
        p,profile=fixture();p['jobs'][0]['deadline_min']=1700
        p['days']['2025-01-02']['operator_windows']['b']=[[1500,1700]]
        p['jobs'][0]['policy']['maximum_retrieval_wait_min']=100
        child=copy.deepcopy(p['jobs'][0]);child.update(need_id='dry',kind='dryer',asset_id='d',depends_on_need_id='wash')
        p['jobs'].append(child)
        asset=copy.deepcopy(p['world']['devices'][0]);asset.update(asset_id='d',kind='dryer');p['world']['devices'].append(asset)
        for m in p['world']['members']:m['can_operate_asset_ids'].append('d')
        d=copy.deepcopy(profile['joint_sampling']['devices'][0]);d.update(asset_id='d',kind='dryer');profile['joint_sampling']['devices'].append(d)
        r={r['need_id']:r for r in derive(p,profile)['rows']}
        self.assertGreaterEqual(r['dry']['local_witness']['load_min'],r['wash']['local_witness']['unload_min']+10)
        self.assertEqual(r['dry']['origin'],'experimental_earliest_after_parent_retrieval;not_independent_dryer_draw')

    def test_explicit_shared_window_overrides_random_clock_direction(self):
        p,profile=fixture();profile['joint_sampling']['devices'][0]['explicit_shared_declaration']={'earliest_h':23.5,'latest_h':24}
        r=derive(p,profile)['rows'][0]
        self.assertLessEqual(r['local_witness']['end_min'],1440)

    def test_unknown_mode_and_household_mismatch_are_rejected(self):
        from .contract import config
        with self.assertRaisesRegex(ValueError,'UNKNOWN_A_TARGET_CONTEXT_MODE'):config({'A_target_context_mode':'guess'})
        p,profile=fixture();profile['household_id']='other'
        with self.assertRaisesRegex(ValueError,'HOUSEHOLD'):derive(p,profile)


if __name__=='__main__':unittest.main()
