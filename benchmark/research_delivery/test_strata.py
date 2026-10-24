import csv
from pathlib import Path
import tempfile
import unittest

from benchmark.ab_generation.common import read,save,sha
from .strata import build


class StrataTests(unittest.TestCase):
    def test_original_failure_slot_and_one_device_two_batches_are_distinct(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);collection=root/'bank';collection.mkdir()
            profile=root/'portrait.json';save(profile,dict(role='B',joint_sampling={'devices':[]}))
            context=root/'context.json';save(context,{'devices':[dict(asset_id='w',kind='washer',types=['washer','dryer'])]})
            dates=['2025-01-01','2025-01-02']
            source=root/'inputs.json';save(source,dict(schema='eb.unified.inputs.v1',records=[dict(household_id='h',date=d,
                context_path=str(context),portrait_path=str(profile)) for d in dates]))
            save(collection/'PRE_GENERATION.json',dict(source_sha256={str(p):sha(p) for p in (source,profile,context)}))
            save(collection/'GENERATION.json',[dict(household_id='h',date=d,status='candidate_catalogue' if i==0 else 'baseline_engineering_error') for i,d in enumerate(dates)])
            proposal=dict(components=[dict(family='washer',relative_level='small_relative')]*2,independent_units=2,
                          changed_assets=['w'],issues=[],judgment_context=[])
            save(collection/'MATERIALS.json.gz',[dict(household_id='h',date=dates[0],proposal=proposal)])
            save(root/'CHECK_INPUT_OPPORTUNITY_COVERAGE.json.gz',[dict(household_id='h',date=d,mechanisms=[dict(
                family='washer',status='potential',candidate_witness_ids=['a'] if i==0 else [],selected_witness_ids=['a'] if i==0 else [])]) for i,d in enumerate(dates)])
            result=build(root/'out',{'CHECK':collection},root)['CHECK']
            self.assertEqual(2,result['date_slots']);self.assertEqual(1,result['cases']);self.assertEqual(1,result['unselected_slots'])
            self.assertEqual({2:1},result['joint_tasks']);self.assertEqual({1:1},result['changed_physical_devices'])
            with (root/'out/STRATA_CASES.csv').open() as file:rows=list(csv.DictReader(file))
            failed=next(r for r in rows if r['date']==dates[1])
            self.assertEqual('baseline_engineering_error',failed['generation_status'])
            for field in ('independent_tasks','changed_physical_devices','life_or_service_pressure','relative_action_positions'):
                self.assertEqual('',failed[field])
            with (root/'out/CLASS_DEVICE_COVERAGE.csv').open() as file:coverage=list(csv.DictReader(file))
            self.assertEqual('2',coverage[0]['potential_mechanisms']);self.assertEqual('1',coverage[0]['selected_direct_witnesses'])


if __name__=='__main__':unittest.main()
