
from unittest import TestCase
from unittest.mock import patch
import copy,datetime as dt
from benchmark.ab_generation.v9_date_adapter import _build_problem_with_source_episode
from benchmark.ab_generation.eb_alignment import handler_in_source_window

class EpisodeContractTests(TestCase):
    def fixture(self):
        anchor=dt.date(2007,7,16);mid='synthetic:M01';aid='synthetic-EV'
        case={'case_id':'synthetic','household':{'members':[{'id':'M01'}],
          'ev':{'service_scope':'one selected parking-session episode; not repeated daily charging demand',
                'parking_sessions':[{'arrival':d*1440+1080,'next_departure':(d+1)*1440+480,'parking_hours':14} for d in range(7)],
                'vehicle_user_member_id':'M01','arrival_soc':.35}}}
        problem={'days':{(anchor+dt.timedelta(days=d)).isoformat():{'base_min':d*1440,
           'calendars':{mid:[{'start_min':0,'end_min':1440,'location':'home','room_id':'reference-home'}]},
           'operator_windows':{mid:[[d*1440+1200,d*1440+1260]]},'reservations':[]} for d in range(15)},
          'jobs':[{'kind':'washer','release_min':0,'deadline_min':1440}],
          'world':{'devices':[{'asset_id':aid,'kind':'ev','room_id':'parking','parameters':{
              'capacity_kwh':60,'initial_energy_kwh':21,'target_soc':.85,'minimum_soc':.1,'charger_kw':3.6,'efficiency':.9}}],
              'members':[{'member_id':mid,'household_id':'synthetic','can_operate_asset_ids':[]}]},
          'fixed_operations':[], 'EV':{'connections':[{'start_min':d*1440,'end_min':(d+1)*1440} for d in range(14)],'journeys':[],'failures':[]},
          'input_lineage':{}}
        return case,problem
    def build(self,case,problem):
        with patch('benchmark.ab_generation.v9_date_adapter._build_problem_opportunity_legacy',return_value=copy.deepcopy(problem)):
            return _build_problem_with_source_episode(case,'2007-07-16',{},days=14,service_date='2007-07-18')
    def test_parking_opportunities_do_not_become_daily_demands(self):
        case,p=self.fixture();before=copy.deepcopy(case);q=self.build(case,p)
        self.assertEqual(case,before)
        self.assertEqual(len(q['EV']['connections']),1)
        self.assertEqual(len(q['EV']['journeys']),1)
        self.assertEqual(q['EV']['journeys'][0]['traction_kWh'],0)
        self.assertFalse(q['EV']['episode']['daily_traction_or_arrival_SOC_reset_invented'])
        self.assertEqual(q['fixed_operations'],[])
    def test_source_connection_is_not_shortened_by_invented_handling(self):
        case,p=self.fixture();q=self.build(case,p);connection=q['EV']['connections'][0]
        self.assertEqual(q['fixed_operations'],[])
        self.assertEqual(connection['origin'],'given_source_parking_episode')
        self.assertEqual(connection['start_min'],q['EV']['episode']['physical_home_witness'][0])
        self.assertEqual(connection['end_min'],q['EV']['episode']['physical_home_witness'][1])
        self.assertEqual(q['EV']['episode']['mapped_operator_id'],'synthetic:M01')
    def test_a_source_vehicle_user_must_exist(self):
        case,p=self.fixture();case['household']['ev']['vehicle_user_member_id']='missing'
        with self.assertRaisesRegex(ValueError,'EV_DRIVER_NOT_SOURCE_MEMBER'):self.build(case,p)
    def test_no_actual_home_parking_is_rejected(self):
        case,p=self.fixture()
        for d in p['days'].values():d['calendars']['synthetic:M01'][0]['location']='away'
        with self.assertRaisesRegex(ValueError,'NO_ACTUAL_HOME_WITNESS'):self.build(case,p)
    def test_historical_weekly_scaffold_is_not_a_daily_task_contract(self):
        case,p=self.fixture();q=self.build(case,p)
        self.assertEqual(len(q['jobs']),1)
        self.assertEqual(q['jobs'][0]['release_min'],0)
        self.assertEqual(q['jobs'][0]['deadline_min'],11520)

class OperationWindowTests(TestCase):
    def context(self):
        return {'operator_windows':{'M01':[[100,110]]},'native_execution_contract':{'EV_episode_binding':{'asset_id':'EV','mapped_operator_id':'M01'}},
                'native_operation_windows_by_asset':{'EV':{'M01':[[200,210]]}}}
    def test_ev_transaction_does_not_make_chore_time_available(self):
        c=self.context();base={'operator_id':'M01','asset_id':'EV','start_min':200,'end_min':210}
        self.assertTrue(handler_in_source_window(c,{**base,'kind':'EV_plug'}))
        self.assertFalse(handler_in_source_window(c,{**base,'kind':'load'}))
        self.assertFalse(handler_in_source_window(c,{**base,'kind':'EV_plug','asset_id':'other'}))
    def test_ev_transaction_cannot_move_outside_its_bound_window(self):
        self.assertFalse(handler_in_source_window(self.context(),{'kind':'EV_unplug','operator_id':'M01','asset_id':'EV','start_min':190,'end_min':200}))
    def test_legacy_handling_uses_original_windows(self):
        self.assertTrue(handler_in_source_window({'operator_windows':{'M01':[[100,110]]}},{'kind':'load','operator_id':'M01','asset_id':'washer','start_min':100,'end_min':110}))


class NativeChargingContinuityTests(TestCase):
    def feasible(self,values,connections):
        from ortools.sat.python import cp_model
        from benchmark.ab_generation.unified.a_solver import limit_native_charge_starts
        model=cp_model.CpModel();flags=[model.new_bool_var('charge:'+str(i)) for i in range(len(values))]
        for flag,value in zip(flags,values):model.add(flag==value)
        limit_native_charge_starts(model,flags,connections)
        return cp_model.CpSolver().solve(model) in (cp_model.FEASIBLE,cp_model.OPTIMAL)
    def test_whole_base_session_is_allowed(self):
        self.assertTrue(self.feasible([1,1,0,0],[{'start_min':0,'end_min':40}]))
    def test_arbitrary_on_off_on_is_rejected(self):
        self.assertFalse(self.feasible([1,0,1,0],[{'start_min':0,'end_min':40}]))
    def test_distinct_physical_parking_episodes_are_separate(self):
        self.assertTrue(self.feasible([1,0,1,0],[{'start_min':0,'end_min':10},{'start_min':20,'end_min':30}]))

class SourceConnectionStateTests(TestCase):
    def context(self):
        from benchmark.ab_generation.connection_states import attach,ORIGIN
        source={'household_case_sha256':'a'*64,'household_input_manifest_sha256':'b'*64}
        c={'source':dict(source),'native_execution_contract':dict(source),
           'physical_ev_connections':[{'origin':ORIGIN,'need_id':'need','start_min':100,'end_min':200}]}
        episode={'asset_id':'EV','mapped_operator_id':'M01','source_driver_member_id':'M01',
                 'connection_interval':[100,200],'physical_home_witness':[90,210]}
        return attach(c,episode)
    def plan(self,start=110,end=190):
        return {'operations':[],'tasks':[],'controls':[{'kind':'ev_charge_window','asset_id':'EV','need_id':'need','start_min':start,'end_min':end}]}
    def test_source_reference_state_is_explicit_and_preserved(self):
        from benchmark.ab_generation.connection_states import valid,covers
        c=self.context();self.assertTrue(valid(c));self.assertTrue(covers(c,self.plan()))
        e=c['native_execution_contract']['source_connected_episode']
        self.assertTrue(e['connection_state_is_reference_condition_not_observed_plugging'])
        self.assertTrue(e['connection_state_is_shared_by_AB'])
    def test_charge_window_cannot_extend_past_fixed_connection(self):
        from benchmark.ab_generation.connection_states import covers
        self.assertFalse(covers(self.context(),self.plan(110,210)))
    def test_forged_source_binding_is_rejected(self):
        from benchmark.ab_generation.connection_states import valid
        c=self.context();c['source']['household_case_sha256']='different'
        self.assertFalse(valid(c))
    def test_modified_connection_record_is_rejected(self):
        from benchmark.ab_generation.connection_states import valid
        c=self.context();c['physical_ev_connections'][0]['end_min']=220
        self.assertFalse(valid(c))
    def test_legacy_or_unbound_state_cannot_bypass_handling_checks(self):
        from benchmark.ab_generation.connection_states import covers
        self.assertFalse(covers({},self.plan()))
    def test_other_engineering_failures_are_kept(self):
        from benchmark.ab_generation.unified.candidates import engineering_issues
        with patch('benchmark.ab_generation.unified.candidates.legacy_engineering_issues',
                   return_value=['INCOMPLETE_EV_CONNECTION','OTHER_FAILURE']):
            self.assertEqual(engineering_issues(self.context(),self.plan()),['OTHER_FAILURE'])

class SourceConnectionRebindingTests(TestCase):
    context=SourceConnectionStateTests.context
    def test_attaching_same_bound_episode_is_idempotent(self):
        from benchmark.ab_generation.connection_states import valid,attach
        c=self.context();before=c['native_execution_contract']['source_connected_episode']['binding_sha256']
        attach(c,c['native_execution_contract']['source_connected_episode'])
        self.assertTrue(valid(c))
        self.assertEqual(c['native_execution_contract']['source_connected_episode']['binding_sha256'],before)
    def test_rebinding_household_keeps_valid_connected_episode(self):
        from benchmark.ab_generation.eb_alignment import bind_household
        from benchmark.ab_generation.connection_states import valid
        c=self.context()
        def core(context,case,manifest_sha256,**kwargs):
            result=copy.deepcopy(context)
            result['native_execution_contract'].pop('source_connected_episode')
            return result
        with patch('benchmark.ab_generation.eb_alignment._bind_household_source_core',side_effect=core):
            result=bind_household(c,{},'b'*64)
        self.assertTrue(valid(result))
    def test_invalid_prior_episode_is_not_repaired_by_rebinding(self):
        from benchmark.ab_generation.eb_alignment import bind_household
        c=self.context();c['physical_ev_connections'][0]['start_min']=90
        with self.assertRaisesRegex(ValueError,'VALID_ORIGIN'):bind_household(c,{},'b'*64)

class OneDayServiceScopeTests(TestCase):
    def test_cross_morning_charge_tail_is_not_cut_into_another_question(self):
        from benchmark.ab_generation.v9_date_adapter import complete_day_service_scope
        c={'A':{'operations':[],'tasks':[],'controls':[{'asset_id':'EV','kind':'ev_charge_window','need_id':'n','start_min':1860,'end_min':1920}]},
           'horizon_min':[480,1920],'reference':{'binding':{}},
           'physical_ev_connections':[{'need_id':'n','start_min':1800,'end_min':2000}]}
        p={'anchor':'2007-07-18','EV':{'episode':{'scope':'reference'}}}
        A={'A':{'controls':[{'asset_id':'EV','kind':'ev_charge_window','need_id':'n','start_min':1860,'end_min':1950}]}}
        complete_day_service_scope(c,p,A,'2007-07-18')
        self.assertEqual(c['question_window_min'],[480,1920])
        self.assertEqual(c['question_unit'],'one_dated_household_day')
        self.assertEqual(c['A']['controls'][0]['end_min'],1950)
        self.assertEqual(c['horizon_min'][1],2000)
    def test_day_without_service_tail_keeps_original_24h_window(self):
        from benchmark.ab_generation.v9_date_adapter import complete_day_service_scope
        c={'A':{'operations':[],'tasks':[],'controls':[]},'horizon_min':[480,1920],'reference':{'binding':{}},'physical_ev_connections':[]}
        complete_day_service_scope(c,{'EV':{},'anchor':'2007-07-18'},{'A':{'controls':[]}},'2007-07-18')
        self.assertEqual(c['question_window_min'],[480,1920]);self.assertEqual(c['horizon_min'],[480,1920])

class SourceCalendarBoundaryTests(TestCase):
    def test_preceding_day_operation_keeps_its_actual_source_window(self):
        from benchmark.ab_generation.eb_alignment import bind_household
        c={'question_unit':'one_dated_household_day','date':'2007-07-18','A':{'operations':[{'operation_id':'n:load','asset_id':'WM','kind':'load','need_id':'n','room_id':'service','operator_id':'M01','duration_min':10,'start_min':-140,'end_min':-130}],'controls':[],'tasks':[]},
           'horizon_min':[480,1920],'reference':{'binding':{}}}
        with patch('benchmark.ab_generation.eb_alignment._bind_household_source_core',side_effect=lambda context,*a,**k:copy.deepcopy(context)):
            with patch('benchmark.ab_generation.eb_alignment.operation_windows',return_value={'2007-07-17':{'base_min':0,'operator_windows':{'M01':[[1300,1320]]}}}) as source:
                result=bind_household(c,{},'manifest')
        self.assertEqual(source.call_args.kwargs['anchor'],'2007-07-17')
        self.assertEqual(result['operator_windows']['M01'],[[-140,-120]])

class CompleteDayPredecessorTests(TestCase):
    def test_day_scoring_window_does_not_crop_fixed_loading_history(self):
        from benchmark.ab_generation.v9_date_adapter import complete_day_service_scope
        op={'operation_id':'n:load','asset_id':'WM','kind':'load','need_id':'n','operator_id':'M01','start_min':-140,'end_min':-130}
        c={'A':{'tasks':[],'operations':[op],'controls':[]},'horizon_min':[480,1920],'physical_ev_connections':[],'reference':{'binding':{}}}
        complete_day_service_scope(c,{'EV':{}},{'A':c['A']},'2007-07-18')
        self.assertEqual(c['question_window_min'],[480,1920])
        self.assertEqual(c['horizon_min'][0],-140)
        self.assertEqual(c['A']['operations'][0],op)

class PrimaryDayClockTests(TestCase):
    def context(self,earliest=0,latest=28):
        from benchmark.ab_generation.primary_day_clock import NATIVE_SOURCE_SHA256
        return {'question_unit':'one_dated_household_day','decision_min':1020,
                'native_execution_contract':{'primary_programme_windows':{'WM':{'washer':{
                  'earliest_h':earliest,'latest_h':latest,'duration_h':4,'native_source_sha256':NATIVE_SOURCE_SHA256}}}}}
    def task(self,start):
        return {'asset_id':'WM','kind':'washer','start_min':start,'end_min':start+240}
    def test_today_start_preserves_complete_overnight_programme(self):
        from benchmark.ab_generation.primary_day_clock import start_supported
        self.assertTrue(start_supported(self.context(),self.task(1200),self.task(1380)))
    def test_larger_check_horizon_does_not_invent_tomorrow_dispatch(self):
        from benchmark.ab_generation.primary_day_clock import start_supported
        c=self.context();c['horizon_min']=[-1440,10080]
        self.assertFalse(start_supported(c,self.task(1200),self.task(1560)))
    def test_explicit_native_overnight_window_can_dispatch_after_midnight(self):
        from benchmark.ab_generation.primary_day_clock import start_supported
        self.assertTrue(start_supported(self.context(19,7),self.task(1200),self.task(1560)))
    def test_precommitted_future_baseline_is_not_a_new_dispatch(self):
        from benchmark.ab_generation.primary_day_clock import start_supported
        self.assertTrue(start_supported(self.context(),self.task(1560),self.task(1560)))
