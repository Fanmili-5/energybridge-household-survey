"""One frozen device: cost of removing ONLY soft calendar/booking filtering.

Measurement adapter, not a production rule or candidate-bank supplement.
The exact adapter source and input hashes are saved before execution.
"""
import argparse
from pathlib import Path
import time
import resource
from unittest.mock import patch

from benchmark.ab_generation.common import read, save, sha
from benchmark.ab_generation.unified.candidates import prepare, catalogue_domains
from benchmark.ab_generation.unified.contract import code_hash
from .acceptance import record_sources


def numeric_slots(c, op, left, right):
    length = op['end_min']-op['start_min']
    lo = ((max(left, c['decision_min'])+9)//10)*10
    hi = min(right, c['horizon_min'][1]-length)//10*10
    return list(range(lo, hi+1, 10))


def run(source, out):
    source, out = Path(source), Path(out)
    out.mkdir(parents=True, exist_ok=False)
    pre, contexts = record_sources(source/'fifty')
    key = ('ordinary-v6-0653', '2025-02-23')
    cfg = pre['configuration']
    c = prepare(read(contexts[key]), cfg)
    asset = next(d for d in c['devices'] if d['kind']=='dishwasher')
    # Scope the measurement to this single device, preserving all its facts.
    measured = {**c, 'devices':[asset]}
    save(out/'PROTOCOL.json', dict(household_id=key[0], date=key[1], asset_id=asset['asset_id'],
        source_context_sha256=sha(contexts[key]), configuration=cfg, helper_sha256=sha(__file__),
        code_sha256=code_hash(), measurement_only=True, physical_runs=0,
        adapter='replace calendar/booking _slots with complete original 10-minute numeric ranges;retain original qualification mask',
        official_catalogue_changed=False))
    start = time.perf_counter()
    with patch('benchmark.ab_generation.unified.candidates._slots', numeric_slots), \
         patch('benchmark.ab_generation.collection_candidates._slots', numeric_slots):
        result = catalogue_domains(measured, cfg)
    report = dict(elapsed_seconds=time.perf_counter()-start,
        process_peak_rss_bytes=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
        raw=result['raw_count'], native=sum(len(v)-1 for v in result['values']),
        support=len(result['support_domain']), factors=len(result['values']),
        engineering_diagnostic_records=len(result['engineering_diagnostics']),
        actual_B_materializations=0, production_adoption=False)
    save(out/'RESULT.json', report)
    return report


if __name__ == '__main__':
    p=argparse.ArgumentParser();p.add_argument('--source',required=True);p.add_argument('--out',required=True)
    a=p.parse_args();print(run(a.source,a.out))
