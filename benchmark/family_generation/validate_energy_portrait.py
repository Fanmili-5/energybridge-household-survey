"""Small, reproducible local audit. Never starts EnergyPlus or deploys."""
import argparse
import copy
from collections import defaultdict
import json
from pathlib import Path

from .core import HERE, digest, read, require, save, sha, verify
from .energy_portrait import RULES, SOURCE_LOCK, build_portraits, compile_portrait, device_line
from .portrait_inputs import from_reference
from .device_persona import RULES as PERSONA_RULES, generate_personas


def validate(output, reference_root=None):
    root = Path(output).resolve(); root.mkdir(parents=True, exist_ok=False)
    fixture = HERE / 'examples/energy_portrait/input.json'
    before = sha(fixture); inputs = read(fixture); contexts = inputs['households']
    source_check = {'checked': False, 'reason': 'optional historical reference root not supplied'}
    receipt_file = read(HERE / 'examples/energy_portrait/SOURCE_RECEIPTS.json')
    receipts = receipt_file['records']
    habit_receipts = {r['household_id']: r['packets'] for r in receipt_file['household_calendar_contexts']}
    if reference_root is not None:
        source = Path(reference_root).resolve(); grouped = defaultdict(list)
        for row in receipts:
            for key, field in [('packet_source_path', 'packet_sha256_before'), ('profile_source_path', 'profile_sha256_before')]:
                path = (source / row[key]).resolve()
                require(path.is_relative_to(source) and sha(path) == row[field], 'REFERENCE_INPUT_CHANGED:' + row[key])
            grouped[row['household_id']].append(row)
        rebuilt = []
        for rows in grouped.values():
            row = rows[0]
            for packet in habit_receipts[row['household_id']]:
                require(sha(source / packet['path']) == packet['sha256'], 'HABIT_CALENDAR_SOURCE_CHANGED')
            rebuilt.append(from_reference(read(source / row['profile_source_path']),
                                          [read(source / r['packet_source_path']) for r in rows], row['role'],
                                          habit_packets=[read(source / p['path']) for p in habit_receipts[row['household_id']]]))
        require(rebuilt == contexts, 'FROZEN_CONTEXT_DOES_NOT_MATCH_ORIGINAL_A_AND_CALENDARS')
        source_check = {'checked': True, 'unique_profiles': len(grouped), 'dated_packets': len(receipts),
                        'habit_calendar_packets': sum(len(v) for v in habit_receipts.values()),
                        'all_hashes_match_before_and_after': True, 'rebuilt_contexts_equal_frozen_fixture': True}
    one = build_portraits(fixture, root / 'run1'); two = build_portraits(fixture, root / 'run2')
    require(one['compiled'] == one['requested'] == 7, 'EXPECTED_SEVEN_SMALL_REFERENCE_HOUSEHOLDS')
    require(one == two and read(root / 'run1/MANIFEST.json') == read(root / 'run2/MANIFEST.json'), 'NOT_BYTE_REPRODUCIBLE')
    verify(root / 'run1'); verify(root / 'run2')
    checks = []
    for c in contexts:
        p = compile_portrait(c)
        flat = [s for d in p['devices'] for s in d['requirements']]
        require(p['existing_days'] == c['days'] and sorted(flat, key=lambda s: s['need_id']) == sorted(c['services'], key=lambda s: s['need_id']),
                'SOURCE_CONTEXT_CHANGED')
        require(p['existing_policy'] == c['existing_policy'] and p['human_acceptance'] is None, 'POLICY_OR_LABEL_CHANGED')
        require(not p['source_calendar_or_A_modified'] and not p['B_outcomes_or_answers_used'], 'UNAUTHORIZED_INPUT_USE')
        counterfactual = copy.deepcopy(c); counterfactual['services'] = []
        counterfactual['plans'] = {'A': 'arbitrary A', 'B': 'arbitrary B'}
        counterfactual['answers'] = {'score': 5}; counterfactual['VPP'] = {'start': 'arbitrary'}
        require(generate_personas(counterfactual) == p['family_device_profile'], 'PROFILE_DEPENDS_ON_A_OR_ANSWERS')
        for device in p['devices']:
            require(device['habit'] in p['participant_family_text'] and
                    device['adjustment_preference'] in p['participant_family_text'] and
                    device['authorization']['narrative'] in p['participant_family_text'], 'PARTICIPANT_FIELDS_NOT_RENDERED')
        checks.append({'household_id': c['household_id'], 'role': c['role'], 'dates': [d['date'] for d in c['days']],
                       'requirements_preserved': len(flat), 'warnings_retained': p['warnings'],
                       'context_sha256': digest(c), 'calendar_A_and_policy_conserved': True,
                       'preference_independent_of_A_B_answers_and_VPP': True,
                       'household_calendar_days': len(c['habit_days']),
                       'all_habits_preferences_and_authorizations_rendered': True,
                       'device_rule_coverage': [{'asset_id': d['asset_id'], 'kind': d['kind'], 'rules': d['persona_rule_ids'],
                                                 'authorization_mode': d['authorization']['mode']} for d in p['devices']]})
    require(sha(fixture) == before, 'FROZEN_INPUT_CHANGED')
    if reference_root is not None:
        for row in receipts:
            require(sha(source / row['packet_source_path']) == row['packet_sha256_before'] and
                    sha(source / row['profile_source_path']) == row['profile_sha256_before'], 'REFERENCE_CHANGED_AFTER_BUILD')
        for packets in habit_receipts.values():
            for p in packets:
                require(sha(source / p['path']) == p['sha256'], 'HABIT_SOURCE_CHANGED_AFTER_BUILD')
    report = {'schema': 'eb.energy_portrait.validation.v2', 'date': '2026-10-20', 'passed': True,
              'households': 7, 'existing_date_slices': sum(len(c['days']) for c in contexts),
              'existing_household_calendar_days': sum(len(c['habit_days']) for c in contexts),
              'roles': sorted({c['role'] for c in contexts}), 'byte_reproducible': True,
              'input_sha256': before, 'rules_sha256': sha(RULES), 'source_lock_sha256': sha(SOURCE_LOCK),
              'device_persona_rules_sha256': sha(PERSONA_RULES),
              'source_reference_check': source_check, 'records': checks, 'EP_runs': 0,
              'existing_households_or_A_modified': False, 'online_changed': False,
              'population1000_started': False, 'human_preferences_validated': False}
    save(root / 'REPORT.json', report)
    lines = ['# v2：两户同为A类的家庭资料', '',
             '以下直接取自生成的受访者简版字段；完整逐设备资料包含习惯、调整偏好、动作授权及来源。两户均未改日程或A。', '']
    for hid in ('ordinary-v6-0653', 'ordinary-v6-0250'):
        c = next(c for c in contexts if c['household_id'] == hid); p = compile_portrait(c)
        lines += [f'## {hid}', '', p['participant_family_brief'].strip(), '']
    lines += ['六类取舍和原设备DR标志沿用EB；洗烘协调、照护操作负担、房间休息优先与逐动作授权边界是基于既有家庭/日历的明确实验设定，不声称从这些家庭测得。',
              'v1只整理原安排与通用态度；v2的家庭习惯生成函数不读取A/B动作，且已逐项渲染到受访者家庭资料。',
              '两户均为A类，先确认这一原则保持相同；不为了制造授权差异把其中一户改成自动执行。',
              '完整阅读版在 run1/portraits/*.family.md，简版在 *.brief.md，带来源与原日程/A核对信息的记录在 *.json。线上未改，未计算新后果。']
    (root / 'BEFORE_AFTER.md').write_text('\n'.join(lines) + '\n', encoding='utf-8')
    return report


if __name__ == '__main__':
    parser = argparse.ArgumentParser(); parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--reference-root', type=Path)
    args = parser.parse_args(); result = validate(args.out, args.reference_root)
    print(json.dumps({k: result[k] for k in ('passed', 'households', 'existing_date_slices', 'roles', 'EP_runs', 'online_changed')}, ensure_ascii=False))
