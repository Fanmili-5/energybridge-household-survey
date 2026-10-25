"""Frozen-case annotation acceptance, not regeneration or reselection."""
import argparse
from collections import Counter
from pathlib import Path

from benchmark.ab_generation.common import read, save, digest
from benchmark.ab_generation.model import apply
from benchmark.ab_generation.unified.change_axes import annotate_frozen_row, presentation, time_band
from benchmark.ab_generation.unified.contract import code_hash
from benchmark.ab_generation.unified.independent import audit
from .acceptance import record_sources
from .causal_audit import check_case
from .shadow_selection import file_hash, summarize


def independent_preparation(context, original):
    """Ten-minute literal comparison; does not call the new timing classifier."""
    if original['mechanism'] != 'precondition_and_relax':
        return 0, 0
    m = original['magnitude']
    lead = m.get('precondition_min', 0)
    if not lead:
        return 0, 0
    patches = [p for p in original['patches'] if p['type'] == 'control_interval']
    boundary = max(p['end_min'] for p in patches) - m['duration_min']
    field = 'value_C' if original['family'] == 'water_heater' else m['axis'] + '_setpoint_C'
    B = apply(context['A'], original['patches'])
    before = inside = 0
    for t in range(boundary - lead, boundary, 10):
        a = next((r.get(field) for r in context['A']['controls'] if r['asset_id'] == original['asset_id'] and r['start_min'] <= t < r['end_min']), None)
        b = next((r.get(field) for r in B['controls'] if r['asset_id'] == original['asset_id'] and r['start_min'] <= t < r['end_min']), None)
        if a is not None and b is not None and a != b:
            before += 10 if t < 1080 else 0
            inside += 10 if 1080 <= t < 1140 else 0
    return before, inside


def run(protocol, out):
    protocol, out = Path(protocol).resolve(), Path(out).resolve()
    spec = read(protocol)
    out.mkdir(parents=True, exist_ok=False)
    bank = Path(spec['source_bank'])
    if code_hash() != spec['core_sha256']:
        raise ValueError('FROZEN_CORE_CHANGED')
    if file_hash(bank / 'CANDIDATE_ROWS.json.gz') != spec['candidate_rows_sha256']:
        raise ValueError('FROZEN_CANDIDATE_BANK_CHANGED')
    if file_hash(spec['selection_path']) != spec['selection_sha256']:
        raise ValueError('FROZEN_SELECTION_CHANGED')
    rows = [r for r in read(bank / 'CANDIDATE_ROWS.json.gz') if r['household_id'] in spec['households']]
    selected = set(read(spec['selection_path'])['selected_ids'])
    _, contexts = record_sources(bank)
    paths = {k: p for k, p in contexts.items() if k[0] in spec['households']}
    if any(sum(k[0] == h for k in paths) != 10 for h in spec['households']):
        raise ValueError('ORIGINAL_TEN_DATES_REQUIRED')
    loaded = {k: read(p) for k, p in paths.items()}
    pins = {str(p): file_hash(p) for p in [protocol, Path(spec['selection_path']), bank/'CANDIDATE_ROWS.json.gz', *paths.values()]}
    protected = read(spec['protected_baseline'])
    if any(file_hash(p) != h for p, h in protected.items()):
        raise ValueError('PROTECTED_INPUT_CHANGED_BEFORE_REVIEW')
    annotations, records, errors = [], [], []
    dimensions, phases, old_positions, sensitivity = Counter(), Counter(), Counter(), {}
    retained_fields = ('id', 'household_id', 'date', 'patches', 'component_ids', 'independent_units', 'issues',
        'known_event_reduction_kWh', 'unknown_thermal_response', 'consent_status', 'A_commands_sha256',
        'working_B_sha256', 'human_acceptance', 'human_score', 'human_reason', 'actual_outcomes')
    for original in rows:
        c = loaded[(original['household_id'], original['date'])]
        new = annotate_frozen_row(c, original, spec['event'])
        if any(original[k] != new[k] for k in retained_fields):
            errors.append(dict(id=original['id'], reason='LITERAL_SELECTION_OR_TAIL_CHANGED'))
        B = apply(c['A'], new['patches'])
        if audit(c, c['A'], B) or any(not r['passed'] for r in check_case(c, new, c['A'], B)):
            errors.append(dict(id=original['id'], reason='INDEPENDENT_ENGINEERING_OR_CAUSAL_ERROR'))
        for a, b in zip(original['components'], new['components']):
            if a['patches'] != b['patches']:
                errors.append(dict(id=original['id'], reason='ACTION_CHANGED'))
            axes = b['change_axes']; machine = axes['machine']['signed_start_shift_min']
            if machine is not None:
                dimensions['machine.' + time_band(machine)] += 1
                dimensions['handling.' + time_band(axes['handling']['maximum_absolute_retime_min'])] += 1
                # Re-derive actual start changes from the preserved literal task rows.
                originals = {t['task_id']: t for t in c['A']['tasks']}
                actual = [t['start_min'] - originals[t['task_id']]['start_min'] for p in a['patches'] if p.get('collection') == 'tasks' for t in p['rows']]
                if not actual or set(actual) != {machine}:
                    errors.append(dict(id=original['id'], reason='MACHINE_COORDINATE_LITERAL_MISMATCH'))
            if 'charging_permission' in axes:
                dimensions['permission_pause.' + axes['charging_permission']['time_band']] += 1
            if 'thermal' in axes:
                t = axes['thermal']['timing']; phases[t['phase']] += 1
                if independent_preparation(c, a) != (t['pre_event_preparation_min'], t['in_event_preparation_min']):
                    errors.append(dict(id=original['id'], reason='PREPARATION_TIMING_ENUMERATION_MISMATCH'))
            old_positions[a['relative_level']] += 1
        annotations.append(new)
        if new['id'] in selected:
            records.append(dict(household_id=new['household_id'], date=new['date'], id=new['id'],
                components=[dict(family=x['family'], axes=x['change_axes'], text=presentation(x)) for x in new['components']],
                issues=new['issues'], known_event_reduction_kWh=new['known_event_reduction_kWh'],
                actual_outcomes=None, physical_status='not_computed'))
    for bounds in ([15, 30, 60], [30, 60, 120], [60, 120, 240]):
        counts = Counter()
        for row in annotations:
            for c in row['components']:
                a = c['change_axes']
                x = a['machine']['signed_start_shift_min']
                if x is not None:
                    counts['machine.' + time_band(x, bounds)] += 1
                    counts['handling.' + time_band(a['handling']['maximum_absolute_retime_min'], bounds)] += 1
        sensitivity[str(bounds)] = dict(counts)
    changed_sources = [p for p, h in pins.items() if file_hash(p) != h]
    changed_protected = [p for p, h in protected.items() if file_hash(p) != h]
    source_selected = [r['id'] for r in rows if r['id'] in selected]
    exact_dates = Counter((r['household_id'], r['date']) for r in records) == Counter({k: 1 for k in paths})
    if not exact_dates:
        errors.append(dict(reason='ORIGINAL_SELECTED_DATES_CHANGED'))
    result = dict(passed=not errors and not changed_sources and not changed_protected,
        core_sha256=code_hash(), households=len(spec['households']), original_dates=len(paths),
        candidate_rows=len(rows), selected_rows=len(records), selected_action_instances=sum(len(r['components']) for r in records),
        original_selection_kept=True, source_candidate_tail_counts=summarize(rows, [r['id'] for r in rows]),
        original_selected_tail_counts=summarize(rows, source_selected),
        dimensions=dict(dimensions), thermal_timing=dict(phases), old_relative_positions=dict(old_positions),
        sensitivity=sensitivity, sensitivity_scope='reporting boundaries only;raw minutes,text,selection and actions unchanged',
        protected_files_checked=len(protected), changed_protected=changed_protected,
        source_files_checked=len(pins), changed_sources=changed_sources, errors=errors,
        new_A_or_B_generated=False, reselected=False, reseeded=False, physical_runs=0, online_changed=False,
        thousand_started=False, physical_or_human_validity_claimed=False)
    save(out/'RESULT.json', result)
    save(out/'SOURCE_PINS.json', pins)
    save(out/'ANNOTATED_ROWS.json.gz', annotations)
    save(out/'SELECTED_ACTION_MATERIALS.json', sorted(records, key=lambda r: (r['household_id'], r['date'])))
    return {k: result[k] for k in ('passed', 'households', 'original_dates', 'candidate_rows', 'selected_rows', 'errors')}


if __name__ == '__main__':
    p = argparse.ArgumentParser()
    p.add_argument('--protocol', required=True); p.add_argument('--out', required=True)
    a = p.parse_args(); print(run(a.protocol, a.out))
