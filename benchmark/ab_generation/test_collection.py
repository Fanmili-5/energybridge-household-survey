"""Collection invariants, analytical counterexamples and assignment scarcity."""
import copy
import tempfile
import unittest
from pathlib import Path
from .common import digest,read
from .collection import review
from .collection_assignment import assign,assignment_frame
from .collection_candidates import generate_day,presence_subsets
from .collection_design import DEFAULT,design,representatives,working_context
from .generate import binding
from .information import information_set
from .model import apply


def fixture():
    c=read(Path(__file__).parent/'examples/family.json')
    c['events']=[copy.deepcopy(DEFAULT['event'])]
    c['reference']['thermal']={}
    span=c['reference']['information_set']['A_reference_span_min']
    c['reference']['information_set']=information_set('offline_unexecuted_A_plan',c['decision_min'],span)
    c['reference']['binding']=binding(c)
    return c


class CollectionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.c=fixture();cls.config=design({'joint_budget':128})
        cls.result=generate_day(cls.c,cls.config)

    def test_input_unchanged_and_event_is_exact(self):
        self.assertEqual(self.c,fixture())
        self.assertEqual(self.c['events'][0]['start_min'],1080)
        self.assertTrue(self.result['A_input_unchanged'])
        bad=copy.deepcopy(self.config);bad['event']['start_min']=1090
        with self.assertRaisesRegex(ValueError,'FIXED_18_19'):design(bad)

    def test_outside_event_program_change_is_not_called_event_reduction(self):
        # Fixture's washer finishes before 18h. There are many changed requests
        # with zero event contribution: whole-profile L1 is not the opportunity.
        rows=[r for r in self.result['rows'] if r['independent_units']==1 and r['features']['composition']=='washer'
              and r['features']['device_count']=='1' and r['features']['event']=='zero']
        self.assertTrue(rows)
        self.assertTrue(all(abs(r['known_event_reduction_kWh'])<1e-9 for r in rows))

    def test_separate_handling_and_high_order_requests_are_real(self):
        rows=self.result['rows']
        self.assertTrue(any('retimed_handling' in r['features']['mechanisms'] and not r['issues'] for r in rows))
        self.assertTrue(any(int(r['features']['device_count'])>=3 for r in rows))
        self.assertTrue(any(int(r['features']['device_count'])>=3 and r['features']['intensity']=='mixed' for r in rows))
        self.assertTrue(any(r['issues'] and r['independent_units']>=2 for r in rows))

    def test_thermal_predictions_unknown_and_restore_A(self):
        rows=[r for r in self.result['rows'] if r['independent_units']==1 and r['features']['composition']=='ac']
        self.assertTrue(any(r['features']['mechanisms']==['precondition_and_relax'] for r in rows))
        for r in rows:
            self.assertEqual(r['features']['event'],'unknown')
            self.assertIsNone(r['actual_outcomes']);self.assertIsNone(r['human_acceptance'])
            b=apply(self.c['A'],r['patches'])
            state=lambda p,t:[{k:v for k,v in x.items() if k not in ('start_min','end_min')}
                for x in p['controls'] if x['asset_id']=='ac' and x['start_min']<=t<x['end_min']]
            self.assertEqual(state(b,1150),state(self.c['A'],1150))

    def test_missing_EV_charge_is_no_EV_opportunity(self):
        c=fixture();c['reference']['ev_charging_steps']=[];c['reference']['binding']=binding(c)
        r=generate_day(c,self.config)
        self.assertFalse(any(x['features']['composition']=='ev' for x in r['rows']))
        self.assertTrue(any(g['asset_id']=='ev' for g in r['gaps']))

    def test_weekend_EV_connection_is_not_shortened_to_case_horizon(self):
        c=fixture()
        for row in c['A']['controls']:
            if row['kind']=='ev_charge_window':row['end_min']=4800
        c['reference']['information_set']=information_set('offline_unexecuted_A_plan',c['decision_min'],[0,5000])
        c['reference']['binding']=binding(c)
        result=generate_day(c,self.config)
        ev=[r for r in result['rows'] if r['features']['composition']=='ev']
        self.assertTrue(ev)
        for r in ev:
            m=r['components'][0]['magnitude']
            self.assertGreater(m['service_slack_min'],m['observation_slack_min'])
            self.assertEqual(m['service_slack_min']-m['observation_slack_min'],4800-c['horizon_min'][1])
            self.assertNotIn('CHARGE_EXCEEDS_ORIGINAL_CONNECTION',r['issues'])
        self.assertTrue(any(any('NOT_DEPARTURE_FAILURE' in s for s in r['gate_issues']) for r in result['quarantined_requests']))

    def test_active_EV_full_future_energy_is_not_clipped_by_display_horizon(self):
        c=fixture();nid=c['reference']['ev_charging_steps'][0]['need_id']
        c['reference']['ev_charging_steps'].append({'need_id':nid,'start_min':2000,'end_min':2010,'grid_kWh':0.5})
        view=working_context(c)
        self.assertEqual(view['reference']['ev_charging_steps'],c['reference']['ev_charging_steps'])

    def test_authority_gate_and_full_review_detect_tampering(self):
        c=fixture();c['authority']['assets']['ac']['target_control_authorized']=False;c['reference']['binding']=binding(c)
        r=generate_day(c,self.config)
        self.assertFalse(any('ac' in x['changed_assets'] for x in r['rows']))
        row=next(x for x in self.result['rows'] if x['features']['composition']=='ev' and not x['issues'])
        check,_=review(self.c,row);self.assertTrue(check['passed'],check)
        bad=copy.deepcopy(row);bad['known_event_reduction_kWh']+=1
        self.assertIn('EVENT_PROFILE_INTEGRATION_MISMATCH',review(self.c,bad)[0]['failed_checks'])
        bad=copy.deepcopy(row);bad['issues']=['invented']
        self.assertIn('FULL_PLAN_ISSUE_MISMATCH',review(self.c,bad)[0]['failed_checks'])
        bad=copy.deepcopy(row);bad['features']['device_count']='5'
        self.assertIn('LITERAL_PLAN_FEATURE_MISMATCH',review(self.c,bad)[0]['failed_checks'])

    def test_tiny_domains_do_not_become_three_different_doses(self):
        self.assertEqual(representatives([10],self.config['quantiles']),[10])
        self.assertEqual(representatives([10,10],self.config['quantiles']),[10])

    def test_joint_budget_bounds_presence_construction_and_preserves_small_order(self):
        import itertools
        keys=list(range(30));seen=presence_subsets(keys,192)
        self.assertEqual(len(seen),192)
        self.assertEqual({len(x) for x in seen},set(range(2,31)))
        for count in range(1,9):
            groups={n:list(itertools.combinations(range(count),n)) for n in range(2,count+1)}
            expected=[]
            for i in range(max(map(len,groups.values()),default=0)):
                expected.extend(v[i] for _,v in sorted(groups.items(),reverse=True) if i<len(v))
            self.assertEqual(presence_subsets(list(range(count)),192),expected[:192])

    def test_immutable_other_household_operator_is_quarantined_not_sampled(self):
        c=fixture();c['authority']['immutable_operator_ids']=['p1'];c['reference']['binding']=binding(c)
        result=generate_day(c,self.config)
        self.assertTrue(result['quarantined_requests'])
        self.assertTrue(any('CONTEXT_OPERATOR_IMMUTABLE' in r['gate_issues'] for r in result['quarantined_requests']))
        for r in result['rows']:
            self.assertNotIn('CONTEXT_OPERATOR_IMMUTABLE',r['issues'])
            self.assertEqual({o['operation_id']:o for o in apply(c['A'],r['patches'])['operations']},
                             {o['operation_id']:o for o in c['A']['operations']})

    def test_assignment_keeps_scarcity_and_does_not_require_manufactured_changes(self):
        control=next(r for r in self.result['rows'] if r['features']['device_count']=='0')
        rows=[]
        for day in range(10):
            r=copy.deepcopy(control);r.update(date='2025-07-'+str(15+day),id=str(day))
            rows.append(r)
        config=design({'solver_node_limit':100})
        answer=assign(rows,config)
        self.assertEqual(len(answer['selected_ids']),10)
        self.assertGreater(answer['required_deficits'],0)
        self.assertEqual(answer['near_duplicate_excess'],9)
        self.assertFalse(answer['outcomes_used'])
        contaminated=copy.deepcopy(rows);contaminated[0]['human_acceptance']=True
        with self.assertRaisesRegex(ValueError,'OUTCOME_LEAKAGE'):assign(contaminated,config)

    def test_multi_label_frame_preserves_all_eligible_coverage(self):
        rows=self.result['rows'];active,report=assignment_frame(rows,self.config)
        self.assertTrue(report['coverage_universe_preserved'])
        self.assertEqual({t for r in rows for t in r['tags']},{t for r in active for t in r['tags']})


if __name__=='__main__':unittest.main()
