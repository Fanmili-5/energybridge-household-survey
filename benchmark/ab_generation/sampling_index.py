"""Exact canonical command hashing with cached immutable baseline rows.

No sample, dose, priority or constraint changes. The slow implementation in
sampling.py remains the executable reference (catalogue(indexed=False)).
"""
import hashlib
from collections import defaultdict
from .common import canonical, digest
from .model import _patch_view, command_order


class CommandIndex:
    def __init__(self, context):
        self.context = context
        self.baseline = {key: sorted(context['A'][key], key=command_order)
                         for key in ('tasks', 'operations', 'controls')}
        self.baseline['controls'] = [{**r, '_ab_control_id': digest(r)} for r in self.baseline['controls']]
        # Retain the source objects: an id can never be confused with a recycled
        # temporary row. Only immutable baseline rows enter this cache.
        self.rows = {id(r): (r, canonical(r)) for key in ('tasks', 'operations') for r in self.baseline[key]}
        self.payloads = {id(r): (r, self._payload(r)) for r in context['A']['controls'] + self.baseline['controls']}
        self.before = {key: {r[ident]: r for r in context['A'][key]}
                       for key, ident in (('tasks', 'task_id'), ('operations', 'operation_id'))}
        self.past = self._past(context['A']['controls'])
        self.control_cache = {}

    @staticmethod
    def _payload(row):
        return canonical({k: v for k, v in row.items() if k not in ('start_min', 'end_min', '_ab_control_id')})

    def patch(self, patches):
        return _patch_view(self.baseline, patches)

    def _past(self, rows):
        changes = {}
        for r in rows:
            lo, hi = r['start_min'], min(r['end_min'], self.context['decision_min'])
            if lo >= hi:
                continue
            cached = self.payloads.get(id(r))
            payload = cached[1] if cached is not None and cached[0] is r else self._payload(r)
            # Canonical payload equality is exactly the equality used by the
            # reference's SHA256 payload keys (without relying on collisions).
            for t, delta in ((lo, 1), (hi, -1)):
                key = (payload, t)
                changes[key] = changes.get(key, 0) + delta
        return {k: v for k, v in changes.items() if v}

    def request_issues(self, plan):
        issues = set()
        for key, ident in (('tasks', 'task_id'), ('operations', 'operation_id')):
            before = self.before[key]
            after = {r[ident]: r for r in plan[key]}
            if before.keys() != after.keys() or len(after) != len(plan[key]):
                issues.add('REQUEST_CHANGES_ORIGINAL_ROW_SET')
            for rid in before.keys() & after.keys():
                a, b = before[rid], after[rid]
                if a is b:
                    continue
                if ({k: v for k, v in a.items() if k not in ('start_min', 'end_min')}
                        != {k: v for k, v in b.items() if k not in ('start_min', 'end_min')}
                        or a['end_min'] - a['start_min'] != b['end_min'] - b['start_min']):
                    issues.add('REQUEST_CHANGES_ORIGINAL_RESOURCE_OR_DURATION')
                if min(a['start_min'], b['start_min']) < self.context['decision_min'] and a != b:
                    issues.add('REQUEST_REWRITES_PREDECISION_COMMAND')
        if self.past != self._past(plan['controls']):
            issues.add('REQUEST_REWRITES_PREDECISION_CONTROL')
        return sorted(issues)

    def _controls(self, rows):
        # Coalescing is the reference rule: equal payload, adjacent intervals,
        # preserving gaps, multiplicity and value differences.
        groups = defaultdict(list)
        for row in rows:
            cached = self.payloads.get(id(row))
            payload = cached[1] if cached is not None and cached[0] is row else self._payload(row)
            groups[payload].append((row['start_min'], row['end_min']))
        signature = tuple((key, tuple(sorted(spans))) for key, spans in sorted(groups.items()))
        if signature not in self.control_cache:
            import json
            controls = []
            for payload, spans in signature:
                merged = []
                for lo, hi in spans:
                    if merged and merged[-1][1] == lo:
                        merged[-1] = (merged[-1][0], hi)
                    else:
                        merged.append((lo, hi))
                values = json.loads(payload)
                controls.extend(canonical({**values, 'start_min': lo, 'end_min': hi}) for lo, hi in merged)
            self.control_cache[signature] = '[' + ','.join(sorted(controls)) + ']'
        return self.control_cache[signature]

    def command_hash(self, plan):
        parts = {'controls': self._controls(plan['controls'])}
        for key in ('operations', 'tasks'):
            rows = []
            for row in plan[key]:
                cached = self.rows.get(id(row))
                rows.append(cached[1] if cached is not None and cached[0] is row else canonical(row))
            parts[key] = '[' + ','.join(sorted(rows)) + ']'
        body = '{' + ','.join('"' + key + '":' + parts[key] for key in ('controls', 'operations', 'tasks')) + '}'
        return hashlib.sha256(body.encode()).hexdigest()
