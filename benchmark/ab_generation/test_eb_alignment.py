"""Public, synthetic counterexamples for EB task and charging semantics."""
import copy,json,unittest
from pathlib import Path
from .common import read,digest
from .eb_alignment import audit,bind_household,compact_plan,runs,CONTIGUOUS,VERSION,operation_windows
from .unified.a_solver import solve
from .unified.candidates import prepare,ev_grammar
from .unified.contract import config
ROOT=Path(__file__).parent

def context():
    c=read(ROOT/'examples/control.json');c['reference']['thermal']={};c['reference']['information_set']['mode']='offline_unexecuted_A_plan'
    c=prepare(c,config({'rows_per_unit':2,'queries_per_row':2}))
    c['native_execution_contract']=dict(version=VERSION,eb_commit='2b17ae63e613da776c93e900f5dace50d63a88a8',controlled_functions=['AC','WM','DR','DW','WH','EV'],function_by_asset={d['asset_id']:[{'washer':'WM','dryer':'DR','dishwasher':'DW','ac':'AC','water_heater':'WH','ev':'EV'}[t] for t in d['types']] for d in c['devices']},operation_policy={'EV':CONTIGUOUS})
    return c

def ev_plan(c,spans):
    b=copy.deepcopy(c['A']);b['controls']=[r for r in b['controls'] if r.get('kind')!='ev_charge_window']
    for i,(a,z) in enumerate(spans):b['controls'].append(dict(asset_id='ev',kind='ev_charge_window',need_id='car',start_min=a,end_min=z))
    return b

def problem():
    policy=dict(duration_min=60,maximum_preload_wait_min=0,maximum_retrieval_wait_min=0,timer_allowed=False,machine_windows_min=[[180,240]],energy_model='legacy_constant_power')
    job=dict(need_id='wash',asset_id='washer',kind='washer',date='2025-07-01',release_min=170,deadline_min=250,preferred_start_min=180,quantity=1,batch_capacity_kg=5,unit='kg',policy=policy)
    world=dict(household_id='counterexample',members=[dict(member_id='M1',household_id='counterexample',can_operate_asset_ids=['washer','ev'])],devices=[dict(asset_id='washer',kind='washer',parameters={'power_kw':1.0},room_id='utility',using_household_ids=['counterexample']),dict(asset_id='ev',kind='ev',parameters=dict(capacity_kwh=20,charger_kw=2,efficiency=.9,initial_energy_kwh=12,target_soc=.8,minimum_soc=.1),room_id='parking',using_household_ids=['counterexample'])],electrical=dict(supply_W=2000))
    return dict(household_id='counterexample',anchor='2025-07-01',end_exclusive='2025-07-02',world=world,jobs=[job],days={'2025-07-01':dict(base_min=0,operator_windows={'M1':[[170,180],[240,250]]},reservations=[])},fixed_operations=[],controls=[],EV=dict(failures=[],journeys=[dict(absolute_departure_min=300,absolute_arrival_min=600,traction_kWh=1)],connections=[dict(need_id='EV0',start_min=60,end_min=300)]),thermostat_policies=[],nonprogram_requirements=[])

class AlignmentTests(unittest.TestCase):
    def test_adjacent_accounting_bins_are_one_session(self):
        self.assertEqual([[1080,1200]],runs([dict(start_min=t,end_min=t+10) for t in range(1080,1200,10)]))
    def test_real_gap_is_not_hidden_by_compaction(self):
        self.assertEqual([[1080,1090],[1100,1120]],runs([dict(start_min=a,end_min=z) for a,z in [(1080,1090),(1100,1110),(1110,1120)]]))
    def test_overlap_is_error(self):
        with self.assertRaisesRegex(ValueError,'OVERLAPPING'):runs([dict(start_min=0,end_min=20),dict(start_min=10,end_min=30)])
    def test_A_fragmentation_counterexample_requires_real_rescheduling(self):
        p=problem();old=solve(p,deterministic_time=2);self.assertEqual('feasible',old['status']);self.assertGreater(len(runs(old['ev_charging_steps'])),1)
        p['world']['devices'][1]['parameters']['charge_session_policy']=CONTIGUOUS
        new=solve(p,deterministic_time=2);self.assertEqual('infeasible',new['status']);self.assertIsNone(new['A'])
    def test_A_continuous_feasible_case_still_completes(self):
        p=problem();p['world']['devices'][1]['parameters']['charge_session_policy']=CONTIGUOUS
        p['jobs'][0].update(release_min=350,deadline_min=430,preferred_start_min=360);p['jobs'][0]['policy']['machine_windows_min']=[[360,420]]
        p['days']['2025-07-01']['operator_windows']={'M1':[[350,360],[420,430]]}
        a=solve(p,deterministic_time=2);self.assertEqual('feasible',a['status']);self.assertEqual(1,len(runs(a['ev_charging_steps'])))
        self.assertGreaterEqual(sum(r['grid_kWh'] for r in a['ev_charging_steps'])*.9,4-1e-6)
    def test_B_grammar_removes_arbitrary_pauses_for_V9(self):
        c=context();d=next(d for d in c['devices'] if 'ev' in d['types']);d['parameters']['charge_session_policy']=CONTIGUOUS
        rows=list(ev_grammar(c,d,config()));self.assertTrue(rows)
        self.assertEqual({'ev_defer'},{r['mechanism'] for r in rows})
        self.assertTrue(all(len(runs(r['profiles']['B']))<=1 for r in rows))
    def test_fragmented_B_is_rejected(self):
        c=context();child=dict(asset_id='ev',family='ev',service_need_id='car',profiles={'B':[dict(start_min=1140,end_min=1150,power_kw=3),dict(start_min=1160,end_min=1270,power_kw=3)]},magnitude={})
        result=audit(c,ev_plan(c,[(1140,1150),(1160,1270)]),[child]);self.assertTrue(any('UNDECLARED_INTERRUPTION' in e for e in result['hard_errors']))
    def test_native_EV_window_crossing_VPP_is_not_mislabeled_continuous(self):
        c=context();child=dict(asset_id='ev',family='ev',service_need_id='car',profiles={'B':[dict(start_min=1070,end_min=1200,power_kw=3)]},magnitude={})
        self.assertTrue(any('WOULD_PAUSE' in e for e in audit(c,ev_plan(c,[(1070,1200)]),[child])['hard_errors']))
    def test_smart_pause_is_allowed_only_as_explicit_native_policy(self):
        c=context();c['native_execution_contract']['operation_policy']['EV']='eb_smart_vpp_pause'
        next(o for o in c['A']['operations'] if o['kind']=='EV_plug').update(start_min=1040,end_min=1050)
        child=dict(asset_id='ev',family='ev',service_need_id='car',profiles={'B':[dict(start_min=1050,end_min=1080,power_kw=3),dict(start_min=1140,end_min=1230,power_kw=3)]},magnitude={})
        b=ev_plan(c,[(1050,1230)])
        self.assertFalse(audit(c,b,[child])['hard_errors'])
        child['profiles']['B'][1]['start_min']=1150
        self.assertTrue(any('DIFFERS_FROM_NATIVE_COMMANDS' in e for e in audit(c,b,[child])['hard_errors']))
    def test_complete_unchanged_programs_pass(self):
        c=context();self.assertFalse(audit(c,c['A'],side='A')['hard_errors'])
    def test_fake_continuous_caption_does_not_override_actual_B_commands(self):
        c=context();child=dict(asset_id='ev',family='ev',service_need_id='car',profiles={'B':[dict(start_min=1140,end_min=1260,power_kw=3)]},magnitude={})
        b=ev_plan(c,[(1140,1200),(1210,1270)])
        errors=audit(c,b,[child])['hard_errors']
        self.assertTrue(any('UNDECLARED_INTERRUPTION' in e for e in errors));self.assertTrue(any('DIFFERS_FROM_NATIVE_COMMANDS' in e for e in errors))
    def test_program_cannot_be_split_to_meet_event(self):
        c=context();b=copy.deepcopy(c['A']);b['tasks'].append(copy.deepcopy(b['tasks'][0]))
        self.assertTrue(any('TASK_SPLIT' in e for e in audit(c,b)['hard_errors']))
    def test_program_duration_must_be_preserved(self):
        c=context();b=copy.deepcopy(c['A']);b['tasks'][0]['end_min']-=30
        self.assertTrue(any('DURATION_CHANGED' in e for e in audit(c,b)['hard_errors']))
    def test_running_program_cannot_be_moved(self):
        c=context();c['decision_min']=700;b=copy.deepcopy(c['A']);b['tasks'][0]['start_min']+=10;b['tasks'][0]['end_min']+=10
        self.assertTrue(any('STARTED_PROGRAM' in e for e in audit(c,b)['hard_errors']))
    def test_shared_asset_fixed_function_is_preserved(self):
        c=context();c['native_execution_contract']['controlled_functions'].remove('WM');b=copy.deepcopy(c['A']);b['tasks'][0]['start_min']-=10;b['tasks'][0]['end_min']-=10
        self.assertTrue(any('UNCONTROLLED_FUNCTION' in e for e in audit(c,b)['hard_errors']))
    def test_multiple_loads_require_explicit_native_capability_upgrade(self):
        c=context();b=copy.deepcopy(c['A']);t=copy.deepcopy(b['tasks'][0]);t.update(task_id='second',need_id='second',start_min=1200,end_min=1320);b['tasks'].append(t)
        self.assertTrue(any('SINGLE_DAILY_TASK' in e for e in audit(c,b)['hard_errors']))
    def test_presentation_merges_bins_without_filling_real_gaps(self):
        c=context();view=compact_plan(c,c['A'],side='A');self.assertEqual([[1080,1200]],view['charging_sessions'][0]['runs_min'])
    def test_household_binding_requires_actual_dated_adapter_lineage(self):
        c=context();case=dict(case_id=c['household_id'],household=dict(controlled_function_ids=['AC','WM','DR','DW','WH','EV'],service_contracts={'EV':{'operation_policy':CONTIGUOUS}}))
        with self.assertRaisesRegex(ValueError,'SOURCE_BINDING_REQUIRED'):bind_household(c,case,'manifest')
        c['source']['household_case_sha256']=digest(case);bound=bind_household(c,case,'manifest');self.assertEqual(digest(case),bound['native_execution_contract']['household_case_sha256'])
        self.assertNotIn('native_execution_contract', {k:v for k,v in c.items() if k!='native_execution_contract'})
    def test_exact_life_clock_is_preserved_when_extracting_machine_grid(self):
        case={'household':{'members':[{'id':'M1'}],'routine':{'daily_services':[{'manual_operation_opportunities':[{'member_id':'M1','start':605,'end':643}]} for _ in range(7)]}}}
        before=copy.deepcopy(case);row=operation_windows(case,['2026-11-09'])['2026-11-09']
        self.assertEqual([[610,640]],row['operator_windows']['M1']);self.assertEqual(case,before)
        self.assertEqual([605,643],row['source_window_bindings'][0]['exact_source_min'])
    def test_short_operation_gap_never_creates_fake_ten_minutes(self):
        case={'household':{'members':[{'id':'M1'}],'routine':{'daily_services':[{'manual_operation_opportunities':[{'member_id':'M1','start':605,'end':614}]} for _ in range(7)]}}}
        self.assertEqual([],operation_windows(case,['2026-11-09'])['2026-11-09']['operator_windows']['M1'])
    def test_fixed_tank_control_cannot_be_changed_via_existing_asset_permission(self):
        c=context();c['native_execution_contract']['controlled_functions'].remove('WH');b=copy.deepcopy(c['A'])
        row=next(r for r in b['controls'] if r['kind']=='tank_setpoint');row['value_C']+=1
        self.assertTrue(any('FIXED_SERVICE_CHANGED:WH' in e for e in audit(c,b)['hard_errors']))
    def test_loading_and_retrieval_cannot_be_silently_deleted(self):
        c=context();b=copy.deepcopy(c['A']);b['operations'].pop()
        self.assertTrue(any('OPERATION_REMOVED' in e for e in audit(c,b)['hard_errors']))
    def test_source_binding_does_not_admit_a_world_missing_controlled_assets(self):
        c=context();case=dict(case_id=c['household_id'],household=dict(controlled_function_ids=['AC','WM','DR','DW','WH','EV'],service_contracts={}))
        c['source']['household_case_sha256']=digest(case);c['devices']=[d for d in c['devices'] if 'ev' not in d['types']]
        with self.assertRaisesRegex(ValueError,'MISSING_CONTROLLED_FUNCTION_ASSET'):bind_household(c,case,'manifest')
    def test_service_failure_is_reported_separately_from_mechanical_fragment(self):
        c=context();child=dict(asset_id='ev',family='ev',service_need_id='car',profiles={'B':[dict(start_min=1140,end_min=1200,power_kw=3)]},magnitude={'energy_shortfall_kWh':2})
        r=audit(c,ev_plan(c,[(1140,1200)]),[child]);self.assertFalse(r['hard_errors']);self.assertTrue(r['service_risks'])

def generation_context():
    c=read(ROOT/'examples/control.json');c['reference']['thermal']={}
    c['reference']['information_set']['mode']='offline_unexecuted_A_plan'
    c['native_execution_contract']=context()['native_execution_contract']
    return c

class GoalRecheckTests(unittest.TestCase):
    def test_formal_household_entry_requires_actual_target_source(self):
        from .unified.candidates import generate_household_day
        with self.assertRaisesRegex(ValueError,'VERIFIED_NATIVE_TARGET_SOURCE_REQUIRED'):
            generate_household_day({}, {}, 'f'*64)
    def test_target_capability_cannot_be_self_declared(self):
        import tempfile
        from .eb_alignment import verify_native_target
        with tempfile.TemporaryDirectory() as td:
            path=Path(td)/'appliance_sim.py';path.write_text('# unverified implementation')
            with self.assertRaisesRegex(ValueError,'NATIVE_TARGET_NOT_VERIFIED'):
                verify_native_target(path)
    def test_full_plan_replay_does_not_require_missing_explanation_profiles(self):
        c=context();b=ev_plan(c,[(1140,1260)])
        r=audit(c,b,[dict(family='ev',service_need_id='car')])
        self.assertTrue(r['passed'])
    def test_explicit_empty_charging_claim_is_still_checked(self):
        c=context();b=ev_plan(c,[(1140,1260)])
        r=audit(c,b,[dict(family='ev',service_need_id='car',profiles={'B':[]})])
        self.assertTrue(any('DECLARED_EV_PROFILE_DIFFERS' in e for e in r['hard_errors']))
    def test_B_instructions_determine_VPP_behavior_without_component_metadata(self):
        c=context();plug=next(o for o in c['A']['operations'] if o['kind']=='EV_plug')
        plug.update(start_min=1060,end_min=1070)
        b=ev_plan(c,[(1070,1260)])
        errors=audit(c,b,children=())['hard_errors']
        self.assertTrue(any('EV_UNDECLARED_INTERRUPTION' in e for e in errors))
    def test_extra_permission_gap_cannot_hide_after_SOC_target_is_met(self):
        c=context();b=ev_plan(c,[(1140,1260),(1270,1280)])
        self.assertTrue(any('EV_PERMISSION_GAP_NOT_NATIVE' in e for e in audit(c,b)['hard_errors']))
    def test_EV_window_cannot_extend_beyond_actual_connection(self):
        c=context();b=ev_plan(c,[(1790,1900)])
        self.assertTrue(any('OUTSIDE_PHYSICAL_CONNECTION' in e for e in audit(c,b)['hard_errors']))
    def test_A_charging_profile_must_match_its_instructions(self):
        c=context()
        for r in c['reference']['ev_charging_steps']:r['start_min']+=10;r['end_min']+=10
        self.assertTrue(any('A_EV_PROFILE_DIFFERS' in e for e in audit(c,c['A'],side='A')['hard_errors']))
    def test_A_operations_must_also_fit_qualified_source_windows(self):
        c=context();c['operator_windows']['p1']=[[0,10]]
        self.assertTrue(any('HANDLER_OUTSIDE_SOURCE' in e for e in audit(c,c['A'],side='A')['hard_errors']))
    def test_operation_duration_cannot_be_shortened_to_fit_a_gap(self):
        c=context();b=copy.deepcopy(c['A']);b['operations'][0]['end_min']-=5
        self.assertTrue(any('IDENTITY_OR_DURATION' in e for e in audit(c,b)['hard_errors']))
    def test_unknown_control_cannot_enter_native_plan(self):
        c=context();b=copy.deepcopy(c['A']);b['controls'].append(dict(asset_id='ev',kind='binary_on_off',start_min=1200,end_min=1210))
        self.assertIn('UNKNOWN_OR_MISMATCHED_NATIVE_CONTROL',audit(c,b)['hard_errors'])
    def test_V9_lineage_cannot_silently_opt_out_of_alignment(self):
        from .unified.candidates import generate_day
        c=generation_context();del c['native_execution_contract'];c['source']['household_case_sha256']='f'*64
        r=generate_day(c,config({'rows_per_unit':2,'queries_per_row':2}))
        self.assertEqual('baseline_native_execution_error',r['status']);self.assertEqual([],r['rows'])
        self.assertIn('V9_NATIVE_EXECUTION_BINDING_REQUIRED',r['engineering_diagnostics'])
    def test_invalid_A_is_rejected_before_any_B_search(self):
        from .unified.candidates import generate_day
        c=generation_context();c['needs'][0]['duration_min']=120;c['A']['tasks'][0]['end_min']-=10
        r=generate_day(c,config({'rows_per_unit':2,'queries_per_row':2}))
        self.assertEqual('baseline_native_execution_error',r['status']);self.assertEqual([],r['rows'])
    def test_legacy_context_cannot_be_presented_as_an_aligned_plan(self):
        c=context();del c['native_execution_contract']
        with self.assertRaisesRegex(ValueError,'BINDING_REQUIRED_FOR_PLAN_SUMMARY'):compact_plan(c,c['A'])
    def test_parking_opportunity_does_not_invent_a_new_charge_requirement(self):
        p=problem();p['EV']['journeys']=[]
        p['world']['devices'][1]['parameters']['charge_session_policy']=CONTIGUOUS
        result=solve(p,deterministic_time=2)
        self.assertEqual('feasible',result['status']);self.assertEqual([],result['ev_charging_steps'])

if __name__=='__main__':unittest.main()
