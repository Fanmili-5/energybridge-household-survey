"""Exhaustive verification of bounded interval search, independent inequalities."""
import itertools
import unittest

from .interval_backtracking import assignments


class IntervalBacktrackingTests(unittest.TestCase):
    def test_complete_search_equals_literal_enumeration(self):
        holds = {
            i: dict(asset_id='same' if i < 2 else 'dryer', need_id=str(i),
                    values=[[j, 20*j+10*i, 20*j+10*i+10, 20*j+10*i+5]
                            for j in range(3)])
            for i in range(3)
        }
        roots = {0: {1}, 1: {2}, 2: set()}
        subsets = [[0], [1], [2], [0, 1], [1, 2], [0, 2], [0, 1, 2]]
        checked = 0
        for ds in itertools.product(subsets, repeat=3):
            for order in (None, 1, 2, 3):
                for dependency in (False, True):
                    expected = set()
                    for x in itertools.product(*ds):
                        if x[0] != 1 and x[1] != 2:
                            continue
                        if order is not None and sum(v != 0 for v in x) != order:
                            continue
                        a, z = 20*x[0], 20*x[0]+10
                        b, y = 20*x[1]+10, 20*x[1]+20
                        if max(a, b) < min(z, y):
                            continue
                        if dependency and 20*x[2]+20 < z:
                            continue
                        expected.add(x)
                    stats = {}
                    found = list(assignments(dict(enumerate(ds)), holds, [],
                        {'2': '0'} if dependency else {}, [], roots, order, 256, stats))
                    self.assertEqual(set(map(tuple, found)), expected)
                    self.assertEqual(len(found), len(expected))
                    self.assertTrue(stats['complete'])
                    self.assertFalse(stats['budget_exhausted'])
                    checked += 1
        self.assertEqual(checked, 2744)

    def test_budget_exhaustion_is_not_infeasibility(self):
        stats = {}
        found = list(assignments({0: [0, 1], 1: [0, 1]}, {}, [], {}, [],
                                 {0: {1}, 1: {1}}, 1, 1, stats))
        self.assertEqual(found, [])
        self.assertTrue(stats['budget_exhausted'])
        self.assertFalse(stats['complete'])


if __name__ == '__main__':
    unittest.main()
