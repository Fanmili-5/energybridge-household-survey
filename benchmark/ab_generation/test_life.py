import copy
import datetime as dt
import tempfile
import unittest
from collections import Counter
from pathlib import Path
from benchmark.ab_generation.common import digest, read, save, seal, verify
from benchmark.ab_generation.generate import generate
from benchmark.ab_generation.generate import binding
from benchmark.ab_generation.life import generate_household
from benchmark.ab_generation.life_pipeline import build_life
from benchmark.ab_generation.model import apply, chain_need_ids, program_issues

HERE = Path(__file__).parent
EXAMPLES = HERE / 'examples/life'


class LifeTests(unittest.TestCase):
    def setUp(self):
        self.batch = read(EXAMPLES / 'life_batch.json')
        self.spec = copy.deepcopy(self.batch['households'][0])
        self.world = next(w for w in read(EXAMPLES / 'resource_worlds.json')['households'] if w['household_id'] == self.spec['household_id'])

    def plan(self):
        return generate_household(self.spec, self.world)

    def test_declared_life_produces_complete_repeatable_A(self):
        before = copy.deepcopy((self.spec, self.world))
        a = self.plan()
        self.assertEqual('A_constructed', a['status'])
        self.assertEqual(93, len(a['A']['tasks']))
        self.assertEqual(a, self.plan())
        self.assertEqual(before, (self.spec, self.world))
        self.assertFalse(a['B_events_prices_or_answers_used'])

    def test_downstream_information_is_rejected(self):
        for key in ('events', 'tariff', 'B', 'human_answers'):
            spec = copy.deepcopy(self.spec); spec[key] = []
            with self.assertRaisesRegex(ValueError, 'DOWNSTREAM_INFORMATION'):
                generate_household(spec, self.world)

    def test_no_hardcoded_household_identity(self):
        old, new = self.spec['household_id'], 'new-world-42'
        self.spec['household_id'] = new; self.world['household_id'] = new
        for m in self.world['members']:
            if m['household_id'] == old: m['household_id'] = new
        for r in self.world['rooms']:
            r['using_household_ids'] = [new if h == old else h for h in r['using_household_ids']]
        for d in self.world['devices']:
            d['using_household_ids'] = [new if h == old else h for h in d['using_household_ids']]
        self.assertEqual('A_constructed', self.plan()['status'])

    def test_identical_weekdays_preserve_habits(self):
        p = self.plan()
        def clock(date):
            base = (dt.date.fromisoformat(date) - dt.date.fromisoformat(p['anchor'])).days * 1440
            return [(t['kind'], t['start_min'] - base, t['end_min'] - base) for t in p['A']['tasks'] if base <= t['start_min'] < base + 1440]
        self.assertEqual(clock('2025-07-14'), clock('2025-07-15'))

    def test_dated_return_changes_only_the_declared_day(self):
        # The family fixture's arrival and matching journey are 20 minutes later.
        family = next(h for h in self.batch['households'] if h['household_id'] == 'example-family')
        world = next(w for w in read(EXAMPLES / 'resource_worlds.json')['households'] if w['household_id'] == 'example-family')
        p = generate_household(family, world)
        needs = {n['need_id']: n for n in p['requirements']}
        anchor = dt.date.fromisoformat(p['anchor'])
        releases = [(needs[d + ':laundry:0']['release_min'] - (dt.date.fromisoformat(d) - anchor).days * 1440) for d in ('2025-07-15', '2025-07-16', '2025-07-17')]
        self.assertEqual([1080, 1100, 1080], releases)

    def test_program_inventory_is_bounded_and_not_invented(self):
        self.spec['program_policies'][0]['daily_quantity_kg'] = 0
        p = self.plan()
        self.assertFalse([t for t in p['A']['tasks'] if t['kind'] in ('washer', 'dryer')])
        self.assertEqual(0, p['remaining_unallocated_textile_kg']['laundry'])

    def test_unsatisfied_services_are_retained_without_helpers(self):
        for template in self.spec['member_calendars'].values():
            for name in ('weekday', 'weekend'):
                for e in template[name]: e['available_for_operation'] = False
            for cal in template.get('date_overrides', {}).values():
                for e in cal: e['available_for_operation'] = False
        p = self.plan()
        self.assertEqual('needs_unserved', p['status'])
        self.assertTrue(p['unserved'])
        self.assertFalse(p['A']['tasks'])
        self.assertFalse(p['A']['operations'])
        self.assertGreater(p['remaining_unallocated_textile_kg']['laundry'], 0)

    def test_full_batch_policy_keeps_partial_inventory(self):
        self.spec['end_exclusive'] = '2025-07-11'
        self.spec['program_policies'][0]['daily_service'] = False
        p = self.plan()
        needs = [n for n in p['requirements'] if n['kind'] == 'washer']
        self.assertEqual([5, 5], [n['quantity'] for n in needs])
        self.assertAlmostEqual(2, p['remaining_unallocated_textile_kg']['laundry'])

    def test_dryer_uses_its_own_declared_deadline(self):
        child = next(p for p in self.spec['program_policies'] if p['kind'] == 'dryer')
        child['deadline_after_release_min'] = 10
        p = self.plan()
        needs = [n for n in p['requirements'] if n['kind'] == 'dryer']
        self.assertTrue(all(n['deadline_min'] - n['release_min'] == 10 for n in needs))
        self.assertTrue([t for t in p['A']['tasks'] if t['kind'] == 'washer'])
        self.assertFalse([t for t in p['A']['tasks'] if t['kind'] == 'dryer'])
        self.assertTrue(p['unserved'])

    def test_operator_permissions_are_not_inferred(self):
        for m in self.world['members']:
            m['can_operate_asset_ids'] = [a for a in m['can_operate_asset_ids'] if a != 'washer']
        p = self.plan()
        self.assertTrue(any(r['reason'] == 'NO_JOINT_LOAD_RUN_RETRIEVE' for r in p['unserved']))
        self.assertFalse([o for o in p['A']['operations'] if o['asset_id'] == 'washer'])

    def test_manual_resources_are_never_double_booked(self):
        p = self.plan()
        bookings = Counter((o['operator_id'], t) for o in p['A']['operations'] for t in range(o['start_min'], o['end_min'], 10))
        self.assertEqual(1, max(bookings.values()))

    def test_separate_dryer_requires_real_transfer(self):
        p = self.plan(); ops = {(o['need_id'], o['kind']): o for o in p['A']['operations']}
        for t in p['A']['tasks']:
            if t['kind'] == 'dryer':
                parent = t['depends_on_need_id']
                self.assertLessEqual(ops[(parent, 'unload')]['end_min'], ops[(t['need_id'], 'load')]['start_min'])
                self.assertNotEqual(ops[(parent, 'unload')]['asset_id'], t['asset_id'])

    def test_comfort_needs_are_independent_of_thermostat(self):
        a = self.plan()
        self.spec['thermostat_policies'][0]['cooling_setpoint_C'] = 27
        b = self.plan()
        self.assertEqual([n for n in a['requirements'] if n['kind'] == 'comfort'], [n for n in b['requirements'] if n['kind'] == 'comfort'])
        self.assertNotEqual(a['A']['controls'], b['A']['controls'])

    def test_empty_room_setback_and_given_hold(self):
        p = self.plan(); ac = next(d for d in self.world['devices'] if d['kind'] == 'ac')
        for c in p['A']['controls']:
            if c['asset_id'] == ac['asset_id'] and c['start_min'] <= 800 < c['end_min']:
                self.assertEqual(40, c['cooling_setpoint_C'])

    def test_known_anchor_connection_has_no_fictitious_visit(self):
        p = self.plan()
        first = p['EV']['connections'][0]
        self.assertEqual(0, first['start_min'])
        self.assertEqual('given_anchor_connection', first['origin'])
        self.assertFalse([o for o in p['A']['operations'] if o['kind'] == 'EV_plug' and o['start_min'] == 0])
        self.assertTrue(all(j['absolute_departure_min'] < j['absolute_arrival_min'] for j in p['EV']['journeys']))

    def test_EV_energy_and_unchanged_journey_contract(self):
        p = self.plan(); parameters = next(d['parameters'] for d in self.world['devices'] if d['kind'] == 'ev')
        final = dict(p['EV']['states'])[len(p['days']) * 1440]
        balance = parameters['initial_energy_kwh'] + sum(e['battery_kWh'] for e in p['EV']['charge_events']) - sum(j['traction_kWh'] for j in p['EV']['journeys'])
        self.assertAlmostEqual(final, balance, places=8)

    def test_EV_target_shortfall_is_not_hidden_by_minimum_reserve(self):
        ev = next(d for d in self.world['devices'] if d['kind'] == 'ev')
        ev['parameters']['initial_energy_kwh'] = 30
        ev['parameters']['charger_kw'] = .1
        p = self.plan()
        self.assertTrue(any(r['reason'] == 'EV_DEPARTURE_TARGET_SHORTFALL' for r in p['unserved']))

    def test_hot_water_demand_survives_missing_hardware(self):
        self.world['devices'] = [d for d in self.world['devices'] if d['kind'] != 'water_heater']
        p = self.plan()
        self.assertTrue(any(r['reason'] == 'HOT_WATER_REQUIREMENT_WITHOUT_TANK' for r in p['unserved']))
        self.assertTrue([n for n in p['requirements'] if n['kind'] == 'water_heater' and n['asset_id'] is None])

    def test_shared_residents_are_preserved(self):
        spec = next(h for h in self.batch['households'] if h['household_id'] == 'example-shared')
        world = next(w for w in read(EXAMPLES / 'resource_worlds.json')['households'] if w['household_id'] == 'example-shared')
        p = generate_household(spec, world)
        self.assertTrue(all('neighbor' in d['calendars'] for d in p['days'].values()))
        self.assertTrue(any(n.get('requester') == 'neighbor' for n in p['requirements']))

    def test_calendar_gaps_and_unknown_fields_are_rejected(self):
        self.spec['member_calendars']['adult1']['weekday'][0]['end_min'] = 410
        with self.assertRaisesRegex(ValueError, 'CALENDAR_GAP_OR_OVERLAP'):
            self.plan()
        self.spec = copy.deepcopy(self.batch['households'][0]); self.spec['future_information'] = {}
        with self.assertRaisesRegex(ValueError, 'UNKNOWN_LIFE_INPUT_FIELD'):
            self.plan()

    def test_nap_never_creates_an_operator_window(self):
        event = next(e for e in self.spec['member_calendars']['adult1']['weekday'] if e['available_for_operation'])
        event.update(activity='nap', room='$sleep')
        with self.assertRaisesRegex(ValueError, 'INVALID_HANDLING_AVAILABILITY'):
            self.plan()

    def test_batch_binds_world_bytes_and_output_is_immutable(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            build_life(EXAMPLES / 'life_batch.json', root / 'plans')
            verify(root / 'plans')
            with self.assertRaises(FileExistsError): build_life(EXAMPLES / 'life_batch.json', root / 'plans')
            batch = copy.deepcopy(self.batch); batch['worlds'] = {'path': 'worlds.json', 'sha256': '0' * 64}
            save(root / 'worlds.json', read(EXAMPLES / 'resource_worlds.json')); save(root / 'batch.json', batch)
            with self.assertRaisesRegex(ValueError, 'LIFE_WORLD_FILE_CHANGED'): build_life(root / 'batch.json', root / 'bad')

    def test_nested_manifests_are_content_bound(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp); save(root / 'child/MANIFEST.json', {'v': 1}); seal(root, {'schema': 'test'})
            verify(root); save(root / 'child/MANIFEST.json', {'v': 2})
            with self.assertRaisesRegex(ValueError, 'ARTIFACT_CHANGED'): verify(root)

    def context(self):
        p = self.plan()
        windows = {}
        for d in p['days'].values():
            for mid, spans in d['operator_windows'].items(): windows.setdefault(mid, []).extend(spans)
        c = {'schema': 'eb.ab_generation.context.v1', 'case_id': 'new-life-case', 'household_id': p['household_id'],
             'date': p['anchor'], 'decision_min': 480, 'horizon_min': [480, 1920], 'A': p['A'],
             'needs': p['requirements'], 'devices': self.world['devices'], 'operator_windows': windows,
             'occupancy': {}, 'reservations': [], 'events': [], 'tariff': [], 'source': {'world': p['world_sha256']}}
        c['reference'] = {'binding': binding(c), 'thermal': {}, 'ev_charging_steps': []}
        return c

    def test_B_shifts_separate_dryer_tasks_and_real_handling_together(self):
        c = self.context(); r = generate(c)
        washers = [x for x in r['candidates'] if x['family'] == 'washer']
        self.assertTrue(washers)
        for candidate in washers:
            nid = candidate['factors']['need_id']; ids = chain_need_ids(c['A'], nid)
            self.assertEqual(2, len(ids))
            b = apply(c['A'], candidate['patches'])
            for old in (t for t in c['A']['tasks'] if t['need_id'] in ids):
                new = next(t for t in b['tasks'] if t['task_id'] == old['task_id'])
                self.assertEqual(candidate['factors']['program_shift_min'], new['start_min'] - old['start_min'])
            if candidate['factors']['handling_mode'] == 'shift_chain':
                self.assertEqual(4, len(candidate['patches'][1]['rows']))

    def test_B_cannot_load_dryer_before_wet_clothes_are_retrieved(self):
        c = self.context(); plan = copy.deepcopy(c['A'])
        child = next(t for t in plan['tasks'] if t['kind'] == 'dryer')
        nid = child['depends_on_need_id']
        parent = next(o for o in plan['operations'] if o['need_id'] == nid and o['kind'] == 'unload')
        loading = next(o for o in plan['operations'] if o['need_id'] == child['need_id'] and o['kind'] == 'load')
        loading['start_min'], loading['end_min'] = parent['start_min'], parent['end_min']
        self.assertIn('PREREQUISITE_NOT_COLLECTED', program_issues(c, plan, nid))
        plan = copy.deepcopy(c['A'])
        plan['operations'] = [o for o in plan['operations'] if not (o['need_id'] == child['need_id'] and o['kind'] == 'load')]
        self.assertIn('INCOMPLETE_PROGRAM_CHAIN', program_issues(c, plan, nid))

    def test_physical_connection_rejects_missing_visits_and_trip_overlap(self):
        from benchmark.housing_simulation.kernel.execution import explicit_EV_connections
        p = self.plan()
        pack = {'anchor': p['anchor'], 'end_exclusive': p['end_exclusive'], 'operations': p['A']['operations'],
                'world': {'parameter_pack': {'devices': self.world['devices']}},
                'journeys': p['EV']['journeys'], 'EV_physical_connections': p['EV']['connections']}
        self.assertTrue(explicit_EV_connections(pack, 0))
        bad = copy.deepcopy(pack); bad['EV_physical_connections'][0]['asset_id'] = 'unknown_EV'
        with self.assertRaisesRegex(ValueError, 'ASSET_NOT_INSTALLED'): explicit_EV_connections(bad, 0)
        bad = copy.deepcopy(pack)
        bad['operations'] = [o for o in bad['operations'] if o['kind'] != 'EV_plug']
        with self.assertRaisesRegex(ValueError, 'NO_ORIGINAL_PLUG'): explicit_EV_connections(bad, 0)
        bad = copy.deepcopy(pack)
        first_trip = bad['journeys'][0]; first_trip['absolute_departure_min'] = 400
        with self.assertRaisesRegex(ValueError, 'OVERLAPS_GIVEN_JOURNEY'): explicit_EV_connections(bad, 0)


if __name__ == '__main__':
    unittest.main()
