"""Validate demand/control syntax and a separately reviewed fixed support domain."""
import datetime as dt
import math
from pathlib import Path

import jsonschema

from .common import ROOT, finite, read, require, verify
from .idf import Fields, objects, parse
from .initialization import bind_initialization, requested_initialization
from .source_adapter import source_file

PROGRAMS = ('washer', 'dryer', 'dishwasher')
CONTROL_FIELDS = ('heating_C', 'cooling_C', 'tank_target_C', 'ev_target_SOC')


def syntax_failures(case, root=ROOT):
    schema = read(root / ('configs/CASE.v3.schema.json' if case.get('schema')=='national_idf.case.v3' else 'configs/CASE.v2.schema.json'))
    validator = jsonschema.Draft202012Validator(schema, format_checker=jsonschema.FormatChecker())
    failures = [{'code': 'FORMAL_INPUT_SCHEMA', 'path': list(e.absolute_path), 'detail': e.message}
                for e in validator.iter_errors(case)]

    def walk(value, path):
        if type(value) is float and not math.isfinite(value):
            failures.append({'code': 'FORMAL_INPUT_NONFINITE', 'path': path})
        elif isinstance(value, dict):
            for key, item in value.items():
                walk(item, path + [key])
        elif isinstance(value, list):
            for i, item in enumerate(value):
                walk(item, path + [i])

    walk(case, [])
    return failures


def bind_domain(record, root=ROOT):
    """A domain is part of physical_digest, hence covered by all bound reviews.

    No bounds are guessed from names, existing households or source examples.
    This check does not itself establish that the bound reviews have passed.
    """
    root = Path(root).resolve()
    ref = record.get('runtime_support_domain')
    require(ref is not None, 'RUNTIME_SUPPORT_DOMAIN_MISSING')
    domain = read(source_file(ref, root))
    require(domain.get('schema') == 'national_idf.runtime_support_domain.v2'
            and domain.get('physics_configuration_id') == record['id'], 'RUNTIME_DOMAIN_IDENTITY')
    expected_model = record['housing'].get('assembly_model', record['housing']['model'])
    require(domain.get('source_model') == expected_model, 'RUNTIME_DOMAIN_SOURCE_MODEL_NOT_BOUND')
    require(domain.get('numerical_protocol_sha256') == record['numerical_protocol_sha256'], 'RUNTIME_DOMAIN_PROTOCOL_NOT_BOUND')
    # Input support belongs to the finished, reviewed assembly. Its RunPeriod,
    # Timestep and control objects may be explicit blueprint modifications of
    # the original. Looking at the raw source here can validate the wrong clock
    # and can never validate an intentionally changed numerical timestep.
    source_file(expected_model, root)
    release_ref = (record.get('reviews', {}).get('source_compiler_release') or {}).get('artifact')
    require(release_ref is not None, 'RUNTIME_DOMAIN_ASSEMBLY_RELEASE_MISSING')
    release = read(source_file(release_ref, root))
    manifest_path = source_file(release['validated_assembly_manifest'], root)
    require(manifest_path.name == 'MANIFEST.json', 'RUNTIME_DOMAIN_ASSEMBLY_MANIFEST_NAME')
    manifest = verify(manifest_path.parent)
    require(manifest.get('schema') == 'national_idf.assembled_reference.v1'
            and manifest.get('id') == record['source_assembly']['id'], 'RUNTIME_DOMAIN_ASSEMBLY_IDENTITY')
    assembled = {'path': str((manifest_path.parent / 'in.idf').relative_to(root)),
                 'sha256': manifest['files']['in.idf']}
    require(domain.get('assembled_model') == assembled, 'RUNTIME_DOMAIN_ASSEMBLED_MODEL_NOT_BOUND')
    model = parse(source_file(assembled, root).read_text())
    engine_bundle = read(source_file(record['engine']['release_manifest'], root))
    schema = record['engine'].get('schema')
    require(schema and engine_bundle['files'].get(schema['path']) == schema['sha256'],
            'RUNTIME_DOMAIN_ENGINE_SCHEMA_NOT_BOUND')
    fields = Fields(source_file(schema, root))
    runs = objects(model, 'RunPeriod')
    require(len(runs) == 1, 'RUNTIME_DOMAIN_RUN_PERIOD_AMBIGUOUS')
    try:
        dates = {name: dt.date(*[int(fields.get(runs[0], k)) for k in keys]).isoformat()
                 for name, keys in [('start_date', ['begin_year', 'begin_month', 'begin_day_of_month']),
                                    ('end_date', ['end_year', 'end_month', 'end_day_of_month'])]}
    except (ValueError, TypeError):
        require(False, 'RUNTIME_DOMAIN_EXPLICIT_CALENDAR_MISSING')
    require(domain.get('run_period') == dates, 'RUNTIME_DOMAIN_CALENDAR_NOT_BOUND')
    expected_weekday = dt.date.fromisoformat(dates['start_date']).strftime('%A')
    require(fields.get(runs[0], 'day_of_week_for_start_day').casefold() == expected_weekday.casefold(),
            'RUNTIME_DOMAIN_EXPLICIT_WEEKDAY_MISMATCH')
    protocol_ref = {'path': 'configs/study_protocol.json', 'sha256': record['numerical_protocol_sha256']}
    bind_initialization(domain, model, fields, protocol_ref, root)
    zones = [r[1] for r in objects(model, 'Zone')]
    require(domain.get('thermal_zones') and len(set(domain['thermal_zones'])) == len(domain['thermal_zones'])
            and set(domain['thermal_zones']) <= set(zones), 'RUNTIME_DOMAIN_ZONE_MAPPING')
    steps = objects(model, 'Timestep')
    require(len(steps) == 1 and domain.get('solver_step_min') in (1, 2, 5)
            and float(steps[0][1]) * domain['solver_step_min'] == 60, 'RUNTIME_DOMAIN_STEP_NOT_BOUND')
    grid = domain.get('command_grid_min')
    require(type(grid) is int and grid > 0 and 1440 % grid == 0
            and grid % domain['solver_step_min'] == 0, 'RUNTIME_DOMAIN_COMMAND_GRID')
    for key in ('maximum_persons', 'max_water_flow_L_min'):
        require(finite(domain.get(key)) and domain[key] >= 0, 'RUNTIME_DOMAIN_VALUE_MISSING', key)
    for field in CONTROL_FIELDS + ('water_target_C', 'activity_W'):
        bounds = domain.get('bounds', {}).get(field)
        require(isinstance(bounds, list) and len(bounds) == 2 and all(finite(v) for v in bounds)
                and bounds[0] <= bounds[1], 'RUNTIME_DOMAIN_VALUE_MISSING', field)
    fixed = domain.get('fixed_life_values')
    require(isinstance(fixed, dict) and set(fixed) == {'lighting_W_m2', 'misc_W_m2'}
            and all(finite(v) and v >= 0 for v in fixed.values()), 'RUNTIME_DOMAIN_FIXED_LOADS_MISSING')
    programs = domain.get('programs')
    require(isinstance(programs, dict) and set(programs) == set(PROGRAMS), 'RUNTIME_DOMAIN_PROGRAMS_MISSING')
    for key, program in programs.items():
        equipment = record['equipment'][key]
        require(program.get('model_key') == equipment['model_key'] and program.get('version') == equipment['version'],
                'RUNTIME_DOMAIN_PROGRAM_MODEL_MISMATCH', key)
        require(type(program.get('duration_min')) in (int, float) and finite(program['duration_min'])
                and program['duration_min'] > 0, 'RUNTIME_DOMAIN_PROGRAM_DURATION_MISSING', key)
        source_file(program['evidence'], root)
    require(domain.get('evidence'), 'RUNTIME_DOMAIN_EVIDENCE_MISSING')
    for item in domain['evidence']:
        source_file(item, root)
    return domain


def _assess_v2_inputs(case, domain=None, root=ROOT):
    failures = syntax_failures(case, root)
    issues = []
    result = {'schema': 'national_idf.runtime_input_screen.v1', 'syntax_valid': not failures,
              'support_domain_checked': domain is not None, 'inputs_supported': False,
              'formal_admitted': False, 'failures': failures, 'service_issues': issues,
              'defaults_or_household_routines_created': False}
    if failures:
        return result
    life, controls = case['life'], case['controls']
    begin = dt.date.fromisoformat(case['run']['start_date'])
    end = dt.date.fromisoformat(case['run']['end_date'])

    def check(ok, code, path, detail=None):
        if not ok:
            failures.append({'code': code, 'path': path, 'detail': detail})

    date_valid = begin <= end and begin.year == end.year
    check(date_valid, 'RUN_DATE_RANGE', ['run'])
    if not date_valid:
        return result
    check(controls['heating_C'] < controls['cooling_C'], 'CROSSED_SETPOINTS', ['controls'])
    check(life['ev_daily']['departure_min'] < life['ev_daily']['return_min'], 'EV_DAILY_TRIP_INTERVAL', ['life', 'ev_daily'])

    def intervals(values, path, *, nonoverlap=True):
        for i, value in enumerate(values):
            check(value['start_min'] < value['end_min'], 'EMPTY_OR_REVERSED_INTERVAL', path + [i])
        if nonoverlap:
            ordered = sorted(values, key=lambda x: x['start_min'])
            check(all(a['end_min'] <= b['start_min'] for a, b in zip(ordered, ordered[1:])),
                  'OVERLAPPING_INTERVALS', path)

    intervals(life['ev_connection_daily'], ['life', 'ev_connection_daily'])
    departure, returned = life['ev_daily']['departure_min'], life['ev_daily']['return_min']
    for i, value in enumerate(life['ev_connection_daily']):
        check(value['end_min'] <= departure or value['start_min'] >= returned,
              'EV_CONNECTED_DURING_DECLARED_TRIP', ['life', 'ev_connection_daily', i])
    intervals(controls['ev_daily_windows'], ['controls', 'ev_daily_windows'])
    for key in ('program_start_overrides', 'ev_window_overrides'):
        for date, value in controls.get(key, {}).items():
            check(begin <= dt.date.fromisoformat(date) <= end, 'OVERRIDE_OUTSIDE_RUN', ['controls', key, date])
            if key == 'ev_window_overrides':
                intervals(value, ['controls', key, date])
    for date in life.get('mixed_water_overrides', {}):
        check(begin <= dt.date.fromisoformat(date) <= end, 'OVERRIDE_OUTSIDE_RUN', ['life', 'mixed_water_overrides', date])
    for i, value in enumerate(controls.get('dated_overrides', [])):
        check(begin <= dt.date.fromisoformat(value['date']) <= end, 'OVERRIDE_OUTSIDE_RUN', ['controls', 'dated_overrides', i])
    for key in ('daily_overrides', 'dated_overrides'):
        for i, value in enumerate(controls.get(key, [])):
            intervals([value], ['controls', key, i])
        groups = {}
        for value in controls.get(key, []):
            groups.setdefault((value.get('date'), value['field']), []).append(value)
        for identity, values in groups.items():
            intervals(values, ['controls', key, str(identity)])
    for device, need in life['services_daily'].items():
        check(need['release_min'] < need['deadline_min'], 'SERVICE_WINDOW_REVERSED', ['life', 'services_daily', device])
    occupancies = [('occupancy', life['occupancy'])] + [
        (field + '.' + day, rows) for field in ('occupancy_weekly', 'occupancy_recovery_weekly')
        for day, rows in life.get(field, {}).items()]
    for label, rows in occupancies:
        people = [0.0] * 1440
        for i, value in enumerate(rows):
            intervals([value], ['life', label, i])
            for minute in range(value['start_min'], value['end_min']):
                people[minute] += value['persons']
        check(max(people, default=0) <= life['maximum_persons'], 'PERSON_DOUBLE_COUNT', ['life', label])
    if domain is None:
        failures.append({'code': 'RUNTIME_SUPPORT_DOMAIN_NOT_BOUND', 'path': ['environment']})
        return result
    check(case['environment']['physics_configuration_id'] == domain['physics_configuration_id'], 'RUNTIME_DOMAIN_IDENTITY', ['environment'])
    check(domain['run_period']['start_date'] <= case['run']['start_date'] <= case['run']['end_date']
          <= domain['run_period']['end_date'], 'RUN_OUTSIDE_BOUND_CALENDAR', ['run'])
    initial = requested_initialization(case, domain)
    result['initialization_support'] = initial
    if domain.get('schema') == 'national_idf.runtime_support_domain.v2':
        check(initial['supported'], 'RUN_INITIALIZATION_WINDOW_NOT_REVIEWED', ['run'])
    grid = domain['command_grid_min']

    def on_grid(value, path):
        check(value % grid == 0, 'COMMAND_OUTSIDE_BOUND_GRID', path, grid)

    def bounded(field, value, path):
        lo, hi = domain['bounds'][field]
        check(lo <= value <= hi or value in domain.get('special_control_values', {}).get(field, []), 'RUNTIME_VALUE_OUTSIDE_SUPPORT', path, [lo, hi])

    for key, value in domain['fixed_life_values'].items():
        check(life[key] == value, 'FIXED_PHYSICAL_LOAD_OVERRIDE', ['life', key], value)
    check(life['maximum_persons'] <= domain['maximum_persons'], 'DESIGN_PERSON_ENVELOPE_EXCEEDED', ['life', 'maximum_persons'])
    for field in CONTROL_FIELDS:
        bounded(field, controls[field], ['controls', field])
    for label, rows in occupancies:
        for i, person in enumerate(rows):
            check(person['room_id'] in domain['thermal_zones'], 'SOURCE_ZONE_UNKNOWN', ['life', label, i, 'room_id'])
            bounded('activity_W', person['activity_W'], ['life', label, i, 'activity_W'])
            if label == 'occupancy':
                for field in ('start_min', 'end_min'):
                    on_grid(person[field], ['life', label, i, field])
    for field in ('departure_min', 'return_min'):
        on_grid(life['ev_daily'][field], ['life', 'ev_daily', field])
    for key, values in [('connections', life['ev_connection_daily']), ('charge_windows', controls['ev_daily_windows'])]:
        for i, value in enumerate(values):
            for field in ('start_min', 'end_min'):
                on_grid(value[field], [key, i, field])
    dates = [begin + dt.timedelta(days=i) for i in range(max(0, (end - begin).days + 1))]
    program_clock = {device: [] for device in PROGRAMS}
    for day_index, date in enumerate(dates):
        day = date.isoformat()
        heat = [controls['heating_C']] * 1440
        cool = [controls['cooling_C']] * 1440
        applied = controls['daily_overrides'] + [r for r in controls.get('dated_overrides', []) if r['date'] == day]
        for i, override in enumerate(applied):
            for field in ('start_min', 'end_min'):
                on_grid(override[field], ['controls', day, i, field])
            field, value = override['field'], override['value']
            if field in CONTROL_FIELDS:
                bounded(field, value, ['controls', day, i, 'value'])
            if field in ('heating_C', 'cooling_C'):
                target = heat if field == 'heating_C' else cool
                target[override['start_min']:override['end_min']] = [value] * (override['end_min'] - override['start_min'])
        check(all(h < c for h, c in zip(heat, cool)), 'OVERRIDE_CROSSED_SETPOINTS', ['controls', day])
        starts = {**controls['program_starts_daily'], **controls.get('program_start_overrides', {}).get(day, {})}
        for device in PROGRAMS:
            duration = domain['programs'][device].get('duration_min')
            ordered = sorted(starts[device])
            maximum = domain['programs'][device].get('max_starts_per_day')
            if maximum is not None:
                check(type(maximum) is int and maximum > 0 and len(ordered) <= maximum,
                      'PROGRAM_DAILY_START_LIMIT', ['controls', day, device], maximum)
            need = life['services_daily'][device]
            # Component-only probes can leave unused programmes unknown. This
            # never passes bind_domain for a formal six-device configuration.
            # A demand or start still requires a supported programme, and must
            # fail explicitly rather than inventing a duration or raising TypeError.
            if not finite(duration) or duration <= 0:
                check(not ordered and need['cycles'] == 0, 'PROGRAM_MODEL_NOT_SUPPORTED', ['controls', day, device])
                continue
            for value in ordered:
                on_grid(value, ['controls', day, device])
            program_clock[device].extend((day_index * 1440 + value, duration, day) for value in ordered)
            if len(ordered) < need['cycles']:
                issues.append({'date': day, 'device': device, 'code': 'MISSING_REQUESTED_PROGRAMS', 'missing': need['cycles'] - len(ordered)})
            if any(value < need['release_min'] or value + duration > need['deadline_min'] for value in ordered):
                issues.append({'date': day, 'device': device, 'code': 'PROGRAM_OUTSIDE_SERVICE_WINDOW'})
        water_flow = [0.0] * 1440
        water_targets = [set() for _ in range(1440)]
        for i, draw in enumerate(life.get('mixed_water_overrides', {}).get(day, life['mixed_water_daily'])):
            check(draw['start_min'] + draw['duration_min'] <= 1440, 'WATER_DRAW_OUTSIDE_DAY', ['life', day, i])
            bounded('water_target_C', draw['target_C'], ['life', day, i, 'target_C'])
            flow = draw['liters'] / draw['duration_min']
            for minute in range(draw['start_min'], min(1440, draw['start_min'] + draw['duration_min'])):
                water_flow[minute] += flow
                if flow > 0:
                    water_targets[minute].add(draw['target_C'])
            on_grid(draw['start_min'], ['life', day, i, 'start_min'])
            on_grid(draw['duration_min'], ['life', day, i, 'duration_min'])
        check(max(water_flow, default=0) <= domain['max_water_flow_L_min'],
              'WATER_FLOW_OUTSIDE_SUPPORT', ['life', day], domain['max_water_flow_L_min'])
        # This interface currently addresses one aggregate mixed-water service.
        # Distinct simultaneous targets need an explicitly mapped multi-outlet
        # model, rather than an invented average target temperature.
        check(all(len(targets) <= 1 for targets in water_targets),
              'SIMULTANEOUS_WATER_TARGETS_REQUIRE_OUTLET_MAPPING', ['life', day])
        for i, window in enumerate(controls.get('ev_window_overrides', {}).get(day, controls['ev_daily_windows'])):
            for field in ('start_min', 'end_min'):
                on_grid(window[field], ['controls', day, 'ev_windows', i, field])
    horizon = len(dates) * 1440
    for device, intervals in program_clock.items():
        intervals.sort()
        check(all(start + duration <= following for (start, duration, _), (following, _, _) in zip(intervals, intervals[1:])),
              'SAME_DEVICE_PROGRAM_OVERLAP', ['controls', device])
        for start, duration, day in intervals:
            if start + duration > horizon:
                issues.append({'date': day, 'device': device, 'code': 'PROGRAM_NOT_FINISHED_BY_RUN_END'})
    result['inputs_supported'] = not failures
    return result


def assess_inputs(case,domain=None,root=ROOT):
    if case.get('schema')!='national_idf.case.v3':return _assess_v2_inputs(case,domain,root)
    from .dated_case import view,dates
    from .common import digest
    failures=syntax_failures(case,root);issues=[];initial=None
    if failures:return dict(schema='national_idf.runtime_input_screen.v3',syntax_valid=False,inputs_supported=False,failures=failures,service_issues=[],formal_admitted=False)
    for date in dates(case):
        if date not in case['life']['by_date']:
            failures.append(dict(code='DATED_CASE_DATE_MISSING',path=['life','by_date',date]));continue
        # Reuse the unchanged v2 physical-domain checks on each date's own view.
        c=view(case,date)
        # Exact water clocks are checked below and integrated as overlap means;
        # no synthetic shifted draw is fed to the actual execution timeline.
        actual_draws=c['life']['mixed_water_daily'];c['life']['mixed_water_daily']=[]
        r=_assess_v2_inputs(c,domain,root);initial=r.get('initialization_support')
        failures.extend(r['failures'])
        issues.extend(x for x in r['service_issues'] if x.get('date')==date)
        if domain:
            lo,hi=domain['bounds']['water_target_C'];flow=[0.]*1440;targets=[set() for _ in range(1440)]
            for draw in actual_draws:
                a=draw['start_min'];z=a+draw['duration_min']
                if z>1440 or not lo<=draw['target_C']<=hi:failures.append(dict(code='DATED_WATER_OUTSIDE_DOMAIN',path=['life','by_date',date,'mixed_water']))
                for minute in range(a,min(1440,z)):
                    flow[minute]+=draw['liters']/draw['duration_min']
                    if draw['liters']>0:targets[minute].add(draw['target_C'])
            if max(flow,default=0)>domain['max_water_flow_L_min']+1e-9:failures.append(dict(code='WATER_FLOW_OUTSIDE_SUPPORT',path=['life','by_date',date]))
            if any(len(x)>1 for x in targets):failures.append(dict(code='SIMULTANEOUS_WATER_TARGETS_REQUIRE_OUTLET_MAPPING',path=['life','by_date',date]))
    failures=list({digest(x):x for x in failures}.values());issues=list({digest(x):x for x in issues}.values())
    return dict(schema='national_idf.runtime_input_screen.v3',syntax_valid=True,support_domain_checked=domain is not None,inputs_supported=not failures,formal_admitted=False,failures=failures,service_issues=issues,initialization_support=initial,defaults_or_household_routines_created=False,date_specific_views=True)
