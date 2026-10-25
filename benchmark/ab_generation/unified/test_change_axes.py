import copy
import unittest
from pathlib import Path

from ..common import read, digest
from .change_axes import VERSION, annotate, describe, labels, presentation, thermal_timing, time_band
from .contract import config, entry_config
from .candidates import prepare, catalogue_domains, generate_day
from .selection import concepts, goals, select_block


EVENT = dict(start_min=1080, end_min=1140)


def thermal(start=1090, split=1100, end=1140, direction='aligned'):
    context = dict(A=dict(tasks=[], operations=[], controls=[dict(asset_id='ac', kind='ac_setpoint',
        start_min=0, end_min=2000, cooling_setpoint_C=25.5, heating_setpoint_C=20.)]))
    component = dict(family='ac', asset_id='ac', mechanism='precondition_and_relax',
        relative_level='small_relative', absolute_level='small',
        magnitude=dict(axis='cooling', direction=direction, precondition_min=split-start,
            duration_min=end-split, ac_intervention=dict(max_comparable_setpoint_delta_C=.5,
            cooling_stop_requested_min=0, state_change='unchanged')),
        patches=[dict(type='control_interval', asset_id='ac', kind='ac_setpoint', start_min=a, end_min=z,
            values={'cooling_setpoint_C': value}) for a, z, value in
            ((start, split, 25. if direction == 'aligned' else 26.), (split, end, 26. if direction == 'aligned' else 25.))])
    return context, component


class SeparateActionAxesTests(unittest.TestCase):
    def test_time_bands_have_explicit_units_and_no_small_label(self):
        for value, expected in ((0, 'unchanged'), (10, 'up_to_30_min'), (30, 'up_to_30_min'),
                (40, 'over_30_to_60_min'), (120, 'over_60_to_120_min'), (121, 'over_120_min'),
                (460, 'over_120_min'), (-780, 'over_120_min'), (None, 'unknown')):
            self.assertEqual(expected, time_band(value))

    def test_invalid_minutes_and_stale_presentation_band_cannot_hide_hours(self):
        for value in (True, float('nan'), float('inf')):
            with self.assertRaisesRegex(ValueError, 'INVALID_ACTION_MINUTES'):
                time_band(value)
        c = dict(A=dict(operations=[]))
        a = describe(c, dict(family='washer', magnitude=dict(signed_machine_shift_min=460), patches=[]), EVENT)
        a['machine']['time_band'] = 'up_to_30_min'
        self.assertEqual('over_120_min', labels(a)['machine_shift'])
        self.assertEqual('over_240_min', time_band(460, [60, 120, 240]))

    def test_machine_and_handling_are_not_one_mixed_dose(self):
        c = dict(A=dict(operations=[dict(operation_id='load', start_min=100, end_min=110),
                                    dict(operation_id='unload', start_min=230, end_min=240)]))
        r = dict(family='washer', magnitude=dict(signed_machine_shift_min=-10),
            patches=[dict(type='rows', collection='operations', rows=[dict(operation_id='load', kind='load', start_min=20, end_min=30),
                dict(operation_id='unload', kind='unload', start_min=440, end_min=450)])])
        a = describe(c, r, EVENT)
        self.assertEqual('up_to_30_min', a['machine']['time_band'])
        self.assertEqual('over_120_min', a['handling']['time_band'])
        self.assertEqual(290, a['handling']['sum_absolute_retime_min'])
        self.assertEqual(0, a['handling']['active_duration_delta_min'])
        self.assertEqual(0, a['handling']['additional_operation_count'])
        self.assertIsNone(a['handling']['experienced_burden'])

    def test_several_hour_machine_shift_is_not_small(self):
        c = dict(A=dict(operations=[]))
        r = dict(family='washer', magnitude=dict(signed_machine_shift_min=460), patches=[])
        a = describe(c, r, EVENT)
        self.assertEqual('over_120_min', labels(a)['machine_shift'])
        self.assertEqual('unchanged', labels(a)['handling_retime'])

    def test_event_internal_preparation_is_not_before_vpp(self):
        c, r = thermal()
        original = copy.deepcopy(r['patches'])
        annotate(c, r, EVENT)
        a = r['change_axes']['thermal']['timing']
        self.assertEqual(0, a['pre_event_preparation_min'])
        self.assertEqual(10, a['in_event_preparation_min'])
        self.assertEqual('in_event_preparation', a['phase'])
        self.assertEqual('in_event_prepare_and_relax', r['mechanism'])
        self.assertFalse(a['before_event_cooling_request'])
        self.assertEqual(0, r['magnitude']['precondition_min'])
        self.assertEqual(10, r['magnitude']['construction_lead_min'])
        self.assertEqual(original, r['patches'])
        self.assertIn('VPP内首阶段调节10分钟', presentation(r))
        self.assertNotIn('VPP前', presentation(r))

    def test_pre_event_preparation_and_half_open_boundary(self):
        c, r = thermal(1070, 1080, 1120)
        t = thermal_timing(c, r, EVENT)
        self.assertEqual((10, 0), (t['pre_event_preparation_min'], t['in_event_preparation_min']))
        self.assertTrue(t['before_event_cooling_request'])

    def test_cross_boundary_preparation_is_split(self):
        c, r = thermal(1070, 1090, 1140)
        t = thermal_timing(c, r, EVENT)
        self.assertEqual((10, 10), (t['pre_event_preparation_min'], t['in_event_preparation_min']))
        self.assertEqual('crosses_event_start_preparation', t['phase'])

    def test_unchanged_first_phase_does_not_manufacture_preparation(self):
        c, r = thermal(1070, 1080, 1120)
        r['patches'][0]['values']['cooling_setpoint_C'] = 25.5
        t = thermal_timing(c, r, EVENT)
        self.assertEqual(0, t['pre_event_preparation_min'])
        self.assertEqual('no_changed_preparation', t['phase'])

    def test_opposing_request_is_not_called_pre_cooling(self):
        c, r = thermal(1070, 1080, 1120, 'opposing')
        t = thermal_timing(c, r, EVENT)
        self.assertFalse(t['before_event_cooling_request'])
        self.assertEqual('opposing_threshold_request', t['preparation_kind'])

    def test_fallback40_is_state_not_temperature_amplitude(self):
        c, r = thermal()
        r['mechanism'] = 'event_cooling_stop_fallback'
        r['patches'] = [dict(type='control_interval', asset_id='ac', kind='ac_setpoint',
            start_min=1080, end_min=1090, values={'cooling_setpoint_C':40.})]
        r['magnitude']['ac_intervention']['cooling_stop_requested_min'] = 10
        annotate(c, r, EVENT)
        self.assertIsNone(r['change_axes']['thermal']['comparable_setpoint_delta_C'])
        self.assertEqual('not_comparable_state_change', labels(r['change_axes'])['temperature_delta'])
        self.assertFalse(r['change_axes']['thermal']['availability_off_proved'])

    def test_permission_pause_not_actual_runtime(self):
        c = dict(A=dict(operations=[]))
        r = dict(family='ev', magnitude={'pause_min':260}, patches=[dict(type='control_pause', start_min=1020, end_min=1280)])
        a = describe(c, r, EVENT)
        self.assertEqual('over_120_min', labels(a)['permission_pause'])
        self.assertTrue(a['charging_permission']['not_actual_charger_runtime'])
        self.assertIsNone(a['machine']['signed_start_shift_min'])

    def test_component_annotation_is_idempotent_and_read_only(self):
        c, r = thermal()
        before = digest(c)
        annotate(c, r, EVENT)
        first = copy.deepcopy(r)
        annotate(c, r, EVENT)
        self.assertEqual(first, r)
        self.assertEqual(before, digest(c))

    def test_new_selector_rejects_unannotated_legacy_rows(self):
        from .test_joint_order_selection import row
        with self.assertRaisesRegex(ValueError, 'REQUIRES_SEPARATE_ACTION_AXES'):
            select_block([row(1,'date','id')], entry_config())


class CurrentGrammarIntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        c = read(Path(__file__).parents[1] / 'examples/control.json')
        c['reference']['thermal'] = {}
        c['reference']['information_set']['mode'] = 'offline_unexecuted_A_plan'
        device = next(d for d in c['devices'] if 'ac' in d['types'])
        c['devices'] = [device]
        c['needs'] = []
        c['A']['tasks'] = []; c['A']['operations'] = []
        c['A']['controls'] = [r for r in c['A']['controls'] if r['asset_id'] == device['asset_id']]
        cls.c = c

    def test_native_literal_commands_retained_with_separate_factor_cells(self):
        c = self.c
        old = config(dict(method_revision='delivery_v2_10', selection_joint_order='exact_witnessed_v1'))
        new = {**old, 'method_revision':'delivery_v2_11'}
        a = catalogue_domains(prepare(c, old), old)
        b = catalogue_domains(prepare(c, new), new)
        self.assertEqual({r['id'] for vs in a['values'] for r in vs if r}, {r['id'] for vs in b['values'] for r in vs if r})
        self.assertTrue(any(r['change_axes']['thermal']['timing']['in_event_preparation_min'] for vs in b['values'] for r in vs if r))
        self.assertTrue(all('small_relative' not in d['label'] for ds in b['descriptors'] for d in ds))

    def test_actual_request_selector_and_questionnaire_receive_axes(self):
        from .materials import project
        cfg = {**entry_config(), 'rows_per_unit':1, 'queries_per_row':2, 'oracle_native_encoding_budget':64}
        before = digest(self.c)
        generated = generate_day(self.c, cfg)
        self.assertTrue(generated['rows'])
        for r in generated['rows']:
            self.assertEqual(VERSION, r['change_axes_version'])
            view = concepts(r, 'exact_witnessed_v1')
            self.assertTrue(any('temperature_delta=' in t for t in view['tokens']))
            self.assertFalse(any('dose=small_relative' in t for t in view['tokens']))
            p = project(self.c, None, r, self.c['A'])
            self.assertTrue(p['action_changes'])
        self.assertEqual('assigned', select_block(generated['rows'], cfg)['status'])
        self.assertEqual(before, digest(self.c))


if __name__ == '__main__':
    unittest.main()
