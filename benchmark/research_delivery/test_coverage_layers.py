import copy
import itertools
from pathlib import Path
import unittest

from benchmark.ab_generation.common import read
from benchmark.ab_generation.unified.contract import config
from benchmark.ab_generation.unified.candidates import generate_day
from .coverage_layers import count_numeric,analyse
from .domain_expansion_audit import compare


class CoverageLayerTests(unittest.TestCase):
    def test_numeric_counts_match_explicit_small_cartesian_enumeration(self):
        domains=[dict(unit=str(i),ids=set(v),resources=set(r)) for i,v,r in
                 [(0,['a','b'],['person:1']),(1,['c'],['person:1']),(2,['d','e'],['room:2'])]]
        full=list(itertools.product(*[sorted(d['ids']|{''}) for d in domains]))
        witnessed=full[::3];selected=witnessed[:2]
        result=count_numeric(domains,witnessed,selected)
        for row in result['groups']:
            axes=list(map(int,row['units']))
            universe={tuple(x[i] for i in axes) for x in full}
            known={tuple(x[i] for i in axes) for x in witnessed}
            chosen={tuple(x[i] for i in axes) for x in selected}
            self.assertEqual(len(universe),row['syntactic_upper_bound'])
            self.assertEqual(len(known),row['known_feasible'])
            self.assertEqual(len(chosen),row['selected'])
            self.assertEqual(len(universe-known),row['feasibility_unclassified'])
        self.assertIn(3,result['by_strength'])
        self.assertFalse(result['feasibility_denominator_exact'])

    def test_no_units_does_not_report_full_coverage(self):
        result=count_numeric([],[],[])
        self.assertEqual({},result['by_strength']);self.assertEqual([],result['groups'])

    def test_large_domain_counts_exact_without_materializing_product(self):
        domains=[dict(unit=str(i),ids=set(map(str,range(300000))),resources={'same'}) for i in range(3)]
        result=count_numeric(domains,[],[])
        self.assertEqual(300001**3,result['by_strength'][3]['syntactic_upper_bound'])
        self.assertIsNone(result['by_strength'][3]['selected_coverage_bounds']['upper'])

    def test_literal_subset_can_expand_while_cell_count_shrinks(self):
        def value(identifier,relative):
            return dict(id=identifier,unit='u',family='washer',mechanism='retimed_handling',relative_level=relative)
        old=dict(native_domains=[[None,value('a','small'),value('b','medium')]],
                 factors=[[dict(label='none',ids=[0]),dict(label='small',ids=[1]),dict(label='medium',ids=[2])]])
        new=dict(native_domains=[[None,value('a','small'),value('b','small'),value('c','small')]],
                 factors=[[dict(label='none',ids=[0]),dict(label='small',ids=[1,2,3])]])
        result=compare(old,new)
        self.assertEqual([],result['removed_old_ids']);self.assertEqual(1,result['added_literal_commands'])
        self.assertTrue(any(r['old_cell']!=r['new_cell'] for r in result['semantic_partition_crosswalk']))

    def test_literal_fixture_all_candidates_checked_and_tamper_reported(self):
        context=read(Path(__file__).parents[1]/'ab_generation/examples/control.json')
        context['reference']['thermal']={}
        context['reference']['information_set']['mode']='offline_unexecuted_A_plan'
        cfg=config(dict(rows_per_unit=2,queries_per_row=2,ac_delta_C=[.5],tank_delta_C=[1],
                        thermal_duration_min=[10],precondition_min=[10]))
        cat=generate_day(context,cfg,{})
        self.assertTrue(cat['rows'])
        selected=[cat['rows'][0]['id']]
        result=analyse(cat,context,selected)
        self.assertTrue(result['all_candidate_checks']['passed'],result['all_candidate_checks']['cases_with_errors'])
        self.assertEqual(len(cat['rows']),result['all_candidate_checks']['cases'])
        before=copy.deepcopy(cat)
        cat['rows'][0]['human_score']=0
        result=analyse(cat,context,selected)
        self.assertIn('ANSWER_OR_ACTUAL_OUTCOME_PRESENT',result['all_candidate_checks']['cases_with_errors'][0]['errors'])
        self.assertEqual(before['native_domains'],cat['native_domains'])


if __name__=='__main__':unittest.main()
