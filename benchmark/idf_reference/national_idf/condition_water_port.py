"""Source-design normalization of the aggregate water demand input.

The existing binding divides requested flow by peak;EnergyPlus multiplies it
back. Scale fixture and distribution peaks together,without resizing hardware
or changing either physical demand or the source waste ratio.
"""
import copy
import math
from pathlib import Path
import time

from .common import ROOT,read,save,require,digest,sha,verify
from .reference_workflow import ref,schedule_dependency
from .source_adapter import source_file,selector,housing_fingerprint
from .housing_pipeline import validate_entry,implementation
from .idf import parse,render,Fields,objects
from .program_resources import model_signature,plan_resources

POLICY='configs/condition_water_input_v1.json'


def policy(identifier):
    value=read(ROOT/POLICY);require(identifier==value['id'],'WATER_INPUT_POLICY_UNKNOWN')
    for source in value['source_basis'].values():source_file(source,ROOT)
    return value


def transform(fixture):
    rows=parse(source_file(fixture['model'],ROOT).read_text());after=copy.deepcopy(rows)
    fields=Fields(source_file(fixture['engine_schema'],ROOT))
    receipt=read(source_file(fixture['life_installation_receipt'],ROOT));mapping=receipt['mapping']['mixed_water']
    names=[mapping['delivered_object'],*mapping['distribution_waste_objects']]
    require(len(names)==len(set(names))==2,'WATER_NORMALIZATION_AGGREGATE_FIXTURE_AND_WASTE_REQUIRED')
    equipment={r[1]:r for r in objects(rows,'WaterUse:Equipment')}
    require(all(n in equipment for n in names),'WATER_NORMALIZATION_FIXTURE_MISSING')
    connections=[r for r in objects(rows,'WaterUse:Connections') if all(n in r for n in names)]
    loops=objects(rows,'PlantLoop');pumps=objects(rows,'Pump:VariableSpeed')+objects(rows,'Pump:ConstantSpeed')
    tanks=[r for r in objects(rows,'WaterHeater:Stratified') if r[1]==fixture['EB_mapping']['water_heater']]
    require(len(connections)==len(loops)==len(pumps)==len(tanks)==1,'WATER_NORMALIZATION_SINGLE_LOOP_CONTEXT_REQUIRED')
    require(any(connections[0][1] in r for r in objects(rows,'Branch')) and any(tanks[0][1] in r for r in objects(rows,'Branch')),
            'WATER_NORMALIZATION_LOOP_COMPONENTS_NOT_BOUND')
    def number(row,key):
        raw=fields.get(row,key)
        try:value=float(raw)
        except (ValueError,TypeError):value=None
        require(value is not None and math.isfinite(value) and value>0,'WATER_NORMALIZATION_EXPLICIT_SOURCE_FLOW_REQUIRED',[row[:2],key,raw])
        return value
    constraints=[]
    for row,key in [(tanks[0],'use_side_design_flow_rate'),(loops[0],'maximum_loop_flow_rate'),
                    (pumps[0],'design_maximum_flow_rate' if pumps[0][0]=='Pump:VariableSpeed' else 'design_flow_rate')]:
        constraints.append({'object':selector(rows,rows.index(row)),'field':key,'value_m3_s':number(row,key),'units':'m3/s'})
    connected=[n for n in equipment if n in connections[0]]
    other=[n for n in connected if n not in names]
    reserve=sum(number(equipment[n],'peak_flow_rate') for n in other)
    controlled=sum(number(equipment[n],'peak_flow_rate') for n in names)
    scale=(min(v['value_m3_s'] for v in constraints)-reserve)/controlled
    require(math.isfinite(scale) and scale>=1,'WATER_NORMALIZATION_SOURCE_DESIGN_NOT_LARGER')
    changes=[]
    for name in names:
        old=equipment[name];require(fields.get(old,'flow_rate_fraction_schedule_name')==mapping['flow_schedule'],
                                    'WATER_NORMALIZATION_UNBOUND_SCHEDULE')
        new=copy.deepcopy(old);fields.set(new,'peak_flow_rate',format(number(old,'peak_flow_rate')*scale,'.17g'))
        index=rows.index(old);after[index]=new
        changes.append({'object':selector(rows,index),'before':old,'after':new,'field':'peak_flow_rate','units':'m3/s'})
    delivered=next(c['after'] for c in changes if c['before'][1]==mapping['delivered_object'])
    return after,{'source_model':fixture['model'],'source_design_flows':constraints,'other_water_consumers':other,
        'other_source_peak_reserve_m3_s':reserve,'controlled_source_peak_sum_m3_s':controlled,'common_scale':scale,
        'normalization_peak_L_min':number(delivered,'peak_flow_rate')*60000,'changes':changes,
        'hardware_design_values_not_maximum_or_service_guarantee':True,'no_device_or_background_parameters_changed':True}


def review(entry,fixture):
    from .condition_physics import normalized,inspect_preparation
    folder=ROOT/entry['prepared_directory'];receipt=read(folder/'WATER_NORMALIZATION.json')
    base=read(source_file(receipt['parent_preparation']['cache_entry'],ROOT));parent=validate_entry(base)
    require(entry['physical_definition']['water_normalization']=={'parent_key':base['physical_key'],'policy':ref(ROOT/POLICY)}
            and receipt['policy']==ref(ROOT/POLICY),'WATER_NORMALIZATION_DECLARED_PARENT_CONFLICT')
    source_review=inspect_preparation(base,parent)
    expected,proof=transform(parent);require(proof==receipt['derivation'],'WATER_NORMALIZATION_DERIVATION_NOT_REPRODUCIBLE')
    actual=parse(source_file(fixture['model'],ROOT).read_text())
    require(normalized(expected,parent)==normalized(actual,fixture),'WATER_NORMALIZATION_UNDECLARED_PHYSICAL_CHANGE')
    before=read(source_file(parent['resource_pack'],ROOT));pack=read(source_file(fixture['resource_pack'],ROOT))
    data=lambda d:{k:v for k,v in d.items() if k not in ('id','binding_model_signature','source_evidence')}
    require(data(before)==data(pack),'WATER_NORMALIZATION_PROGRAMME_CHANGED')
    old=read(source_file(parent['input_domain'],ROOT));domain=read(source_file(fixture['input_domain'],ROOT))
    def other(d):
        value=copy.deepcopy(d)
        for k in ('physics_configuration_id','max_water_flow_L_min'):value.pop(k)
        for p in value['programs'].values():p.pop('resource_pack',None)
        return value
    require(other(old)==other(domain) and domain['max_water_flow_L_min']==proof['normalization_peak_L_min'],
            'WATER_NORMALIZATION_INPUT_DOMAIN_NOT_DERIVED')
    return expected,{'receipt':ref(folder/'WATER_NORMALIZATION.json'),'derivation':proof,'source_parent_review':source_review,
        'all_nonfixture_peak_rows_preserved':True,'original_water_waste_ratio_preserved':True,
        'programme_electric_water_and_gains_unchanged':True,'same_demand_native_equivalence_still_required':True}


def prepare(preparation,identifier,cache):
    policy(identifier);start=time.monotonic();base=read(source_file(preparation['cache_entry'],ROOT));parent=validate_entry(base)
    require(preparation['fixture']==base['fixture'],'WATER_NORMALIZATION_PARENT_CONFLICT')
    cache=Path(cache).resolve();require(cache.is_relative_to(ROOT),'WATER_NORMALIZATION_CACHE_OUTSIDE_PROJECT');cache.mkdir(parents=True,exist_ok=True)
    definition={'parent_key':base['physical_key'],'policy':ref(ROOT/POLICY)}
    for path in sorted(cache.glob('housing_*.json')):
        entry=read(path)
        if entry['physical_definition'].get('water_normalization')==definition:
            fixture=validate_entry(entry);review(entry,fixture);return result(entry,fixture,path,preparation,True,start)
    version=cache/'adapter_versions'/(sha(ROOT/'national_idf/condition_water_port.py')+'.py');version.parent.mkdir(exist_ok=True)
    if not version.exists():version.write_bytes((ROOT/'national_idf/condition_water_port.py').read_bytes())
    physical={'water_normalization':definition,'physical_sources':{**base['physical_definition']['physical_sources'],
        'water_input_policy':ref(ROOT/POLICY),'water_adapter':ref(version)}}
    key='housing_'+digest(physical)[:28];path=cache/(key+'.json');out=cache/key
    require(not out.exists(),'WATER_NORMALIZATION_FAILED_ATTEMPT_RETAINED');out.mkdir()
    expected,proof=transform(parent);source=parse(source_file(parent['model'],ROOT).read_text());identifier='condition_water_'+digest(physical)[:24]
    pack={'schema':'national_idf.source_water_input_normalization_pack.v1','parent_fixture':base['fixture'],
          'policy':ref(ROOT/POLICY),'derivation':proof,'mapping':read(source_file(parent['life_installation_receipt'],ROOT))['mapping']}
    save(out/'NORMALIZATION_PACK.json',pack);new_rows=[c['after'] for c in proof['changes']]
    (out/'PEAKS.idf').write_text(render(new_rows));save(out/'MAPPING.json',parent['EB_mapping'])
    adapter={'schema':'national_idf.source_adapter.v1','adapter':'native_idf_objects.v1','id':identifier+'__source','package_id':identifier+'__package',
        'model':parent['model'],'engine_version':'25.2','housing_sha256':housing_fingerprint(source),'thermal_zones':[r[1] for r in objects(source,'Zone')],
        'legacy_groups':{},'schedule_files':[],'support_conditions':{'use':'Source-design inputnormalization;hardware unchanged'},
        'source_scope_gaps':['Same-demand equivalence andownoriginalCASEquality required;no pressure or thermalserviceguarantee']}
    for i,row in enumerate(source):
        if row[0]=='Schedule:File':adapter['schedule_files'].append({'object':selector(source,i),'original_filename':row[3],
            'file':schedule_dependency(parent['dependencies'],row[3])})
    save(out/'ADAPTER.json',adapter)
    changes=[{'action':'replace','object':c['object'],'after':{'file':ref(out/'PEAKS.idf'),'object':selector(new_rows,i)},
        'reason':'Common-source peak rescaling with inverse existingCASE binding;physicalflow andwaste ratio preserved',
        'evidence':ref(out/'NORMALIZATION_PACK.json'),'affected_meters':['Electricity:Facility','WaterSystems:Electricity']}
        for i,c in enumerate(proof['changes'])]
    blueprint={'schema':'national_idf.assembly_blueprint.v1','id':identifier,'source_adapter':ref(out/'ADAPTER.json'),'changes':changes,'legacy_group_policy':{},
        'components':{k:{'status':'engineering_reference','evidence':ref(out/'NORMALIZATION_PACK.json')}
                      for k in ('air_conditioner','washer','dryer','dishwasher','water_heater','ev')},
        'engine_schema':parent['engine_schema'],'eb_mapping':ref(out/'MAPPING.json'),'eb_binding_implementation':parent['EB_modules']['binding'],
        'site_weather':{'artifacts':[ref(out/'NORMALIZATION_PACK.json')],'weather':parent['weather']},
        'numerical_protocol':ref(ROOT/'configs/study_protocol.json'),'review_receipts':{},'assembly_gaps':[],'formal_release_gaps':adapter['source_scope_gaps']}
    save(out/'BLUEPRINT.json',blueprint)
    from .assembly import compile_assembly
    plan_resources(source,parent['engine_schema'],parent['resource_pack'])
    compile_assembly(identifier,out/'assembly',mode='engineering_reference',blueprint_ref=ref(out/'BLUEPRINT.json'))
    actual=parse((out/'assembly/in.idf').read_text());resource=read(source_file(parent['resource_pack'],ROOT))
    resource['binding_model_signature']=model_signature(actual);resource['source_evidence'].append(ref(out/'NORMALIZATION_PACK.json'));save(out/'RESOURCE_PACK.json',resource)
    plan_resources(actual,parent['engine_schema'],ref(out/'RESOURCE_PACK.json'))
    domain=read(source_file(parent['input_domain'],ROOT));domain.update(physics_configuration_id=identifier,max_water_flow_L_min=proof['normalization_peak_L_min'])
    for p in domain['programs'].values():p['resource_pack']=ref(out/'RESOURCE_PACK.json')
    save(out/'DOMAIN.json',domain)
    life=read(source_file(parent['life_installation_receipt'],ROOT));require(life['installed_model_signature']==model_signature(source) and life['ready'],
        'WATER_NORMALIZATION_OLD_PORT_NOT_BOUND')
    life.update(installed_model_signature=model_signature(actual),pack=ref(out/'NORMALIZATION_PACK.json'),source_water_normalization_parent=parent['life_installation_receipt'])
    from .life_binding import LifeBinding
    LifeBinding(actual,Fields(source_file(parent['engine_schema'],ROOT)),life['mapping']);save(out/'LIFE_INSTALLATION.json',life)
    fixture=copy.deepcopy(parent);fixture.update(id=identifier,model=ref(out/'assembly/in.idf'),input_domain=ref(out/'DOMAIN.json'),
        resource_pack=ref(out/'RESOURCE_PACK.json'),life_installation_receipt=ref(out/'LIFE_INSTALLATION.json'),dependencies=read(out/'assembly/ASSEMBLY.json')['dependencies'])
    save(out/'FIXTURE.json',fixture);case=read(source_file(base['engineering_case'],ROOT));case['case_id']=identifier;case['environment']['physics_configuration_id']=identifier
    save(out/'CASE.json',case)
    from .joint_case_runtime import compile_joint_case,run_joint_case
    compile_joint_case(ref(out/'FIXTURE.json'),case,out/'compiled',mode='engineering_reference');run_joint_case(out/'compiled',out/'run',mode='engineering_reference')
    from scripts.validate_multicountry_life import validate
    require(validate(out/'run',fixture,case)['passed_input_and_component_checks'],'WATER_NORMALIZATION_NATIVE_LEDGER_FAILED')
    from .condition_geometry import check
    geometry=read(ROOT/base['prepared_directory']/'GEOMETRY_CHECKS.json');save(out/'GEOMETRY_CHECKS.json',check(fixture,geometry['source_idf'],geometry['source_xml'],ref(out/'run/output/eplusout.eio')))
    save(out/'WATER_NORMALIZATION.json',{'parent_preparation':preparation,'policy':ref(ROOT/POLICY),'derivation':proof})
    save(out/'EXECUTION.json',{'source_preparation':preparation,'native_component_life_checks_pass':True,'source_geometry_and_context_preserved':True,
        'same_demand_quality_and_equivalence_not_waived':True});verify(out/'compiled')
    paths=['FIXTURE.json','CASE.json','WATER_NORMALIZATION.json','NORMALIZATION_PACK.json','BLUEPRINT.json','GEOMETRY_CHECKS.json',
           'EXECUTION.json','compiled/MANIFEST.json','run/COMPONENT_CHECKS.json','run/LIFE_CHECKS.json']
    entry={'schema':'national_idf.condition_preparation_cache.v1','physical_key':key,'physical_definition':physical,'catalog_snapshot':base['catalog_snapshot'],
        'fixture':ref(out/'FIXTURE.json'),'engineering_case':ref(out/'CASE.json'),'source_directory':base['source_directory'],'prepared_directory':str(out.relative_to(ROOT)),
        'artifacts':[ref(out/p) for p in paths],'implementation':implementation(),'physical_or_reference_admission_granted':False,
        'state':'water_input_normalization_pending_own_CASE_quality_and_equivalence'}
    validate_entry(entry);review(entry,fixture);save(path,entry);return result(entry,fixture,path,preparation,False,start)


def result(entry,fixture,path,preparation,hit,start):
    return {'schema':'national_idf.condition_preparation_resolution.v1','status':'prepared_reference_pending_domain_review',
        'physical_key':entry['physical_key'],'physics_configuration_id':fixture['id'],'cache_entry':ref(path),'fixture':entry['fixture'],
        'cache_hit':hit,'physical_model_rebuilt':not hit,'seconds':time.monotonic()-start,
        'survey_housing':copy.deepcopy(preparation['survey_housing']),'survey_housing_modified':False,
        'reference_housing':copy.deepcopy(preparation['reference_housing']),'water_input_policy':read(ROOT/POLICY)['id'],
        'physical_or_reference_admission_granted':False}
