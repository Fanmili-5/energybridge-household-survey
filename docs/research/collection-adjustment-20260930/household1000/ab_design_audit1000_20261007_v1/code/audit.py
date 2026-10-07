"""Read saved V16 artifacts on school Linux; do not generate pairs or run EP."""
import collections
import datetime as dt
import hashlib
import json
import sys
from pathlib import Path

OUT = Path(__file__).resolve().parents[1]
SRC = OUT.parent / 'joint_static_production_20261007_v16'


def read(path):
    return json.loads(path.read_text())


def digest(value):
    raw = json.dumps(value, ensure_ascii=False, sort_keys=True,
                     separators=(',', ':'), allow_nan=False)
    return hashlib.sha256(raw.encode()).hexdigest()


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def overlap(interval, event):
    return max(interval[0], event[0]) < min(interval[1], event[1])


def future_prefix(plan, decision):
    return {
        'tasks': sorted((x for x in plan['tasks'] if x['start_min'] < decision),
                        key=lambda x: x['need_id']),
        'operations': sorted((x for x in plan['operations'] if x['start_min'] < decision),
                             key=lambda x: x['operation_id']),
        'controls': sorted(({**x, 'end_min': min(x['end_min'], decision)}
                            for x in plan['controls'] if x['start_min'] < decision),
                           key=digest),
    }


def main():
    assert sys.platform == 'linux', 'School server only'
    assert not (OUT / 'AUDIT.json').exists(), 'Use a new version'
    worlds = read(SRC / 'WORLD_BINDINGS1000.json')
    pairs = read(SRC / 'PAIR_BINDINGS10000.json')
    counts = collections.Counter()
    families = collections.Counter()
    magnitudes = collections.defaultdict(collections.Counter)
    quarters = collections.Counter()
    task_statistics = collections.defaultdict(collections.Counter)
    errors, records, world_records = [], [], []
    bindings = {b['household_id']: b for b in worlds['records']}
    for household in pairs['households']:
        hid = household['household_id']
        binding = bindings[hid]
        wpath = SRC / binding['world_path']
        w = read(wpath)
        if sha(wpath) != binding['world_sha256']:
            errors.append([hid, 'WORLD_FILE_HASH'])
        if digest(w['parameter_pack']) != w['parameter_pack_sha256']:
            errors.append([hid, 'PARAMETER_PACK_HASH'])
        dates = [r['date'] for r in household['records']]
        if len(dates) != 10 or len(set(dates)) != 10:
            errors.append([hid, 'TEN_UNIQUE_DATES'])
        if dates != [r['date'] for r in w['random10_date_selection']['dates']]:
            errors.append([hid, 'WORLD_PAIR_DATES'])
        qcount = collections.Counter((dt.date.fromisoformat(d).month - 1) // 3 + 1
                                     for d in dates)
        if sorted(qcount.values()) != [2, 2, 3, 3] or set(qcount) != {1, 2, 3, 4}:
            errors.append([hid, 'QUARTER_COUNTS'])
        quarters.update(qcount)
        counts['households_read'] += 1
        if w['assets']['water_heater']['present']:
            counts['WH_households'] += 1
            # Storage can satisfy later draws: this is a flag, not a service-failure verdict.
            final_draw_end = w['routine']['bath_start_min'] + 10 * w['N']
            availability_end = w['routine']['tank_heat_window_min'][1]
            gap = max(0, final_draw_end - availability_end)
            if gap:
                counts['WH_availability_ends_before_last_reference_draw_households'] += 1
            world_records.append({'household_id': hid,
                                  'WH_availability_end_min': availability_end,
                                  'last_reference_draw_end_min': final_draw_end,
                                  'availability_gap_min': gap,
                                  'actual_service_failure_inferred': False})
        for b in household['records']:
            path = SRC / b['pair_path']
            p = read(path)
            counts['pairs_read'] += 1
            family = p['proposal']['family']
            families[family] += 1
            magnitudes[family][str(p['proposal'].get('amount'))] += 1
            if sha(path) != b['pair_sha256']:
                errors.append([p['case_id'], 'PAIR_FILE_HASH'])
            if p['world_sha256'] != w['world_content_sha256']:
                errors.append([p['case_id'], 'WORLD_CONTENT_BINDING'])
            if p['needs_A'] != p['needs_B']:
                errors.append([p['case_id'], 'DEMAND_MISMATCH'])
            if digest(p['A']) != p['A_frozen_before_B_sha256']:
                errors.append([p['case_id'], 'A_NOT_FROZEN'])
            if p['parameter_pack_sha256'] != w['parameter_pack_sha256']:
                errors.append([p['case_id'], 'PAIR_PARAMETER_PACK'])
            if future_prefix(p['A'], p['decision_abs_min']) != future_prefix(p['B'], p['decision_abs_min']):
                errors.append([p['case_id'], 'PREDECISION_INPUT_MISMATCH'])
            no_op = all(p['A'][key] == p['B'][key] for key in ['tasks', 'controls', 'operations'])
            counts['identical_task_control_operation_pairs'] += int(no_op)
            event = p['event_window_min']
            counts['event_' + str(event)] += 1
            counts['decision_' + str(p['decision_abs_min'])] += 1
            date = dt.date.fromisoformat(p['date'])
            if date.year != 2025:
                errors.append([p['case_id'], 'REFERENCE_YEAR'])
            if (date - dt.timedelta(days=7)).year != (date + dt.timedelta(days=2)).year:
                counts['cross_year_input_episodes'] += 1
            if date.month == 1 and date.day <= 7:
                counts['leap2024_to_nonleap2025_TMY_bridge_cases'] += 1
            A = {x['need_id']: x for x in p['A']['tasks']}
            B = {x['need_id']: x for x in p['B']['tasks']}
            changed = [(A[n], B[n]) for n in A.keys() & B.keys() if A[n] != B[n]]
            active_A = any(overlap([a['start_min'], a['end_min']], event) for a, _ in changed)
            active_B = any(overlap([v['start_min'], v['end_min']], event) for _, v in changed)
            info = {'household_id': hid, 'case_id': p['case_id'], 'round_index': p['round_index'],
                    'date': p['date'], 'family': family, 'amount': p['proposal'].get('amount'),
                    'no_actual_input_change': no_op, 'event_window_min': event,
                    'changed_program_A_event_overlap': active_A,
                    'changed_program_B_event_overlap': active_B,
                    'pair_path': b['pair_path'], 'pair_sha256': b['pair_sha256']}
            if family in ['task_shift', 'task_plus_ac']:
                s = task_statistics[family]
                s['pairs'] += 1
                s['changed_program_A_overlaps_event'] += int(active_A)
                s['changed_program_B_overlaps_event'] += int(active_B)
                s['changed_program_neither_A_nor_B_overlaps_event'] += int(not active_A and not active_B)
                s['changed_program_only_B_overlaps_event'] += int(not active_A and active_B)
                s['changed_program_only_A_overlaps_event'] += int(active_A and not active_B)
                # Joint AC can still affect the event; only task_shift is a whole-case flag.
                info['joint_AC_effect_not_evaluated'] = family == 'task_plus_ac'
            records.append(info)
    report = {
        'scope': 'Independent saved-input audit of sealed1000 households/10000 pairs;no EP or model calls',
        'host': 'school Linux', 'source_stage': SRC.name,
        'source_delivery_sha256': sha(SRC / 'DELIVERY.json'),
        'source_world_bindings_sha256': sha(SRC / 'WORLD_BINDINGS1000.json'),
        'source_pair_bindings_sha256': sha(SRC / 'PAIR_BINDINGS10000.json'),
        'source_code_sha256': {name: sha(SRC / 'code' / name) for name in ['plans.py', 'build_worlds.py', 'validate.py']},
        'counts': dict(counts), 'proposal_families': dict(families),
        'proposal_magnitudes': {k: dict(v) for k, v in magnitudes.items()},
        'quarter_target_day_counts': dict(quarters),
        'program_event_overlap': {k: dict(v) for k, v in task_statistics.items()},
        'saved_binding_demand_and_prefix_errors': errors,
        'EP_runs_this_audit': 0, 'full1000_EP_authorized': False,
        'actual_event_energy_effects_measured_for_full1000': False,
        'physical_service_failure_inferred_from_input_window': False,
        'human_discriminability_validated': False, 'human_answers': 0,
        'collection_release': False, 'training_release': False,
        'no_op_admission': 'Identity controls may be diagnostics;not ten informative primary preference contrasts',
        'window_overlap_limit': 'Nominal program intervals only;WH/AC actual electricity and comfort require EP/observation',
        'records': records, 'WH_input_window_flags': world_records,
    }
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / 'AUDIT.json').write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n')
    print(json.dumps({k: v for k, v in report.items() if k not in ['records', 'WH_input_window_flags', 'source_code_sha256']}, ensure_ascii=False))
    assert counts['households_read'] == 1000 and counts['pairs_read'] == 10000
    assert not errors, errors[:10]


if __name__ == '__main__':
    main()
