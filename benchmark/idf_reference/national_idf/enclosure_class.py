"""Select a frozen reference enclosure class before the existing compiler.

This is input policy, not another physical compiler. It leaves household facts,
geometry conditions, equipment, life and controls unchanged. Its output is the
same existing reference_pipeline_request, with a registered recipe selected.
"""
import argparse
import copy
from pathlib import Path

from .common import ROOT, read, require, save
from .source_adapter import source_file
from .reference_workflow import ref

CATALOG = 'configs/reference_enclosure_classes_v2.json'


def select(request, class_id=None, *, root=ROOT):
    catalog = read(root / CATALOG)
    housing = request.get('housing') or {}
    require(request.get('schema') == 'national_idf.reference_pipeline_request.v1', 'ENCLOSURE_CLASS_REQUEST_SCHEMA')
    require(housing.get('schema') == 'national_idf.housing_condition_request.v1', 'ENCLOSURE_CLASS_RESOLVED_HOUSING_REQUIRED')
    conditions = housing.get('reference_housing') or {}
    if class_id == 'CN_low_insulation_masonry_slab_flat_roof_v1':
        require(conditions.get('stories_above_grade') == 1, 'ENCLOSURE_CLASS_LEGACY_SCOPE_CONFLICT')
        class_id = 'CN_complete_reference_detached_v1'
    if class_id is None:
        matches = [v for v in catalog['classes'] if v['country'] == housing.get('country') and
                   all(conditions.get(k) in allowed for k, allowed in v['housing_conditions'].items())]
        require(len(matches) == 1, 'ENCLOSURE_CLASS_AMBIGUOUS_OR_UNSUPPORTED', [v['id'] for v in matches])
    else:
        matches = [v for v in catalog['classes'] if v['id'] == class_id]
        require(len(matches) == 1, 'ENCLOSURE_CLASS_UNKNOWN', class_id)
    chosen = matches[0]
    require(housing.get('country') == chosen['country'], 'ENCLOSURE_CLASS_COUNTRY_CONFLICT')
    require(conditions.get('acknowledge_reference_not_survey_home') is True, 'ENCLOSURE_CLASS_REFERENCE_ACK_REQUIRED')
    for key, allowed in chosen['housing_conditions'].items():
        require(conditions.get(key) in allowed, 'ENCLOSURE_CLASS_HOUSING_CONFLICT', key)
    if chosen.get('regional_package'):
        from .regional_profile import package
        _, binding = package(housing['country'], housing.get('site_id'), root=root)
        require(binding == chosen['regional_package'], 'ENCLOSURE_CLASS_REGIONAL_PACKAGE_CONFLICT')
    if chosen['recipe_id'] is not None:
        recipes = read(source_file(chosen['recipe_catalog'], root))
        candidates = [v for v in recipes['recipes'] if v['id'] == chosen['recipe_id']]
        require(len(candidates) == 1 and candidates[0]['country'] == chosen['country'], 'ENCLOSURE_CLASS_RECIPE_CONFLICT')
        source_file(candidates[0]['source_pack'], root)
    require('envelope_recipe_id' not in request or request['envelope_recipe_id'] == chosen['recipe_id'],
            'ENCLOSURE_CLASS_EXPLICIT_RECIPE_CONFLICT')
    result = copy.deepcopy(request); result['envelope_recipe_id'] = chosen['recipe_id']
    return result, {'schema': 'national_idf.enclosure_class_selection.v1', 'class_id': chosen['id'],
                    'selection_mode': 'unique_compatible_reference_class' if class_id is None else 'explicit_shared_class',
                    'catalog': ref(root / CATALOG, root), 'recipe_catalog': chosen['recipe_catalog'],
                    'regional_package': chosen.get('regional_package'),
                    'selected_recipe_id': chosen['recipe_id'], 'selection_basis': chosen['selection_basis'],
                    'housing_equipment_life_and_control_unchanged': True, 'survey_facts_modified': False,
                    'new_CASE_requires_original_native_checks': True, 'class_wide_numeric_admission_granted': False}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(); parser.add_argument('--request', type=Path, required=True)
    parser.add_argument('--class-id'); parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args(); request, report = select(read(args.request), args.class_id)
    require(args.out.resolve().is_relative_to(ROOT) and not args.out.exists(), 'ENCLOSURE_CLASS_OUTPUT_EXISTS')
    args.out.mkdir(parents=True); save(args.out / 'REQUEST.json', request); save(args.out / 'SELECTION.json', report)
