from pathlib import Path
import tempfile
import unittest
from common import UPSTREAM, file_hash
from native_assets import bind_native_appliances, idf_objects
from native_support import upstream

class NativeAssetTests(unittest.TestCase):
    def test_binding_is_idempotent_and_preserves_original(self):
        source=UPSTREAM/'experiments/models/family_home/family_simple_3day.idf'
        before=file_hash(source)
        with tempfile.TemporaryDirectory() as tmp:
            target=Path(tmp)/'run.idf';target.write_bytes(source.read_bytes())
            result=bind_native_appliances(target,upstream()[0]._APPL_DESIGN_W)
            self.assertEqual(result['added_objects'],8)
            body=target.read_text()
            again=bind_native_appliances(target,upstream()[0]._APPL_DESIGN_W)
            self.assertEqual(again['added_objects'],0);self.assertEqual(body,target.read_text())
        self.assertEqual(file_hash(source),before)
    def test_conflict_does_not_double_count(self):
        source=UPSTREAM/'experiments/models/family_home/family_simple_3day.idf'
        with tempfile.TemporaryDirectory() as tmp:
            target=Path(tmp)/'run.idf';target.write_text(source.read_text()+'\nSchedule:Constant,ClothesWasher_Power_Frac,,1;\n')
            with self.assertRaises(ValueError):bind_native_appliances(target,upstream()[0]._APPL_DESIGN_W)

if __name__=='__main__':unittest.main()
