"""Verify a physical review plus an exact, version-bound compiler release.

This module grants compilation only. It never registers a configuration or
starts EnergyPlus, and it does not supply a formal EB runtime implementation.
"""
from datetime import date
from pathlib import Path

from .common import ROOT, digest, read, require, sha, verify
from .governance import REQUIRED_REVIEWS, configuration_failures, physical_digest
from .idf import render
from .source_adapter import normalized_version, source_file

COMPILER_FILES=('national_idf/assembly.py','national_idf/release.py','national_idf/source_adapter.py',
                'national_idf/idf.py','national_idf/common.py','national_idf/governance.py',
                'national_idf/request_support.py','national_idf/source_case.py',
                'national_idf/initialization.py','national_idf/source_numerics.py','national_idf/weather_scope.py',
                'configs/CASE.v2.schema.json','national_idf/program_resources.py','national_idf/installation.py',
                'national_idf/weather_mains.py','national_idf/load_replacement.py','national_idf/supply_network.py',
                'national_idf/joint_installation.py','national_idf/joint_case_runtime.py','national_idf/hvac_network.py',
                'national_idf/runtime_release.py','national_idf/formal_case.py','national_idf/life_binding.py',
                'national_idf/life_installation.py','national_idf/water_scope.py')


def compiler_identity():
    project=Path(__file__).resolve().parents[1]
    return {name:sha(project/name) for name in COMPILER_FILES}


def not_expired(value,today,code,context):
    try:valid=date.fromisoformat(value)
    except (ValueError,TypeError):require(False,code,context)
    require(valid>=today,code,context)


def reviewed_assembly(identifier,root=ROOT,today=None):
    """Rebuild the exact assembly plan covered by a compiler-release receipt."""
    from .assembly import blueprint, plan_assembly
    today=today or date.today()
    records=read(root/'configs/physics_configurations.json')['records']
    matches=[r for r in records if r['id']==identifier]
    require(len(matches)==1,'PHYSICS_CONFIGURATION_NOT_REGISTERED',identifier)
    record=matches[0]
    failures=configuration_failures(record,root)
    require(not failures,'FORMAL_ADMISSION_BLOCKED',failures)
    for phase in REQUIRED_REVIEWS:
        review=read(source_file(record['reviews'][phase]['artifact'],root))
        not_expired(review.get('valid_until'),today,'FORMAL_REVIEW_EXPIRED_OR_UNDATED',phase)
    binding=record.get('source_assembly') or {}
    require(isinstance(binding,dict) and set(binding)=={'id','blueprint'} and bool(binding['id']),
            'FORMAL_SOURCE_ASSEMBLY_MISSING')
    spec,ref=blueprint(binding.get('id'),root)
    require(binding.get('blueprint')==ref,'FORMAL_BLUEPRINT_NOT_BOUND')
    plan=plan_assembly(binding['id'],root)
    require(plan['engineering_compilation_ready'] and not plan['formal_release_gaps'],
            'FORMAL_ASSEMBLY_HAS_GAPS',plan['assembly_gaps']+plan['formal_release_gaps'])
    bind_mains_weather(record, plan, root)
    require(plan['source']['package_id']==record['housing']['package_id'],'FORMAL_HOUSING_PACKAGE_MISMATCH')
    # An OpenStudio/transitioned source may explicitly bind its derived native
    # assembly model in the same physical definition and conversion review.
    model=record['housing'].get('assembly_model',record['housing']['model'])
    source_file(model,root)
    require(plan['source']['model']==model,'FORMAL_ASSEMBLY_MODEL_NOT_BOUND')
    require(normalized_version(plan['source']['engine_version'])==normalized_version(record['engine']['version']),
            'FORMAL_ASSEMBLY_ENGINE_MISMATCH')
    engine_manifest=read(source_file(record['engine']['release_manifest'],root))
    schema=spec['engine_schema']
    require(engine_manifest['files'].get(schema['path'])==schema['sha256'],'FORMAL_ENGINE_SCHEMA_NOT_BOUND')
    for device,component in spec['components'].items():
        expected=record['equipment'][device]
        require(component['status']=='reviewed' and component.get('model_key')==expected['model_key']
                and component.get('version')==expected['version'],'FORMAL_COMPONENT_NOT_BOUND',device)
    weather_refs=spec['site_weather'].get('artifacts',[])
    require(all(record['weather'][k] in weather_refs for k in ('epw','design_days')),'FORMAL_WEATHER_NOT_BOUND')
    release_ref=(record['reviews'].get('source_compiler_release') or {}).get('artifact')
    require(release_ref is not None,'FORMAL_COMPILER_RELEASE_MISSING')
    release=read(source_file(release_ref,root))
    require(isinstance(release,dict) and set(release)=={'schema','status','configuration_id',
            'physical_definition_sha256','valid_until','blueprint','assembly_fingerprints',
            'compiler_files','validated_assembly_manifest'},'FORMAL_COMPILER_RELEASE_FIELDS')
    require(release.get('schema')=='national_idf.source_compiler_release.v1'
            and release.get('status')=='passed' and release.get('configuration_id')==identifier
            and release.get('physical_definition_sha256')==physical_digest(record),
            'FORMAL_COMPILER_RELEASE_STALE')
    not_expired(release.get('valid_until'),today,'FORMAL_COMPILER_RELEASE_EXPIRED_OR_UNDATED',identifier)
    require(release.get('blueprint')==ref and release.get('assembly_fingerprints')==plan['fingerprints'],
            'FORMAL_COMPILER_DEPENDENCIES_CHANGED')
    require(release.get('compiler_files')==compiler_identity(),'FORMAL_COMPILER_IMPLEMENTATION_CHANGED')
    manifest_path=source_file(release['validated_assembly_manifest'],root)
    require(manifest_path.name=='MANIFEST.json','VALIDATED_ASSEMBLY_MANIFEST_NAME')
    folder=manifest_path.parent;manifest=verify(folder)
    require(manifest.get('schema')=='national_idf.assembled_reference.v1'
            and manifest.get('id')==binding['id'],'VALIDATED_ASSEMBLY_ID_MISMATCH')
    expected={'MODIFICATIONS.json':plan['modifications'],'EB_MAPPING.json':plan['eb_mapping'],
              'METERING.json':plan['metering']}
    for name,value in expected.items():
        require(read(folder/name)==value,'VALIDATED_ASSEMBLY_OBJECTS_CHANGED',name)
    model_hash=digest(render(plan['new_model_rows']))
    require(digest((folder/'in.idf').read_text())==model_hash,'VALIDATED_ASSEMBLY_MODEL_CHANGED')
    for dep in plan['dependencies']:
        require(sha(folder/dep['output_path'])==dep['source']['sha256'],'VALIDATED_ASSEMBLY_DEPENDENCY_CHANGED')
    if plan['installation'] is not None:
        require(read(folder/'INSTALLATION.json')==plan['installation'],'VALIDATED_INSTALLATION_CHANGED')
    for key, filename in [('whole_plug_load_replacement','LOAD_REPLACEMENT.json'),('weather_mains','WEATHER_MAINS.json'),('supply_network','SUPPLY_NETWORK.json'),('joint_installation','JOINT_INSTALLATION.json')]:
        if plan.get(key) is not None:
            require(read(folder/filename)==plan[key],'VALIDATED_BOUNDARY_OR_REPLACEMENT_CHANGED',key)
    resources=plan.get('program_resources')
    if resources:
        for name,key in [('PACK.json','pack'),('PROFILE.json','profile')]:
            require(sha(folder/'program_resources'/name)==resources[key]['sha256'],
                    'VALIDATED_PROGRAM_RESOURCE_CHANGED',name)
    return record,plan,{'artifact':release_ref,'physical_definition_sha256':physical_digest(record),
        'validated_assembly_manifest':release['validated_assembly_manifest'],
        'compiler_files':compiler_identity(),'scope':'Exact source compilation only; formal EB runtime is a separate release'}


def bind_mains_weather(record, plan, root=ROOT):
    """A formal inlet model must derive from the same frozen annual weather.

    Explicit component laboratory counterfactuals use their separate reference
    entrance. They cannot implicitly become a joint physical configuration.
    """
    if plan.get('weather_mains'):
        boundary = read(source_file(plan['weather_mains']['boundary'], root))
        require(boundary['weather'] == record['weather']['epw'], 'FORMAL_MAINS_WEATHER_NOT_BOUND')
