"""Single reference-housing entry; delegates physics to the existing compiler.

Resolve an explicitly chosen reference context, select the shared complete
enclosure class, and call reference_pipeline unchanged. This file supplies no
material, equipment, boundary, schedule, or numerical default of its own.
"""
import argparse
import copy
from pathlib import Path

from national_idf.common import ROOT, read, require, save, AdmissionError
from national_idf.condition_housing import plan
from national_idf.enclosure_class import select, CATALOG
from national_idf.reference_context import resolve
from national_idf.reference_pipeline import execute, implementation
from national_idf.reference_workflow import ref


def normalize(request):
    require(request.get('schema') == 'national_idf.reference_pipeline_request.v1', 'REFERENCE_PIPELINE_SCHEMA')
    result = copy.deepcopy(request); housing = result.get('housing'); context = None
    if not isinstance(housing, dict):
        return None, {'status': 'candidate_or_missing_conditions', 'gaps': [{'field': 'housing', 'code': 'INPUT_REQUIRED'}]}
    if housing.get('schema') != 'national_idf.housing_condition_request.v1':
        require(request.get('reference_context_policy'), 'REFERENCE_PIPELINE_REFERENCE_POLICY_REQUIRED')
        context = resolve(housing, request['reference_context_policy'], consent=request.get('select_reference_policy') is True)
        if context['gaps']:
            return None, {'status': 'candidate_or_missing_conditions', 'gaps': context['gaps'], 'context': context}
        result['housing'] = context['housing_request']
    design = plan(result['housing'])
    if design['status'] != 'constructible_reference':
        return None, {'status': 'candidate_or_missing_conditions', 'gaps': design['missing'], 'context': context}
    selected, selection = select(result)
    return selected, {'status': 'complete_reference_class_selected', 'context': context,
        'selection': selection, 'housing_plan': design, 'no_physics_or_service_parameters_invented': True,
        'native_or_numerical_acceptance_granted': False}


def run(request, out, housing_cache, package_cache, result_cache):
    out = Path(out).resolve()
    require(out.is_relative_to(ROOT) and not out.exists(), 'SHARED_HOUSING_OUTPUT_EXISTS')
    out.mkdir(parents=True); save(out / 'REQUEST.json', request)
    save(out / 'FRONTEND.json', {'runner': ref(ROOT / 'scripts/run_shared_housing.py'),
        'class_catalog': ref(ROOT / CATALOG), 'existing_compiler_implementation': implementation(),
        'does_not_replace_EB_or_unified_compiler': True})
    try:
        normalized, resolution = normalize(request); save(out / 'CLASS_RESOLUTION.json', resolution)
        if normalized is None:
            result = {**resolution, 'new_native_simulation_executed': False}
        else:
            save(out / 'COMPILE_REQUEST.json', normalized)
            result = execute(normalized, out / 'compiler', housing_cache, package_cache, result_cache)
            save(out / 'DELEGATION.json', {'normalized_request': ref(out / 'COMPILE_REQUEST.json'),
                'existing_compiler_response': ref(out / 'compiler/RESULT.json'),
                'returned_output_status_unchanged': True})
    except AdmissionError as error:
        result = {'status': 'request_not_executed_or_not_publishable', 'gap_code': error.code,
            'details': error.detail, 'new_native_simulation_executed': False,
            'no_other_class_or_location_silently_substituted': True}
    save(out / 'RESULT.json', result); return result


if __name__ == '__main__':
    parser = argparse.ArgumentParser(); parser.add_argument('--request', type=Path, required=True)
    parser.add_argument('--out', type=Path, required=True); parser.add_argument('--housing-cache', type=Path, required=True)
    parser.add_argument('--package-cache', type=Path, required=True); parser.add_argument('--result-cache', type=Path, required=True)
    args = parser.parse_args(); result = run(read(args.request), args.out, args.housing_cache, args.package_cache, args.result_cache)
    print(result['status'], result.get('gap_code', ''), flush=True)
