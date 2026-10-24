import tempfile
import unittest
from pathlib import Path

from benchmark.ab_generation.common import save
from .acceptance import date_accounting,record_sources


class AcceptanceIdentityTests(unittest.TestCase):
    def test_same_count_cannot_hide_repeated_or_wrong_day(self):
        sources={('h','d1'):'one',('h','d2'):'two'}
        rows=[dict(household_id='h',date=d) for d in ('d1','d2')]
        self.assertTrue(date_accounting(sources,rows)['passed'])
        bad=date_accounting(sources,[rows[0],rows[0]])
        self.assertFalse(bad['passed']);self.assertEqual([['h','d2']],bad['missing'])
        self.assertEqual([['h','d1']],bad['duplicate_dates'])
        bad=date_accounting(sources,[rows[0],dict(household_id='h',date='other')])
        self.assertFalse(bad['passed']);self.assertEqual([['h','other']],bad['unexpected'])

    def test_duplicate_frozen_input_is_not_silently_dict_compressed(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder=Path(tmp);source=folder/'inputs.json'
            row=dict(household_id='h',date='d',context_path='context.json.gz')
            save(source,dict(schema='eb.unified.inputs.v1',records=[row,row]))
            save(folder/'PRE_GENERATION.json',dict(source_sha256={str(source):'not_used_in_this_identity_check'}))
            with self.assertRaisesRegex(ValueError,'DUPLICATE_INPUT_DATE'):
                record_sources(folder)


if __name__=='__main__':unittest.main()
