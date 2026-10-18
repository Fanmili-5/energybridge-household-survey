"""Read paired consequences after selection; never choose or rewrite requests."""
import json
import lzma
from pathlib import Path
from .common import bound, read, save, seal, sha, verify
from .model import plan_hash


def summarize(job_path, compiled, runs, audit, out, reference_stage=None, imported=None):
    job_path, compiled, runs, audit, out = map(Path, (job_path, compiled, runs, audit, out))
    job = read(job_path)
    verify(compiled)
    verify(runs)
    audit_data = verify(audit)
    audits = {r['id']: r for r in audit_data['records']}
    resources = (job_path.parent / job['resource_root']).resolve()
    contexts = {}
    if imported:
        verify(imported)
        incoming = Path(imported)
        contexts = {r['case_id']: read(bound(incoming, r['context'])) for r in read(incoming / 'BATCH.json')['records']}
    rows = []
    for entry in job['pairs']:
        pair = read(bound(resources, entry['pair']['path']))
        rid = entry['id']
        traces = {s: read(runs / rid / s / 'TRACE.json.gz') for s in ('A', 'B')}
        metas = {s: read(compiled / rid / s / 'INPUT.json.gz') for s in ('A', 'B')}
        def channel(side, name, key):
            found = [c['values'] for k, c in traces[side].items() if k.lower() == (name + '|' + key).lower()]
            if len(found) != 1:
                raise ValueError('MISSING_PAIRED_CHANNEL:' + name)
            return dict(found[0])
        def controlled(side):
            meta = metas[side]
            targets = [('Zone Packaged Terminal Heat Pump Electricity Energy', name) for name in meta['HVAC_equipment_mapping'].values()]
            targets += [('Electric Equipment Electricity Energy', name) for name in meta['equipment_meter_mapping']]
            if meta['tank_name']:
                targets += [('WaterSystems:Electricity', '')]
            if meta['EV']['installed']:
                targets += [('Exterior Equipment Electricity Energy', 'EXTERNAL_EV')]
            total = {}
            for variable, key in targets:
                for t, value in channel(side, variable, key).items():
                    total[t] = total.get(t, 0) + value / 3600000
            return total
        energy = {s: controlled(s) for s in ('A', 'B')}
        costs = None
        if imported:
            context = contexts[pair['case_id']]
            if plan_hash(pair['A']) != context['reference']['binding']['A_commands_sha256'] or pair['VPP_events'] != context['events']:
                raise ValueError('PRICING_CONTEXT_MISMATCH')
            tariff = context['tariff']
            def bill(values, lo, hi):
                total = 0.0
                for t, kWh in values.items():
                    if not lo <= t < hi:
                        continue
                    rates = [r['price_per_kWh'] for r in tariff if r['start_min'] <= t and t + 10 <= r['end_min']]
                    if len(rates) != 1:
                        return None
                    total += kWh * rates[0]
                return total
            costs = {'currency': context.get('tariff_provenance', {}).get('currency', 'declared_input_currency'),
                     'scope': 'unrounded_simulated_meter_cost;no_VPP_compensation_or_acceptance_inferred',
                     'tariff_provenance': context.get('tariff_provenance'), 'intervals': {}}
            for label, hi in [('primary_24h', 1920), ('primary_and_followup', metas['A']['run_interval_min'][1])]:
                totals = {s: bill({t: v / 3600000 for t, v in channel(s, 'Electricity:Facility', '').items()}, 480, hi) for s in ('A', 'B')}
                costs['intervals'][label] = {'interval_min': [480, hi], **totals,
                                             'B_minus_A': totals['B'] - totals['A'] if None not in totals.values() else None}
        events = []
        for e in pair['VPP_events']:
            measured = {s: sum(v for t, v in energy[s].items() if e['start_min'] <= t < e['end_min']) for s in ('A', 'B')}
            delta = (measured['B'] - measured['A']) * 60 / (e['end_min'] - e['start_min'])
            aligned = delta * (1 if e['direction'] == 'up' else -1)
            events.append({'event_id': e['event_id'], 'requested_direction': e['direction'],
                           'delta_kw': delta, 'aligned_response_kw': aligned,
                           'target_kw': e['target_kw'], 'target_met': aligned + 1e-8 >= e['target_kw']})
        old_match = None
        if reference_stage:
            oldpath = Path(reference_stage) / 'results/pilot50' / pair['household_id'] / pair['date'] / 'A/TRACE.json.xz'
            old = json.loads(lzma.decompress(oldpath.read_bytes()))['channels']
            lower = {k.lower(): dict(v) for k, v in old.items()}
            errors = []
            common = 0
            for name, c in traces['A'].items():
                if name.lower() not in lower:
                    continue
                common += 1
                previous = lower[name.lower()]
                errors.extend(abs(v - previous[t]) for t, v in c['values'] if t in previous)
            old_match = {'common_channels': common, 'max_absolute_error_in_channel_native_units': max(errors, default=None),
                         'within_1e_minus6_each_native_channel': bool(errors) and max(errors) < 1e-6,
                         'reference_archive_sha256': sha(oldpath)}
        check = audits[rid]
        row = {'case_id': pair['case_id'], 'policy': pair['AB_generation']['policy'],
               'request_status': pair['AB_generation']['status'], 'engine_arms': 2,
               'history_days': metas['A']['history_days'],
               'A_reference_comparison': old_match,
               'audit_status': check['status'], 'failed_checks': [k for k, v in check['checks'].items() if not v],
               'events': events, 'meter_scope': 'target HVAC,programs,water systems,and separately supplied EV;not whole facility',
               'facility_energy_kWh': {s: read(runs / rid / s / 'RESULT.json')['facility_energy_kWh'] for s in ('A', 'B')},
               'simulated_facility_cost': costs,
               'service_execution': {s: metas[s]['execution']['batches'] for s in ('A', 'B')},
               'EV': {s: {'installed': metas[s]['EV']['installed'],
                           'end_energy_kWh': metas[s]['EV'].get('end_energy_kWh'),
                           'unexecutable_trip_min': metas[s]['EV'].get('stop_at_unexecutable_trip_min')}
                      for s in ('A', 'B')},
               'actual_results_used_for_reselection': False, 'human_acceptance': None}
        rows.append(row)
    out.mkdir(parents=True, exist_ok=False)
    save(out / 'REPORT.json', {'schema': 'eb.ab_generation.physical_report.v1', 'records': rows,
                              'whole500_physical_acceptance': False, 'human_acceptance_inferred': False})
    seal(out, {'job_sha256': sha(job_path), 'compiled_manifest_sha256': sha(compiled / 'MANIFEST.json'),
               'runs_manifest_sha256': sha(runs / 'MANIFEST.json'), 'audit_manifest_sha256': sha(audit / 'MANIFEST.json')})
    return {'reported_cases': len(rows), 'engine_arms': len(rows) * 2}
