"""Compose reference measures with the existing source compiler and EB runtime.

The result is an engineering configuration, never a formal release inferred
from successful compilation. Country names are data; no country-specific code.
"""
from __future__ import annotations

import copy
from pathlib import Path
import shutil

from .common import ROOT, digest, read, require, save, sha
from .idf import Fields, objects, parse, render
from .source_adapter import housing_fingerprint, selector, source_file

IMPLEMENTATION = ('national_idf/envelope_adaptation.py', 'national_idf/reference_scenarios.py',
                  'national_idf/reference_workflow.py', 'national_idf/reference_equipment.py')


def ref(path, root=ROOT):
    return {'path': str(Path(path).resolve().relative_to(root.resolve())), 'sha256': sha(path)}


def schedule_dependency(dependencies, filename, *, root=ROOT):
    """Several source schedules may legitimately share one pinned CSV."""
    matches=[d['source'] for d in dependencies if d['output_path']==filename]
    require(matches and len({(d['path'],d['sha256']) for d in matches})==1,
            'REFERENCE_SOURCE_SCHEDULE_DEPENDENCY', filename)
    for item in matches:source_file(item,root)
    return matches[0]


def apply_site(rows, site_ref, schema_ref, *, root=ROOT):
    from .weather import audit
    from .weather_mains import derive
    site = read(source_file(site_ref, root))
    require(site.get('schema') == 'national_idf.reference_site.v1', 'REFERENCE_SITE_SCHEMA')
    weather = source_file(site['weather'], root)
    qc = audit(weather)
    require(not qc['errors'], 'REFERENCE_WEATHER_QC_FAILED', qc['errors'])
    identity = qc['identity']
    require(identity == site['weather_identity'], 'REFERENCE_SITE_IDENTITY_CHANGED')
    require(site.get('time_basis') == 'local_standard_time_no_DST' and site.get('terrain_basis')
            and site.get('ground_basis') and site.get('design_conditions'), 'REFERENCE_SITE_SCOPE_INCOMPLETE')
    result = copy.deepcopy(rows); inventory = []
    location = ['Site:Location', identity['city'], *[str(identity[k]) for k in
                ('latitude', 'longitude', 'timezone', 'elevation_m')], 'Yes']
    mains = derive(site['weather'], root=root)
    for kind, after in [('Site:Location', location), ('Site:WaterMainsTemperature', mains['idf_object'])]:
        before = objects(result, kind)
        require(len(before) == 1, 'REFERENCE_SITE_OBJECT_CARDINALITY', kind)
        index = result.index(before[0]); inventory.append({'before': before[0], 'after': after})
        result[index] = after
    boundaries = None
    if site.get('derived_boundaries'):
        boundaries = read(source_file(site['derived_boundaries'], root))
        require(boundaries['weather'] == site['weather'], 'REFERENCE_BOUNDARY_WEATHER_MISMATCH')
        source_file(boundaries['algorithm'], root); source_file(boundaries['exporter'], root)
        temperatures = boundaries['shallow_ground_monthly_C']
        require(len(temperatures) == 12 and all(type(v) in (int, float) and -90 < v < 90 for v in temperatures),
                'REFERENCE_GROUND_DERIVATION_INVALID')
        old = objects(result, 'Site:GroundTemperature:Shallow')
        require(len(old) == 1, 'REFERENCE_SHALLOW_GROUND_OBJECT_CARDINALITY')
        after = ['Site:GroundTemperature:Shallow', *[format(v, '.17g') for v in temperatures]]
        index = result.index(old[0]); inventory.append({'before': old[0], 'after': after}); result[index] = after
    fields = Fields(source_file(schema_ref, root))
    for row in objects(result, 'RunPeriod'):
        require(fields.get(row, 'use_weather_file_daylight_saving_period') == 'No', 'REFERENCE_DST_NOT_DISABLED')
    return result, {'site_pack': site_ref, 'weather_QC': qc, 'modifications': inventory,
                    'mains': mains, 'ground_basis': site['ground_basis'],
                    'ground_locally_measured': False, 'derived_boundaries': boundaries,
                    'design_capacity_verified': False}


def prepare(spec_ref, out, *, root=ROOT):
    """Enclosure → site → source adapter → existing unified source compiler."""
    from .assembly import compile_assembly
    from .envelope_adaptation import apply as apply_envelope
    from .program_resources import model_signature, plan_resources
    spec = read(source_file(spec_ref, root))
    require(spec.get('schema') == 'national_idf.reference_workflow.v1', 'REFERENCE_WORKFLOW_SCHEMA')
    require(spec.get('representation_kind') in ('local_archetype', 'controlled_reference'), 'REFERENCE_KIND')
    parent = read(source_file(spec['parent_fixture'], root))
    source_rows = parse(source_file(parent['model'], root).read_text())
    # Validate the inherited resource library before binding it to any derivative.
    plan_resources(source_rows, parent['engine_schema'], parent['resource_pack'], root=root)
    rows, envelope_report = source_rows, None
    if spec.get('envelope_pack'):
        require(spec['representation_kind'] == 'controlled_reference', 'LOCAL_ARCHETYPE_ENVELOPE_OVERRIDE')
        rows, envelope_report = apply_envelope(rows, spec['envelope_pack'], parent['engine_schema'], root=root)
    site_report = None
    if spec.get('site_pack'):
        rows, site_report = apply_site(rows, spec['site_pack'], parent['engine_schema'], root=root)
    tank_report = None
    if spec.get('complete_tank'):
        from .reference_equipment import install_tank
        rows, tank_report = install_tank(rows, spec['complete_tank'], parent['engine_schema'], root=root)
    out = Path(out).resolve()
    require(out.is_relative_to(root.resolve()) and not out.exists(), 'REFERENCE_OUTPUT_PATH')
    out.mkdir(parents=True)
    (out/'prepared.idf').write_text(render(rows))
    rows = parse((out/'prepared.idf').read_text())
    mapping = copy.deepcopy(parent['EB_mapping']); save(out/'EB_MAPPING.json', mapping)
    dependencies = []
    for index, row in enumerate(rows):
        if row[0] != 'Schedule:File':
            continue
        dependency = schedule_dependency(parent['dependencies'], row[3], root=root)
        dependencies.append({'object': selector(rows, index), 'original_filename': row[3], 'file': dependency})
    adapter = {'schema': 'national_idf.source_adapter.v1', 'adapter': 'native_idf_objects.v1',
               'id': spec['id']+'__source', 'package_id': spec['id']+'__prepared_package',
               'model': ref(out/'prepared.idf', root), 'engine_version': '25.2',
               'housing_sha256': housing_fingerprint(rows),
               'thermal_zones': [r[1] for r in objects(rows, 'Zone')], 'schedule_files': dependencies,
               'legacy_groups': {}, 'support_conditions': spec['support_scope'],
               'source_scope_gaps': spec['remaining_evidence_gaps']}
    save(out/'SOURCE_ADAPTER.json', adapter)
    evidence = ref(out/'PROVENANCE.json', root) if (out/'PROVENANCE.json').exists() else spec_ref
    components = {device: {'status': 'engineering_reference', 'evidence': evidence}
                  for device in ('air_conditioner', 'washer', 'dryer', 'dishwasher', 'water_heater', 'ev')}
    blueprint = {'schema': 'national_idf.assembly_blueprint.v1', 'id': spec['id'],
                 'source_adapter': ref(out/'SOURCE_ADAPTER.json', root), 'changes': [],
                 'legacy_group_policy': {}, 'components': components,
                 'engine_schema': parent['engine_schema'], 'eb_mapping': ref(out/'EB_MAPPING.json', root),
                 'eb_binding_implementation': parent['EB_modules']['binding'],
                 'site_weather': {'artifacts': [spec_ref], 'weather': read(source_file(spec['site_pack'], root))['weather']
                                  if spec.get('site_pack') else parent['weather']},
                 'numerical_protocol': ref(root/'configs/study_protocol.json', root),
                 'review_receipts': {}, 'assembly_gaps': [], 'formal_release_gaps': spec['remaining_evidence_gaps']}
    save(out/'BLUEPRINT.json', blueprint)
    compile_assembly(spec['id'], out/'assembly', mode='engineering_reference', root=root,
                     blueprint_ref=ref(out/'BLUEPRINT.json', root))
    compiled_rows = parse((out/'assembly/in.idf').read_text())
    assembly = read(out/'assembly/ASSEMBLY.json')
    # This rebinding grants no physical validation: only the electrical/water
    # resource schedules and their consuming objects must be exactly inherited.
    inherited_types = ('ElectricEquipment', 'OtherEquipment', 'WaterUse:Equipment', 'WaterUse:Connections',
                       'WaterHeater:Stratified', 'EnergyManagementSystem:Program')
    expected_devices = source_rows
    if spec.get('complete_tank'):
        from .reference_equipment import install_tank
        expected_devices, _ = install_tank(source_rows, spec['complete_tank'], parent['engine_schema'], root=root)
    for kind in inherited_types:
        require(objects(expected_devices, kind) == objects(compiled_rows, kind), 'REFERENCE_DEVICE_PHYSICS_CHANGED', kind)
    pack = read(source_file(parent['resource_pack'], root))
    pack['binding_model_signature'] = model_signature(compiled_rows)
    pack['id'] = spec['id']+'__source_resources'
    pack['source_evidence'] = [*pack['source_evidence'], spec_ref]
    save(out/'RESOURCE_PACK.json', pack)
    domain = read(source_file(parent['input_domain'], root)); domain['physics_configuration_id'] = spec['id']
    for program in domain['programs'].values():
        program['resource_pack'] = ref(out/'RESOURCE_PACK.json', root)
    save(out/'DOMAIN.json', domain)
    fixture = copy.deepcopy(parent)
    fixture.update(id=spec['id'], model=ref(out/'assembly/in.idf', root),
                   dependencies=assembly['dependencies'], resource_pack=ref(out/'RESOURCE_PACK.json', root),
                   input_domain=ref(out/'DOMAIN.json', root),
                   weather=blueprint['site_weather']['weather'])
    save(out/'FIXTURE.json', fixture)
    report = {'schema': 'national_idf.reference_workflow_receipt.v1', 'configuration_id': spec['id'],
              'workflow': spec_ref, 'parent_fixture': spec['parent_fixture'],
              'representation_kind': spec['representation_kind'], 'country': spec['country'],
              'support_scope': spec['support_scope'], 'envelope': envelope_report, 'site': site_report,
              'inherited_device_physics_unchanged': True, 'complete_tank_replacement': tank_report,
              'unified_source_compiler_executed': True,
              'runtime_fixture': ref(out/'FIXTURE.json', root),
              'implementation': {p: sha(root/p) for p in IMPLEMENTATION},
              'remaining_evidence_gaps': spec['remaining_evidence_gaps'],
              'physical_validation_passed': False, 'formal_admitted': False,
              'household_or_AB_generated': False}
    save(out/'PREPARATION.json', report)
    return report


def compile_case(preparation_ref, case, out, *, root=ROOT):
    from .joint_case_runtime import compile_joint_case
    preparation = read(source_file(preparation_ref, root))
    require(preparation['schema'] == 'national_idf.reference_workflow_receipt.v1', 'REFERENCE_PREPARATION_SCHEMA')
    require(all(sha(root/p) == v for p, v in preparation['implementation'].items()), 'REFERENCE_CODE_CHANGED')
    # Recompute the measure result and compare every model row. A receipt flag
    # or a changed pack hash cannot authorize unlogged physics.
    spec = read(source_file(preparation['workflow'], root)); parent = read(source_file(spec['parent_fixture'], root))
    rows = parse(source_file(parent['model'], root).read_text())
    if spec.get('envelope_pack'):
        from .envelope_adaptation import apply
        rows, _ = apply(rows, spec['envelope_pack'], parent['engine_schema'], root=root)
    if spec.get('site_pack'):
        rows, _ = apply_site(rows, spec['site_pack'], parent['engine_schema'], root=root)
    if spec.get('complete_tank'):
        from .reference_equipment import install_tank
        rows, _ = install_tank(rows, spec['complete_tank'], parent['engine_schema'], root=root)
    fixture = read(source_file(preparation['runtime_fixture'], root))
    expected = copy.deepcopy(rows)
    depmap = {d['source']['sha256']: d['output_path'] for d in fixture['dependencies']}
    parent_deps = {d['output_path']: d['source']['sha256'] for d in parent['dependencies']}
    for row in expected:
        if row[0] == 'Schedule:File': row[3] = depmap[parent_deps[row[3]]]
    require(expected == parse(source_file(fixture['model'], root).read_text()), 'REFERENCE_MEASURES_NOT_REPRODUCIBLE')
    return compile_joint_case(preparation['runtime_fixture'], case, out, mode='engineering_reference', root=root)


def run(compiled, out, *, root=ROOT):
    from .joint_case_runtime import run_joint_case
    return run_joint_case(compiled, out, mode='engineering_reference', root=root)
