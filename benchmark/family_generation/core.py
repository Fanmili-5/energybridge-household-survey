"""Build declared family scenarios; no inference of preferences or human labels."""
from collections import Counter
import copy
import hashlib
import json
from pathlib import Path
import re

from benchmark.household_archetypes.allocate import largest_remainder

HERE = Path(__file__).resolve().parent
ROLES = tuple('ABCDEF')
KINDS = {'ac', 'washer', 'dryer', 'dishwasher', 'water_heater', 'ev'}


def require(ok, reason):
    if not ok:
        raise ValueError(reason)


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False,
                                    allow_nan=False, separators=(',', ':')).encode()).hexdigest()


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def read(path):
    def invalid(v):
        raise ValueError('NONFINITE_JSON:' + v)
    value = json.loads(Path(path).read_text(), parse_constant=invalid)
    # JSON can overflow to infinity even without a NaN/Infinity literal.
    digest(value)
    return value


def save(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, sort_keys=True, ensure_ascii=False,
                               allow_nan=False, indent=2) + '\n')


def indexed(rows, key):
    require(isinstance(rows, list) and bool(rows), 'EMPTY_' + key)
    result = {r[key]: r for r in rows}
    require(len(result) == len(rows), 'DUPLICATE_' + key)
    require(all(isinstance(k, str) and re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.-]{0,120}', k)
                for k in result), 'UNSAFE_' + key)
    return result


def fixed_roster(before, after):
    """ID-keyed conservation: never zip unequal or reordered resident lists."""
    a, b = indexed(before, 'member_id'), indexed(after, 'member_id')
    require(set(a) == set(b), 'ROSTER_MEMBERS_ADDED_OR_REMOVED')
    for mid in a:
        require(a[mid] == b[mid], 'ROSTER_FACT_CHANGED:' + mid)
    return True


def validate_template(t):
    """Validate facts before role assignment, geometry or scheduling can alter them."""
    require(t['evidence_kind'] in ('declared_synthetic_scenario', 'authorized_joint_source_reference'), 'UNKNOWN_SOURCE_KIND')
    require(bool(t['source_reference']) and bool(t['template_id']), 'SOURCE_REFERENCE_REQUIRED')
    require(set(t['field_origins']) == {'roster', 'relationships', 'housing', 'devices', 'permissions', 'life'}, 'FIELD_ORIGINS_REQUIRED')
    require(all(isinstance(v, str) and v for v in t['field_origins'].values()), 'EMPTY_FIELD_ORIGIN')
    world, life, facts, shell = (t[k] for k in ('world', 'life', 'facts', 'shell'))
    target = world['household_id']
    require(target == life['household_id'] == shell['household_id'], 'HOUSEHOLD_IDENTITY_MISMATCH')
    members = indexed(world['members'], 'member_id')
    fm = indexed(facts['members'], 'member_id')
    require(set(fm) == set(members), 'FACT_AND_PHYSICAL_ROSTER_MISMATCH')
    for mid, m in members.items():
        f = fm[mid]
        require(type(m['age_years']) is int and 0 <= m['age_years'] <= 120, 'INVALID_AGE')
        require(f['age_years'] == m['age_years'] and f['household_id'] == m['household_id'], 'AGE_OR_OWNER_MISMATCH')
        require(f['sex'] in ('male', 'female', 'unknown'), 'INVALID_SEX')
        require(f['employment_status'] in ('has_work', 'no_work', 'unknown'), 'INVALID_EMPLOYMENT')
        require(type(f['generation_level']) is int, 'INVALID_GENERATION')
    require(set(life['member_calendars']) == set(members), 'ALL_RESIDENT_CALENDARS_REQUIRED')
    own = [m for m in fm.values() if m['household_id'] == target]
    require(len(own) == facts['N'] and len({m['generation_level'] for m in own}) == facts['G'], 'N_OR_G_MISMATCH')
    require({m['household_id'] for m in members.values()} == {target} | set(facts['context_household_ids']), 'SHARED_ROSTER_MISMATCH')
    require(shell['shared_households'] == 1 + len(facts['context_household_ids']), 'SHARED_HOUSEHOLD_COUNT_MISMATCH')
    relations = facts['relationships']; seen = set(); parents = []
    for e in relations:
        a, b, kind = e['subject'], e['object'], e['type']
        require(a in fm and b in fm and a != b, 'UNKNOWN_OR_SELF_RELATION')
        require(fm[a]['household_id'] == fm[b]['household_id'], 'RELATION_CROSSES_HOUSEHOLDS')
        key = (kind, *sorted((a, b))) if kind in ('partner', 'sibling') else (kind, a, b)
        require(key not in seen, 'DUPLICATE_RELATION'); seen.add(key)
        gap = fm[a]['age_years'] - fm[b]['age_years']
        if kind == 'parent':
            require(gap >= 15 and fm[a]['generation_level'] == fm[b]['generation_level'] + 1, 'PARENT_AGE_OR_GENERATION_NEEDS_EXPLICIT_REVIEW')
            parents.append((a, b))
        elif kind == 'partner':
            require(min(fm[a]['age_years'], fm[b]['age_years']) >= 18 and fm[a]['generation_level'] == fm[b]['generation_level'], 'PARTNER_REFERENCE_CONFLICT')
        elif kind == 'sibling':
            require(fm[a]['generation_level'] == fm[b]['generation_level'], 'SIBLING_GENERATION_CONFLICT')
        else:
            require(kind == 'source_relation_unspecified' and bool(e.get('source_label')), 'UNSUPPORTED_RELATION_SUBTYPE')
    def visit(mid, chain):
        require(mid not in chain, 'ANCESTRY_CYCLE')
        for a, b in parents:
            if a == mid:
                visit(b, chain | {mid})
    for mid in fm:
        visit(mid, set())
    require(facts['decision_maker_id'] in fm and fm[facts['decision_maker_id']]['household_id'] == target
            and fm[facts['decision_maker_id']]['age_years'] >= 18, 'EXPLICIT_RESIDENT_ADULT_DECISION_MAKER_REQUIRED')
    assets = indexed(world['devices'], 'asset_id')
    identity_ids = [target, *facts['context_household_ids'], *members, *assets]
    require(len(identity_ids) == len(set(identity_ids)), 'AMBIGUOUS_CROSS_NAMESPACE_ID')
    require(all(d['kind'] in KINDS for d in assets.values()), 'UNKNOWN_DEVICE_KIND')
    kinds = {d['kind'] for d in assets.values() if target in d['using_household_ids']}
    require('ac' in kinds and 4 <= len(kinds) <= 6, 'DEVICE_COVERAGE_OUTSIDE_DECLARED_BENCHMARK')
    require('dryer' not in kinds or 'washer' in kinds, 'DRYER_WITHOUT_WASHING_SERVICE')
    for mid, m in members.items():
        rights = m['can_operate_asset_ids']
        require(len(set(rights)) == len(rights) and set(rights) <= assets.keys(), 'UNKNOWN_OR_DUPLICATE_ASSET_RIGHT')
        require(not rights or m['age_years'] >= 16, 'OPERATOR_BELOW_REFERENCE_AGE')
        require(all(m['household_id'] in assets[a]['using_household_ids'] for a in rights), 'ASSET_PERMISSION_DENIED')
    for d in assets.values():
        require(d['using_household_ids'] and set(d['using_household_ids']) <= {m['household_id'] for m in fm.values()}, 'UNKNOWN_DEVICE_OWNER')
    groups = indexed(world['sleep_groups'], 'group_id')
    assigned = [mid for g in groups.values() for mid in g['member_ids']]
    require(Counter(assigned) == Counter(members.keys()), 'BED_ROSTER_MISMATCH')
    require(all(type(g['capacity']) is int and 0 < len(g['member_ids']) <= g['capacity'] <= 2 for g in groups.values()), 'BED_CAPACITY_CONFLICT')
    require(all(len({fm[mid]['household_id'] for mid in g['member_ids']}) == 1 for g in groups.values()), 'BED_GROUP_CROSSES_HOUSEHOLDS')
    for c in facts['care']:
        require(c['caregiver_id'] in fm and fm[c['caregiver_id']]['age_years'] >= 18
                and set(c['dependent_ids']) <= fm.keys() and c['caregiver_id'] not in c['dependent_ids'], 'INVALID_CARE_CONTRACT')
        require(c['basis'] == 'declared_reference_support', 'CARE_NOT_A_DECLARED_SCENARIO')
    children = {mid for mid, m in fm.items() if m['age_years'] < 6}
    require(children <= {mid for c in facts['care'] for mid in c['dependent_ids']}, 'UNDER6_WITHOUT_DECLARED_CARE')
    roles = t['eligible_archetypes']
    require(roles and len(set(roles)) == len(roles) and set(roles) <= set(ROLES), 'INVALID_ROLE_ELIGIBILITY')
    if 'F' in roles:
        require('ev' in kinds and life.get('mobility') and facts['mobility_basis'] == 'declared_resident_driver', 'F_WITHOUT_EV_OR_MOBILITY')
        driver = life['mobility']['operator_id']
        require(driver in fm and fm[driver]['age_years'] >= 18 and fm[driver]['household_id'] == target, 'F_WITHOUT_RESIDENT_ADULT_DRIVER')
        require(any(d['kind'] == 'ev' and a in members[driver]['can_operate_asset_ids'] for a, d in assets.items()), 'EV_DRIVER_LACKS_RIGHTS')
        require(bool(life['mobility']['journey_templates']['weekday']), 'F_WITHOUT_DECLARED_WEEKDAY_TRAVEL')
    if 'E' in roles:
        require(any(fm[c['caregiver_id']]['household_id'] == target and any(fm[mid]['household_id'] == target for mid in c['dependent_ids'])
                    for c in facts['care']), 'E_WITHOUT_DECLARED_CARE_CONTEXT')
    return True


ID_FIELDS = {'household_id', 'member_id', 'asset_id', 'operator_id', 'calendar_id',
             'caregiver_id', 'decision_maker_id', 'subject', 'object'}
ID_LIST_FIELDS = {'member_ids', 'using_household_ids', 'can_operate_asset_ids',
                  'dependent_ids', 'context_household_ids'}


def remap(value, mapping, field=None):
    if isinstance(value, dict):
        return {(mapping.get(k, k) if field == 'member_calendars' else k): remap(v, mapping, k)
                for k, v in value.items()}
    if isinstance(value, list):
        return [remap(v, mapping, field) for v in value]
    if isinstance(value, str):
        if value.startswith('$sleep:'):
            return '$sleep:' + mapping[value.split(':', 1)[1]]
        return mapping.get(value, value) if field in ID_FIELDS | ID_LIST_FIELDS else value
    return value


def construct(t, hid, role):
    world = t['world']; old = world['household_id']
    contexts = sorted(t['facts']['context_household_ids'])
    mapping = {old: hid, **{k: hid + '-aux-%02d' % (i + 1) for i, k in enumerate(contexts)}}
    require(not (set(m['member_id'] for m in world['members']) & set(d['asset_id'] for d in world['devices'])), 'AMBIGUOUS_MEMBER_ASSET_ID')
    for field, key, suffix in [('members', 'member_id', 'm'), ('devices', 'asset_id', 'a')]:
        mapping.update({r[key]: hid + '-' + suffix + '%02d' % (i + 1) for i, r in enumerate(world[field])})
    result = remap(copy.deepcopy(t), mapping)
    for i, group in enumerate(result['world']['sleep_groups']):
        group['group_id'] = hid + '-bed%02d' % (i + 1)
    result['household_id'] = hid; result['archetype'] = role
    result['archetype_is_given_experimental_condition'] = True
    result['human_acceptance'] = None
    result['source_template_sha256'] = digest(t)
    result['source_evidence_kind'] = t['evidence_kind']
    validate_template(result)
    # All demographic/relationship facts are conserved under ID renaming.
    require(result['facts'] == remap(t['facts'], mapping), 'FACTS_CHANGED_DURING_CONSTRUCTION')
    return result


def generate(input_path, output):
    input_sha = sha(input_path)
    cfg = read(input_path)
    require(set(cfg) == {'schema', 'total', 'subset_size', 'seed', 'prefix', 'pool'}, 'UNKNOWN_GENERATION_INPUT')
    require(cfg['schema'] == 'eb.family_generation.input.v1', 'UNKNOWN_SCHEMA')
    require(type(cfg['total']) is int and 1 <= cfg['total'] <= 100000, 'INVALID_TOTAL')
    require(type(cfg['subset_size']) is int and 0 <= cfg['subset_size'] <= cfg['total'], 'INVALID_SUBSET_SIZE')
    require(type(cfg['seed']) is int and re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.-]{0,40}', cfg['prefix']), 'INVALID_SEED_OR_PREFIX')
    source = (Path(input_path).parent / cfg['pool']['path']).resolve()
    require(source.is_relative_to(Path(input_path).parent.resolve()) and sha(source) == cfg['pool']['sha256'], 'POOL_PATH_OR_HASH')
    pool = read(source)
    require(pool['schema'] == 'eb.family_reference_pool.v1', 'UNKNOWN_SOURCE_POOL_SCHEMA')
    templates = indexed(pool['templates'], 'template_id')
    invalid = {}; valid = {}
    for key, t in sorted(templates.items()):
        try:
            validate_template(t); valid[key] = t
        except (ValueError, KeyError, TypeError) as error:
            invalid[key] = str(error)
    policy_path = HERE.parent / 'household_archetypes/POLICY.json'
    lock_path = HERE.parent / 'household_archetypes/INPUTS.lock.json'
    policy_sha, lock_sha = sha(policy_path), sha(lock_path)
    policy = read(policy_path)
    role_lock = read(lock_path)
    quotas = largest_remainder(policy['EB_source']['assigned_role_counts'], cfg['total'])['quotas']
    root = Path(output).resolve(); require(not root.is_relative_to(HERE.resolve()), 'OUTPUT_INSIDE_METHOD_PACKAGE')
    root.mkdir(parents=True, exist_ok=False)
    save(root / 'INPUT.json', cfg); save(root / 'SOURCE_POOL.json', pool)
    save(root / 'ROLE_POLICY.json', policy)
    records = []; i = 0
    for role in ROLES:
        candidates = [t for t in valid.values() if role in t['eligible_archetypes']]
        for _ in range(quotas[role]):
            i += 1; hid = cfg['prefix'] + '-%06d' % i
            row = {'household_id': hid, 'archetype': role}
            if not candidates:
                row.update(status='source_support_unavailable', reason='NO_VALID_TEMPLATE_FOR_ROLE')
            else:
                t = min(candidates, key=lambda t: digest([cfg['seed'], hid, role, t['template_id']]))
                try:
                    result = construct(t, hid, role)
                    result['archetype_definition'] = {
                        'role': role, 'title': policy['archetypes'][role],
                        'EB_commit': policy['EB_source']['commit'],
                        'role_card_sha256': next(v['sha256'] for v in role_lock['EB_files'] if 'fixed_role_cards' in v['path']),
                        'given_experimental_condition': True, 'human_label': None}
                    path = 'families/' + hid + '.json'; save(root / path, result)
                    row.update(status='family_constructed', path=path, sha256=sha(root / path))
                except (ValueError, KeyError, TypeError) as error:
                    row.update(status='construction_rejected', reason=str(error), template_id=t['template_id'])
            records.append(row)
    subset_quota = largest_remainder(quotas, cfg['subset_size'])['quotas']
    selected = []
    for role in ROLES:
        rows = sorted((r for r in records if r['archetype'] == role), key=lambda r: digest([cfg['seed'], 'subset', r['household_id']]))
        selected += rows[:subset_quota[role]]
    save(root / 'SUBSET.json', {'requested': cfg['subset_size'], 'quotas': subset_quota, 'records': selected,
                               'same_master_files': True, 'failed_slots_not_removed': True})
    summary = {'schema': 'eb.family_generation.output.v1', 'requested': cfg['total'], 'quotas': quotas,
               'records': records, 'invalid_source_templates': invalid,
               'constructed': sum(r['status'] == 'family_constructed' for r in records),
               'selection': 'deterministic scenario-pool sampling with replacement;not population estimation',
               'existing_data_migrated': False, 'EP_runs': 0, 'human_labels_generated': 0}
    save(root / 'SUMMARY.json', summary)
    require(sha(input_path) == input_sha and sha(source) == cfg['pool']['sha256']
            and sha(policy_path) == policy_sha and sha(lock_path) == lock_sha,
            'INPUT_CHANGED_DURING_GENERATION')
    seal(root, {'input_sha256': input_sha, 'pool_sha256': cfg['pool']['sha256'],
                'role_policy_sha256': policy_sha,
                'role_allocator_sha256': sha(HERE.parent / 'household_archetypes/allocate.py'),
                'role_source_lock_sha256': lock_sha,
                'generator_sha256': sha(Path(__file__)), 'complete': summary['constructed'] == cfg['total']})
    return summary


def seal(root, metadata):
    save(root / 'MANIFEST.json', {**metadata, 'files': {str(p.relative_to(root)): sha(p)
        for p in sorted(root.rglob('*')) if p.is_file() and p != root / 'MANIFEST.json'}})


def verify(root):
    root = Path(root).resolve(); m = read(root / 'MANIFEST.json')
    actual = {str(p.relative_to(root)) for p in root.rglob('*') if p.is_file() and p != root / 'MANIFEST.json'}
    require(actual == set(m['files']), 'MISSING_OR_UNREGISTERED_OUTPUT')
    for rel, expected in m['files'].items():
        p = (root / rel).resolve()
        require(p.is_relative_to(root) and p.is_file() and sha(p) == expected, 'OUTPUT_HASH_MISMATCH:' + rel)
    summary = read(root / 'SUMMARY.json')
    require(len(summary['records']) == summary['requested'], 'LOST_REQUESTED_SLOT')
    for row in summary['records']:
        if row['status'] == 'family_constructed':
            p = (root / row['path']).resolve()
            require(p.is_relative_to(root) and sha(p) == row['sha256'], 'RECORD_PRODUCT_MISMATCH')
            family = read(p); validate_template(family)
            require(family['household_id'] == row['household_id'] and family['archetype'] == row['archetype'], 'RECORD_IDENTITY_MISMATCH')
    return {'passed': True, 'requested': summary['requested'], 'constructed': summary['constructed'], 'EP_runs': 0}
