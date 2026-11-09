"""Separate reference experiments from strict survey-housing matching."""
from __future__ import annotations

import copy

from .common import ROOT, digest, read, require
from .source_adapter import source_file

FUNCTIONS = {'AC': 'air_conditioner', 'WM': 'washer', 'DR': 'dryer',
             'DW': 'dishwasher', 'WH': 'water_heater', 'EV': 'ev'}


def countries_from_projection(projection_ref, *, root=ROOT):
    projection = read(source_file(projection_ref, root))
    require(projection.get('schema') == 'national_idf.household_interface_projection.v1', 'REFERENCE_INPUT_SCHEMA')
    records = projection['households']
    return sorted({h['country'] for h in records})


def inventory(value):
    """No inference that an uncontrolled device is absent, or vice versa."""
    require(set(value) == set(FUNCTIONS), 'REFERENCE_INVENTORY_SIX_FUNCTIONS_REQUIRED')
    for key, device in value.items():
        require(type(device.get('physically_present')) is bool or device.get('physically_present') is None,
                'REFERENCE_PRESENCE_INVALID')
        require(type(device.get('control_enabled')) is bool, 'REFERENCE_CONTROL_FLAG_REQUIRED')
        require(not device['control_enabled'] or device['physically_present'] is True,
                'REFERENCE_CONTROL_WITHOUT_PHYSICAL_DEVICE', key)
        if device['physically_present'] is not None:
            require(device.get('presence_basis'), 'REFERENCE_ASSET_PROVENANCE_REQUIRED', key)
        if device['physically_present'] is True:
            require(device.get('asset_id'), 'REFERENCE_ASSET_PROVENANCE_REQUIRED', key)
        if device['physically_present'] and not device['control_enabled']:
            require(device.get('background_service_id'), 'REFERENCE_BACKGROUND_SERVICE_UNDECLARED', key)
    return {'installed': [FUNCTIONS[k] for k in FUNCTIONS if value[k]['physically_present'] is True],
            'controlled': [FUNCTIONS[k] for k in FUNCTIONS if value[k]['control_enabled']],
            'unknown_presence': [k for k in FUNCTIONS if value[k]['physically_present'] is None]}


def resolve(request, catalog_ref, *, root=ROOT):
    require(request.get('schema') == 'national_idf.reference_scenario_request.v1', 'REFERENCE_REQUEST_SCHEMA')
    require(request.get('purpose') == 'roleplay_control_reference', 'REFERENCE_PURPOSE_UNSUPPORTED')
    catalog = read(source_file(catalog_ref, root))
    require(catalog.get('schema') == 'national_idf.reference_scenario_catalog.v1', 'REFERENCE_CATALOG_SCHEMA')
    observed = copy.deepcopy(request.get('survey_dwelling', {}))
    selection = request.get('reference_selection', {})
    candidates, gaps = [], []
    inv = inventory(request['equipment'])
    for record in catalog['records']:
        if record['country'] != request['country']:
            continue
        if selection.get('physics_configuration_id') and record['id'] != selection['physics_configuration_id']:
            continue
        if selection.get('housing_class') and record['housing_class'] != selection['housing_class']:
            continue
        missing = list(record.get('gaps', []))
        missing += [{'code': 'EQUIPMENT_PRESENCE_UNKNOWN', 'function': k} for k in inv['unknown_presence']]
        if sorted(inv['installed']) != sorted(record['installed_devices']):
            missing.append({'code': 'PHYSICAL_DEVICE_CONFIGURATION_NOT_AVAILABLE'})
        if not set(inv['controlled']) <= set(record['controllable_devices']):
            missing.append({'code': 'CONTROL_CONFIGURATION_NOT_AVAILABLE'})
        patterns = record.get('reviewed_control_patterns')
        if record.get('reviewed') and patterns is not None and sorted(inv['controlled']) not in [sorted(v) for v in patterns]:
            missing.append({'code': 'CONTROL_PATTERN_NOT_REVIEWED', 'detail': 'Fixed/background and shared-service contracts need their own reviewed scope'})
        candidates.append({'physics_configuration_id': record['id'], 'representation_kind': record['representation_kind'],
                           'reference_dwelling': record['reference_dwelling'], 'gaps': missing,
                           'reviewed': record.get('reviewed', False), 'support_scope': record['support_scope'],
                           'reference_release': record.get('reference_release'),
                           'new_CASE_requires_its_own_quality_check': bool(record.get('reference_release')),
                           'compiled_configuration': record.get('compiled_configuration')})
    if not candidates:
        gaps.append({'code': 'NO_REGISTERED_REFERENCE_SCENARIO'})
    ready = [v for v in candidates if not v['gaps'] and v['reviewed']]
    # Explicit selection/consent: a surveyed apartment is never silently replaced
    # by a detached reference just because the country matches.
    explicit = bool(selection.get('physics_configuration_id') and selection.get('acknowledge_reference_not_survey_home'))
    if candidates and not explicit:
        gaps.append({'code': 'EXPLICIT_REFERENCE_SELECTION_REQUIRED'})
    return {'schema': 'national_idf.reference_scenario_resolution.v1', 'country': request['country'],
            'survey_dwelling': observed, 'survey_dwelling_sha256': digest(observed),
            'reference_candidates': candidates, 'gaps': gaps,
            'physics_configuration_id': ready[0]['physics_configuration_id'] if explicit and len(ready) == 1 else None,
            'status': 'resolved' if explicit and len(ready) == 1 else 'candidate_or_missing_evidence',
            'survey_facts_modified': False, 'strict_housing_match_bypassed': False,
            'national_stock_representativeness_claimed': False}


def validate_shared_asset_intervals(tasks, equipment, *, fixed_service_tasks=()):
    """Validate one physical asset across controlled and fixed service tasks."""
    spans = []
    all_tasks = [*fixed_service_tasks, *tasks]
    by_id = {t['id']: t for t in all_tasks}
    require(len(by_id) == len(all_tasks), 'REFERENCE_DUPLICATE_TASK_ID')
    for task in all_tasks:
        require(task['function'] in equipment, 'REFERENCE_TASK_FUNCTION_UNKNOWN')
        asset = equipment[task['function']]['asset_id']
        require(equipment[task['function']]['physically_present'] is True, 'REFERENCE_TASK_DEVICE_ABSENT')
        start, end = task['start_elapsed_min'], task['end_elapsed_min']
        require(type(start) is int and type(end) is int and 0 <= start < end, 'REFERENCE_TASK_INTERVAL')
        for other_asset, a, b in spans:
            require(asset != other_asset or max(a, start) >= min(b, end), 'REFERENCE_SHARED_ASSET_OVERLAP', asset)
        spans.append((asset, start, end))
        for predecessor in task.get('after_tasks', []):
            require(predecessor in by_id and by_id[predecessor]['end_elapsed_min'] <= start,
                    'REFERENCE_WASH_BEFORE_DRY_DEPENDENCY', task['id'])
    return {'tasks_checked': len(all_tasks), 'shared_asset_exclusivity_checked': True,
            'declared_dependencies_checked': True, 'dryness_or_cleaning_verified': False}
