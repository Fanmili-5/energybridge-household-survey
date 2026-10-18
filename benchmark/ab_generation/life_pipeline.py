"""File interfaces for life generation; no historical stages or fixed cohorts."""
from pathlib import Path
from .common import bound, code_hash, digest, read, save, seal, sha, verify
from .life import LIFE_RULES, LIFE_VERSION, generate_household, require


def build_life(input_path, out, rules_path=None):
    input_path, out = Path(input_path), Path(out)
    batch = read(input_path)
    require(batch['schema'] == 'eb.life_to_A.input.v1', 'UNKNOWN_LIFE_BATCH_SCHEMA')
    require(set(batch) == {'schema', 'worlds', 'households'}, 'UNKNOWN_LIFE_BATCH_FIELD')
    worlds_path = bound(input_path.parent, batch['worlds']['path'])
    require(sha(worlds_path) == batch['worlds']['sha256'], 'LIFE_WORLD_FILE_CHANGED')
    worlds = read(worlds_path)
    require(worlds['schema'] == 'eb.life_resource_worlds.v1', 'UNKNOWN_RESOURCE_WORLD_SCHEMA')
    by_id = {w['household_id']: w for w in worlds['households']}
    require(len(by_id) == len(worlds['households']), 'DUPLICATE_RESOURCE_WORLD')
    ids = [h['household_id'] for h in batch['households']]
    require(ids and len(ids) == len(set(ids)) and set(ids) <= by_id.keys(), 'EMPTY_DUPLICATE_OR_UNKNOWN_LIFE_HOUSEHOLD')
    rules = {**LIFE_RULES, **(read(rules_path) if rules_path else {})}
    out.mkdir(parents=True, exist_ok=False)
    save(out / 'INPUT.json', batch)
    save(out / 'WORLD_INPUT.json', worlds)
    save(out / 'RULES.json', rules)
    records = []
    for spec in sorted(batch['households'], key=lambda x: x['household_id']):
        result = generate_household(spec, by_id[spec['household_id']], rules)
        name = 'households/' + digest(spec['household_id'])[:24] + '.json.gz'
        save(out / name, result)
        records.append({'household_id': spec['household_id'], 'status': result['status'], 'path': name,
                        'tasks': len(result['A']['tasks']), 'operations': len(result['A']['operations']),
                        'requirements': len(result['requirements']), 'unserved': len(result['unserved'])})
    summary = {'schema': LIFE_VERSION, 'households': len(records), 'records': records,
               'all_A_constructed': all(r['status'] == 'A_constructed' for r in records),
               'B_events_prices_or_answers_used': False, 'physical_simulations_started': 0}
    save(out / 'SUMMARY.json', summary)
    seal(out, {'schema': LIFE_VERSION, 'input_sha256': sha(input_path), 'worlds_sha256': sha(worlds_path),
               'code_sha256': code_hash(), 'records': records})
    return summary
