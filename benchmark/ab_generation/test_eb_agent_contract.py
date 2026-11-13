from unittest import TestCase
from copy import deepcopy
from benchmark.ab_generation.eb_agent_contract import plan_errors,household_bounds,complete_appliance_payload
from benchmark.ab_generation import upstream_eb_agent_contract as original

class MainAgentActionContractTests(TestCase):
    def fixture(self):
        tasks=[dict(task_id=k,need_id=k,asset_id=k,kind=k,start_min=t,end_min=t+60,power_kw=1.0) for k,t in [("washer",600),("dryer",720),("dishwasher",900)]]
        ac=dict(asset_id="ac",kind="ac_setpoint",start_min=0,end_min=1440,cooling_setpoint_C=26.0,heating_setpoint_C=20.0,fan_operating_mode=0,_unified_id="ac0")
        wh=dict(asset_id="water_heater",kind="tank_setpoint",start_min=1020,end_min=1260,value_C=60.0,_unified_id="wh0")
        controls=[ac,{**ac,"start_min":1440,"end_min":2880,"_unified_id":"ac1"},wh,{**wh,"start_min":2460,"end_min":2700,"_unified_id":"wh1"},dict(asset_id="ev",kind="ev_charge_window",need_id="evneed",start_min=1080,end_min=1920,stop_at_target_soc=.8,_unified_id="ev0")]
        a=dict(tasks=tasks,operations=[],controls=controls)
        limits=household_bounds({"comfort":{"preferred_cooling_c":[24,26],"allowed_short_adjustment_c":1}})
        c=dict(source={"appliance_command_protocol":"eb.primary_appliance_calls.v1"},decision_min=480,A=a,
            native_execution_contract={"agent_action_bounds":limits,"primary_water_heater_configuration":{"pre_heat_window_start_h":15,"pre_heat_window_end_h":18}},
            authority={"assets":{k:{"target_control_authorized":True} for k in ["washer","dryer","dishwasher","ac","water_heater","ev"]}})
        return c,deepcopy(a)
    def cool(self,plan,value,duration=30):
        row=plan["controls"][0]
        plan["controls"]=[{**row,"end_min":1080},{**row,"start_min":1080,"end_min":1080+duration,"cooling_setpoint_C":value},{**row,"start_min":1080+duration}]+plan["controls"][1:]
    def test_reference_is_valid(self):
        c,b=self.fixture();self.assertEqual(plan_errors(c,b),[])
    def test_all_three_programmes_allow_complete_start_shift(self):
        for kind in ["washer","dryer","dishwasher"]:
            c,b=self.fixture();r=next(r for r in b["tasks"] if r["kind"]==kind);r["start_min"]+=30;r["end_min"]+=30
            self.assertEqual(plan_errors(c,b),[])
    def test_all_three_reject_power_duration_and_custom_programme(self):
        for kind in ["washer","dryer","dishwasher"]:
            for field,value in [("power_kw",.2),("programme","eco")]:
                c,b=self.fixture();next(r for r in b["tasks"] if r["kind"]==kind)[field]=value
                self.assertIn("AGENT_CANNOT_CHANGE_PROGRAMME_ID_POWER_OR_HARDWARE",plan_errors(c,b))
            c,b=self.fixture();next(r for r in b["tasks"] if r["kind"]==kind)["end_min"]-=10
            self.assertIn("AGENT_CANNOT_CHANGE_PROGRAMME_DURATION",plan_errors(c,b))
    def test_dropping_required_programme_is_rejected(self):
        c,b=self.fixture();b["tasks"].pop()
        self.assertIn("AGENT_PROGRAMME_SERVICE_SET_CHANGED",plan_errors(c,b))
    def test_ac40_heating_fan_and_power_are_rejected(self):
        for key,value,expected in [("cooling_setpoint_C",40,"OUTSIDE_ORIGINAL_AGENT_COOLING_RANGE"),("heating_setpoint_C",18,"AGENT_AC_ONLY_COOLING_SETPOINT_IS_MUTABLE"),("fan_operating_mode",1,"AGENT_AC_ONLY_COOLING_SETPOINT_IS_MUTABLE"),("power_kw",0,"AGENT_AC_ONLY_COOLING_SETPOINT_IS_MUTABLE")]:
            c,b=self.fixture();b["controls"][0][key]=value
            self.assertIn(expected,plan_errors(c,b))
    def test_ac_point25_is_rejected_before_rounding(self):
        c,b=self.fixture();self.cool(b,26.25)
        self.assertIn("AGENT_AC_TEMPERATURE_WOULD_BE_ROUNDED",plan_errors(c,b))
    def test_ac10min_is_rejected_and20_30_60_accepted(self):
        c,b=self.fixture();self.cool(b,27,10)
        self.assertIn("PAPER_V1_CHECKPOINT_CLOCK_CANNOT_REPRODUCE_LITERAL_PLAN",plan_errors(c,b))
        for duration in [20,30,60]:
            c,b=self.fixture();self.cool(b,27,duration);self.assertEqual(plan_errors(c,b),[])
    def test_soft_preference_violation_is_still_eligible(self):
        c,b=self.fixture();self.cool(b,27.5);self.assertEqual(plan_errors(c,b),[])
    def test_wh_temperature_and_window_are_allowed(self):
        c,b=self.fixture();b["controls"][2].update(start_min=960,end_min=1200,value_C=65)
        self.assertEqual(plan_errors(c,b),[])
    def test_wh_power_and_tank_size_are_not_actions(self):
        for key in ["power_kw","tank_volume_l"]:
            c,b=self.fixture();b["controls"][2][key]=1
            self.assertIn("AGENT_CANNOT_CHANGE_SERVICE_TARGET_OR_HARDWARE",plan_errors(c,b))
    def test_wh_rejects_actual_runtime_clamp_and_temperature(self):
        c,b=self.fixture();b["controls"][2]["start_min"]=960
        self.assertIn("AGENT_WH_WINDOW_WOULD_BE_BOUNDED",plan_errors(c,b))
        c,b=self.fixture();b["controls"][2]["value_C"]=80
        self.assertIn("PAPER_V1_WH_TEMPERATURE_WOULD_BE_CLIPPED",plan_errors(c,b))
    def test_ev_start_after_midnight_is_expressible_in_dated_queue(self):
        c,b=self.fixture();b["controls"][-1].update(start_min=1500,end_min=1800)
        self.assertEqual(plan_errors(c,b),[])
    def test_ev_soc_power_and_capacity_are_not_actions(self):
        for key in ["stop_at_target_soc","charger_kw","capacity_kwh","initial_soc"]:
            c,b=self.fixture();b["controls"][-1][key]=.6
            self.assertIn("AGENT_CANNOT_CHANGE_SERVICE_TARGET_OR_HARDWARE",plan_errors(c,b))
    def test_ev_multiple_windows_are_rejected(self):
        c,b=self.fixture();b["controls"].append({**b["controls"][-1],"start_min":1500,"end_min":1600})
        self.assertIn("AGENT_REQUIRES_SINGLE_CONTIGUOUS_SERVICE_WINDOW",plan_errors(c,b))
    def test_serialized_service_targets_are_explicit(self):
        c,b=self.fixture();actions=complete_appliance_payload(b)
        for kind in ["washer","dryer","dishwasher"]:
            self.assertIs(actions[kind+"_skip"],False)
        self.assertIs(actions["water_heater_preheat"],True)
    def test_uncontrolled_service_cannot_be_changed(self):
        c,b=self.fixture();c["authority"]["assets"]["water_heater"]["target_control_authorized"]=False;b["controls"][2]["value_C"]=61
        self.assertIn("TARGET_CONTROL_NOT_AUTHORIZED",plan_errors(c,b))
    def test_missing_bound_contract_is_not_admitted(self):
        c,b=self.fixture();del c["native_execution_contract"]["agent_action_bounds"]
        self.assertEqual(plan_errors(c,b),["ORIGINAL_AGENT_ACTION_BOUNDS_NOT_BOUND"])
    def test_all_three_uncontrolled_programmes_remain_fixed(self):
        for kind in ["washer","dryer","dishwasher"]:
            c,b=self.fixture();c["authority"]["assets"][kind]["target_control_authorized"]=False
            row=next(r for r in b["tasks"] if r["kind"]==kind);row["start_min"]+=30;row["end_min"]+=30
            self.assertIn("TARGET_CONTROL_NOT_AUTHORIZED",plan_errors(c,b))

    def test_prepare_rejects_an_unsupported_A_before_any_search(self):
        from benchmark.ab_generation.unified.candidates import prepare
        c,b=self.fixture()
        c["reference"]={"information_set":{"mode":"offline_unexecuted_A_plan"}}
        c["A"]["controls"][0]["cooling_setpoint_C"]=40
        with self.assertRaisesRegex(ValueError,"A_OUTSIDE_ORIGINAL_AGENT_CONTRACT"):
            prepare(c,{})
    def test_primary_candidate_checks_reject_extra_actions(self):
        from unittest.mock import patch
        from benchmark.ab_generation.eb_primary_candidates import checks
        c,b=self.fixture()
        patch40=dict(type="control_interval",asset_id="ac",kind="ac_setpoint",start_min=1080,end_min=1110,values={"cooling_setpoint_C":40})
        with patch("benchmark.ab_generation.eb_primary_candidates.request_issues",return_value=[]),patch("benchmark.ab_generation.eb_primary_candidates.control_issues",return_value=[]),patch("benchmark.ab_generation.eb_primary_candidates.site_capacity",return_value={"issues":[]}):
            _,gate,_=checks(c,[patch40])
        self.assertIn("OUTSIDE_ORIGINAL_AGENT_COOLING_RANGE",gate)
    def test_unsupported_actions_are_excluded_before_coverage_factors(self):
        from unittest.mock import patch
        from benchmark.ab_generation.unified.candidates import catalogue_domains
        c,b=self.fixture();c.update(household_id="synthetic",date="2007-07-18")
        raw=dict(family="ac",asset_id="ac",service_need_id=None,mechanism="event_setpoint",branch="aligned",needs=[],profiles=None,
            magnitude={"dose_coordinate":1,"manual_total_shift_min":0},
            patches=[dict(type="control_interval",asset_id="ac",kind="ac_setpoint",start_min=1080,end_min=1110,values={"cooling_setpoint_C":27})])
        bad=deepcopy(raw);bad["patches"][0]["values"]["cooling_setpoint_C"]=40
        cfg={"seed":1,"relative_cuts":[.33,.66],"method_revision":"guard_test","event":{"start_min":1080,"end_min":1140}}
        with patch("benchmark.ab_generation.unified.candidates.raw_grammar",return_value=iter([bad,raw])),patch("benchmark.ab_generation.unified.candidates.control_issues",return_value=[]),patch("benchmark.ab_generation.unified.candidates.direct",return_value=True),patch("benchmark.ab_generation.unified.candidates.absolute_level",return_value="test"):
            frame=catalogue_domains(c,cfg)
        self.assertEqual(len(frame["values"]),1)
        self.assertEqual(len(frame["values"][0]),2)
        self.assertEqual(frame["engineering_diagnostics"][0]["rejection_stage"],"original_agent_action_domain")

    def test_preference_policy_is_not_a_generation_gate(self):
        c,b=self.fixture()
        c["native_execution_contract"]["agent_action_bounds"]=household_bounds({"comfort":{"preferred_cooling_c":[23,24],"allowed_short_adjustment_c":0}})
        self.cool(b,28)
        self.assertEqual(plan_errors(c,b),[])
    def test_original_event_checkpoint_rescues_ten_minute_pulse(self):
        from benchmark.ab_generation.model import apply
        c,b=self.fixture();c["events"]=[{"start_min":1080,"end_min":1140}]
        b=apply(b,[dict(type="control_interval",asset_id="ac",kind="ac_setpoint",start_min=1070,end_min=1080,values={"cooling_setpoint_C":27})])
        self.assertEqual(plan_errors(c,b),[])
    def test_original_pre_event_checkpoint_can_interrupt_a_longer_gap(self):
        from benchmark.ab_generation.model import apply
        c,b=self.fixture();c["events"]=[{"start_min":1080,"end_min":1140}]
        b=apply(b,[dict(type="control_interval",asset_id="ac",kind="ac_setpoint",start_min=1000,end_min=1030,values={"cooling_setpoint_C":27})])
        self.assertIn("PAPER_V1_CHECKPOINT_CLOCK_CANNOT_REPRODUCE_LITERAL_PLAN",plan_errors(c,b))
