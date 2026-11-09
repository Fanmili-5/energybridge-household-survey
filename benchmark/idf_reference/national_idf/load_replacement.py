"""Replace a whole unallocated plug-load aggregate with explicit source objects.

No estimate of the old aggregate's appliance fractions or unknown residual is
used. People and lighting remain outside this electrical replacement scope.
"""
import copy
import re

from .common import ROOT, read, require, sha
from .idf import Fields, objects, parse
from .source_adapter import equipment_zone, housing_fingerprint, selected, source_file

REQUIRED = {'washer', 'dryer', 'dishwasher', 'refrigerator', 'electric_cooking', 'other_plugs', 'television'}


def apply(rows, pack_ref, schema_ref, *, root=ROOT):
    pack = read(source_file(pack_ref, root))
    empty_fixture = pack.get('schema') == 'national_idf.empty_enclosure_plug_installation.v1'
    require((empty_fixture or pack.get('schema') == 'national_idf.whole_plug_load_replacement.v1')
            and pack['mode'] == 'controlled_reference_fixed_background'
            and set(pack['components']) == REQUIRED, 'LOAD_REPLACEMENT_SCOPE_NOT_COMPLETE')
    require(pack['residual_old_aggregate'] == ('none_source_enclosure_has_no_load_objects' if empty_fixture else 'none_entire_object_removed')
            and pack['original_aggregate_breakdown_inferred'] is False
            and pack['floor_area_scaling_applied'] is False, 'LOAD_REPLACEMENT_CANNOT_INFER_RESIDUAL')
    original = parse(source_file(pack['target_model'], root).read_text())
    old = None
    if empty_fixture:
        require(pack['remove_aggregate'] is None and not pack.get('retire_explicit_objects'),
                'EMPTY_ENCLOSURE_CANNOT_RETIRE_UNREVIEWED_LOAD')
        kinds = {'electricequipment','gasequipment','otherequipment','hotwaterequipment',
                 'steamequipment','people','lights'}
        require(not any(r[0].casefold() in kinds for r in original+rows),
                'EMPTY_ENCLOSURE_CONTAINS_ORIGINAL_OR_NEW_LOAD')
        scope = read(source_file(pack['source_operation_replacement'], root))
        require(scope.get('schema') == 'national_idf.native_operation_replacement.v1' and
                scope.get('target_model') == pack['target_model'] and
                scope.get('source_operational_reproduction') is False and
                scope.get('formal_admitted') is False and scope.get('excluded_source_tables'),
                'EMPTY_ENCLOSURE_OPERATION_REPLACEMENT_NOT_DECLARED')
        for evidence in scope['excluded_source_tables'].values(): source_file(evidence, root)
    else:
        old = selected(original, pack['remove_aggregate'])
        require(old[0] == 'ElectricEquipment' and rows.count(old) == 1, 'LOAD_REPLACEMENT_AGGREGATE_PRECONDITION')
    fields = Fields(source_file(schema_ref, root))
    models = [binding['model'] for binding in pack['components'].values()]
    require(all(model == models[0] for model in models), 'LOAD_REPLACEMENT_REQUIRES_ONE_COHERENT_SOURCE_PACK')
    target = pack.get('installation_target', pack['installation_zone'])
    require(equipment_zone(rows, target, fields) == pack['installation_zone'], 'LOAD_REPLACEMENT_ZONE')
    result = copy.deepcopy(rows)
    if old is not None: result.remove(old)
    retired = []
    for item in pack.get('retire_explicit_objects', []):
        row = selected(original, item)
        require(row[0] == 'ElectricEquipment' or row[0].startswith('EnergyManagementSystem:'),
                'LOAD_REPLACEMENT_UNSUPPORTED_RETIREMENT')
        require(result.count(row) == 1, 'LOAD_REPLACEMENT_RETIREMENT_PRECONDITION')
        result.remove(row); retired.append(row)
    dependencies, inserted, schedules, types = {}, [], {}, {}
    equipment_names, schedule_names = {}, {}
    for role, binding in pack['components'].items():
        source_rows = parse(source_file(binding['model'], root).read_text())
        device = selected(source_rows, binding['equipment'])[:]
        require(device[0] == 'ElectricEquipment' and fields.get(device, 'design_level_calculation_method') == 'EquipmentLevel',
                'SOURCE_LOAD_NOT_EXPLICIT_EQUIPMENT_LEVEL', role)
        original_device = device[:]
        source_schedule = fields.get(device, 'schedule_name')
        equipment_names[original_device[1]] = binding['output_name']
        schedule_names[source_schedule] = binding['output_schedule']
        matches = [r for r in source_rows if r[0] in ('Schedule:File', 'Schedule:Constant') and r[1] == source_schedule]
        require(len(matches) == 1, 'LOAD_REPLACEMENT_SOURCE_SCHEDULE')
        schedule = matches[0][:]
        limits = [r for r in objects(source_rows, 'ScheduleTypeLimits') if r[1] == schedule[2]]
        require(len(limits) == 1, 'SOURCE_SCHEDULE_LIMITS_MISSING')
        limit = limits[0][:]; limit[1] = binding['output_type_limits']
        require(limit[1] not in types or types[limit[1]] == limit, 'SOURCE_SCHEDULE_LIMIT_CONFLICT')
        types[limit[1]] = limit
        schedule[1], schedule[2] = binding['output_schedule'], limit[1]
        if schedule[0] == 'Schedule:File':
            source_csv = source_file(binding['schedule_file'], root)
            original_csv = source_file(binding['model'], root).parent / schedule[3]
            require(original_csv.is_file() and sha(original_csv) == sha(source_csv), 'LOAD_REPLACEMENT_SCHEDULE_NOT_FROM_SOURCE_MODEL')
            path = f'assets/{sha(source_csv)}{source_csv.suffix}'
            schedule[3] = path
            dependencies[path] = {'source': binding['schedule_file'], 'output_path': path}
        else:
            require(role == 'refrigerator' and binding.get('EMS_controller'), 'CONSTANT_ZERO_FRIDGE_REQUIRES_SOURCE_CONTROLLER')
        if schedule[1] in schedules:
            require(schedules[schedule[1]] == schedule, 'LOAD_REPLACEMENT_SHARED_SCHEDULE_CONFLICT')
        else:
            schedules[schedule[1]] = schedule; result.append(schedule)
        device[1], device[2], device[3] = binding['output_name'], target, binding['output_schedule']
        # Every numeric field and source thermal partition is preserved.
        require(device[4:] == original_device[4:], 'LOAD_REPLACEMENT_CHANGED_DEVICE_PHYSICS')
        result.append(device)
        if binding.get('EMS_controller'):
            controls = [selected(source_rows, item)[:] for item in binding['EMS_controller']]
            require(len(controls) == 4 and {row[0] for row in controls} == {
                'EnergyManagementSystem:Sensor', 'EnergyManagementSystem:Actuator',
                'EnergyManagementSystem:Program', 'EnergyManagementSystem:ProgramCallingManager'}, 'SOURCE_FRIDGE_CONTROLLER_INCOMPLETE')
            names = {row[1]: binding['EMS_prefix'] + row[1] for row in controls}
            token = re.compile(r'\b(' + '|'.join(map(re.escape, sorted(names, key=len, reverse=True))) + r')\b')
            for row in controls:
                row[1] = names[row[1]]
                if row[0] == 'EnergyManagementSystem:Sensor':
                    require(row[3] == 'Zone Mean Air Temperature', 'UNSUPPORTED_BACKGROUND_SENSOR')
                    row[2] = pack['installation_zone']
                elif row[0] == 'EnergyManagementSystem:Actuator':
                    require(row[2:] == [source_schedule, 'Schedule:Constant', 'Schedule Value'], 'UNSUPPORTED_BACKGROUND_ACTUATOR')
                    row[2] = binding['output_schedule']
                else:
                    row[2:] = [token.sub(lambda m: names[m[0]], value) for value in row[2:]]
                result.append(row)
        inserted.append({'role': role, 'source': binding['model'], 'source_object': binding['equipment'],
                         'before': original_device, 'after': device, 'source_controller_retained': bool(binding.get('EMS_controller'))})
    reporting = []
    for row in result:
        if row[0] == 'Output:Variable':
            mapping = equipment_names if row[2].startswith('Electric Equipment ') else schedule_names if row[2] == 'Schedule Value' else {}
            if row[1] in mapping:
                before = row[:]; row[1] = mapping[row[1]]; reporting.append({'before': before, 'after': row[:]})
    # The source schedule type is an explicit dependency, not a new invented
    # limit. Same-named, conflicting limits must be resolved in a new package.
    for name, row in types.items():
        limits = [row]
        existing = [r for r in objects(result, 'ScheduleTypeLimits') if r[1] == name]
        require(not existing or existing == limits, 'LOAD_REPLACEMENT_SCHEDULE_LIMIT_CONFLICT')
        if not existing:
            result.append(limits[0][:])
    keys = [('Schedule' if r[0].startswith('Schedule:') else r[0], r[1].casefold())
            for r in result if r[0] == 'ElectricEquipment' or r[0].startswith('Schedule:')]
    require(len(keys) == len(set(keys)), 'LOAD_REPLACEMENT_DUPLICATE_OBJECT')
    require(housing_fingerprint(result) == housing_fingerprint(rows), 'LOAD_REPLACEMENT_CHANGED_HOUSING')
    return result, {'pack': pack_ref, 'removed_whole_aggregate': old, 'other_explicit_retired_objects': retired,
        'empty_enclosure_installation': empty_fixture,
        'inserted': inserted, 'reporting_reference_rebindings': reporting,
        'old_aggregate_breakdown_remains_unknown': True, 'arbitrary_residual_created': False,
        'mode': pack['mode'], 'Chinese_population_background_calibrated': False,
        'scope': 'Declared experimental reference replacement; public source schedules are engineering fixtures, not generated family behaviour',
        'formal_admitted': False}, list(dependencies.values())
