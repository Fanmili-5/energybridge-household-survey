#!/usr/bin/env python3
"""Materialize a complete production design and1000 diagnostic routing rows.

No household facts, physical models, answers or recruitment are generated.
"""
import collections
import hashlib
import json
from pathlib import Path

OUT = Path(__file__).resolve().parent.parent
H = OUT.parent
BASE = H / 'production_route_v5_20261004/housing1000/HOUSEHOLDS1000.json'


def sha(p):
    return hashlib.sha256(p.read_bytes()).hexdigest()


def save(name, value):
    (OUT / name).write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + '\n')


def main():
    definitions = [
        ('FRAME', [], ['census2020'], '总体和1000配额', 'TARGET1000.json', '全城市或城市普通住宅；配额分母一致，结构性不适用不能伪造'),
        ('REFERENCES', ['FRAME'], ['chfs2021', 'crecs2012', 'census2020'], '同源联合条件参考、缺失与迁移规则', 'CONDITIONAL_REFERENCES.json', '概率/来源/回退完整，私有调查记录不直接复制'),
        ('FAMILY', ['REFERENCES'], ['chfs2021', 'crecs2012'], '联合生成关系图、年龄、就业/上学、经济与同住范围', 'ROLE.json', '关系、年龄、N/G一致；不能先固定随机年龄再强補关系'),
        ('HOUSING', ['FAMILY'], ['census2020', 'chfs2021'], '同权属占用范围生成住房、H6/H7和设施；明确顶码实验确数', 'HOUSING_ANCHORS.json', '独用、共用、整套及面积口径分开，缺观察不冒充观察'),
        ('CONTEXT', ['HOUSING'], ['dest2023', 'EPW'], '地点、气候、户位、时间、控制及计量情境', 'WORLD.json', '具体实验地点不冒充真实住所；EPW与时钟一致'),
        ('LAYOUT', ['CONTEXT'], ['dest2023', 'xia2025', 'iea68'], '源拓扑加受约束房间尺度、门窗、睡位、设备位置重建', 'LAYOUT.json', 'H7、面积、通路、功能及私有/共用边界闭合'),
        ('ENVELOPE', ['LAYOUT'], ['dest2023', 'ma2022', 'energyplus24'], '构造、外墙暴露、楼层、邻户、窗与通风参数匹配', 'ENVELOPE.json', '不凭城市/最近年份标签宣称物理匹配'),
        ('ASSETS', ['ENVELOPE'], ['chfs2021', 'crecs2012', 'energyplus24', 'manufacturer'], 'CHFS C8001ab组拥有/价值约束+历史细类条件组合；唯一硬件、服务、性能、操作者、电表', 'ASSETS.json', '组拥有不等于单个设备/台数/安装；容量与电功率区分，实例不重复'),
        ('ACTIVITY', ['ASSETS'], ['timeuse2018', 'fu2022', 'liu2023'], '受约束协调日程、需求、任务与初始状态', 'A_OPERATIONS.json', '24小时、工作学校照护与设备资源均一致'),
        ('IDF', ['ACTIVITY'], ['energyplus24'], '编译几何、设备、得热、HVAC、热水、邻户与电表', 'PHYSICS_BINDING.json', '所有模型对象绑定同一角色世界；无住所仅全城市合同允许不适用'),
        ('BASELINE', ['IDF'], ['energyplus24'], '年度基线及分项能量、事件前历史、服务与状态读回', 'A_RESULTS.json', '运行与能量/服务验证；模拟不是实际家庭观测'),
        ('EVENTS', ['BASELINE'], ['benchmark_contract'], '已有任务和权限下生成十轮提议，同前史A/B与反弹验证', 'ROUNDS10.json', '无虚构设备/任务，非执行题不编节能数，B′单列'),
        ('ACTOR', ['EVENTS'], ['benchmark_contract'], '统一对象投影完整角色卡，理解试点与展示一致验证', 'ACTOR_CARD.md', '所有必需角色事实具体，没有预造回答或待补占位'),
        ('FREEZE', ['ACTOR'], ['benchmark_contract'], '分组留出、1000包和来源/输出哈希冻结', 'DATASET1000_MANIFEST.json', '全1000验收，答案只由真人采集产生')]
    stages = [{'id': str(n + 1).zfill(2) + '_' + key, 'key': key, 'parents': parents, 'sources': sources,
               'method': method, 'output': output, 'completion_gate': gate, 'implementation_state': 'planned_full_factory'}
              for n, (key, parents, sources, method, output, gate) in enumerate(definitions)]
    recipes = {
        'owned_private': {'completion': '自有分支条件参考→完整空间→私有系统与控制→日程和物理', 'endpoint': 'residential_IDF'},
        'rented_private': {'completion': '租赁C1004→H7缺关联模型及变体→整租使用/权限安排→完整住宅工厂', 'endpoint': 'residential_IDF'},
        'owned_shared': {'completion': '整套户型→实验共享人数及背景住户→独用/共用分区→H6推导与独立计量→共享控制', 'endpoint': 'shared_world_IDF_and_household_meter'},
        'rented_shared': {'completion': '2/3/4+合租实验确数→C1004共用包含解释变体→分区及H6→服务预约/控制/电表', 'endpoint': 'shared_world_IDF_and_household_meter'},
        'ordinary_other_source': {'completion': '保留来源类别→有调查支撑的免费/借住/单位使用情境→实际使用和权限补全→完整住宅', 'endpoint': 'residential_or_shared_world_IDF'},
        'nonordinary_city_family': {'completion': '按H5定义生产宿舍/工作地/其他住所/无住所情境变体，不填未知全国细分比例',
                                     'endpoint': 'accommodation_IDF_or_explicit_no_residence_service_case',
                                     'strict_residential_scope': 'rebuild_entire1000ordinary_cohort_from_correct_frame_not_relabel52'}}
    required = {
        'ROLE.json': ['role_id', 'profile_version', 'reference_date', 'resident_member_ids', 'members_age_sex', 'role_kinship_graph', 'occupation_school_state', 'resident_economic_crosswalk', 'budget', 'care_and_family_rules'],
        'WORLD.json': ['world_id', 'experiment_site', 'statistical_anchor_refs', 'declared_imputations', 'housing_use_arrangement', 'shared_background_households', 'household_unit_area_scopes', 'independent_rooms', 'unit_neighbors', 'calendar_weather', 'service_permissions', 'billing_rule'],
        'LAYOUT.json': ['source_reconstruction_version', 'rooms_function_polygons', 'H7_counting_mask', 'doors_access_graph', 'private_shared_partition', 'member_sleep_activity_locations', 'asset_locations', 'walls_windows_peers', 'area_conservation'],
        'ENVELOPE.json': ['physics_source_hashes', 'layers_and_glazing', 'era_interpretation', 'orientation_exposure', 'floor_roof_party_boundaries', 'airflow_and_ground_context', 'transport_assumptions'],
        'ASSETS.json': ['unique_asset_hardware_ids', 'classes_services', 'ownership_installed_operable_control_states', 'operators', 'permission_conditions', 'functional_zones', 'performance_or_program_model', 'electric_input_vs_capacity', 'meter_scope'],
        'A_OPERATIONS.json': ['household_coordinated_schedule', 'service_demand', 'tasks_assets', 'release_duration_deadline', 'initial_state', 'materials_prerequisites', 'legal_window', 'clock_resolution'],
        'PHYSICS_BINDING.json': ['role_world_layout_asset_operations_hashes', 'IDF_or_structural_NA_manifest', 'weather_hash', 'engine_version', 'service_model_versions', 'meter_reporting_contract', 'input_validation'],
        'A_RESULTS.json': ['case_id', 'output_hash', 'annual_meter_enduses', 'event_history_state', 'thermal_water_service', 'unmet_service', 'simulated_not_measured_scope'],
        'ROUNDS10.json': ['round_ids10', 'role_world_hashes', 'event_context', 'baseline_task_ref', 'proposal_Bprime_versions', 'actionability_applicability', 'paired_prefix_proof', 'physical_service_rebound_or_NA', 'display_hashes', 'human_answers_null_before_collection'],
        'ACTOR_CARD.md': ['complete_readable_role_facts', 'housing_space', 'assigned_devices_control', 'daily_schedule_requirements', 'consistent_displays', 'no_internal_pending_fields', 'no_preassigned_answers'],
        'EVIDENCE.json': ['source_years_scopes', 'observed_reference_modeled_design_derived_status', 'conditional_models_parameters', 'transport', 'shared_topcode_other_source_choices', 'sensitivity_worlds', 'scientific_claim_scope'],
        'QA.json': ['population_margin_residuals', 'kinship_age_NG', 'geometry_access_function', 'asset_service_meter_rights', 'activity_resources', 'engine_energy_service', 'AB_prefix', 'display_identity', 'source_output_integrity']}
    profiles = json.loads(BASE.read_text())['profiles']
    rows, counts = [], collections.Counter()
    for p in profiles:
        h = p['housing']
        t, scope = h['current_tenure_model'], h['occupancy_scope']
        recipe = ('nonordinary_city_family' if not h['H5_is_ordinary_model_assigned'] else
                  'ordinary_other_source' if t is None else
                  ('owned_' if t == 'owned' else 'rented_') + ('shared' if scope == 'shared_household' else 'private'))
        counts[recipe] += 1
        gaps = ['kinship_occupation_economic_scope', 'site_world_context', 'functional_layout_door_access', 'exposure_envelope',
                'H6_geometry_bridge_H7_semantics', 'assets_services_operators_meters', 'coordinated_activity_initial_state', 'annual_A', 'rounds10_A_B', 'actor_packet']
        if h['H6_building_area_m2'] is None and h['H5_is_ordinary_model_assigned']:
            gaps.append('household_H6_components')
        if h['H7_census_bin'] == '5+':
            gaps.append('H7_exact_tail_design')
        rows.append({'slot_id': p['slot_id'], 'input_profile_sha256': hashlib.sha256(json.dumps(p, ensure_ascii=False, sort_keys=True, separators=(',', ':')).encode()).hexdigest(),
                     'province': p['province'], 'N_bin': p['size_category'], 'G_bin': p['generation_category'],
                     'completion_recipe': recipe, 'recipe_ref': 'PIPELINE_SPEC.json#/recipes/' + recipe,
                     'required_stage_ids': [s['id'] for s in stages], 'gaps_with_handlers': gaps,
                     'package_contract': 'ROLE_PACKAGE_CONTRACT.json', 'status': 'planned_route_complete_not_materialized_role', 'human_answers': None})
    handlers = {
        'kinship_occupation_economic_scope': {'stage': 'FAMILY', 'rule': '同源粗化关系模式和出生年龄联合抽样；以N/G、亲属图和就业/学校约束校验；经济范围另列；不从世代直接编父子'},
        'site_world_context': {'stage': 'CONTEXT', 'rule': '省内气候/地点来源对照；有目标权重则校准，缺权重则明确实验地点及省内暴露变体'},
        'functional_layout_door_access': {'stage': 'LAYOUT', 'rule': '源平面语义分组或受约束重建；具体设计门通路并验证，重建状态不冒充原图观察'},
        'exposure_envelope': {'stage': 'ENVELOPE', 'rule': '注册构造及户位边界联合选择；没有真实年代参数时明示参考热工情境并做敏感性'},
        'H6_geometry_bridge_H7_semantics': {'stage': 'LAYOUT', 'rule': '统计建筑面积、热区净面积、楼宇公摊分别桥接；起居室/厅及复合睡居空间明确计数，不能取热区总数当H7'},
        'assets_services_operators_meters': {'stage': 'ASSETS', 'rule': 'CHFS C8001ab组级现代拥有/价值约束+CRECS历史细类条件参考；具体类型/安装/服务潜变量联合补全；权限缺证据作固定实验条件而非全国频率'},
        'coordinated_activity_initial_state': {'stage': 'ACTIVITY', 'rule': '时间预算和家庭资源约束下生成日程、任务与初态；缺日记时不伪造观察轨迹'},
        'annual_A': {'stage': 'BASELINE', 'rule': '统一角色世界编译，全年基线仿真后读回服务与电表'},
        'rounds10_A_B': {'stage': 'EVENTS', 'rule': '从已有合法任务/协商/无动作路径选十轮情境，核同前史、服务和恢复期；无执行量则不给节能标签'},
        'actor_packet': {'stage': 'ACTOR', 'rule': '从完成的角色世界生成演员卡和展示；所有演员必要事实确定、原始未知留在证据层'},
        'household_H6_components': {'stage': 'HOUSING', 'rule': '以完整分区求独用+共用/户数；C1004是否含共用分摊采用λ=0与1解释变体，不能称λ被源问卷识别'},
        'H7_exact_tail_design': {'stage': 'HOUSING', 'rule': '5+下按声明尾部参考选择实验确数；租赁尾部无观测关联时用下限/替代尾部情境，并保留顶码原锚点'}}
    spec = {'schema': 'eb.end_to_end1000.production_plan.v1', 'plan_id': 'END_TO_END1000_20261004', 'planning_only': True,
            'input_diagnostic_cohort_sha256': sha(BASE), 'population_scope': {'current': 'China_city_family_households_only',
                'recommended_if1000residential_IDFs_required': 'China_city_ordinary_residence_family_households_only',
                'town_rural_excluded': True, 'reference_year': 2020, 'scope_not_silently_changed': True,
                'ordinary_frame_requires_new_allocation': True, 'existing_under20_singleton_gate_not_changed': True},
            'generation_policy': {'whole_cohort_regeneration_allowed': True, 'old_candidates_are_diagnostics_not_fixed_ages_housing': True,
                'statistical_anchors_and_complete_experiment_world_separate': True, 'all_required_actor_values_materialized_before_release': True,
                'source_missingness_never_relabelled_as_observation': True, 'known_margin_constraints_precede_template_selection': True,
                'repair_does_not_drop_slots': True, 'unidentified_joint': 'declared_entropy_completion_and_feasible_dependence_variants',
                'unsupported_national_device_or_H5_subtype_rates_invented': False}, 'stages': stages, 'recipes': recipes, 'gap_completion_handlers': handlers,
            'current_diagnostic_route_counts': dict(counts), 'artifact_files': list(required),
            'compute_contract': {'naive_annual1000baseline_plus10branches_upper_bound': 11000,
                'performance_budget': 'measure_on_path_covering_pilot', 'reuse': 'exact_full_input_hash_only',
                'paired_state': 'same_annual_prefix_then_event_change;pre_event_readback_must_match', 'outputs_are_simulated_not_measured': True},
            'release': {'collection_release': False, 'training_release': False, 'plan_coverage_is_not_execution_success': True}}
    save('PIPELINE_SPEC.json', spec)
    save('PLANNED_ROUTES1000.json', {'schema': 'eb.plan_household_routes.v1', 'input_file': str(BASE), 'input_sha256': sha(BASE),
         'rows': rows, 'route_counts': dict(counts), 'planned_routes': len(rows), 'materialized_actor_ready_roles': 0,
         'counts_are_not_new_population_frequency_targets': True})
    save('ROLE_PACKAGE_CONTRACT.json', {'schema': 'eb.complete_role_package.contract.v1', 'files_required': required,
         'completion': 'all applicable required values concrete and provenance-bound;raw unknowns remain in evidence;structural_NA only by explicit scope',
         'strict_residential1000': '1000 validated residential/shared housing model bindings;no no_residence substitute',
         'all_city1000': '1000 complete roles;no_residence has external service case;unknown H5 mixtures evaluated as contexts,not arbitrary stock rates',
         'collection_release': False, 'training_release': False})
    print(json.dumps({'planned_routes': len(rows), 'counts': dict(counts), 'stages': len(stages), 'required_files': len(required), 'new_actor_ready_roles': 0}, ensure_ascii=False))


if __name__ == '__main__':
    main()
