"""Collection invariants, analytical counterexamples and assignment scarcity."""
import copy
import tempfile
import unittest
from pathlib import Path
from .common import digest,read
from .collection import review
from .collection_assignment import assign,assignment_frame,goals
from .collection_candidates import generate_day,presence_subsets,_raw_thermal,_finish,_request
from .collection_design import DEFAULT,design,representatives,working_context
from .generate import binding
from .information import information_set
from .model import apply
from .collection_thermal import AC_CONTRACT


def fixture():
    c=read(Path(__file__).parent/'examples/family.json')
    c['events']=[copy.deepcopy(DEFAULT['event'])]
    c['reference']['thermal']={}
    span=c['reference']['information_set']['A_reference_span_min']
    c['reference']['information_set']=information_set('offline_unexecuted_A_plan',c['decision_min'],span)
    c['reference']['binding']=binding(c)
    c['reference']['ac_control_contract']=copy.deepcopy(AC_CONTRACT)
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
        self.assertFalse(rows)  # outside-only changes now have no event root
        self.assertTrue(self.result['relevance_diagnostics'])

    def test_separate_handling_and_high_order_requests_are_real(self):
        rows=self.result['rows']
        self.assertTrue(any('retimed_handling' in r['features']['mechanisms'] and not r['issues'] for r in rows))
        self.assertTrue(any(int(r['features']['device_count'])>=3 for r in rows))
        self.assertTrue(any(int(r['features']['device_count'])>=3 and len(r['features']['amplitude_axes'])>=3 for r in rows))
        self.assertTrue(all(r['features']['intensity']=='not_aggregated_use_amplitude_axes' for r in rows))
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
        for row in c['A']['operations']:
            if row['kind']=='EV_unplug':row.update(start_min=4800,end_min=4810)
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

    def test_EV_connection_endpoints_are_retained_when_both_outside_case(self):
        c=fixture()
        for r in c['A']['controls']:
            if r['kind']=='ev_charge_window':r.update(start_min=400,end_min=3000)
        for r in c['A']['operations']:
            if r['kind']=='EV_plug':r.update(start_min=390,end_min=400)
            if r['kind']=='EV_unplug':r.update(start_min=3000,end_min=3010)
        c['reference']['information_set']=information_set('offline_unexecuted_A_plan',c['decision_min'],[0,3200])
        c['reference']['binding']=binding(c)
        view=working_context(c)
        self.assertEqual(len([o for o in view['A']['operations'] if o['kind'].startswith('EV_')]),2)
        self.assertTrue(generate_day(c,self.config)['A_input_unchanged'])

    def test_unmodified_censored_EV_calendar_boundary_is_not_a_B_failure(self):
        c=fixture();r=copy.deepcopy(next(r for r in c['A']['controls'] if r['kind']=='ev_charge_window'))
        r.update(need_id='censored_source_start',start_min=0,end_min=100)
        c['A']['controls'].append(r);c['reference']['binding']=binding(c)
        result=generate_day(c,self.config)
        selected=next(r for r in result['rows'] if r['features']['composition']=='ev' and not r['issues'])
        self.assertTrue(review(c,selected)[0]['passed'])

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
        control=self.result['control_record']
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

    def test_precedence_is_constructed_for_washer_combo_dishes_and_joint_requests(self):
        engineering=self.result['engineering_diagnostics']
        self.assertTrue(any('RETRIEVAL_BEFORE_PROGRAM_END' in r['engineering_issues'] for r in engineering))
        self.assertTrue(all(not r['repaired'] and not r['replacement_generated'] for r in engineering))
        self.assertTrue(self.result['no_retries_or_replacements'])
        self.assertFalse(any(r['features']['device_count']=='0' for r in self.result['rows']))
        for row in self.result['rows']:
            self.assertFalse(row['engineering_issues'])
            b=apply(self.c['A'],row['patches'])
            for need in self.c['needs']:
                nid=need['need_id'];tasks=[t for t in b['tasks'] if t['need_id'] in (nid,nid+':dry')]
                load=next(o for o in b['operations'] if o['need_id']==nid and o['kind']=='load')
                unload=next(o for o in b['operations'] if o['need_id']==nid and o['kind']=='unload')
                self.assertLessEqual(load['end_min'],min(t['start_min'] for t in tasks))
                self.assertGreaterEqual(unload['start_min'],max(t['end_min'] for t in tasks))
            self.assertTrue(review(self.c,row)[0]['passed'])

    def test_service_stress_zero_opposing_and_EV_shortfall_are_not_removed(self):
        rows=self.result['rows']
        self.assertTrue(any('CHARGE_EXCEEDS_ORIGINAL_CONNECTION' in r['issues'] for r in rows))
        # Genuine zero-net event roots are tested separately. This fixture's
        # former zeroes were wholly outside the event and now stay in the ledger.
        self.assertTrue(self.result['relevance_diagnostics_retained'])
        self.assertTrue(any(r['features']['thermal_direction']=='opposing' for r in rows))
        self.assertTrue(any(set(r['issues']) & {'OPERATOR_UNAVAILABLE','OPERATOR_DOUBLE_BOOKED','SERVICE_DEADLINE_MISSED'} for r in rows))
        for r in rows:self.assertIsNone(r['actual_outcomes'])

    def test_timer_capability_is_enforced_before_ordinary_admission(self):
        c=fixture();c['needs'][1]['timer_allowed']=False
        for t in c['A']['tasks']:
            if t['need_id']=='dishes':t.update(start_min=1120,end_min=1210)
        c['reference']['binding']=binding(c)
        result=generate_day(c,self.config)
        self.assertTrue(any('TIMER_NOT_AVAILABLE' in r['engineering_issues'] for r in result['engineering_diagnostics']))
        for row in result['rows']:
            b=apply(c['A'],row['patches'])
            self.assertEqual(next(t['start_min'] for t in b['tasks'] if t['need_id']=='dishes'),
                next(o['end_min'] for o in b['operations'] if o['need_id']=='dishes' and o['kind']=='load'))

    def test_no_admission_or_control_coverage_reward_and_no_prescribed_proportions(self):
        targets=goals(self.result['rows'],[self.c['household_id']])
        self.assertFalse(any('admission=' in t['tag'] or t['tag'] in ('composition=control','mechanism=control','device_count=0') for t in targets))
        bad=copy.deepcopy(self.result['rows'][0]);bad['engineering_issues']=['RETRIEVAL_BEFORE_PROGRAM_END']
        with self.assertRaisesRegex(ValueError,'ENGINEERING_DIAGNOSTIC'):assignment_frame([bad],self.config)
        with self.assertRaisesRegex(ValueError,'CONTROL_NOT_ELIGIBLE'):
            assignment_frame(self.result['rows']+[self.result['control_record']],self.config)

    def test_no_opportunity_keeps_fallback_without_manufacturing_changes(self):
        c=fixture()
        for a in c['authority']['assets'].values():a['target_control_authorized']=False
        c['reference']['binding']=binding(c)
        result=generate_day(c,self.config)
        self.assertEqual(len(result['rows']),1)
        self.assertEqual(result['rows'][0]['features']['device_count'],'0')
        self.assertIn('not_global_no_opportunity_proof',result['rows'][0]['fallback_reason'])

    def test_thermal_joint_deadband_and_tank_hardware_are_engineering_diagnostics(self):
        c=fixture()
        for r in c['A']['controls']:
            if r['kind']=='ac_setpoint':r['heating_setpoint_C']=25
        c['reference']['binding']=binding(c)
        cfg=design({'ac_axes':['cooling','heating']});ac=next(d for d in c['devices'] if d['asset_id']=='ac')
        children=[]
        for axis in ['cooling','heating']:
            raw=next(r for r in _raw_thermal(c,ac,cfg) if r['magnitude']['axis']==axis
                     and r['magnitude']['service_delta_C']==0.5 and r['magnitude']['direction']=='opposing'
                     and r['magnitude']['duration_min']==20 and r['mechanism']=='event_setpoint')
            item=_finish(c,raw,cfg);self.assertNotIn('engineering_diagnostic',item)
            item['relative_level']='low';children.append(item)
        combined=_request(c,children,cfg)
        self.assertTrue(combined['engineering_diagnostic'])
        self.assertIn('THERMOSTAT_DEADBAND_INVERTED',combined['engineering_issues'])
        result=generate_day(fixture(),design({'tank_delta_C':[1,3,7]}))
        self.assertTrue(any('SETPOINT_OUTSIDE_HARDWARE_RANGE' in r['engineering_issues'] for r in result['engineering_diagnostics']))

    def test_malformed_A_is_not_mislabelled_as_a_B_failure(self):
        c=fixture();c['A']['operations'][1].update(start_min=800,end_min=810)
        c['reference']['binding']=binding(c)
        with self.assertRaisesRegex(ValueError,'BASELINE_ENGINEERING_ERROR;A_NOT_MODIFIED'):
            generate_day(c,self.config)

    def test_joint_batches_cannot_use_one_machine_simultaneously(self):
        c=fixture();second={**c['needs'][0],'need_id':'wash2','release_min':900,'deadline_min':1400}
        c['needs'].append(second)
        c['A']['tasks'].append({'task_id':'laundry2','need_id':'wash2','asset_id':'washer','kind':'washer','start_min':1060,'end_min':1120})
        for kind,a,z in [('load',1050,1060),('unload',1130,1140)]:
            c['A']['operations'].append({'operation_id':kind+'2','need_id':'wash2','asset_id':'washer','kind':kind,
                'operator_id':'p1','room_id':'utility','start_min':a,'end_min':z})
        c['reference']['binding']=binding(c);result=generate_day(c,self.config)
        self.assertTrue(any(set(r['engineering_issues']) & {'ASSET_HOLD_CONFLICT','SIMULTANEOUS_PROGRAMS_ON_ONE_ASSET'}
                            for r in result['engineering_diagnostics']))
        for row in result['rows']:
            tasks=apply(c['A'],row['patches'])['tasks']
            for i,t in enumerate(tasks):
                for u in tasks[i+1:]:
                    if t['asset_id']==u['asset_id']:
                        self.assertFalse(max(t['start_min'],u['start_min'])<min(t['end_min'],u['end_min']))

    def test_separate_dependent_dryer_waits_for_parent_retrieval(self):
        c=fixture()
        c['devices'].append({'asset_id':'dryer','types':['dryer'],'room_id':'utility','parameters':{'dryer':{'power_kw':2.0}}})
        c['authority']['assets']['dryer']=copy.deepcopy(c['authority']['assets']['washer'])
        c['needs'].append({**c['needs'][0],'need_id':'dry_need','asset_id':'dryer','kind':'dryer','release_min':780,'deadline_min':1400})
        for t in c['A']['tasks']:
            if t['task_id']=='dry':t.update(asset_id='dryer',need_id='dry_need',depends_on_need_id='wash',start_min=1040,end_min=1130)
        for kind,a,z in [('load',1030,1040),('unload',1140,1150)]:
            c['A']['operations'].append({'operation_id':'dryer_'+kind,'need_id':'dry_need','asset_id':'dryer','kind':kind,
                'operator_id':'p1','room_id':'utility','start_min':a,'end_min':z})
        c['reference']['binding']=binding(c);result=generate_day(c,self.config)
        self.assertTrue(any('dryer' in r['changed_assets'] for r in result['rows']))
        for row in result['rows']:
            b=apply(c['A'],row['patches'])
            load=next(o for o in b['operations'] if o['operation_id']=='dryer_load')
            parent=next(o for o in b['operations'] if o['operation_id']=='unload')
            self.assertGreaterEqual(load['start_min'],parent['end_min'])
            self.assertGreaterEqual(next(t['start_min'] for t in b['tasks'] if t['task_id']=='dry'),load['end_min'])

    def test_multi_label_frame_preserves_all_eligible_coverage(self):
        from .collection_selection import tokens,view
        rows=self.result['rows'];active,report=assignment_frame(rows,self.config)
        self.assertTrue(report['coverage_universe_preserved'])
        self.assertEqual({t for r in rows for t in tokens(view(r))},{t for r in active for t in tokens(view(r))})


if __name__=='__main__':unittest.main()
