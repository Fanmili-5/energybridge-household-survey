import copy
import tempfile
import unittest
from pathlib import Path
from benchmark.ab_generation.common import bound, digest, read, save, seal, verify
from benchmark.ab_generation.generate import binding, generate
from benchmark.ab_generation.model import apply, plan_commands, plan_hash, program_issues

HERE = Path(__file__).parent


class GenerationTests(unittest.TestCase):
    def setUp(self):
        self.context = read(HERE / 'examples/family.json')

    def refresh(self):
        self.context['reference']['binding'] = binding(self.context)

    def test_generation_preserves_input_and_is_deterministic(self):
        before = copy.deepcopy(self.context)
        first = generate(self.context)
        self.assertEqual(first, generate(self.context))
        self.assertEqual(before, self.context)
        self.assertTrue(first['candidates'])
        self.assertFalse(first['final_B_outcomes_used_for_selection'])

    def test_changed_A_or_weather_invalidates_reference(self):
        for field in ('A', 'source'):
            c = copy.deepcopy(self.context)
            if field == 'A':
                c['A']['tasks'][0]['start_min'] += 10
            else:
                c['source']['weather'] = 'another weather'
            with self.assertRaisesRegex(ValueError, 'STALE_A_REFERENCE'):
                generate(c)

    def test_automatic_combo_moves_complete_program_chain(self):
        result = generate(self.context)
        for row in result['candidates']:
            if row['family'] != 'washer':
                continue
            plan = apply(self.context['A'], row['patches'])
            ts = {t['kind']: t for t in plan['tasks'] if t['need_id'].startswith('wash')}
            self.assertEqual(ts['washer']['end_min'], ts['dryer']['start_min'])
            self.assertEqual(90, ts['dryer']['end_min'] - ts['dryer']['start_min'])

    def test_timer_keeps_manual_actions(self):
        for row in generate(self.context)['candidates']:
            if row['family'] == 'washer' and row['factors']['handling_mode'] == 'timer_only':
                self.assertEqual(plan_commands(self.context['A'])['operations'], apply(self.context['A'], row['patches'])['operations'])

    def test_operator_unavailable_remains_recorded(self):
        self.context['operator_windows'] = {'p1': [[540, 550], [1020, 1030], [1110, 1120], [1260, 1270]]}
        self.refresh()
        result = generate(self.context)
        bad = [r for r in result['candidates'] if 'OPERATOR_UNAVAILABLE' in r['static_issues']]
        self.assertTrue(bad)
        chosen = {i for s in result['selections'].values() for i in s['candidate_ids']}
        self.assertFalse(chosen & {r['id'] for r in bad})

    def test_factorial_thermal_doses_and_restoration(self):
        rows = [r for r in generate(self.context)['candidates'] if r['family'] == 'ac']
        self.assertEqual({(.5, 20), (.5, 60), (1., 20), (1., 60)}, {(r['factors']['setpoint_delta_C'], r['factors']['requested_duration_min']) for r in rows})
        for row in rows:
            b = apply(self.context['A'], row['patches'])
            for t in range(480, 1440, 10):
                old = next(c for c in self.context['A']['controls'] if c['asset_id'] == 'ac' and c['start_min'] <= t < c['end_min'])
                new = next(c for c in b['controls'] if c['asset_id'] == 'ac' and c['start_min'] <= t < c['end_min'])
                self.assertEqual(old['fan_operating_mode'], new['fan_operating_mode'])
                if not any(p['start_min'] <= t < p['end_min'] for p in row['patches']):
                    self.assertEqual(old['heating_setpoint_C'], new['heating_setpoint_C'])
                    self.assertEqual(old['cooling_setpoint_C'], new['cooling_setpoint_C'])

    def test_missing_current_reference_does_not_reuse_old_forecast(self):
        self.context['reference']['thermal'] = {}
        result = generate(self.context)
        self.assertFalse([r for r in result['candidates'] if r['family'] in ('ac', 'water_heater')])
        self.assertEqual(2, sum(r['reason'] == 'CURRENT_A_THERMAL_REFERENCE_UNAVAILABLE' for r in result['unavailable']))

    def test_no_thermal_opportunity_from_idle_or_empty_room(self):
        self.context['occupancy'] = {}
        self.refresh()
        result = generate(self.context)
        self.assertFalse([r for r in result['candidates'] if r['family'] == 'ac'])

    def test_ev_keeps_original_physical_connection_and_no_idle_tail_claim(self):
        result = generate(self.context)
        for row in result['candidates']:
            if row['family'] == 'ev':
                plan = copy.deepcopy(self.context['A'])
                for c in plan['controls']:
                    c['_ab_control_id'] = digest(c)
                b = apply(plan, row['patches'])
                self.assertEqual(plan_commands(plan)['operations'], b['operations'])
                old = next(c for c in plan['controls'] if c['asset_id'] == 'ev')
                new = next(c for c in b['controls'] if c['asset_id'] == 'ev')
                self.assertEqual(old['end_min'], new['end_min'])
        self.context['reference']['ev_charging_steps'] = []
        self.assertFalse([r for r in generate(self.context)['candidates'] if r['family'] == 'ev'])

    def test_identical_and_given_failure_assignments_are_preserved(self):
        self.context['assignment']['mode'] = 'identical_control'
        self.refresh()
        for s in generate(self.context)['selections'].values():
            self.assertEqual(plan_hash(self.context['A']), s['B_commands_sha256'])
        self.context['assignment']['mode'] = 'preserved_failure_replay'
        broken = copy.deepcopy(self.context['A'])
        broken['operations'][1]['start_min'] = 700
        self.context['retained_B_request'] = broken
        self.refresh()
        for s in generate(self.context)['selections'].values():
            self.assertEqual(plan_hash(broken), s['B_commands_sha256'])
            self.assertEqual('original_failure_request_preserved', s['status'])

    def test_partial_tariff_disables_cost_comparison(self):
        self.context['tariff'] = self.context['tariff'][:1]
        self.refresh()
        result = generate(self.context)
        self.assertEqual('no_comparable_opportunity', result['selections']['known_profile_cost']['status'])

    def test_unknown_policy_and_ambiguous_controls_are_rejected(self):
        with self.assertRaisesRegex(ValueError, 'UNKNOWN_SELECTION_POLICY'):
            generate(self.context, {'selection_policies': ['acceptance']})
        self.context['A']['controls'].append(copy.deepcopy(self.context['A']['controls'][0]))
        self.refresh()
        with self.assertRaisesRegex(ValueError, 'OVERLAPPING_BASELINE_CONTROLS'):
            generate(self.context)

    def test_content_hashes_and_path_confinement(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            save(root / 'one.json', {'a': 1})
            seal(root, {'schema': 'test'})
            verify(root)
            save(root / 'one.json', {'a': 2})
            with self.assertRaisesRegex(ValueError, 'ARTIFACT_CHANGED'):
                verify(root)
            with self.assertRaisesRegex(ValueError, 'RESOURCE_OUTSIDE_ROOT'):
                bound(root, '../outside.json')

    def test_batch_uses_new_directory_and_checks_case_identity(self):
        from benchmark.ab_generation.__main__ import build_batch
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            result = build_batch(HERE / 'examples/batch.json', root / 'out')
            self.assertEqual(3, result['counts']['cases'])
            verify(root / 'out')
            with self.assertRaises(FileExistsError):
                build_batch(HERE / 'examples/batch.json', root / 'out')

    def test_program_shift_cannot_rewrite_executed_past(self):
        self.context['A']['operations'][0]['start_min'] = 450
        self.context['A']['operations'][0]['end_min'] = 460
        self.refresh()
        result = generate(self.context)
        moved = [r for r in result['candidates'] if r['family'] == 'washer' and r['factors']['handling_mode'] == 'shift_chain']
        self.assertTrue(moved)
        self.assertTrue(all('CHANGES_PREDECISION_HANDLING' in r['static_issues'] for r in moved))

    def test_joint_operator_conflict_is_detected_without_repair(self):
        plan = copy.deepcopy(self.context['A'])
        wash = next(o for o in plan['operations'] if o['operation_id'] == 'unload')
        dishes = next(o for o in plan['operations'] if o['operation_id'] == 'dload')
        dishes['start_min'], dishes['end_min'] = wash['start_min'], wash['end_min']
        before = copy.deepcopy(plan)
        self.assertIn('OPERATOR_DOUBLE_BOOKED', program_issues(self.context, plan, 'wash'))
        self.assertEqual(before, plan)

    def test_unknown_rule_keys_and_unknown_rows_are_rejected(self):
        with self.assertRaisesRegex(ValueError, 'UNKNOWN_RULE_KEYS'):
            generate(self.context, {'unknown_parameter': 1})
        with self.assertRaisesRegex(ValueError, 'PATCH_ADDS_UNKNOWN_ROW'):
            apply(self.context['A'], [{'type': 'rows', 'collection': 'tasks', 'identity': 'task_id',
                                       'rows': [{'task_id': 'invented'}]}])

    def test_legacy_cooling_alias_matches_the_requested_setpoint(self):
        for c in self.context['A']['controls']:
            if c['kind'] == 'ac_setpoint':
                c['value_C'] = c['cooling_setpoint_C']
        self.refresh()
        rows = [r for r in generate(self.context)['candidates'] if r['family'] == 'ac' and r['factors']['thermal_axis'] == 'cooling']
        self.assertTrue(rows)
        for row in rows:
            for c in apply(self.context['A'], row['patches'])['controls']:
                if c['kind'] == 'ac_setpoint':
                    self.assertEqual(c['cooling_setpoint_C'], c['value_C'])


if __name__ == '__main__':
    unittest.main()
