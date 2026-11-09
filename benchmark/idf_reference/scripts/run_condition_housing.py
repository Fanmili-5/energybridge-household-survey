"""Connect condition-generated housing to existing EB installers and compiler."""
import argparse
import copy
from pathlib import Path
import time

from national_idf.common import ROOT, read, require, save, sha
from national_idf.condition_housing import plan
from national_idf.idf import Fields, objects, parse
from national_idf.reference_workflow import ref, prepare, run, compile_case
from national_idf.source_adapter import source_file
from scripts.validate_multicountry_life import validate


def execute(request_path, source, out):
    source = Path(source).resolve(); out = Path(out).resolve()
    request = read(request_path); design = plan(request)
    require(read(source / 'PLAN.json') == design, 'CONDITION_GENERATED_SOURCE_PLAN_CHANGED')
    receipt = read(source / 'SOURCE_RECEIPT.json')
    source_file(receipt['source_model'], ROOT)
    require(not out.exists(), 'CONDITION_RUN_OUTPUT_EXISTS'); out.mkdir(parents=True)
    before = time.monotonic()

    # This is the same source geometry-independent installer used for the
    # earlier apartment,not a second implementation of appliance physics.
    from scripts import run_six_joint as joint
    old_out = joint.OUT
    old_source = {k: getattr(joint.source, k) for k in ('OUT', 'ORIGIN', 'CHANNELS', 'SHIFTS')}
    try:
        joint.OUT = source
        joint.prepare(2)
        joint.build_case(2, 'summer')
    finally:
        joint.OUT = old_out
        for k, v in old_source.items(): setattr(joint.source, k, v)
    installer_seconds = time.monotonic() - before

    # Correct target weather,mains and source shallow-ground algorithm before
    # the actual target CASE. Earlier source profiles are resource extraction
    # only;their legacy host weather/mains are not target-location validation.
    site_ref = design['definition']['site']['site_pack']; site = read(source_file(site_ref, ROOT))
    site['id'] = design['configuration_id'] + '__site'
    site['ground_basis'] = 'Complete officially generated foundation/soil context retained as reference;source weather-derived shallow temperatures when supplied;not measured local soil'
    site['design_conditions']['capacity_selected_from_local_design_load'] = False
    save(out / 'SITE_PACK.json', site)
    source_fixture = ref(source / 'summer_2min/FIXTURE.json')
    old = read(ROOT / 'reports/multicountry_idf_20261107/US_EB_TANK_WORKFLOW.json')
    workflow = {'schema': 'national_idf.reference_workflow.v1', 'id': design['configuration_id'],
        'country': request['country'], 'representation_kind': 'controlled_reference',
        'parent_fixture': source_fixture, 'envelope_pack': None, 'site_pack': ref(out / 'SITE_PACK.json'),
        'complete_tank': old['complete_tank'],
        'support_scope': 'Condition-generated public reference geometry and complete source construction plus EB six-device chain;declared area/floors/adjacency and explicit site;not local stock or measured housing',
        'remaining_evidence_gaps': ['New generated geometry/source defaults and enclosure physical review',
            'Independent design-load/performance-domain assessment for this geometry/site',
            'Original numerical protocol and cross-season support for this geometry/site',
            'No comparison with author output']}
    save(out / 'WORKFLOW.json', workflow)
    start = time.monotonic()
    prepare(ref(out / 'WORKFLOW.json'), out / 'source_compiler')
    preparation_seconds = time.monotonic() - start
    case = read(source / 'summer_2min/CASE.json')
    case.update(case_id=design['configuration_id'], environment={**case['environment'], 'physics_configuration_id': design['configuration_id']})
    save(out / 'source_compiler/CASE.json', case)
    # Existing life preparation creates the independent People/general-water
    # ports;source backgrounds and all consumer physics remain accounted for.
    from national_idf.reference_life import prepare as prepare_life
    start = time.monotonic()
    prepare_life(ref(out / 'source_compiler/BLUEPRINT.json'), ref(out / 'source_compiler/FIXTURE.json'),
                 out / 'life', supply_receipt_ref=ref(source / 'profiles/native_baseline_2min/WATER_INSTALLATION.json'))
    life_seconds = time.monotonic() - start
    fixture = read(out / 'life/FIXTURE.json'); case = read(out / 'life/CASE.json')
    # The name is a derived physical configuration,never an input lookup ID.
    save(out / 'FIXTURE.json', fixture); save(out / 'CASE.json', case)
    start = time.monotonic()
    from national_idf.joint_case_runtime import compile_joint_case, run_joint_case
    compile_joint_case(ref(out / 'FIXTURE.json'), case, out / 'compiled', mode='engineering_reference')
    compile_seconds = time.monotonic() - start
    start = time.monotonic(); run_joint_case(out / 'compiled', out / 'run', mode='engineering_reference')
    native_seconds = time.monotonic() - start
    save(out / 'COSTS.json', {'legacy_source_resource_install_and_probes': installer_seconds,
        'source_compiler': preparation_seconds, 'life_ports': life_seconds, 'CASE_compile': compile_seconds, 'CASE_native': native_seconds})
    return finish(request_path, source, out)


def finish(request_path, source, out):
    source=Path(source).resolve(); out=Path(out).resolve(); request=read(request_path); design=plan(request)
    require(read(source/'PLAN.json')==design,'CONDITION_GENERATED_SOURCE_PLAN_CHANGED')
    receipt=read(source/'SOURCE_RECEIPT.json'); fixture=read(out/'FIXTURE.json')
    case=read(out/'CASE.json')
    checks = validate(out / 'run', fixture, case)
    from national_idf.condition_geometry import check
    geometry = check(fixture, receipt['source_model'], receipt['derived_XML'], ref(out / 'run/output/eplusout.eio'))
    save(out / 'GEOMETRY_CHECKS.json', geometry)
    rows = parse(source_file(fixture['model'], ROOT).read_text()); fields = Fields(source_file(fixture['engine_schema'], ROOT))
    component = read(ROOT / 'configs/component_models/EB_original_water_heater_c58a2a7a.json')
    tanks = objects(rows, 'WaterHeater:Stratified')
    require(len(tanks) == 1 and all(fields.get(tanks[0], k) == v for k, v in component['physical_parameters'].items()),
            'CONDITION_ORIGINAL_EB_TANK_CHANGED')
    require(not objects(rows, 'ZoneHVAC:IdealLoadsAirSystem') and not objects(rows, 'Coil:Heating:Electric'),
            'CONDITION_HIDDEN_HEATING')
    result = {'schema': 'national_idf.condition_housing_native_execution.v1', 'request': ref(request_path),
        'plan': design, 'source_receipt': ref(source / 'SOURCE_RECEIPT.json'), 'fixture': ref(out / 'FIXTURE.json'),
        'compiled_model': fixture['model'], 'CASE': ref(out / 'CASE.json'),
        'area_m2': geometry['conditioned_area_m2'], 'air_volume_m3': geometry['conditioned_air_volume_m3'],
        'native_floor_area_m2':geometry['native_conditioned_floor_area_m2'],
        'reference_CFA_minus_polygon_area_m2':geometry['source_CFA_minus_polygon_floor_area_m2'],
        'boundaries': geometry['boundary_counts'], 'same_unified_source_compiler': True,
        'source_geometry_and_context_preserved': geometry['complete_source_context_retained'],
        'native_component_life_checks_pass': checks['passed_input_and_component_checks'],
        'original_EB_tank_unchanged': True, 'numerical_acceptance': False, 'formal_or_reference_admission_granted': False,
        'unknowns_filled_or_household_AB_changed': False,
        'seconds': read(out/'COSTS.json') if (out/'COSTS.json').exists() else None,
        'remaining_evidence': read(out/'WORKFLOW.json')['remaining_evidence_gaps']}
    save(out / 'EXECUTION.json', result)
    print(request['request_id'], 'area', result['area_m2'], 'boundaries', result['boundaries'], 'native', result['native_component_life_checks_pass'], flush=True)


if __name__ == '__main__':
    p = argparse.ArgumentParser(); p.add_argument('--request', type=Path, required=True);p.add_argument('--finish',action='store_true')
    p.add_argument('--source', type=Path, required=True); p.add_argument('--out', type=Path, required=True)
    a = p.parse_args(); (finish if a.finish else execute)(a.request, a.source, a.out)
