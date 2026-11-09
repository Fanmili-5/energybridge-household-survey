"""Bind formal EB execution to reviewed physics and a validated backend version."""
import copy
from datetime import date
from pathlib import Path

from .common import ROOT, read, require, sha, verify
from .idf import parse
from .release import not_expired, reviewed_assembly
from .request_support import assess_inputs, bind_domain
from .source_adapter import source_file

VALIDATION_PARTS={'input_application','six_device_metering','dynamic_response','numerical_support'}


def runtime_identity():
    from .joint_case_runtime import IMPLEMENTATION
    names=set(IMPLEMENTATION)|{'national_idf/runtime_release.py','national_idf/formal_case.py',
        'national_idf/release.py','national_idf/governance.py','national_idf/source_case.py',
        'national_idf/initialization.py','national_idf/common.py','national_idf/idf.py',
        'national_idf/executed_results.py','national_idf/curve_domain.py','national_idf/weather_scope.py','configs/CASE.v2.schema.json'}
    project=Path(__file__).resolve().parents[1]
    return {name:sha(project/name) for name in sorted(names)}


def fixed_rows(rows):
    # Reporting diagnostics can also affect engine behavior. Freeze every
    # object except the separately checked run calendar.
    return [r for r in rows if r[0]!='RunPeriod']


def reviewed_runtime(identifier, *, root=ROOT, today=None):
    today=today or date.today()
    record,plan,compiler=reviewed_assembly(identifier,root,today)
    reference=(record['reviews'].get('source_runtime_release') or {}).get('artifact')
    require(reference is not None,'FORMAL_RUNTIME_RELEASE_MISSING')
    release=read(source_file(reference,root))
    required={'schema','status','configuration_id','physical_definition_sha256','valid_until',
        'source_compiler_release','source_fixture','backend_files','validation_artifacts'}
    require(set(release)==required and release['schema']=='national_idf.source_EB_runtime_release.v1'
        and release['status']=='passed','FORMAL_RUNTIME_RELEASE_FIELDS')
    require(release['configuration_id']==identifier
        and release['physical_definition_sha256']==compiler['physical_definition_sha256']
        and release['source_compiler_release']==compiler['artifact'],'FORMAL_RUNTIME_RELEASE_STALE')
    not_expired(release['valid_until'],today,'FORMAL_RUNTIME_RELEASE_EXPIRED_OR_UNDATED',identifier)
    require(release['backend_files']==runtime_identity(),'FORMAL_RUNTIME_IMPLEMENTATION_CHANGED')
    require(set(release['validation_artifacts'])==VALIDATION_PARTS,'FORMAL_RUNTIME_VALIDATION_INCOMPLETE')
    for phase,item in release['validation_artifacts'].items():
        result=read(source_file(item,root));checks=result.get('checks')
        require(result.get('status')=='passed' and result.get('phase')==phase
            and result.get('physical_definition_sha256')==compiler['physical_definition_sha256']
            and isinstance(checks,dict) and checks and all(v is True for v in checks.values())
            and result.get('scope') and result.get('evidence'),'FORMAL_RUNTIME_VALIDATION_FAILED',phase)
        for evidence in result['evidence']:source_file(evidence,root)
    fixture=read(source_file(release['source_fixture'],root))
    require(fixture.get('schema')=='national_idf.six_reference_fixture.v1'
        and fixture['id']==identifier and fixture['input_domain']==record['runtime_support_domain'],
        'FORMAL_RUNTIME_FIXTURE_NOT_BOUND')
    require(not fixture.get('registered_numerical_overlay'),'FORMAL_RUNTIME_REQUIRES_FROZEN_NUMERICS')
    template=parse(source_file(fixture['model'],root).read_text())
    require(fixed_rows(template)==fixed_rows(plan['new_model_rows']),'FORMAL_RUNTIME_TEMPLATE_PHYSICS_CHANGED')
    require(fixture['EB_mapping']==plan['eb_mapping'],'FORMAL_RUNTIME_MAPPING_CHANGED')
    require(plan['program_resources'] is not None and fixture['resource_pack']==plan['program_resources']['pack'],
        'FORMAL_RUNTIME_RESOURCE_PACK_CHANGED')
    require(fixture['dependencies']==plan['dependencies'],'FORMAL_RUNTIME_DEPENDENCIES_CHANGED')
    engine=read(source_file(record['engine']['release_manifest'],root))['files']
    for item in fixture['official_engine_files']:
        source_file(item,root)
        require(engine.get(item['path'])==item['sha256'],'FORMAL_RUNTIME_ENGINE_NOT_PINNED')
    require(fixture['engine_schema']==record['engine']['schema']
        and fixture['weather']==record['weather']['epw'],'FORMAL_RUNTIME_SITE_OR_SCHEMA_CHANGED')
    executable=[r for r in fixture['official_engine_files'] if Path(r['path']).name in ('energyplus','energyplus.exe')]
    require(executable==[record['engine']['executable']],'FORMAL_RUNTIME_EXECUTABLE_CHANGED')
    for item in fixture['EB_modules'].values():source_file(item,root)
    domain=bind_domain(record,root)
    return record,plan,fixture,domain,{'artifact':reference,'source_fixture':release['source_fixture'],
        'physical_definition_sha256':compiler['physical_definition_sha256'],'backend_files':release['backend_files']}


def validate_compiled(compiled, *, root=ROOT, today=None):
    manifest=verify(compiled)
    require(manifest['schema']=='national_idf.compiled_reviewed_six_CASE.v1'
        and manifest.get('execution_mode')=='formal','FORMAL_RUNTIME_COMPILED_SCHEMA')
    case=read(compiled/'CASE.json');identifier=case['environment']['physics_configuration_id']
    record,plan,template,domain,release=reviewed_runtime(identifier,root=root,today=today)
    require(read(compiled/'SOURCE_RUNTIME_RELEASE.json')==release,'FORMAL_RUNTIME_COMPILED_RELEASE_CHANGED')
    require(manifest['physics_configuration_id']==identifier
        and manifest['physical_definition_sha256']==release['physical_definition_sha256'],'FORMAL_RUNTIME_CONFIGURATION_CHANGED')
    support=assess_inputs(case,domain,root)
    require(support['inputs_supported'],'FORMAL_RUNTIME_INPUT_OUTSIDE_SUPPORT',support['failures'])
    fixture=read(compiled/'FIXTURE.json');expected=copy.deepcopy(template)
    expected['model']={'path':str((compiled/'in.idf').resolve().relative_to(root.resolve())),
        'sha256':sha(compiled/'in.idf')}
    require(fixture==expected,'FORMAL_RUNTIME_COMPILED_FIXTURE_CHANGED')
    require(fixed_rows(parse((compiled/'in.idf').read_text()))==fixed_rows(plan['new_model_rows']),
        'FORMAL_RUNTIME_COMPILED_PHYSICS_CHANGED')
    from .idf import Fields,objects
    import datetime as dt
    fields=Fields(source_file(fixture['engine_schema'],root))
    periods=objects(parse((compiled/'in.idf').read_text()),'RunPeriod')
    require(len(periods)==1,'FORMAL_RUNTIME_CALENDAR_COUNT')
    period=periods[0]
    for label,prefix in (('start_date','begin'),('end_date','end')):
        value=dt.date(*[int(fields.get(period,prefix+suffix)) for suffix in ('_year','_month','_day_of_month')])
        require(value.isoformat()==case['run'][label],'FORMAL_RUNTIME_CALENDAR_CHANGED')
    require(fields.get(period,'day_of_week_for_start_day')==dt.date.fromisoformat(case['run']['start_date']).strftime('%A'),
        'FORMAL_RUNTIME_WEEKDAY_CHANGED')
    require(sha(compiled/'weather.epw')==record['weather']['epw']['sha256'],'FORMAL_RUNTIME_WEATHER_CHANGED')
    for dependency in plan['dependencies']:
        require(sha(compiled/dependency['output_path'])==dependency['source']['sha256'],
            'FORMAL_RUNTIME_DEPENDENCY_CHANGED')
    return release
