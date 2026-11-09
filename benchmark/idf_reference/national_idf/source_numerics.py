"""Bound declared numerical changes without weakening source housing protection."""
import copy
import datetime as dt

from .common import ROOT, read, require, sha
from .idf import Fields, objects, parse
from .source_adapter import source_file

WARMUP_FIELDS = ('minimum_number_of_warmup_days', 'maximum_number_of_warmup_days')
WARMUP_TOLERANCE = 'temperature_convergence_tolerance_value'


def warmup_temperature_probe(rows, probe_ref, schema_ref, protocol_ref, *, root=ROOT):
    """One source-bound official convergence setting; no acceptance relaxation."""
    probe = read(source_file(probe_ref, root))
    require(probe.get('schema') == 'national_idf.official_warmup_temperature_probe.v1'
        and probe.get('scope') == 'one_factor_official_warmup_temperature_convergence'
        and probe.get('formal_admitted') is False and probe['engine_schema'] == schema_ref
        and probe['protocol'] == protocol_ref, 'WARMUP_TEMPERATURE_PROBE_NOT_BOUND')
    require(rows == parse(source_file(probe['source_model'], root).read_text()),
            'WARMUP_TEMPERATURE_SOURCE_PRECONDITION')
    schema = read(source_file(schema_ref, root)); fields = Fields(source_file(schema_ref, root))
    building = objects(rows, 'Building'); require(len(building) == 1, 'WARMUP_TEMPERATURE_BUILDING_COUNT')
    require(probe['field'] == WARMUP_TOLERANCE and probe['before'] == fields.get(building[0], WARMUP_TOLERANCE)
        and probe['after'] == '0.01', 'WARMUP_TEMPERATURE_METHOD_NOT_REGISTERED')
    properties = schema['properties']['Building']['patternProperties']['.*']['properties'][WARMUP_TOLERANCE]
    protocol = read(source_file(protocol_ref, root))
    require(protocol_ref['sha256'] == sha(root/'configs/study_protocol.json'), 'NUMERICAL_PROTOCOL_CHANGED')
    value = float(probe['after'])
    require(value > properties['exclusiveMinimum'] and value <= properties['maximum']
        and value < float(probe['before']) and value < protocol['numerical_criteria']['zone_mean_absolute_C'],
        'WARMUP_TEMPERATURE_NOT_STRICTER')
    return probe


def zone_air_solver_probe(rows, probe_ref, schema_ref, protocol_ref, *, root=ROOT):
    """One frozen official integration-method pilot, not a physical override."""
    probe = read(source_file(probe_ref, root))
    require(probe.get('schema') == 'national_idf.official_zone_air_solver_probe.v1'
        and probe.get('scope') == 'one_factor_official_air_heat_balance_integration_pilot'
        and probe.get('formal_admitted') is False and probe['engine_schema'] == schema_ref
        and probe['protocol'] == protocol_ref, 'ZONE_AIR_SOLVER_PROBE_NOT_BOUND')
    require(probe['before'] == ['ZoneAirHeatBalanceAlgorithm', 'ThirdOrderBackwardDifference']
        and probe['after'] == ['ZoneAirHeatBalanceAlgorithm', 'AnalyticalSolution'], 'ZONE_AIR_SOLVER_PROBE_METHOD_NOT_REGISTERED')
    schema = read(source_file(schema_ref, root))
    require('AnalyticalSolution' in schema['properties']['ZoneAirHeatBalanceAlgorithm']['patternProperties']['.*']['properties']['algorithm']['enum'],
        'ZONE_AIR_SOLVER_NOT_IN_OFFICIAL_SCHEMA')
    require(objects(rows, 'ZoneAirHeatBalanceAlgorithm') == [probe['before']], 'ZONE_AIR_SOLVER_SOURCE_PRECONDITION')
    return probe


def plant_iteration_probe(rows, probe_ref, schema_ref, protocol_ref, *, root=ROOT):
    """A source-bound convergence study; no equipment or boundary override."""
    probe = read(source_file(probe_ref, root))
    require(probe.get('schema') == 'national_idf.official_plant_iteration_probe.v1'
        and probe.get('scope') == 'fixed_Guangzhou_plant_iteration_diagnostic'
        and probe.get('formal_admitted') is False and probe['engine_schema'] == schema_ref
        and probe['protocol'] == protocol_ref, 'PLANT_ITERATION_PROBE_NOT_BOUND')
    require(rows == parse(source_file(probe['source_model'], root).read_text())
        and not objects(rows, 'ConvergenceLimits') and probe['before'] == [],
        'PLANT_ITERATION_SOURCE_PRECONDITION')
    minimum = probe.get('minimum_plant_iterations')
    require(type(minimum) is int and minimum in (2, 4, 8)
        and probe['after'] == ['ConvergenceLimits', '1', '20', str(minimum), '8'],
        'PLANT_ITERATION_METHOD_NOT_REGISTERED')
    schema = read(source_file(schema_ref, root))
    fields = Fields(source_file(schema_ref, root))
    properties = schema['properties']['ConvergenceLimits']['patternProperties']['.*']['properties']
    for key, definition in properties.items():
        value = int(fields.get(probe['after'], key))
        require(definition['type'] == 'integer'
            and value >= definition.get('minimum', value)
            and value <= definition.get('maximum', value), 'PLANT_ITERATION_OUTSIDE_OFFICIAL_SCHEMA', key)
    return probe


def registered_warmup_pairs(protocol_ref, root=ROOT):
    protocol = read(source_file(protocol_ref, root))
    require(protocol_ref['sha256'] == sha(root / 'configs/study_protocol.json'), 'NUMERICAL_PROTOCOL_CHANGED')
    minimum, maximum = protocol.get('warmup_min_days'), protocol.get('warmup_max_days')
    require(isinstance(minimum, list) and isinstance(maximum, list) and len(minimum) == len(maximum)
            and minimum and all(type(lo) is int and type(hi) is int and 0 < lo <= hi
                                for lo, hi in zip(minimum, maximum)), 'REGISTERED_WARMUP_PAIRS_MISSING')
    return list(zip(minimum, maximum))


def building_numerical_replacement(before, after, declared, schema_path, protocol_ref, root=ROOT):
    require(before[0] == after[0] == 'Building', 'NUMERICAL_REPLACEMENT_REQUIRES_BUILDING')
    fields = Fields(schema_path)
    names = fields.names('Building')
    require(len(before) <= len(names) + 1 and len(after) <= len(names) + 1, 'BUILDING_UNKNOWN_TRAILING_FIELD')
    require(isinstance(declared, list) and declared and all(isinstance(key, str) for key in declared)
            and len(set(declared)) == len(declared)
            and set(declared) <= set(WARMUP_FIELDS), 'BUILDING_NUMERICAL_FIELD_NOT_ALLOWED')
    changed = [key for key in names if fields.get(before, key) != fields.get(after, key)]
    require(set(changed) == set(declared), 'BUILDING_UNDECLARED_FIELD_EDIT', changed)
    try:
        pair = tuple(int(fields.get(after, key)) for key in WARMUP_FIELDS)
    except (TypeError, ValueError):
        require(False, 'BUILDING_WARMUP_NOT_EXPLICIT_INTEGER')
    require(pair in registered_warmup_pairs(protocol_ref, root), 'BUILDING_WARMUP_PAIR_OUTSIDE_PROTOCOL', pair)
    return {key: {'before': fields.get(before, key), 'after': fields.get(after, key), 'unit': 'days'} for key in changed}


def effective_numerical_context(rows, schema_path, protocol_ref):
    fields = Fields(schema_path)
    return {'protocol': protocol_ref, 'timesteps': objects(rows, 'Timestep'), 'run_periods': objects(rows, 'RunPeriod'),
        'solar_time_integration': objects(rows, 'ShadowCalculation'),
        'building_initialization': [{key: fields.get(row, key) for key in ('name', *WARMUP_FIELDS)}
                                    for row in objects(rows, 'Building')]}


def validate_model_overlay(rows, model_ref, overlay_ref, schema_ref, *, root=ROOT):
    """Allow registered initialization/clock changes, never physical overrides.

    Life installation signatures otherwise bind the exact Building fields.
    This evidence-bound exception is required to test 14 vs 28 warmup days;
    it does not loosen the normal signature or grant model admission.
    """
    from .program_resources import model_signature
    overlay = read(source_file(overlay_ref, root))
    require(overlay.get('schema') == 'national_idf.registered_model_numerical_overlay.v1'
        and overlay.get('formal_admitted') is False and overlay['target_model'] == model_ref,
        'NUMERICAL_OVERLAY_MODEL_NOT_BOUND')
    target = parse(source_file(model_ref, root).read_text())
    require(target == rows, 'NUMERICAL_OVERLAY_TARGET_ROWS_CHANGED')
    source = parse(source_file(overlay['source_model'], root).read_text())
    protocol = read(source_file(overlay['protocol'], root))
    require(overlay['protocol']['sha256'] == sha(root/'configs/study_protocol.json'), 'NUMERICAL_PROTOCOL_CHANGED')
    fields = Fields(source_file(schema_ref, root))
    before, after = objects(source, 'Building'), objects(rows, 'Building')
    require(len(before) == len(after) == 1, 'NUMERICAL_OVERLAY_BUILDING_COUNT')
    pair = tuple(int(fields.get(after[0], name)) for name in WARMUP_FIELDS)
    require(pair in registered_warmup_pairs(overlay['protocol'], root), 'BUILDING_WARMUP_PAIR_OUTSIDE_PROTOCOL')
    changed = [key for key in WARMUP_FIELDS if fields.get(before[0], key) != fields.get(after[0], key)]
    numerical_building = copy.deepcopy(after[0])
    tolerance = None
    if overlay.get('warmup_temperature_probe'):
        tolerance = warmup_temperature_probe(source, overlay['warmup_temperature_probe'], schema_ref,
                                             overlay['protocol'], root=root)
        require(fields.get(after[0], WARMUP_TOLERANCE) == tolerance['after'], 'WARMUP_TEMPERATURE_TARGET_CHANGED')
        fields.set(numerical_building, WARMUP_TOLERANCE, tolerance['before'])
    edits = building_numerical_replacement(before[0], numerical_building, changed,
        source_file(schema_ref, root), overlay['protocol'], root) if changed else {}
    require(edits == overlay['warmup_overlay'], 'NUMERICAL_OVERLAY_EDIT_RECORD_CHANGED')
    canonical = copy.deepcopy(rows)
    for key in WARMUP_FIELDS: fields.set(objects(canonical, 'Building')[0], key, fields.get(before[0], key))
    if tolerance: fields.set(objects(canonical, 'Building')[0], WARMUP_TOLERANCE, tolerance['before'])
    if overlay.get('zone_air_solver_probe'):
        probe = zone_air_solver_probe(source, overlay['zone_air_solver_probe'], schema_ref, overlay['protocol'], root=root)
        require(objects(canonical, 'ZoneAirHeatBalanceAlgorithm') == [probe['after']], 'ZONE_AIR_SOLVER_UNDECLARED_TARGET')
        objects(canonical, 'ZoneAirHeatBalanceAlgorithm')[0][:] = probe['before']
    if overlay.get('plant_iteration_probe'):
        probe = plant_iteration_probe(source, overlay['plant_iteration_probe'], schema_ref,
            overlay['protocol'], root=root)
        require(objects(canonical, 'ConvergenceLimits') == [probe['after']],
            'PLANT_ITERATION_UNDECLARED_TARGET')
        canonical.remove(objects(canonical, 'ConvergenceLimits')[0])
    require(model_signature(canonical) == model_signature(source), 'NUMERICAL_OVERLAY_CHANGED_PHYSICS')
    timesteps, periods = objects(rows, 'Timestep'), objects(rows, 'RunPeriod')
    require(len(timesteps) == len(periods) == 1, 'NUMERICAL_OVERLAY_CLOCK_CARDINALITY')
    step = 60/float(timesteps[0][1])
    require(type(overlay['step_min']) is int and step in protocol['solver_steps_min']
        and step == overlay['step_min'], 'NUMERICAL_OVERLAY_STEP_OUTSIDE_PROTOCOL')
    require(type(overlay['days']) is int and overlay['days'] in (protocol['baseline_duration_days'], protocol['extended_duration_days']),
        'NUMERICAL_OVERLAY_DURATION_OUTSIDE_PROTOCOL')
    begin, end = [dt.date(*[int(fields.get(periods[0], prefix+k)) for k in ('_year', '_month', '_day_of_month')])
        for prefix in ('begin', 'end')]
    require((end-begin).days+1 == overlay['days'], 'NUMERICAL_OVERLAY_CALENDAR_MISMATCH')
    return {'source_model_signature': model_signature(source), 'target_model_signature': model_signature(rows),
        'registered_warmup_pair': list(pair), 'physical_parameters_changed': False, 'formal_admitted': False}
