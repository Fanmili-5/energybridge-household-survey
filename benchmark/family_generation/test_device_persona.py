import copy
from pathlib import Path
import tempfile
import unittest

from .core import HERE, digest, generate, read, save
from .device_persona import generate_personas, preference_input, render_family
from .energy_portrait import build_portraits, compile_portrait


class DevicePersonaTests(unittest.TestCase):
    def setUp(self):
        self.contexts = read(HERE / 'examples/energy_portrait/input.json')['households']
        self.a = copy.deepcopy(next(c for c in self.contexts if c['household_id'] == 'ordinary-v6-0653'))
        self.b = copy.deepcopy(next(c for c in self.contexts if c['household_id'] == 'ordinary-v6-0250'))

    def test_preferences_ignore_A_times_programs_operations_and_outcomes(self):
        before = generate_personas(self.a)
        for s in self.a['services']:
            s['baseline_tasks'] = [{'start_at': '1900-01-01T00:00', 'end_at': '2100-01-01T00:00'}]
            s['handling'] = [{'operator_id': 'different-person'}]
        self.a['plans'] = {'A': 'arbitrary', 'B': 'arbitrary'}
        self.a['VPP'] = {'start': 4}; self.a['answers'] = {'score': 5}
        self.a['outcomes'] = {'computed': True}; self.a['services'] = []
        self.assertEqual(before, generate_personas(self.a))

    def test_preference_projection_contains_no_selected_A_or_service_fields(self):
        p = preference_input(self.a)
        self.assertNotIn('services', p)
        self.assertNotIn('baseline_tasks', str(p))
        self.assertNotIn('handling', p)

    def test_same_household_keeps_same_profile_across_selected_days(self):
        p = generate_personas(self.a)
        self.a['days'] = self.a['days'][-1:]
        self.a['services'] = []
        self.assertEqual(p, generate_personas(self.a))
        self.assertEqual(len(p['bindings']['calendar_dates']), 10)

    def test_same_role_has_qualitative_device_differences_beyond_timing(self):
        x, y = generate_personas(self.a), generate_personas(self.b)
        self.assertEqual(x['attitude'], y['attitude'])
        wx = next(d for d in x['devices'] if d['kind'] == 'washer')
        wy = next(d for d in y['devices'] if d['kind'] == 'washer')
        self.assertIn('SAME_ASSET_CHAIN_UNSPECIFIED_HANDLING', wx['rule_ids'])
        self.assertIn('HANDLER_UNKNOWN', wx['rule_ids'])  # legacy snapshot lacks device rights
        self.assertIn('WASHED_NOT_WEARABLE', wy['rule_ids'])
        self.assertIn('HANDLER_UNKNOWN', wy['rule_ids'])
        self.assertNotEqual(wx['habit'], wy['habit'])

    def test_age_alone_does_not_create_care_or_diagnoses(self):
        for day in self.a['habit_days']:
            for cal in day['calendars'].values():
                for e in cal:
                    if e['activity'] in ('childcare_supervision', 'child_bathing_assistance'):
                        e['activity'] = 'home_free_activity'
        p = generate_personas(self.a)
        self.assertEqual(p['context_evidence']['minor_count'], 2)
        self.assertFalse(p['context_evidence']['care_references'])
        self.assertTrue(any(d['context_features']['child_rest_in_this_room'] for d in p['devices']))  # actual rest is still declared
        for day in self.a['habit_days']:
            for cal in day['calendars'].values():
                for e in cal:
                    if e['activity'] in ('day_nap', 'sleep_rest'): e['activity'] = 'home_free_activity'
        self.assertFalse(any(d['context_features']['child_rest_in_this_room'] for d in generate_personas(self.a)['devices']))

    def test_gender_does_not_assign_habits_or_handlers(self):
        before = generate_personas(self.a)
        for m in self.a['members']:
            m['sex'] = 'changed'
        after = generate_personas(self.a)
        self.assertEqual(before['devices'], after['devices'])

    def test_A_never_gets_automatic_execution_from_free_time(self):
        for c in (self.a, self.b):
            for d in generate_personas(c)['devices']:
                self.assertEqual(d['authorization']['mode'], 'confirm_each_proposal')
                self.assertEqual(d['authorization']['standing_consent_actions'], [])
                self.assertFalse(d['authorization']['automatic_execution_claimed'])

    def test_device_authorizations_have_different_action_scopes(self):
        rows = {d['kind']: d['authorization'] for d in generate_personas(self.a)['devices']}
        self.assertIn('move_bath', rows['water_heater']['requires_new_explicit_consent'])
        self.assertIn('lower_target_SOC', rows['ev']['requires_new_explicit_consent'])
        self.assertIn('V2G', rows['ev']['requires_new_explicit_consent'])
        self.assertIn('stop_occupied_room_without_separate_consent', rows['ac']['requires_new_explicit_consent'])
        self.assertIn('change_program_or_quantity', rows['washer']['requires_new_explicit_consent'])
        self.assertNotEqual(rows['ac']['proposal_actions'], rows['ev']['proposal_actions'])

    def test_household_eligibility_does_not_override_BCE_confirmation(self):
        for c in self.contexts:
            p = generate_personas(c)
            for d in p['devices']:
                auth = d['authorization']
                if c['role'] in 'BCE' and d['kind'] == 'washer':
                    self.assertFalse(auth['standing_consent_actions'])
                    self.assertEqual(d['sources']['EB_appliance_reference']['dr_adjustable'], False)
                    self.assertTrue(d['sources']['EB_shared_appliance_reference']['dr_adjustable'])
                if c['role'] == 'C':
                    self.assertTrue(auth['same_day_reconfirmation'])
                if c['role'] == 'E':
                    self.assertEqual(auth['mode'], 'advice_first_separate_confirmation')

    def test_free_time_does_not_turn_B_or_C_into_a_price_cooperative_A(self):
        for role in ('B', 'C', 'D', 'F'):
            c = copy.deepcopy(self.b); c['role'] = role
            w = next(d for d in generate_personas(c)['devices'] if d['kind'] == 'washer')
            self.assertNotIn('选省钱且方便', w['handling_preference'])
            if role == 'B':
                self.assertIn('优先维持既定生活节奏', w['adjustment_preference'])
            if role == 'C':
                self.assertIn('当天', w['authorization']['narrative'])

    def test_D_and_F_authority_needs_bounds_and_preserves_explicit_denial(self):
        c = copy.deepcopy(next(c for c in self.contexts if c['role'] == 'D'))
        c['existing_policy']['permissions']['automatic_within_declared_bounds'] = False
        for d in generate_personas(c)['devices']:
            self.assertFalse(d['authorization']['standing_consent_actions'])
        c['existing_policy'] = {'permissions': {'automatic_within_declared_bounds': True}}
        c['declared_device_settings'] = {}
        for d in generate_personas(c)['devices']:
            self.assertFalse(d['authorization']['standing_consent_actions'])

    def test_room_specific_preferences_follow_actual_rest_calendar(self):
        p = generate_personas(self.a)
        rooms = {d['room_id']: d for d in p['devices'] if d['kind'] == 'ac'}
        self.assertIn('PROTECT_CHILD_ROOM_REST', rooms['private_01']['rule_ids'])
        self.assertIn('PROTECT_CHILD_ROOM_REST', rooms['private_02']['rule_ids'])
        self.assertNotIn('PROTECT_CHILD_ROOM_REST', rooms['living_hall']['rule_ids'])
        self.assertIn('成员3', rooms['private_01']['room_label'])

    def test_missing_handling_opportunities_do_not_invent_flexibility(self):
        for day in self.b['habit_days']:
            day['operator_windows'] = {m['member_id']: [] for m in self.b['members']}
        w = next(d for d in generate_personas(self.b)['devices'] if d['kind'] == 'washer')
        self.assertIn('HANDLER_UNKNOWN', w['rule_ids'])
        self.assertIn('不能把任一成人空闲', w['handling_preference'])

    def test_bad_availability_is_retained_as_engineering_diagnostic(self):
        mid = self.a['members'][0]['member_id']
        self.a['habit_days'][0]['operator_windows'][mid] = [[0, 1440]]
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            save(root / 'input.json', {'schema': 'eb.energy_portrait.batch.v1', 'households': [self.a]})
            s = build_portraits(root / 'input.json', root / 'out')
            self.assertEqual((s['requested'], s['compiled']), (1, 0))
            self.assertIn('AVAILABILITY_OVERLAPS', s['records'][0]['reason'])

    def test_participant_text_actually_renders_habits_preferences_and_authorizations(self):
        p = compile_portrait(self.a)
        text = p['participant_family_text']
        for d in p['devices']:
            self.assertIn(d['habit'], text)
            self.assertIn(d['adjustment_preference'], text)
            self.assertIn(d['authorization']['narrative'], text)
        self.assertNotIn('既有A启动', text)
        self.assertIn('不是当天A的实际时间', text)
        self.assertIn('洗碗', p['participant_family_brief'])

    def test_sources_distinguish_EB_absent_devices_from_experimental_extension(self):
        p = generate_personas(self.a)
        for d in p['devices']:
            if d['kind'] in ('dryer', 'ev'):
                self.assertTrue(d['sources']['device_absent_from_basic_EB_persona_requires_extension'])
            self.assertIn('not_measured_or_inferred_from_A', d['sources']['habit_and_action_scope'])
            self.assertTrue(d['sources']['device_present_in_EB_household_reference'])
        self.assertFalse(p['acceptance_or_score_generated'])

    def test_family_stage_constructs_persona_before_any_A(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            s = generate(HERE / 'examples/batch.json', root / 'out')
            self.assertEqual(s['constructed'], 6)
            for r in s['records']:
                f = read(root / 'out' / r['path'])
                self.assertIn('energy_use_profile', f)
                self.assertFalse(f['energy_use_profile']['A_or_B_actions_read'])
                self.assertNotIn('A', f)
                self.assertIn('constructed_before_A', f['energy_portrait_status'])


if __name__ == '__main__':
    unittest.main()
