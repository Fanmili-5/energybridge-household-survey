import copy
import unittest
from unittest.mock import patch
from benchmark.ab_generation.unified import selection
from .semantic_links import signature,relation_nodes,audit_rows


def fixture():
    row=dict(id='probe',household_id='h',date='2025-01-01',components=[],judgment_context=[],
        independent_units=2,known_event_reduction_kWh=0,features={'manual':'multiple'},
        consent_status='proposal',issues=[],patches=[])
    for i,family in enumerate(('washer','dishwasher')):
        row['components'].append(dict(id='c'+str(i),asset_id=family,family=family,mechanism='retimed_handling',
            relative_level='medium_relative',magnitude=dict(machine_shift_min=40,signed_machine_shift_min=40,manual_total_shift_min=20),
            event_relevance={'role':'direct_event_request'}))
        row['judgment_context'].append(dict(asset_id=family,soft_preference_tension=True,
            machine_time_tension=i==0,handling_tension=i!=0,authorization_preference='confirm',
            reference_member='m',actual_proposed_operator_ids=['m'],confirmation_holder='m',
            member_preferences={'m':{'routine_sensitive':True,'handling_change_sensitive':False,'preferred_shift_limit_min':30}}))
    return row


class LinkedSemanticTests(unittest.TestCase):
    def view(self,row):
        with patch.object(selection,'judgment_signature',signature):return selection.concepts(row)

    def test_device_bound_tension_swap_is_retained(self):
        a=fixture();b=copy.deepcopy(a)
        for j in b['judgment_context']:j['machine_time_tension'],j['handling_tension']=j['handling_tension'],j['machine_time_tension']
        self.assertEqual(selection.concepts(a)['signature'],selection.concepts(b)['signature'])
        self.assertNotEqual(self.view(a)['signature'],self.view(b)['signature'])
        self.assertEqual(self.view(a)['tokens'],self.view(b)['tokens'])

    def test_names_ids_dates_and_extra_descriptions_do_not_change_signature(self):
        a=fixture();b=copy.deepcopy(a);b.update(household_id='renamed',date='2035-01-01',id='opaque')
        for c,j in zip(b['components'],b['judgment_context']):
            c['asset_id']='new-'+c['asset_id'];c['id']='new-'+c['id'];c['magnitude']['extra_description']=['ignored']*100;c['branch']='arbitrary-construction-label'
            j['asset_id']='new-'+j['asset_id'];j['member_preferences']={'renamed-person':j['member_preferences']['m']}
            j.update(reference_member='renamed-person',actual_proposed_operator_ids=['renamed-person'],confirmation_holder='renamed-person')
        self.assertEqual(self.view(a)['signature'],self.view(b)['signature'])
        b['components'].reverse();b['judgment_context'].reverse()
        self.assertEqual(self.view(a)['signature'],self.view(b)['signature'])

    def test_wrong_pairing_is_detected_not_silently_used(self):
        a=fixture();a['judgment_context'].reverse()
        with self.assertRaisesRegex(ValueError,'ORDER_MISMATCH'):self.view(a)

    def test_same_device_batches_use_own_shift_for_member_scope(self):
        a=fixture()
        for c,j in zip(a['components'],a['judgment_context']):c['asset_id']=j['asset_id']='shared-washer';c['family']='washer'
        a['components'][0]['magnitude']['machine_shift_min']=20
        nodes=relation_nodes(a)
        self.assertNotEqual(nodes[0]['member_and_permission_relations'],nodes[1]['member_and_permission_relations'])
        # Fix all other judgment fields, so the remaining difference is solely
        # the component-specific 20-versus-40 minute relation to the 30 bound.
        a['judgment_context'][1]=copy.deepcopy(a['judgment_context'][0])
        nodes=relation_nodes(a)
        self.assertNotEqual(nodes[0]['member_and_permission_relations'],nodes[1]['member_and_permission_relations'])

    def test_audit_reports_current_alias_split_without_modifying_rows(self):
        a=fixture();b=copy.deepcopy(a);b['id']='other'
        for j in b['judgment_context']:j['machine_time_tension'],j['handling_tension']=j['handling_tension'],j['machine_time_tension']
        rows=[a,b];before=copy.deepcopy(rows);r=audit_rows(rows)
        self.assertEqual(1,r['pools_split']);self.assertEqual(2,r['candidate_rows_in_split_pools'])
        self.assertTrue(r['features_weights_and_literal_actions_unchanged']);self.assertEqual(before,rows)


if __name__=='__main__':unittest.main()
