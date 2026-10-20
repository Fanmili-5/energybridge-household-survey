"""Explicit inputs -> reference shell -> paired IDFs -> EnergyPlus traces.

Every batch size comes from its input list. Historical cohorts are not imported.
"""
import argparse
import collections
import datetime as dt
import gzip
import hashlib
import json
import math
import os
from pathlib import Path
import re
import sqlite3
import subprocess
from concurrent.futures import ThreadPoolExecutor
import sys

HERE = Path(__file__).resolve().parent


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':'),
                                     ensure_ascii=False, allow_nan=False).encode()).hexdigest()


def read(path):
    p = Path(path)
    raw = gzip.decompress(p.read_bytes()) if p.suffix == '.gz' else p.read_bytes()
    def invalid(value):
        raise ValueError('nonfinite JSON constant: ' + value)
    value = json.loads(raw, parse_constant=invalid)
    def finite(item):
        if isinstance(item, float) and not math.isfinite(item):
            raise ValueError('JSON number outside finite range')
        if isinstance(item, dict):
            for child in item.values(): finite(child)
        if isinstance(item, list):
            for child in item: finite(child)
    finite(value)
    return value


def save(path, value):
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    raw = (json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False) + '\n').encode()
    p.write_bytes(portable_gzip(raw) if p.suffix == '.gz' else raw)


def portable_gzip(raw):
    data=gzip.compress(raw,mtime=0)
    # CPython3.11/3.12 delegate OS-byte selection to zlib; normalize that header.
    return data[:9]+b'\xff'+data[10:]


def bound(root, item):
    if not isinstance(item, dict) or not re.fullmatch('[a-f0-9]{64}', item.get('sha256', '')):
        raise ValueError('artifact needs path and sha256')
    p = (Path(root) / item['path']).resolve()
    if not p.is_relative_to(Path(root).resolve()):
        raise ValueError('artifact path escapes resource root')
    if sha(p) != item['sha256']:
        raise ValueError('input hash mismatch: ' + item['path'])
    return p


def identifier(value):
    if not isinstance(value, str) or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.-]{0,120}', value):
        raise ValueError('unsafe or empty output identifier')
    return value


def fresh(path):
    p = Path(path).resolve()
    p.mkdir(parents=True, exist_ok=False)
    return p


def seal(folder, data):
    data['files'] = {str(p.relative_to(folder)): sha(p) for p in sorted(folder.rglob('*'))
                     if p.is_file() and p != folder / 'MANIFEST.json'}
    save(folder / 'MANIFEST.json', data)
    return data


def verify(folder):
    folder = Path(folder).resolve()
    data = read(folder / 'MANIFEST.json')
    failures = []
    actual={str(p.relative_to(folder))for p in folder.rglob('*')if p.is_file()and p!=folder/'MANIFEST.json'}
    failures.extend(sorted(actual-set(data['files'])))
    for rel, expected in data['files'].items():
        p = (folder / rel).resolve()
        if not p.is_relative_to(folder) or not p.is_file() or sha(p) != expected:
            failures.append(rel)
    if failures:
        raise ValueError('output hash mismatch: ' + ','.join(failures[:10]))
    return data


def match(request, references):
    """Source-bound deterministic candidate rule; not a population estimator."""
    valid = [r for r in references if r['city'] == request['city'] and
             r['province'] == request['province'] and r.get('admitted', False)]
    order = request['building_type_order']
    valid = [r for r in valid if r['building_type'] in order]
    if not valid:
        raise ValueError('no admitted same-city building reference')
    preferred = min(order.index(r['building_type']) for r in valid)
    valid = [r for r in valid if order.index(r['building_type']) == preferred]
    lo, hi = request['given_epoch_interval']
    if not all(type(x) is int for x in (lo, hi)) or lo > hi:
        raise ValueError('invalid epoch interval')
    gap = lambda r: max(r['catalogue_interval'][0] - hi, lo - r['catalogue_interval'][1], 0)
    score = min(gap(r) for r in valid)
    pool = [r for r in valid if gap(r) == score]
    chosen = min(pool, key=lambda r: (r['id'] != request.get('preferred_reference_id'),
                                    digest([request['household_id'], r['id']])))
    return {'selected_reference_id': chosen['id'], 'candidate_count': len(valid),
            'minimum_catalogue_gap_years': score, 'given_epoch_interval': [lo, hi],
            'historical_reference_gap': bool(score),
            'envelope_mode': 'explicit_refurbished_envelope_scenario' if score else 'city_building_reference',
            'catalogue_intervals_are_verified_adoption_dates': False,
            'renovation_or_housing_frequency_estimated': False,
            'selection_uses_simulation_or_human_outcomes': False}


def validate_assembly(a):
    rows = a['rows']
    byname = {r[1]: r for r in rows}
    if len(byname) != len(rows):
        raise ValueError('duplicate assembly object name')
    for r in rows:
        if r[0] == 'Material' and not all(math.isfinite(float(v)) and float(v) > 0 for v in r[3:7]):
            raise ValueError('invalid material thickness or thermal property')
    for kind in ('exterior', 'interior', 'floor', 'window'):
        c = byname[a['names'][kind]]
        if c[0] != 'Construction' or any(m not in byname for m in c[2:]):
            raise ValueError('unresolved construction closure')
    for kind in ('exterior', 'interior'):
        c = byname[a['names'][kind]]
        thickness = sum(float(byname[m][3]) for m in c[2:])
        if abs(thickness - a[kind + '_thickness_m']) > 1e-9:
            raise ValueError('geometry and material thickness differ')
    if not a.get('source_sha256') or not a.get('climate_identity'):
        raise ValueError('assembly provenance required')


def build_shell(config, output):
    from .kernel.geometry import sized
    from .kernel.shell import model
    root = config.parent
    job = read(config)
    if job.get('boundary_policy') != 'midfloor_north_south_reference':
        raise ValueError('unsupported or missing shell boundary_policy')
    if type(job['height_m']) not in (int, float) or job['height_m'] <= 2.1:
        raise ValueError('height must exceed reference door/opening domain2.1m')
    a = read(bound(root, job['assembly']))
    validate_assembly(a)
    hh = job['households']
    if not hh or len({identifier(h['household_id']) for h in hh}) != len(hh):
        raise ValueError('empty batch or duplicate household ids')
    out = fresh(output)
    save(out/'_inputs/assembly.json',a)
    recipe={**job,'assembly':{'path':'assembly.json','sha256':sha(out/'_inputs/assembly.json')}}
    save(out/'_inputs/shell.json',recipe)
    records = []
    for h in hh:
        hid = h['household_id']
        try:
            for k in ('natural_rooms', 'shared_households'):
                if type(h[k]) is not int or h[k] < 1:
                    raise ValueError('positive exact count required: ' + k)
            if h['facilities']['kitchen'] not in ('exclusive', 'shared', 'none'):
                raise ValueError('unknown kitchen reference')
            if type(h['gross_area_m2']) not in (int, float) or not math.isfinite(h['gross_area_m2']) or h['gross_area_m2'] <= 0:
                raise ValueError('positive finite gross area required')
            profile = {'slot_id': hid, 'housing': {
                'H7_independent_natural_rooms_design': h['natural_rooms'],
                'shared_household_count_design': h['shared_households'],
                'H6_census_building_area_design_m2': h['gross_area_m2']}}
            for k in ('reference_neighbor_room_counts', 'target_bedroom_width_weights'):
                if k in h:
                    profile[k] = h[k]
            shapes = job['studio_shapes'] if h['natural_rooms'] == h['shared_households'] == 1 else job['gallery_shapes']
            failures = []
            for shape in shapes:
                try:
                    layout = sized(profile, h['facilities'], a, shape)
                    from .geometry_reference import check_geometry_reference
                    layout['geometry_reference']=check_geometry_reference(h,layout)
                    rows, metadata = model(layout, a, job['height_m'])
                    metadata['geometry_reference']=layout['geometry_reference']
                    break
                except (ValueError, AssertionError) as e:
                    failures.append(str(e))
            else:
                raise ValueError('no declared geometry candidate: ' + ';'.join(failures))
            folder = out / hid
            folder.mkdir()
            save(folder / 'layout.json', layout)
            save(folder / 'shell_metadata.json', metadata)
            text = '\n\n'.join(',\n  '.join(str(v) for v in r) + ';' for r in rows) + '\n'
            (folder / 'shell.idf').write_text(text)
            records.append({'household_id': hid, 'status': 'shell_compiled',
                            'rejected_shape_attempts': failures,
                            'sleep_and_appliance_installation_checked': False})
        except (KeyError, ValueError, AssertionError) as e:
            records.append({'household_id': hid, 'status': 'rejected', 'reason': str(e)})
    return seal(out, {'schema': 'eb.housing_shell.batch.v1', 'input_sha256': sha(config),
                      'assembly_sha256': job['assembly']['sha256'], 'records': records,
                      'households_requested': len(hh), 'output_scope': 'reference shell geometry;not complete household service world',
                      'rejected_households_retained': True, 'new_EnergyPlus_runs': 0})


def extract_native(config, output):
    # The optional Access reader is only needed for original DeST extraction.
    from .kernel.native_bundle import extract
    entry = read(config)
    # Resolve native/EPW paths relative to the explicit entry file, not a cohort.
    entry['source_path'] = str((config.parent / entry['source_path']).resolve())
    for candidate in entry['coordinate_confirmed_WMO_station_candidates']:
        candidate['path'] = str((config.parent / candidate['path']).resolve())
    updated, assembly = extract(entry)
    out = fresh(output)
    save(out / 'reference.json', updated)
    save(out / 'assembly.json', assembly)
    return seal(out, {'schema': 'eb.housing_native.extraction.v1', 'input_sha256': sha(config),
                      'native_source_sha256': updated['source_sha256'],
                      'native_geometry_reconstructed': False, 'new_EnergyPlus_runs': 0})


def make_demo(schema, weather, output):
    """Create a wholly synthetic no-appliance A=B integration fixture."""
    from .kernel.core_tools import parse_idf
    import shutil
    out = fresh(output)
    build_shell(HERE / 'examples/shell_batch.json', out / 'shells')
    layout = read(out / 'shells/example-studio/layout.json')
    schema_fields = {k: v['legacy_idd']['fields'] for k, v in read(schema)['properties'].items()
                     if 'legacy_idd' in v and 'fields' in v['legacy_idd']}
    save(out / 'inputs/schema_fields.json.gz', schema_fields)
    gains = [['Lights', 'synthetic_light', '', '', 'Watts/Area', '', 1],
             ['ElectricEquipment', 'IECC_Adj1', '', '', 'Watts/Area', '', 1, '', 0, .5, 0],
             ['ElectricEquipment', 'refrigerator1', '', '', 'EquipmentLevel', 100, '', '', 0, .5, 0],
             ['ElectricEquipment', 'electric_range1', '', '', 'EquipmentLevel', 1000, '', '', 0, .5, 0]]
    save(out / 'inputs/native_rows.json.gz', {'gains': gains, 'tank': []})
    shutil.copy2(HERE / 'reference_environment.json', out / 'THERMAL_ENVIRONMENT_POLICY.json')
    epw = out / 'inputs/weather.epw'; epw.parent.mkdir(exist_ok=True); shutil.copy2(weather, epw)
    days = {}
    day, end = dt.date(2024, 12, 15), dt.date(2026, 1, 15)
    while day < end:
        days[str(day)] = {'controls': [], 'calendars': {}, 'operator_windows': {},
                          'family': {'bath_times_min': {}, 'member_dinners_min': {}},
                          'shared': {'member_calendars': {}, 'facility_reservations': []}}
        day += dt.timedelta(days=1)
    pack = {'household_id': 'public-demo', 'anchor': '2024-12-15', 'end_exclusive': '2026-01-15',
            'world': {'layout': layout, 'parameter_pack': {'devices': []},
                      'activity_contract': {'room_map': {'bath': 'washroom'}}},
            'days': days, 'tasks': [], 'operations': [], 'HVAC': [], 'journeys': [],
            'EV_battery_energy_events': [], 'weather': 'inputs/weather.epw', 'weather_sha256': sha(epw),
            'source_shell_sha256': sha(out / 'shells/example-studio/shell.idf'),
            'shell_rows': parse_idf((out / 'shells/example-studio/shell.idf').read_text())}
    empty = {'tasks': [], 'operations': [], 'controls': []}
    pair = {'case_id': 'public-demo-pair', 'household_id': 'public-demo', 'date': '2025-01-22',
            'A': empty, 'B': empty, 'schedule_hashes': {'A': digest(empty), 'B': digest(empty)},
            'needs_A': [], 'EV_continuous_reference': {'status': 'not_installed'},
            'synthetic_fixture': True}
    pair['source_pair_sha256'] = digest(pair)
    save(out / 'inputs/household.json.gz', pack); save(out / 'inputs/pair.json.gz', pair)
    resources = {p: sha(out / p) for p in ['inputs/schema_fields.json.gz', 'inputs/native_rows.json.gz', 'THERMAL_ENVIRONMENT_POLICY.json']}
    job = {'schema': 'eb.housing_physics.input.v1', 'resource_root': '.', 'resources': resources,
           'settings': {'history_days': 7, 'tail_days': 1},
           'pairs': [{'id': 'public-demo-pair', 'household': {'path': 'inputs/household.json.gz', 'sha256': sha(out / 'inputs/household.json.gz')},
                      'pair': {'path': 'inputs/pair.json.gz', 'sha256': sha(out / 'inputs/pair.json.gz')}}]}
    save(out / 'physics_job.json', job)
    return seal(out, {'schema': 'eb.housing_physics.synthetic_demo.v1',
                      'source_schema_sha256': sha(schema), 'source_weather_sha256': sha(weather),
                      'not_a_measured_household': True, 'A_equals_B_by_design': True,
                      'HVAC_or_appliance_performance_validated': False})


def compile_pairs(config, output, workers=1):
    if type(workers) is not int or not 1<=workers<=16:raise ValueError('workers must be1..16')
    job = read(config)
    root = (config.parent / job['resource_root']).resolve()
    settings = {'history_days':112,'tail_days':8,'reference_ach':.35,'portal_flow_scale':1.,'simulation_timestep_min':10,'airflow_model':'reference_mixing','people_scale':1.,'lighting_scale':1.,'misc_scale':1.}
    if set(job.get('settings', {})) - set(settings):
        raise ValueError('unknown compiler setting')
    settings.update(job.get('settings', {}))
    if type(settings['history_days']) is not int or settings['history_days'] < 0:
        raise ValueError('invalid history_days')
    if type(settings['tail_days']) is not int or settings['tail_days'] < 1:
        raise ValueError('invalid tail_days')
    if any(type(settings[k])not in(int,float)or not math.isfinite(settings[k])for k in ('reference_ach','portal_flow_scale'))or not 0 < settings['reference_ach'] <= 3 or not .5<=settings['portal_flow_scale']<=2:
        raise ValueError('undeclared airflow settings')
    if type(settings['simulation_timestep_min'])is not int or settings['simulation_timestep_min']not in (1,2,5,10)or settings['airflow_model']not in ('reference_mixing','pressure_network'):
        raise ValueError('unsupported solver timestep/airflow model')
    if any(type(settings[k])not in(int,float)or not math.isfinite(settings[k])or not .5<=settings[k]<=2 for k in ('people_scale','lighting_scale','misc_scale')):
        raise ValueError('internal gain scale outside declared study domain')
    resources = {}
    for rel in ('inputs/schema_fields.json.gz', 'inputs/native_rows.json.gz', 'THERMAL_ENVIRONMENT_POLICY.json'):
        resources[rel] = sha(bound(root, {'path': rel, 'sha256': job['resources'][rel]}))
    pairs = job['pairs']
    if not pairs or len({identifier(x['id']) for x in pairs}) != len(pairs):
        raise ValueError('empty batch or duplicate pair ids')
    # Validate every input before writing output; preserve per-pair failures at execution.
    inputs = []
    for item in pairs:
        pack_path, pair_path = bound(root, item['household']), bound(root, item['pair'])
        pack, pair = read(pack_path), read(pair_path)
        if pack['household_id'] != pair['household_id']:
            raise ValueError('household/pair identity mismatch')
        if not {'A', 'B', 'schedule_hashes', 'date'} <= set(pair):
            raise ValueError('incomplete A/B input')
        if pack['world'].get('input_kind','').startswith('declared_reference_household'):
            if any(pair['schedule_hashes'][s]!=digest(pair[s])for s in ('A','B')) or pair['source_pair_sha256']!=digest({k:v for k,v in pair.items()if k!='source_pair_sha256'}):
                raise ValueError('assembled pair internal hash mismatch')
        start, end = dt.date.fromisoformat(pack['anchor']), dt.date.fromisoformat(pack['end_exclusive'])
        date=dt.date.fromisoformat(pair['date'])
        if not start <= date < end:
            raise ValueError('case date outside declared calendar')
        if date-dt.timedelta(days=settings['history_days'])<start:
            raise ValueError('insufficient history calendar; implicit truncation is not admitted')
        weather = bound(root, {'path': pack['weather'], 'sha256': pack['weather_sha256']})
        inputs.append((item, pack_path, pair_path, weather))
    out = fresh(output)
    def compile_one(entry):
        item,pp,cp,weather=entry
        folder = out / item['id']
        folder.mkdir()
        worker = {'resource_root': str(root), 'household_path': str(pp), 'pair_path': str(cp),
                  'settings': settings, 'output': str(folder)}
        save(folder / 'compiler_job.json', worker)
        run = subprocess.run([sys.executable, '-B', '-m', 'benchmark.housing_simulation.worker',
                              str(folder / 'compiler_job.json')], capture_output=True, text=True)
        (folder / 'compile.log').write_text(run.stdout + run.stderr)
        rec = {'id': item['id'], 'status': 'compiled' if run.returncode == 0 else 'failed',
               'weather_path': str(weather), 'weather_sha256': sha(weather),
               'household_sha256': sha(pp), 'pair_sha256': sha(cp)}
        return rec
    with ThreadPoolExecutor(max_workers=workers) as pool:
        records=list(pool.map(compile_one,inputs))
    for rel, expected in resources.items():
        if sha(root / rel) != expected:
            raise ValueError('resource changed during compilation')
    for item, pp, cp, weather in inputs:
        if sha(pp) != item['household']['sha256'] or sha(cp) != item['pair']['sha256']:
            raise ValueError('request changed during compilation')
    return seal(out, {'schema': 'eb.housing_physics.compilation.v1', 'input_sha256': sha(config),
                      'resource_hashes': resources, 'settings': settings, 'records': records,
                      'pair_count': len(pairs), 'new_EnergyPlus_runs': 0})


def sql_trace(path, history_days, native_step=10):
    channels = {}
    with sqlite3.connect(path) as db:
        query = '''SELECT d.Name,d.KeyValue,d.Units,d.IsMeter,t.SimulationDays,t.Hour,t.Minute,t.Interval,r.Value,d.Type
        FROM ReportData r JOIN ReportDataDictionary d USING(ReportDataDictionaryIndex)
        JOIN Time t USING(TimeIndex) JOIN EnvironmentPeriods e USING(EnvironmentPeriodIndex)
        WHERE t.WarmupFlag=0 AND e.EnvironmentType=3 AND t.SimulationDays>=?
        ORDER BY t.TimeIndex'''
        for name, key, unit, meter, day, hour, minute, interval, value, aggregation in db.execute(query, (history_days + 1,)):
            if interval != native_step or not math.isfinite(value):
                raise ValueError('invalid timestep or nonfinite output')
            t = (day - history_days - 1) * 1440 + hour * 60 + minute - interval
            if aggregation not in ('Sum','Avg'):raise ValueError('unknown native output aggregation type')
            channel = channels.setdefault(name + '|' + (key or ''), {'unit': unit, 'is_meter': bool(meter), 'values': [],'native_aggregation':aggregation})
            channel['values'].append([t, value])
    if native_step!=10:
        for c in channels.values():
            raw=c['values'];expected=list(range(raw[0][0],raw[-1][0]+native_step,native_step))
            if [t for t,v in raw]!=expected:raise ValueError('missing/duplicate native solver interval')
            bins={}
            for t,value in raw:bins.setdefault(t//10*10,[]).append(value)
            if any(len(v)!=10//native_step for v in bins.values()):raise ValueError('incomplete native aggregation bin')
            c['values']=[[t,sum(v)if c['native_aggregation']=='Sum'else sum(v)/len(v)]for t,v in bins.items()]
            c['native_timestep_min']=native_step;c['report_timestep_min']=10
    if not any(k.startswith('Electricity:Facility|') for k in channels) or not any(k.startswith('Zone Mean Air Temperature|') for k in channels):
        raise ValueError('required meter/temperature channels missing')
    return channels


def native_site_power(path, history_days, hi, native_step):
    """Read solver-step facility demand before ten-minute report aggregation."""
    with sqlite3.connect(path) as db:
        query = '''SELECT t.SimulationDays,t.Hour,t.Minute,t.Interval,r.Value,d.Units
        FROM ReportData r JOIN ReportDataDictionary d USING(ReportDataDictionaryIndex)
        JOIN Time t USING(TimeIndex) JOIN EnvironmentPeriods e USING(EnvironmentPeriodIndex)
        WHERE COALESCE(t.WarmupFlag,0)=0 AND e.EnvironmentType=3 AND t.SimulationDays>=?
        AND lower(d.Name)='electricity:facility' AND d.IsMeter=1 ORDER BY t.TimeIndex'''
        rows = list(db.execute(query, (history_days + 1,)))
    values = []
    for day, hour, minute, interval, value, unit in rows:
        t = (day - history_days - 1) * 1440 + hour * 60 + minute - interval
        if not 0 <= t < hi:
            continue
        if unit != 'J' or interval != native_step or value is None or not math.isfinite(value) or value < 0:
            raise ValueError('INVALID_NATIVE_SITE_POWER')
        values.append([t, value / (60 * interval)])
    if [t for t, v in values] != list(range(0, hi, native_step)):
        raise ValueError('MISSING_OR_DUPLICATE_NATIVE_SITE_POWER')
    return {'native_step_min': native_step, 'values_W': values, 'peak_W': max(v for t, v in values),
            'scope': 'native_solver_interval_mean_real_power;not_inrush_current_or_breaker_trip'}


def run_pairs(compiled, output, engine, engine_sha, timeout, workers=1):
    if type(workers) is not int or not 1<=workers<=16:raise ValueError('workers must be1..16')
    compiled = Path(compiled).resolve()
    m = verify(compiled)
    engine = Path(engine).resolve()
    if sha(engine) != engine_sha:
        raise ValueError('engine sha256 mismatch')
    version = subprocess.check_output([str(engine), '--version'], text=True).strip()
    if '24.1.0-9d7789a3ac' not in version:
        raise ValueError('this kernel requires EnergyPlus24.1.0-9d7789a3ac')
    out = fresh(output)
    jobs=[(item,side) for item in m['records'] if item['status']=='compiled' for side in ('A','B')]
    def run_one(job):
        item,side=job
        if sha(item['weather_path']) != item['weather_sha256']:
            raise ValueError('weather changed after compilation')
        folder = out / item['id'] / side
        folder.mkdir(parents=True)
        source = compiled / item['id'] / side
        meta = read(source / 'INPUT.json.gz')
        if sha(source / 'model.idf') != meta['idf_sha256']:
            raise ValueError('compiled model/input receipt mismatch')
        command = [str(engine), '-w', item['weather_path'], '-d', str(folder / 'out'), str(source / 'model.idf')]
        try:
            run = subprocess.run(command, capture_output=True, text=True, timeout=timeout)
            (folder / 'stdout.txt').write_text(run.stdout + run.stderr)
            errors = (folder / 'out/eplusout.err').read_text()
            success = run.returncode == 0 and 'EnergyPlus Completed Successfully' in errors
            result = {'id': item['id'], 'side': side, 'status': 'completed' if success else 'engine_failed',
                      'engine_sha256': engine_sha, 'idf_sha256': sha(source / 'model.idf'),
                      'evaluated_interval_min': [0, meta['run_interval_min'][1]],
                      'energy_scope': 'facility electricity over evaluated interval;not automatically daily or equal-service savings',
                      'warnings': [l for l in errors.splitlines() if '** Warning **' in l],
                      'human_acceptance': None, 'engine_completion_is_not_service_success': True}
            if success:
                channels = sql_trace(folder / 'out/eplusout.sql', meta['history_days'],meta.get('simulation_timestep_min',10))
                expected = list(range(0, meta['run_interval_min'][1], 10))
                if any([t for t, v in c['values']] != expected for c in channels.values()):
                    raise ValueError('incomplete or duplicated output timeline')
                save(folder / 'TRACE.json.gz', channels)
                result['SQL_sha256'] = sha(folder / 'out/eplusout.sql')
                result['trace_sha256'] = sha(folder / 'TRACE.json.gz')
                result['facility_energy_kWh'] = sum(v for t, v in channels['Electricity:Facility|']['values']) / 3600000
            save(folder / 'RESULT.json', result)
            # Retain the redundant native text exports losslessly; SQL/TRACE and
            # error logs remain directly readable and content-bound.
            for name in ('eplusout.eso','eplusout.mtr'):
                text_export=folder/'out'/name
                if text_export.exists():
                    text_export.with_suffix(text_export.suffix+'.gz').write_bytes(portable_gzip(text_export.read_bytes()))
                    text_export.unlink()
            return result
        except (OSError, ValueError, subprocess.TimeoutExpired) as e:
            result = {'id': item['id'], 'side': side, 'status': 'readback_or_engine_failed', 'reason': str(e)}
            save(folder / 'RESULT.json', result); return result
    with ThreadPoolExecutor(max_workers=workers) as pool:
        executed=list(pool.map(run_one,jobs))
    by={(r['id'],r['side']):r for r in executed}
    records=[]
    for item in m['records']:
        if item['status']!='compiled':records.append({'id':item['id'],'status':'compile_failed'})
        else:records.extend(by[(item['id'],side)] for side in ('A','B'))
    verify(compiled)
    if sha(engine) != engine_sha:
        raise ValueError('engine changed during execution')
    return seal(out, {'schema': 'eb.housing_physics.execution.v1', 'engine_version': version,
                      'compiled_manifest_sha256': sha(compiled / 'MANIFEST.json'), 'records': records,
                      'whole_benchmark_validated': False, 'human_answers_created': 0})


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='command', required=True)
    p = sub.add_parser('match'); p.add_argument('--request', type=Path, required=True); p.add_argument('--catalog', type=Path, required=True)
    p = sub.add_parser('make-demo'); p.add_argument('--schema', type=Path, required=True); p.add_argument('--weather', type=Path, required=True); p.add_argument('--out', type=Path, required=True)
    for command in ('extract-native', 'build-shell', 'compile'):
        p = sub.add_parser(command); p.add_argument('--input', type=Path, required=True); p.add_argument('--out', type=Path, required=True)
    p = sub.add_parser('verify'); p.add_argument('directory', type=Path)
    p = sub.add_parser('assemble'); p.add_argument('--input', type=Path, required=True); p.add_argument('--shells', type=Path, required=True)
    p.add_argument('--weather', type=Path, required=True); p.add_argument('--out', type=Path, required=True)
    p = sub.add_parser('audit'); p.add_argument('--compiled', type=Path, required=True); p.add_argument('--runs', type=Path, required=True); p.add_argument('--out', type=Path, required=True)
    p = sub.add_parser('reproduce'); p.add_argument('--energyplus-dir', type=Path, required=True); p.add_argument('--weather', type=Path)
    p.add_argument('--weather-metadata', type=Path)
    p.add_argument('--out', type=Path, required=True)
    p = sub.add_parser('study'); p.add_argument('--energyplus-dir',type=Path,required=True);p.add_argument('--out',type=Path,required=True);p.add_argument('--workers',type=int,default=3);p.add_argument('--weather',type=Path);p.add_argument('--weather-metadata',type=Path)
    p = sub.add_parser('run'); p.add_argument('--compiled', type=Path, required=True); p.add_argument('--out', type=Path, required=True)
    p.add_argument('--engine', type=Path, required=True); p.add_argument('--engine-sha256', required=True); p.add_argument('--timeout', type=int, default=300)
    args = parser.parse_args()
    try:
        if args.command == 'match':
            result = match(read(args.request), read(args.catalog)['references'])
        elif args.command == 'make-demo': result = make_demo(args.schema, args.weather, args.out)
        elif args.command == 'extract-native': result = extract_native(args.input.resolve(), args.out)
        elif args.command == 'build-shell': result = build_shell(args.input.resolve(), args.out)
        elif args.command == 'compile': result = compile_pairs(args.input.resolve(), args.out)
        elif args.command == 'assemble':
            from .assembly import assemble
            result=assemble(args.input.resolve(),args.shells,args.weather,args.out)
        elif args.command == 'audit':
            from .validation import audit
            result=audit(args.compiled,args.runs,args.out)
        elif args.command == 'reproduce':
            from .validation import reproduce
            result=reproduce(args.energyplus_dir,args.weather,args.out,args.weather_metadata)
        elif args.command == 'study':
            from .robustness import public_study
            result=public_study(args.energyplus_dir,args.out,args.workers,args.weather,args.weather_metadata)
        elif args.command == 'run': result = run_pairs(args.compiled, args.out, args.engine, args.engine_sha256, args.timeout)
        else: result = verify(args.directory)
        display={k:v for k,v in result.items()if k!='files'}
        if 'records'in display:display['records']=[{k:v for k,v in r.items()if k not in ('checks','details')}for r in display['records']]
        print(json.dumps(display, ensure_ascii=False, indent=2))
        return int(result.get('passed') is False or any(r.get('status') in ('rejected', 'failed', 'compile_failed', 'engine_failed', 'readback_or_engine_failed')
                       for r in result.get('records', [])))
    except (OSError, ValueError, KeyError, TypeError, ImportError, subprocess.SubprocessError) as e:
        print(json.dumps({'status': 'failed', 'reason': str(e)}, ensure_ascii=False), file=sys.stderr)
        return 1
