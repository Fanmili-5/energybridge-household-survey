"""Bind generated families to public housing and life-A modules, without EP."""
import copy
from pathlib import Path

from .core import read, save, seal, sha, verify, require


def connect(families, output):
    from benchmark.housing_simulation.pipeline import build_shell
    from benchmark.housing_simulation.assembly import bind_world
    from benchmark.ab_generation.life import normalize_world
    from benchmark.ab_generation.life_pipeline import build_life
    from .energy_portrait import RULES, SOURCE_LOCK, compile_portrait, render_portrait
    from .device_persona import RULES as PERSONA_RULES
    from .household_preferences import SOURCES as HOUSEHOLD_SOURCES
    from .portrait_inputs import from_life
    from benchmark.ab_generation.common import read as read_life
    families, root = Path(families).resolve(), Path(output).resolve()
    rules_hash, lock_hash, persona_hash = sha(RULES), sha(SOURCE_LOCK), sha(PERSONA_RULES)
    household_hash, household_code_hash = sha(HOUSEHOLD_SOURCES), sha(Path(__file__).parent / 'household_preferences.py')
    joint_hashes = {p: sha(Path(__file__).parent / p) for p in ('joint_sampling.py', 'JOINT_SAMPLING_RULES.json')}
    verify(families)
    source = read(families / 'SUMMARY.json'); pool = read(families / 'SOURCE_POOL.json')
    require(source['schema'] == 'eb.family_generation.output.v1', 'FAMILY_BATCH_REQUIRED')
    require(not root.is_relative_to(families), 'CONNECTION_OUTPUT_MUST_BE_SEPARATE')
    root.mkdir(parents=True, exist_ok=False)
    save(root / 'SOURCE_MANIFEST.json', read(families / 'MANIFEST.json'))
    worlds = {r['household_id']: read(families / r['path']) for r in source['records'] if r['status'] == 'family_constructed'}
    save(root / 'assembly.json', pool['assembly'])
    shell_input = {**pool['shell_defaults'], 'schema': 'eb.housing_shell.input.v1',
                   'assembly': {'path': 'assembly.json', 'sha256': sha(root / 'assembly.json')},
                   'households': [v['shell'] for v in worlds.values()]}
    records = []
    if worlds:
        save(root / 'SHELL_INPUT.json', shell_input)
        shell_result = build_shell(root / 'SHELL_INPUT.json', root / 'shells')
        statuses = {r['household_id']: r['status'] for r in shell_result['records']}
    else:
        statuses = {}
    for row in source['records']:
        hid = row['household_id']; record = {'household_id': hid, 'archetype': row['archetype']}
        try:
            require(hid in worlds, 'FAMILY_SOURCE_SUPPORT_UNAVAILABLE')
            require(statuses.get(hid) == 'shell_compiled', 'SHELL_NOT_ADMITTED')
            t = worlds[hid]
            world = bind_world(copy.deepcopy(t['world']), read(root / 'shells' / hid / 'layout.json'))
            # Reject a known compiler limitation here, retaining the family in the denominator.
            ac_rooms = [d['room_id'] for d in world['parameter_pack']['devices'] if d['kind'] == 'ac']
            require(len(ac_rooms) == len(set(ac_rooms)), 'MULTIPLE_INDEPENDENT_AC_IN_ONE_ZONE_UNSUPPORTED')
            folder = root / 'life_inputs' / hid
            save(folder / 'world_contracts.json', {**pool['world_defaults'], 'households': [t['world']]})
            save(folder / 'family_context.json', {'facts': t['facts'], 'archetype_definition': t['archetype_definition'],
                                                'source_family_sha256': row['sha256'], 'human_acceptance': None})
            save(folder / 'resource_worlds.json', {'schema': 'eb.life_resource_worlds.v1',
                 'source_world_contract_sha256': sha(folder / 'world_contracts.json'), 'households': [normalize_world(world)]})
            life = copy.deepcopy(t['life'])
            from .joint_sampling import apply_to_life
            life, preference_changes = apply_to_life(life, t.get('energy_use_profile', {}))
            if preference_changes:
                save(folder / 'PREFERENCE_APPLICATION.json', {'profile_sha256': t['energy_use_profile']['joint_sampling']['profile_sha256'],
                    'changes': preference_changes, 'calendar_or_hard_service_changed': False})
            life['provenance'] = {'source_family_sha256': row['sha256'], 'archetype': row['archetype'],
                                  'family_context_sha256': sha(folder / 'family_context.json'), 'human_label_used': False}
            batch = {'schema': 'eb.life_to_A.input.v1', 'worlds': {'path': 'resource_worlds.json',
                     'sha256': sha(folder / 'resource_worlds.json')}, 'households': [life]}
            save(folder / 'LIFE_INPUT.json', batch)
            result = build_life(folder / 'LIFE_INPUT.json', root / 'life_A' / hid)
            if 'energy_attitude_rules_sha256' in t:
                require(t['energy_attitude_rules_sha256'] == sha(RULES), 'ENERGY_ATTITUDE_RULES_CHANGED')
            if 'energy_use_profile' in t:
                require(t['energy_use_profile']['bindings']['rules_sha256'] == persona_hash and
                        t['energy_use_profile']['bindings']['conditions_code_sha256'] == sha(Path(__file__).parent / 'decision_conditions.py') and
                        t['energy_use_profile']['bindings']['household_preferences_code_sha256'] == sha(Path(__file__).parent / 'household_preferences.py') and
                        t['energy_use_profile']['bindings']['household_preferences_sources_sha256'] == sha(Path(__file__).parent / 'EB_HOUSEHOLD_PREFERENCE_SOURCES.json') and
                        t['energy_use_profile']['bindings']['code_sha256'] == sha(Path(__file__).parent / 'device_persona.py'),
                        'FAMILY_DEVICE_PERSONA_VERSION_CHANGED')
            life_row = result['records'][0]
            original_life = read_life(root / 'life_A' / hid / life_row['path'])
            bound_family = copy.deepcopy(t)
            bound_family['life'] = life
            portrait = compile_portrait(from_life(bound_family, original_life, normalize_world(world)))
            save(root / 'energy_portraits' / (hid + '.json'), portrait)
            first_date = min(original_life['days'])
            (root / 'energy_portraits' / (hid + '.md')).write_text(render_portrait(portrait, first_date), encoding='utf-8')
            status = 'A_constructed' if result['all_A_constructed'] else 'needs_unserved'
            record.update(status=status, life_manifest='life_A/' + hid + '/MANIFEST.json',
                          family_sha256=row['sha256'], energy_portrait='energy_portraits/' + hid + '.json')
        except (ValueError, KeyError, TypeError) as error:
            record.update(status='connection_rejected', reason=str(error))
        records.append(record)
    verify(families)
    require(sha(RULES) == rules_hash and sha(SOURCE_LOCK) == lock_hash and sha(PERSONA_RULES) == persona_hash and
            sha(HOUSEHOLD_SOURCES) == household_hash and sha(Path(__file__).parent / 'household_preferences.py') == household_code_hash,
            'PORTRAIT_RULES_CHANGED_DURING_CONNECTION')
    require(all(sha(Path(__file__).parent / p) == h for p,h in joint_hashes.items()), 'JOINT_METHOD_CHANGED_DURING_CONNECTION')
    summary = {'schema': 'eb.family_connection.v1', 'requested': source['requested'], 'records': records,
               'constructed': sum(r['status'] == 'A_constructed' for r in records),
               'source_family_manifest_sha256': sha(families / 'MANIFEST.json'),
               'failures_retained': True, 'EP_runs': 0, 'existing_data_migrated': False}
    save(root / 'SUMMARY.json', summary)
    seal(root, {'source_family_manifest_sha256': sha(families / 'MANIFEST.json'),
                'joint_sampling_hashes': joint_hashes,
                'energy_portrait_rules_sha256': rules_hash, 'energy_portrait_source_lock_sha256': lock_hash,
                'device_persona_rules_sha256': persona_hash,
                'household_preferences_sources_sha256': household_hash, 'household_preferences_code_sha256': household_code_hash,
                'complete': summary['constructed'] == summary['requested'], 'EP_runs': 0})
    return summary
