import copy
import unittest
from pathlib import Path
from ..common import read,digest
from ..model import apply
from .semantics import within_daily_windows
from .opportunities import declare,coverage
from .contract import config
from .factorized import ProgramRecipe,export,expand
from .candidates import program_grammar,legacy_config,issues,prepare,catalogue_domains
from .selection import concepts
from .exhaustive import run


class DeliveryTests(unittest.TestCase):
    def test_selector_rejects_all_answer_fields_before_constructing_features(self):
        from .selection import select_block
        for field,value in (('actual_outcomes',{}),('human_acceptance',False),('human_score',0),('human_reason','')):
            with self.subTest(field=field):
                with self.assertRaisesRegex(ValueError,'ENGINEERING_OR_OUTCOME_LEAKAGE'):
                    select_block([{field:value}])

    def test_combo_primary_family_does_not_depend_on_rule_key_order(self):
        from unittest.mock import patch
        from . import opportunities
        d=next(d for d in self.c['devices'] if d['asset_id']=='washer')
        d['kind']='washer';d['types']=['washer','dryer']
        first=declare(self.c,config());other=copy.deepcopy(opportunities.RULES)
        other['devices']=dict(reversed(list(other['devices'].items())))
        with patch.object(opportunities,'RULES',other):second=declare(self.c,config())
        self.assertEqual(first,second)
        self.assertTrue(all(e['family']=='washer' for e in first['entries'] if e['asset_id']=='washer'))

    def test_granular_EV_permission_is_not_a_charge_window(self):
        from .ev_request_relevance import direct
        e={'start_min':1080,'end_min':1140}
        r=dict(family='ev',asset_id='ev',patches=[dict(type='rows',collection='controls',identity='_unified_id',rows=[])],
            magnitude={'permission_pause_interval_min':[1070,1150]})
        self.assertTrue(direct({},r,e));self.assertTrue(direct({},r,e)[0]['nominal_response_can_be_zero'])
        r['magnitude']['permission_pause_interval_min']=[1150,1160]
        self.assertEqual([],direct({},r,e))
        r['magnitude']={}
        self.assertEqual([],direct({},r,e))

    def test_technical_exception_does_not_erase_input_denominator(self):
        import tempfile
        from unittest.mock import patch
        from ..common import save
        from .pipeline import _job
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'context.json';save(path,self.c)
            with patch('benchmark.ab_generation.unified.pipeline.generate_day',side_effect=ValueError('injected_technical_error')):
                r=_job(({'context_path':str(path)},config()))
        self.assertEqual('engineering_exception',r['status'])
        self.assertEqual('preserved',r['input_opportunity_status'])
        self.assertGreater(r['independent_opportunity_coverage']['potential'],0)

    def setUp(self):
        self.c=read(Path(__file__).parents[1]/'examples/control.json')
        self.c['reference']['thermal']={};self.c['reference']['information_set']['mode']='offline_unexecuted_A_plan'

    def test_daily_window_union_and_midnight(self):
        self.assertTrue(within_daily_windows(1420,1510,[[0,1440]]))
        self.assertTrue(within_daily_windows(1420,1510,[[1320,1440],[0,120]]))
        self.assertFalse(within_daily_windows(1420,1510,[[1320,1440],[60,120]]))
        self.assertFalse(within_daily_windows(100,100,[[0,1440]]))

    def test_device_exhaustive_denominator_and_literal_admission(self):
        r=run();self.assertTrue(r['passed'],str(r));self.assertEqual(54,r['cases'])

    def test_input_denominator_detects_removed_generator_mechanism(self):
        a=declare(self.c,config());b=declare(copy.deepcopy(self.c),config())
        self.assertEqual(a,b)
        report=coverage(a,{'rows':[],'native_domains':[]})
        self.assertGreater(report['potential'],0)
        self.assertTrue(any(r['gap']=='generation_mechanism_missing_or_unresolved' for r in report['mechanisms']))
        self.assertFalse(report['actual_response_distribution_observed'])

    def test_no_charging_demand_is_not_fabricated(self):
        self.c['reference']['ev_charging_steps']=[]
        r=declare(self.c,config())
        self.assertTrue(all(e['status']=='inapplicable' for e in r['entries'] if e['family']=='ev'))

    def test_factorized_program_is_lossless(self):
        d=next(d for d in self.c['devices'] if d['asset_id']=='washer')
        found=0
        for r in program_grammar(self.c,d,legacy_config(config())):
            if not isinstance(r,ProgramRecipe):continue
            encoded,templates=export([[None,r]])
            literal=expand(encoded[0][1],templates)
            self.assertEqual(r['patches'],literal['patches'])
            self.assertEqual(r['profiles'],literal['profiles'])
            self.assertEqual(apply(self.c['A'],r['patches']),apply(self.c['A'],literal['patches']))
            found+=1
            if found==50:break
        self.assertEqual(50,found)

    def test_semantic_dedup_ignores_irrelevant_dates_and_identifiers(self):
        row=dict(components=[],independent_units=0,known_event_reduction_kWh=0,
            features={'manual':'none'},consent_status='proposal',judgment_context=[],issues=[],patches=[],service_context=[])
        other={**copy.deepcopy(row),'date':'2099-01-01','service_context':[{'kind':'unrelated','quantity':999}],
               'description':{'ac_axes':['extra']*50}}
        self.assertEqual(concepts(row),concepts(other))

    def test_semantic_context_preserves_member_stance(self):
        row=dict(components=[],independent_units=0,known_event_reduction_kWh=0,features={'manual':'none'},
            consent_status='proposal',judgment_context=[{'soft_preference_tension':False,'member_preferences':{'x':{'routine_sensitive':False}}}],issues=[],patches=[])
        other=copy.deepcopy(row);other['judgment_context'][0]['member_preferences']['x']['routine_sensitive']=True
        self.assertNotEqual(concepts(row)['signature'],concepts(other)['signature'])

    def test_preloaded_future_program_keeps_executed_loading_fixed(self):
        c=copy.deepcopy(self.c);need=next(n for n in c['needs'] if n['kind']=='washer')
        ops=[o for o in c['A']['operations'] if o['need_id']==need['need_id']]
        load=next(o for o in ops if o['kind']=='load');load.update(start_min=470,end_min=480)
        need['release_min']=400;need['timer_allowed']=True
        g=catalogue_domains(prepare(c,config()),config())
        candidates=[r for values in g['values'] for r in values[1:] if r['family']=='washer' and r['mechanism']=='timer_only']
        self.assertTrue(candidates)
        for r in candidates:
            self.assertEqual(load,next(o for p in r['patches'] if p.get('collection')=='operations' for o in p['rows'] if o['operation_id']==load['operation_id']))

    def test_member_operator_relation_is_not_lost_in_semantic_dedup(self):
        row=dict(components=[],independent_units=0,known_event_reduction_kWh=0,features={'manual':'none'},
            consent_status='proposal',judgment_context=[{'soft_preference_tension':False,'actual_proposed_operator_ids':['a'],
                'member_preferences':{'a':{'handling_change_sensitive':True},'b':{'handling_change_sensitive':False}}}],issues=[],patches=[])
        other=copy.deepcopy(row);other['judgment_context'][0]['actual_proposed_operator_ids']=['b']
        self.assertNotEqual(concepts(row)['signature'],concepts(other)['signature'])

    def test_missing_and_unconnected_targets_have_distinct_reasons(self):
        from .a_solver import target_ledger
        p={'anchor':'2025-07-01','jobs':[]}
        profile={'joint_sampling':{'devices':[{'asset_id':'washer','time_preference':{'per_service':[
            {'source_date':'2025-07-01','need_id':'x','preferred_start_min':None},
            {'source_date':'2025-07-01','need_id':'y','preferred_start_min':1500}]}}]}}
        rows=target_ledger(p,profile,False)
        self.assertEqual(['missing_target','not_connected'],[r['status'] for r in rows])
        self.assertEqual(1500,rows[1]['preferred_start_min'])

    def test_paired_preconditioning_has_necessary_companion_and_pending_consent(self):
        from .candidates import coupled_precondition,heating_precondition,request
        from ..collection_candidates import _raw_thermal
        from ..model import control_issues
        from ..common import canonical
        c=copy.deepcopy(self.c);device=next(d for d in c['devices'] if 'ac' in d['types'])
        for r in c['A']['controls']:
            if r['kind']=='ac_setpoint':r.update(heating_setpoint_C=22,cooling_setpoint_C=25,value_C=25,heating_and_cooling_deadband_C=3)
        c['occupancy'][device['room_id']]=[[480,1920]];local=legacy_config(config())
        for axis in ('cooling','heating'):
            source=_raw_thermal(c,device,local) if axis=='cooling' else heating_precondition(c,device,local)
            raw=next(r for r in source if r['mechanism']=='precondition_and_relax' and r['magnitude']['axis']==axis)
            self.assertIn('THERMOSTAT_DEADBAND_TOO_NARROW',control_issues(c,apply(c['A'],raw['patches'])))
            paired=coupled_precondition(c,raw,local)
            self.assertIsNotNone(paired);self.assertFalse(control_issues(c,apply(c['A'],paired['patches'])))
            paired.update(id=digest(paired['patches']),unit=canonical([device['asset_id'],None]),relative_level='small_relative',absolute_level='small',known_event_reduction_kWh=0,unknown_thermal_response=True)
            row=request(c,[paired],config())
            self.assertFalse(row.get('engineering_diagnostic'));self.assertEqual('new_confirmation_required',row['consent_status'])
            self.assertTrue(paired['magnitude']['companion_setpoint_changes'])
            self.assertTrue(all(x['without_companion_gap_C']<x['required_deadband_C'] for x in paired['magnitude']['companion_setpoint_changes']))

    def test_fresh_control_identity_covers_non_EV_rows_without_state_change(self):
        from .a_solver import compile_life
        from .pipeline import fresh_context
        root=Path(__file__).parents[1];spec=copy.deepcopy(read(root/'examples/life/life_batch.json')['households'][0])
        world=read(root/'examples/life/resource_worlds.json')['households'][0];spec['end_exclusive']='2025-07-03'
        p=compile_life(spec,world);A=copy.deepcopy(p['legacy_comparator']['A'])
        for i,r in enumerate(A['controls']):
            if r['kind']=='ev_charge_window':r['_unified_id']='charge-'+str(i)
        result=dict(status='feasible',A=A,input_sha256='fixture',ev_charging_steps=[],physical_ev_connections=p['EV']['connections'])
        c=fresh_context(p,result,spec['anchor'],{},config())
        self.assertEqual(len(c['A']['controls']),len({r['_unified_id'] for r in c['A']['controls']}))
        strip=lambda r:{k:v for k,v in r.items() if k!='_unified_id'}
        self.assertEqual([strip(r) for r in A['controls']],[strip(r) for r in c['A']['controls']])
        ev=next(r for r in c['A']['controls'] if r['kind']=='ev_charge_window');b={**ev,'start_min':ev['start_min']+10}
        changed=apply(c['A'],[dict(type='rows',collection='controls',identity='_unified_id',rows=[b])])
        self.assertEqual([r for r in c['A']['controls'] if r['kind']!='ev_charge_window'],[r for r in changed['controls'] if r['kind']!='ev_charge_window'])


if __name__=='__main__':unittest.main()
