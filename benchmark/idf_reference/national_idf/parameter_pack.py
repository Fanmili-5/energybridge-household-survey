"""Read-only, schema-bound inventories; an inventory never grants admission."""
from __future__ import annotations

import math
import re

from .common import require
from .source_adapter import selector


def field_definitions(schema, kind):
    definition = schema['properties'][kind]
    body = next(iter(definition['patternProperties'].values()))
    props = body['properties']
    legacy = definition['legacy_idd']
    fields = []
    for name in legacy['fields']:
        meta = definition.get('name', {}) if name == 'name' else props[name]
        fields.append((name, meta))
    extension = legacy.get('extension')
    extensions = [(name, props[extension]['items']['properties'][name])
                  for name in legacy.get('extensibles', [])]
    return fields, extensions


def typed_value(raw, meta):
    """Decode values for checking only. Never write these back into the IDF."""
    if raw in ('', None):
        return None
    alternatives = meta.get('anyOf', [meta])
    # IDF enumerations are case-insensitive. Preserve original spelling separately.
    for part in alternatives:
        for value in part.get('enum', []):
            if str(value).casefold() == raw.casefold():
                return value
    if any(p.get('type') in ('number', 'integer') for p in alternatives):
        try:
            value = float(raw)
            if math.isfinite(value):
                return value
        except ValueError:
            pass
    return raw


def value_errors(value, meta):
    if value is None:
        return []
    alternatives = meta.get('anyOf', [meta])
    errors = []
    for part in alternatives:
        failures = []
        kind = part.get('type')
        number = isinstance(value, (int, float)) and not isinstance(value, bool)
        if kind in ('number', 'integer'):
            if not number or not math.isfinite(value):
                failures.append('not_finite_numeric')
            elif kind == 'integer' and not float(value).is_integer():
                failures.append('not_integer')
        if kind == 'string' and not isinstance(value, str):
            failures.append('not_string')
        if 'enum' in part and value not in part['enum']:
            failures.append('outside_enum')
        if number:
            if 'minimum' in part and value < part['minimum']:
                failures.append('below_minimum')
            if 'maximum' in part and value > part['maximum']:
                failures.append('above_maximum')
            if 'exclusiveMinimum' in part and value <= part['exclusiveMinimum']:
                failures.append('below_exclusive_minimum')
            if 'exclusiveMaximum' in part and value >= part['exclusiveMaximum']:
                failures.append('above_exclusive_maximum')
        if not failures:
            return []
        errors.extend(failures)
    return sorted(set(errors))


def inventory(rows, text, schema):
    """Inventory explicit values, blanks and declared defaults, including extensibles."""
    records, issues = [], []
    cursor = 0
    for index, row in enumerate(rows):
        require(row[0] in schema['properties'], 'PARAMETER_OBJECT_OUTSIDE_SCHEMA', row[0])
        definition = schema['properties'][row[0]]
        fields, ext = field_definitions(schema, row[0])
        pattern = r'(?im)^[ \t]*' + re.escape(row[0]) + r'\s*,'
        match = re.search(pattern, text[cursor:])
        require(match is not None, 'PARAMETER_SOURCE_LOCATION_MISSING', row[0])
        offset = cursor + match.start()
        line = text.count('\n', 0, offset) + 1
        cursor += match.end()
        body = next(iter(definition['patternProperties'].values()))
        required = set(body.get('required', []))
        if definition.get('name', {}).get('is_required'):
            required.add('name')
        count = max(len(fields), len(row) - 1)
        if ext and count > len(fields):
            count = len(fields) + math.ceil((count - len(fields)) / len(ext)) * len(ext)
        for pos in range(count):
            group = None
            if pos < len(fields):
                name, meta = fields[pos]
            else:
                require(ext, 'PARAMETER_EXTRA_FIELD_WITHOUT_EXTENSION', [index, pos])
                group, item = divmod(pos - len(fields), len(ext))
                name, meta = ext[item]
            raw = row[pos + 1] if pos + 1 < len(row) else None
            value = typed_value(raw, meta)
            status = ('explicit_source_value' if value is not None else
                      'omitted_with_schema_default' if 'default' in meta else
                      'omitted_without_schema_default')
            record = {'object': selector(rows, index), 'object_start_line': line,
                      'idf_field_index': pos + 1, 'field': name,
                      'extensible_group_zero_based': group, 'raw_value': raw, 'value': value,
                      'units': meta.get('units'), 'status': status,
                      'declared_schema_default': meta.get('default'),
                      'reference_lists': meta.get('object_list', []),
                      'schema_note': meta.get('note'), 'modified': False,
                      'household_applicability': None}
            records.append(record)
            errors = value_errors(value, meta)
            field_required = name in required
            if group is not None:
                extension = definition['legacy_idd']['extension']
                field_required = name in body['properties'][extension]['items'].get('required', [])
            if value is None and field_required and 'default' not in meta:
                errors.append('required_field_missing')
            if errors:
                issues.append({'object': record['object'], 'field': name,
                               'idf_field_index': pos + 1, 'raw_value': raw, 'errors': errors})
    return {'fields': records, 'field_constraint_issues': issues,
            'scope': 'Schema field inventory only; not engine validation, reference/network closure or physical admission.',
            'runtime_defaults_verified': False}
