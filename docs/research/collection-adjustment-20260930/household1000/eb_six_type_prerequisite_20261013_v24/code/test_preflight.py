"""Meaningful negative controls for quotas, eligibility, and joint feasibility."""
import unittest
import random
from preflight import capacity_match, eligibility, quota, TYPES


def world(ages, work=None, ev=False):
    return {'members': [{'member_id': str(i), 'age_years': a,
                         'employment_status': (work or ['unknown'] * len(ages))[i]}
                        for i, a in enumerate(ages)],
            'parameter_pack': {'devices': [{'types': ['ev']}] if ev else []}}


class AdmissionChecks(unittest.TestCase):
    def test_public_counts_and_integer_rounding(self):
        self.assertEqual(quota(dict(zip(TYPES, [97,116,73,88,91,119])), 1000),
                         dict(zip(TYPES, [166,198,125,151,156,204])))

    def test_reject_invalid_counts(self):
        for bad in [{}, dict(zip(TYPES, [97,116,73,88,91,0])),
                    dict(zip(TYPES, [97,116,73,88,91,119.0]))]:
            with self.assertRaises(ValueError):
                quota(bad, 1000)

    def test_unknown_employment_never_imputed(self):
        w = world([25], ev=True)
        self.assertTrue(eligibility(w)['F'])
        self.assertEqual(w['members'][0]['employment_status'], 'unknown')

    def test_no_current_work_not_commuter(self):
        e = eligibility(world([25], ['no_current_work'], ev=True))
        self.assertFalse(e['A'] or e['D'] or e['F'])
        self.assertTrue(e['B'])

    def test_95_year_old_unknown_not_commuter(self):
        e = eligibility(world([95], ev=True))
        self.assertFalse(e['A'] or e['C'] or e['D'] or e['F'])
        self.assertTrue(e['B'])

    def test_minor_only_household_is_explicit_deficit(self):
        self.assertFalse(any(eligibility(world([10], ev=True)).values()))

    def test_caregiver_needs_another_member(self):
        self.assertFalse(eligibility(world([67]))['E'])
        self.assertTrue(eligibility(world([30,67]))['E'])
        self.assertTrue(eligibility(world([30,3]))['E'])

    def test_EV_equipment_is_necessary_but_not_sufficient(self):
        self.assertFalse(eligibility(world([30]))['F'])
        self.assertFalse(eligibility(world([90], ev=True))['F'])

    def test_marginal_capacities_can_hide_joint_infeasibility(self):
        # Every marginal has one eligible unit, but they are the same unit.
        rows = [dict.fromkeys(TYPES, True)] + [dict.fromkeys(TYPES, False)] * 5
        r = capacity_match(rows, dict.fromkeys(TYPES, 1))
        self.assertEqual(r['maximum_assignable'], 1)
        self.assertEqual(r['cut_certificate_flow'], 1)
        self.assertFalse(r['jointly_feasible'])

    def test_augmenting_paths_resolve_competing_types(self):
        rows = [{k: k in ['A','B'] for k in TYPES},
                {k: k == 'A' for k in TYPES}]
        targets = {k: int(k in ['A','B']) for k in TYPES}
        r = capacity_match(rows, targets)
        self.assertEqual(r['maximum_assignable'], 2)
        self.assertTrue(r['jointly_feasible'])

    def test_flow_and_cut_match_independent_exhaustive_solver(self):
        rng = random.Random(241013)
        targets = dict(zip(TYPES, [2,1,1,0,0,0]))

        def exhaustive(rows, remaining, i=0):
            if i == len(rows):
                return 0
            best = exhaustive(rows, remaining, i + 1)
            for k in TYPES:
                if rows[i][k] and remaining[k]:
                    nxt = dict(remaining)
                    nxt[k] -= 1
                    best = max(best, 1 + exhaustive(rows, nxt, i + 1))
            return best

        for _ in range(30):
            rows = [{k: rng.random() < .5 for k in TYPES} for _ in range(4)]
            expected = exhaustive(rows, targets)
            report = capacity_match(rows, targets)
            self.assertEqual(report['maximum_assignable'], expected)
            self.assertEqual(report['cut_certificate_flow'], expected)


if __name__ == '__main__':
    unittest.main()
