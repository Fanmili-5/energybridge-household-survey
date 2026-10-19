"""Read-only audit of authorized historical household worlds, never simulations."""
import argparse
from collections import Counter
import json
from pathlib import Path
from .core import digest, read, save, sha


def audit(stage):
    stage = Path(stage).resolve(); binding = stage / 'WORLD_BINDINGS1000.json'
    entries = read(binding)['records']; errors = []; reviews = []
    seen_hid = set(); global_members = set(); counts = Counter()
    for row in entries:
        path = (stage / row['world_path']).resolve()
        if not path.is_relative_to(stage) or not path.is_file() or sha(path) != row['world_sha256']:
            errors.append({'household_id': row['household_id'], 'code': 'SOURCE_WORLD_HASH_OR_PATH'}); continue
        before = sha(path); w = read(path); hid = w['household_id']; members = w['members']
        mids = [m['member_id'] for m in members]; by = {m['member_id']: m for m in members}
        rooms = {r['room_id']: r for r in w['layout']['rooms']}; devices = w['parameter_pack']['devices']
        def check(ok, code):
            if not ok: errors.append({'household_id': hid, 'code': code})
        check(hid == row['household_id'] and hid not in seen_hid, 'HOUSEHOLD_ID'); seen_hid.add(hid)
        check(len(members) == w['N'] and len(set(mids)) == len(mids), 'MEMBER_COUNT_OR_ID')
        check(not (set(mids) & global_members), 'GLOBAL_MEMBER_ID'); global_members.update(mids)
        check(len({m['generation_level'] for m in members}) == w['G'], 'GENERATION_COUNT')
        check(all(type(m['age_years']) is int and 0 <= m['age_years'] <= 120 for m in members), 'AGE_RANGE')
        check(all(m['reference_home_room_id'] in rooms and hid in rooms[m['reference_home_room_id']]['using_household_ids'] for m in members), 'SLEEP_ROOM_ACCESS')
        check(len({d['asset_id'] for d in devices}) == len(devices), 'ASSET_ID')
        kinds = {k for d in devices for k in d['types']}
        check('ac' in kinds and 4 <= len(kinds) <= 6, 'DEVICE_CLASS_COVERAGE')
        # An EV bay is intentionally outside the dwelling's thermal-room list.
        check(all(d['room_id'] in rooms for d in devices if 'ev' not in d['types']), 'INDOOR_ASSET_ROOM')
        for kind, asset in w['assets'].items():
            check(set(asset['asset_ids']) == {d['asset_id'] for d in devices if kind in d['types']}, 'ASSET_REGISTRY')
        for edge in w['ego_relationships']:
            a, b = edge['subject'], edge['object']
            check(a in by and b in by and a != b, 'RELATION_ENDPOINT')
            if a in by and b in by and edge['type'] == 'parent_of' and by[a]['age_years'] - by[b]['age_years'] < 15:
                reviews.append({'household_id': hid, 'code': 'PARENT_RELATION_AGE_SUBTYPE_REVIEW',
                                'note': 'Review threshold15 is a reference rule,not proof of biological parentage error;do not invent a step/adoption subtype'})
        ac = Counter(d['room_id'] for d in devices if 'ac' in d['types'])
        if any(n > 1 for n in ac.values()):
            reviews.append({'household_id': hid, 'code': 'CURRENT_KERNEL_MULTIPLE_AC_ZONE_UNSUPPORTED'})
        counts['explicit_nonresident_guardian_households'] += int(not any(m['age_years'] >= 18 for m in members))
        counts['under6_households'] += int(any(m['age_years'] < 6 for m in members))
        check(sha(path) == before, 'SOURCE_CHANGED_DURING_READ')
    return {'schema': 'eb.family_generation.legacy_audit.v1', 'households': len(entries),
            'binding_sha256': sha(binding), 'source_files_read_only': True, 'structural_errors': errors,
            'review_flags': reviews, 'review_counts': dict(Counter(r['code'] for r in reviews)),
            'context_counts': dict(counts), 'production_changes': False, 'EP_runs': 0,
            'scope': 'Historical master facts and device/relationship consistency;not housing feasibility,all life days or physical/human validity'}


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__); p.add_argument('--stage', type=Path, required=True); p.add_argument('--out', type=Path, required=True)
    args = p.parse_args()
    if args.out.resolve().is_relative_to(args.stage.resolve()):
        raise ValueError('Audit output must be outside the protected source stage')
    result = audit(args.stage); save(args.out, result)
    print(json.dumps({k: v for k, v in result.items() if k not in ('structural_errors', 'review_flags')}))
