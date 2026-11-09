"""Fail-closed admission. Evidence review is distinct from a runnable release.

A reusable source assembly compiler is available for explicit engineering
review. Formal execution still needs a validated source/EB runtime release;
a registry flag or a successful engineering build cannot install one.
"""
from __future__ import annotations

from .applicability import bound_location_applicability
from .common import ROOT, AdmissionError, digest, finite, locked, read, require, sha

FORMAL = 'formal'
REFERENCE = 'engineering_reference'
DEVICE_CLASSES = {'air_conditioner', 'washer', 'dryer', 'dishwasher', 'water_heater', 'ev'}
HOUSING_PARTS = {'geometry', 'materials', 'windows', 'floors', 'adjacency'}
REQUIRED_REVIEWS = (
    'source_applicability', 'structure', 'source_baseline_run', 'conversion',
    'equipment_applicability', 'metering_and_energy_balances', 'dynamic_response',
    'numerical_convergence', 'parameter_inventory', 'modification_inventory',
    'weather_and_design_domain', 'life_and_control_support',
)


def reference_only(mode=FORMAL):
    require(mode in (FORMAL, REFERENCE), 'UNKNOWN_EXECUTION_MODE', mode)
    require(mode == REFERENCE, 'ENGINEERING_REFERENCE_MODE_REQUIRED',
            'Historical compiler/runtime only. Use --mode engineering_reference explicitly; formal admission is not inherited.')


def physical_digest(record):
    """Reviews bind the complete physical definition, not their own signatures."""
    return digest({k: v for k, v in record.items() if k not in ('reviews', 'release_status')})


def configuration_failures(record, root=ROOT):
    """Validate proposed release evidence. This does not execute or publish it."""
    failures = []

    def need(ok, code, detail=None):
        if not ok:
            failures.append({'code': code, 'detail': detail})

    def artifact(ref, context):
        try:
            require(isinstance(ref, dict), 'MISSING_ARTIFACT')
            path = (root / ref['path']).resolve()
            require(path.is_relative_to(root.resolve()), 'ARTIFACT_OUTSIDE_PROJECT')
            return locked(ref, root)
        except (AdmissionError, OSError, KeyError, TypeError) as exc:
            failures.append({'code': 'EVIDENCE_ARTIFACT_INVALID', 'detail': [context, str(exc)]})
            return None

    def bundle(ref, context):
        path = artifact(ref, context)
        if path:
            contents = read(path).get('files')
            need(isinstance(contents, dict) and bool(contents), 'BUNDLE_INVENTORY_MISSING', context)
            if isinstance(contents, dict):
                for name, signature in contents.items():
                    artifact({'path': name, 'sha256': signature}, context + ': ' + name)

    need(record.get('release_status') == 'reviewed', 'CONFIGURATION_NOT_REVIEWED')
    housing = record.get('housing') or {}
    package = housing.get('package_id')
    need(bool(package), 'HOUSING_PACKAGE_MISSING')
    need(housing.get('native_format') in ('EnergyPlus', 'OpenStudio'), 'NATIVE_EP_OS_REQUIRED')
    rule_derived = bool(housing.get('rule_construction'))
    need(housing.get('access') == ('public_source_rule_construction' if rule_derived else 'public_direct'),
         'PUBLIC_ORIGINAL_REQUIRED')
    need(bool(housing.get('source_url')) and bool(housing.get('version')), 'HOUSING_VERSION_OR_SOURCE_MISSING')
    target_city = record.get('city')
    city_supported = False
    if rule_derived:
        try:
            from .housing_rules import household_lineage
            city_supported = household_lineage(housing, target_city, root=root)
        except (AdmissionError, OSError, KeyError, TypeError) as exc:
            failures.append({'code': 'HOUSING_RULE_HOUSEHOLD_LINEAGE_INVALID', 'detail': str(exc)})
    else:
        city_supported = bool(target_city) and housing.get('city') == target_city
    if not rule_derived and not city_supported and housing.get('location_applicability'):
        path = artifact(housing['location_applicability'], 'housing applicability in another location')
        if path:
            applicability = read(path)
            city_supported = bound_location_applicability(housing, target_city, applicability)
    need(city_supported, 'HOUSING_CITY_MISMATCH')
    need(housing.get('dwelling_boundary_verified') is True, 'DWELLING_BOUNDARY_UNKNOWN')
    need(housing.get('complete_building_context_preserved') is True, 'BUILDING_CONTEXT_UNSUPPORTED')
    need(housing.get('xy_scale') == 1, 'GEOMETRY_SCALING_NOT_ADMITTED')
    parts = housing.get('part_package_ids') or {}
    need(set(parts) == HOUSING_PARTS and all(v == package for v in parts.values()), 'MIXED_HOUSING_SOURCES')
    bundle(housing.get('bundle_manifest'), 'housing bundle')
    artifact(housing.get('model'), 'housing model')

    engine = record.get('engine') or {}
    need(engine.get('distribution') == 'official' and engine.get('research_patch_applied') is False,
         'OFFICIAL_UNPATCHED_ENGINE_REQUIRED')
    need(bool(engine.get('version')), 'ENGINE_VERSION_MISSING')
    bundle(engine.get('release_manifest'), 'official engine')
    policy = read(root / 'configs/physics_configurations.json')
    if policy.get('engine_freeze_policy') == 'per_configuration':
        # The complete engine definition is already inside physical_digest and
        # all required reviews bind that digest. No other city's original is
        # needed to freeze this configuration's official engine.
        need(bool(engine.get('release_manifest')), 'CONFIGURATION_ENGINE_NOT_PINNED')
    else:
        need(policy.get('frozen_official_engine') is not None and
             engine == policy.get('frozen_official_engine'), 'FORMAL_ENGINE_NOT_FROZEN_OR_MISMATCH')
    need(record.get('numerical_protocol_sha256') == sha(root / 'configs/study_protocol.json'),
         'NUMERICAL_PROTOCOL_CHANGED')

    weather = record.get('weather') or {}
    artifact(weather.get('epw'), 'weather')
    artifact(weather.get('design_days'), 'design days')
    need(weather.get('city') == record.get('city'), 'WEATHER_CITY_MISMATCH')
    identity = weather.get('identity') or {}
    need(all(identity.get(k) is not None for k in
             ('wmo', 'latitude', 'longitude', 'elevation_m', 'timezone', 'terrain_context')),
         'WEATHER_IDENTITY_INCOMPLETE')

    equipment = record.get('equipment') or {}
    need(set(equipment) == DEVICE_CLASSES, 'SIX_COMPONENTS_REQUIRED')
    for name, component in equipment.items():
        key = component.get('model_key')
        need(bool(key) and bool(component.get('version')), 'COMPONENT_IDENTITY_MISSING', name)
        need(component.get('evidence_kind') in ('exact_model', 'public_experimental_model'),
             'COMPONENT_SOURCE_UNSUPPORTED', name)
        bundle(component.get('source_manifest'), name)
        need(component.get('defaults_reviewed') is True, 'UNREVIEWED_COMPONENT_DEFAULTS', name)
    ac = equipment.get('air_conditioner') or {}
    for part in ('low_temperature', 'part_load', 'defrost'):
        evidence = (ac.get('performance_evidence') or {}).get(part) or {}
        need(bool(ac.get('model_key')) and evidence.get('model_key') == ac.get('model_key')
             and evidence.get('version') == ac.get('version'), 'AC_MODEL_OR_VERSION_MISMATCH', part)
        artifact(evidence.get('artifact'), 'AC ' + part)
    domain = ac.get('dry_bulb_domain_C')
    temperatures = [weather.get(k) for k in ('annual_min_C', 'annual_max_C', 'heating_design_C', 'cooling_design_C')]
    valid_domain = (isinstance(domain, list) and len(domain) == 2 and all(finite(v) for v in domain)
                    and domain[0] <= domain[1] and all(finite(v) for v in temperatures))
    if weather.get('operating_scope') is not None:
        need(valid_domain,'WEATHER_TEMPERATURES_OR_AC_DOMAIN_INVALID')
        try:
            from .weather_scope import assess as assess_weather_scope
            assess_weather_scope(record,root=root)
        except (AdmissionError,OSError,KeyError,TypeError,ValueError) as exc:
            need(False,'WEATHER_OPERATING_SCOPE_INVALID',str(exc))
    else:
        need(valid_domain and all(domain[0] <= v <= domain[1] for v in temperatures), 'WEATHER_OUTSIDE_AC_DOMAIN')
    # DB coverage is necessary, not sufficient: WB, humidity, speed, installation,
    # voltage, capacity and defrost compatibility also need the bound reviews.
    need(ac.get('supplemental_heat_W') == 0 or bool(ac.get('supplemental_heat_source')),
         'UNSOURCED_AUXILIARY_HEAT')

    inventory_path = artifact(record.get('parameter_inventory'), 'parameter inventory')
    if inventory_path:
        inventory = read(inventory_path)
        entries = inventory.get('records') or []
        need(bool(entries) and inventory.get('coverage') == 'all_result_affecting_fields', 'PARAMETER_INVENTORY_INCOMPLETE')
        for p in entries:
            need(p.get('value') is not None and p.get('unit') is not None and bool(p.get('locator'))
                 and bool(p.get('field')) and isinstance(p.get('modified'), bool)
                 and bool(p.get('applicable_domain')) and p.get('review_status') == 'accepted',
                 'UNRESOLVED_PHYSICAL_PARAMETER', p.get('id'))
            need(p.get('method') in ('source_value', 'documented_derivation', 'reviewed_source_simplification',
                                     'reviewed_engine_algorithm', 'experiment_design'),
                 'UNSUPPORTED_PARAMETER_METHOD', p.get('id'))
            if p.get('method') == 'experiment_design':
                need(p.get('design_kind') in ('six_classes_present', 'year_round_ac', 'engineering_schedule'),
                     'PHYSICAL_VALUE_DISGUISED_AS_EXPERIMENT_DESIGN', p.get('id'))
            artifact(p.get('source'), 'parameter ' + str(p.get('id')))
            if p.get('engine_default'):
                need(bool(p.get('default_justification')), 'UNREVIEWED_ENGINE_DEFAULT', p.get('id'))
    artifact(record.get('modification_inventory'), 'object additions removals replacements and meter map')

    identity_digest = physical_digest(record)
    for phase in REQUIRED_REVIEWS:
        review = (record.get('reviews') or {}).get(phase) or {}
        path = artifact(review.get('artifact'), phase)
        if path:
            result = read(path)
            need(result.get('status') == 'passed' and result.get('phase') == phase and
                 result.get('physical_definition_sha256') == identity_digest,
                 'REVIEW_FAILED_OR_STALE', phase)
            checks = result.get('checks')
            need(bool(result.get('scope')) and isinstance(checks, dict) and bool(checks),
                 'REVIEW_SCOPE_MISSING', phase)
            need(isinstance(checks, dict) and bool(checks) and all(v is True for v in checks.values()),
                 'REVIEW_HAS_UNPASSED_CHECKS', phase)
    comparison = record.get('author_output_comparison') or {}
    need(comparison.get('status') in ('compared', 'not_available'), 'AUTHOR_COMPARISON_STATUS_REQUIRED')
    if comparison.get('status') == 'compared':
        artifact(comparison.get('artifact'), 'author comparison')
    else:
        need(bool(comparison.get('limitation')), 'AUTHOR_COMPARISON_LIMITATION_REQUIRED')
    return failures


def assess_formal(case, *, root=ROOT, today=None):
    from .request_support import assess_inputs, bind_domain
    input_screen = assess_inputs(case, root=root)
    failures = []
    registry = read(root / 'configs/physics_configurations.json')
    environment = case.get('environment') if isinstance(case, dict) else None
    identifier = environment.get('physics_configuration_id') if isinstance(environment, dict) else None
    matches = [r for r in registry['records'] if r['id'] == identifier]
    if len(matches) != 1:
        failures.append({'code': 'PHYSICS_CONFIGURATION_NOT_REGISTERED', 'detail': identifier})
    else:
        try:
            failures.extend(configuration_failures(matches[0], root))
            domain = bind_domain(matches[0], root)
            input_screen = assess_inputs(case, domain, root)
        except (ValueError, OSError, KeyError, TypeError) as exc:
            failures.append({'code': 'CONFIGURATION_EVIDENCE_MALFORMED', 'detail': str(exc)})
    failures.extend(input_screen['failures'])
    if not failures:
        try:
            from .runtime_release import reviewed_runtime
            reviewed_runtime(identifier,root=root,today=today)
        except (ValueError,OSError,KeyError,TypeError) as exc:
            failures.append({'code':'FORMAL_RUNTIME_RELEASE_NOT_VALIDATED','detail':str(exc)})
    admitted = not failures
    return {'schema': 'national_idf.support_screen.v2', 'execution_mode': FORMAL,
            'physics_configuration_id': identifier, 'source_input_supported': admitted,
            'formal_admitted': admitted, 'formal_configuration_count':len(registry['records']),
            'input_screen': input_screen,
            'failures': failures, 'physical_validity_inferred_from_software_checks': False}


def guard_case(case, mode=FORMAL):
    require(mode in (FORMAL, REFERENCE), 'UNKNOWN_EXECUTION_MODE', mode)
    if mode == FORMAL:
        result = assess_formal(case)
        require(result['formal_admitted'],'FORMAL_ADMISSION_BLOCKED',result['failures'])
        raise AdmissionError('FORMAL_REQUIRES_SOURCE_RUNTIME_ENTRY',
            'Use household-run/source-EB-compile/source-EB-run; the legacy v1 engine path cannot execute a v2 configuration.')
    require(case.get('schema') == 'national_idf.case.v1', 'REFERENCE_REQUIRES_LEGACY_V1',
            'A v2 configuration must never fall back to the legacy compiler.')
