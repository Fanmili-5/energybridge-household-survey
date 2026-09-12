"""Checks for source checkpoints, chronological ledgers and full-trajectory display."""
from copy import deepcopy
import unittest
from common import normalize_answers
from paired_contract import LOOKUP,prepare,validate,participant_view
from verify_paired_physics import answers
from eb_execution import upstream
from closed_loop import next_checkpoint,display_trajectory

from legacy_test_support import prepare

class ClosedLoopTests(unittest.TestCase):
    def test_native_checkpoints_and_model_requested_earlier_checks(self):
        runner,_=upstream();event={'trigger_h':90,'end_h':91,'id':'vpp'}
        for now in (88,88.5,89,90,90.5,91,92):
            native=runner._agent_next_vpp_checkpoint_hour(now,vpp_events=[event])
            self.assertEqual(next_checkpoint(runner,now,{'next_check_hour':None},event,1/6),native)
        self.assertEqual(next_checkpoint(runner,89,{'next_check_hour':89.5},event,1/6),89.5)
        self.assertEqual(next_checkpoint(runner,90,{'next_check_hour':93},event,1/6),91)
        self.assertEqual(next_checkpoint(runner,91,{'next_check_hour':93},event,1/6),93)
    def test_complete_trajectory_keeps_earlier_change_after_restoration(self):
        profile=normalize_answers(answers(),list(LOOKUP),LOOKUP);original,scenario=prepare(profile,'display')
        def row(a,b,c):return {'start_h':a,'end_h':b,'hvac_available':True,'cooling_setpoint':c,'actuators':{}}
        baseline={'controls':[row(88,90,25),row(90,91,25)],'decisions':[]}
        proposal={'controls':[row(88,90,27),row(90,91,25)],'decisions':[]}
        display=display_trajectory(original,baseline,proposal,scenario,{})
        ac=next(r for r in display['rows'] if r['device_id']=='ac')
        self.assertTrue(ac['changed']);self.assertIn('27℃',ac['proposal']);self.assertIn('25℃',ac['proposal'])
    def test_future_observation_and_nonmonotonic_history_rejected(self):
        profile=normalize_answers(answers(),list(LOOKUP),LOOKUP);original,scenario=prepare(profile,'ledger');now=72+scenario['decision_h']
        from evaluation_window import make_window
        scenario['evaluation_window']=make_window(original)  # historical custom-loop contract
        decision={'sim_h':now,'observed':{'end_h':now},'requested_plan':original['eb_ordinary_plan']}
        plan={'execution_mode':'eb_closed_loop','horizon_end_sim_h':scenario['evaluation_window']['end_sim_h'],'decisions':[decision]}
        self.assertEqual(validate(original,plan,scenario),plan)
        bad=deepcopy(plan);bad['decisions'][0]['observed']['end_h']=now+.5
        with self.assertRaises(ValueError):validate(original,bad,scenario)
        bad=deepcopy(plan);bad['decisions'].append(deepcopy(decision))
        with self.assertRaises(ValueError):validate(original,bad,scenario)

if __name__=='__main__':unittest.main()
