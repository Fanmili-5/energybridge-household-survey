"""Selection invariants on independently enumerable finite candidate fixtures."""
import copy
import itertools
import unittest

from benchmark.research_delivery.test_semantic_links import fixture
from .contract import config,entry_config
from .selection import assign,concepts,select_block


def row(count,date,identity):
    r=fixture();component,judgment=copy.deepcopy(r['components'][0]),copy.deepcopy(r['judgment_context'][0])
    r.update(id=identity,date=date,independent_units=count,components=[],judgment_context=[],patches=[])
    for i in range(count):
        c,j=copy.deepcopy(component),copy.deepcopy(judgment)
        c.update(id=identity+':'+str(i),unit='batch'+str(i),asset_id='shared-washer',family='washer',service_need_id='batch'+str(i))
        j['asset_id']='shared-washer';r['components'].append(c);r['judgment_context'].append(j)
    return r


def current(**overrides):
    return config({**entry_config(),**overrides})


class JointOrderSelectionTests(unittest.TestCase):
    def test_exact_counts_do_not_collapse_three_and_six(self):
        a,b=row(3,'d','a'),row(6,'d','b')
        old=lambda r:{t for t in concepts(r)['tokens'] if 'joint_order=' in t}
        new=lambda r:{t for t in concepts(r,'exact_witnessed_v1')['tokens'] if 'joint_order=' in t}
        self.assertEqual(old(a),old(b));self.assertNotEqual(new(a),new(b))

    def test_all_available_orders_fit_without_prescribed_ratios(self):
        rows=[row(k,'d'+str(d),f'{d}-{k}') for d in range(10) for k in range(1,7)]
        before=copy.deepcopy(rows)
        answer=select_block(rows,current(repeat_family=100,repeat_context=100,repeat_composition=100))
        self.assertEqual(set(range(1,7)),set(answer['joint_order_coverage'][0]['selected_task_counts']))
        self.assertEqual(10,len(answer['selected_ids']));self.assertEqual(before,rows)
        self.assertFalse(answer['proportions_prescribed']);self.assertTrue(answer['solver']['joint_order']['optimal'])

    def test_date_competition_matches_independent_enumeration(self):
        options=[(1,2),(3,4),(4,5)]
        rows=[row(k,'d'+str(d),f'{d}-{k}') for d,ks in enumerate(options) for k in ks]
        maximum=max(len(set(values)) for values in itertools.product(*options))
        answer=select_block(rows,current());coverage=answer['joint_order_coverage'][0]
        self.assertEqual(maximum,len(coverage['selected_task_counts']))
        self.assertTrue(coverage['missing_task_counts'])
        gaps=[x for x in answer['coverage'] if x['tag'].startswith('trade.joint_order=') and x['deficit']]
        self.assertTrue(gaps);self.assertTrue(all(x['reason']=='given_dates_compete_for_slots_or_solver_budget' for x in gaps))
        self.assertTrue(set(answer['selected_ids']) <= {r['id'] for r in rows})

    def test_only_witnessed_counts_enter_targets_and_no_change_is_not_inserted(self):
        rows=[row(1,'d1','a'),row(11,'d2','b')]
        answer=select_block(rows,current());coverage=answer['joint_order_coverage'][0]
        self.assertEqual([1,11],coverage['available_task_counts'])
        self.assertNotIn(0,coverage['selected_task_counts'])
        self.assertEqual({'a','b'},set(answer['selected_ids']))
        self.assertIn('absent_is_not_proven_no_opportunity',coverage['scope'])

    def test_no_help_reverse_conflict_and_small_actions_are_not_filtered(self):
        rows=[row(1,'d'+str(i),'case'+str(i)) for i in range(3)]
        rows[0]['known_event_reduction_kWh']=0
        rows[1]['known_event_reduction_kWh']=-1
        rows[2]['issues']=['life_conflict'];rows[2]['consent_status']='confirmation_required'
        for r in rows:r['components'][0]['relative_level']='small_relative'
        answer=select_block(rows,current())
        self.assertEqual({r['id'] for r in rows},set(answer['selected_ids']))

    def test_same_household_date_and_seed_replay(self):
        rows=[row(k,'d'+str(d),f'{d}-{k}') for d in range(4) for k in (1,2,4)]
        for seed in (0,7):
            cfg=current(seed=seed)
            self.assertEqual(assign(rows,cfg)['selected_ids'],assign(list(reversed(rows)),cfg)['selected_ids'])

    def test_unknown_policy_or_invalid_task_count_is_rejected(self):
        with self.assertRaisesRegex(ValueError,'UNKNOWN_JOINT_ORDER'):config({'selection_joint_order':'invented'})
        with self.assertRaisesRegex(ValueError,'NEW_SELECTION_POLICY'):config({'selection_joint_order':'exact_witnessed_v1'})
        r=row(1,'d','a');r['independent_units']=-1
        with self.assertRaisesRegex(ValueError,'INVALID_INDEPENDENT_TASK_COUNT'):select_block([r],current())
        r['independent_units']=6
        with self.assertRaisesRegex(ValueError,'DOES_NOT_MATCH_COMPONENTS'):select_block([r],current())

    def test_missing_unit_cannot_hide_duplicate_roots(self):
        r=row(3,'d','a')
        r['components'][1]['unit']=r['components'][0]['unit']
        r['components'][2].pop('unit')
        with self.assertRaisesRegex(ValueError,'MISSING_INDEPENDENT_TASK_UNIT'):select_block([r],current())
        r['components'][2]['unit']='third'
        with self.assertRaisesRegex(ValueError,'DUPLICATE_INDEPENDENT_TASK_UNIT'):select_block([r],current())

    def test_no_task_identity_is_unknown_instead_of_component_count_fallback(self):
        r=row(1,'d','a')
        for invalid in (None,'',0,[]):
            r['components'][0]['unit']=invalid
            with self.subTest(unit=invalid),self.assertRaisesRegex(ValueError,'MISSING_INDEPENDENT_TASK_UNIT'):
                select_block([r],current())

    def test_duplicate_case_id_cannot_collapse_date_or_coverage_views(self):
        with self.assertRaisesRegex(ValueError,'DUPLICATE_CANDIDATE_ID'):
            select_block([row(1,'d1','same'),row(4,'d2','same')],current())

    def test_no_solver_incumbent_is_unknown_without_manufactured_choices(self):
        from types import SimpleNamespace
        from unittest.mock import patch
        with patch('scipy.optimize.milp',return_value=SimpleNamespace(x=None,message='budget exhausted')):
            answer=select_block([row(1,'d','a')],current())
        self.assertEqual('solver_unknown_no_incumbent',answer['status'])
        self.assertEqual([],answer['selected_ids'])

    def test_secondary_timeout_keeps_primary_incumbent_and_reports_fallback(self):
        from types import SimpleNamespace
        from unittest.mock import patch
        from scipy.optimize import milp as solve
        calls=[]
        def limited(*args,**kwargs):
            calls.append(1)
            if len(calls)==2:return SimpleNamespace(x=None,message='budget exhausted',status=1)
            return solve(*args,**kwargs)
        rows=[row(k,'d'+str(d),f'{d}-{k}') for d in range(3) for k in (1,2,4)]
        with patch('scipy.optimize.milp',side_effect=limited):answer=select_block(rows,current())
        self.assertTrue(answer['coverage_stage_used_fallback'])
        self.assertFalse(answer['solver']['coverage']['optimal'])
        self.assertEqual(3,len(answer['joint_order_coverage'][0]['selected_task_counts']))


class CurrentEntryTests(unittest.TestCase):
    def test_implicit_CLI_config_is_current_and_explicit_legacy_is_preserved(self):
        cfg=entry_config()
        self.assertEqual('delivery_v2_10',cfg['method_revision'])
        self.assertEqual('exact_witnessed_v1',cfg['selection_joint_order'])
        self.assertEqual('life_conditional_v1',cfg['A_target_context_mode'])
        self.assertEqual('include_life_conflicts',cfg['handling_calendar_domain'])
        from pathlib import Path
        old=entry_config(Path(__file__).with_name('DEFAULT_CONFIG.json'))
        self.assertEqual('delivery_v2_3',old['method_revision'])
        self.assertEqual('legacy_buckets_v1',old['selection_joint_order'])

    def test_actual_CLI_dispatch_passes_current_configuration(self):
        import contextlib
        import io
        import runpy
        from unittest.mock import patch
        with patch('sys.argv',['unified','build','--inputs','read-only-input','--out','unused']),\
             patch('benchmark.ab_generation.unified.pipeline.build',return_value={'status':'mocked'}) as build,\
             contextlib.redirect_stdout(io.StringIO()):
            runpy.run_module('benchmark.ab_generation.unified.__main__',run_name='__main__')
        self.assertEqual('exact_witnessed_v1',build.call_args.args[2]['selection_joint_order'])


if __name__=='__main__':unittest.main()
