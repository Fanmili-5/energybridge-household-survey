"""Date-specific input and command regression; not a native physics test."""
import copy
import unittest

from national_idf.case_commands import CaseTimeline
from national_idf.dated_case import view
from national_idf.request_support import assess_inputs
from tests.synthetic_inputs import case, domain


def dated():
    value = case()
    value['schema'] = 'national_idf.case.v3'
    life = value['life']
    day = dict(occupancy=life['occupancy'], mixed_water=life['mixed_water_daily'],
               services=life['services_daily'], ev_connections=life['ev_connection_daily'], ev_trip=life['ev_daily'])
    life['by_date'] = {date: copy.deepcopy(day) for date in ('2007-01-01', '2007-01-02')}
    return value


class DatedCommandTests(unittest.TestCase):
    def codes(self, value):
        return {row['code'] for row in assess_inputs(value, domain())['failures']}

    def test_missing_requested_date_is_rejected(self):
        value = dated()
        self.assertFalse(self.codes(value))
        del value['life']['by_date']['2007-01-02']
        self.assertIn('DATED_CASE_DATE_MISSING', self.codes(value))

    def test_second_day_demands_are_not_replaced_by_first_day(self):
        value = dated()
        day = value['life']['by_date']['2007-01-02']
        day['occupancy'] = []
        day['mixed_water'] = []
        for service in day['services'].values():
            service['cycles'] = 0
        value['controls']['program_start_overrides'] = {'2007-01-02': {key: [] for key in day['services']}}
        frames = list(CaseTimeline(value, domain()).frame(i) for i in range(576))
        self.assertAlmostEqual(sum(x['mixed_water']['requested_volume_L'] for x in frames), 40)
        self.assertFalse(any(x['program_starts'] for x in frames[288:]))
        self.assertEqual(sum(x['people']['conditioned space']['persons'] for x in frames[288:]), 0)

    def test_dated_view_preserves_input_and_trims_only_outside_control_dates(self):
        value = dated()
        value['controls']['program_start_overrides'] = {'2007-01-01': {'washer': []}, '2008-01-01': {'washer': [600]}}
        before = copy.deepcopy(value)
        result = view(value, '2007-01-02')
        self.assertEqual(value, before)
        self.assertEqual(set(result['controls']['program_start_overrides']), {'2007-01-01'})
        self.assertEqual(result['life']['mixed_water_daily'], value['life']['by_date']['2007-01-02']['mixed_water'])

    def test_explicit_daily_copies_preserve_values_and_add_ev_departure_metadata(self):
        old, new = CaseTimeline(case(), domain()), CaseTimeline(dated(), domain())
        self.assertEqual(old.steps, new.steps)
        for index in range(old.steps):
            before, after = old.frame(index), new.frame(index)
            self.assertEqual(after['ev'].pop('departure_min'), 480)
            self.assertEqual(before, after)


if __name__ == '__main__':
    unittest.main()
