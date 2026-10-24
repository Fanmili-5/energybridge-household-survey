import copy
import unittest
from unittest.mock import patch

from .comparison_audit import matrix_keys,direct_family_metrics
from .shared_domain_comparison import ARMS


class ComparisonAuditTests(unittest.TestCase):
    def test_equal_row_count_does_not_hide_duplicate_or_missing_run(self):
        plan=dict(seeds=list(range(8)),comparison_records=[dict(household_id=str(h),date='2025-01-'+str(d))
                    for h in range(8) for d in (1,5,10)])
        rows=[dict(arm=a,seed=s,**r) for a,_ in ARMS for s in plan['seeds'] for r in plan['comparison_records']]
        self.assertTrue(matrix_keys(plan,rows)['complete'])
        replaced=rows[:-1]+[copy.deepcopy(rows[0])]
        report=matrix_keys(plan,replaced)
        self.assertEqual(1152,report['actual']);self.assertFalse(report['complete'])
        self.assertEqual(1,len(report['missing']));self.assertEqual(1,len(report['duplicates']))

    def test_device_family_weight_is_not_number_of_AC_descriptors(self):
        entries=[]
        for family,n in [('ac',4),('washer',1)]:
            for i in range(n):
                entries.append(dict(family=family,asset_id=family,need_id=None,mechanism='m'+str(i),axis=None,status='potential'))
        ledger={'entries':entries}
        cs=[dict(asset_id=e['asset_id'],service_need_id=e['need_id'],mechanism=e['mechanism'],magnitude={},
                 event_relevance={'role':'direct_event_request'}) for e in entries if e['family']=='ac']
        cat=dict(comparison={'configuration':{}},input_opportunities=ledger,rows=[{'components':cs}],
                 independent_opportunity_coverage={'potential':5,'witnessed':4})
        with patch('benchmark.research_delivery.comparison_audit.declare',return_value=ledger):
            result=direct_family_metrics(cat,{})
        self.assertEqual(.5,result['macro_family_ratio'])
        self.assertEqual({'ac':1,'washer':0},result['family_potential_witness_ratios'])

    def test_only_direct_roots_count_and_stale_counts_are_rejected(self):
        e=dict(family='washer',asset_id='washer',need_id='n',mechanism='retimed_handling',axis=None,status='potential')
        ledger={'entries':[e]}
        c=dict(asset_id='washer',service_need_id='n',mechanism='retimed_handling_full_grid',magnitude={},
               event_relevance={'role':'necessary_service_or_machine_dependency'})
        cat=dict(comparison={'configuration':{}},input_opportunities=ledger,rows=[{'components':[c]}],
                 independent_opportunity_coverage={'potential':1,'witnessed':0})
        with patch('benchmark.research_delivery.comparison_audit.declare',return_value=ledger):
            self.assertEqual(0,direct_family_metrics(cat,{})['witnessed'])
            c['event_relevance']['role']='direct_event_request'
            with self.assertRaisesRegex(ValueError,'COUNTS_DISAGREE'):direct_family_metrics(cat,{})
            cat['independent_opportunity_coverage']['witnessed']=1
            self.assertEqual(1,direct_family_metrics(cat,{})['witnessed'])
            with patch('benchmark.research_delivery.comparison_audit.declare',return_value={'entries':[]}):
                with self.assertRaisesRegex(ValueError,'REDECLARATION_DIFFERS'):direct_family_metrics(cat,{})


if __name__=='__main__':unittest.main()
