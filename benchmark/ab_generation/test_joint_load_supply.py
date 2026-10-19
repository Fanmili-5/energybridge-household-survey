import copy
import itertools
import sqlite3
import tempfile
import unittest
from pathlib import Path

from .common import read
from .energy import batch_energy, task_power
from .generate import DEFAULT_RULES, generate
from .joint import search
from .life import generate_household
from .model import apply, control_issues, program_issues
from .power import site_capacity

HERE = Path(__file__).parent


def two_jobs():
    tasks, ops, needs = [], [], []
    for nid, start in [('first', 100), ('second', 140)]:
        tasks.append({'task_id': nid, 'need_id': nid, 'asset_id': 'washer', 'kind': 'washer', 'start_min': start, 'end_min': start + 20})
        for kind, a in [('load', start - 10), ('unload', start + 20)]:
            ops.append({'operation_id': nid + ':' + kind, 'need_id': nid, 'asset_id': 'washer', 'operator_id': 'adult',
                        'room_id': 'room', 'kind': kind, 'start_min': a, 'end_min': a + 10})
        needs.append({'need_id': nid, 'asset_id': 'washer', 'kind': 'washer', 'release_min': 0, 'deadline_min': 1440,
                      'timer_allowed': True, 'maximum_preload_wait_min': 180, 'maximum_retrieval_wait_min': 180,
                      'machine_windows_min': [[0, 1440]]})
    return {'A': {'tasks': tasks, 'operations': ops, 'controls': []}, 'needs': needs,
            'devices': [{'asset_id': 'washer', 'kind': 'washer', 'types': ['washer'], 'parameters': {'power_kw': .5, 'nameplate_W': 1000}}],
            'operator_windows': {'adult': [[0, 1440]]}, 'reservations': [], 'decision_min': 0, 'horizon_min': [0, 1440],
            'reference': {'binding': {}, 'ev_charging_steps': []}}


def move(c, nid, delta):
    patches = [{'type': 'rows', 'collection': key, 'identity': ident,
                'rows': [{**r, 'start_min': r['start_min'] + delta, 'end_min': r['end_min'] + delta}
                         for r in c['A'][key] if r['need_id'] == nid]}
               for key, ident in [('tasks', 'task_id'), ('operations', 'operation_id')]]
    return {'id': nid, 'family': 'washer', 'asset_id': 'washer', 'patches': patches,
            'factors': {'need_id': nid}, 'static_issues': program_issues(c, apply(c['A'], patches), nid),
            'opportunity': {'status': 'supported'}}


class JointLoadSupplyTests(unittest.TestCase):
    def test_two_invalid_same_asset_singles_can_be_valid_joint_swap(self):
        c = two_jobs(); a, b = move(c, 'first', 40), move(c, 'second', -40)
        self.assertIn('ASSET_HOLD_CONFLICT', a['static_issues']); self.assertIn('ASSET_HOLD_CONFLICT', b['static_issues'])
        rows, coverage = search(c, [a, b], DEFAULT_RULES)
        self.assertEqual(1, len(rows)); self.assertEqual([], rows[0]['static_issues'])
        self.assertEqual(['washer', 'washer'], rows[0]['family_composition'])
        self.assertTrue(coverage['coverage_passed'])

    def test_small_space_matches_independent_subset_oracle_and_all_families(self):
        c = read(HERE / 'examples/family.json')
        singles = generate(c, {'joint_family_limit': 1})['candidates']
        families = sorted({r['family'] for r in singles})
        chosen = [next(r for r in singles if r['family'] == f) for f in families]
        rows, coverage = search(c, chosen, DEFAULT_RULES)
        expected = {frozenset(r['id'] for r in combo) for size in range(2, len(chosen) + 1) for combo in itertools.combinations(chosen, size)}
        self.assertEqual(expected, {frozenset(r['candidate_ids']) for r in rows})
        self.assertGreaterEqual(len(families), 3); self.assertTrue(coverage['coverage_passed'])
        self.assertEqual(len(families), max(len(r['candidate_ids']) for r in rows))

    def test_budget_gap_is_explicit_and_never_claimed_complete(self):
        c = read(HERE / 'examples/family.json'); singles = generate(c, {'joint_family_limit': 1})['candidates']
        rows, coverage = search(c, singles, {**DEFAULT_RULES, 'joint_candidate_budget': 2})
        self.assertEqual(2, len(rows)); self.assertFalse(coverage['coverage_passed'])
        self.assertLess(coverage['pair_dose_covered'], coverage['pair_dose_required'])
        self.assertFalse(coverage['B_results_used'])

    def test_final_joint_deadband_checked_after_both_axes_change(self):
        c = {'devices': []}; p = {'controls': [{'asset_id': 'ac', 'kind': 'ac_setpoint', 'heating_setpoint_C': 26, 'cooling_setpoint_C': 25}]}
        self.assertIn('THERMOSTAT_DEADBAND_INVERTED', control_issues(c, p))

    def test_empirical_shape_can_be_nonmonotone_and_energy_conserved(self):
        h = {'power_kw': .5, 'nameplate_W': 2500}; p = {'kind': 'washer', 'duration_min': 60}
        def e(m):return batch_energy({'kind': 'washer', 'quantity': m, 'batch_capacity_kg': 5}, p, h)
        self.assertLess(e(.6)['cycle_energy_kWh'], e(1.8)['cycle_energy_kWh'])
        self.assertGreater(e(4)['cycle_energy_kWh'], e(5)['cycle_energy_kWh'])
        for m in (.1, 1.2, 4, 5):
            value=e(m);t={'kind':'washer','start_min':0,'end_min':60,**value}
            self.assertAlmostEqual(value['cycle_energy_kWh'], task_power(t,h))
        with self.assertRaisesRegex(ValueError, 'INVALID_BATCH_MASS'):
            e(5.1)
        with self.assertRaisesRegex(ValueError, 'NAMEPLATE_DURATION'):
            batch_energy({'kind':'washer','quantity':5,'batch_capacity_kg':5},{'duration_min':10},{'power_kw':.5,'nameplate_W':500})

    def test_batch_energy_cannot_change_when_only_start_time_moves(self):
        h={'power_kw':.5,'nameplate_W':2500};e=batch_energy({'kind':'washer','quantity':1.2,'batch_capacity_kg':5},{'duration_min':60},h)
        a={'kind':'washer','start_min':100,'end_min':160,**e};b={**a,'start_min':200,'end_min':260}
        self.assertEqual(task_power(a,h),task_power(b,h))
        with self.assertRaisesRegex(ValueError, 'ENERGY_POWER_DURATION'):
            task_power({**b,'end_min':270},h)

    def test_site_capacity_is_cumulative_and_upper_uncertainty_is_separate(self):
        c=two_jobs();c['electrical']={'schema':'eb.ab_site_capacity.v1','supply_W':750,'background_upper_W':0}
        self.assertFalse(site_capacity(c,c['A'])['issues'])
        # Different devices with simultaneous complete programs exceed the site.
        c['devices'].append({**c['devices'][0],'asset_id':'other'})
        b=copy.deepcopy(c['A']);b['tasks'][1].update(asset_id='other',start_min=100,end_min=120)
        self.assertEqual('known_profile_overload',site_capacity(c,b)['status'])
        c['electrical']['background_upper_W']=500
        self.assertEqual('conservative_bound_exceeded',site_capacity(c,c['A'])['status'])

    def test_A_scheduler_staggers_known_programs_around_given_EV_charge(self):
        spec=read(HERE/'examples/strategy_review/life_batch.json')['households'][0];spec['end_exclusive']='2025-03-08'
        world=next(w for w in read(HERE/'examples/strategy_review/resource_worlds.json')['households'] if w['household_id']==spec['household_id'])
        world['electrical']['supply_W']=7000
        a=generate_household(spec,world)
        self.assertEqual('A_constructed',a['status'])
        self.assertLessEqual(a['electrical_plan_check']['known_program_EV_peak_W'],7000+1e-6)

    def test_native_five_minute_peak_not_hidden_by_ten_minute_average(self):
        from benchmark.housing_simulation.pipeline import native_site_power
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'data.sql'
            with sqlite3.connect(path) as db:
                db.executescript('''CREATE TABLE ReportDataDictionary(ReportDataDictionaryIndex INT,Name TEXT,KeyValue TEXT,Units TEXT,IsMeter INT);
                CREATE TABLE Time(TimeIndex INT,SimulationDays INT,Hour INT,Minute INT,Interval INT,WarmupFlag INT,EnvironmentPeriodIndex INT);
                CREATE TABLE EnvironmentPeriods(EnvironmentPeriodIndex INT,EnvironmentType INT);
                CREATE TABLE ReportData(ReportDataDictionaryIndex INT,TimeIndex INT,Value REAL);
                INSERT INTO ReportDataDictionary VALUES(1,'Electricity:Facility','','J',1);
                INSERT INTO EnvironmentPeriods VALUES(1,3);
                INSERT INTO Time VALUES(1,1,0,5,5,NULL,1),(2,1,0,10,5,0,1);
                INSERT INTO ReportData VALUES(1,1,600000),(1,2,0);''')
            result=native_site_power(path,0,10,5)
            self.assertEqual(2000,result['peak_W']);self.assertEqual(1000,sum(v for t,v in result['values_W'])/2)


if __name__=='__main__':unittest.main()
