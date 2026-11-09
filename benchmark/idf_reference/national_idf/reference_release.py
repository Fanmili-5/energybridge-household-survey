"""Reviewed reference authority around the existing source compiler and EB runtime.

Reference experiments and strict survey-home admission remain separate. This
adds no appliance physics, defaults or relaxed numerical criteria. New CASE
inputs trigger the same existing numerical suite instead of inheriting the
quality of a different request.
"""
import copy
import shutil
from datetime import date
from pathlib import Path

from .assembly import plan_assembly
from .case_commands import CaseTimeline
from .common import ROOT, digest, read, require, save, seal, sha, verify
from .governance import REQUIRED_REVIEWS
from .idf import parse
from .release import compiler_identity, not_expired
from .runtime_release import runtime_identity
from .source_adapter import source_file


def implementation():
    result = {**compiler_identity(), **runtime_identity()}
    for path in ('national_idf/reference_release.py', 'national_idf/reference_cli.py',
        'national_idf/reference_controls.py', 'national_idf/reference_geometry.py',
        'national_idf/reference_defaults.py', 'scripts/run_multicountry_life_numerics.py',
        'scripts/analyze_multicountry_life_numerics.py', 'scripts/analyze_multicountry_numerics.py',
        'scripts/validate_multicountry_life.py', 'scripts/check_multicountry_life_curves.py',
        'scripts/review_multicountry_reference_releases.py', 'scripts/run_multicountry_design_load.py',
        'scripts/check_reference_design_steps.py', 'national_idf/reference_design.py'):
        result[path] = sha(ROOT / path)
    return result


def request_digest(case):
    return digest({k: v for k, v in case.items() if k != 'case_id'})


def reviewed(reference, *, root=ROOT, today=None):
    release = read(source_file(reference, root))
    require(release.get('schema') == 'national_idf.reviewed_reference_release.v1'
            and release.get('status') == 'passed' and release.get('purpose') == 'roleplay_control_reference',
            'REFERENCE_RELEASE_NOT_REVIEWED')
    not_expired(release['valid_until'], today or date.today(), 'REFERENCE_RELEASE_EXPIRED', release['id'])
    require(release['implementation'] == implementation(), 'REFERENCE_RELEASE_IMPLEMENTATION_CHANGED')
    require(release['protocol']['sha256'] == sha(root / 'configs/study_protocol.json'), 'REFERENCE_RELEASE_CRITERIA_CHANGED')
    source_file(release['protocol'], root)
    require(set(release['reviews']) == set(REQUIRED_REVIEWS), 'REFERENCE_RELEASE_REVIEW_INCOMPLETE')
    for phase, item in release['reviews'].items():
        review = read(source_file(item, root))
        require(review['phase'] == phase and review['definition_sha256'] == release['definition_sha256']
                and review['status'] == 'passed' and review['checks']
                and all(v is True for v in review['checks'].values()), 'REFERENCE_RELEASE_REVIEW_FAILED', phase)
        not_expired(review['valid_until'], today or date.today(), 'REFERENCE_REVIEW_EXPIRED', phase)
        for evidence in review['evidence']: source_file(evidence, root)
    definition = release['definition']
    require(digest(definition) == release['definition_sha256'], 'REFERENCE_RELEASE_DEFINITION_CHANGED')
    fixture = read(source_file(definition['fixture'], root))
    require(fixture['id'] == release['id'], 'REFERENCE_RELEASE_ID_CONFLICT')
    plan = plan_assembly(release['id'], root=root, blueprint_ref=definition['source_blueprint'])
    require(plan['engineering_compilation_ready'] and plan['new_model_rows'] ==
            parse(source_file(fixture['model'], root).read_text()), 'REFERENCE_RELEASE_SOURCE_RECIPE_CHANGED')
    gaps = set(plan['formal_release_gaps'])
    require(gaps == set(release['finding_dispositions']), 'REFERENCE_RELEASE_NEW_OR_MISSING_FINDING')
    for item in release['finding_dispositions'].values():
        require(item['disposition'] in ('resolved_by_bound_review', 'outside_declared_output_scope')
                and item['reason'] and item['phase'] in release['reviews'], 'REFERENCE_RELEASE_UNCLASSIFIED_FINDING')
    for item in fixture['official_engine_files']: source_file(item, root)
    for item in fixture['EB_modules'].values(): source_file(item, root)
    for dependency in fixture['dependencies']: source_file(dependency['source'], root)
    source_file(fixture['weather'], root); source_file(fixture['engine_schema'], root)
    for item in release['validated_cases']: source_file(item['case'], root)
    return release, fixture, plan


def assess(reference, case, *, root=ROOT, today=None):
    from .request_support import syntax_failures
    require(not syntax_failures(case, root), 'REFERENCE_INPUT_SCHEMA', syntax_failures(case, root))
    release, fixture, _ = reviewed(reference, root=root, today=today)
    domain = read(source_file(fixture['input_domain'], root))
    require(case['environment']['physics_configuration_id'] == release['id'], 'REFERENCE_REQUEST_CONFIGURATION_CONFLICT')
    require(case['run'] == domain['run_period'], 'REFERENCE_REQUEST_UNREVIEWED_WINDOW')
    timeline = CaseTimeline(case, domain, root=root)
    require(not timeline.support['failures'], 'REFERENCE_REQUEST_OUTSIDE_PHYSICAL_DOMAIN', timeline.support['failures'])
    covered = request_digest(case) in {request_digest(read(source_file(item['case'], root))) for item in release['validated_cases']}
    return {'schema': 'national_idf.reviewed_reference_input_screen.v1', 'physics_configuration_id': release['id'],
        'reference_configuration_reviewed': True, 'physical_input_supported': True,
        'case_numerics_previously_validated': covered, 'new_case_numerics_required': not covered,
        'strict_survey_home_admitted': False, 'formal_admitted': False, 'request_sha256': request_digest(case)}


def compile_case(reference, case, out, *, control_contract=None, root=ROOT, today=None):
    from .joint_case_runtime import compile_joint_case
    screen = assess(reference, case, root=root, today=today)
    release, fixture, _ = reviewed(reference, root=root, today=today)
    control = None
    if control_contract:
        from .reference_controls import validate
        control = validate(case, CaseTimeline(case, read(source_file(fixture['input_domain'], root)), root=root), control_contract, root=root)
    compiled = compile_joint_case(release['definition']['fixture'], case, out, mode='engineering_reference', root=root)
    out = Path(out).resolve()
    save(out / 'REFERENCE_AUTHORITY.json', {'release': reference, 'definition_sha256': release['definition_sha256'],
        'input_screen': screen, 'control_contract': control_contract, 'control_validation': control})
    return seal(out, {k: v for k, v in compiled.items() if k != 'files'})


def _new_case_numerics(release, fixture, case, folder, *, root=ROOT):
    from .reference_workflow import ref
    from scripts.run_multicountry_life_numerics import VARIANTS, execute
    from scripts.analyze_multicountry_life_numerics import PAIRS, compare_paths
    from scripts.validate_multicountry_life import validate
    base = folder / 'case_quality'; base.mkdir()
    backend = {path: release['implementation'][path] for path in runtime_identity()}
    backend['scripts/run_multicountry_life_numerics.py'] = release['implementation']['scripts/run_multicountry_life_numerics.py']
    alias = 'rq_' + digest({'release': release['definition_sha256'], 'case': case, 'backend': backend})[:24]
    candidate = copy.deepcopy(fixture); candidate['id'] = alias
    domain = read(source_file(fixture['input_domain'], root)); domain['physics_configuration_id'] = alias
    save(base / 'DOMAIN.json', domain); candidate['input_domain'] = ref(base / 'DOMAIN.json')
    save(base / 'FIXTURE.json', candidate)
    numerical_case = copy.deepcopy(case); numerical_case['environment']['physics_configuration_id'] = alias
    save(base / 'CASE.json', numerical_case)
    save(base / 'PREPARATION.json', {'schema': 'national_idf.reviewed_reference_request_numerics.v1',
        'release_definition': release['definition_sha256'], 'source_fixture': release['definition']['fixture'],
        'only_nonphysical_case_alias_changed': True})
    library = release['numerical_resource_library']
    for step, warmup, days in VARIANTS:
        for arm in ('baseline', 'intervention'):
            execute(library, step, warmup, days, arm, base_folder=base, output_label=alias)
    num = root / 'reports/multicountry_life_20261108/numerics_life'
    def path(args, arm):
        step, warmup, days = args
        return num / f'{alias}_s{step}_w{warmup}_d{days}_{arm}' / 'run'
    comparisons = {name: compare_paths([path(a, arm) for arm in ('baseline', 'intervention')],
                                      [path(b, arm) for arm in ('baseline', 'intervention')]) for name, a, b in PAIRS}
    native = {}
    for args in VARIANTS:
        for arm in ('baseline', 'intervention'):
            p = path(args, arm); verify(p.parent / 'compiled')
            require(all(sha(root / name) == signature for name, signature in read(p / 'IMPLEMENTATION.json').items()),
                    'REFERENCE_CACHED_NATIVE_BACKEND_CHANGED')
            native[str(p.relative_to(root))] = validate(p, read(p.parent / 'FIXTURE.json'), read(p.parent / 'CASE.json'))
    report = {'schema': 'national_idf.reviewed_reference_case_quality.v1', 'comparisons': comparisons,
        'native_checks': native, 'all_existing_checks_pass': all(v['passed'] for v in comparisons.values()),
        'new_request_checked': True, 'criteria_unchanged': True, 'physics_configuration_id': release['id']}
    save(base / 'QUALITY.json', report)
    return report


def _observe_case_curves(fixture, case, folder, *, root=ROOT):
    from .reference_workflow import ref
    from scripts.check_multicountry_life_curves import execute
    source = folder / 'curve_input'; source.mkdir()
    save(source / 'FIXTURE.json', fixture); save(source / 'CASE.json', case)
    (source / 'run').mkdir(); shutil.copyfile(folder / 'TRACE.csv', source / 'run/TRACE.csv')
    execute('US', base_folder=source, output_folder=folder / 'curve_observed')
    result = read(folder / 'curve_observed/CURVE_CHECKS.json')
    result.update(actual_case=ref(source / 'CASE.json'), actual_source_trace=ref(folder / 'TRACE.csv'))
    save(folder / 'curve_observed/CURVE_CHECKS.json', result)
    return result


def run_case(compiled, out, *, root=ROOT, today=None):
    from .joint_case_runtime import run_joint_case
    from scripts.validate_multicountry_life import validate
    compiled = Path(compiled).resolve(); verify(compiled)
    authority = read(compiled / 'REFERENCE_AUTHORITY.json'); case = read(compiled / 'CASE.json')
    screen = assess(authority['release'], case, root=root, today=today)
    require(screen == authority['input_screen'], 'REFERENCE_COMPILED_AUTHORITY_CHANGED')
    release, fixture, _ = reviewed(authority['release'], root=root, today=today)
    require(authority['definition_sha256'] == release['definition_sha256'], 'REFERENCE_COMPILED_DEFINITION_CHANGED')
    require(read(compiled / 'FIXTURE.json') == fixture, 'REFERENCE_COMPILED_BINDING_CHANGED')
    require(sha(compiled / 'weather.epw') == fixture['weather']['sha256'], 'REFERENCE_COMPILED_WEATHER_CHANGED')
    for dependency in fixture['dependencies']:
        require(sha(compiled / dependency['output_path']) == dependency['source']['sha256'], 'REFERENCE_COMPILED_DEPENDENCY_CHANGED')
    if authority['control_contract']:
        from .reference_controls import validate as validate_controls
        actual = validate_controls(case, CaseTimeline(case, read(source_file(fixture['input_domain'], root)), root=root),
                                   authority['control_contract'], root=root)
        require(actual == authority['control_validation'], 'REFERENCE_CONTROL_CONTRACT_CHANGED')
    # Verify the compiled fixed rows against the reviewed source,not just a
    # caller-supplied signature or the contents of the manifest it accompanies.
    require(parse((compiled / 'in.idf').read_text()) == parse(source_file(fixture['model'], root).read_text()),
            'REFERENCE_COMPILED_PHYSICS_CHANGED')
    result = run_joint_case(compiled, out, mode='engineering_reference', root=root)
    out = Path(out).resolve(); native = validate(out, fixture, case)
    quality = None if screen['case_numerics_previously_validated'] else _new_case_numerics(release, fixture, case, out, root=root)
    curve = None if screen['case_numerics_previously_validated'] else _observe_case_curves(fixture, case, out, root=root)
    report = {'schema': 'national_idf.reviewed_reference_execution.v1', 'release': authority['release'],
        'definition_sha256': release['definition_sha256'], 'input_screen': screen, 'native_checks': native,
        'case_quality_passed': quality['all_existing_checks_pass'] and curve['passed_observed_domain_screen'] if quality else True,
        'additional_case_quality': quality, 'additional_curve_quality': curve, 'reference_configuration_reviewed': True,
        'strict_survey_home_admitted': False, 'formal_admitted': False,
        'unknown_values_filled': False, 'household_generator_or_AB_changed': False}
    save(out / 'REFERENCE_EXECUTION.json', report)
    return report
