"""Source-backed People capacity with the existing EB device pack frozen."""
import copy
from pathlib import Path
import time

from .common import ROOT,read,save,require,digest,sha,verify,AdmissionError
from .reference_workflow import ref
from .source_adapter import source_file,selector,housing_fingerprint
from .housing_pipeline import validate_entry,implementation
from .condition_occupancy import validate_design,prepare as prepare_donor,review as review_donor
from .idf import parse,render,objects,Fields
from .program_resources import model_signature

POLICY='configs/condition_people_capacity_v1.json'


def replacement(parent,donor,number):
    before=parse(source_file(parent['model'],ROOT).read_text());source=parse(source_file(donor['model'],ROOT).read_text())
    fields=Fields(source_file(parent['engine_schema'],ROOT));target=objects(before,'People');people=objects(source,'People')
    require(len(target)==len(people)==1,'PEOPLE_CAPACITY_SINGLE_ZONE_REQUIRED')
    value=copy.deepcopy(people[0]);require(float(fields.get(value,'number_of_people'))==number,'PEOPLE_CAPACITY_DONOR_COUNT')
    for name in ('number_of_people_schedule_name','activity_level_schedule_name'):
        fields.set(value,name,fields.get(target[0],name))
    same=copy.deepcopy(value);fields.set(same,'number_of_people',fields.get(target[0],'number_of_people'))
    require(same==target[0],'PEOPLE_CAPACITY_DONOR_OTHER_PROPERTIES_DIFFER')
    return before,before.index(target[0]),value


def review(entry,fixture):
    from .condition_physics import normalized
    folder=ROOT/entry['prepared_directory'];receipt=read(folder/'PEOPLE_CAPACITY.json');n=receipt['design_occupants'];validate_design(n)
    base=read(source_file(receipt['parent_preparation']['cache_entry'],ROOT));parent=validate_entry(base)
    donor_entry=read(source_file(receipt['donor_preparation']['cache_entry'],ROOT));donor=validate_entry(donor_entry)
    declared=entry['physical_definition']['people_capacity']
    require(declared=={'parent_key':base['physical_key'],'design_occupants':n,'donor_key':donor_entry['physical_key']}
        and receipt['policy']==entry['physical_definition']['physical_sources']['people_capacity_policy']==ref(ROOT/POLICY),
        'PEOPLE_CAPACITY_DECLARED_INPUT_CONFLICT')
    review_donor(donor_entry,donor)
    source,index,value=replacement(parent,donor,n);expected=copy.deepcopy(source);expected[index]=value
    actual=parse(source_file(fixture['model'],ROOT).read_text())
    require(normalized(expected,parent)==normalized(actual,fixture),'PEOPLE_CAPACITY_UNDECLARED_PHYSICS_CHANGE')
    original_pack=read(source_file(parent['resource_pack'],ROOT));pack=read(source_file(fixture['resource_pack'],ROOT))
    physical=lambda d:{k:v for k,v in d.items() if k not in ('id','binding_model_signature','source_evidence')}
    require(physical(original_pack)==physical(pack),'PEOPLE_CAPACITY_PROGRAMME_PHYSICS_CHANGED')
    domain=read(source_file(fixture['input_domain'],ROOT));old=read(source_file(parent['input_domain'],ROOT))
    require(domain['maximum_persons']==n and domain['max_water_flow_L_min']==old['max_water_flow_L_min'],
            'PEOPLE_CAPACITY_DOMAIN_NOT_COMPONENT_BOUND')
    require({k:v for k,v in domain.items() if k not in ('physics_configuration_id','maximum_persons','programs')}==
            {k:v for k,v in old.items() if k not in ('physics_configuration_id','maximum_persons','programs')},
            'PEOPLE_CAPACITY_OTHER_DOMAIN_CHANGED')
    programmes=lambda d:{k:{a:b for a,b in v.items() if a!='resource_pack'} for k,v in d['programs'].items()}
    require(programmes(domain)==programmes(old),'PEOPLE_CAPACITY_PROGRAMME_DOMAIN_CHANGED')
    return expected,{'receipt':ref(folder/'PEOPLE_CAPACITY.json'),'design_occupants':n,'source_donor_checked':True,
        'all_nonpeople_rows_preserved':True,'programme_electric_water_and_gain_parameters_unchanged':True,
        'water_capacity_and_independent_background_unchanged':True,'only_validator_bound_overridden':False}


def result(entry,fixture,path,preparation,number,hit,start):
    return {'schema':'national_idf.condition_preparation_resolution.v1','status':'prepared_reference_pending_domain_review',
        'physical_key':entry['physical_key'],'physics_configuration_id':fixture['id'],'cache_entry':ref(path),'fixture':entry['fixture'],
        'cache_hit':hit,'physical_model_rebuilt':not hit,'seconds':time.monotonic()-start,
        'survey_housing':copy.deepcopy(preparation['survey_housing']),'survey_housing_modified':False,
        'reference_housing':copy.deepcopy(preparation['reference_housing']),'design_occupants':number,
        'physical_or_reference_admission_granted':False}


def donor_for(preparation,parent,number,cache):
    """Reuse a complete public People donor by component compatibility.

    No country,house ID or energy outcome selects the donor. New geometry
    with the same source People properties needs no new end-use translation.
    """
    policy=ref(ROOT/'configs/condition_occupancy_v1.json')
    for path in sorted(cache.glob('housing_*.json')):
        entry=read(path);definition=entry['physical_definition'];design=definition.get('occupancy_design')
        if not design or design['occupants']!=number:continue
        sources=definition['physical_sources']
        if sources.get('occupancy_policy')!=policy or 'adapter_versions' not in sources['occupancy_adapter']['path']:continue
        fixture=validate_entry(entry);review_donor(entry,fixture)
        try:replacement(parent,fixture,number)
        except AdmissionError as error:
            if error.code=='PEOPLE_CAPACITY_DONOR_OTHER_PROPERTIES_DIFFER':continue
            raise
        receipt=read(ROOT/entry['prepared_directory']/'OCCUPANCY_DESIGN.json')
        return {'schema':'national_idf.condition_preparation_resolution.v1','physical_key':entry['physical_key'],
            'cache_entry':ref(path),'fixture':entry['fixture'],'physics_configuration_id':fixture['id'],
            'cache_hit':True,'physical_model_rebuilt':False,
            'reference_housing':receipt['parent_preparation']['reference_housing'],'survey_housing':{},
            'donor_reused_across_housing_conditions':receipt['parent_preparation']['physical_key']!=preparation['physical_key'],
            'selection_by_source_object_compatibility_not_energy':True,'physical_or_reference_admission_granted':False}
    return prepare_donor(preparation,number,cache)


def prepare(preparation,number,cache):
    validate_design(number);start=time.monotonic();base=read(source_file(preparation['cache_entry'],ROOT));parent=validate_entry(base)
    cache=Path(cache).resolve();require(cache.is_relative_to(ROOT),'PEOPLE_CAPACITY_CACHE_OUTSIDE_PROJECT');cache.mkdir(parents=True,exist_ok=True)
    # Old preparations remain reusable across changes to discovery code only
    # after their entire declarative transaction is replayed with currentcode.
    for path in sorted(cache.glob('housing_*.json')):
        entry=read(path);capacity=entry['physical_definition'].get('people_capacity')
        if not capacity or capacity['parent_key']!=base['physical_key'] or capacity['design_occupants']!=number:continue
        if entry['physical_definition']['physical_sources'].get('people_capacity_policy')!=ref(ROOT/POLICY):continue
        fixture=validate_entry(entry);review(entry,fixture)
        return result(entry,fixture,path,preparation,number,True,start)
    donor_prep=donor_for(preparation,parent,number,cache);donor_entry=read(source_file(donor_prep['cache_entry'],ROOT));donor=validate_entry(donor_entry)
    version=cache/'adapter_versions'/(sha(ROOT/'national_idf/condition_people_capacity.py')+'.py');version.parent.mkdir(exist_ok=True)
    if not version.exists():version.write_bytes((ROOT/'national_idf/condition_people_capacity.py').read_bytes())
    physical={'people_capacity':{'parent_key':base['physical_key'],'design_occupants':number,'donor_key':donor_entry['physical_key']},
        'physical_sources':{**base['physical_definition']['physical_sources'],'people_capacity_policy':ref(ROOT/POLICY),
            'donor_entry':donor_prep['cache_entry'],'capacity_adapter':ref(version)}}
    key='housing_'+digest(physical)[:28];index_path=cache/(key+'.json');hit=index_path.exists()
    if hit:entry=read(index_path);fixture=validate_entry(entry)
    else:
        out=cache/key;require(not out.exists(),'PEOPLE_CAPACITY_FAILED_ATTEMPT_RETAINED');out.mkdir()
        source,index,value=replacement(parent,donor,number);identifier='condition_people_'+digest(physical)[:24]
        pack={'schema':'national_idf.source_people_capacity_extension.v1','source_parent_fixture':base['fixture'],
            'source_donor_fixture':donor_prep['fixture'],'source_object':selector(parse(source_file(donor['model'],ROOT).read_text()),
                next(i for i,r in enumerate(parse(source_file(donor['model'],ROOT).read_text())) if r[0]=='People')),
            'target_object':selector(source,index),'design_occupants':number,'public_policy':ref(ROOT/POLICY),
            'only_people_capacity_changes':True,'all_appliance_and_water_physics_preserved':True}
        save(out/'CAPACITY_PACK.json',pack);(out/'PEOPLE.idf').write_text(render([value]));save(out/'MAPPING.json',parent['EB_mapping'])
        adapter={'schema':'national_idf.source_adapter.v1','adapter':'native_idf_objects.v1','id':identifier+'__source',
            'package_id':identifier+'__package','model':parent['model'],'engine_version':'25.2',
            'housing_sha256':housing_fingerprint(source),'thermal_zones':[r[1] for r in objects(source,'Zone')],
            'legacy_groups':{},'schedule_files':[],'support_conditions':{'use':'Explicit referencePeoplecapacity;unchangedEB'},
            'source_scope_gaps':['Own CASE numerical andcurve checks required;not full source operationalenduse scaling or nationalstock']}
        from .reference_workflow import schedule_dependency
        for i,row in enumerate(source):
            if row[0]=='Schedule:File':adapter['schedule_files'].append({'object':selector(source,i),'original_filename':row[3],
                'file':schedule_dependency(parent['dependencies'],row[3])})
        save(out/'ADAPTER.json',adapter)
        operation={'action':'replace','object':selector(source,index),'after':{'file':ref(out/'PEOPLE.idf'),'object':selector([value],0)},
            'reason':'Complete public sourcePeople object with explicit designcount;independent EBdevices unchanged',
            'evidence':ref(out/'CAPACITY_PACK.json'),'affected_meters':['Electricity:Facility']}
        blueprint={'schema':'national_idf.assembly_blueprint.v1','id':identifier,'source_adapter':ref(out/'ADAPTER.json'),
            'changes':[operation],'legacy_group_policy':{},'components':{k:{'status':'engineering_reference','evidence':ref(out/'CAPACITY_PACK.json')}
              for k in ('air_conditioner','washer','dryer','dishwasher','water_heater','ev')},
            'engine_schema':parent['engine_schema'],'eb_mapping':ref(out/'MAPPING.json'),'eb_binding_implementation':parent['EB_modules']['binding'],
            'site_weather':{'artifacts':[ref(out/'CAPACITY_PACK.json')],'weather':parent['weather']},
            'numerical_protocol':ref(ROOT/'configs/study_protocol.json'),'review_receipts':{},'assembly_gaps':[],
            'formal_release_gaps':adapter['source_scope_gaps']}
        save(out/'BLUEPRINT.json',blueprint)
        from .assembly import compile_assembly
        compile_assembly(identifier,out/'assembly',mode='engineering_reference',blueprint_ref=ref(out/'BLUEPRINT.json'))
        actual=parse((out/'assembly/in.idf').read_text());resource=read(source_file(parent['resource_pack'],ROOT))
        resource['binding_model_signature']=model_signature(actual);resource['source_evidence'].append(ref(out/'CAPACITY_PACK.json'))
        save(out/'RESOURCE_PACK.json',resource)
        domain=read(source_file(parent['input_domain'],ROOT));domain.update(physics_configuration_id=identifier,maximum_persons=number)
        for p in domain['programs'].values():p['resource_pack']=ref(out/'RESOURCE_PACK.json')
        save(out/'DOMAIN.json',domain)
        life=read(source_file(parent['life_installation_receipt'],ROOT))
        require(life['ready'] and life['installed_model_signature']==model_signature(source),'PEOPLE_CAPACITY_OLD_PORT_NOT_BOUND')
        life.update(installed_model_signature=model_signature(actual),pack=ref(out/'CAPACITY_PACK.json'),
                    source_people_capacity_parent=parent['life_installation_receipt'])
        from .life_binding import LifeBinding
        binding=LifeBinding(actual,Fields(source_file(parent['engine_schema'],ROOT)),life['mapping'])
        require(all(v['design_persons']==number for v in binding.people.values()),'PEOPLE_CAPACITY_NEW_PORT_NOT_BOUND')
        save(out/'LIFE_INSTALLATION.json',life)
        fixture=copy.deepcopy(parent);fixture.update(id=identifier,model=ref(out/'assembly/in.idf'),input_domain=ref(out/'DOMAIN.json'),
            resource_pack=ref(out/'RESOURCE_PACK.json'),life_installation_receipt=ref(out/'LIFE_INSTALLATION.json'),
            dependencies=read(out/'assembly/ASSEMBLY.json')['dependencies'])
        save(out/'FIXTURE.json',fixture)
        case=read(source_file(base['engineering_case'],ROOT));old=read(source_file(parent['input_domain'],ROOT))['maximum_persons']
        case['case_id']=identifier;case['environment']['physics_configuration_id']=identifier;case['life']['maximum_persons']=number
        for frame in case['life']['occupancy']:
            if frame['persons']==old:frame['persons']=number
        save(out/'CASE.json',case)
        from .joint_case_runtime import compile_joint_case,run_joint_case
        compile_joint_case(ref(out/'FIXTURE.json'),case,out/'compiled',mode='engineering_reference');run_joint_case(out/'compiled',out/'run',mode='engineering_reference')
        from scripts.validate_multicountry_life import validate
        require(validate(out/'run',fixture,case)['passed_input_and_component_checks'],'PEOPLE_CAPACITY_NATIVE_LEDGER_FAILED')
        from .condition_geometry import check
        geometry=read(ROOT/base['prepared_directory']/'GEOMETRY_CHECKS.json')
        save(out/'GEOMETRY_CHECKS.json',check(fixture,geometry['source_idf'],geometry['source_xml'],ref(out/'run/output/eplusout.eio')))
        save(out/'PEOPLE_CAPACITY.json',{'design_occupants':number,'parent_preparation':preparation,'donor_preparation':donor_prep,
            'policy':ref(ROOT/POLICY),'capacity_pack':ref(out/'CAPACITY_PACK.json'),
            'operational_source_other_defaults_intentionally_not_adopted':True})
        save(out/'EXECUTION.json',{'source_preparation':preparation,'native_component_life_checks_pass':True,
            'source_geometry_and_context_preserved':True,'own_CASE_quality_still_required':True})
        verify(out/'compiled')
        paths=['FIXTURE.json','CASE.json','PEOPLE_CAPACITY.json','CAPACITY_PACK.json','BLUEPRINT.json','GEOMETRY_CHECKS.json',
               'EXECUTION.json','compiled/MANIFEST.json','run/COMPONENT_CHECKS.json','run/LIFE_CHECKS.json']
        entry={'schema':'national_idf.condition_preparation_cache.v1','physical_key':key,'physical_definition':physical,
            'catalog_snapshot':base['catalog_snapshot'],'fixture':ref(out/'FIXTURE.json'),'engineering_case':ref(out/'CASE.json'),
            'source_directory':base['source_directory'],'prepared_directory':str(out.relative_to(ROOT)),
            'artifacts':[ref(out/p) for p in paths],'implementation':implementation(),
            'physical_or_reference_admission_granted':False,'state':'people_capacity_with_fixed_EB_pending_own_CASE_quality'}
        validate_entry(entry);review(entry,fixture);save(index_path,entry)
    return result(entry,fixture,index_path,preparation,number,hit,start)
