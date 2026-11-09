"""One condition-input entry with reusable physical preparations and EB CASEs.

This caches construction,not admission. Missing housing conditions remain
missing. A cache hit never approves a new control/service input or claims
local-stock equivalence. Existing compiler/runtime/quality standards apply.
"""
import argparse
import copy
from pathlib import Path
import shutil
import time

from .common import ROOT, digest, read, require, save, sha, verify
from .condition_housing import plan, build, CATALOG
from .reference_workflow import ref
from .source_adapter import source_file


def identity(design, catalog):
    d=design['definition']
    return {'builder_arguments':d['builder_arguments'],'country':d['country'],
            'site':d['site'],'reference_conditions':d['reference_conditions'],
            'physical_sources':physical_sources(design,catalog)}


def physical_sources(design,catalog):
    regional=design['definition'].get('regional_enclosure_package')
    return {**catalog['sources'],**({'regional_enclosure_package':regional['package']} if regional else {})}


def cache_key(design,catalog):return 'housing_'+digest(identity(design,catalog))[:28]


def implementation():
    from .release import compiler_identity
    return {**compiler_identity(),**{p:sha(ROOT/p) for p in ('national_idf/condition_housing.py',
        'national_idf/condition_geometry.py','scripts/run_condition_housing.py',
        'national_idf/housing_pipeline.py','national_idf/reference_workflow.py','national_idf/reference_life.py',
        'national_idf/native_build_runtime.py','configs/native_build_platforms_v3.json','national_idf/regional_profile.py',
        'national_idf/reference_enclosure.py','national_idf/envelope_adaptation.py',
        'configs/hpxml_subsurface_proxy_v1.json',
        'scripts/run_six_joint.py','scripts/run_whitegoods_shift.py')}}


def validate_entry(item):
    require(item['schema']=='national_idf.condition_preparation_cache.v1' and item['implementation']==implementation(),
            'HOUSING_CACHE_IMPLEMENTATION_CHANGED')
    for source in item['physical_definition']['physical_sources'].values():source_file(source,ROOT)
    source_file(item['catalog_snapshot'],ROOT)
    for source in item['artifacts']:source_file(source,ROOT)
    fixture=read(source_file(item['fixture'],ROOT))
    for source in [fixture['model'],fixture['input_domain'],fixture['resource_pack'],fixture['life_installation_receipt'],fixture['weather'],
                   *fixture['official_engine_files'],*fixture['EB_modules'].values(),*[v['source'] for v in fixture['dependencies']]]:
        source_file(source,ROOT)
    require(item['physical_key']=='housing_'+digest(item['physical_definition'])[:28],'HOUSING_CACHE_KEY_CHANGED')
    return fixture


def register(request,source,prepared,cache):
    source=Path(source).resolve();prepared=Path(prepared).resolve();cache=Path(cache).resolve();cache.mkdir(parents=True,exist_ok=True)
    design=plan(request);catalog=read(ROOT/CATALOG);key=cache_key(design,catalog)
    require(read(source/'PLAN.json')['definition']==design['definition'],'HOUSING_CACHE_SOURCE_CONDITIONS')
    result=read(prepared/'EXECUTION.json')
    require(result['native_component_life_checks_pass'] and result['source_geometry_and_context_preserved'],
            'HOUSING_CACHE_NATIVE_PREPARATION_INCOMPLETE')
    verify(prepared/'compiled')
    archive=cache/'catalog_versions'/ (sha(ROOT/CATALOG)+'.json');archive.parent.mkdir(exist_ok=True)
    if not archive.exists():shutil.copyfile(ROOT/CATALOG,archive)
    paths=[source/'PLAN.json',source/'SOURCE_RECEIPT.json',source/'housing_with_devices.xml',
           prepared/'FIXTURE.json',prepared/'CASE.json',prepared/'GEOMETRY_CHECKS.json',prepared/'EXECUTION.json',
           prepared/'compiled/MANIFEST.json',prepared/'run/COMPONENT_CHECKS.json',prepared/'run/LIFE_CHECKS.json']
    item={'schema':'national_idf.condition_preparation_cache.v1','physical_key':key,
          'physical_definition':identity(design,catalog),'catalog_snapshot':ref(archive),
          'fixture':ref(prepared/'FIXTURE.json'),'engineering_case':ref(prepared/'CASE.json'),
          'prepared_directory':str(prepared.relative_to(ROOT)), 'source_directory':str(source.relative_to(ROOT)),
          'artifacts':[ref(p) for p in paths],'implementation':implementation(),
          'physical_or_reference_admission_granted':False,'state':'generated_source_and_native_checks_pending_full_domain_review'}
    validate_entry(item);save(cache/(key+'.json'),item);return item


def prepare(request,cache):
    start=time.monotonic();design=plan(request)
    if design['status']!='constructible_reference':return design
    catalog=read(ROOT/CATALOG);cache=Path(cache).resolve()
    require(cache.is_relative_to(ROOT),'HOUSING_CACHE_OUTSIDE_PROJECT')
    key=cache_key(design,catalog);index=cache/(key+'.json');hit=index.exists()
    if hit:
        item=read(index);fixture=validate_entry(item)
        require(item['physical_definition']==identity(design,catalog),'HOUSING_CACHE_DEFINITION_CONFLICT')
    else:
        folder=cache/key;physical_request=copy.deepcopy(request)
        physical_request['request_id']=key;physical_request['survey_housing']={}
        build(physical_request,folder/'source')
        save(folder/'PHYSICAL_REQUEST.json',physical_request)
        from scripts.run_condition_housing import execute
        execute(folder/'PHYSICAL_REQUEST.json',folder/'source',folder/'prepared')
        item=register(physical_request,folder/'source',folder/'prepared',cache);fixture=validate_entry(item)
    return {'schema':'national_idf.condition_preparation_resolution.v1','status':'prepared_reference_pending_domain_review',
            'physical_key':key,'physics_configuration_id':fixture['id'],'cache_entry':ref(index),
            'fixture':item['fixture'],'cache_hit':hit,'physical_model_rebuilt':not hit,'seconds':time.monotonic()-start,
            'survey_housing':copy.deepcopy(request.get('survey_housing',{})),'survey_housing_modified':False,
            'reference_housing':copy.deepcopy(request['reference_housing']),
            'physical_or_reference_admission_granted':False}


def run(preparation,case,out,libraries_ref):
    entry=read(source_file(preparation['cache_entry'],ROOT));fixture=validate_entry(entry)
    require(preparation['fixture']==entry['fixture'] and preparation['physics_configuration_id']==fixture['id'],
            'HOUSING_RUN_PREPARATION_CHANGED')
    case=copy.deepcopy(case);identifier=case.get('environment',{}).get('physics_configuration_id')
    require(identifier is None or identifier==fixture['id'],'HOUSING_RUN_CONFLICTING_CONFIGURATION')
    case['environment']['physics_configuration_id']=fixture['id']
    out=Path(out).resolve();require(out.is_relative_to(ROOT) and not out.exists(),'HOUSING_RUN_OUTPUT_EXISTS');out.mkdir(parents=True)
    save(out/'FIXTURE.json',fixture);save(out/'CASE.json',case)
    start=time.monotonic()
    from .joint_case_runtime import compile_joint_case,run_joint_case
    from scripts.validate_multicountry_life import validate
    compile_joint_case(entry['fixture'],case,out/'compiled',mode='engineering_reference')
    run_joint_case(out/'compiled',out/'run',mode='engineering_reference')
    checks=validate(out/'run',fixture,case);native_seconds=time.monotonic()-start
    prepared=ROOT/entry['prepared_directory'];quality_path=prepared/'numerics/QUALITY.json'
    from .reference_release import request_digest
    previous=read(source_file(entry['engineering_case'],ROOT))
    reuse=request_digest(case)==request_digest(previous) and quality_path.exists()
    if reuse:
        quality=read(quality_path)
        from scripts.check_condition_housing import quality_identity
        require(quality['parent_fixture']==entry['fixture'] and quality['request_sha256']==request_digest(case)
                and quality['implementation']==quality_identity(),'HOUSING_PREVIOUS_QUALITY_CONTEXT_CHANGED')
        require(quality['quality_passed'] and quality.get('curve_domain_passed'),'HOUSING_PREVIOUS_QUALITY_FAILED')
        quality_ref=ref(quality_path)
    else:
        from scripts.check_condition_housing import execute
        execute(out,libraries_ref);quality_ref=ref(out/'numerics/QUALITY.json');quality=read(source_file(quality_ref,ROOT))
    result={'schema':'national_idf.condition_housing_pipeline_execution.v1',
            'preparation':preparation,'physical_model_rebuilt':False,'fixture':entry['fixture'],
            'native_component_life_checks_pass':checks['passed_input_and_component_checks'],
            'identical_full_input_quality_reused':reuse,'quality':quality_ref,
            'quality_passed':quality['quality_passed'] and quality.get('curve_domain_passed',False),
            'native_compile_and_run_seconds':native_seconds,'physical_or_reference_admission_granted':False,
            'household_generator_or_AB_changed':False}
    save(out/'EXECUTION.json',result);return result


def main():
    p=argparse.ArgumentParser();sub=p.add_subparsers(dest='action',required=True)
    q=sub.add_parser('prepare');q.add_argument('--request',type=Path,required=True);q.add_argument('--cache',type=Path,required=True);q.add_argument('--out',type=Path,required=True)
    q=sub.add_parser('register');q.add_argument('--request',type=Path,required=True);q.add_argument('--source',type=Path,required=True);q.add_argument('--prepared',type=Path,required=True);q.add_argument('--cache',type=Path,required=True)
    q=sub.add_parser('run');q.add_argument('--preparation',type=Path,required=True);q.add_argument('--case',type=Path,required=True);q.add_argument('--out',type=Path,required=True);q.add_argument('--libraries',type=Path,required=True)
    a=p.parse_args()
    if a.action=='prepare':save(a.out,prepare(read(a.request),a.cache))
    elif a.action=='register':register(read(a.request),a.source,a.prepared,a.cache)
    else:run(read(a.preparation),read(a.case),a.out,ref(a.libraries))


if __name__=='__main__':main()
