"""Bind exact reviewed run windows and source initialization; never infer state."""
import datetime as dt

from .common import ROOT, require
from .idf import objects
from .source_adapter import source_file
from .source_numerics import WARMUP_FIELDS, registered_warmup_pairs


def bind_initialization(domain, model, fields, protocol_ref, root=ROOT):
    policy = domain.get('initialization')
    require(isinstance(policy, dict) and set(policy) == {'mode', 'source_initialization_evidence', 'warmup',
        'approved_run_windows', 'state_restore_supported'}, 'INITIALIZATION_POLICY_MISSING_OR_FIELDS')
    require(policy['mode'] == 'reviewed_run_windows' and policy['state_restore_supported'] is False,
            'INITIALIZATION_MODE_OR_STATE_RESTORE_UNSUPPORTED')
    warmup = policy['warmup']
    require(isinstance(warmup, dict) and set(warmup) == {'minimum_days', 'maximum_days'}
            and all(type(v) is int for v in warmup.values()), 'INITIALIZATION_WARMUP_FIELDS')
    pair = (warmup['minimum_days'], warmup['maximum_days'])
    require(pair in registered_warmup_pairs(protocol_ref, root), 'INITIALIZATION_WARMUP_OUTSIDE_PROTOCOL', pair)
    buildings = objects(model, 'Building')
    require(len(buildings) == 1, 'INITIALIZATION_BUILDING_AMBIGUOUS')
    try:
        actual = tuple(int(fields.get(buildings[0], key)) for key in WARMUP_FIELDS)
    except (TypeError, ValueError):
        require(False, 'INITIALIZATION_MODEL_WARMUP_NOT_EXPLICIT')
    require(pair == actual, 'INITIALIZATION_WARMUP_NOT_BOUND_TO_FINAL_MODEL', {'policy': pair, 'model': actual})
    basis = policy['source_initialization_evidence']
    require(isinstance(basis, list) and basis, 'INITIALIZATION_SOURCE_EVIDENCE_MISSING')
    for ref in basis:
        source_file(ref, root)
    windows = policy['approved_run_windows']
    require(isinstance(windows, list) and windows, 'INITIALIZATION_REVIEWED_WINDOWS_MISSING')
    seen = set()
    for window in windows:
        require(isinstance(window, dict) and set(window) == {'start_date', 'end_date', 'evidence'}, 'INITIALIZATION_WINDOW_FIELDS')
        try:
            begin, end = (dt.date.fromisoformat(window[key]) for key in ('start_date', 'end_date'))
        except (TypeError, ValueError):
            require(False, 'INITIALIZATION_WINDOW_DATES')
        require(begin <= end and begin.year == end.year
                and domain['run_period']['start_date'] <= begin.isoformat() <= end.isoformat() <= domain['run_period']['end_date'],
                'INITIALIZATION_WINDOW_OUTSIDE_SOURCE_CALENDAR')
        identity = begin, end
        require(identity not in seen, 'INITIALIZATION_DUPLICATE_WINDOW')
        seen.add(identity)
        require(isinstance(window['evidence'], list) and window['evidence'], 'INITIALIZATION_WINDOW_EVIDENCE_MISSING')
        for ref in window['evidence']:
            source_file(ref, root)
    return policy


def requested_initialization(case, domain):
    """Only v2 can carry formal history support; v1 remains component semantics."""
    if domain.get('schema') != 'national_idf.runtime_support_domain.v2':
        return {'checked': False, 'supported': False, 'reason': 'No formal v2 initialization policy bound', 'approved_window': None}
    policy = domain.get('initialization')
    policy = policy if isinstance(policy, dict) else {}
    candidates = policy.get('approved_run_windows')
    candidates = candidates if isinstance(candidates, list) else []
    matches = [w for w in candidates if isinstance(w, dict)
               and all(w.get(k) == case['run'][k] for k in ('start_date', 'end_date'))]
    supported = (policy.get('mode') == 'reviewed_run_windows' and policy.get('state_restore_supported') is False
                 and len(matches) == 1)
    return {'checked': True, 'supported': supported, 'mode': policy.get('mode'),
        'approved_window': matches[0] if supported else None, 'state_restoration_performed': False,
        'scope': 'Exact reviewed window and source initialization; no implicit prefix, cold-start or restored-state equivalence'}
