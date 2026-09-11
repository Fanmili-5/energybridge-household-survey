"""Cross-midnight comparison must retain energy and original-day task identity."""
from contextlib import redirect_stdout
from io import StringIO
from copy import deepcopy
from pathlib import Path
import tempfile
import unittest
from common import normalize_answers
from paired_contract import LOOKUP,prepare,sanitize_profile
from verify_paired_physics import answers
from closed_loop import simulate_live,display_trajectory
from paired_ep import pair_metrics
from evaluation_window import clock

class ServiceOutcomeTests(unittest.TestCase):
    def test_overnight_shift_moves_energy_but_does_not_erase_it(self):
        raw=answers();raw.update(B05=['washer'],H_washer='late',E_washer='8',D_washer='2',T_washer='3.0')
        profile=sanitize_profile(normalize_answers(raw,list(LOOKUP),LOOKUP));original,scenario=prepare(profile,'overnight-test')
        self.assertEqual(scenario['evaluation_window']['end_sim_h'],98)
        request={'profile':profile,'original_plan':original,'scenario':scenario}
        def planner(loop,now,observed,history,reasons):
            plan=deepcopy(original['eb_ordinary_plan']);plan['appliances']['washer_start_h']=23
            return plan,'确定性工程测试，将任务推迟一小时。'
        with tempfile.TemporaryDirectory() as directory,redirect_stdout(StringIO()):
            baseline=simulate_live(Path(directory)/'baseline',request)
            proposal=simulate_live(Path(directory)/'proposal',request,planner)
        metrics=pair_metrics(baseline,proposal,scenario)
        self.assertEqual(len(proposal['controls']),588)
        self.assertEqual(baseline['task_outcomes']['washer']['completed_sim_h'],97)
        self.assertEqual(proposal['task_outcomes']['washer']['completed_sim_h'],98)
        self.assertTrue(proposal['task_outcomes']['washer']['completed'])
        self.assertAlmostEqual(metrics['original']['comparison_kwh'],metrics['proposal']['comparison_kwh'],places=6)
        self.assertAlmostEqual(metrics['original']['daily_kwh']-metrics['proposal']['daily_kwh'],1.5,places=6)
        self.assertAlmostEqual(metrics['proposal']['next_day_kwh']-metrics['original']['next_day_kwh'],1.5,places=6)
        display=display_trajectory(original,baseline,proposal,scenario,metrics)
        self.assertIn('次日02:00',display['notice'])
        self.assertIn('次日02:00',display['service_rows'][0]['proposal'])
        self.assertTrue(any('比较期总费用'==m['label'] for m in display['comparison_metrics']))

    def test_day_aware_labels(self):
        self.assertEqual(clock(24),'24:00');self.assertEqual(clock(26),'次日02:00');self.assertEqual(clock(8),'08:00')

if __name__=='__main__':unittest.main()
