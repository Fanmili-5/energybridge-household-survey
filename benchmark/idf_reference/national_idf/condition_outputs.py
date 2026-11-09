"""Evidence-bound,per-output validation of an actual reference CASE result.

An accepted CASE is not a national stock model,unconditional geometry-domain
release or HVAC-sizing certificate. Optional diagnostic limitations remain
visible without waiving the original criteria on requested CASE outputs.
"""
import argparse
import copy
import csv
from collections import defaultdict
from pathlib import Path

from .common import ROOT,read,save,require,digest,sha,verify
from .reference_workflow import ref
from .source_adapter import source_file
from .housing_pipeline import validate_entry
from .condition_physics import inspect_preparation,normalized
from .idf import parse,objects,Fields

CORE=('whole_home_electricity','whole_home_temperature','device_resource_accounts','EV_energy_and_departure_state')
UNSUPPORTED=('HVAC_capacity_selection','national_stock_or_real_home_equivalence','room_level_temperature',
             'cleanliness_or_dryness','event_specific_water_room_gains','bath_success')


def physical_case(case):
    value=copy.deepcopy(case);value.pop('case_id',None);value['environment'].pop('physics_configuration_id',None)
    value['life'].pop('basis',None);return value


def domain(folder):
    if (folder/'compiled/DOMAIN.json').exists():return read(folder/'compiled/DOMAIN.json')
    fixture=read(folder/'parent/FIXTURE.json');return read(source_file(fixture['input_domain'],ROOT))


def water_grid(folder,step):
    width=read(ROOT/'configs/study_protocol.json')['comparison_grid_min'];bins=defaultdict(lambda:[0.,0.,0.,0.])
    with (folder/'LIFE_SYSTEM.csv').open() as stream:
        for row in csv.DictReader(stream):
            mass=float(row['EB_WATER_dhw fixtures:total_kg_s'])*float(row['seconds'])
            temperature=float(row['EB_WATER_dhw fixtures:mixed_C']);target=float(row['EB_WATER_dhw fixtures:target_C'])
            value=bins[int(row['frame_index'])*step//width]
            value[0]+=mass;value[1]+=mass*temperature;value[2]+=mass*max(target-temperature,0)
            value[3]+=float(row['EB_WATER_dhw fixtures:total_m3'])*1000
    return bins


def numerical_replay(base,quality):
    from scripts.analyze_multicountry_life_numerics import PAIRS,compare_paths
    comparisons={};water={}
    def folder(args,arm):
        s,w,d=args;return base/f's{s}_w{w}_d{d}_{arm}'
    for name,left,right in PAIRS:
        folders=[folder(args,arm) for args in (left,right) for arm in ('baseline','intervention')]
        if not all((p/'run/RUNTIME.json').exists() for p in folders):
            require(name=='5_vs_2min' and quality['comparisons'][name]['passed'] is None,'CONDITION_OUTPUT_NUMERICS_MISSING')
            comparisons[name]=quality['comparisons'][name];continue
        for p in folders:verify(p/'compiled')
        comparisons[name]=compare_paths([folder(left,a)/'run' for a in ('baseline','intervention')],
                                       [folder(right,a)/'run' for a in ('baseline','intervention')])
        require(comparisons[name]==quality['comparisons'][name],'CONDITION_OUTPUT_NUMERICAL_RECEIPT_CHANGED',name)
        water[name]={}
        for arm in ('baseline','intervention'):
            grids=[water_grid(folder(args,arm)/'run',domain(folder(args,arm))['solver_step_min']) for args in (left,right)]
            common=set(grids[0])&set(grids[1]);active=[k for k in common if all(v[k][0]>0 for v in grids)]
            require(common,'CONDITION_OUTPUT_WATER_NO_COMMON_CLOCK')
            errors=[abs(grids[0][k][1]/grids[0][k][0]-grids[1][k][1]/grids[1][k][0]) for k in active]
            water[name][arm]={'active_bins':len(active),'mass_weighted_delivery_MAE_C':sum(errors)/len(errors) if errors else None,
                'maximum_delivery_difference_C':max(errors) if errors else None,
                'common_volume_difference_L':sum(grids[0][k][3]-grids[1][k][3] for k in common),
                'common_temperature_shortfall_difference_K_kg':sum(grids[0][k][2]-grids[1][k][2] for k in common),
                'personal_service_tolerance_or_success_inferred':False}
    fine=all(comparisons[k]['passed'] is True for k in ('2_vs_1min','warmup_14_vs_28days','tail_7_vs_14days'))
    selected=5 if fine and comparisons['5_vs_2min']['passed'] else 2 if fine else None
    require(selected==quality['selected_step_min'],'CONDITION_OUTPUT_SELECTED_STEP_CHANGED')
    return comparisons,water,selected


def publish(execution_path,out,requested=None):
    from scripts.validate_multicountry_life import validate
    from .reference_retirement import audit as retirement
    folder=Path(execution_path).resolve().parent;out=Path(out).resolve()
    require(out.is_relative_to(ROOT) and not out.exists(),'CONDITION_OUTPUT_DIRECTORY_EXISTS');out.mkdir(parents=True)
    execution=read(execution_path);prep=execution['source_preparation'];entry=read(source_file(prep['cache_entry'],ROOT));base=validate_entry(entry)
    require(prep['fixture']==entry['fixture'] and prep['physics_configuration_id']==base['id'],'CONDITION_OUTPUT_PREPARATION_CONFLICT')
    physics=inspect_preparation(entry,base);save(out/'PHYSICS.json',physics)
    fixture=read(source_file(execution['fixture'],ROOT));case=read(folder/'CASE.json')
    before=normalized(parse(source_file(base['model'],ROOT).read_text()),base)
    actual=normalized(parse(source_file(fixture['model'],ROOT).read_text()),fixture)
    if execution.get('calendar_transaction'):
        transaction=read(source_file(execution['calendar_transaction'],ROOT))
        require(transaction['source_fixture']==entry['fixture'] and transaction['run']==case['run'],
                'CONDITION_OUTPUT_CALENDAR_NOT_BOUND')
        from .condition_calendar import rows_for_window
        source_window=read(source_file(base['input_domain'],ROOT))['run_period']
        before=rows_for_window(before,Fields(source_file(base['engine_schema'],ROOT)),case['run'],source_window)
    if execution.get('explicit_numerical_method'):
        method=read(source_file(execution['explicit_numerical_method'],ROOT))
        require(method['algorithm']=='AnalyticalSolution' and method['engine_schema']==base['engine_schema'],'CONDITION_OUTPUT_METHOD_NOT_BOUND')
        existing=objects(before,'ZoneAirHeatBalanceAlgorithm')
        require(len(existing)<=1,'CONDITION_OUTPUT_METHOD_CARDINALITY')
        if existing:before[before.index(existing[0])]=['ZoneAirHeatBalanceAlgorithm','AnalyticalSolution']
        else:before.append(['ZoneAirHeatBalanceAlgorithm','AnalyticalSolution'])
    require(before==actual,'CONDITION_OUTPUT_UNDECLARED_PHYSICAL_CHANGE')
    verify(folder/'compiled')
    installed=execution['installed_devices'];partial=len(installed)!=6
    implementation_path=folder/('compiled/IMPLEMENTATION.json' if partial else 'run/IMPLEMENTATION.json')
    for p,s in read(implementation_path).items():require(sha(ROOT/p)==s,'CONDITION_OUTPUT_RUNTIME_CODE_CHANGED',p)
    domain_path=folder/'compiled/DOMAIN.json' if partial else None
    native=validate(folder/'run',fixture,case,installed,domain_path)
    require(native['passed_input_and_component_checks'],'CONDITION_OUTPUT_NATIVE_ACCOUNTS_FAILED')
    if partial:
        pack=read(folder/'inventory/PACK.json')
        save(out/'RETIREMENT.json',retirement(parse(source_file(fixture['model'],ROOT).read_text()),
            parse((folder/'compiled/in.idf').read_text()),pack,Fields(source_file(fixture['engine_schema'],ROOT))))
    quality=read(source_file(execution['quality'],ROOT));qfolder=folder/('inventory_quality/numerics' if partial else 'numerics')
    require(read(source_file(quality['parent_fixture'],ROOT))==fixture,'CONDITION_OUTPUT_QUALITY_WRONG_PHYSICS')
    if partial:
        require(physical_case(read(folder/'inventory_quality/main/CASE.json'))==physical_case(case),'CONDITION_OUTPUT_QUALITY_WRONG_CASE')
    else:
        from .reference_release import request_digest
        require(quality['request_sha256']==request_digest(case),'CONDITION_OUTPUT_QUALITY_WRONG_CASE')
    comparisons,water,selected=numerical_replay(qfolder,quality)
    observer=folder/('inventory_quality/curve_observed' if partial else 'curve_observed')
    verify(observer/'compiled')
    require((folder/'run/TRACE.csv').read_bytes()==(observer/'run/TRACE.csv').read_bytes(),
            'CONDITION_OUTPUT_CURVE_OBSERVER_NOT_SAME_CASE')
    from .reference_curve_observer import instrument,report
    rows=parse(source_file(fixture['model'],ROOT).read_text());fields=Fields(source_file(fixture['engine_schema'],ROOT))
    observed_rows,tables=instrument(rows,fields);curve=report(observed_rows,tables,fields,observer/'run')
    require(quality['curve_domain_passed'] and curve['passed_observed_domain_screen'],'CONDITION_OUTPUT_CURVE_DOMAIN_FAILED')
    save(out/'CURVE_REPLAY.json',curve)
    # Recheck the actual foreground/background permissions before publishing.
    if execution.get('control_contract_checks'):
        from .condition_controls import validate as validate_controls
        from .case_commands import CaseTimeline
        eq=read(folder/'EQUIPMENT.json');bound=execution['control_contract_checks']['contract']
        d=read(domain_path or source_file(fixture['input_domain'],ROOT));validate_controls(case,CaseTimeline(case,d),eq,bound)
        require(len(execution['numerical_contract_checks'])==10,'CONDITION_OUTPUT_DIAGNOSTIC_CONTROL_CHECKS_MISSING')
    save(out/'NUMERICAL_REPLAY.json',{'comparisons':comparisons,'selected_step_min':selected,'original_criteria_unchanged':True})
    save(out/'WATER_RESOLUTION.json',{'comparisons':water,'service_success_threshold_C':None,
        'source_method':'Existing native mixed-water delivery-grid accounting;no new comfort or accuracy tolerance',
        'bath_success_or_event_specific_room_heat_claimed':False})
    outputs={name:{'status':'validated_for_this_reference_CASE' if selected else 'numerical_requirements_failed'} for name in CORE}
    if 'ev' not in installed:outputs['EV_energy_and_departure_state']={'status':'not_installed'}
    outputs['mixed_water_delivery_profile']={'status':'reported_with_resolution_sensitivity','evidence':ref(out/'WATER_RESOLUTION.json')}
    for name in UNSUPPORTED:outputs[name]={'status':'unsupported','reason':'Not established by this CASE;requires separate evidence and relevant acceptance conditions'}
    requested=list(requested if requested is not None else [v for v in CORE if v!='EV_energy_and_departure_state' or 'ev' in installed])
    require(requested,'CONDITION_OUTPUT_EMPTY_REQUEST')
    unknown=[v for v in requested if v not in outputs]
    require(not unknown,'CONDITION_OUTPUT_NAME_UNKNOWN',unknown)
    complete=all(outputs[v]['status']=='validated_for_this_reference_CASE' for v in requested)
    receipt={'schema':'national_idf.validated_reference_case_outputs.v1','status':'requested_CASE_outputs_validated' if complete else 'requested_outputs_not_fully_supported',
        'execution':ref(execution_path),'physics_configuration_id':execution['physics_configuration_id'],
        'reference_housing':prep['reference_housing'],'weather':fixture['weather'],'case':ref(folder/'CASE.json'),
        'requested_outputs':requested,'outputs':outputs,'required_request_checks_pass':selected is not None,
        'physics_evidence':ref(out/'PHYSICS.json'),'numerical_evidence':ref(out/'NUMERICAL_REPLAY.json'),
        'curve_evidence':ref(out/'CURVE_REPLAY.json'),
        'whole_home_native_accounts':ref(folder/'run/COMPONENT_CHECKS.json'),'life_native_accounts':ref(folder/'run/LIFE_CHECKS.json'),
        'frozen_domain':ref(ROOT/'configs/condition_reference_domain_v1.json'),
        'model_domain_or_stock_admission_granted':False,'household_generation_or_final_AB_changed':False,
        'implementation':{p:sha(ROOT/p) for p in ('national_idf/condition_outputs.py','national_idf/condition_physics.py')}}
    save(out/'RESULT.json',receipt);return receipt


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--execution',type=Path,required=True);p.add_argument('--out',type=Path,required=True)
    p.add_argument('--outputs',nargs='+');a=p.parse_args();publish(a.execution,a.out,a.outputs)
