"""Regression protection against field-count bias and false novelty."""
import copy
import unittest
from collections import defaultdict
from .collection_assignment import assignment_frame,assign,goals
from .collection_selection import POLICY,view,tokens
from .collection_candidates import generate_day
from .collection_design import design
from .test_collection import fixture


class SelectionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.config=design({'joint_budget':32,'solver_node_limit':100})
        cls.rows=generate_day(fixture(),cls.config)['rows']

    def test_device_detail_budgets_do_not_grow_with_leaf_count(self):
        gs=goals(self.rows,[self.rows[0]['household_id']]);budgets=defaultdict(float)
        for g in gs:
            if g['budget']=='batch_device_details':budgets[g['tag'].split('.')[1]]+=g['weight']
        self.assertGreaterEqual(len(budgets),3)
        self.assertAlmostEqual(sum(budgets.values()),POLICY['batch_device_detail_budget'])
        for value in budgets.values():self.assertAlmostEqual(value,1/len(budgets))
        self.assertFalse(any('amplitude=ac.' in g['tag'] or '|amplitude=' in g['tag'] for g in gs))
        self.assertFalse(any(g['household'] is not None and g['tag'].startswith('tradeoff.root_services=') for g in gs))

    def test_descriptive_AC_fields_and_tags_cannot_create_rewards(self):
        changed=copy.deepcopy(self.rows)
        for r in changed:
            r['features']['amplitude_axes'] += ['ac.copied_axis_'+str(i)+'=large' for i in range(20)]
            r['tags'] += ['extra_description='+str(i) for i in range(20)]
            r['features']['unused_description']='arbitrary'
        self.assertEqual(goals(changed,[changed[0]['household_id']]),goals(self.rows,[self.rows[0]['household_id']]))
        a,_=assignment_frame(self.rows,self.config);b,_=assignment_frame(changed,self.config)
        self.assertEqual([r['id'] for r in a],[r['id'] for r in b])

    def test_duplicate_candidate_aliases_do_not_create_tie_tickets(self):
        clones=copy.deepcopy(self.rows)
        for r in clones:r['id']='alias-'+r['id']
        a,_=assignment_frame(self.rows,self.config);b,_=assignment_frame(self.rows+clones,self.config)
        self.assertEqual([(r['household_id'],r['date'],view(r),r['patches']) for r in a],
                         [(r['household_id'],r['date'],view(r),r['patches']) for r in b])

    def test_support_action_is_not_an_independent_device_witness(self):
        r=copy.deepcopy(next(r for r in self.rows if len(r['components'])>=2 and len({c['family'] for c in r['components']})>=2))
        family=r['components'][0]['family']
        for c in r['components']:
            if c['family']==family:c['event_relevance']['role']='constraint_support'
        self.assertNotIn(family,view(r)['families'])
        self.assertNotIn('root='+family,tokens(view(r)))
        self.assertIn('tradeoff.coordination=support_required',tokens(view(r)))

    def test_date_weekday_and_internal_ID_do_not_create_new_tradeoff(self):
        r=self.rows[0];z=copy.deepcopy(r);z.update(date='2025-07-27',id='another-id',near_duplicate_key='different-old-key')
        self.assertEqual(view(r),view(z))

    def test_EV_shortfall_and_service_boundary_are_distinct(self):
        r=copy.deepcopy(next(r for r in self.rows if r['features']['composition']=='ev'))
        z=copy.deepcopy(r);z['components'][0]['magnitude'].update(service_slack_min=-1,energy_shortfall_kWh=1)
        z['issues']=['CHARGE_EXCEEDS_ORIGINAL_CONNECTION']
        self.assertNotEqual(view(r)['signature'],view(z)['signature'])
        self.assertIn('tradeoff.constraint=service_or_window_stress',tokens(view(z)))

    def test_only_one_device_opportunity_allows_ten_repetitions(self):
        source=next(r for r in self.rows if r['features']['composition']=='ac')
        rows=[]
        for day in range(10):
            r=copy.deepcopy(source);r.update(date='2025-07-'+str(15+day),id='same-opportunity-'+str(day));rows.append(r)
        result=assign(rows,self.config)
        self.assertEqual(len(result['selected_ids']),10)
        self.assertEqual(result['family_exposure'][source['household_id']],{'ac':10})
        self.assertEqual(result['near_duplicate_excess'],9)
        self.assertFalse(result['category_proportions_prescribed'])

    def test_failed_proposals_remain_selection_eligible_and_outcomes_stay_unknown(self):
        r=copy.deepcopy(next(r for r in self.rows if r['issues']))
        active,_=assignment_frame([r],self.config)
        self.assertEqual(len(active),1)
        self.assertIsNone(active[0]['actual_outcomes']);self.assertIsNone(active[0]['human_acceptance'])
        self.assertFalse(any('admission=' in g['tag'] for g in goals([r],[r['household_id']])))

    def test_explicit_automatic_dry_need_does_not_invent_second_handling(self):
        from .generate import binding
        c=fixture();parent=c['needs'][0]
        dry=next(t for t in c['A']['tasks'] if t['kind']=='dryer')
        self.assertEqual(dry['need_id'],parent['need_id']+':dry')
        c['needs'].append({**parent,'need_id':dry['need_id'],'kind':'dryer'})
        c['reference']['binding']=binding(c)
        result=generate_day(c,self.config)
        self.assertTrue(result['A_input_unchanged'])
        self.assertFalse(any(o['need_id']==dry['need_id'] for o in c['A']['operations']))

    def test_explicit_thermostat_deadband_is_respected(self):
        from .model import control_issues
        c=fixture();plan=copy.deepcopy(c['A'])
        for x in plan['controls']:
            if x['kind']=='ac_setpoint':
                x.update(heating_setpoint_C=24,cooling_setpoint_C=25,heating_and_cooling_deadband_C=3)
        self.assertIn('THERMOSTAT_DEADBAND_TOO_NARROW',control_issues(c,plan))

    def test_same_AC_two_axes_are_not_two_devices_and_physical_identity_is_retained(self):
        r=copy.deepcopy(next(r for r in self.rows if r['features']['composition']=='ac'))
        second=copy.deepcopy(r['components'][0]);second['magnitude']['axis']='heating';r['components'].append(second)
        self.assertIn('tradeoff.root_services=single',tokens(view(r)))
        second['asset_id']='different_physical_AC'
        self.assertIn('tradeoff.root_services=two',tokens(view(r)))
        before=view(r)['signature'];second['asset_id']='another_physical_AC'
        self.assertNotEqual(before,view(r)['signature'])


if __name__=='__main__':unittest.main()
