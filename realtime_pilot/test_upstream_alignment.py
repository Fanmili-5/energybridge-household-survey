"""Boundary parity with pinned EB plus real EP actuator/decision evidence."""
import ast
from contextlib import redirect_stdout
from copy import deepcopy
from io import StringIO
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from common import UPSTREAM, ROOT, normalize_answers, write_json
from paired_contract import LOOKUP,prepare
from verify_paired_physics import answers
from household_config import bind_household
from eb_execution import upstream
from eb_controller_adapter import daily_plan_due,planning_evidence
from closed_loop import simulate_live,EBPlanner,display_trajectory
from paired_ep import pair_metrics


def request(**changes):
    raw=answers();raw.update(changes)
    profile=normalize_answers(raw,list(LOOKUP),LOOKUP)
    original,scenario=prepare(profile,'alignment_v27')
    # This suite records the historical v2.7 custom loop, not the new entry.
    from evaluation_window import make_window
    scenario['evaluation_window']=make_window(original)
    scenario.update(decision_h=17,event={'id':'alignment_v27','trigger_h':18,'end_h':19,'day':4})
    return {'profile':profile,'original_plan':original,'scenario':scenario,'household_id':'engineering_alignment_v27'}


from legacy_test_support import prepare


class AlignmentTests(unittest.TestCase):
    def test_daily_trigger_matches_original_callback_ast(self):
        runner,_=upstream()
        tree=ast.parse((UPSTREAM/'experiments/benchmark/family_runner.py').read_text())
        native=next(n for n in ast.walk(tree) if isinstance(n,ast.For) and isinstance(n.target,ast.Name)
            and n.target.id=='_day_idx' and any(isinstance(x,ast.Name) and x.id=='_crossed_plan' for x in ast.walk(n)))
        code=compile(ast.fix_missing_locations(ast.Module(body=[native],type_ignores=[])),'<native daily trigger>','exec')
        for previous,now in ((95.833333,96),(96,96.166667),(95,96.5),(95,97),(88.833333,89)):
            for done in ({0,1,2,3},{0,1,2,3,4}):
                a=runner._FamilyLoop();b=runner._FamilyLoop()
                a.daily_plans_done=set(done);b.daily_plans_done=set(done)
                env={'loop':a,'sim_days':5,'sim_h':now,'psim':previous,'planning_hour':runner.DEFAULT_PLANNING_HOUR,
                     '_plan_grace_h':max(.25,2/6),'triggered_daily_plan':False}
                exec(code,env)
                self.assertEqual(daily_plan_due(b,now,previous,1/6,5),env['triggered_daily_plan'])
                self.assertEqual(a.daily_plans_done,b.daily_plans_done)

    def test_native_household_state_and_literal_answer_provenance(self):
        runner,_=upstream()
        for option,expected in (('confirm_required','ask_first'),('high_trust_auto','delegated')):
            r=request(A_EB_CONTROL=option);loop=runner._FamilyLoop();h=bind_household(loop,r)
            self.assertEqual(runner._agent_memory_profile(loop)['automation_preference'],expected)
            self.assertEqual(h['tags']['control'],option)
            raw=next(a for a in loop.agent_preference_memory['onboarding']['answers'] if a['id']=='a_eb_control')
            self.assertEqual(raw['selected_option_ids'],[option])
            self.assertTrue(loop.agent_operations_knowledge['facts'])
            tolerance=loop.agent_household_model['traits']['thermostat_change_tolerance_c']
            self.assertIsNone(tolerance['distribution']['mean'])
            self.assertEqual(tolerance['confidence'],0)
            self.assertIsNone(h['meta']['preset_household_id'])

    def test_native_evidence_reaches_saved_model_request(self):
        from energybridge.llm.client import LLMClient
        runner,Suite=upstream();r=request();loop=runner._FamilyLoop();h=bind_household(loop,r)
        loop.appliance_suite=Suite(h['appliances'],sim_days=5,explicit_only=True)
        loop.sim_days=5;loop.weather_label='tianjin';loop.sp=25
        loop.current_occupied=True;loop.current_occupancy_count=3
        observation={'temperature_c':25,'outdoor_c':32,'facility_w':3000,'occupancy_count':3}
        with tempfile.TemporaryDirectory() as directory:
            planner=EBPlanner(r,Path(directory),lambda *a:None)
            with patch.object(LLMClient,'chat_with_metrics',side_effect=TimeoutError('engineering fixture')):
                planner(loop,89,observation,[],['notification'])
            import json
            inputs=json.loads((Path(directory)/'round_001/planning_input.json').read_text())['inputs']
        self.assertEqual(inputs['observable_state']['hourly_tariff']['coverage_hours'],24)
        self.assertEqual(inputs['observable_state']['hourly_tariff']['unit'],'CNY/kWh')
        self.assertTrue(inputs['observable_state']['professional_hvac_rollout']['candidate_setpoints'])
        self.assertTrue(inputs['observable_state']['operational_knowledge']['facts'])
        self.assertEqual(inputs['event']['demand_context']['source'],'fallback')
        event={'id':'alignment_v27','trigger_h':90,'end_h':91}
        evidence=planning_evidence(loop,sim_h=90,observed=observation,event=event,
            appliances=h['appliances'],tariff=r['scenario']['tariff'])
        capacity=loop.vpp_capacity_by_id[event['id']]
        expected=runner._call_vpp_demand_agent(event['id'],household_capacity=capacity,observed_baseline_kw=3,duration_h=1)
        self.assertEqual(evidence['demand_context'],expected)
        self.assertTrue(evidence['hvac_rollout']['candidate_setpoints'])

    def test_ev_equal_clock_rejected_and_overnight_preserved(self):
        with self.assertRaisesRegex(ValueError,'相同时刻'):request(H_home_ev='evening',D_home_ev='18')
        r=request(H_home_ev='late',D_home_ev='8')
        self.assertEqual(r['scenario']['evaluation_window']['ev_departure_sim_h'],104)
        _,Suite=upstream();ev=Suite(r['original_plan']['eb_appliance_config'],sim_days=5,explicit_only=True)._ev
        self.assertTrue(ev._is_home(23));self.assertTrue(ev._is_home(7));self.assertFalse(ev._is_home(8))

    def test_real_ep_common_prefix_occupancy_and_midnight_planning(self):
        r=request(H_ac='evening',B04='mostly_occupied',F_EVENING='mostly_away')
        folder=ROOT/'data/upstream_alignment_v2_7';folder.mkdir(parents=True,exist_ok=True)
        def planner(loop,now,observed,history,reasons):
            plan=deepcopy(r['original_plan']['eb_ordinary_plan'])
            plan.update(setpoint=27 if now<96 else 26,next_check_hour=None)
            return plan,'工程测试：跨日与占用控制，不是真人数据。'
        with (folder/'console.log').open('w') as log,redirect_stdout(log):
            baseline=simulate_live(folder/'baseline',r)
            proposal=simulate_live(folder/'proposal',r,planner)
        metric=pair_metrics(baseline,proposal,r['scenario'])
        p=lambda hour:next(x for x in proposal['controls'] if abs(x['start_h']-hour)<1e-6)
        b=lambda hour:next(x for x in baseline['controls'] if abs(x['start_h']-hour)<1e-6)
        self.assertTrue(p(89)['hvac_available']);self.assertFalse(b(89)['hvac_available'])
        self.assertFalse(p(91)['hvac_available']);self.assertTrue(b(91)['hvac_available'])
        self.assertTrue(all(x['hvac_availability_actuator']==int(x['hvac_available']) for x in proposal['controls']))
        self.assertEqual(p(95+5/6)['cooling_setpoint'],27)
        self.assertEqual(p(96)['cooling_setpoint'],26)
        midnight=next(d for d in proposal['decisions'] if d['sim_h']==96)
        self.assertIn('daily_plan',midnight['trigger'])
        self.assertFalse(any(a['kind']=='ordinary' and a['sim_h']>=89 for a in proposal['execution']['applications']))
        self.assertEqual(baseline['idf_sha256'],proposal['idf_sha256'])
        display=display_trajectory(r['original_plan'],baseline,proposal,r['scenario'],metric)
        write_json(folder/'verification.json',{'engineering_only':True,'status':'passed',
            'metrics':metric,'midnight_decision':midnight,'control_17':p(89),'control_19':p(91),
            'control_2350':p(95+5/6),'control_0000':p(96),
            'native_actuator_meter_checks':proposal['task_energy_checks'],
            'live_observation_sql_check':proposal['live_observation_sql_check'],'display':display})


if __name__=='__main__':unittest.main()
