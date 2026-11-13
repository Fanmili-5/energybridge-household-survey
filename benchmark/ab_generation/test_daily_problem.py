"""Native EB contract tests; intentionally no loading/retrieval fixtures."""
from copy import deepcopy
import datetime as dt
import hashlib,inspect,os
from pathlib import Path
from unittest import TestCase
from unittest.mock import patch
from .eb_primary import PROTOCOL
from .v9_date_adapter import build_problem,generate_day_baseline
from .unified.contract import entry_config
from .eb_alignment import audit
from .upstream_eb_routine import _schedule_no_dr_routine_appliances

NATIVE=Path(os.environ.get('EB_NATIVE_SOURCE',str(Path(__file__).resolve().parents[2].parent/'native_runtime_candidate/appliance_sim.py')))
MANIFEST='a'*64

class NativeDailyTests(TestCase):
    def fixture(self,ev=False,shared=False):
        fs={'AC':'ac','WM':'washer','DR':'dryer','DW':'dishwasher'}
        if ev:fs.update(WH='water_heater',EV='ev')
        registry={f:{'asset_id':f,'functions':[f]} for f in fs}
        if shared:
            del registry['DR'];registry['WM']['functions'].append('DR')
        h={'members':[{'id':'M'}],'controlled_function_ids':list(fs),'service_asset_registry':registry,
           'calendar':{'weekly_events':[]},'comfort':{'preferred_cooling_c':[24,26],'allowed_short_adjustment_c':1.0},
           'service_contracts':{f:{'operation_policy':'whole_non_interruptible_cycle'} for f in fs}}
        h['service_contracts']['DR']['predecessor']={'same_load_required':True,'timing':'wash_end_lte_dry_start'}
        h['service_contracts']['AC']['operation_policy']='bounded_temperature_setpoint'
        if ev:
            h['service_contracts']['EV']['operation_policy']='single_contiguous_session_per_episode'
            h['ev']={'vehicle_user_member_id':'M','parking_sessions':[{'arrival':i*1440+1080,'next_departure':(i+1)*1440+480} for i in range(7)],
                     'arrival_soc':.4,'departure_soc_target':.8,'reference_battery_kwh':60,'reference_charger_kw':3.6,
                     'charge_efficiency':.9,'service_scope':'one selected parking-session episode; not repeated daily charging demand',
                     'charging_contiguity':'one_continuous_session_is_required_for_base_need'}
        h['routine']={'daily_services':[{'day':day,'flexible_chore_window':[1080,1200],'meals':[{'kind':'dinner','location':'home','start':1080,'end':1110}], 'bathing_services':[{'start':1140,'end':1150,'member_id':'M'}]} for day in range(7)]}
        case={'case_id':'synthetic-native','household':h}
        ref={'programs':{k:{'duration_min':d,'nominal_peak_kw':kw} for k,d,kw in [('washer',120,1.5),('dryer',60,2),('dishwasher',90,1)]},
             'AC_nominal_upper_W':None,'tank_normal_C':55,'tank_maximum_C':65,'heating_C':20,'EV_reserve_SOC':.15}
        cfg=entry_config();cfg['A_target_context_mode']='frozen_v3'
        return case,ref,cfg
    def generate(self,ev=False,shared=False):
        if not NATIVE.exists():self.skipTest('EB_NATIVE_SOURCE is required for original-code replay')
        case,ref,cfg=self.fixture(ev,shared)
        result=generate_day_baseline(case,'2007-07-18',ref,cfg,MANIFEST,native_appliance_source_path=NATIVE)
        self.assertEqual(result['status'],'accepted_plan_only')
        return case,ref,cfg,result
    def test_native_path_does_not_require_any_manual_household_fields(self):
        case,ref,cfg,result=self.generate()
        self.assertFalse(any('manual_operation_opportunities' in r for r in case['household']['routine']['daily_services']))
        self.assertEqual(result['result']['A']['operations'],[])
        self.assertEqual(result['context']['operator_windows'],{})
        self.assertEqual(result['context']['source']['appliance_command_protocol'],PROTOCOL)
        for need in result['context']['needs']:
            self.assertFalse({'maximum_preload_wait_min','maximum_retrieval_wait_min','timer_allowed'}&need.keys())
    def test_original_upstream_routine_is_really_called(self):
        case,ref,cfg=self.fixture()
        if not NATIVE.exists():self.skipTest('original EB source unavailable')
        with patch('benchmark.ab_generation.eb_primary._schedule_no_dr_routine_appliances',wraps=_schedule_no_dr_routine_appliances) as sampler:
            r=generate_day_baseline(case,'2007-07-18',ref,cfg,MANIFEST,native_appliance_source_path=NATIVE)
        self.assertEqual(r['status'],'accepted_plan_only');self.assertGreaterEqual(sampler.call_count,1)
        self.assertIn('household_routine_schedule',r['result'])
    def test_daily_complete_programmes_finish_same_date(self):
        _,ref,_,r=self.generate()
        self.assertEqual(len(r['result']['A']['tasks']),3)
        for t in r['result']['A']['tasks']:
            self.assertEqual(t['end_min']-t['start_min'],ref['programs'][t['kind']]['duration_min'])
            self.assertTrue(480<=t['start_min']<t['end_min']<=1440)
    def test_shared_asset_never_runs_simultaneous_programmes(self):
        _,_,_,r=self.generate(shared=True);ts=[t for t in r['result']['A']['tasks'] if t['asset_id']=='WM']
        ts.sort(key=lambda t:t['start_min']);self.assertLessEqual(ts[0]['end_min'],ts[1]['start_min'])
    def test_existing_declared_order_remains_without_invented_transfer(self):
        _,_,_,r=self.generate();ts={t['kind']:t for t in r['result']['A']['tasks']}
        self.assertLessEqual(ts['washer']['end_min'],ts['dryer']['start_min'])
        self.assertEqual(r['result']['A']['operations'],[])
    def test_fixed_present_programme_is_retained(self):
        case,ref,cfg=self.fixture();case['household']['controlled_function_ids'].remove('DW')
        if not NATIVE.exists():self.skipTest('original EB source unavailable')
        r=generate_day_baseline(case,'2007-07-18',ref,cfg,MANIFEST,native_appliance_source_path=NATIVE)
        self.assertEqual(r['status'],'accepted_plan_only')
        self.assertEqual(sum(t['kind']=='dishwasher' for t in r['result']['A']['tasks']),1)
    def test_A_is_blind_to_VPP_event_and_source_is_unchanged(self):
        case,ref,cfg=self.fixture();before=deepcopy(case)
        if not NATIVE.exists():self.skipTest('original EB source unavailable')
        a=generate_day_baseline(case,'2007-07-18',ref,cfg,MANIFEST,native_appliance_source_path=NATIVE)
        cfg['event']['start_min']=600;cfg['event']['end_min']=660
        b=generate_day_baseline(case,'2007-07-18',ref,cfg,MANIFEST,native_appliance_source_path=NATIVE)
        self.assertEqual(a['result']['A'],b['result']['A']);self.assertEqual(case,before)
    def test_seed_is_reproducible_without_a_hardcoded_universal_start(self):
        case,ref,cfg=self.fixture()
        if not NATIVE.exists():self.skipTest('original EB source unavailable')
        starts=set()
        for seed in range(12):
            cfg['seed']=seed;r=generate_day_baseline(case,'2007-07-18',ref,cfg,MANIFEST,native_appliance_source_path=NATIVE)
            starts.add(next(t['start_min'] for t in r['result']['A']['tasks'] if t['kind']=='washer'))
        self.assertGreater(len(starts),5)
    def test_EV_is_the_only_overnight_service_and_reaches_target(self):
        _,_,_,r=self.generate(ev=True);A=r['result']['A']
        windows=[x for x in A['controls'] if x['kind']=='ev_charge_window']
        self.assertEqual(len(windows),1);self.assertGreater(windows[0]['end_min'],1440)
        steps=r['result']['ev_charging_steps'];self.assertTrue(all(a['end_min']==b['start_min'] for a,b in zip(steps,steps[1:])))
        self.assertAlmostEqual(sum(s['grid_kWh'] for s in steps)*.9,24,places=6)
    def test_B_insufficient_EV_is_rejected_not_only_warned(self):
        _,_,_,r=self.generate(ev=True);c=r['context'];b=deepcopy(c['A'])
        ev=next(x for x in b['controls'] if x['kind']=='ev_charge_window');ev['end_min']=ev['start_min']+10
        result=audit(c,b,side='B')
        self.assertFalse(result['passed']);self.assertIn('EV_DEPARTURE_TARGET_NOT_MET',result['hard_errors'])
    def test_B_non_EV_overnight_programme_is_rejected(self):
        _,_,_,r=self.generate();c=r['context'];b=deepcopy(c['A']);t=next(x for x in b['tasks'] if x['kind']=='washer')
        t['start_min']=1380;t['end_min']=1500
        result=audit(c,b,side='B')
        self.assertFalse(result['passed']);self.assertIn('NON_EV_PROGRAMME_OVERNIGHT_FORBIDDEN',result['hard_errors'])
    def test_B_cannot_add_invented_human_operations(self):
        _,_,_,r=self.generate();c=r['context'];b=deepcopy(c['A'])
        b['operations']=[{'operation_id':'invented','asset_id':'WM','need_id':'invented','operator_id':'M','kind':'load','room_id':'utility','start_min':480,'end_min':490}]
        result=audit(c,b,side='B');self.assertFalse(result['passed']);self.assertIn('NON_EB_MANUAL_OPERATION',result['hard_errors'])
    def test_B_valid_post_event_continuous_EV_meets_target(self):
        _,_,_,r=self.generate(ev=True);c=r['context'];b=deepcopy(c['A']);ev=next(x for x in b['controls'] if x['kind']=='ev_charge_window')
        ev['start_min']=1140
        result=audit(c,b,side='B');self.assertTrue(result['passed'],result['hard_errors'])
        self.assertFalse(result['service_risks'])
    def test_time_origin_translation_includes_start_window(self):
        from .unified.pipeline import fresh_context
        _,_,cfg,r=self.generate();p=deepcopy(r['problem']);a=deepcopy(r['result'])
        origin=dt.date.fromisoformat(p['anchor']);p['anchor']=(origin-dt.timedelta(days=1)).isoformat()
        for day in p['days'].values():day['base_min']+=1440
        for j in p['jobs']:
            j['release_min']+=1440;j['deadline_min']+=1440;j['start_window_min']=[v+1440 for v in j['start_window_min']]
        for collection in a['A'].values():
            for row in collection:row['start_min']+=1440;row['end_min']+=1440
        c=fresh_context(p,a,'2007-07-18',None,cfg)
        self.assertEqual([n['start_window_min'] for n in c['needs']],[n['start_window_min'] for n in r['context']['needs']])
    def test_native_programme_variants_have_no_handling_and_no_overnight(self):
        from .eb_primary_candidates import programmes
        _,_,_,r=self.generate();c=r['context'];d=next(d for d in c['devices'] if 'washer' in d['types'])
        raws=list(programmes(c,d));self.assertTrue(raws)
        for raw in raws:
            self.assertEqual(raw['mechanism'],'start_time_shift')
            self.assertTrue(all(p['collection']=='tasks' for p in raw['patches']))
            for p in raw['patches']:
                self.assertTrue(all(t['end_min']<=1440 for t in p['rows']))
    def test_legacy_handling_compiler_is_explicitly_retired(self):
        from .daily_problem import compile_question_day
        with self.assertRaisesRegex(ValueError,'REMOVED_NON_EB'):compile_question_day({}, {}, {}, '2007-07-18')
    def test_missing_question_date_fails_before_generation(self):
        with self.assertRaisesRegex(ValueError,'EXPLICIT_SERVICE_DATE'):build_problem({},'2007-07-16',{})

class NativeBIntegrationTests(TestCase):
    fixture=NativeDailyTests.fixture
    generate=NativeDailyTests.generate
    def test_B_entry_has_no_handling_dependencies_and_returns_valid_candidates(self):
        from .unified.candidates import generate_household_day
        from .model import apply
        case,_,cfg,r=self.generate(ev=True)
        cfg['rows_per_unit']=2;cfg['queries_per_row']=1
        result=generate_household_day(r['context'],case,MANIFEST,cfg,native_appliance_source_path=NATIVE)
        self.assertEqual(result['status'],'candidate_catalogue');self.assertTrue(result['rows'])
        for row in result['rows']:
            b=apply(r['context']['A'],row['patches'])
            self.assertEqual(b['operations'],[])
            checked=audit(r['context'],b,side='B')
            self.assertTrue(checked['passed'],checked['hard_errors'])
            self.assertFalse(any(s.startswith('EV_DEPARTURE') for s in checked['service_risks']))

class NativeACPermissionTests(TestCase):
    fixture=NativeDailyTests.fixture
    generate=NativeDailyTests.generate
    def test_absence_is_not_a_fabricated_actuator_permission_barrier(self):
        from .unified.candidates import raw_grammar
        _,_,cfg,r=self.generate()
        context=deepcopy(r['context']);context['occupancy']={}
        self.assertTrue(any(row['family']=='ac' for row in raw_grammar(context,cfg)))
        self.assertEqual(context['occupancy'],{})

class NativeServiceContractTests(TestCase):
    fixture=NativeDailyTests.fixture
    generate=NativeDailyTests.generate
    def test_EV_relevance_uses_actual_event_energy_change(self):
        from .eb_primary_candidates import ev_windows
        from .unified.ev_request_relevance import direct
        _,_,_,r=self.generate(ev=True);c=r['context'];d=next(d for d in c['devices'] if 'ev' in d['types'])
        candidates=list(ev_windows(c,d));self.assertTrue(candidates)
        self.assertTrue(any(direct(c,row,c['events'][0]) for row in candidates))
    def test_WH_candidates_are_single_native_windows_without_clamping(self):
        from .eb_primary_candidates import wh_windows
        _,_,cfg,r=self.generate(ev=True);c=r['context'];d=next(d for d in c['devices'] if 'water_heater' in d['types'])
        candidates=list(wh_windows(c,d,cfg));self.assertTrue(candidates)
        for row in candidates:
            self.assertEqual(len(row['patches']),1);patch=row['patches'][0]
            self.assertEqual(patch['type'],'rows');self.assertEqual(len(patch['rows']),1)
            command=patch['rows'][0]
            self.assertTrue(45<=command['value_C']<=65)
            self.assertTrue(0<command['end_min']-command['start_min']<=240)
            self.assertLessEqual(command['end_min'],1440)
    def test_WH_temperature_that_native_would_clamp_is_rejected(self):
        _,_,_,r=self.generate(ev=True);c=r['context'];b=deepcopy(c['A'])
        next(x for x in b['controls'] if x['kind']=='tank_setpoint')['value_C']=35
        result=audit(c,b,side='B')
        self.assertFalse(result['passed']);self.assertIn('PRIMARY_WATER_HEATER_TEMPERATURE_UNREPRESENTABLE',result['hard_errors'])
    def test_accepted_A_start_record_matches_authoritative_plan(self):
        _,_,_,r=self.generate()
        for task in r['result']['A']['tasks']:
            self.assertEqual(r['result']['native_accepted_programme_start_h'][task['kind']+'_start_h']*60,task['start_min'])


class HouseholdRoutineBindingTests(TestCase):
    fixture=NativeDailyTests.fixture
    def test_A_responds_to_household_routine_without_mutating_source(self):
        from .common import digest
        case,ref,cfg=self.fixture()
        if not NATIVE.exists():self.skipTest('original EB source unavailable')
        before=digest(case);a=generate_day_baseline(case,'2007-07-18',ref,cfg,MANIFEST,native_appliance_source_path=NATIVE)
        self.assertEqual(before,digest(case))
        for day in case['household']['routine']['daily_services']:
            day['flexible_chore_window']=[900,960]
        b=generate_day_baseline(case,'2007-07-18',ref,cfg,MANIFEST,native_appliance_source_path=NATIVE)
        starts=lambda e:{t['kind']:t['start_min'] for t in e['context']['A']['tasks']}
        self.assertNotEqual(starts(a)['washer'],starts(b)['washer'])
        self.assertEqual([t['end_min']-t['start_min'] for t in a['context']['A']['tasks']],[t['end_min']-t['start_min'] for t in b['context']['A']['tasks']])
    def test_odd_minute_baths_do_not_create_off_grid_heater_commands(self):
        case,ref,cfg=self.fixture(ev=True)
        if not NATIVE.exists():self.skipTest('original EB source unavailable')
        for day in case['household']['routine']['daily_services']:
            day['bathing_services'][0].update(start=1145,end=1155)
        e=generate_day_baseline(case,'2007-07-18',ref,cfg,MANIFEST,native_appliance_source_path=NATIVE)
        for c in e['context']['A']['controls']:
            if c['kind']=='tank_setpoint':self.assertEqual((c['start_min']%10,c['end_min']%10),(0,0))
        self.assertEqual(case['household']['routine']['daily_services'][2]['bathing_services'][0]['start'],1145)

    def test_late_dinner_uses_an_existing_earlier_meal_without_overnight(self):
        case,ref,cfg=self.fixture();ref['programs']['dishwasher']['duration_min']=240
        if not NATIVE.exists():self.skipTest('original EB source unavailable')
        for day in case['household']['routine']['daily_services']:
            day['meals']=[dict(kind='breakfast',location='home',start=440,end=470,participants=['M']),dict(kind='dinner',location='home',start=1260,end=1290,participants=['M'])]
        e=generate_day_baseline(case,'2007-07-18',ref,cfg,MANIFEST,native_appliance_source_path=NATIVE)
        job=next(j for j in e['problem']['jobs'] if j['kind']=='dishwasher')
        task=next(t for t in e['context']['A']['tasks'] if t['kind']=='dishwasher')
        self.assertEqual(job['A_reference_dish_load']['meal_kind'],'breakfast')
        self.assertGreaterEqual(task['start_min'],470);self.assertLessEqual(task['end_min'],1440)
        self.assertEqual(job['release_min'],480) # Native B window is not replaced by the meal preference.
