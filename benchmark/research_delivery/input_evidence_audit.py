"""Locate unknown opportunity evidence in frozen inputs without reclassification.

Does not call the opportunity declaration or candidate admission functions.
An absent control interval is not an observed OFF state.
"""
import argparse
import csv
from collections import Counter
from pathlib import Path
from benchmark.ab_generation.common import read, save, sha
from .acceptance import record_sources


def explain(context, entry, event):
    family, asset, need = entry['family'], entry['asset_id'], entry['need_id']
    devices = [d for d in context['devices'] if d['asset_id'] == asset]
    if len(devices) != 1:
        raise ValueError('UNKNOWN_EVIDENCE_ASSET_IDENTITY')
    if entry['reason'] == 'service_or_excerpt_has_no_program_evidence':
        needs = [n for n in context['needs'] if n['need_id'] == need and n['asset_id'] == asset]
        if len(needs) != 1:
            raise ValueError('UNKNOWN_EVIDENCE_SERVICE_IDENTITY')
        tasks = [t for t in context['A']['tasks']
                 if t['asset_id'] == asset and t['need_id'] in (need, need + ':dry')]
        if tasks:
            raise ValueError('UNKNOWN_PROGRAM_LABEL_CONTRADICTS_INPUT')
        n = needs[0]; lo, hi = context['horizon_min']
        location = ('release_after_excerpt' if n['release_min'] >= hi else
                    'deadline_before_excerpt' if n['deadline_min'] <= lo else
                    'within_excerpt_unmatched_program')
        return dict(detail=location, source_field='needs + A.tasks',
            release_min=n['release_min'], deadline_min=n['deadline_min'],
            excerpt_start_min=lo, excerpt_end_min=hi, matching_program_rows=0,
            release_after_event=n['release_min'] >= event['end_min'])
    if entry['reason'] == 'event_control_evidence_missing':
        kind = {'ac':'ac_setpoint', 'water_heater':'tank_setpoint'}[family]
        rows = [c for c in context['A']['controls'] if c['asset_id'] == asset and c['kind'] == kind]
        overlap = lambda a, z: max(a, event['start_min']) < min(z, event['end_min'])
        if any(overlap(c['start_min'], c['end_min']) for c in rows):
            raise ValueError('UNKNOWN_CONTROL_LABEL_CONTRADICTS_INPUT')
        room = devices[0].get('room_id')
        occupancy = context.get('occupancy', {})
        recorded = room in occupancy if family == 'ac' else None
        room_used = any(overlap(a,z) for a,z in occupancy[room]) if recorded else None
        return dict(detail='controls_outside_event' if rows else 'no_control_rows_for_asset',
            source_field='A.controls + occupancy', expected_control_kind=kind,
            controls_for_asset=len(rows), controls_overlapping_event=0,
            original_control_intervals=[[c['start_min'],c['end_min']] for c in rows],
            occupancy_room_record_present=recorded, event_room_use_declared=room_used)
    return dict(detail='unreviewed_reason', source_field=None)


def run(collection, ledger_path, out):
    collection, ledger_path, out = map(Path, (collection, ledger_path, out))
    out.mkdir(parents=True, exist_ok=False)
    pre, contexts = record_sources(collection)
    ledger = read(ledger_path)
    dates = [(d['household_id'],d['date']) for d in ledger]
    if len(dates) != len(set(dates)) or set(dates) != set(contexts):
        raise ValueError('UNKNOWN_AUDIT_DATE_ROSTER_MISMATCH')
    pins = {str(ledger_path):sha(ledger_path), str(collection/'PRE_GENERATION.json'):sha(collection/'PRE_GENERATION.json'),
            str(Path(__file__).resolve()):sha(__file__)}
    rows, unique = [], {}
    for day in ledger:
        key = day['household_id'],day['date']; path = contexts[key]
        expected = pre['source_sha256'].get(str(path))
        if expected is None or sha(path) != expected:
            raise ValueError('UNKNOWN_AUDIT_SOURCE_NOT_FROZEN')
        pins[str(path)] = expected
        context = read(path)
        for entry in day['mechanisms']:
            if entry['status'] != 'unknown': continue
            detail = explain(context, entry, pre['configuration']['event'])
            row = dict(household_id=key[0],date=key[1],context_path=str(path),context_sha256=expected,
                **{k:entry[k] for k in ('key','family','asset_id','need_id','mechanism','axis','reason')}, **detail)
            rows.append(row)
            unit = (*key,entry['asset_id'],entry['need_id'])
            if unit in unique and unique[unit] != detail:
                raise ValueError('UNKNOWN_AUDIT_INCONSISTENT_UNIT_DETAILS')
            unique[unit] = detail
    if any(r['detail']=='unreviewed_reason' for r in rows):
        raise ValueError('UNREVIEWED_UNKNOWN_REASON;KEEP_DIAGNOSTIC')
    if any(sha(p)!=h for p,h in pins.items()):
        raise ValueError('UNKNOWN_AUDIT_SOURCE_CHANGED')
    flat = [{k:v for k,v in r.items() if k!='original_control_intervals'} for r in rows]
    with (out/'UNKNOWN_MECHANISMS.csv').open('w',newline='') as f:
        fields = sorted(set().union(*(r.keys() for r in flat)))
        writer = csv.DictWriter(f,fieldnames=fields);writer.writeheader();writer.writerows(flat)
    save(out/'DETAILS.json.gz', rows)
    result = dict(passed=True,date_slots=len(dates),unknown_mechanisms=len(rows),unique_asset_need_dates=len(unique),
        mechanism_details=dict(Counter(r['family']+':'+r['detail'] for r in rows)),
        unique_unit_details=dict(Counter(d['detail'] for d in unique.values())),
        thermal_no_event_room_use_units=sum(d.get('event_room_use_declared') is False for d in unique.values()),
        all_sources_unchanged=True,source_sha256=pins,opportunity_statuses_changed=False,
        missing_control_is_not_observed_off=True,physical_runs=0,new_proposals_generated=False)
    save(out/'RESULT.json',result)
    return {k:v for k,v in result.items() if k!='source_sha256'}


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--collection',required=True);p.add_argument('--ledger',required=True);p.add_argument('--out',required=True)
    a=p.parse_args();print(run(a.collection,a.ledger,a.out))
