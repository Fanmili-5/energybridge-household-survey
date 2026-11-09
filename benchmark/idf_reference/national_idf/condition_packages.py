"""Compose cached housing,public envelope recipe and site through EB compilers."""
import argparse
import copy
from pathlib import Path
import time

from .common import ROOT,read,save,require,digest,verify
from .idf import parse,objects,Fields
from .housing_pipeline import validate_entry,implementation
from .reference_workflow import ref,prepare as prepare_workflow,compile_case,run
from .reference_ports import rebind
from .source_adapter import source_file
from .condition_envelope import instantiate,recipe,CATALOG


def prepare(preparation,recipe_id,site_id,cache):
    start=time.monotonic()
    from .condition_housing import CATALOG as housing_catalog
    sites=[v for v in read(ROOT/housing_catalog)['sites'] if v['id']==site_id]
    require(len(sites)==1,'CONDITION_PACKAGE_SITE_UNKNOWN')
    site=sites[0];rule=recipe(recipe_id);require(site['country']==rule['country'],'CONDITION_PACKAGE_COUNTRY_CONFLICT')
    parent_entry=read(source_file(preparation['cache_entry'],ROOT));parent=validate_entry(parent_entry)
    require(preparation['fixture']==parent_entry['fixture'] and preparation['physics_configuration_id']==parent['id'],
            'CONDITION_PACKAGE_PARENT_CONFLICT')
    physical={'base_housing_key':parent_entry['physical_key'],'base_model':parent['model'],
        'recipe':{k:v for k,v in rule.items() if k!='reference_insert'},'site':site,
        'physical_sources':{**parent_entry['physical_definition']['physical_sources'],
            'envelope_recipe':rule['source_pack'],'site_pack':site['site_pack'],
            'recipe_code':ref(ROOT/'national_idf/condition_envelope.py'),'composition_code':ref(ROOT/'national_idf/condition_packages.py')}}
    key='housing_'+digest(physical)[:28];cache=Path(cache).resolve()
    require(cache.is_relative_to(ROOT),'CONDITION_PACKAGE_CACHE_OUTSIDE_PROJECT');cache.mkdir(exist_ok=True,parents=True)
    index=cache/(key+'.json');hit=index.exists()
    if hit:entry=read(index);fixture=validate_entry(entry)
    else:
        folder=cache/key;require(not folder.exists(),'CONDITION_PACKAGE_FAILED_ATTEMPT_RETAINED');folder.mkdir()
        rows=parse(source_file(parent['model'],ROOT).read_text())
        _,modifications=instantiate(rows,parent['engine_schema'],recipe_id,folder/'envelope')
        identifier='condition_composed_'+digest(physical)[:24]
        workflow={'schema':'national_idf.reference_workflow.v1','id':identifier,'country':site['country'],
            'representation_kind':'controlled_reference','parent_fixture':parent_entry['fixture'],
            'envelope_pack':ref(folder/'envelope/PACK.json'),'site_pack':site['site_pack'],
            'support_scope':rule['scope'],'remaining_evidence_gaps':[
                'Own housing/site/request physical and numerical support not automatically admitted',
                'Local stock,survey equivalence,full code compliance and event-specific water room gains unsupported']}
        save(folder/'WORKFLOW.json',workflow);prepare_workflow(ref(folder/'WORKFLOW.json'),folder/'source_compiler')
        fixture=read(folder/'source_compiler/FIXTURE.json');after=parse(source_file(fixture['model'],ROOT).read_text())
        save(folder/'LIFE_INSTALLATION.json',rebind(parent,rows,after,ref(folder/'WORKFLOW.json')))
        fixture['life_installation_receipt']=ref(folder/'LIFE_INSTALLATION.json')
        # Generic people/water/control wrappers deepcopy the fixture. Keep the
        # enclosure authority with it so later geometry checks replay the same
        # declared window transaction rather than masking arbitrary changes.
        fixture['declared_envelope_geometry_transaction']={'source_model':parent['model'],'pack':ref(folder/'envelope/PACK.json')}
        save(folder/'source_compiler/FIXTURE.json',fixture);save(folder/'FIXTURE.json',fixture)
        receipt=read(folder/'source_compiler/PREPARATION.json');receipt['runtime_fixture']=ref(folder/'source_compiler/FIXTURE.json')
        save(folder/'source_compiler/PREPARATION.json',receipt)
        case=read(source_file(parent_entry['engineering_case'],ROOT));case['case_id']=identifier
        case['environment']['physics_configuration_id']=identifier;save(folder/'CASE.json',case)
        compile_case(ref(folder/'source_compiler/PREPARATION.json'),case,folder/'compiled');run(folder/'compiled',folder/'run')
        from scripts.validate_multicountry_life import validate
        checks=validate(folder/'run',fixture,case);require(checks['passed_input_and_component_checks'],'CONDITION_PACKAGE_NATIVE_LEDGER_FAILED')
        from .condition_geometry import check
        geometry=read(ROOT/parent_entry['prepared_directory']/'GEOMETRY_CHECKS.json')
        geometry=check(fixture,geometry['source_idf'],geometry['source_xml'],ref(folder/'run/output/eplusout.eio'),
                       envelope_transaction={'source_model':parent['model'],'pack':ref(folder/'envelope/PACK.json')})
        save(folder/'GEOMETRY_CHECKS.json',geometry)
        from .condition_defaults import inspect
        from .parameter_pack import inventory
        text=source_file(fixture['model'],ROOT).read_text();fields=Fields(source_file(fixture['engine_schema'],ROOT))
        defaults=inspect(after,inventory(after,text,read(source_file(fixture['engine_schema'],ROOT))),fields,rows,fixture['engine_schema'])
        require(not defaults['unreviewed'],'CONDITION_PACKAGE_DEFAULT_NOT_REVIEWED',defaults['unreviewed']);save(folder/'DEFAULTS.json',defaults)
        tanks=objects(after,'WaterHeater:Stratified');component=read(ROOT/'configs/component_models/EB_original_water_heater_c58a2a7a.json')
        require(len(tanks)==1 and all(fields.get(tanks[0],k)==v for k,v in component['physical_parameters'].items()),'CONDITION_PACKAGE_EB_TANK_CHANGED')
        require(not objects(after,'ZoneHVAC:IdealLoadsAirSystem') and not objects(after,'Coil:Heating:Electric'),'CONDITION_PACKAGE_HIDDEN_HEATING')
        save(folder/'EXECUTION.json',{'native_component_life_checks_pass':True,'source_geometry_and_context_preserved':True,
            'source_preparation':preparation,'source_recipe':rule['source_pack'],'site_pack':site['site_pack'],
            'complete_original_EB_tank_retained':True,'numerical_or_joint_admission_granted':False})
        verify(folder/'compiled')
        paths=['FIXTURE.json','CASE.json','WORKFLOW.json','GEOMETRY_CHECKS.json','DEFAULTS.json','EXECUTION.json',
               'envelope/PACK.json','envelope/MODIFICATIONS.json','compiled/MANIFEST.json','run/COMPONENT_CHECKS.json','run/LIFE_CHECKS.json']
        entry={'schema':'national_idf.condition_preparation_cache.v1','physical_key':key,'physical_definition':physical,
            'catalog_snapshot':parent_entry['catalog_snapshot'],'fixture':ref(folder/'FIXTURE.json'),'engineering_case':ref(folder/'CASE.json'),
            'source_directory':parent_entry['source_directory'],'prepared_directory':str(folder.relative_to(ROOT)),
            'artifacts':[ref(folder/p) for p in paths],'implementation':implementation(),
            'physical_or_reference_admission_granted':False,'state':'composed_reference_pending_own_CASE_quality_and_output_review'}
        validate_entry(entry);save(index,entry)
    return {'schema':'national_idf.condition_preparation_resolution.v1','status':'prepared_reference_pending_domain_review',
        'physical_key':key,'physics_configuration_id':fixture['id'],'cache_entry':ref(index),'fixture':entry['fixture'],
        'cache_hit':hit,'physical_model_rebuilt':not hit,'seconds':time.monotonic()-start,
        'survey_housing':copy.deepcopy(preparation['survey_housing']),'survey_housing_modified':False,
        'reference_housing':copy.deepcopy(preparation['reference_housing']),'reference_country':site['country'],
        'envelope_recipe_id':recipe_id,'site_id':site_id,'physical_or_reference_admission_granted':False}


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--preparation',type=Path,required=True);p.add_argument('--recipe',required=True)
    p.add_argument('--site',required=True);p.add_argument('--cache',type=Path,required=True);p.add_argument('--out',type=Path,required=True)
    a=p.parse_args();save(a.out,prepare(read(a.preparation),a.recipe,a.site,a.cache))
