"""Compile pinned source resource windows; CASE supplies start times only.

A reference window is not a measured machine cycle. Native EnergyPlus has
already interpreted the source Schedule:File interpolation at each frozen step.
This compiler cannot infer profiles, resize devices, or approve a new context.
"""
from pathlib import Path
import shutil
import tempfile

from .common import ROOT, digest, finite, read, require, save, seal, sha
from .idf import Fields, objects, one, parse, render
from .source_adapter import source_file

DEVICES = ('washer', 'dryer', 'dishwasher')


def model_signature(rows):
    """Ignore reporting and explicitly variable calendar/numerical fields only."""
    return digest([row for row in rows if row[0] not in ('RunPeriod', 'Timestep')
                   and not row[0].startswith('Output')])


def plan_resources(rows, schema_ref, pack_ref, *, root=ROOT):
    pack = read(source_file(pack_ref, root))
    require(pack.get('schema') == 'national_idf.program_resource_pack.v1'
            and pack.get('service_unit') == 'published_source_resource_window', 'PROGRAM_RESOURCE_PACK_SCHEMA')
    require(pack['binding_model_signature'] == model_signature(rows), 'PROGRAM_RESOURCE_CONTEXT_NOT_BOUND')
    require(pack['engine_schema'] == schema_ref, 'PROGRAM_RESOURCE_ENGINE_NOT_BOUND')
    fields = Fields(source_file(schema_ref, root))
    step = 60 / float(one(rows, 'Timestep')[1])
    require(step in (1, 2, 5) and str(int(step)) in pack['profiles'], 'PROGRAM_RESOURCE_STEP_NOT_SUPPORTED')
    profile_ref = pack['profiles'][str(int(step))]
    profile = read(source_file(profile_ref, root))
    require(profile['step_min'] == step and set(profile['programs']) == set(DEVICES), 'PROGRAM_RESOURCE_PROFILE_STEP')
    for ref in pack['source_evidence']:
        source_file(ref, root)
    source_file(profile['native_interpreted_SQL'], root)
    for device, program in profile['programs'].items():
        require(program['model_key'] == pack['programs'][device]['model_key']
                and program['version'] == pack['programs'][device]['version'], 'PROGRAM_RESOURCE_MODEL_MISMATCH')
        length = program['duration_min'] / step
        require(length > 0 and length == int(length), 'PROGRAM_RESOURCE_DURATION')
        require(set(program['channels']) == set(pack['programs'][device]['schedules']), 'PROGRAM_RESOURCE_CHANNELS')
        for name, values in program['channels'].items():
            require(len(values) == length and all(finite(v) and v >= 0 for v in values),
                    'PROGRAM_RESOURCE_PROFILE_INVALID', name)
            require(len([r for r in objects(rows, 'Schedule:File') if r[1] == name]) == 1,
                    'PROGRAM_RESOURCE_SCHEDULE_MISSING', name)
        require(any(v[0] > 0 for v in program['channels'].values())
                and any(v[-1] > 0 for v in program['channels'].values()), 'PROGRAM_RESOURCE_ENVELOPE_NOT_EXACT')
        equipment = [r for r in objects(rows, 'ElectricEquipment') if r[1] == pack['programs'][device]['equipment']]
        require(len(equipment) == 1 and fields.get(equipment[0], 'schedule_name')
                == pack['programs'][device]['electric_schedule'], 'PROGRAM_RESOURCE_ELECTRIC_MAPPING')
        require(float(fields.get(equipment[0], 'design_level')) > 0, 'PROGRAM_RESOURCE_POWER_MISSING')
    return {'pack': pack_ref, 'profile': profile_ref, 'definition': pack, 'values': profile,
            'step_min': int(step), 'formal_admitted': False}


def assembly_resources(rows, spec, *, root=ROOT):
    refs = {key: spec['components'][key].get('program_resource_pack') for key in DEVICES}
    if not any(refs.values()):
        return None
    require(all(refs.values()) and all(ref == refs['washer'] for ref in refs.values()),
            'PROGRAM_RESOURCE_PACK_NOT_JOINTLY_BOUND')
    plan = plan_resources(rows, spec['engine_schema'], refs['washer'], root=root)
    for device in DEVICES:
        p, component = plan['values']['programs'][device], spec['components'][device]
        require(all(component[key] == p[key] for key in ('model_key', 'version')), 'PROGRAM_RESOURCE_COMPONENT_MISMATCH')
    return plan


def bind_program_domain(plan, domain):
    for device, program in plan['values']['programs'].items():
        target = domain['programs'][device]
        require(all(target.get(key) == program[key] for key in ('model_key', 'version', 'duration_min'))
                and target.get('resource_pack') == plan['pack']
                and target.get('max_starts_per_day') == 1, 'PROGRAM_RESOURCE_DOMAIN_MISMATCH', device)


def write_resources(stage, plan, *, root=ROOT):
    if plan is None:
        return
    folder = stage / 'program_resources'
    folder.mkdir()
    shutil.copyfile(source_file(plan['pack'], root), folder / 'PACK.json')
    shutil.copyfile(source_file(plan['profile'], root), folder / 'PROFILE.json')
    save(stage / 'PROGRAM_RESOURCES.json', {'pack': plan['pack'], 'profile': plan['profile'],
        'step_min': plan['step_min'], 'service_unit': 'published_source_resource_window',
        'native_water_partition_recomputed': True, 'dryness_or_cleaning_inferred': False})


def compile_reference_case(spec_ref, case, out, *, mode, root=ROOT):
    """Explicit component-only entrance using the same assembly resource compiler.

    It does not impersonate a reviewed six-device configuration. Other source
    schedules remain fixed context; any demand on those channels is rejected.
    """
    from .case_commands import CaseTimeline
    require(mode == 'engineering_reference', 'PROGRAM_REFERENCE_MODE_REQUIRED')
    spec = read(source_file(spec_ref, root))
    if spec.get('schema') == 'national_idf.six_reference_fixture.v1':
        from .joint_case_runtime import compile_joint_case
        return compile_joint_case(spec_ref, case, out, mode=mode, root=root)
    require(spec.get('schema') == 'national_idf.program_reference_fixture.v1', 'PROGRAM_REFERENCE_FIXTURE_SCHEMA')
    require(not (spec.get('installation_pack') and spec.get('whole_plug_load_replacement')),
            'PROGRAM_REFERENCE_COMPOSED_INSTALLATION_NEEDS_OWN_REVIEW')
    rows = parse(source_file(spec['model'], root).read_text())
    replacement, replacement_dependencies = None, []
    if spec.get('whole_plug_load_replacement'):
        from .load_replacement import apply as replace_plugs
        rows, replacement, replacement_dependencies = replace_plugs(rows, spec['whole_plug_load_replacement'],
                                                                    spec['engine_schema'], root=root)
    installation = None
    if spec.get('installation_pack'):
        from .installation import plan_installation, installation_receipt
        installation = plan_installation(spec['installation_pack'], spec['model'], rows, rows, spec['engine_schema'], root=root)
        require(installation['ready'], 'PROGRAM_INSTALLATION_EVIDENCE_BLOCKED', installation['gaps'])
        rows = installation['new_model_rows']
    plan = plan_resources(rows, spec['engine_schema'], spec['resource_pack'], root=root)
    domain = read(source_file(spec['input_domain'], root))
    require(case['environment']['physics_configuration_id'] == spec['id'], 'PROGRAM_REFERENCE_CASE_ID')
    bind_program_domain(plan, domain)
    timeline = CaseTimeline(case, domain, root=root)
    life, controls = case['life'], case['controls']
    selected = spec['applied_devices']
    require(selected and len(set(selected)) == len(selected) and set(selected) <= set(DEVICES),
            'PROGRAM_REFERENCE_DEVICE_SELECTION')
    require(spec['EB_mapping']['equipment'] == {device: {
        'equipment': plan['definition']['programs'][device]['equipment'], 'schedule_kind': 'Schedule:File'}
        for device in selected} and spec['EB_mapping']['water_heater'] is None,
        'PROGRAM_REFERENCE_EB_MAPPING_MISMATCH')
    for index in range(timeline.steps):
        require(all(task['device'] in selected for task in timeline.frame(index)['program_starts']),
                'PROGRAM_REFERENCE_UNSELECTED_START')
    require(not life['occupancy'] and not life['mixed_water_daily'] and not life.get('mixed_water_overrides')
            and life['ev_daily']['traction_kWh'] == 0 and not controls['ev_daily_windows']
            and not controls.get('ev_window_overrides') and not controls['daily_overrides']
            and not controls.get('dated_overrides') and all(life['services_daily'][device]['cycles'] == 0
                for device in set(DEVICES) - set(selected)), 'PROGRAM_REFERENCE_UNAPPLIED_DEMAND')
    require(not timeline.support['service_issues'], 'PROGRAM_REFERENCE_UNFINISHED_TASK', timeline.support['service_issues'])
    # Every source clock and profile dependency must be explicit. No generated
    # CSV, inferred day profile, new ground input or weather substitution here.
    fields = Fields(source_file(spec['engine_schema'], root))
    period = one(rows, 'RunPeriod')
    import datetime as dt
    dates = [dt.date(*[int(fields.get(period, key)) for key in keys]).isoformat() for keys in
             [('begin_year', 'begin_month', 'begin_day_of_month'), ('end_year', 'end_month', 'end_day_of_month')]]
    require(dates == [case['run']['start_date'], case['run']['end_date']], 'PROGRAM_REFERENCE_CALENDAR_MISMATCH')
    weather = source_file(spec['weather'], root)
    for dep in spec['dependencies']:
        target = Path(dep['output_path'])
        require(not target.is_absolute() and '..' not in target.parts and len(target.parts) == 1,
                'PROGRAM_REFERENCE_DEPENDENCY_PATH')
        source_file(dep['source'], root)
    # Official engine and EB code identities are pinned, not chosen by CASE.
    for ref in spec['official_engine_files'] + list(spec['EB_modules'].values()):
        source_file(ref, root)
    out = Path(out).absolute()
    require(not out.exists(), 'OUTPUT_EXISTS', str(out))
    out.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='.program-case-', dir=out.parent) as temp:
        stage = Path(temp) / 'compiled'; stage.mkdir()
        (stage / 'in.idf').write_text(render(rows))
        shutil.copyfile(weather, stage / 'weather.epw')
        for dep in spec['dependencies']:
            shutil.copyfile(source_file(dep['source'], root), stage / dep['output_path'])
        for dep in replacement_dependencies:
            target = stage / dep['output_path']; target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source_file(dep['source'], root), target)
        write_resources(stage, plan, root=root)
        save(stage / 'CASE.json', case)
        save(stage / 'RUNTIME_SUPPORT_DOMAIN.json', domain)
        save(stage / 'INPUT_SUPPORT.json', timeline.support)
        save(stage / 'FIXTURE.json', spec)
        if replacement is not None:
            save(stage / 'LOAD_REPLACEMENT.json', replacement)
        if installation is not None:
            save(stage / 'INSTALLATION.json', installation_receipt(installation))
        save(stage / 'PROVENANCE.json', {'fixture': spec_ref, 'component_only': True,
            'fixed_source_context': True, 'housing_applicability_approved': False})
        save(stage / 'COMPILER_IDENTITY.json', {name: sha(root / name) for name in
            ('national_idf/program_resources.py', 'national_idf/case_commands.py', 'national_idf/request_support.py',
             'national_idf/installation.py')})
        if replacement is not None:
            identity = read(stage / 'COMPILER_IDENTITY.json')
            identity['national_idf/load_replacement.py'] = sha(root / 'national_idf/load_replacement.py')
            save(stage / 'COMPILER_IDENTITY.json', identity)
        receipt = seal(stage, {'schema': 'national_idf.compiled_program_reference_CASE.v1',
            'execution_mode': mode, 'formal_admitted': False, 'whole_CASE_executed': False,
            'physical_values_invented': False, 'engine_started': False})
        stage.rename(out)
    return receipt
