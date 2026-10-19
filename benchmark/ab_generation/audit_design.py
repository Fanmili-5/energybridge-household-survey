"""Read-only cross-check of public provenance and parameter review coverage."""
from collections import defaultdict
from pathlib import Path
from .common import bound, read, sha
from .generate import DEFAULT_RULES
from .life import LIFE_RULES


def schema_fields(obj, path=''):
    fields = {}
    if ('type' in obj and obj['type'] not in ('object', 'array')) or 'enum' in obj or 'const' in obj:
        fields[path] = {k: obj[k] for k in ('type', 'minimum', 'maximum', 'exclusiveMinimum', 'multipleOf',
                       'enum', 'const', 'pattern', 'format', 'minLength') if k in obj}
    for key, value in obj.get('properties', {}).items():
        fields.update(schema_fields(value, path + '/' + key))
    if isinstance(obj.get('items'), dict):
        fields.update(schema_fields(obj['items'], path + '/*'))
    if isinstance(obj.get('additionalProperties'), dict):
        fields.update(schema_fields(obj['additionalProperties'], path + '/*'))
    for i, value in enumerate(obj.get('oneOf', [])):
        fields.update(schema_fields(value, path + '/oneOf/' + str(i)))
    return fields


def quantitative(obj, path=''):
    result = defaultdict(list)
    if isinstance(obj, dict):
        for key, value in obj.items():
            for name, values in quantitative(value, path + '/' + key).items():
                result[name].extend(values)
    elif isinstance(obj, list):
        for value in obj:
            for name, values in quantitative(value, path + '/*').items():
                result[name].extend(values)
    elif type(obj) in (int, float, bool):
        result[path].append(obj)
    return result


def audit():
    package = Path(__file__).parent
    repository = package.parents[1]
    sources, register = read(package / 'SOURCES.json'), read(package / 'PARAMETERS.json')
    for pin in sources['legacy_source_pins']:
        if sha(bound(repository, pin['public_path'])) != pin['sha256']:
            raise ValueError('PUBLIC_LEGACY_SOURCE_MISMATCH:' + pin['path'])
    inherited = sources['inherited_contract']
    if sha(bound(repository, inherited['path'])) != inherited['sha256']:
        raise ValueError('PUBLIC_DESIGN_CONTRACT_MISMATCH')
    original, upstream = read(package / 'provenance/ORIGINAL_EB.json'), read(repository / 'UPSTREAM_TRACKED_FILES.json')
    if original['commit'] != upstream['commit'] or any(upstream['files'][r['path']] != r['sha256'] for r in original['files']):
        raise ValueError('ORIGINAL_EB_PIN_MISMATCH')
    for group, values in [('A_scheduler', LIFE_RULES), ('B_generation', DEFAULT_RULES)]:
        entries = register['default_settings'][group]
        if {k: r['value'] for k, r in entries.items()} != values:
            raise ValueError('UNREVIEWED_GENERATOR_PARAMETER:' + group)
        if any(not all(r.get(k) for k in ('purpose', 'origin', 'implementation', 'calibration', 'validation'))
               or r['exact_value_from_paper'] is not False for r in entries.values()):
            raise ValueError('INCOMPLETE_PARAMETER_BASIS:' + group)
    schema = register['life_schema_parameters']
    path = bound(package, schema['path'])
    if sha(path) != schema['sha256'] or schema_fields(read(path)) != schema['fields']:
        raise ValueError('UNREVIEWED_LIFE_SCHEMA_PARAMETER')
    expected = {str(p.relative_to(package)) for p in (package / 'examples').rglob('*.json')}
    if expected != {r['path'] for r in register['public_inputs']}:
        raise ValueError('UNREVIEWED_PUBLIC_EXAMPLE')
    from .common import canonical
    for entry in register['public_inputs']:
        path = bound(package, entry['path'])
        if sha(path) != entry['sha256']:
            raise ValueError('UNREVIEWED_PUBLIC_INPUT_VALUE:' + entry['path'])
        fields = quantitative(read(path)); rows = {r['path_pattern']: r for r in entry['quantitative_fields']}
        if fields.keys() != rows.keys():
            raise ValueError('UNREVIEWED_PUBLIC_PARAMETER:' + entry['path'])
        for key, values in fields.items():
            row = rows[key]
            if (len(values) != row['occurrences'] or {canonical(v) for v in values} != {canonical(v) for v in row['values']}
                    or not row['origin'] or not row['purpose_and_boundary'] or row['exact_value_from_paper'] is not False):
                raise ValueError('PUBLIC_PARAMETER_BASIS_MISMATCH:' + entry['path'] + ':' + key)
    rights = read(package / 'AUTHORIZATION.json')
    from .sampling import FEATURES, SERVICE_FAILURES, SIGN_EPSILON, STRESS_STATIC, validate_plan
    from .opportunity import EPSILON
    from .effects import ENERGY_EPSILON_KWH, STATE_EPSILON
    validate_plan(read(package / 'examples/tail/plan.json'))
    tail = register['tail_algorithm_settings']
    evidence = register['opportunity_algorithm_settings']
    if (evidence['profile_difference_epsilon_kWh'] != EPSILON or evidence['state_witness_epsilon_C'] != EPSILON
            or evidence['readback_energy_epsilon_kWh'] != ENERGY_EPSILON_KWH or evidence['readback_state_epsilon'] != STATE_EPSILON):
        raise ValueError('UNREVIEWED_OPPORTUNITY_NUMERICAL_GUARD')
    if (tail['allowed_features'] != sorted(FEATURES) or tail['service_failure_checks'] != sorted(SERVICE_FAILURES)
            or tail['failure_static_whitelist'] != STRESS_STATIC or tail['prediction_sign_epsilon'] != SIGN_EPSILON):
        raise ValueError('UNREVIEWED_TAIL_CONTRACT')
    if len({r['id'] for r in rights['entries']}) != len(rights['entries']) or any(
            not all(r.get(k) for k in ('material', 'basis', 'permitted_here', 'not_granted', 'status')) for r in rights['entries']):
        raise ValueError('INCOMPLETE_AUTHORIZATION_BOUNDARY')
    return {'passed': True, 'public_legacy_sources': len(sources['legacy_source_pins']),
            'pinned_original_EB_files': len(original['files']), 'generator_defaults': len(LIFE_RULES) + len(DEFAULT_RULES),
            'life_schema_fields': len(schema['fields']), 'public_example_files': len(expected),
            'quantitative_field_groups': sum(len(r['quantitative_fields']) for r in register['public_inputs']),
            'authorization_boundaries': len(rights['entries']), 'legal_or_ethics_clearance_claimed': False,
            'physics_or_production_started': False}


if __name__ == '__main__':
    from .common import canonical
    print(canonical(audit()))
