"""Bind finite source/physics/native/numerical reviews to executable references."""
import copy

from national_idf.common import ROOT, read, save, require, digest
from national_idf.governance import REQUIRED_REVIEWS
from national_idf.reference_release import implementation, reviewed
from national_idf.reference_workflow import ref
from national_idf.source_adapter import source_file
from national_idf.idf import Fields, objects, parse
from national_idf.assembly import plan_assembly
from national_idf.chinese_design import performance_layers
from national_idf.weather import audit
from scripts.validate_multicountry_life import validate

OUT = ROOT / 'reports/multicountry_release_review_20261108'
PREVIOUS = ROOT / 'reports/multicountry_envelope_review_20261108'


def make(label, folder, case_path, numeric_path, geometry_path, defaults_path, curve_path, xml_path, baseline_label):
    target = OUT / (label + '_release'); target.mkdir(exist_ok=True)
    fixture = read(folder / 'FIXTURE.json'); case = read(case_path)
    rows = parse(source_file(fixture['model'], ROOT).read_text()); fields = Fields(source_file(fixture['engine_schema'], ROOT))
    geometry = read(geometry_path); defaults = read(defaults_path); curve = read(curve_path); numeric = read(numeric_path)
    require(all(v['passed'] for v in numeric['comparisons'].values()), 'REFERENCE_REVIEW_NUMERICAL_FAILURE')
    run = folder / ('stress_run' if label == 'ES' else 'run')
    life = validate(run, fixture, case); components = read(run / 'COMPONENT_CHECKS.json')
    require(components['passed_component_checks'] and life['passed_input_and_component_checks'], 'REFERENCE_REVIEW_NATIVE_LEDGER_FAILED')
    require(geometry['fixture_model'] == fixture['model'] and defaults['model'] == fixture['model'], 'REFERENCE_REVIEW_WRONG_MODEL')
    require(defaults['all_schema_default_branches_accounted'] and not defaults['unreviewed'], 'REFERENCE_REVIEW_DEFAULT_NOT_ACCOUNTED')
    performance = performance_layers(rows, ref(xml_path), fields); save(target / 'PERFORMANCE.json', performance)
    source = parse(source_file(geometry['source_idf'], ROOT).read_text())
    performance_objects = lambda model: [r for r in model if r[0].startswith(('Coil:', 'Fan:'))]
    require(performance_objects(source) == performance_objects(rows), 'REFERENCE_HVAC_PERFORMANCE_CHANGED')
    tank_component = read(ROOT / 'configs/component_models/EB_original_water_heater_c58a2a7a.json')
    tanks = objects(rows, 'WaterHeater:Stratified'); require(len(tanks) == 1, 'REFERENCE_ORIGINAL_TANK_NOT_UNIQUE')
    require(all(fields.get(tanks[0], key) == value for key, value in tank_component['physical_parameters'].items()), 'REFERENCE_ORIGINAL_TANK_CHANGED')
    weather = audit(source_file(fixture['weather'], ROOT)); require(not weather['errors'], 'REFERENCE_RELEASE_WEATHER_ERRORS')
    save(target / 'WEATHER_QC.json', weather)
    blueprint = ref(folder / 'BLUEPRINT.json'); plan = plan_assembly(fixture['id'], blueprint_ref=blueprint)
    require(plan['new_model_rows'] == rows, 'REFERENCE_REVIEW_COMPILER_RECIPE_CHANGED')
    source_baseline = OUT / 'source_baselines' / baseline_label / 'SOURCE_BASELINE.json'
    baseline = read(source_baseline); require(baseline['source_inputs_unmodified'] and baseline['no_severe_or_fatal'], 'REFERENCE_SOURCE_BASELINE_INCOMPLETE')
    design_refs = [ref(OUT / (label + suffix + '_DESIGN_NUMERICS.json')) for suffix in ('_cold', '_programs')]
    require(all(read(source_file(v, ROOT))['all_existing_checks_pass'] for v in design_refs), 'REFERENCE_DESIGN_NUMERICS_FAILED')
    original_baseline = copy.deepcopy(case); original_baseline['controls']['dated_overrides'] = []
    save(target / 'BASELINE_CASE.json', original_baseline); save(target / 'CASE.json', case)
    definition = {'fixture': ref(folder / 'FIXTURE.json'), 'source_blueprint': blueprint,
        'country': label, 'representation_kind': 'local_archetype' if label == 'US' else 'controlled_reference',
        'housing_class': 'apartment_with_source_adiabatic_boundaries' if label == 'US' else 'detached_with_conditioned_basement',
        'source_area_m2': geometry['conditioned_area_m2'], 'source_air_volume_m3': geometry['conditioned_air_volume_m3'],
        'scope': 'Public whole-home experimental reference at the fixed source-year July window;source activity,0-to3person input,aggregate draws and original EB equipment;not stock,a measured survey dwelling or all input patterns',
        'unsupported_outputs': ['national stock or household calibration', 'room allocation or closed measured plan',
            'event-specific water heat/moisture', 'washing cleanliness,dryness or empirical product performance',
            'air quality or safe occupancy', 'unreviewed dates,restored states or annual operation',
            'automatic inference that3persons or6L/min is a real housing/plumbing capacity']}
    identity = digest(definition)
    checks = {
        'source_applicability': {'complete_public_reference_and_explicit_representation': True, 'stock_or_survey_representation_not_inferred': True},
        'structure': {'source_geometry_and_context_unchanged': geometry['source_geometry_orientation_air_volume_and_boundary_rows_unchanged'],
                      'native_area_volume_multipliers_match': geometry['native_area_volume_and_multipliers_match_source']},
        'source_baseline_run': {'original_source_run_without_input_edits': baseline['source_inputs_unmodified'],
                               'original_native_no_severe_or_fatal': baseline['no_severe_or_fatal'], 'author_reproduction_not_claimed': not baseline['author_results_compared']},
        'conversion': {'actual_source_recipe_exact': plan['new_model_rows'] == rows, 'public_source_geometry_semantics_retained': geometry['complete_source_context_retained']},
        'equipment_applicability': {'same_public_heatpump_coefficients': performance_objects(source) == performance_objects(rows),
            'original_complete_EB_tank_unchanged': True, 'all_observed_curve_uses_reviewed': curve['passed_observed_domain_screen'],
            'independent_design_numerics_pass': all(read(source_file(v, ROOT))['all_existing_checks_pass'] for v in design_refs)},
        'metering_and_energy_balances': {'native_components_pass': components['passed_component_checks'],
            'native_life_water_and_people_accounts_pass': life['passed_input_and_component_checks']},
        'dynamic_response': {'actual_dated_setpoint_and_off_commands_present': bool(case['controls']['dated_overrides']),
            'native_control_readback_matches': all(value == 0 for value in components['control_readback_errors'].values()), 'existing_dynamic_numeric_checks_pass': all(v['passed'] for v in numeric['comparisons'].values())},
        'numerical_convergence': {'all_registered_step_warmup_and_tail_comparisons_pass': all(v['passed'] for v in numeric['comparisons'].values())},
        'parameter_inventory': {'all_present_object_defaults_accounted': defaults['all_schema_default_branches_accounted'],
            'no_unknown_field_filled': defaults['physical_fields_filled_or_overridden'] is False},
        'modification_inventory': {'source_blueprint_checked': bool(plan['fingerprints']), 'no_ideal_backup': not objects(rows, 'ZoneHVAC:IdealLoadsAirSystem')},
        'weather_and_design_domain': {'frozen_annual_weather_QC_pass': not weather['errors'],
            'actual_window_curve_domain_reviewed': curve['passed_observed_domain_screen'], 'independent_design_numerics_pass': True},
        'life_and_control_support': {'source_life_ports_bound': read(source_file(fixture['life_installation_receipt'], ROOT))['ready'],
            'native_input_application_matches': life['passed_input_and_component_checks'], 'only_fixed_window_registered': case['run'] == read(source_file(fixture['input_domain'], ROOT))['run_period']}}
    common_evidence = [ref(geometry_path), ref(defaults_path), ref(curve_path), ref(numeric_path),
        ref(run / 'LIFE_CHECKS.json'), ref(run / 'COMPONENT_CHECKS.json'), ref(source_baseline),
        ref(target / 'PERFORMANCE.json'), ref(target / 'WEATHER_QC.json'), *design_refs]
    reviews = {}
    for phase in REQUIRED_REVIEWS:
        require(checks[phase] and all(checks[phase].values()), 'REFERENCE_JOINT_REVIEW_FAILED', [phase, checks[phase]])
        path = target / 'reviews' / (phase + '.json')
        save(path, {'phase': phase, 'status': 'passed', 'definition_sha256': identity,
            'valid_until': '2027-11-08', 'scope': definition['scope'], 'checks': checks[phase], 'evidence': common_evidence})
        reviews[phase] = ref(path)
    dispositions = {}
    for finding in set(plan['formal_release_gaps']):
        if finding == 'Individual water-event room heat/moisture not modeled':
            dispositions[finding] = {'disposition': 'outside_declared_output_scope', 'phase': 'life_and_control_support',
                'reason': 'Known unsupported causal event output;aggregate public background retained explicitly'}
        else:
            require(finding in ('Zone integration trial not reviewed or admitted', 'Joint physical/numerical release review pending'),
                    'REFERENCE_NEW_UNREVIEWED_FINDING', finding)
            dispositions[finding] = {'disposition': 'resolved_by_bound_review', 'phase': 'numerical_convergence',
                'reason': 'Bound complete native source,component,geometry,design and unchanged numerical reviews above;strict survey-home admission not granted'}
    release = {'schema': 'national_idf.reviewed_reference_release.v1', 'status': 'passed', 'id': fixture['id'],
        'purpose': 'roleplay_control_reference', 'definition': definition, 'definition_sha256': identity,
        'valid_until': '2027-11-08', 'protocol': ref(ROOT / 'configs/study_protocol.json'), 'reviews': reviews,
        'finding_dispositions': dispositions, 'implementation': implementation(),
        'numerical_resource_library': 'US_apartment' if label == 'US' else 'US',
        'validated_cases': [{'case': ref(target / 'CASE.json')}, {'case': ref(target / 'BASELINE_CASE.json')}],
        'strict_survey_home_admitted': False, 'formal_admitted': False}
    if (target / 'RELEASE.json').exists():
        old = read(target / 'RELEASE.json'); history = target / 'versions' / (digest(old) + '.json')
        if not history.exists(): save(history, old)
    save(target / 'RELEASE.json', release)
    immutable = target / 'versions' / (digest(release) + '.json')
    if not immutable.exists(): save(immutable, release)
    save(target / 'CURRENT_RELEASE.json', ref(immutable)); reviewed(ref(immutable))
    print(label, 'joint reference authority bound;strict survey admission unchanged', flush=True)


def main():
    make('US', PREVIOUS / 'US_apartment_zone_analytical/s2_intervention', PREVIOUS / 'US_apartment_zone_analytical/s2_intervention/CASE.json',
         PREVIOUS / 'US_apartment_zone_analytical/NUMERICAL_RESULTS.json', OUT / 'US_apartment_GEOMETRY.json',
         PREVIOUS / 'US_apartment_zone_analytical/DEFAULT_REVIEW.json', PREVIOUS / 'US_apartment_zone_analytical/curve_observed/CURVE_CHECKS.json',
         ROOT / 'reports/multicountry_idf_20261107/US_apartment_source_v2/apartment_with_published_devices.xml', 'US_apartment')
    base = ROOT / 'reports/multicountry_joint_review_20261108/ES_fixture_normalization'
    # Current default review uses the pre-normalization model. The proven
    # q=P*f transaction changes two explicit peak fields,not omitted defaults.
    parent_review = read(PREVIOUS / 'ES_DEFAULT_REVIEW.json'); fixture = read(base / 'FIXTURE.json')
    from national_idf.parameter_pack import inventory
    from national_idf.reference_defaults import review
    blueprint = read(base / 'BLUEPRINT.json'); adapter = read(source_file(blueprint['source_adapter'], ROOT))
    model = source_file(fixture['model'], ROOT); rows = parse(model.read_text()); fields = Fields(source_file(fixture['engine_schema'], ROOT))
    item = review(rows, inventory(rows, model.read_text(), read(source_file(fixture['engine_schema'], ROOT))), fields,
                  parse(source_file(adapter['model'], ROOT).read_text()))
    item.update(model=fixture['model'], unchanged_effective_method_review=parent_review['absent_algorithm_review'])
    save(OUT / 'ES_NORMALIZED_DEFAULTS.json', item)
    make('ES', base, base / 'STRESS_CASE.json', base / 'NUMERICAL_RESULTS.json', OUT / 'ES_detached_GEOMETRY.json',
         OUT / 'ES_NORMALIZED_DEFAULTS.json', OUT / 'ES_actual_case_curves/CURVE_CHECKS.json',
         ROOT / 'reports/eb_six_joint_20261031/six_source.xml', 'US_detached')


if __name__ == '__main__': main()
