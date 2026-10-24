"""Counterexamples for household precedence, member scope and consent safety."""
import copy
import unittest

from .core import HERE, digest, read
from .device_persona import generate_personas, preference_input, render_family
from .household_preferences import SOURCES, S4


class HouseholdPreferenceTests(unittest.TestCase):
    def setUp(self):
        examples = read(HERE / 'examples/energy_portrait/input.json')['households']
        self.c = copy.deepcopy(next(c for c in examples if c['role'] == 'F'))
        self.c['energy_preferences'] = {'EB_household_id': S4}
        self.holder = self.c['existing_policy']['holder']['person_id']
        self.other = next(m['member_id'] for m in self.c['members'] if m['member_id'] != self.holder)
        self.c['asset_authority'] = {'assets': {
            d['asset_id']: {'authorized_operator_ids': [self.holder, self.other],
                            'registered_operator_id': self.other if 'washer' in d['types'] else self.holder}
            for d in self.c['devices']}}

    def test_shared_portfolio_does_not_add_or_delete_owned_assets(self):
        before = digest(self.c)
        p = generate_personas(self.c)
        self.assertEqual({(d['asset_id'], k) for d in self.c['devices'] for k in d['types']},
                         {(d['asset_id'], d['kind']) for d in p['devices']})
        self.assertEqual(before, digest(self.c))
        self.assertFalse(p['household_preferences']['original_household_members_copied'])
        for m in p['household_preferences']['member_profiles']:
            self.assertNotIn('schedule', m['tags'])
            self.assertTrue(m['appliance_fields_are_preference_references_not_personal_ownership'])

    def test_explicit_household_preference_wins_over_personal_appliance_flags(self):
        self.c['role'] = 'B'
        w = next(d for d in generate_personas(self.c)['devices'] if d['kind'] == 'washer')
        self.assertFalse(w['sources']['EB_appliance_reference']['dr_adjustable'])
        self.assertTrue(w['sources']['EB_shared_appliance_reference']['dr_adjustable'])
        self.assertTrue(w['authorization']['routine_DR_eligible'])
        self.assertFalse(w['authorization']['standing_consent_actions'])
        self.assertIn('先说明并确认', w['authorization']['narrative'])

    def test_explicit_household_no_DR_is_not_erased_by_F_role(self):
        self.c['energy_preferences']['shared_appliances'] = {'washer': {'dr_adjustable': False}}
        w = next(d for d in generate_personas(self.c)['devices'] if d['kind'] == 'washer')
        self.assertFalse(w['authorization']['routine_DR_eligible'])
        self.assertFalse(w['authorization']['standing_consent_actions'])

    def test_member_objection_only_gates_affected_devices(self):
        self.c['energy_preferences']['member_personas'] = {self.other: 'basic_role_b_home_comfort_gated'}
        p = generate_personas(self.c)
        w = next(d for d in p['devices'] if d['kind'] == 'washer')
        ev = next(d for d in p['devices'] if d['kind'] == 'ev')
        self.assertIn(self.other, w['authorization']['member_confirmation_required_ids'])
        self.assertFalse(w['authorization']['standing_consent_actions'])
        self.assertNotIn(self.other, ev['authorization']['affected_member_ids'])
        self.assertIn('shift_charging_in_original_connection', ev['authorization']['standing_consent_actions'])

    def test_explicit_global_denial_cannot_be_granted_by_EB_auto_members(self):
        self.c['existing_policy']['permissions']['automatic_within_declared_bounds'] = False
        self.assertFalse(any(d['authorization']['standing_consent_actions'] for d in generate_personas(self.c)['devices']))

    def test_missing_action_bounds_stay_ungranted(self):
        p = generate_personas(self.c)
        for d in p['devices']:
            self.assertNotIn('change_heating_setpoint', d['authorization']['standing_consent_actions'])
            self.assertNotIn('change_tank_setpoint_preserving_draw_service', d['authorization']['standing_consent_actions'])

    def test_existing_program_habit_takes_precedence_over_EB_reference(self):
        washer = next(d['asset_id'] for d in self.c['devices'] if 'washer' in d['types'])
        self.c['declared_device_settings'] = {washer: {'program_policies': [
            {'kind': 'washer', 'preferred_start_min': {'weekday': 1117, 'weekend': 967}}]}}
        w = next(d for d in generate_personas(self.c)['devices'] if d['kind'] == 'washer')
        self.assertIn('18:37', w['habit'])
        self.assertIn('16:07', w['habit'])
        self.assertEqual(w['inherited_preferences']['habit_clock_origin'], 'original_declared_program_policy')

    def test_personality_is_not_assigned_from_sex_or_age(self):
        before = generate_personas(self.c)['household_preferences']
        for m in self.c['members']:
            m['sex'] = 'changed'
            m['age_years'] += 1
        self.assertEqual(before, generate_personas(self.c)['household_preferences'])

    def test_plan_changes_do_not_change_preferences(self):
        before = generate_personas(self.c)
        self.c['services'] = []; self.c['plans'] = {'A': 'changed', 'B': 'changed'}
        self.c['answers'] = 'changed'; self.c['outcomes'] = 'changed'
        self.assertEqual(before, generate_personas(self.c))
        self.assertNotIn('plans', preference_input(self.c))

    def test_holder_temperature_is_not_imposed_on_an_unused_room(self):
        asset = next(d for d in self.c['devices'] if 'ac' in d['types'])
        for day in self.c.get('habit_days', self.c['days']):
            for e in day['calendars'][self.holder]:
                if e.get('room_id') == asset['room_id']:
                    e['room_id'] = 'another_room'
        p = generate_personas(self.c)
        d = next(d for d in p['devices'] if d['asset_id'] == asset['asset_id'])
        self.assertNotIn(self.holder, d['authorization']['affected_member_ids'])
        self.assertEqual(d['authorization']['holder_member_id'], self.holder)

    def test_unknown_member_override_is_rejected_without_retry(self):
        self.c['energy_preferences']['member_personas'] = {'not_a_resident': 'atom_control_auto'}
        with self.assertRaisesRegex(ValueError, 'UNKNOWN_MEMBER_PREFERENCE_OWNER'):
            generate_personas(self.c)

    def test_sources_exclude_human_answer_priors(self):
        sources = read(SOURCES)
        for h in sources['households'].values():
            self.assertNotIn('preferences', h)
            self.assertNotIn('scoring_policy', h)
        self.assertEqual(len(sources['households']), 5)

    def test_brief_does_not_drop_member_preferences_or_per_device_consent(self):
        self.c['energy_preferences']['member_personas'] = {self.other: 'atom_price_indifferent'}
        p = generate_personas(self.c); text = render_family(p, brief=True)
        self.assertIn('小额节省不足以抵消额外麻烦', text)
        self.assertIn('充电改时', text)
        self.assertIn('属于本研究实验设定', text)


if __name__ == '__main__': unittest.main()
