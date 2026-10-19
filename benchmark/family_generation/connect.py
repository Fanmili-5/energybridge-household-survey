"""Bind generated families to public housing and life-A modules, without EP."""
import copy
from pathlib import Path

from .core import read, save, seal, sha, verify, require


def connect(families, output):
    from benchmark.housing_simulation.pipeline import build_shell
    from benchmark.housing_simulation.assembly import bind_world
    from benchmark.ab_generation.life import normalize_world
    from benchmark.ab_generation.life_pipeline import build_life
    families, root = Path(families).resolve(), Path(output).resolve()
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
            life['provenance'] = {'source_family_sha256': row['sha256'], 'archetype': row['archetype'],
                                  'family_context_sha256': sha(folder / 'family_context.json'), 'human_label_used': False}
            batch = {'schema': 'eb.life_to_A.input.v1', 'worlds': {'path': 'resource_worlds.json',
                     'sha256': sha(folder / 'resource_worlds.json')}, 'households': [life]}
            save(folder / 'LIFE_INPUT.json', batch)
            result = build_life(folder / 'LIFE_INPUT.json', root / 'life_A' / hid)
            status = 'A_constructed' if result['all_A_constructed'] else 'needs_unserved'
            record.update(status=status, life_manifest='life_A/' + hid + '/MANIFEST.json',
                          family_sha256=row['sha256'])
        except (ValueError, KeyError, TypeError) as error:
            record.update(status='connection_rejected', reason=str(error))
        records.append(record)
    verify(families)
    summary = {'schema': 'eb.family_connection.v1', 'requested': source['requested'], 'records': records,
               'constructed': sum(r['status'] == 'A_constructed' for r in records),
               'source_family_manifest_sha256': sha(families / 'MANIFEST.json'),
               'failures_retained': True, 'EP_runs': 0, 'existing_data_migrated': False}
    save(root / 'SUMMARY.json', summary)
    seal(root, {'source_family_manifest_sha256': sha(families / 'MANIFEST.json'),
                'complete': summary['constructed'] == summary['requested'], 'EP_runs': 0})
    return summary
