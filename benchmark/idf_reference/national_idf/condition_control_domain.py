"""Reuse public EB write limits without altering the installed physical model.

The old +/-2C probe envelope is not an equipment performance limit. Broader
explicit commands still need their own numerical and observed curve checks.
"""
import ast
import copy
from pathlib import Path
import time

from .common import ROOT,read,save,sha,digest,require
from .source_adapter import source_file
from .reference_workflow import ref
from .housing_pipeline import validate_entry,implementation
from .idf import parse,objects,Fields

POLICY='configs/condition_control_inputs_v1.json'
POLICIES={'EB_source_control_inputs_v1':POLICY,'EB_primary_method_control_inputs_v2':'configs/condition_primary_control_inputs_v2.json'}


def policy(identifier):
    value=read(ROOT/POLICIES.get(identifier,POLICY))
    require(identifier==value['id'],'CONTROL_INPUT_POLICY_UNKNOWN')
    for key in ('source_actuator_writer','source_preheat_controller','current_binding','source_tank'):
        source_file(value[key],ROOT)
    if 'source_primary_method' in value: source_file(value['source_primary_method'],ROOT)
    return value


def derive(fixture,identifier='EB_source_control_inputs_v1'):
    config=policy(identifier)
    primary={}
    if 'source_primary_method' in config:
        main=ast.parse(source_file(config['source_primary_method'],ROOT).read_text())
        values=[ast.literal_eval(n.value) for n in main.body if isinstance(n,ast.Assign)
                and any(isinstance(t,ast.Name) and t.id=='AC_OFF_FALLBACK_COOLING_SETPOINT' for t in n.targets)]
        require(len(values)==1 and values[0]==40.0,'PRIMARY_FALLBACK_SOURCE_CHANGED')
        direct=any(isinstance(n,ast.Call) and isinstance(n.func,ast.Attribute)
                   and n.func.attr=='set_actuator_value' and len(n.args)==3
                   and isinstance(n.args[2],ast.Call) and isinstance(n.args[2].func,ast.Name)
                   and n.args[2].func.id=='float' and len(n.args[2].args)==1
                   and isinstance(n.args[2].args[0],ast.Name) and n.args[2].args[0].id=='effective_sp'
                   for n in ast.walk(main))
        require(direct,'PRIMARY_DIRECT_WRITE_SOURCE_CHANGED')
        primary={'source_EB_main_method_cooling_fallback_C':values[0],
                 'source_EB_main_method_direct_write_verified':True}
    tree=ast.parse(source_file(config['source_actuator_writer'],ROOT).read_text())
    constants={node.targets[0].id:ast.literal_eval(node.value) for node in tree.body
        if isinstance(node,ast.Assign) and len(node.targets)==1 and isinstance(node.targets[0],ast.Name)
        and node.targets[0].id in ('_COOLING_SETPOINT_MIN','_COOLING_SETPOINT_MAX','_HEATING_SETPOINT_MIN','_HEATING_SETPOINT_MAX')}
    require(len(constants)==4,'CONTROL_INPUT_SOURCE_CONSTANTS_MISSING')
    controller=ast.parse(source_file(config['source_preheat_controller'],ROOT).read_text())
    cls=next(n for n in controller.body if isinstance(n,ast.ClassDef) and n.name=='WaterHeater')
    method=next(n for n in cls.body if isinstance(n,ast.FunctionDef) and n.name=='set_preheat_schedule')
    candidates=[n.value for n in ast.walk(method) if isinstance(n,ast.Assign) and
        any(isinstance(t,ast.Subscript) and isinstance(t.slice,ast.Constant) and t.slice.value=='preheat_temp_c' for t in n.targets)]
    require(len(candidates)==1,'CONTROL_INPUT_PREHEAT_SOURCE_MISSING')
    call=candidates[0]
    require(isinstance(call,ast.Call) and isinstance(call.func,ast.Name) and call.func.id=='float',
            'CONTROL_INPUT_PREHEAT_SOURCE_CHANGED')
    outer=call.args[0]
    require(isinstance(outer,ast.Call) and isinstance(outer.func,ast.Name) and outer.func.id=='max'
            and len(outer.args)==2,'CONTROL_INPUT_PREHEAT_SOURCE_CHANGED')
    inner=outer.args[1]
    require(isinstance(inner,ast.Call) and isinstance(inner.func,ast.Name) and inner.func.id=='min'
            and len(inner.args)==2 and isinstance(inner.args[1],ast.Name) and inner.args[1].id=='temp_c',
            'CONTROL_INPUT_PREHEAT_SOURCE_CHANGED')
    preheat=[float(ast.literal_eval(outer.args[0])),float(ast.literal_eval(inner.args[0]))]
    rows=parse(source_file(fixture['model'],ROOT).read_text());fields=Fields(source_file(fixture['engine_schema'],ROOT))
    tanks=objects(rows,'WaterHeater:Stratified')
    require(len(tanks)==1 and tanks[0][1]==fixture['EB_mapping']['water_heater'],'CONTROL_INPUT_TANK_NOT_BOUND')
    max_C=float(fields.get(tanks[0],'maximum_temperature_limit'))
    expected=read(source_file(config['source_tank'],ROOT))['physical_parameters']
    require(all(fields.get(tanks[0],k)==v for k,v in expected.items()),'CONTROL_INPUT_TANK_PHYSICS_CHANGED')
    bounds={'heating_C':[constants['_HEATING_SETPOINT_MIN'],constants['_HEATING_SETPOINT_MAX']],
        'cooling_C':[constants['_COOLING_SETPOINT_MIN'],constants['_COOLING_SETPOINT_MAX']],
        'tank_target_C':[preheat[0],min(preheat[1],max_C)]}
    schedules=[]
    for mode in ('heating','cooling'):
        port=fixture['EB_mapping']['hvac'][mode]
        interval=list(bounds[mode+'_C'])
        if mode=='cooling' and primary: interval[1]=max(interval[1],primary['source_EB_main_method_cooling_fallback_C'])
        schedules.append((next(r for r in objects(rows,port['kind']) if r[1]==port['schedule']),interval))
    for key in ('heater_1_setpoint_temperature_schedule_name','heater_2_setpoint_temperature_schedule_name'):
        name=fields.get(tanks[0],key)
        schedules.append((next(r for r in objects(rows,'Schedule:Constant') if r[1]==name),bounds['tank_target_C']))
    for schedule,interval in schedules:
        limits=next(r for r in objects(rows,'ScheduleTypeLimits') if r[1]==schedule[2])
        require((not limits[2] or float(limits[2])<=interval[0]) and
                (not limits[3] or float(limits[3])>=interval[1]),'CONTROL_INPUT_SCHEDULE_TYPE_CONFLICT')
    return bounds,{**primary,'source_EB_actuator_limits':constants,'source_preheat_limits_C':preheat,
        'actual_native_tank_max_C':max_C,'schedule_type_limits_checked':True,
        'no_silent_clamp_or_controller_policy_inferred':True,'performance_domain_not_inferred_from_setpoint_bounds':True}


def review(entry,fixture):
    from .condition_physics import inspect_preparation
    folder=ROOT/entry['prepared_directory'];receipt=read(folder/'CONTROL_INPUT_DOMAIN.json')
    base=read(source_file(receipt['parent_preparation']['cache_entry'],ROOT));parent=validate_entry(base)
    selected_path=ROOT/receipt['policy']['path']
    selected=read(source_file(receipt['policy'],ROOT))['id']
    require(POLICIES.get(selected)==str(selected_path.relative_to(ROOT)),'CONTROL_INPUT_POLICY_PATH')
    expected={'parent_key':base['physical_key'],'policy':ref(selected_path)}
    require(entry['physical_definition']['control_input_domain']==expected and receipt['policy']==ref(selected_path),
            'CONTROL_INPUT_PARENT_OR_POLICY_CONFLICT')
    bounds,derivation=derive(parent,selected);old=read(source_file(parent['input_domain'],ROOT));domain=copy.deepcopy(old)
    domain['physics_configuration_id']=fixture['id'];domain['bounds'].update(bounds)
    if 'source_EB_main_method_cooling_fallback_C' in derivation:
        domain['special_control_values']={'cooling_C':[derivation['source_EB_main_method_cooling_fallback_C']]}
    require(domain==read(source_file(fixture['input_domain'],ROOT)) and derivation==receipt['derivation'],
            'CONTROL_INPUT_DOMAIN_NOT_SOURCE_DERIVED')
    before=copy.deepcopy(parent);before.update(id=fixture['id'],input_domain=fixture['input_domain'])
    require(before==fixture,'CONTROL_INPUT_UNDECLARED_PHYSICAL_CHANGE')
    parent_review=inspect_preparation(base,parent)
    return parse(source_file(parent['model'],ROOT).read_text()),{
        'receipt':ref(folder/'CONTROL_INPUT_DOMAIN.json'),'derived_bounds':bounds,
        'actual_model_and_every_hardware_parameter_unchanged':True,
        'old_test_interval_not_claimed_as_hardware_performance_limit':True,
        'new_CASE_quality_and_observed_performance_still_required':True,'parent_package_review':parent_review}


def prepare(preparation,identifier,cache):
    policy(identifier);selected_path=ROOT/POLICIES[identifier];start=time.monotonic();base=read(source_file(preparation['cache_entry'],ROOT));parent=validate_entry(base)
    require(preparation['fixture']==base['fixture'],'CONTROL_INPUT_PARENT_NOT_BOUND')
    cache=Path(cache).resolve();require(cache.is_relative_to(ROOT),'CONTROL_INPUT_CACHE_OUTSIDE_PROJECT');cache.mkdir(parents=True,exist_ok=True)
    definition={'parent_key':base['physical_key'],'policy':ref(selected_path)}
    for path in sorted(cache.glob('housing_*.json')):
        entry=read(path)
        if entry['physical_definition'].get('control_input_domain')==definition:
            fixture=validate_entry(entry);review(entry,fixture)
            return result(entry,path,preparation,True,start)
    adapter=cache/'adapter_versions'/(sha(ROOT/'national_idf/condition_control_domain.py')+'.py');adapter.parent.mkdir(exist_ok=True)
    if not adapter.exists():adapter.write_bytes((ROOT/'national_idf/condition_control_domain.py').read_bytes())
    physical={'control_input_domain':definition,'physical_sources':{**base['physical_definition']['physical_sources'],
        'control_input_policy':ref(selected_path),'control_input_adapter':ref(adapter)}}
    key='housing_'+digest(physical)[:28];index=cache/(key+'.json');folder=cache/key
    require(not folder.exists(),'CONTROL_INPUT_FAILED_ATTEMPT_RETAINED');folder.mkdir()
    bounds,derivation=derive(parent,identifier);identifier='condition_controls_'+digest(physical)[:24]
    domain=read(source_file(parent['input_domain'],ROOT));domain['physics_configuration_id']=identifier;domain['bounds'].update(bounds)
    if 'source_EB_main_method_cooling_fallback_C' in derivation:
        domain['special_control_values']={'cooling_C':[derivation['source_EB_main_method_cooling_fallback_C']]}
    save(folder/'DOMAIN.json',domain);fixture=copy.deepcopy(parent);fixture.update(id=identifier,input_domain=ref(folder/'DOMAIN.json'))
    save(folder/'FIXTURE.json',fixture);case=read(source_file(base['engineering_case'],ROOT));case['environment']['physics_configuration_id']=identifier
    save(folder/'CASE.json',case);save(folder/'GEOMETRY_CHECKS.json',read(ROOT/base['prepared_directory']/'GEOMETRY_CHECKS.json'))
    save(folder/'CONTROL_INPUT_DOMAIN.json',{'parent_preparation':preparation,'policy':ref(selected_path),'derivation':derivation})
    save(folder/'EXECUTION.json',{'source_preparation':preparation,'physical_model_rebuilt':False,
        'input_contract_only_changed':True,'own_native_CASE_quality_not_yet_completed':True})
    paths=['DOMAIN.json','FIXTURE.json','CASE.json','GEOMETRY_CHECKS.json','CONTROL_INPUT_DOMAIN.json','EXECUTION.json']
    entry={'schema':'national_idf.condition_preparation_cache.v1','physical_key':key,'physical_definition':physical,
        'catalog_snapshot':base['catalog_snapshot'],'fixture':ref(folder/'FIXTURE.json'),'engineering_case':ref(folder/'CASE.json'),
        'prepared_directory':str(folder.relative_to(ROOT)),'source_directory':base['source_directory'],
        'artifacts':[ref(folder/p) for p in paths],'implementation':implementation(),
        'physical_or_reference_admission_granted':False,'state':'same_source_physics_EB_control_bounds_pending_own_CASE_quality'}
    validate_entry(entry);review(entry,fixture);save(index,entry)
    return result(entry,index,preparation,False,start)


def result(entry,path,parent,hit,start):
    return {'schema':'national_idf.condition_preparation_resolution.v1','physical_key':entry['physical_key'],
        'physics_configuration_id':read(source_file(entry['fixture'],ROOT))['id'],'cache_entry':ref(path),'fixture':entry['fixture'],
        'status':'prepared_reference_pending_domain_review','cache_hit':hit,'physical_model_rebuilt':False,
        'input_domain_rebound':True,'seconds':time.monotonic()-start,'survey_housing':copy.deepcopy(parent['survey_housing']),
        'survey_housing_modified':False,'reference_housing':copy.deepcopy(parent['reference_housing']),
        'physical_or_reference_admission_granted':False}
