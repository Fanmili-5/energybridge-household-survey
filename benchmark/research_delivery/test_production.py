import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from benchmark.ab_generation.common import save,sha,read
from .production import produce


class ProductionDateTests(unittest.TestCase):
    def test_dates_and_all_failure_slots_freeze_before_solving(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);worlds=root/'worlds.json';profiles=root/'portraits';profiles.mkdir()
            ids=['h1','h2'];save(worlds,{'households':[{'household_id':h} for h in ids]})
            specs=[dict(household_id=h,anchor='2025-01-01',end_exclusive='2025-01-16') for h in ids]
            batch=root/'INPUT.json';save(batch,{'worlds':{'path':'worlds.json','sha256':sha(worlds)},'households':specs})
            dates={h:['2025-01-%02d'%i for i in range(1,11)] for h in ids};save(root/'DATES.json',dates)
            for h in ids:save(profiles/(h+'.json'),{'household_id':h})
            out=root/'out'
            def unresolved(*args,**kwargs):
                frozen=read(out/'FROZEN_INPUTS.json');self.assertEqual(2,len(frozen['households']))
                self.assertEqual(dates['h1'],frozen['households'][0]['dates'])
                return {'status':'unknown','A':None}
            with patch('benchmark.research_delivery.production.compile_life',return_value={}),patch('benchmark.research_delivery.production.solve',side_effect=unresolved) as solver,patch('benchmark.research_delivery.production.build') as B:
                result=produce(batch,profiles,out,date_manifest=root/'DATES.json')
                self.assertEqual(2,solver.call_count);B.assert_not_called()
            failures=read(out/'BASELINE_FAILURE_SLOTS.json');self.assertEqual(20,len(failures))
            self.assertEqual('no_feasible_baselines;no_replacement',result['status'])


if __name__=='__main__':unittest.main()
