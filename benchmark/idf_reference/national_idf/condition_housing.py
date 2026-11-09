"""Construct reference housing from conditions through the pinned public builder.

The official geometry measure owns area, floors and adiabatic boundaries.
The existing EB installers own appliances. No IDF vertex scaling, national
stock defaults, household generator or new appliance physics is added here.
"""
import argparse
import copy
from decimal import Decimal
from pathlib import Path
import subprocess
import time
import xml.etree.ElementTree as ET

from .common import ROOT, digest, read, require, save, sha
from .reference_workflow import ref
from .source_adapter import source_file

from .native_build_runtime import catalog_path

CATALOG = catalog_path()
FT2_M2 = Decimal('0.09290304')


def plan(request, *, root=ROOT):
    require(request.get('schema') == 'national_idf.housing_condition_request.v1', 'HOUSING_CONDITION_SCHEMA')
    require(set(request) <= {'schema', 'request_id', 'country', 'site_id', 'reference_housing', 'survey_housing'},
            'HOUSING_CONDITION_UNSUPPORTED_FIELDS')
    catalog = read(root / CATALOG)
    for item in catalog['sources'].values(): source_file(item, root)
    housing = request.get('reference_housing') or {}
    required = {'kind', 'conditioned_area_m2', 'area_basis', 'stories_above_grade', 'attached_walls',
                'vertical_context', 'acknowledge_reference_not_survey_home'}
    require(set(housing) <= required, 'HOUSING_CONDITION_EXTRA_PHYSICS_FIELD')
    missing = sorted(k for k in required if housing.get(k) is None)
    if missing:
        return {'status': 'missing_conditions', 'missing': missing, 'survey_housing': copy.deepcopy(request.get('survey_housing', {}))}
    require(housing['acknowledge_reference_not_survey_home'] is True, 'HOUSING_REFERENCE_ACK_REQUIRED')
    require(housing['area_basis'] == 'declared_reference_conditioned_floor_area', 'HOUSING_CONDITION_AREA_BASIS')
    area = housing['conditioned_area_m2']
    require(type(area) in (int, float) and 0 < area < 1e6, 'HOUSING_CONDITION_AREA_INVALID')
    family = catalog['families'].get(housing['kind'])
    require(family is not None, 'HOUSING_CONDITION_KIND_UNKNOWN')
    stories = housing['stories_above_grade']
    require(type(stories) is int and stories in family['stories_above_grade'], 'HOUSING_CONDITION_STORIES')
    walls = housing['attached_walls']
    require(walls in family['attached_walls'], 'HOUSING_CONDITION_ADJACENCY')
    vertical = family['vertical_contexts'].get(housing['vertical_context'])
    require(vertical is not None, 'HOUSING_CONDITION_VERTICAL_CONTEXT')
    sites = [s for s in catalog['sites'] if s['id'] == request.get('site_id')]
    require(len(sites) == 1 and sites[0]['country'] == request.get('country'), 'HOUSING_CONDITION_SITE_COUNTRY')
    site = sites[0]
    source_file(site['site_pack'], root)
    args = copy.deepcopy(read(source_file(catalog['sources']['builder_workflow'], root))['steps'][0]['arguments'])
    args.update(catalog['builder_geometry_only_system_overrides'])
    regional = None
    if catalog.get('regional_enclosure_packages'):
        from .regional_profile import apply
        source_file(catalog['regional_enclosure_packages'], root)
        args, regional = apply(request['country'], request['site_id'], args, root=root)
    args.update(geometry_unit_type=family['unit_type_by_stories'][str(stories)],
                geometry_unit_conditioned_floor_area=str(Decimal(str(area))/FT2_M2),
                geometry_attached_walls=walls, **vertical)
    # The output path and wall clock are execution metadata, not physical keys.
    args.pop('hpxml_path', None)
    definition = {'builder_arguments': args, 'source_catalog': ref(root / CATALOG, root),
                  'country': request['country'], 'site': site,
                  'reference_conditions': housing}
    if regional is not None: definition['regional_enclosure_package'] = regional
    return {'schema': 'national_idf.housing_condition_plan.v1', 'status': 'constructible_reference',
            'configuration_id': 'condition_ref_' + digest(definition)[:24], 'definition': definition,
            'survey_housing': copy.deepcopy(request.get('survey_housing', {})),
            'survey_housing_modified': False, 'physical_admission_granted': False,
            'new_geometry_and_site_require_own_validation': True}


def _command(command, folder, name, cwd):
    start = time.monotonic()
    with (folder / (name + '.log')).open('w') as log:
        p = subprocess.run([str(v) for v in command], stdout=log, stderr=subprocess.STDOUT, cwd=cwd)
    receipt = {'command': [str(v) for v in command], 'exit_code': p.returncode,
               'seconds': time.monotonic() - start}
    save(folder / (name + '.json'), receipt)
    require(p.returncode == 0, 'HOUSING_CONDITION_SOURCE_COMMAND_FAILED', name)
    return receipt


def build(request, out, *, root=ROOT):
    design = plan(request, root=root)
    require(design['status'] == 'constructible_reference', 'HOUSING_CONDITION_NOT_CONSTRUCTIBLE', design)
    out = Path(out).resolve()
    require(out.is_relative_to(root.resolve()) and not out.exists(), 'HOUSING_CONDITION_OUTPUT_EXISTS')
    out.mkdir(parents=True)
    save(out / 'REQUEST.json', request); save(out / 'PLAN.json', design)
    catalog = read(root / CATALOG)
    checkout = root / catalog['checkout']
    cli = root / read(source_file(catalog['sources']['sdk'], root))['CLI_paths'][0]
    geometry = out / 'geometry'; geometry.mkdir()
    workflow = read(source_file(catalog['sources']['builder_workflow'], root))
    workflow['run_directory'] = str(geometry / 'run')
    workflow['measure_paths'] = [str(checkout)]
    args = copy.deepcopy(design['definition']['builder_arguments'])
    args.update(hpxml_path=str(geometry / 'built.xml'),
                location_epw_path=str(source_file(catalog['sources']['source_weather'], root)))
    workflow['steps'][0]['arguments'] = args
    save(geometry / 'build.osw', workflow)
    commands = [_command([cli, 'run', '-m', '-w', geometry / 'build.osw'], out, 'GEOMETRY_BUILD', checkout)]

    # Whole complete public device blocks, exactly as in the prior apartment
    # installer; do not transplant individual performance points or defaults.
    tree = ET.parse(geometry / 'built.xml'); original = tree.getroot()
    equipment = ET.parse(source_file(catalog['sources']['equipment_xml'], root)).getroot()
    local = lambda e: e.tag.rsplit('}', 1)[-1]
    namespace = original.tag.split('}')[0][1:]; ET.register_namespace('', namespace)
    enclosure_before = ET.tostring(next(e for e in original.iter() if local(e) == 'Enclosure'))
    replacements = []
    for name in ('Systems', 'Appliances'):
        old = next(e for e in original.iter() if local(e) == name)
        owner = next(e for e in original.iter() if old in list(e))
        new = copy.deepcopy(next(e for e in equipment.iter() if local(e) == name))
        index = list(owner).index(old); owner.remove(old); owner.insert(index, new)
        replacements.append({'element': name, 'before': ET.tostring(old, encoding='unicode'),
                             'after': ET.tostring(new, encoding='unicode')})
    summary = next(e for e in original.iter() if local(e) == 'BuildingSummary')
    extension = next((e for e in summary if local(e) == 'extension'), None)
    if extension is None: extension = ET.SubElement(summary, '{' + namespace + '}extension')
    for element in list(extension):
        if local(element) == 'SchedulesFilePath': extension.remove(element)
    extension.append(copy.deepcopy(next(e for e in equipment.iter() if local(e) == 'SchedulesFilePath')))
    require(enclosure_before == ET.tostring(next(e for e in original.iter() if local(e) == 'Enclosure')),
            'HOUSING_CONDITION_EQUIPMENT_CHANGED_ENCLOSURE')
    xml = out / 'housing_with_devices.xml'; tree.write(xml, encoding='utf-8', xml_declaration=True)
    xml_area = next(e for e in original.iter() if local(e) == 'ConditionedFloorArea')
    actual_area = float(Decimal(xml_area.text) * FT2_M2)
    requested_area = request['reference_housing']['conditioned_area_m2']
    require(abs(actual_area - requested_area) < 1e-8, 'HOUSING_CONDITION_AREA_NOT_PRESERVED')
    commands.append(_command([cli, checkout / 'workflow/run_simulation.rb', '-x', xml, '-o', out / 'source_model',
                              '-d', '--skip-simulation'], out, 'SOURCE_TRANSLATION', checkout))
    commands.append(_command([cli, root / 'scripts/forward_translate_source.rb', out / 'source_model/run/in.osm',
                              out / 'source_model/run/in.idf'], out, 'FORWARD_TRANSLATION', checkout))
    receipt = {'schema': 'national_idf.condition_generated_source.v1', 'plan': ref(out / 'PLAN.json', root),
        'official_builder': catalog['sources']['builder'], 'source_workflow': catalog['sources']['builder_workflow'],
        'generated_geometry_xml': ref(geometry / 'built.xml', root), 'derived_XML': ref(xml, root),
        'source_model': ref(out / 'source_model/run/in.idf', root), 'source_area_m2': actual_area,
        'equipment_blocks': replacements, 'commands': commands,
        'reference_geometry_generated_by_official_algorithm': True, 'IDF_vertices_manually_scaled': False,
        'generated_enclosure_unchanged_by_equipment_installation': True,
        'not_measured_or_national_stock_housing': True, 'household_generation_or_AB_called': False,
        'numerical_or_physical_acceptance_granted': False}
    save(out / 'SOURCE_RECEIPT.json', receipt)
    return receipt


def main():
    p = argparse.ArgumentParser(); p.add_argument('action', choices=('plan', 'build'))
    p.add_argument('--request', type=Path, required=True); p.add_argument('--out', type=Path, required=True)
    a = p.parse_args(); request = read(a.request)
    if a.action == 'plan': save(a.out, plan(request))
    else: build(request, a.out)


if __name__ == '__main__': main()
