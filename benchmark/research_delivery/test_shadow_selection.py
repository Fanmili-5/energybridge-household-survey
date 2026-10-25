import copy
import unittest

from .shadow_selection import summarize, tail_flags, validate_slots


def case(identifier, day, count=1):
    return dict(id=identifier, household_id='h', date=day, independent_units=count,
        components=[dict(relative_level='small_relative')], issues=['deadline_conflict'],
        judgment_context=[dict(soft_preference_tension=True, member_opinions_differ=True)],
        consent_status='new_confirmation_required', known_event_reduction_kWh=0.,
        unknown_thermal_response=True, actual_outcomes=None)


class FrozenShadowReportingTests(unittest.TestCase):
    def test_tails_overlap_and_unknown_is_not_observed_failure(self):
        r = case('a', 'd1')
        result = summarize([r], ['a'])
        self.assertTrue(tail_flags(r)['nominal_zero'])
        self.assertEqual(1, result['tails']['thermal_unknown'])
        self.assertEqual(1, result['tails']['life_or_service_conflict'])
        self.assertEqual(0, result['physical_failures_observed'])
        self.assertTrue(result['actual_outcomes_empty'])

    def test_original_dates_required_not_just_total_question_count(self):
        rows = [case('a', 'd1'), case('b', 'd1'), case('c', 'd2')]
        contexts = {('h', 'd1'): None, ('h', 'd2'): None}
        validate_slots(rows, ['a', 'c'], contexts)
        with self.assertRaisesRegex(ValueError, 'ORIGINAL_DATE_ACCOUNTING_FAILED'):
            validate_slots(rows, ['a', 'b'], contexts)

    def test_duplicate_and_unknown_identifiers_are_not_silently_dropped(self):
        r = case('a', 'd1')
        for ids in (['a', 'a'], ['unknown']):
            with self.assertRaises(ValueError):
                summarize([r], ids)
        with self.assertRaisesRegex(ValueError, 'DUPLICATE_CANDIDATE_ID'):
            validate_slots([r, copy.deepcopy(r)], ['a'], {('h', 'd1'): None})

    def test_reverse_nominal_effect_retained_without_mutating_input(self):
        r = case('a', 'd1', 6)
        r['known_event_reduction_kWh'] = -.5
        before = copy.deepcopy(r)
        result = summarize([r], ['a'])
        self.assertEqual({6: 1}, result['task_counts'])
        self.assertEqual(1, result['tails']['nominal_reverse'])
        self.assertEqual(before, r)


if __name__ == '__main__':
    unittest.main()
