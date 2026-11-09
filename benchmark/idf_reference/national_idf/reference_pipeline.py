"""Housing inputs→shared packages→existing EB→evidence-bound reference outputs.

Exact physical/life/control inputs may reuse a fully hashed result bundle.
New inputs keep the original numerical suite;no domain-wide waiver is added.
"""
import argparse
import copy
from pathlib import Path
import time

from .common import ROOT,read,save,require,digest,sha,AdmissionError
from .source_adapter import source_file
from .reference_workflow import ref
from .housing_pipeline import prepare as prepare_housing,validate_entry
from .condition_packages import prepare as compose
from .condition_housing import plan
from .reference_context import resolve
from .reference_scenarios import inventory
from .condition_inventory import require_no_absent_demands
from .condition_outputs import CORE,UNSUPPORTED,physical_case
from .reference_domain_outputs import publish

DEFAULTS='configs/reference_runtime_defaults_v7.json'

def implementation():
    from .release import compiler_identity
    from .runtime_release import runtime_identity
    from .housing_pipeline import implementation as housing_identity
    paths=('configs/CASE.v3.schema.json','configs/condition_primary_control_inputs_v2.json','national_idf/dated_case.py','national_idf/reference_pipeline.py','national_idf/condition_actions.py','national_idf/condition_inventory.py',
        'national_idf/condition_controls.py','national_idf/condition_quality.py','scripts/check_condition_housing.py',
        'scripts/check_condition_inventory.py','national_idf/condition_outputs.py','national_idf/condition_physics.py',
        'national_idf/condition_calendar.py','national_idf/condition_occupancy.py','national_idf/condition_people_capacity.py','national_idf/condition_water_port.py','national_idf/condition_control_domain.py','scripts/prepare_condition_solver.py',
        'configs/study_protocol.json','configs/reference_template_policy_v2.json',
        'configs/reference_calendar_policy_v1.json','configs/reference_experiment_frame_v1.json','configs/condition_occupancy_v1.json',
        'configs/condition_people_capacity_v1.json','configs/condition_water_input_v1.json',
        DEFAULTS,'configs/condition_control_inputs_v1.json',
        'national_idf/condition_packages.py','national_idf/condition_envelope.py','national_idf/condition_defaults.py',
        'national_idf/reference_enclosure.py','national_idf/reference_domain_outputs.py','national_idf/regional_profile.py',
        'national_idf/reference_context.py','national_idf/reference_scenarios.py',
        'national_idf/reference_curve_observer.py','national_idf/water_scope.py')
    return {**compiler_identity(),**runtime_identity(),**housing_identity(),**{p:sha(ROOT/p) for p in paths}}


def equipment_physics(equipment):
    """Keep flags andsharing graph;asset labels/provenance are not watts."""
    groups={};result={}
    for name in sorted(equipment):
        value=equipment[name]
        require(set(value)<={'physically_present','control_enabled','asset_id','presence_basis','background_service_id'},
                'REFERENCE_PIPELINE_UNSUPPORTED_EQUIPMENT_OVERRIDE',name)
        asset=value.get('asset_id') if value['physically_present'] else None
        if asset is not None and asset not in groups:groups[asset]=len(groups)
        result[name]={'physically_present':value['physically_present'],'control_enabled':value['control_enabled'],
            'asset_group':groups.get(asset),'background_service_id':value.get('background_service_id')}
    return result


def execution_defaults(request):
    """Project solver/profiles are configured once, not by each household."""
    require(isinstance(request,dict),'REFERENCE_PIPELINE_REQUEST_OBJECT_REQUIRED')
    result=copy.deepcopy(request);defaults=read(ROOT/DEFAULTS);selected={}
    for name in ('fractional_libraries','numerical_method'):
        if name not in request:
            result[name]=defaults[name];source_file(result[name],ROOT);selected[name]=result[name]
    return result,{'policy':ref(ROOT/DEFAULTS),'selected_execution_inputs':selected,
        'housing_equipment_CASE_and_survey_facts_unchanged':True}


def resolve_request(request):
    request,_=execution_defaults(request)
    require(isinstance(request,dict),'REFERENCE_PIPELINE_REQUEST_OBJECT_REQUIRED')
    require(request.get('schema')=='national_idf.reference_pipeline_request.v1','REFERENCE_PIPELINE_SCHEMA')
    allowed={'schema','request_id','housing','reference_context_policy','select_reference_policy',
        'envelope_recipe_id','equipment','case','control_contract','requested_outputs','numerical_method','fractional_libraries','design_occupants','water_input_policy','control_input_policy'}
    require(set(request)<=allowed,'REFERENCE_PIPELINE_UNSUPPORTED_FIELDS')
    if request.get('water_input_policy') is not None:
        from .condition_water_port import policy
        policy(request['water_input_policy'])
    if request.get('design_occupants') is not None:
        from .condition_occupancy import validate_design
        validate_design(request['design_occupants'])
    if request.get('control_input_policy') is not None:
        from .condition_control_domain import policy as control_policy
        control_policy(request['control_input_policy'])
    missing=[name for name in ('housing','equipment','case','fractional_libraries') if request.get(name) is None]
    if missing:
        return {'status':'candidate_or_missing_conditions',
                'gaps':[{'field':name,'code':'INPUT_REQUIRED'} for name in missing]}
    require(isinstance(request['housing'],dict),'REFERENCE_PIPELINE_HOUSING_OBJECT_REQUIRED')
    for name in ('equipment','case','fractional_libraries','numerical_method','control_contract'):
        if request.get(name):
            require(isinstance(request[name],dict) and {'path','sha256'}<=set(request[name]),
                    'REFERENCE_PIPELINE_SOURCE_REFERENCE_REQUIRED',name)
    housing=copy.deepcopy(request['housing']);resolution=None
    if housing.get('schema')!='national_idf.housing_condition_request.v1':
        require(request.get('reference_context_policy'),'REFERENCE_PIPELINE_REFERENCE_POLICY_REQUIRED')
        resolution=resolve(housing,request['reference_context_policy'],consent=request.get('select_reference_policy') is True)
        if resolution['gaps']:return {'status':'candidate_or_missing_conditions','gaps':resolution['gaps'],'resolution':resolution}
        housing=resolution['housing_request']
    design=plan(housing)
    if design['status']!='constructible_reference':return {'status':'candidate_or_missing_conditions','gaps':design.get('missing',[])}
    frame=read(ROOT/'configs/reference_experiment_frame_v1.json')
    lower,upper=frame['conditioned_area_m2_inclusive']
    require(lower<=housing['reference_housing']['conditioned_area_m2']<=upper,
            'REFERENCE_PIPELINE_AREA_OUTSIDE_DECLARED_EXPERIMENT_FRAME')
    if request.get('envelope_recipe_id'):
        from .condition_envelope import recipe
        chosen=recipe(request['envelope_recipe_id'])
        require(chosen['country']==housing['country'],'REFERENCE_PIPELINE_RECIPE_COUNTRY_CONFLICT')
        from .condition_housing import CATALOG
        source_attic=read(source_file(read(ROOT/CATALOG)['sources']['builder_workflow'],ROOT))['steps'][0]['arguments']['geometry_attic_type']
        if chosen.get('adapter')=='complete_reference_constructions_v1':
            require(housing['reference_housing']['vertical_context'] in chosen['supported_vertical_contexts'],
                    'REFERENCE_PIPELINE_RECIPE_GEOMETRY_CONTEXT_UNSUPPORTED')
        else:
            require(design['definition']['builder_arguments'].get('geometry_attic_type')==source_attic,
                    'REFERENCE_PIPELINE_RECIPE_ATTIC_CONTEXT_UNSUPPORTED')
    eq=read(source_file(request['equipment'],ROOT))
    require(isinstance(eq,dict) and all(isinstance(v,dict) and
            {'physically_present','control_enabled'}<=set(v) for v in eq.values()),
            'REFERENCE_PIPELINE_EQUIPMENT_FLAGS_REQUIRED')
    inv=inventory(eq)
    equipment_physics(eq)
    require(not inv['unknown_presence'],'REFERENCE_PIPELINE_EQUIPMENT_PRESENCE_UNKNOWN')
    require(set(inv['installed'])>={'air_conditioner','water_heater'} and 4<=len(inv['installed'])<=6,'REFERENCE_PIPELINE_EQUIPMENT_DOMAIN')
    from .condition_controls import BACKGROUND_DEVICES
    require(set(inv['installed'])-set(inv['controlled'])<=BACKGROUND_DEVICES,'REFERENCE_PIPELINE_BACKGROUND_DOMAIN')
    shared=any(a!=b and eq[a]['physically_present'] and eq[b]['physically_present'] and eq[a]['asset_id']==eq[b]['asset_id'] for a in eq for b in eq)
    for a in eq:
        for b in eq:
            if a!=b and eq[a]['physically_present'] and eq[b]['physically_present'] and eq[a]['asset_id']==eq[b]['asset_id']:
                require({a,b}=={'WM','DR'},'REFERENCE_PIPELINE_SHARED_ASSET_DOMAIN')
    require(set(inv['installed'])==set(inv['controlled']) and not shared or request.get('control_contract'),
            'REFERENCE_PIPELINE_FIXED_SHARED_CONTRACT_REQUIRED')
    case=read(source_file(request['case'],ROOT))
    from .request_support import syntax_failures
    failures=syntax_failures(case,ROOT)
    # The request deliberately has no compiled ID yet. All other CASE schema
    # requirements remain; do not fabricate an ID or fill missing inputs.
    if isinstance(case,dict) and case.get('environment')=={'physics_configuration_id':None}:
        failures=[v for v in failures if v['path']!=['environment','physics_configuration_id']]
    require(not failures,'REFERENCE_PIPELINE_CASE_SCHEMA',failures)
    require(case['environment'].get('physics_configuration_id') is None,'REFERENCE_PIPELINE_ID_MUST_BE_DERIVED')
    from .condition_calendar import validate_window
    calendar=read(ROOT/'configs/reference_calendar_policy_v1.json')
    calendar_case=read(source_file(calendar['source_engineering_case'],ROOT))
    validate_window(case['run'],calendar_case['run'])
    require_no_absent_demands(case,{'equipment':eq})
    known=set(CORE)|set(UNSUPPORTED)|{'mixed_water_delivery_profile'}
    require('requested_outputs' not in request or bool(request['requested_outputs']),'REFERENCE_PIPELINE_EMPTY_OUTPUT_REQUEST')
    require(all(v in known for v in request.get('requested_outputs',CORE)),'REFERENCE_PIPELINE_OUTPUT_NAME_UNKNOWN')
    for name in ('numerical_method','fractional_libraries','control_contract'):
        if request.get(name):source_file(request[name],ROOT)
    return {'status':'conditions_resolved_not_yet_physics_validated','housing_request':housing,'resolution':resolution}


def cache_key(preparation,request):
    request,_=execution_defaults(request)
    case=physical_case(read(source_file(request['case'],ROOT)))
    # All demand/control values anddevice relations remain;only explicit
    # nonphysical labels/provenance are excluded,with original input retained.
    return 'result_'+digest({'physical_key':preparation['physical_key'],'equipment':equipment_physics(read(source_file(request['equipment'],ROOT))),
        'case':case,'contract':request.get('control_contract'),'method':request.get('numerical_method'),
        'libraries':request['fractional_libraries'],'implementation':implementation()})[:28]


def template_preparation(housing,cache):
    """Reuse complete source geometry across locations before declared re-siting."""
    from .condition_housing import CATALOG
    start=time.monotonic();created=False
    from .housing_pipeline import physical_sources
    catalog=read(ROOT/CATALOG);design=plan(housing);policy=read(ROOT/'configs/reference_template_policy_v2.json')
    require(policy['site_replacement_must_follow'] is True,'REFERENCE_TEMPLATE_RESITING_NOT_DECLARED')
    definition={'builder_arguments':design['definition']['builder_arguments'],'reference_conditions':housing['reference_housing'],
                'physical_sources':physical_sources(design,catalog)}
    cache=Path(cache).resolve();require(cache.is_relative_to(ROOT),'REFERENCE_TEMPLATE_CACHE_OUTSIDE_PROJECT')
    registry=cache/'template_index'/('template_'+digest(definition)[:28]+'.json')
    if registry.exists():index=source_file(read(registry)['source_entry'],ROOT)
    else:
        candidates=[]
        for path in sorted(cache.glob('housing_*.json')):
            entry=read(path);value=entry['physical_definition']
            if all(value.get(k)==v for k,v in definition.items()):validate_entry(entry);candidates.append(path)
        if candidates:index=candidates[0]
        else:
            intermediate=copy.deepcopy(housing);intermediate.update(policy['intermediate_sites_by_country'][housing['country']])
            prep=prepare_housing(intermediate,cache);created=prep['physical_model_rebuilt'];index=source_file(prep['cache_entry'],ROOT)
        save(registry,{'source_entry':ref(index),'definition':definition,'policy':ref(ROOT/'configs/reference_template_policy_v2.json')})
    entry=read(index);fixture=validate_entry(entry)
    return {'schema':'national_idf.condition_preparation_resolution.v1','status':'source_template_pending_target_site',
        'physical_key':entry['physical_key'],'physics_configuration_id':fixture['id'],'cache_entry':ref(index),
        'fixture':entry['fixture'],'cache_hit':not created,'physical_model_rebuilt':created,'seconds':time.monotonic()-start,
        'survey_housing':copy.deepcopy(housing.get('survey_housing',{})),'survey_housing_modified':False,
        'reference_housing':copy.deepcopy(housing['reference_housing']),
        'intermediate_template_region_not_household_location':True,'physical_or_reference_admission_granted':False}


def select_packages(request,preparation):
    """Select shared reference inputs, without changing facts, CASE or hardware.

    A declared life maximum is a design load, not an inferred census fact.
    The water normalization changes only a peak/fraction representation; its
    accepted native equivalence is checked before it becomes a default.
    Explicit null preserves the original source mode for comparisons.
    """
    defaults_path=ROOT/DEFAULTS
    defaults=read(defaults_path);effective=copy.deepcopy(request)
    fixture=read(source_file(preparation['fixture'],ROOT))
    source_domain=read(source_file(fixture['input_domain'],ROOT))
    count=read(source_file(request['case'],ROOT))['life']['maximum_persons']
    if 'design_occupants' not in request and count>source_domain['maximum_persons']:
        from .condition_occupancy import validate_design
        validate_design(count);effective['design_occupants']=count
    if 'water_input_policy' not in request:
        admission=read(source_file(defaults['native_admission'],ROOT))
        require(admission['schema']=='national_idf.water_input_policy_native_admission.v1',
                'REFERENCE_DEFAULT_NATIVE_ADMISSION_SCHEMA')
        for name,signature in admission['critical_implementation'].items():
            require(sha(ROOT/name)==signature,'REFERENCE_DEFAULT_IMPLEMENTATION_CHANGED',name)
        for name,signature in admission['native_evidence_hashes'].items():
            require(sha(ROOT/name)==signature,'REFERENCE_DEFAULT_NATIVE_EVIDENCE_CHANGED',name)
        for item in admission['same_demand_equivalence']:
            require(read(source_file(item,ROOT))['all_original_accuracy_requirements_pass'],
                    'REFERENCE_DEFAULT_EQUIVALENCE_NOT_PASSED')
        for item in admission['higher_draw_native_results']:
            evidence=read(source_file(item,ROOT))
            require(all(evidence['outputs'][name]['status']=='validated_for_this_reference_CASE' for name in CORE),
                    'REFERENCE_DEFAULT_NATIVE_QUALITY_NOT_PASSED')
        effective['water_input_policy']=defaults['water_input_policy']
    if 'control_input_policy' not in request and defaults.get('control_input_policy'):
        evidence=read(source_file(defaults['control_native_admission'],ROOT))
        require(evidence['schema']=='national_idf.control_input_native_admission.v1','REFERENCE_CONTROL_ADMISSION_SCHEMA')
        for name,signature in {**evidence['critical_implementation'],**evidence['native_evidence_hashes']}.items():
            require(sha(ROOT/name)==signature,'REFERENCE_CONTROL_ADMISSION_CHANGED',name)
        equivalence=read(source_file(evidence['same_commands_equivalence'],ROOT))
        require(equivalence['original_criteria_pass'] and equivalence['main_TRACE_byte_identical'],
                'REFERENCE_CONTROL_EQUIVALENCE_NOT_PASSED')
        for item in evidence['native_results']:
            require(read(source_file(item,ROOT))['status']=='requested_CASE_outputs_validated',
                    'REFERENCE_CONTROL_NATIVE_QUALITY_NOT_PASSED')
        effective['control_input_policy']=defaults['control_input_policy']
    return effective,{'shared_defaults':ref(defaults_path),
        'source_people_capacity':source_domain['maximum_persons'],
        'declared_life_maximum_persons':count,
        'selected_design_occupants':effective.get('design_occupants'),
        'people_capacity_selected_from_declared_life': 'design_occupants' not in request and 'design_occupants' in effective,
        'water_input_policy':effective.get('water_input_policy'),
        'water_policy_selected_from_shared_default':'water_input_policy' not in request,
        'control_input_policy':effective.get('control_input_policy'),
        'control_policy_selected_from_shared_default':'control_input_policy' not in request and bool(defaults.get('control_input_policy')),
        'survey_facts_CASE_and_equipment_unchanged':True,
        'selection_uses_energy_or_control_effects':False}


def register(preparation,request,execution_path,result_path,cache):
    request,_=execution_defaults(request)
    result=read(result_path);execution=read(execution_path);folder=Path(execution_path).resolve().parent
    require(result['execution']==ref(execution_path) and result['physics_configuration_id']==execution['physics_configuration_id'],
            'REFERENCE_PIPELINE_RESULT_NOT_BOUND')
    require(execution['source_preparation']['physical_key']==preparation['physical_key'],'REFERENCE_PIPELINE_PHYSICS_NOT_IDENTICAL')
    require(equipment_physics(read(source_file(request['equipment'],ROOT)))==equipment_physics(read(folder/'EQUIPMENT.json')),
            'REFERENCE_PIPELINE_EQUIPMENT_NOT_IDENTICAL')
    require(physical_case(read(source_file(request['case'],ROOT)))==physical_case(read(folder/'CASE.json')),'REFERENCE_PIPELINE_CASE_NOT_IDENTICAL')
    require(request.get('numerical_method')==execution.get('explicit_numerical_method'),'REFERENCE_PIPELINE_METHOD_NOT_IDENTICAL')
    require(result['implementation']=={p:sha(ROOT/p) for p in result['implementation']},'REFERENCE_PIPELINE_RESULT_CODE_CHANGED')
    cache=Path(cache).resolve();require(cache.is_relative_to(ROOT),'REFERENCE_PIPELINE_CACHE_OUTSIDE_PROJECT');cache.mkdir(parents=True,exist_ok=True)
    key=cache_key(preparation,request)
    # Lock actual native outputs,SQL,compiled input,all numerical variants and
    # source/output reviews. A previous boolean alone cannot authorize reuse.
    paths=[p for p in folder.rglob('*') if p.is_file()]+[p for p in Path(result_path).parent.rglob('*') if p.is_file()]
    evidence={str(p.relative_to(ROOT)):sha(p) for p in paths}
    curve=read(source_file(result['curve_evidence'],ROOT));policy=curve['unchanged_source_curve_method_policy']
    external=[result['frozen_domain'],policy,read(source_file(policy,ROOT))['source_code']]
    for item in external:source_file(item,ROOT)
    record={'schema':'national_idf.exact_reference_result_cache.v1','key':key,'preparation':preparation,
        'result':ref(result_path),'execution':ref(execution_path),'evidence':evidence,'implementation':implementation(),
        'external_review_references':external,
        'identical_full_inputs_only':True,'new_demand_quality_waiver_granted':False}
    index=cache/(key+'.json');require(not index.exists() or read(index)==record,'REFERENCE_PIPELINE_CACHE_CONFLICT')
    save(index,record);return record


def execute(request,out,housing_cache,package_cache,result_cache):
    start=time.monotonic();out=Path(out).resolve()
    require(out.is_relative_to(ROOT) and not out.exists(),'REFERENCE_PIPELINE_OUTPUT_EXISTS');out.mkdir(parents=True)
    save(out/'REQUEST.json',request)
    try:
        request,execution_setup=execution_defaults(request)
        save(out/'SHARED_EXECUTION_INPUTS.json',execution_setup)
        resolution=resolve_request(request);save(out/'RESOLUTION.json',resolution)
        if resolution['status']=='candidate_or_missing_conditions':
            response={'schema':'national_idf.reference_pipeline_response.v1',**resolution,
                      'new_native_simulation_executed':False}
            save(out/'RESULT.json',response);return response
        # Compiler/input semantics can evolve while frozen models and old
        # failures stay available. New code gets one shared cache generation,
        # rather than overwriting old preparations or requiring per-family
        # manual cache repair.
        generation = 'implementation_' + digest(implementation())[:20]
        housing_cache = Path(housing_cache) / generation
        package_cache = Path(package_cache) / generation
        save(out/'CACHE_GENERATION.json', {'generation': generation,
            'housing_cache': str(housing_cache), 'package_cache': str(package_cache),
            'old_preparations_and_failures_preserved': True})
        prep=template_preparation(resolution['housing_request'],housing_cache) if request.get('envelope_recipe_id') else prepare_housing(resolution['housing_request'],housing_cache)
        request,selected=select_packages(request,prep)
        save(out/'SELECTED_PACKAGES.json',selected);save(out/'EFFECTIVE_REQUEST.json',request)
        if request.get('design_occupants') is not None:
            from .condition_people_capacity import prepare as prepare_occupancy
            prep=prepare_occupancy(prep,request['design_occupants'],package_cache)
        if request.get('envelope_recipe_id'):
            prep=compose(prep,request['envelope_recipe_id'],resolution['housing_request']['site_id'],package_cache)
        if request.get('water_input_policy') is not None:
            from .condition_water_port import prepare as prepare_water
            prep=prepare_water(prep,request['water_input_policy'],package_cache)
        if request.get('control_input_policy') is not None:
            from .condition_control_domain import prepare as prepare_controls
            prep=prepare_controls(prep,request['control_input_policy'],package_cache)
        save(out/'PREPARATION.json',prep)
        from .regional_profile import audit as regional_audit
        save(out/'REGIONAL_ENCLOSURE_READBACK.json',regional_audit(read(source_file(prep['fixture'],ROOT)),
            resolution['housing_request']['country'],resolution['housing_request']['site_id']))
        cache=Path(result_cache).resolve();require(cache.is_relative_to(ROOT),'REFERENCE_PIPELINE_CACHE_OUTSIDE_PROJECT')
        index=cache/(cache_key(prep,request)+'.json');hit=index.exists()
        if hit:
            record=read(index);require(record['implementation']==implementation(),'REFERENCE_PIPELINE_CACHE_CODE_CHANGED')
            for item in record['external_review_references']:source_file(item,ROOT)
            for path,signature in record['evidence'].items():require(sha(ROOT/path)==signature,'REFERENCE_PIPELINE_CACHED_EVIDENCE_CHANGED',path)
            result=read(source_file(record['result'],ROOT));evidence=record['result']
        else:
            from .condition_actions import run
            run(prep,read(source_file(request['equipment'],ROOT)),read(source_file(request['case'],ROOT)),out/'execution',request['fractional_libraries'],
                contract_ref=request.get('control_contract'),numerical_method_ref=request.get('numerical_method'))
            result=publish(out/'execution/EXECUTION.json',out/'validated_outputs')
            register(prep,request,out/'execution/EXECUTION.json',out/'validated_outputs/RESULT.json',cache)
            evidence=ref(out/'validated_outputs/RESULT.json')
        requested=request.get('requested_outputs') or result['requested_outputs']
        passed=all(result['outputs'][v]['status']=='validated_for_this_reference_CASE' for v in requested)
        response={'schema':'national_idf.reference_pipeline_response.v1','status':'requested_CASE_outputs_validated' if passed else 'requested_outputs_not_fully_supported',
            'request_id':request.get('request_id'),'reference_housing':prep['reference_housing'],'survey_housing':prep['survey_housing'],
            'reference_design_occupants':request.get('design_occupants'),
            'selected_packages':ref(out/'SELECTED_PACKAGES.json'),
            'physics_configuration_id':result['physics_configuration_id'],'result_evidence':evidence,
            'requested_outputs':requested,'output_status':{v:result['outputs'][v] for v in requested},
            'identical_full_input_result_reused':hit,'new_native_simulation_executed':not hit,'seconds':time.monotonic()-start,
            'model_or_country_domain_admission_granted':False,'household_generation_and_final_AB_changed':False}
        save(out/'RESULT.json',response);return response
    except AdmissionError as error:
        failure={'status':'request_not_executed_or_not_publishable','gap_code':error.code,'details':error.detail,
                 'evidence_preserved':True,'no_other_recipe_date_or_demand_silently_substituted':True}
        save(out/'FAILURE.json',failure)
        response={'schema':'national_idf.reference_pipeline_response.v1',**failure}
        save(out/'RESULT.json',response);return response


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--request',type=Path,required=True);p.add_argument('--out',type=Path,required=True)
    p.add_argument('--housing-cache',type=Path,required=True);p.add_argument('--package-cache',type=Path,required=True);p.add_argument('--result-cache',type=Path,required=True)
    a=p.parse_args();execute(read(a.request),a.out,a.housing_cache,a.package_cache,a.result_cache)
