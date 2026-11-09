"""A source-native occupancy design package over complete cached housing.

The public builder writes NumberofResidents;its full translator owns all
dependent defaults. This adapter does not edit IDF People counts or loosen
CASE bounds. Existing EB installation,compiler and physics are reused.
"""
import copy
from pathlib import Path
import time
import xml.etree.ElementTree as ET

from .common import ROOT,read,save,require,digest,verify,sha
from .reference_workflow import ref
from .source_adapter import source_file
from .housing_pipeline import validate_entry,implementation
from .condition_housing import plan,_command
from .idf import parse,Fields,objects

POLICY='configs/condition_occupancy_v1.json'


def validate_design(value):
    policy=read(ROOT/POLICY)
    for item in policy['source_options'].values():source_file(item,ROOT)
    require(type(value) is int and value in policy['positive_design_occupants'],
            'OCCUPANCY_DESIGN_OUTSIDE_SOURCE_CHOICES')
    options=source_file(policy['source_options']['choices'],ROOT).read_text().splitlines()
    require(any(line.split('\t')[:2]==[str(value),str(value)] for line in options),
            'OCCUPANCY_DESIGN_OPTION_NOT_PUBLISHED')
    return policy


def with_occupants(path,value):
    """Mirror the public builder's single HPXML assignment,not its defaults."""
    validate_design(value);tree=ET.parse(path);root=tree.getroot()
    namespace=root.tag.split('}')[0][1:];ET.register_namespace('',namespace)
    local=lambda e:e.tag.rsplit('}',1)[-1]
    summaries=[e for e in root.iter() if local(e)=='BuildingSummary']
    require(len(summaries)==1,'OCCUPANCY_DESIGN_MULTIPLE_UNITS_UNSUPPORTED')
    summary=summaries[0];occupancy=[e for e in summary if local(e)=='BuildingOccupancy']
    require(len(occupancy)<=1,'OCCUPANCY_DESIGN_OCCUPANCY_CARDINALITY')
    if occupancy:owner=occupancy[0]
    else:
        owner=ET.Element('{'+namespace+'}BuildingOccupancy')
        construction=next(e for e in summary if local(e)=='BuildingConstruction')
        summary.insert(list(summary).index(construction),owner)
    residents=[e for e in owner if local(e)=='NumberofResidents']
    require(len(residents)<=1,'OCCUPANCY_DESIGN_RESIDENT_CARDINALITY')
    resident=residents[0] if residents else ET.SubElement(owner,'{'+namespace+'}NumberofResidents')
    before=resident.text;resident.text=str(value)
    # Explicit input must not retain an author-generated default flag.
    resident.attrib.pop('dataSource',None)
    return tree,{'before':before,'after':value,'property':'BuildingOccupancy/NumberofResidents'}


def semantic_xml(path):
    def value(e):return [e.tag,sorted(e.attrib.items()),(e.text or '').strip(),[value(c) for c in e]]
    return value(ET.parse(path).getroot())


def review(entry,fixture):
    """Replay XML transaction and exact compiler alias before output release."""
    from .condition_physics import normalized
    d=entry['physical_definition']['occupancy_design'];validate_design(d['occupants'])
    folder=ROOT/entry['prepared_directory'];receipt=read(folder/'OCCUPANCY_DESIGN.json')
    require(receipt['occupants']==d['occupants'],'OCCUPANCY_DESIGN_RECEIPT_CONFLICT')
    parent_entry=read(source_file(receipt['parent_preparation']['cache_entry'],ROOT));validate_entry(parent_entry)
    require(receipt['parent_preparation']['physical_key']==d['base_housing_key'] and receipt['source_xml']==d['source_xml'],
            'OCCUPANCY_DESIGN_DECLARED_PARENT_CONFLICT')
    before=source_file(receipt['source_xml'],ROOT);after=source_file(receipt['derived_xml'],ROOT)
    expected,_=with_occupants(before,d['occupants'])
    def value(e):return [e.tag,sorted(e.attrib.items()),(e.text or '').strip(),[value(c) for c in e]]
    require(value(expected.getroot())==semantic_xml(after),'OCCUPANCY_DESIGN_XML_NOT_REPRODUCIBLE')
    original=read(source_file(receipt['source_installed_fixture'],ROOT))
    source=parse(source_file(original['model'],ROOT).read_text());actual=parse(source_file(fixture['model'],ROOT).read_text())
    require(normalized(source,original)==normalized(actual,fixture),'OCCUPANCY_DESIGN_ALIAS_CHANGED_PHYSICS')
    fields=Fields(source_file(fixture['engine_schema'],ROOT));people=objects(actual,'People')
    require(len(people)==1 and float(fields.get(people[0],'number_of_people'))==d['occupants'],
            'OCCUPANCY_DESIGN_SOURCE_PERSON_COUNT')
    domain=read(source_file(fixture['input_domain'],ROOT))
    require(domain['maximum_persons']==d['occupants'],'OCCUPANCY_DESIGN_BOUND_NOT_FROM_SOURCE')
    return source,{'receipt':ref(folder/'OCCUPANCY_DESIGN.json'),'design_occupants':d['occupants'],
                   'full_source_translation_executed':True,'typed_XML_replay':True,
                   'actual_people_and_domain_match':True,'validator_only_override':False}


def prepare(preparation,occupants,cache):
    policy=validate_design(occupants);start=time.monotonic()
    parent_entry=read(source_file(preparation['cache_entry'],ROOT));parent=validate_entry(parent_entry)
    require(preparation['fixture']==parent_entry['fixture'],'OCCUPANCY_DESIGN_PARENT_CONFLICT')
    require('builder_arguments' in parent_entry['physical_definition'],'OCCUPANCY_DESIGN_NEEDS_COMPLETE_BASE_TEMPLATE')
    base_source=ROOT/parent_entry['source_directory'];base_receipt=read(base_source/'SOURCE_RECEIPT.json')
    cache=Path(cache).resolve()
    require(cache.is_relative_to(ROOT),'OCCUPANCY_DESIGN_CACHE_OUTSIDE_PROJECT');cache.mkdir(parents=True,exist_ok=True)
    version=cache/'adapter_versions'/(sha(ROOT/'national_idf/condition_occupancy.py')+'.py');version.parent.mkdir(exist_ok=True)
    if not version.exists():version.write_bytes((ROOT/'national_idf/condition_occupancy.py').read_bytes())
    physical={'occupancy_design':{'base_housing_key':parent_entry['physical_key'],'occupants':occupants,
                                  'source_xml':base_receipt['derived_XML']},
        'physical_sources':{**parent_entry['physical_definition']['physical_sources'],
            **policy['source_options'],'occupancy_policy':ref(ROOT/POLICY),
            'occupancy_adapter':ref(version)}}
    key='housing_'+digest(physical)[:28]
    index=cache/(key+'.json');hit=index.exists()
    if hit:entry=read(index);fixture=validate_entry(entry)
    else:
        folder=cache/key;require(not folder.exists(),'OCCUPANCY_DESIGN_FAILED_ATTEMPT_RETAINED');folder.mkdir()
        source=folder/'source';source.mkdir()
        request=read(base_source/'REQUEST.json');original_plan=read(base_source/'PLAN.json');current_plan=plan(request)
        # A registered catalog may have gained unrelated sites since this
        # geometry was built. Rebind metadata only when every actual source
        # argument and site is identical;never repair physical differences.
        def physical_plan(value):
            result=copy.deepcopy(value);result.pop('configuration_id',None)
            result['definition'].pop('source_catalog',None);return result
        require(physical_plan(original_plan)==physical_plan(current_plan),'OCCUPANCY_DESIGN_BASE_ARGUMENTS_CHANGED')
        save(source/'REQUEST.json',request);save(source/'PLAN.json',current_plan)
        tree,change=with_occupants(source_file(base_receipt['derived_XML'],ROOT),occupants)
        xml=source/'housing_with_devices.xml';tree.write(xml,encoding='utf-8',xml_declaration=True)
        catalog=read(source_file(parent_entry['catalog_snapshot'],ROOT));checkout=ROOT/catalog['checkout']
        cli=ROOT/read(source_file(catalog['sources']['sdk'],ROOT))['CLI_paths'][0]
        commands=[_command([cli,checkout/'workflow/run_simulation.rb','-x',xml,'-o',source/'source_model',
                            '-d','--skip-simulation'],source,'SOURCE_TRANSLATION',checkout)]
        commands.append(_command([cli,ROOT/'scripts/forward_translate_source.rb',source/'source_model/run/in.osm',
                                   source/'source_model/run/in.idf'],source,'FORWARD_TRANSLATION',checkout))
        receipt=copy.deepcopy(base_receipt);receipt.update(plan=ref(source/'PLAN.json'),derived_XML=ref(xml),
            source_model=ref(source/'source_model/run/in.idf'),commands=commands,
            original_geometry_plan=ref(base_source/'PLAN.json'),catalog_metadata_rebound_without_physical_argument_changes=original_plan!=current_plan,
            occupancy_design={'occupants':occupants,'policy':ref(ROOT/POLICY),'change':change,
                              'source_complete_geometry':parent_entry['fixture']})
        save(source/'SOURCE_RECEIPT.json',receipt)
        from scripts.run_condition_housing import execute
        execute(source/'REQUEST.json',source,folder/'source_installed')
        # A content-derived fixed ID distinguishes designs while the original
        # installer remains untouched. Compile the exact whole model again.
        from .reference_workflow import prepare as prepare_workflow,compile_case,run
        from .reference_ports import rebind
        installed=read(folder/'source_installed/FIXTURE.json');identifier='condition_occupancy_'+digest(physical)[:24]
        out=folder/'prepared';out.mkdir()
        workflow={'schema':'national_idf.reference_workflow.v1','id':identifier,'country':parent_entry['physical_definition']['country'],
            'representation_kind':'controlled_reference','parent_fixture':ref(folder/'source_installed/FIXTURE.json'),
            'envelope_pack':None,'site_pack':None,'support_scope':policy['mode'],
            'remaining_evidence_gaps':['Own request numerical andcurve checks still required;not nationalstock or capacityselection']}
        save(out/'WORKFLOW.json',workflow);prepare_workflow(ref(out/'WORKFLOW.json'),out/'source_compiler')
        fixture=read(out/'source_compiler/FIXTURE.json');before=parse(source_file(installed['model'],ROOT).read_text())
        after=parse(source_file(fixture['model'],ROOT).read_text())
        save(out/'LIFE_INSTALLATION.json',rebind(installed,before,after,ref(out/'WORKFLOW.json')))
        fixture['life_installation_receipt']=ref(out/'LIFE_INSTALLATION.json')
        save(out/'FIXTURE.json',fixture);save(out/'source_compiler/FIXTURE.json',fixture)
        wf=read(out/'source_compiler/PREPARATION.json');wf['runtime_fixture']=ref(out/'source_compiler/FIXTURE.json');save(out/'source_compiler/PREPARATION.json',wf)
        case=read(folder/'source_installed/CASE.json');case['case_id']=identifier;case['environment']['physics_configuration_id']=identifier
        save(out/'CASE.json',case);compile_case(ref(out/'source_compiler/PREPARATION.json'),case,out/'compiled');run(out/'compiled',out/'run')
        from scripts.validate_multicountry_life import validate
        checks=validate(out/'run',fixture,case);require(checks['passed_input_and_component_checks'],'OCCUPANCY_DESIGN_NATIVE_LEDGER')
        from .condition_geometry import check
        save(out/'GEOMETRY_CHECKS.json',check(fixture,receipt['source_model'],receipt['derived_XML'],ref(out/'run/output/eplusout.eio')))
        save(out/'OCCUPANCY_DESIGN.json',{'occupants':occupants,'parent_preparation':preparation,
            'source_xml':base_receipt['derived_XML'],'derived_xml':ref(xml),'source_installed_fixture':ref(folder/'source_installed/FIXTURE.json'),
            'public_policy':ref(ROOT/POLICY),'source_change':change,'raw_source_receipt':ref(source/'SOURCE_RECEIPT.json'),
            'public_translator_defaults_recomputed':True,'source_national_demographics_or_ownership_claimed':False,
            'actual_survey_people_count_inferred':False,'original_tank_or_household_AB_modified':False})
        save(out/'EXECUTION.json',{'native_component_life_checks_pass':True,'source_geometry_and_context_preserved':True,
            'source_preparation':preparation,'numerical_or_joint_admission_granted':False})
        verify(out/'compiled')
        paths=[source/'PLAN.json',source/'SOURCE_RECEIPT.json',xml,source/'source_model/run/in.idf',
            *[out/p for p in ('FIXTURE.json','CASE.json','WORKFLOW.json','GEOMETRY_CHECKS.json','OCCUPANCY_DESIGN.json',
                             'EXECUTION.json','compiled/MANIFEST.json','run/COMPONENT_CHECKS.json','run/LIFE_CHECKS.json')]]
        entry={'schema':'national_idf.condition_preparation_cache.v1','physical_key':key,'physical_definition':physical,
            'catalog_snapshot':parent_entry['catalog_snapshot'],'fixture':ref(out/'FIXTURE.json'),'engineering_case':ref(out/'CASE.json'),
            'source_directory':str(source.relative_to(ROOT)),'prepared_directory':str(out.relative_to(ROOT)),
            'artifacts':[ref(p) for p in paths],'implementation':implementation(),
            'physical_or_reference_admission_granted':False,'state':'source_occupancy_design_pending_own_CASE_quality'}
        validate_entry(entry);review(entry,fixture);save(index,entry)
    return {'schema':'national_idf.condition_preparation_resolution.v1','status':'prepared_reference_pending_domain_review',
        'physical_key':key,'physics_configuration_id':fixture['id'],'cache_entry':ref(index),'fixture':entry['fixture'],
        'cache_hit':hit,'physical_model_rebuilt':not hit,'seconds':time.monotonic()-start,
        'survey_housing':copy.deepcopy(preparation['survey_housing']),'survey_housing_modified':False,
        'reference_housing':copy.deepcopy(preparation['reference_housing']),'design_occupants':occupants,
        'physical_or_reference_admission_granted':False}
