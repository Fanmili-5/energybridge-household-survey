# -*- coding: utf-8 -*-
"""One reproducible family -> housing -> life A -> B-plan project, without EP."""
import copy
import datetime as dt
import shutil
from collections import Counter, defaultdict
from pathlib import Path
from benchmark.ab_generation.common import bound, digest, read, save, seal, sha, verify
from benchmark.ab_generation.generate import generate
from benchmark.ab_generation.model import apply, control_issues
from benchmark.ab_generation.power import site_capacity
from benchmark.ab_generation.sampling import catalogue, command_hash, describe, interactions, sample_catalogue, validate_plan
from benchmark.family_generation.core import generate as generate_families
from benchmark.family_generation.connect import connect
from .context import plan_context

HERE = Path(__file__).parent
DEFAULT_INPUT = HERE / 'examples/project.json'
LABELS = {'washer': '洗衣机', 'dryer': '干衣机', 'dishwasher': '洗碗机', 'ac': '空调', 'water_heater': '储水式热水器', 'ev': '电动汽车'}
STAGES = ['family', 'housing', 'life_A', 'B_plans', 'static_checks']


def configuration(path):
    path = Path(path); c = read(path)
    if c['schema'] != 'eb.project.input.v1' or set(c) != {'schema', 'family_input', 'calendar', 'date', 'prefix', 'events', 'tariff', 'preview_plan'}:
        raise ValueError('UNKNOWN_PROJECT_CONFIGURATION')
    source = bound(HERE.parent, c['family_input']['path'])
    if sha(source) != c['family_input']['sha256']:
        raise ValueError('PROJECT_FAMILY_INPUT_CHANGED')
    validate_plan(c['preview_plan'])
    if len(c['preview_plan']['variants']) != 1:
        raise ValueError('PROJECT_PREVIEW_REQUIRES_ONE_DECLARED_VARIANT')
    if not dt.date.fromisoformat(c['calendar']['anchor']) < dt.date.fromisoformat(c['date']) < dt.date.fromisoformat(c['calendar']['end_exclusive']):
        raise ValueError('PROJECT_DATE_OUTSIDE_CALENDAR')
    return c, source


def prepare_families(c, source, out):
    batch = read(source); pool = read(bound(source.parent, batch['pool']['path']))
    if sha(bound(source.parent, batch['pool']['path'])) != batch['pool']['sha256']:
        raise ValueError('PROJECT_SOURCE_POOL_CHANGED')
    original = copy.deepcopy(pool)
    for template in pool['templates']:
        template['life'].update(c['calendar'])
        template['field_origins']['life'] += ';project-calendar-override-explicitly-declared-before-life-and-B'
    folder = out / 'inputs'; save(folder / 'ORIGINAL_POOL.json', original)
    save(folder / 'REFERENCE_POOL.json', pool)
    batch.update(prefix=c['prefix'], pool={'path': 'REFERENCE_POOL.json', 'sha256': sha(folder / 'REFERENCE_POOL.json')})
    save(folder / 'families.json', batch)
    save(folder / 'DERIVATION.json', {'original_family_input_sha256': sha(source), 'original_pool_sha256': digest(original),
        'calendar_override': c['calendar'], 'purpose': 'explicit calendar supplies 112-day preparation history and tail;not selected using B outcomes',
        'rosters_devices_rights_and_habits_changed': False, 'before_any_B_generation': True})
    return folder / 'families.json'


def display_plan(plan, lo=480, hi=1920):
    return {key: [{k: v for k, v in r.items() if k != '_ab_control_id'} for r in plan[key]
                  if r['end_min'] > lo and r['start_min'] < hi] for key in ('tasks', 'operations', 'controls')}


def preview(sample, c, result):
    override = sample['aliases'][0]['override']; singles = {r['id']: r for r in result['candidates']}
    if 'candidate_id' in override:
        request = singles[override['candidate_id']]; children = [request]
    elif 'joint_id' in override:
        request = next(r for r in result['joint_candidates'] if r['id'] == override['joint_id'])
        children = [singles[i] for i in request['candidate_ids']]
    else:
        request, children = {'patches': [], 'static_issues': []}, []
    B = apply(c['A'], request['patches'])
    features, issues = describe(c, B, children, list(request['static_issues']),
        unchanged=command_hash(B) == command_hash(c['A']), stress_admissions=[])
    extra = sorted(set(control_issues(c, B) + site_capacity(c, B)['issues']) - set(issues))
    if command_hash(B) != sample['B_commands_sha256'] or features != sample['features'] or issues != sample['static_issues'] or extra:
        raise ValueError('PROJECT_SELECTED_PLAN_AUDIT_MISMATCH')
    prediction = {key: sum(r['prediction'][key] for r in children)
                  if children and all(r['prediction'][key] is not None for r in children) else None
                  for key in ('delta_cost', 'aligned_event_kWh')}
    item = {'id': sample['sample_id'], 'category': sample['stratum'], 'features': features,
        'static_valid': not issues, 'static_issues': issues, 'full_plan_checked': True,
        'A': display_plan(c['A']), 'B': display_plan(B), 'factors': [r['factors'] for r in children],
        'evidence': [r['opportunity'] for r in children], 'prediction': prediction,
        'prediction_scope': 'task-chain/analytic-EV only where known;not actual full-household energy or bill',
        'physical_status': 'not_run', 'human_acceptance': None}
    pair = {'schema': 'eb.project.plan_pair.v1', 'household_id': c['household_id'], 'case_id': c['case_id'],
        'sample_id': sample['sample_id'], 'A': c['A'], 'B': B, 'needs_A': c['needs'], 'needs_B': c['needs'],
        'date': c['date'], 'events': c['events'], 'information_set': c['reference']['information_set'],
        'A_commands_sha256': command_hash(c['A']), 'B_commands_sha256': command_hash(B),
        'static_issues': issues, 'physical_status': 'not_run', 'human_acceptance': None}
    return item, pair


def build(input_path, out, progress=None):
    c, source = configuration(input_path)
    out = Path(out); out.mkdir(parents=True, exist_ok=False)
    emit = progress or (lambda stage, message: print(stage + ': ' + message, flush=True))
    save(out / 'INPUT.json', c)
    source_files = [HERE / 'pipeline.py', HERE / 'context.py'] + [f
                    for name in ('ab_generation', 'family_generation', 'housing_simulation')
                    for f in (HERE.parent / name).glob('*.py')]
    save(out / 'SOURCE_CODE.json', {'files': {str(f.relative_to(HERE.parent.parent)): sha(f) for f in sorted(source_files)},
        'purpose': 'generator-stage implementation bytes at build time;questionnaire adapter is pinned in its own release;not a physical or population validity claim'})
    family_input = prepare_families(c, source, out)
    emit('family', '生成固定公开家庭与实验角色')
    families = generate_families(family_input, out / 'families')
    emit('housing', '匹配住房、安装设备并生成完整生活A')
    connection = connect(out / 'families', out / 'connected')
    family_rows = {r['household_id']: r for r in families['records']}
    variant = c['preview_plan']['variants'][0]
    records, all_rows, contexts, views = [], [], {}, {}
    for row in connection['records']:
        hid = row['household_id']; record = dict(row)
        if row['status'] != 'A_constructed':
            records.append(record); continue
        emit('B_plans', '构造 ' + hid + ' 的计划候选；热状态未知项保持探索标签')
        try:
            family = read(out / 'families' / family_rows[hid]['path'])
            folder = out / 'connected/life_A' / hid
            life = read(bound(folder, read(folder / 'MANIFEST.json')['records'][0]['path']))
            world = read(folder / 'WORLD_INPUT.json')['households'][0]
            experiment = {'case_id': hid + '-' + c['date'], 'date': c['date'], 'events': c['events'], 'tariff': c['tariff']}
            context = plan_context(life, world, experiment, family_rows[hid]['sha256'])
            result = generate(context, variant['overrides'])
            save(out / 'contexts' / (hid + '.json.gz'), context)
            save(out / 'generated' / (hid + '.json.gz'), result)
            rows = catalogue({context['case_id']: context}, {variant['id']: {context['case_id']: result}}, stress_admissions=[])
            for request in rows:
                for alias in request['aliases']:
                    alias['household_id'] = hid
            all_rows.extend(rows); contexts[hid] = context
            layout = read(out / 'connected/shells' / hid / 'layout.json')
            views[hid] = {'id': hid, 'archetype': family['archetype'], 'role_title': family['archetype_definition']['title'],
                'facts': family['facts'], 'field_origins': family['field_origins'], 'members': world['members'],
                'devices': world['devices'], 'authority': context['authority'], 'date': c['date'],
                'events': context['events'], 'A': display_plan(context['A']),
                'calendars': life['days'][c['date']]['calendars'],
                'housing': {'rooms': layout['rooms'], 'access': layout['access'],
                    'outer_rect_m': layout['metric_outer_rect_m'], 'gross_area_m2': layout['whole_unit_building_area_m2'],
                    'usable_area_m2': layout['usable_total_area_m2'], 'source': 'declared_reference_geometry;not_surveyed_floorplan',
                    'shared_households': layout['shared_household_count_design'], 'shell_status': 'compiled', 'paired_idf_status': 'not_prepared'},
                'inventory': result['device_opportunity_inventory'], 'previews': [], 'physical_status': 'not_run'}
            record.update(status='plans_constructed', case_id=context['case_id'], candidates=len(result['candidates']),
                joints=len(result['joint_candidates']), catalogue_unique=len(rows),
                joint_generation_coverage=result['joint_search_coverage'], program_shift_domain=result['program_shift_domain'])
        except (ValueError, KeyError, TypeError) as error:
            record.update(status='B_generation_rejected', reason=str(error))
        records.append(record)
    emit('static_checks', '固定分层取样，并逐个核对完整A/B计划')
    selection = sample_catalogue(sorted(all_rows, key=lambda r: r['sample_id']), c['preview_plan'])
    grouped = defaultdict(list)
    for sample in selection['records']:
        grouped[sample['household_id']].append(sample)
    for hid, samples in grouped.items():
        result = read(out / 'generated' / (hid + '.json.gz'))
        for sample in samples:
            item, pair = preview(sample, contexts[hid], result)
            save(out / 'pairs' / (sample['sample_id'] + '.json'), pair)
            item['artifact'] = 'pairs/' + sample['sample_id'] + '.json'
            views[hid]['previews'].append(item)
    save(out / 'SELECTION.json', selection)
    coverage = {'strata': selection['coverage'], 'selection_coverage_passed': selection['selection_coverage_passed'],
        'catalogue_unique': len(all_rows), 'invalid_catalogue_retained': sum(r['features']['admission'] == 'static_diagnostic' for r in all_rows),
        'selected': len(selection['records']), 'interactions': interactions(all_rows, selection['records'], c['preview_plan']['coverage_axes']),
        'interpretation': 'six-household project preview;optional equipment strata may have deficits;not the frozen ten-stratum benchmark sample'}
    save(out / 'COVERAGE.json', coverage)
    frozen = read(HERE.parent / 'ab_generation/validation/gap_supplement/final_sample/RESULT.json')
    view = {'schema': 'eb.project.view.v1', 'title': 'EnergyBridge 三主线数据', 'scope': 'public_synthetic_plan_preview',
        'date': c['date'], 'seed': c['preview_plan']['seed'], 'households': list(views.values()), 'records': records,
        'stages': [{'id': name, 'status': 'complete' if len(views) == families['requested'] else 'partial_failures_retained'} for name in STAGES], 'coverage': coverage,
        'frozen_research_sample': {'separate_version': True, 'selected': frozen['selected'], 'strata': len(frozen['coverage']),
            'required_deficits': frozen['required_deficits'], 'interaction_covered': frozen['covered_interaction_levels'],
            'interaction_total': frozen['interaction_levels'], 'interaction_deficits': len(frozen['missing_interactions'])},
        'physical_status': 'not_run', 'new_engine_runs': 0, 'questionnaire_changed': False, 'master1000_started': False,
        'source': {'input_sha256': sha(input_path), 'component_versions': {'family': 'public-family-v1', 'AB': 'v3-plan-only-explicit', 'housing': '3.0.0'},
                   'calendar_override': c['calendar'], 'population_proportion_claim': False, 'human_labels_generated': 0}}
    save(out / 'VIEW.json', view)
    summary = {'schema': 'eb.project.output.v1', 'requested': families['requested'], 'records': records,
        'constructed': len(views), 'selected_previews': len(selection['records']),
        'all_slots_accounted': len(records) == families['requested'], 'new_engine_runs': 0,
        'same_household_identity_preserved': True, 'human_labels_generated': 0}
    save(out / 'SUMMARY.json', summary)
    seal(out, {'schema': 'eb.project.output.v1', 'input_sha256': sha(input_path), 'new_engine_runs': 0})
    emit('complete', '项目构建完成；所有失败与缺额原样保留')
    return summary


def check(folder):
    folder = Path(folder); manifest = verify(folder)
    if manifest['schema'] != 'eb.project.output.v1':
        raise ValueError('PROJECT_OUTPUT_REQUIRED')
    summary = read(folder / 'SUMMARY.json'); view = read(folder / 'VIEW.json')
    if not summary['all_slots_accounted'] or summary['new_engine_runs'] or view['new_engine_runs']:
        raise ValueError('PROJECT_SLOT_OR_NO_ENGINE_CONTRACT_FAILED')
    for household in view['households']:
        hid = household['id']; context = read(folder / 'contexts' / (hid + '.json.gz'))
        if context['household_id'] != hid or context['reference']['thermal']:
            raise ValueError('PROJECT_IDENTITY_OR_STATE_BOUNDARY_FAILED')
        for sample in household['previews']:
            pair = read(bound(folder, sample['artifact']))
            if (pair['household_id'] != hid or pair['case_id'] != context['case_id'] or pair['sample_id'] != sample['id']
                    or pair['A_commands_sha256'] != command_hash(context['A'])
                    or pair['A_commands_sha256'] != command_hash(pair['A'])
                    or pair['B_commands_sha256'] != command_hash(pair['B'])):
                raise ValueError('PROJECT_PLAN_PAIR_BINDING_FAILED')
    return {'passed': True, 'requested': summary['requested'], 'constructed': summary['constructed'],
            'previews': summary['selected_previews'], 'new_engine_runs': 0}
