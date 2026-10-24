import copy
import unittest
from collections import Counter
from unittest.mock import patch

from benchmark.ab_generation.unified import selection,semantics
from .selection_protocol import selection_accounting,signature_provenance,view_scope
from .test_semantic_links import fixture


class SelectionProtocolTests(unittest.TestCase):
    def test_duplicate_ids_cannot_pass_day_accounting(self):
        rows=[dict(id='a',household_id='h',date='d1'),dict(id='b',household_id='h',date='d2')]
        expected=Counter({('h','d1'):1,('h','d2'):1})
        self.assertTrue(selection_accounting(rows,['a','b'],expected)['passed'])
        bad=selection_accounting(rows,['a','b','b','missing'],expected)
        self.assertFalse(bad['passed']);self.assertEqual(['b'],bad['duplicate_ids'])
        self.assertEqual(['missing'],bad['unknown_ids']);self.assertEqual(['a','b'],bad['metric_ids'])
        self.assertEqual([['h','d2']],bad['multiple_cases_per_date'])

    def test_frozen_v2_is_explicit_even_when_runtime_supports_new_signature(self):
        original=selection.judgment_signature
        def legacy(*args):return 'legacy-signature'
        with patch.object(semantics,'legacy_judgment_signature',legacy,create=True):
            with view_scope('frozen_v2'):
                self.assertEqual('legacy-signature',selection.concepts(fixture())['signature'])
        self.assertIs(original,selection.judgment_signature)
        self.assertEqual('eb.plan_semantics.v2',signature_provenance('frozen_v2',[]))

    def test_new_mode_cannot_silently_fall_back_to_unmarked_rows(self):
        if not hasattr(semantics,'LINK_VERSION'):
            with self.assertRaisesRegex(ValueError,'NOT_INSTALLED'):
                signature_provenance('linked_v3',[fixture()])
            return
        a=fixture()
        with self.assertRaisesRegex(ValueError,'EXPLICITLY_BOUND'):
            signature_provenance('linked_v3',[a])
        for c,j in zip(a['components'],a['judgment_context']):
            j.update(component_id=c['id'],service_need_id=c.get('service_need_id'))
        a['judgment_context_version']=semantics.LINK_VERSION
        self.assertEqual(semantics.LINKED_SIGNATURE_VERSION,signature_provenance('linked_v3',[a]))
        b=copy.deepcopy(a)
        for j in b['judgment_context']:
            j['machine_time_tension'],j['handling_tension']=j['handling_tension'],j['machine_time_tension']
        with view_scope('linked_v3'):
            self.assertNotEqual(selection.concepts(a)['signature'],selection.concepts(b)['signature'])
        with view_scope('frozen_v2'):
            self.assertEqual(selection.concepts(a)['signature'],selection.concepts(b)['signature'])


if __name__=='__main__':unittest.main()
