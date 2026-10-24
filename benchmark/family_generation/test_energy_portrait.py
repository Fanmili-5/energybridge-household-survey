"""Conservation and counterexample tests; no EP or population batch."""
import copy
from pathlib import Path
import tempfile
import unittest

from .core import HERE, digest, read, save, verify
from .energy_portrait import build_portraits, compile_portrait, device_line, render_portrait
from .portrait_inputs import at, from_reference

FIXTURE = HERE / 'examples/energy_portrait/input.json'


class EnergyPortraitTests(unittest.TestCase):
    def setUp(self):
        self.contexts = read(FIXTURE)['households']
        self.context = copy.deepcopy(self.contexts[0])

    def test_existing_days_and_service_requirements_are_conserved(self):
        before = digest(self.context)
        p = compile_portrait(self.context)
        self.assertEqual(digest(self.context), before)
        self.assertEqual(p['existing_days'], self.context['days'])
        got = {s['need_id']: s for d in p['devices'] for s in d['requirements']}
        self.assertEqual(got, {s['need_id']: s for s in self.context['services']})
        self.assertEqual(p['existing_policy'], self.context['existing_policy'])

    def test_same_input_has_identical_output_without_random_parameters(self):
        self.assertEqual(compile_portrait(self.context), compile_portrait(copy.deepcopy(self.context)))

    def test_all_six_roles_keep_distinct_EB_confirmation_conditions(self):
        modes = {c['role']: compile_portrait(c)['attitude']['control'] for c in self.contexts}
        self.assertEqual(modes, dict(A='suggestion_first', B='confirm_required', C='confirm_same_day',
                                   D='automatic_within_bounds', E='advice_only_default', F='automatic_within_bounds'))
        a = [compile_portrait(c) for c in self.contexts if c['role'] == 'A']
        self.assertEqual(a[0]['attitude'], a[1]['attitude'])
        self.assertNotEqual(a[0]['devices'], a[1]['devices'])

    def test_multifunction_asset_retains_both_services(self):
        p = compile_portrait(self.context)
        kinds = [(d['asset_id'], d['kind']) for d in p['devices']]
        shared = next(d['asset_id'] for d in p['devices'] if d['kind'] == 'dryer')
        self.assertIn((shared, 'washer'), kinds)
        self.assertIn((shared, 'dryer'), kinds)

    def test_no_dryer_or_dishwasher_is_invented_for_second_A_family(self):
        c = next(c for c in self.contexts if c['household_id'] == 'ordinary-v6-0250')
        self.assertFalse({'dryer', 'dishwasher'} & {d['kind'] for d in compile_portrait(c)['devices']})

    def test_cross_midnight_deadlines_keep_the_date(self):
        p = compile_portrait(self.context)
        d = next(d for d in p['devices'] if d['kind'] == 'washer')
        date = d['requirements'][0]['source_date']
        self.assertIn('次日18:00', device_line(d, date))
        self.assertEqual(at('2025-01-01', 2520), '2025-01-02T18:00')
        self.assertEqual(at('2025-01-01', -30), '2024-12-31T23:30')

    def test_reference_start_is_not_labeled_measured_habit(self):
        p = compile_portrait(self.context)
        d = next(d for d in p['devices'] if d['kind'] == 'washer')
        self.assertIn('not_measured_human_preference', d['habit_basis'])
        self.assertIn('安排参考', device_line(d, d['requirements'][0]['source_date']))

    def test_existing_EV_85_is_not_replaced_by_EB_reference_80(self):
        c = next(c for c in self.contexts if c['role'] == 'F')
        p = compile_portrait(c)
        self.assertTrue(any('REFERENCE80' in w for w in p['warnings']))
        ev = next(d for d in p['devices'] if d['kind'] == 'ev')
        self.assertTrue(all(s['required_departure_soc'] == .85 for s in ev['requirements']))

    def test_existing_thermal_bound_is_flagged_without_rewriting_it(self):
        p = compile_portrait(self.context)
        self.assertEqual(p['existing_policy']['thermal']['usual_setpoint_C'], 25.5)
        self.assertTrue(any('PREFERRED26' in w for w in p['warnings']))
        self.assertFalse(p['physical_success_claimed'])

    def test_absent_service_is_unknown_not_a_new_task(self):
        self.context['services'] = [s for s in self.context['services'] if s['kind'] != 'washer']
        p = compile_portrait(self.context)
        d = next(d for d in p['devices'] if d['kind'] == 'washer')
        self.assertTrue(d['no_task_in_selected_days'])
        self.assertIn('不补造', device_line(d, self.context['days'][0]['date']))

    def test_invalid_deadline_is_retained_as_diagnostic_without_redraw(self):
        self.context['services'][0].pop('deadline_at')
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            save(root / 'input.json', {'schema': 'eb.energy_portrait.batch.v1', 'households': [self.context]})
            r = build_portraits(root / 'input.json', root / 'out')
            self.assertEqual(r['requested'], 1)
            self.assertEqual(r['compiled'], 0)
            self.assertEqual(r['records'][0]['status'], 'portrait_rejected')
            self.assertIn('MISSING_SERVICE_DEADLINE', r['records'][0]['reason'])

    def test_unowned_device_service_is_rejected(self):
        self.context['services'][0]['asset_id'] = 'nonexistent'
        with self.assertRaisesRegex(ValueError, 'UNOWNED_SERVICE'):
            compile_portrait(self.context)

    def test_forty_degree_actuator_command_is_not_a_comfort_preference(self):
        self.context['declared_thermostats'] = [{'setback_setpoint_C': 40}]
        p = compile_portrait(self.context)
        self.assertEqual(p['declared_thermostats'], self.context['declared_thermostats'])
        self.assertNotIn('40', p['attitude']['thermal'])
        self.assertNotIn('40℃', render_portrait(p, self.context['days'][0]['date']))

    def test_adapter_ignores_B_outcomes_and_answers(self):
        c = self.context; day = c['days'][0]; date = day['date']
        aid = next(d['asset_id'] for d in c['devices'] if 'washer' in d['types'])
        need = dict(need_id=date + ':W-test', asset_id=aid, kind='washer', release_min=1000,
                    deadline_min=2520, quantity=3, unit='kg')
        profile = dict(household_id=c['household_id'], members=c['members'], devices=c['devices'])
        packet = dict(date=date, household_id=c['household_id'], context=dict(days=[day], needs={'A': [need], 'B': []}),
                      plans={'A': {'tasks': [], 'operations': []}, 'B': {}}, outcomes={}, answers={})
        before = from_reference(profile, [packet], 'A')
        packet['plans']['B'] = {'bad': 'data'}; packet['context']['needs']['B'] = ['arbitrary']
        packet['outcomes'] = {'accept': True}; packet['answers'] = {'score': 5}
        self.assertEqual(before, from_reference(profile, [packet], 'A'))
        self.assertEqual(before['services'][0]['deadline_at'][:10], at(date, 2520)[:10])

    def test_care_and_room_use_references_are_copied_not_invented(self):
        p = compile_portrait(self.context)
        self.assertIn('childcare_supervision', {e['activity'] for e in p['calendar_protections']})
        for d in p['devices']:
            for e in d['room_use_references']:
                self.assertEqual(e['room_id'], d['room_id'])
                day = next(x for x in self.context['days'] if x['date'] == e['date'])
                self.assertIn({k: v for k, v in e.items() if k not in ('date', 'member_id')}, day['calendars'][e['member_id']])

    def test_batch_has_all_six_roles_and_preserves_all_requested_slots(self):
        with tempfile.TemporaryDirectory() as td:
            r = build_portraits(FIXTURE, Path(td) / 'out')
            self.assertEqual((r['requested'], r['compiled'], r['EP_runs']), (7, 7, 0))
            self.assertEqual(sum(len(x['dates']) for x in r['records']), 9)
            self.assertEqual(set(r['role_counts']), set('ABCDEF'))
            self.assertTrue(verify(Path(td) / 'out')['passed'])


if __name__ == '__main__':
    unittest.main()
