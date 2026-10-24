import tempfile
import unittest
from pathlib import Path

from benchmark.ab_generation.common import read,save,sha
from .replay_relocation import semantic_fingerprints,verify_package_sources,retained_source_map


class RelocationEvidenceTests(unittest.TestCase):
    def test_unselected_candidates_and_unknowns_are_part_of_replay(self):
        with tempfile.TemporaryDirectory() as tmp:
            output=Path(tmp);collection=output/'AB/collection'
            save(collection/'MATERIALS.json.gz',[dict(id='selected',A={'value':1},B={'value':2})])
            save(collection/'SELECTION.json',{'selected_ids':['selected']})
            save(collection/'GENERATION.json',[dict(household_id='h',date='d',path='catalogues/day.json.gz')])
            path=collection/'catalogues/day.json.gz'
            cat=dict(rows=[{'id':'selected'},{'id':'unselected'}],unknown=['u'],engineering_diagnostics=['e'],telemetry={'wall_seconds':1})
            save(path,cat);base=semantic_fingerprints(output,'both')
            cat['telemetry']['wall_seconds']=999;save(path,cat)
            self.assertEqual(base,semantic_fingerprints(output,'both'))
            cat['unknown']=[];save(path,cat)
            changed=semantic_fingerprints(output,'both')
            self.assertEqual(base['selected_plans'],changed['selected_plans'])
            self.assertNotEqual(base['catalogue:h:d'],changed['catalogue:h:d'])
            cat['rows'].pop();save(path,cat)
            self.assertNotEqual(changed['catalogue:h:d'],semantic_fingerprints(output,'both')['catalogue:h:d'])

    def test_package_manifest_does_not_substitute_for_actual_source_hash(self):
        with tempfile.TemporaryDirectory() as tmp:
            p=Path(tmp);(p/'entry.py').write_text('original\n');save(p/'data/PUBLIC_REPLAY.json',{})
            save(p/'PACKAGE_SOURCES.json',dict(code={'entry.py':{'sha256':sha(p/'entry.py')}},data_manifest_sha256=sha(p/'data/PUBLIC_REPLAY.json')))
            self.assertEqual(sha(p/'PACKAGE_SOURCES.json'),verify_package_sources(p))
            (p/'entry.py').write_text('changed\n')
            with self.assertRaisesRegex(ValueError,'SOURCE_CHANGED'):verify_package_sources(p)

    def test_retained_sources_resolve_deleted_temporary_prefix_without_rewriting(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);package=root/'package';evidence=root/'first'
            save(package/'PACKAGE_SOURCES.json',{});save(package/'data/portrait.json',{'frozen':True})
            save(evidence/'context.json',{'A':'unchanged'})
            moved=root/'deleted moved directory';output=moved/'relocation-replay'
            pins={str(moved/'data/portrait.json'):sha(package/'data/portrait.json'),str(output/'context.json'):sha(evidence/'context.json')}
            pre=evidence/'AB/collection/PRE_GENERATION.json';save(pre,{'source_sha256':pins});before=sha(pre)
            mapped=retained_source_map(evidence,package,moved,output)
            self.assertTrue(mapped['passed']);self.assertEqual(2,len(mapped['records']))
            self.assertEqual(before,sha(pre));self.assertFalse(moved.exists())
            save(package/'data/portrait.json',{'frozen':'tampered'})
            self.assertFalse(retained_source_map(evidence,package,moved,output)['passed'])


if __name__=='__main__':unittest.main()
