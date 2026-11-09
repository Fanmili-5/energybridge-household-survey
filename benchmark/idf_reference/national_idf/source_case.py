"""Compile a typed request onto an exact reviewed source assembly.

The EB runtime consumes CASE.json separately from fixed physics. This module
does not supply missing task models, start an engine, or grant runtime release.
"""
import copy
import datetime as dt
from pathlib import Path
import shutil
import tempfile

from .common import ROOT, read, require, save, seal, sha
from .idf import Fields, one, parse, render
from .release import reviewed_assembly
from .request_support import assess_inputs, bind_domain, syntax_failures
from .source_adapter import source_file


def artifact(path, root):
    return {'path': str(path.relative_to(root)), 'sha256': sha(path)}


def official_engine(record, expected_schema, root=ROOT):
    """Resolve the pinned distribution, never the global research engine."""
    bundle = read(source_file(record['engine']['release_manifest'], root))
    files = bundle['files']
    require(record['engine'].get('schema') == expected_schema, 'CASE_ENGINE_SCHEMA_NOT_EXPLICITLY_BOUND')
    executable = record['engine'].get('executable')
    require(isinstance(executable, dict) and Path(executable.get('path', '')).name in ('energyplus', 'energyplus.exe'),
            'CASE_OFFICIAL_ENGINE_EXECUTABLE_NOT_EXPLICITLY_BOUND')
    result = {'schema': expected_schema, 'executable': executable}
    for ref in result.values():
        require(files.get(ref['path']) == ref['sha256'], 'CASE_OFFICIAL_ENGINE_FILE_NOT_IN_RELEASE', ref['path'])
        source_file(ref, root)
    return {'distribution': record['engine']['distribution'], 'version': record['engine']['version'],
        'release_manifest': record['engine']['release_manifest'], **result}


def compile_source_case(case, out, *, root=ROOT, today=None):
    """Compile only after physical/assembly/input review, without runtime grant.

    All failures precede output creation. Run dates are the only edited source
    fields; numerics, weather, housing, equipment and dependencies stay fixed.
    """
    root = Path(root).resolve()
    syntax = syntax_failures(case, root)
    require(not syntax, 'FORMAL_INPUT_SCHEMA', syntax)
    identifier = case['environment']['physics_configuration_id']
    record, plan, release = reviewed_assembly(identifier, root, today)
    domain = bind_domain(record, root)
    support = assess_inputs(case, domain, root)
    require(support['inputs_supported'], 'SOURCE_CASE_INPUT_OUTSIDE_SUPPORT', support['failures'])
    from .program_resources import bind_program_domain, write_resources
    require(plan['program_resources'] is not None or not any(p.get('resource_pack') for p in domain['programs'].values()),
            'SOURCE_CASE_PROGRAM_RESOURCES_NOT_ASSEMBLED')
    if plan['program_resources'] is not None:
        bind_program_domain(plan['program_resources'], domain)
    from .assembly import blueprint
    spec, _ = blueprint(record['source_assembly']['id'], root)
    engine = official_engine(record, spec['engine_schema'], root)
    fields = Fields(source_file(engine['schema'], root))
    original = copy.deepcopy(plan['new_model_rows'])
    rows = copy.deepcopy(original)
    period = one(rows, 'RunPeriod')
    before = copy.deepcopy(period)
    begin = dt.date.fromisoformat(case['run']['start_date'])
    end = dt.date.fromisoformat(case['run']['end_date'])
    for key, value in {'begin_year': begin.year, 'begin_month': begin.month, 'begin_day_of_month': begin.day,
            'end_year': end.year, 'end_month': end.month, 'end_day_of_month': end.day,
            'day_of_week_for_start_day': begin.strftime('%A')}.items():
        fields.set(period, key, str(value))
    require([r for r in rows if r[0].casefold() != 'runperiod']
            == [r for r in original if r[0].casefold() != 'runperiod'], 'SOURCE_CASE_CHANGED_FIXED_PHYSICS')
    # Source paths point only to the known file dependencies; unlike the old
    # v1 compiler, no geometry, equipment or weather is generated from life.
    weather = source_file(record['weather']['epw'], root)
    parameter_inventory = source_file(record['parameter_inventory'], root)
    modification_inventory = source_file(record['modification_inventory'], root)
    out = Path(out).absolute()
    require(not out.exists() and not out.is_symlink(), 'OUTPUT_EXISTS', str(out))
    metadata = {'schema': 'national_idf.compiled_source_case.v2', 'case_id': case['case_id'],
        'physics_configuration_id': identifier, 'execution_mode': 'formal_source_compilation_only',
        'source_compilation_reviewed': True, 'formal_admitted': False, 'engine_started': False,
        'source_runtime_release_required': True, 'household_or_AB_generated': False,
        'physical_definition_sha256': release['physical_definition_sha256']}
    out.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='.source-case-', dir=out.parent) as temporary:
        stage = Path(temporary) / 'compiled'
        stage.mkdir()
        (stage / 'in.idf').write_text(render(rows))
        shutil.copyfile(weather, stage / 'weather.epw')
        shutil.copyfile(parameter_inventory, stage / 'PARAMETERS.json')
        shutil.copyfile(modification_inventory, stage / 'PHYSICAL_MODIFICATIONS.json')
        for dependency in plan['dependencies']:
            target = stage / dependency['output_path']
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source_file(dependency['source'], root), target)
        save(stage / 'CASE.json', case)
        save(stage / 'INPUT_SUPPORT.json', support)
        save(stage / 'INITIALIZATION_POLICY.json', domain['initialization'])
        save(stage / 'INITIALIZATION_SUPPORT.json', support['initialization_support'])
        save(stage / 'RUNTIME_SUPPORT_DOMAIN.json', domain)
        save(stage / 'OFFICIAL_ENGINE.json', engine)
        save(stage / 'EB_MAPPING.json', plan['eb_mapping'])
        save(stage / 'METERING.json', plan['metering'])
        for key, filename in [('whole_plug_load_replacement', 'LOAD_REPLACEMENT.json'), ('weather_mains', 'WEATHER_MAINS.json'), ('supply_network', 'SUPPLY_NETWORK.json'), ('joint_installation', 'JOINT_INSTALLATION.json')]:
            if plan.get(key) is not None:
                save(stage / filename, plan[key])
        if plan['installation'] is not None:
            save(stage / 'INSTALLATION.json', plan['installation'])
        write_resources(stage, plan['program_resources'], root=root)
        save(stage / 'SOURCE_COMPILER_RELEASE.json', release)
        save(stage / 'CASE_MODIFICATIONS.json', {'fixed_assembly_model': domain['assembled_model'],
            'source_model': domain['source_model'],
            'changes': [] if before == period else [{'before': before, 'after': period,
                'reason': 'Exact explicitly reviewed run window; fixed numerical protocol and initialization policy are unchanged'}],
            'physical_values_invented': False, 'controls_embedded_as_new_physics': False})
        save(stage / 'PROVENANCE.json', {'configuration_id': identifier,
            'source_blueprint': record['source_assembly']['blueprint'], 'weather': record['weather'],
            'source_domain': record['runtime_support_domain'], 'official_engine': engine,
            'physical_definition_sha256': release['physical_definition_sha256'],
            'source_compiler_release': release['artifact'], 'compiler_files': release['compiler_files'],
            'scope': 'Typed-case compilation onto a reviewed fixed assembly. A validated source EB runtime is still required.'})
        receipt = seal(stage, metadata)
        require(not out.exists() and not out.is_symlink(), 'OUTPUT_EXISTS', str(out))
        stage.rename(out)
    return receipt
