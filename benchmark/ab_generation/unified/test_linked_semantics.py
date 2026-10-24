import copy
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from ..common import read,digest
from . import semantics
from .selection import concepts
from .contract import config
from .candidates import generate_day
from .pipeline import fresh_life
from benchmark.research_delivery.test_semantic_links import fixture
from benchmark.research_delivery.semantic_links import relation_nodes


def linked(row):
    row=copy.deepcopy(row)
    row['judgment_context_version']=semantics.LINK_VERSION
    for c,j in zip(row['components'],row['judgment_context']):
        j.update(component_id=c['id'],service_need_id=c.get('service_need_id'))
    return row


class LinkedSemanticsTests(unittest.TestCase):
    def test_legacy_rows_keep_legacy_signature(self):
        row=fixture()
        self.assertEqual(semantics.legacy_judgment_signature(row,{},{}),
                         semantics.judgment_signature(row,{},{}))

    def test_device_tension_swap_changes_only_semantic_repeat_key(self):
        first=linked(fixture());second=copy.deepcopy(first)
        for j in second['judgment_context']:
            j['machine_time_tension'],j['handling_tension']=j['handling_tension'],j['machine_time_tension']
        a,b=concepts(first),concepts(second)
        self.assertNotEqual(a['signature'],b['signature'])
        for key in ('tokens','families','composition','action'):
            self.assertEqual(a[key],b[key])

    def test_explicit_links_allow_independent_array_order(self):
        first=linked(fixture());second=copy.deepcopy(first)
        second['judgment_context'].reverse()
        self.assertEqual(concepts(first),concepts(second))
        second['components'].reverse()
        self.assertEqual(concepts(first),concepts(second))

    def test_invalid_explicit_links_fail_closed(self):
        for kind in ('missing','duplicate','wrong_asset','wrong_service','unknown_version'):
            row=linked(fixture())
            if kind=='missing':row['judgment_context'][0].pop('component_id')
            if kind=='duplicate':row['judgment_context'][1]['component_id']=row['components'][0]['id']
            if kind=='wrong_asset':row['judgment_context'][0]['asset_id']='unrelated'
            if kind=='wrong_service':row['judgment_context'][0]['service_need_id']='other_batch'
            if kind=='unknown_version':row['judgment_context_version']='unknown'
            with self.subTest(kind=kind),self.assertRaises(ValueError):concepts(row)

    def test_same_asset_batches_use_own_member_machine_scope(self):
        row=fixture()
        for i,(c,j) in enumerate(zip(row['components'],row['judgment_context'])):
            c.update(asset_id='washer',family='washer',service_need_id='batch'+str(i))
            j['asset_id']='washer'
        row['components'][0]['magnitude']['machine_shift_min']=20
        row['judgment_context'][1]=copy.deepcopy(row['judgment_context'][0])
        row=linked(row)
        nodes=semantics.linked_relation_nodes(row)
        self.assertNotEqual(nodes[0]['member_and_permission_relations'],nodes[1]['member_and_permission_relations'])
        row['judgment_context'][0]['service_need_id']='batch1'
        with self.assertRaisesRegex(ValueError,'SERVICE_MISMATCH'):concepts(row)

    def test_opaque_renaming_and_description_fields_do_not_gain_votes(self):
        first=linked(fixture());second=copy.deepcopy(first)
        second.update(id='another-id',household_id='another-household',date='2030-01-01')
        for c,j in zip(second['components'],second['judgment_context']):
            c['asset_id']='new-'+c['asset_id'];c['id']='new-'+c['id']
            j.update(asset_id=c['asset_id'],component_id=c['id'])
            j['member_preferences']={'renamed':j['member_preferences']['m']}
            j.update(reference_member='renamed',actual_proposed_operator_ids=['renamed'],confirmation_holder='renamed')
            c['magnitude']['irrelevant_description']=['extra']*100
        self.assertEqual(concepts(first),concepts(second))

    def test_candidate_relation_mapping_is_preserved(self):
        row=linked(fixture())
        self.assertEqual(relation_nodes(row),semantics.linked_relation_nodes(row))

    def test_new_request_version_preserves_fixture_commands_and_adds_links(self):
        c=read(Path(__file__).parents[1]/'examples/control.json')
        c['reference']['thermal']={}
        c['reference']['information_set']['mode']='offline_unexecuted_A_plan'
        cfg=dict(rows_per_unit=2,queries_per_row=2)
        before=digest(c)
        old=generate_day(c,{**cfg,'method_revision':'delivery_v2_8'})
        new=generate_day(c,{**cfg,'method_revision':'delivery_v2_9'})
        current=generate_day(c,{**cfg,'method_revision':'delivery_v2_10','selection_joint_order':'exact_witnessed_v1'})
        self.assertEqual(before,digest(c))
        self.assertTrue(old['rows'])
        # Fresh-generation IDs bind the complete configuration, including its
        # revision. Compare commands; do not pretend a new revision has old IDs.
        a={r['working_B_sha256']:r for r in old['rows']}
        b={r['working_B_sha256']:r for r in new['rows']}
        self.assertEqual(set(a),set(b))
        self.assertEqual(set(b),{r['working_B_sha256'] for r in current['rows']})
        for r in current['rows']:
            self.assertEqual(semantics.LINK_VERSION,r['judgment_context_version'])
            semantics.linked_contexts(r)
        for key,first in a.items():
            second=b[key]
            semantics.linked_contexts(second)
            self.assertEqual(semantics.LINK_VERSION,second['judgment_context_version'])
            stripped=copy.deepcopy(second);stripped.pop('judgment_context_version')
            stripped['id']=first['id']
            for j in stripped['judgment_context']:
                j.pop('component_id');j.pop('service_need_id')
            self.assertEqual(first,stripped)

    def test_standalone_A_forwards_explicit_and_default_target_mode(self):
        for supplied,expected in (({},'frozen_v3'),({'A_target_context_mode':'life_conditional_v1'},'life_conditional_v1')):
            with tempfile.TemporaryDirectory() as tmp:
                problem={'legacy_comparator':{}}
                with patch('benchmark.ab_generation.unified.a_solver.compile_life',return_value=problem), \
                     patch('benchmark.ab_generation.unified.a_solver.solve',return_value={'status':'infeasible'}) as solver:
                    fresh_life({}, {}, {},Path(tmp)/'A',config(supplied))
                self.assertEqual(expected,solver.call_args.kwargs['target_mode'])


if __name__=='__main__':unittest.main()
