import itertools
import unittest

from .joint_order_review import attainable_orders


class IndependentOrderBoundTests(unittest.TestCase):
    def check(self,options):
        rows=[dict(household_id='h',date=str(d),independent_units=k) for d,ks in enumerate(options) for k in ks]
        result=attainable_orders(rows)[0]
        exhaustive=max(len(set(values)) for values in itertools.product(*options))
        self.assertEqual(exhaustive,result['maximum_distinct_counts'])
        self.assertEqual(exhaustive,len({r['date'] for r in result['witness']}))
        self.assertTrue(all(r['tasks'] in options[int(r['date'])] for r in result['witness']))

    def test_matching_handles_competing_counts_on_one_date(self):
        self.check([(1,2,3),(1,),(1,)])

    def test_matching_bound_agrees_with_exhaustive_small_spaces(self):
        for options in ([(1,),(2,),(4,)],[(1,2),(2,3),(4,5)],[(1,3),(1,3)]):self.check(options)

    def test_empty_roster_does_not_invent_an_opportunity(self):
        self.assertEqual([],attainable_orders([]))


if __name__=='__main__':unittest.main()
