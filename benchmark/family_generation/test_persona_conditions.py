import copy
import unittest

from .core import HERE, read, digest
from .device_persona import generate_personas
from .decision_conditions import contract_input
from .validate_device_personas import behavior_signature
from .portrait_inputs import from_formal


class ConditionTests(unittest.TestCase):
    def setUp(self):
        self.a, self.b = copy.deepcopy(read(HERE / 'examples/energy_portrait/current_two.json')['households'])

    def device(self, c, kind):
        return next(d for d in generate_personas(c)['devices'] if d['kind'] == kind)

    def test_care_burden_is_bound_to_qualified_person_not_household_boolean(self):
        d = self.device(self.a, 'washer'); f = d['decision_conditions']
        self.assertEqual(sorted(f['care_minutes_by_operator'].values()), [400, 3650])
        self.assertIn('KEEP_HANDLER_AVOID_CARE_TRANSFER', d['rule_ids'])
        # If the more-burdened adult lacks this device right, their household
        # presence must not select the substitute-care tradeoff for this device.
        aid = d['asset_id']; primary = f['registered_operator_id']
        self.a['asset_authority']['assets'][aid]['authorized_operator_ids'] = [primary]
        d = self.device(self.a, 'washer')
        self.assertNotIn('KEEP_HANDLER_AVOID_CARE_TRANSFER', d['rule_ids'])
        self.assertIn('PROTECT_HANDLER_CARE', d['rule_ids'])

    def test_no_age_or_gender_prediction_of_care(self):
        before = self.device(self.b, 'washer')
        for m in self.b['members']: m['age_years'] = 80; m['sex'] = 'unknown'
        after = self.device(self.b, 'washer')
        self.assertEqual(before['conditional_preferences'], after['conditional_preferences'])
        self.assertEqual(set(after['decision_conditions']['care_minutes_by_operator'].values()), {0})

    def test_counterfactual_calendar_changes_rule_not_only_wording(self):
        before = behavior_signature(generate_personas(self.a))
        for day in self.a['habit_days']:
            for cal in day['calendars'].values():
                for e in cal:
                    if e['activity'] in ('childcare_supervision', 'child_bathing_assistance'): e['activity'] = 'home_free_activity'
        self.assertNotEqual(before, behavior_signature(generate_personas(self.a)))
        self.assertNotIn('KEEP_HANDLER_AVOID_CARE_TRANSFER', self.device(self.a, 'washer')['rule_ids'])

    def test_A_commands_and_derived_handling_cannot_leak_through_contracts(self):
        before = generate_personas(self.a)
        for c in self.a['declared_service_contracts']:
            c.update(load_min=-999, unload_min=999999, program_start_uses_given_timer='mutated',
                     baseline_tasks='mutated', outcome='mutated')
        self.a.update(A='mutated', B='mutated', answers='mutated', impact='mutated')
        self.assertEqual(before, generate_personas(self.a))

    def test_same_equipment_can_have_different_journey_and_room_priorities(self):
        self.assertIn('EV_NONCOMMUTE_DECLARED_TRIPS', self.device(self.a, 'ev')['rule_ids'])
        self.assertIn('EV_WORK_AND_OTHER_TRIPS', self.device(self.b, 'ev')['rule_ids'])
        a = generate_personas(self.a); b = generate_personas(self.b)
        self.assertTrue(any('PROTECT_ROOM_WORK' in d['rule_ids'] for d in a['devices']))
        self.assertFalse(any('PROTECT_ROOM_WORK' in d['rule_ids'] for d in b['devices']))

    def test_current_replacement_dates_are_bound(self):
        dates = generate_personas(self.b)['bindings']['calendar_dates']
        self.assertTrue({'2025-01-15', '2025-10-18', '2025-12-29'} <= set(dates))
        self.assertTrue({'2025-02-06', '2025-03-25', '2025-05-16'}.isdisjoint(dates))

    def test_formal_adapter_does_not_read_plan_or_physical_fields(self):
        devices = copy.deepcopy(self.a['devices'])
        for d in devices: d['operator_id'] = self.a['asset_authority']['assets'][d['asset_id']]['registered_operator_id']
        contexts = [{'household_id':self.a['household_id'], 'date':day['date'], 'devices':devices,
            'authority':self.a['asset_authority'], 'operator_windows':day['operator_windows'],
            'needs':[n for n in self.a['declared_service_contracts'] if n['source_date']==day['date']]} for day in self.a['habit_days']]
        profile = {'household_id':self.a['household_id'], 'members':self.a['members'], 'devices':devices, 'role_policy':self.a['existing_policy']}
        before = from_formal(profile, self.a['habit_days'], 'A', contexts)
        for c in contexts: c.update(A='changed', B='changed', reference='changed', outcomes='changed', answers='changed')
        self.assertEqual(before, from_formal(profile, self.a['habit_days'], 'A', contexts))

    def test_tank_and_heating_have_explicit_actions_but_no_invented_authority(self):
        self.a['role'] = 'D'; self.a['existing_policy']['permissions'].update(automatic_within_declared_bounds=True, confirmation_before_action=False)
        water = self.device(self.a, 'water_heater')['authorization']
        ac = self.device(self.a, 'ac')['authorization']
        self.assertIn('change_tank_setpoint_preserving_draw_service', water['proposal_actions'])
        self.assertNotIn('change_tank_setpoint_preserving_draw_service', water['standing_consent_actions'])
        self.assertIn('change_heating_setpoint', ac['proposal_actions'])
        self.assertNotIn('change_heating_setpoint', ac['standing_consent_actions'])
        self.assertIsNone(ac['bounds']['heating_change_numeric_bound'])

    def test_target_or_program_declaration_does_not_grant_automation(self):
        self.b['role'] = 'F'; self.b['existing_policy'] = {'permissions': {'automatic_within_declared_bounds': True}}
        aid = self.device(self.b, 'ev')['asset_id']
        self.b['declared_device_settings'][aid] = {'target_soc': .85}
        self.assertFalse(self.device(self.b, 'ev')['authorization']['standing_consent_actions'])

    def test_invalid_explicit_bound_is_diagnostic_not_unlimited_permission(self):
        self.b['existing_policy']['service_policy']['reschedule_limit_min'] = -1
        with self.assertRaisesRegex(ValueError, 'INVALID_EXPLICIT_ACTION_BOUND'):
            generate_personas(self.b)

    def test_same_asset_id_is_not_automatic_transfer_capability(self):
        self.assertIn('AUTOMATIC_COMBO_CHAIN', self.device(self.a, 'washer')['rule_ids'])
        for n in self.a['declared_service_contracts']: n.pop('wash_only_delivery', None)
        self.assertNotIn('AUTOMATIC_COMBO_CHAIN', self.device(self.a, 'washer')['rule_ids'])
        self.assertIn('SAME_ASSET_CHAIN_UNSPECIFIED_HANDLING', self.device(self.a, 'washer')['rule_ids'])

    def test_signature_ignores_prose_numeric_bounds_ids_and_raw_times(self):
        p = generate_personas(self.a); before = behavior_signature(p)
        for d in p['devices']:
            d['asset_id'] = 'other'; d['habit'] = 'synonyms'
            d['authorization']['bounds'] = {'invented': 1234}
            d['decision_conditions'] = {'raw_times': [1, 2, 3]}
        self.assertEqual(before, behavior_signature(p))

    def test_bad_rights_fail_explicitly_without_adult_fallback(self):
        aid = self.device(self.a, 'washer')['asset_id']
        self.a['asset_authority']['assets'][aid]['authorized_operator_ids'] += ['undeclared_helper']
        with self.assertRaisesRegex(ValueError, 'UNKNOWN_OPERATOR'):
            generate_personas(self.a)

    def test_other_adults_free_time_never_substitutes_for_device_operator(self):
        d = self.device(self.b, 'washer'); aid = d['asset_id']; primary = d['decision_conditions']['registered_operator_id']
        self.b['asset_authority']['assets'][aid]['authorized_operator_ids'] = [primary]
        for day in self.b['habit_days']: day['operator_windows'][primary] = []
        after = self.device(self.b, 'washer')
        self.assertIn('NO_DECLARED_HANDLING_WINDOW', after['rule_ids'])
        self.assertNotIn('FIT_BOTH_HANDLING_WINDOWS', after['rule_ids'])
        self.assertEqual(after['context_features']['qualified_operator_ids_with_declared_windows'], [])

    def test_existing_external_helper_is_not_added_to_household(self):
        aid = self.device(self.b, 'washer')['asset_id']; ext = 'declared_external_helper'
        self.b['external_operator_ids'] = [ext]
        self.b['asset_authority']['assets'][aid]['authorized_operator_ids'] += [ext]
        for day in self.b['habit_days']: day['operator_windows'][ext] = [[600, 620]]
        before = digest(self.b['members']); p = generate_personas(self.b)
        self.assertEqual(before, digest(self.b['members']))
        self.assertEqual(p['context_evidence']['adult_count'], 2)
        d = next(d for d in p['devices'] if d['kind'] == 'washer')
        self.assertIn('EXISTING_VISIT_WINDOWS_ONLY', d['rule_ids'])
        self.assertIsNone(d['decision_conditions']['care_minutes_by_operator'][ext])


if __name__ == '__main__': unittest.main()
