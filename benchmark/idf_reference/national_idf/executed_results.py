"""Export native electricity, zone temperatures and service observations.

This consumes an executed six-device CASE. It neither compiles new physics
nor grants model admission. SQL timestamps must match the controller clock;
the building meter is never silently renamed a household meter.
"""
import csv
import copy
import datetime as dt
from pathlib import Path
import sqlite3

import numpy as np

from .common import ROOT, locked, read, require, save, sha, verify
from .idf import Fields, objects, parse


def reference(path, root):
    return {'path': str(path.resolve().relative_to(root.resolve())), 'sha256': sha(path)}


def native_series(path):
    result = {}
    with sqlite3.connect(f'{path.resolve().as_uri()}?mode=ro', uri=True) as db:
        query = db.execute(
            'SELECT q.Name,q.KeyValue,q.Units,t.Year,t.Month,t.Day,t.Hour,t.Minute,d.Value '
            'FROM ReportData d JOIN ReportDataDictionary q '
            'ON q.ReportDataDictionaryIndex=d.ReportDataDictionaryIndex '
            'JOIN Time t ON t.TimeIndex=d.TimeIndex WHERE t.WarmupFlag=0 '
            "AND q.ReportingFrequency='Zone Timestep' ORDER BY d.TimeIndex")
        for name, key, unit, year, month, day, hour, minute, value in query:
            item = result.setdefault((name.casefold(), (key or '').casefold()),
                                     {'unit': unit, 'times': [], 'values': []})
            require(item['unit'] == unit, 'RESULT_UNIT_CONFLICT', name)
            item['times'].append(dt.datetime(year, month, day)+dt.timedelta(hours=hour, minutes=minute))
            item['values'].append(value)
    return result


def checked_series(raw, name, key, times, unit):
    item = raw.get((name.casefold(), key.casefold()))
    require(item is not None and item['unit'] == unit and item['times'] == times,
            'RESULT_NATIVE_CLOCK_OR_UNITS', [name, key, unit])
    values = np.asarray(item['values'], dtype=float)
    require(np.all(np.isfinite(values)), 'RESULT_NONFINITE_NATIVE_OUTPUT', [name, key])
    return values


def energy_terms(rows, fields, mapping):
    """Every claimed component has one owner; facility closure checks coverage."""
    terms = {}
    electric = {r['equipment'].casefold(): d for d, r in mapping['equipment'].items()}
    def add(owner, name, variable):
        term = (variable, name)
        require(not any(term in values for values in terms.values()), 'RESULT_DUPLICATE_ENERGY_OWNER', term)
        terms.setdefault(owner, []).append(term)
    for row in rows:
        kind, name = row[:2] if len(row) > 1 else (row[0], '')
        if kind == 'ElectricEquipment':
            add(electric.get(name.casefold(), 'background'), name, 'Electric Equipment Electricity Energy')
        elif kind == 'Lights': add('background', name, 'Lights Electricity Energy')
        elif kind in ('WaterHeater:Stratified', 'WaterHeater:Mixed'):
            add('water_heater', name, 'Water Heater Electricity Energy')
        elif kind.startswith('Pump:'): add('water_heater', name, 'Pump Electricity Energy')
        elif kind.startswith('Fan:'): add('air_conditioner', name, 'Fan Electricity Energy')
        elif kind.startswith('Coil:Heating:DX:'):
            for variable in ('Heating Coil Electricity Energy', 'Heating Coil Defrost Electricity Energy',
                             'Heating Coil Crankcase Heater Electricity Energy'):
                add('air_conditioner', name, variable)
        elif kind.startswith('Coil:Cooling:DX:'):
            add('air_conditioner', name, 'Cooling Coil Electricity Energy')
        elif kind == 'OtherEquipment' and fields.get(row, 'fuel_type').casefold() == 'electricity':
            owner = 'water_heater' if name == mapping['water_heater']+' energy adjustment1' else 'air_conditioner'
            require(owner == 'water_heater' or name.startswith('HP_AC_'), 'RESULT_UNREVIEWED_ELECTRIC_AUXILIARY', name)
            add(owner, name, 'Other Equipment Electricity Energy')
    require(set(terms) == {'air_conditioner', 'washer', 'dryer', 'dishwasher', 'water_heater', 'ev', 'background'},
            'RESULT_INCOMPLETE_SIX_DEVICE_ACCOUNT')
    return terms


def housing_comparison_rows(rows, spec, *, root=ROOT):
    """Normalize only evidence-bound initialization fields for housing identity."""
    if not spec.get('registered_numerical_overlay'):
        return rows
    from .source_numerics import validate_model_overlay, WARMUP_FIELDS, WARMUP_TOLERANCE
    model = parse(locked(spec['model'], root).read_text())
    validate_model_overlay(model, spec['model'], spec['registered_numerical_overlay'],
                           spec['engine_schema'], root=root)
    require(objects(rows, 'Building') == objects(model, 'Building'),
            'RESULT_COMPILED_INITIALIZATION_CHANGED')
    overlay = read(locked(spec['registered_numerical_overlay'], root))
    source = parse(locked(overlay['source_model'], root).read_text())
    fields = Fields(locked(spec['engine_schema'], root))
    canonical = copy.deepcopy(rows)
    for key in WARMUP_FIELDS:
        fields.set(objects(canonical, 'Building')[0], key,
                   fields.get(objects(source, 'Building')[0], key))
    if overlay.get('warmup_temperature_probe'):
        fields.set(objects(canonical, 'Building')[0], WARMUP_TOLERANCE,
                   fields.get(objects(source, 'Building')[0], WARMUP_TOLERANCE))
    return canonical


def execution_admission(compiled_receipt, runtime):
    """Report actual run authority; never infer it from a successful exit."""
    formal=(compiled_receipt.get('schema')=='national_idf.compiled_reviewed_six_CASE.v1'
            and compiled_receipt.get('execution_mode')=='formal')
    require(runtime.get('formal_admitted') is formal,'RESULT_RUNTIME_ADMISSION_MISMATCH')
    return formal


def export(case_folder, template_ref, out, *, root=ROOT):
    case_folder, out = case_folder.resolve(), out.resolve()
    require(case_folder.is_relative_to(root) and out.is_relative_to(root) and not out.exists(), 'RESULT_PATH')
    compiled_receipt = verify(case_folder/'compiled')
    fixture_path = case_folder/'FIXTURE.json'
    spec = read(fixture_path if fixture_path.exists() else case_folder/'compiled/FIXTURE.json')
    if (case_folder/'NUMERICAL_OVERLAY.json').exists():
        overlay = read(case_folder/'NUMERICAL_OVERLAY.json')
    else:
        require(compiled_receipt['schema'] in ('national_idf.compiled_six_reference_CASE.v1',
            'national_idf.compiled_reviewed_six_CASE.v1'),'RESULT_UNSUPPORTED_COMPILED_SCHEMA')
        executed_rows = parse((case_folder/'compiled/in.idf').read_text())
        run = read(case_folder/'compiled/CASE.json')['run']
        step = 60/float(objects(executed_rows,'Timestep')[0][1])
        require(step in (1,2,5),'RESULT_FIXED_STEP_UNSUPPORTED')
        overlay = {'step_min':int(step),'days':(dt.date.fromisoformat(run['end_date'])
            -dt.date.fromisoformat(run['start_date'])).days+1}
    runtime = read(case_folder/'eb_run/RUNTIME.json')
    formal=execution_admission(compiled_receipt,runtime)
    require(runtime['exit_code'] == 0 and not runtime['progress']['errors'], 'RESULT_FAILED_RUN')
    require(runtime['compiled_manifest_sha256'] == sha(case_folder/'compiled/MANIFEST.json'), 'RESULT_RUNTIME_MODEL_MISMATCH')
    template = read(locked(template_ref, root))
    source_rows = parse(locked(template['model'], root).read_text())
    rows = parse((case_folder/'compiled/in.idf').read_text())
    fields = Fields(locked(spec['engine_schema'], root))
    # A foreign template must not relabel the executed house or its zone names.
    from .source_adapter import housing_fingerprint
    require(housing_fingerprint(housing_comparison_rows(rows, spec, root=root)) ==
            housing_fingerprint(source_rows), 'RESULT_FOREIGN_HOUSING_TEMPLATE')
    zones = template['reviewed_dwelling']['room_names']
    require(zones and len(set(zones)) == len(zones)
            and set(zones) <= {r[1] for r in objects(rows, 'Zone')}, 'RESULT_DWELLING_SCOPE')
    connected = [fields.get(r, 'zone_name') for r in objects(rows, 'ZoneHVAC:EquipmentConnections')]
    target = spec['EB_mapping']['hvac']['zone']
    require(target in zones and all(z in zones for z in connected), 'RESULT_SHARED_HVAC_UNREVIEWED')
    require(not objects(rows, 'ZoneHVAC:IdealLoadsAirSystem'), 'RESULT_RETAINED_IDEAL_HVAC_REQUIRES_OWNERSHIP')
    # Record retained-context electric objects explicitly. Facility still means
    # the full building even when this test installs electricity only in one home.
    outside = []
    for kind in ('ElectricEquipment', 'Lights', 'OtherEquipment'):
        for row in objects(rows, kind):
            if kind == 'OtherEquipment' and fields.get(row, 'fuel_type').casefold() != 'electricity': continue
            zone = fields.get(row, 'zone_or_zonelist_or_space_or_spacelist_name')
            if zone not in zones: outside.append([kind, row[1], zone])
    require(not outside, 'RESULT_NEIGHBOUR_ELECTRICITY_REQUIRES_OWNERSHIP', outside)
    with (case_folder/'eb_run/TRACE.csv').open() as stream: trace = list(csv.DictReader(stream))
    step = overlay['step_min']; expected = overlay['days']*1440//step
    require(len(trace) == runtime['progress']['zone_steps'] == expected, 'RESULT_TRACE_LENGTH')
    times = [dt.datetime.fromisoformat(r['date'])+dt.timedelta(minutes=int(r['start_min'])+step) for r in trace]
    require(all(b-a == dt.timedelta(minutes=step) for a,b in zip(times, times[1:])), 'RESULT_TRACE_GAP')
    raw = native_series(case_folder/'eb_run/output/eplusout.sql')
    get = lambda name,key='',unit='J': checked_series(raw, name, key, times, unit)
    curve_quality=None
    if formal:
        from .curve_domain import assess, reviewed_policy
        identifier=compiled_receipt['physics_configuration_id']
        records=read(root/'configs/physics_configurations.json')['records']
        record=next(r for r in records if r['id']==identifier)
        evidence=record['equipment']['air_conditioner']['performance_evidence']['low_temperature']['artifact']
        tables=read(locked(evidence,root))['generated_lookup_tables']
        # E+ curve reports use empty/dimensionless units for axis/output fields.
        def curve_get(name,key,unit):
            data=raw.get((name.casefold(),key.casefold()))
            require(data is not None,'CURVE_NATIVE_REPORT_MISSING',[name,key])
            actual=data['unit']
            if unit in ('','1'):require(actual in ('','1','C'),'CURVE_NATIVE_AXIS_UNITS',actual)
            else:require(actual==unit,'CURVE_NATIVE_POWER_UNITS',actual)
            return checked_series(raw,name,key,times,actual)
        policy=record['equipment']['air_conditioner'].get('curve_support_policy')
        allowed=reviewed_policy(policy,tables,rows,fields,root=root) if policy else set()
        curve_quality=assess(tables,curve_get,reviewed_axes=allowed)
        curve_quality['reviewed_source_method']=policy
        if not curve_quality['passed_observed_domain_screen']:
            out.mkdir(parents=True)
            save(out/'QUALITY.json',curve_quality)
            require(False,'RESULT_CURVE_SUPPORT_EXCURSION',curve_quality['observed_outside_count'])

    terms = energy_terms(rows, fields, spec['EB_mapping'])
    energy = {owner: sum((get(v,n) for v,n in values), np.zeros(expected)) for owner, values in terms.items()}
    facility = get('Electricity:Facility'); residual = float(np.max(abs(facility-sum(energy.values()))))
    require(residual < 1e-7, 'RESULT_ELECTRICITY_NOT_CLOSED', residual)
    temperatures = {z: get('Zone Mean Air Temperature', z, 'C') for z in zones}
    water = read(case_folder/'eb_run/WATER_SERVICE.json'); water_volumes = {}
    for row in objects(rows, 'WaterUse:Equipment'):
        water_volumes[row[1]] = get('Water Use Equipment Total Volume', row[1], 'm3')*1000
    columns = {'date': [r['date'] for r in trace], 'start_min': [r['start_min'] for r in trace],
               'end_timestamp': [t.isoformat() for t in times], 'step_min': [step]*expected,
               **{owner+'_kWh': values/3.6e6 for owner,values in energy.items()},
               'facility_kWh': facility/3.6e6,
               'requested_general_water_L': [float(r['requested_water_L']) for r in trace],
               'requested_general_water_target_C': [float(r['requested_water_target_C'])
                   if r['requested_water_target_C'] != '' else None for r in trace],
               'tank_temperature_C': [float(r['tank_temperature_C']) for r in trace],
               **{'zone_C:'+z: values for z,values in temperatures.items()},
               **{'water_L:'+z: values for z,values in water_volumes.items()}}
    zone_results = {z: {'min_C': float(v.min()), 'max_C': float(v.max()), 'time_mean_C': float(v.mean()),
                       'has_direct_HVAC_connection': z in connected} for z,v in temperatures.items()}
    cycles = {device: [r for r in records if r['scheduled_abs_h'] is not None]
              for device,records in runtime['whitegoods']['EB_results'].items()}
    out.mkdir(parents=True)
    with (out/'TIMESERIES.csv').open('w', newline='') as stream:
        writer = csv.writer(stream); writer.writerow(columns)
        writer.writerows(zip(*columns.values()))
    result = {'schema': 'national_idf.executed_six_device_results.v1',
        'runtime': reference(case_folder/'eb_run/RUNTIME.json', root),
        'compiled_manifest': reference(case_folder/'compiled/MANIFEST.json', root),
        'native_sql': reference(case_folder/'eb_run/output/eplusout.sql', root),
        'controller_trace': reference(case_folder/'eb_run/TRACE.csv', root),
        'template': template_ref, 'days': overlay['days'], 'step_min': step,
        'energy_kWh': {owner: float(v.sum()/3.6e6) for owner,v in energy.items()},
        'facility_kWh': float(facility.sum()/3.6e6), 'max_account_residual_J': residual,
        'energy_owner_terms': terms,
        'meter_scope': {'facility_is_whole_building': True,
            'all_installed_electricity_belongs_to_selected_test_home': True,
            'neighbours_are_free_floating_without_installed_electric_loads': True,
            'neighbour_household_operation_reproduced': False},
        'zones': zone_results, 'HVAC_control_zone': target,
        'directly_HVAC_connected_selected_home_zones': connected,
        'single_zone_temperature_is_not_whole_home_temperature': True,
        'whole_home_comfort_success': None,
        'native_water_L': {n: float(v.sum()) for n,v in water_volumes.items()},
        'water_service': water, 'whitegoods_source_window_completion': cycles,
        'cleaning_or_dryness_verified': False, 'EV_service': runtime['EV']['departure_service'],
        'EV_account': runtime['EV']['EB_ledger'],
        'ground_physical_applicability_approved': False,
        'annual_validation_granted': False, 'formal_admitted': formal,
        'source_reference_configuration_reviewed':formal,
        'native_curve_domain_quality':curve_quality,
        'ground_applicability_scope':'Approval covers the declared reference installation only; actual household foundation/terrain is not inferred.',
        'engineering_instructions_not_final_AB': True,
        'data_dictionary': {'electricity': 'native interval energy in kWh; not instantaneous kW',
            'zone_temperature': 'native zone-timestep mean, all selected dwelling zones retained separately',
            'general_water': 'fixture request only; machine water and distribution waste reported separately',
            'water_heating': 'water-use heating demand is not added as another electricity meter'},
        'timeseries': reference(out/'TIMESERIES.csv', root), 'implementation': reference(Path(__file__), root)}
    if spec.get('water_effect_scope'):
        from .water_scope import describe
        result['water_effect_scope'] = describe(rows, fields, spec['water_effect_scope'], root=root)
        result['data_dictionary']['general_water'] = (
            'mixed DHW fixture draw request only; independent source aggregate water-related heat/moisture '
            'is retained separately; machine water and distribution waste are separate outputs')
    save(out/'RESULTS.json', result)
    return result
