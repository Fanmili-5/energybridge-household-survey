import copy
import itertools
import unittest
from pathlib import Path
from ..common import read,digest
from ..model import apply
from .contract import config,dates,stream
from .ipog import generate
from .a_solver import compile_life,solve,dated_targets
from .candidates import generate_day,prepare,request,legacy_config,program_grammar,ev_grammar,heating_precondition,heating_description,engineering_issues,issues
from .selection import assign,concepts
from .independent import audit
from .evaluation import grouped_split

ROOT=Path(__file__).resolve().parents[1]


class InteractionTests(unittest.TestCase):
    def test_oracle_and_denominator_against_exhaustive(self):
        domains=[[0,1]]*4
        allrows=[r for r in itertools.product(*domains) if not(r[0] and r[1])]
        def oracle(partial):
            rows=[r for r in allrows if all(r[i]==v for i,v in partial.items())]
            return ('feasible',list(rows[0]),'independent_enumerator') if rows else ('infeasible',None,'enumerator_proof')
        result=generate(domains,oracle,triples=[(0,2,3)])
        self.assertTrue(result['complete'])
        for cell in result['coverage']:
            exists=any(all(r[i]==v for i,v in cell['target']) for r in allrows)
            self.assertEqual(exists,cell['witness_row'] is not None)
        self.assertTrue(any(sum(r)>=3 for r in result['rows']))
        self.assertEqual(result,generate(domains,oracle,triples=[(0,2,3)]))
    def test_budget_is_unknown_not_impossible(self):
        r=generate([[0,1]]*4,lambda p:('unknown',None,'budget'),query_budget=2)
        self.assertFalse(r['complete']);self.assertFalse(any(x['status']=='infeasible' for x in r['coverage']))
        self.assertEqual(24,len(r['coverage']))
    def test_dates_are_not_conditioned_on_B(self):
        available=['2025-01-%02d'%i for i in range(1,32)]
        self.assertEqual(10,len(dates(available,0,'new-house')))
        self.assertEqual(dates(available,0,'new-house'),dates(available,0,'new-house'))
        self.assertNotEqual(dates(available,0,'new-house'),dates(available,1,'new-house'))
    def test_config_target_optional_and_time_fixed(self):
        self.assertIsNone(config()['event']['target_kw'])
        with self.assertRaises(ValueError):config({'event':{**config()['event'],'start_min':1070}})
    def test_config_file_matches_executable_defaults(self):
        self.assertEqual(config(),read(Path(__file__).parent/'DEFAULT_CONFIG.json'))


class ATests(unittest.TestCase):
    def setUp(self):
        self.spec=copy.deepcopy(read(ROOT/'examples/life/life_batch.json')['households'][0])
        self.world=copy.deepcopy(read(ROOT/'examples/life/resource_worlds.json')['households'][0])
        self.spec['end_exclusive']='2025-07-03'
    def test_joint_A_replays_and_has_complete_services(self):
        problem=compile_life(self.spec,self.world);before=digest(problem)
        a=solve(problem,deterministic_time=2);b=solve(problem,deterministic_time=2)
        self.assertEqual('feasible',a['status']);self.assertEqual(a,b);self.assertEqual(before,digest(problem))
        self.assertEqual(len(problem['jobs']),len(a['A']['tasks']))
        bookings=[]
        for o in a['A']['operations']:bookings.extend((o['operator_id'],t) for t in range(o['start_min'],o['end_min'],10))
        self.assertEqual(len(bookings),len(set(bookings)))
    def test_cross_day_target_is_not_clock_folded(self):
        profile={'joint_sampling':{'devices':[dict(asset_id='washer',time_preference={'per_service':[dict(source_date='2025-07-01',need_id='2025-07-01:laundry:0',preferred_start_min=1500)]})]}}
        self.assertEqual(1500,dated_targets(profile,'2025-07-01')[('washer','2025-07-01','2025-07-01:laundry:0')])
    def test_complete_program_can_span_midnight_in_all_day_window(self):
        p=compile_life(self.spec,self.world);j=copy.deepcopy(next(j for j in p['jobs'] if j['kind']=='washer'))
        j.update(release_min=1380,deadline_min=1800,preferred_start_min=1420);j['policy']['machine_windows_min']=[[0,1440]]
        p['jobs']=[j];p['world']['devices']=[d for d in p['world']['devices'] if d['kind']!='ev'];p['fixed_operations']=[];p['EV']={'journeys':[],'connections':[],'failures':[]}
        for d in p['days'].values():d['operator_windows']={'adult1':[]};d['reservations']=[]
        p['days'][p['anchor']]['operator_windows']={'adult1':[[1380,1420],[1540,1800]]}
        r=solve(p,deterministic_time=2);self.assertEqual('feasible',r['status']);t=r['A']['tasks'][0]
        self.assertLess(t['start_min'],1440);self.assertGreater(t['end_min'],1440)
    def test_unavailable_handler_is_proved_not_replaced(self):
        problem=compile_life(self.spec,self.world)
        for d in problem['days'].values():d['operator_windows']={k:[] for k in d['operator_windows']}
        a=solve(problem,deterministic_time=1)
        self.assertEqual('infeasible',a['status']);self.assertIsNone(a['A']);self.assertTrue(a['unsat_core'])
    def test_qualified_residents_can_share_baseline_without_inventing_helpers(self):
        problem=compile_life(self.spec,self.world);m=copy.deepcopy(self.world['members'][0]);m['member_id']='another-adult'
        problem['world']['members'].append(m)
        for d in problem['days'].values():d['operator_windows'][m['member_id']]=copy.deepcopy(d['operator_windows'][self.world['members'][0]['member_id']])
        a=solve(problem,deterministic_time=1)
        self.assertEqual('feasible',a['status'])
        self.assertLessEqual({o['operator_id'] for o in a['A']['operations']},{m['member_id'] for m in problem['world']['members']})
    def test_demand_compiler_not_greedy_failure_inventory(self):
        for cal in self.spec['member_calendars'].values():
            for name in ('weekday','weekend'):
                for e in cal[name]:e['available_for_operation']=False
        problem=compile_life(self.spec,self.world)
        wash=[j for j in problem['jobs'] if j['kind']=='washer']
        self.assertEqual(2,len(wash));self.assertEqual(wash[0]['quantity'],wash[1]['quantity'])
    def test_A_does_not_read_comparison_A_or_B(self):
        problem=compile_life(self.spec,self.world);a=solve(problem,deterministic_time=2)
        problem['legacy_comparator']['A']={'B':'arbitrary_old_output'}
        self.assertEqual(a,solve(problem,deterministic_time=2))
        problem['events']=[]
        with self.assertRaisesRegex(ValueError,'DOWNSTREAM'):solve(problem)
    def test_greedy_order_counterexample_joint_solver_recovers(self):
        from ..life import Scheduler,LIFE_RULES
        p=compile_life(self.spec,self.world);p['days']={next(iter(p['days'])):next(iter(p['days'].values()))}
        p['world']['devices']=[d for d in p['world']['devices'] if d['kind']!='ev'];p['EV']={'journeys':[],'connections':[],'failures':[]}
        p['fixed_operations']=[];p['controls']=[];p['world']['electrical']={'supply_W':2000}
        for device in p['world']['devices']:
            if device['kind'] in ('washer','dishwasher'):
                device['parameters']['power_kw']=1.5
                device['parameters']['nameplate_W']=max(1500,device['parameters'].get('nameplate_W',1500))
        p['days'][next(iter(p['days']))]['operator_windows']={'adult1':[[480,720]]}
        p['days'][next(iter(p['days']))]['reservations']=[]
        jobs=[]
        for kind,deadline,duration in [('washer',720,120),('dishwasher',630,90)]:
            base=next(j for j in p['jobs'] if j['kind']==kind);base=copy.deepcopy(base)
            base.update(need_id=kind,release_min=480,deadline_min=deadline,preferred_start_min=490,quantity=2)
            base['policy'].update(duration_min=duration,machine_windows_min=[[0,1440]],energy_model='legacy_constant_power')
            jobs.append(base)
        p['jobs']=jobs
        s=Scheduler(p['world'],p['days'],LIFE_RULES)
        self.assertEqual('scheduled',s.program(jobs[0],jobs[0]['policy'])['status'])
        self.assertEqual('unserved',s.program(jobs[1],jobs[1]['policy'])['status'])
        result=solve(p,deterministic_time=2)
        self.assertEqual('feasible',result['status'])
        times={r['kind']:r['start_min'] for r in result['A']['tasks']}
        self.assertLess(times['dishwasher'],times['washer'])


class BTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.c=read(ROOT/'examples/control.json')
        cls.c['reference']['thermal']={}
        cls.c['reference']['information_set']['mode']='offline_unexecuted_A_plan'
        # Public fixture has an alternate old event; the new entry point declares
        # the experimental event independently, without changing source A.
        cls.cfg={'rows_per_unit':2,'queries_per_row':2}
        cls.r=generate_day(cls.c,cls.cfg)
    def test_A_immutable_and_no_answers(self):
        before=digest(self.c);r=generate_day(self.c,self.cfg)
        self.assertEqual(before,digest(self.c));self.assertEqual(self.r,r)
        self.assertTrue(r['A_input_unchanged'])
        self.assertLessEqual(r['materialized_requests'],r['materialization_budget'])
        for row in r['rows']:
            self.assertIsNone(row['actual_outcomes']);self.assertIsNone(row['human_acceptance'])
            self.assertFalse(audit(self.c,self.c['A'],apply(self.c['A'],row['patches'])))
    def test_every_component_is_relevant(self):
        for r in self.r['rows']:
            self.assertTrue(r['event_relevance']['passed'])
            self.assertEqual(set(r['changed_assets']),set(r['asset_change_reasons']))
    def test_joint_witnesses_are_not_starved_by_single_device_detail(self):
        self.assertTrue(any(r['independent_units']>=3 for r in self.r['rows']))
    def test_thermal_result_input_rejected(self):
        c=copy.deepcopy(self.c);c['reference']['thermal']={'ac':[{'temperature_C':26}]}
        with self.assertRaisesRegex(ValueError,'FUTURE'):generate_day(c,self.cfg)
    def test_pending_control_consent_never_granted(self):
        c=copy.deepcopy(self.c)
        for d in c['authority']['assets'].values():d['target_control_authorized']=False
        before=digest(c);r=generate_day(c,self.cfg)
        self.assertEqual(before,digest(c));self.assertTrue(r['rows'])
        self.assertTrue(all(x['consent_status']=='new_confirmation_required' for x in r['rows'] if x['components']))
    def test_immutable_handling_cannot_starve_valid_thermal_opportunities(self):
        c=copy.deepcopy(self.c);c['authority']['immutable_operator_ids']=sorted({o['operator_id'] for o in c['A']['operations']})
        result=generate_day(c,self.cfg)
        self.assertTrue(any(x['family']=='water_heater' for r in result['rows'] for x in r['components']))
        original={o['operation_id']:o for o in c['A']['operations']}
        self.assertTrue(all(o==original[o['operation_id']] for r in result['rows'] for p in r['patches'] if p.get('collection')=='operations' for o in p['rows']))
    def test_description_fields_do_not_add_selection_weight(self):
        row=self.r['rows'][0];other=copy.deepcopy(row);other['description']={'extra_AC_axes':['x']*100}
        self.assertEqual(concepts(row),concepts(other))
    def test_two_signatures_and_ten_slots(self):
        rows=[]
        for i in range(10):
            for original in self.r['rows'][:2]:
                r=copy.deepcopy(original);r['date']='2025-07-%02d'%(i+1);r['id']=digest([original['id'],i]);rows.append(r)
        selected=assign(rows,{'selection_nodes':100})
        self.assertEqual(10,len(selected['selected_ids']))
        self.assertTrue(all(not b['physical_or_human_outcomes_used'] for b in selected['blocks']))
    def test_household_and_source_split_has_no_branch_leakage(self):
        records=[dict(id='a',household_id='h1',source_scenario_ids=['s1']),dict(id='b',household_id='h1'),
                 dict(id='c',household_id='h2',source_scenario_ids=['s1']),dict(id='d',household_id='h3')]
        splits=grouped_split(records)['assignments']
        self.assertEqual(splits['a'],splits['b']);self.assertEqual(splits['b'],splits['c'])
    def test_separate_dryer_has_own_request_without_moving_washer(self):
        c=copy.deepcopy(self.c);washer=next(d for d in c['devices'] if d['asset_id']=='washer')
        dryer=copy.deepcopy(washer);dryer.update(asset_id='separate-dryer',types=['dryer']);c['devices'].append(dryer)
        t=next(t for t in c['A']['tasks'] if t['kind']=='dryer');t.update(asset_id='separate-dryer',need_id='separate-dry',depends_on_need_id='wash',start_min=800,end_min=890)
        u=next(o for o in c['A']['operations'] if o['need_id']=='wash' and o['kind']=='unload');u.update(start_min=780,end_min=790)
        c['A']['operations'].extend([{**u,'asset_id':'separate-dryer','need_id':'separate-dry','kind':k,'operation_id':'dry-'+k,'start_min':a,'end_min':a+10} for k,a in [('load',790),('unload',890)]])
        n=copy.deepcopy(c['needs'][0]);n.update(asset_id='separate-dryer',kind='dryer',need_id='separate-dry',deadline_min=1500);c['needs'].append(n)
        raw=next(program_grammar(c,dryer,legacy_config(config())))
        tasks=next(p['rows'] for p in raw['patches'] if p.get('collection')=='tasks')
        self.assertEqual({'separate-dryer'},{t['asset_id'] for t in tasks});self.assertEqual('wash',tasks[0]['depends_on_need_id'])
        self.assertIn('wash',raw['needs'])
    def test_combo_keeps_automatic_dry_in_same_request(self):
        d=next(d for d in self.c['devices'] if d['asset_id']=='washer')
        raw=next(program_grammar(self.c,d,legacy_config(config())))
        self.assertEqual({'washer','dryer'},{t['kind'] for p in raw['patches'] if p.get('collection')=='tasks' for t in p['rows']})
    def test_heating_has_no_cooling_sentinel_delta(self):
        c=copy.deepcopy(self.c);d=next(d for d in c['devices'] if d['asset_id']=='ac')
        for r in c['A']['controls']:
            if r['asset_id']=='ac':r.update(heating_setpoint_C=22,cooling_setpoint_C=40)
        raw=next(heating_precondition(c,d,legacy_config(config())))
        desc=heating_description(c,raw)
        self.assertTrue(desc['cooling_fallback_is_not_heating_state']);self.assertIsNone(desc['response_kWh'])
        self.assertTrue(all(abs(p['same_time_setpoint_delta_C'])<=2 for p in desc['phases']))
    def test_explicit_EV_recovers_inside_physical_connection(self):
        c=copy.deepcopy(self.c);d=next(d for d in c['devices'] if d['asset_id']=='ev')
        old=next(r for r in c['A']['controls'] if r['kind']=='ev_charge_window');nid=old['need_id']
        c['A']['controls']=[r for r in c['A']['controls'] if r['kind']!='ev_charge_window']
        c['A']['controls'].extend({**old,'start_min':t,'end_min':t+10,'_unified_id':'charge-'+str(t)} for t in (1080,1090))
        c['reference']['ev_charging_steps']=[dict(need_id=nid,start_min=t,end_min=t+10,grid_kWh=d['parameters']['charger_kw']/6) for t in (1080,1090)]
        c['physical_ev_connections']=[dict(need_id=nid,start_min=1080,end_min=1260)]
        before=digest(c)
        raws=ev_grammar(c,d,config());r=next(r for r in raws if r['mechanism']=='ev_defer' and r['magnitude']['pause_min']==60)
        self.assertEqual(0,r['magnitude']['energy_shortfall_kWh'])
        self.assertEqual(1140,min(x['start_min'] for x in r['profiles']['B']))
        self.assertEqual(before,digest(c))
        power_context=copy.deepcopy(c);power_context['A']['tasks']=[]
        power_context['devices']=[copy.deepcopy(d)]
        power_context['A']['operations']=[o for o in power_context['A']['operations'] if o['asset_id']==d['asset_id']]
        power_context['A']['controls']=[z for z in power_context['A']['controls'] if z['kind']=='ev_charge_window']
        power_context['electrical']=dict(schema='eb.ab_site_capacity.v1',supply_W=d['parameters']['charger_kw']*500,background_upper_W=0,capacity_mode='declared_test')
        _,_,power=issues(power_context,r['patches'])
        self.assertIn(1140,power['known_excess_minutes'])
    def test_boundary_censoring_is_unknown_but_in_window_chain_is_error(self):
        c=copy.deepcopy(self.c);a=copy.deepcopy(c['A']['operations'][0]);a.update(need_id='outside',operation_id='outside-load',start_min=4000,end_min=4010)
        c['A']['operations'].append(a)
        self.assertFalse(audit(c,c['A'],c['A']))
        c['A']['operations'][-1].update(start_min=1000,end_min=1010)
        self.assertIn('INCOMPLETE_CHAIN',audit(c,c['A'],c['A']))
    def test_initial_connected_evidence_does_not_invent_plug_operation(self):
        c=copy.deepcopy(self.c);row=next(r for r in c['A']['controls'] if r['kind']=='ev_charge_window');nid=row['need_id']
        c['A']['operations']=[o for o in c['A']['operations'] if not(o['need_id']==nid and o['kind']=='EV_plug')]
        unplug=next(o for o in c['A']['operations'] if o['need_id']==nid and o['kind']=='EV_unplug')
        p=dict(need_id=nid,asset_id=row['asset_id'],start_min=row['start_min'],end_min=unplug['start_min'],origin='given_anchor_connection');c['physical_ev_connections']=[p]
        self.assertNotIn('INCOMPLETE_EV_CONNECTION',engineering_issues(c,c['A']))
        p['origin']='guessed'
        self.assertIn('INCOMPLETE_EV_CONNECTION',engineering_issues(c,c['A']))


if __name__=='__main__':unittest.main()
