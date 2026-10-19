"""Bind selected requests to the housing module's existing physical interface."""
import copy
import shutil
from pathlib import Path
from .common import bound, digest, read, save, seal, sha, verify
from .model import apply, plan_hash, request_issues


def attach_legacy_requirements(pack, annual_path):
    if 'service_needs' in pack:
        return pack
    if annual_path is None:
        raise ValueError('FULL_SERVICE_REQUIREMENTS_REQUIRED;pass_annual_A_root')
    if sha(annual_path) != pack['source_annual_A_sha256']:
        raise ValueError('ANNUAL_A_SOURCE_CHANGED')
    annual = read(annual_path)
    if annual['household_id'] != pack['household_id'] or annual['anchor'] != pack['anchor'] or annual['end_exclusive'] != pack['end_exclusive']:
        raise ValueError('ANNUAL_A_IDENTITY_MISMATCH')
    if digest(annual['tasks']) != digest(pack['tasks']) or digest(annual['operations']) != digest(pack['operations']):
        raise ValueError('ANNUAL_A_PROGRAMS_CHANGED')
    pack = copy.deepcopy(pack)
    pack['service_needs'] = [copy.deepcopy(n) for d in annual['days'].values() for n in d['needs']
                             if n['kind'] in ('washer', 'dishwasher')]
    pack['AB_service_needs_source'] = {'annual_A_sha256': sha(annual_path),
                                      'coordinate_system': 'original_household_anchor', 'requirements_redefined': False}
    return pack


def export_physics(stage, imported, generated, case_ids, policy, out, candidate_id=None, annual_A_root=None):
    stage, imported, generated, out = map(Path, (stage, imported, generated, out))
    incoming, produced = verify(imported), verify(generated)
    if incoming['source_manifest_sha256'] != sha(stage / 'INPUT_MANIFEST.json'):
        raise ValueError('SOURCE_STAGE_CHANGED')
    source = read(stage / 'INPUT_MANIFEST.json')
    batch = read(imported / 'BATCH.json')
    inrows = {r['case_id']: r for r in batch['records']}
    outrows = {r['case_id']: r for r in produced['records']}
    if len(set(case_ids)) != len(case_ids):
        raise ValueError('DUPLICATE_EXPORT_CASE')
    if not set(case_ids) <= inrows.keys() & outrows.keys():
        raise ValueError('UNKNOWN_EXPORT_CASE')
    if candidate_id and len(case_ids) != 1:
        raise ValueError('EXPLICIT_PROBE_REQUIRES_SINGLE_CASE')
    out.mkdir(parents=True, exist_ok=False)
    resources = out / 'resources'
    fixed = ('inputs/schema_fields.json.gz', 'inputs/native_rows.json.gz', 'THERMAL_ENVIRONMENT_POLICY.json')
    hashes = {}
    for name in fixed:
        src, dst = bound(stage, name), bound(resources, name)
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(src, dst)
        hashes[name] = sha(dst)
    pairs, groups = [], {}
    for case_id in case_ids:
        row = inrows[case_id]
        context = read(bound(imported, row['context']))
        result = read(bound(generated, outrows[case_id]['path']))
        if result['context_sha256'] != digest(context) or result['binding'] != context['reference']['binding']:
            raise ValueError('GENERATION_CONTEXT_CHANGED')
        selection = result['selections'][policy]
        if candidate_id:
            if result['assignment']['mode'] != 'fresh_candidates':
                raise ValueError('CANNOT_OVERRIDE_FROZEN_CONTROL_OR_FAILURE')
            probe = next((c for c in result['candidates'] if c['id'] == candidate_id), None)
            if probe is None or probe['static_issues']:
                raise ValueError('UNKNOWN_OR_STATICALLY_INVALID_PROBE')
            baseline = copy.deepcopy(context['A'])
            for c in baseline['controls']:
                c['_ab_control_id'] = digest(c)
            plan = apply(baseline, probe['patches'])
            for c in plan['controls']:
                c.pop('_ab_control_id', None)
            selection = {'status': 'explicit_predeclared_candidate_probe', 'candidate_ids': [candidate_id], 'plan_B': plan}
        if selection['status'] == 'no_comparable_opportunity':
            raise ValueError('NO_SELECTED_REQUEST:' + case_id)
        if selection['status'] != 'original_failure_request_preserved' and request_issues(context, selection['plan_B']):
            raise ValueError('REQUEST_CHANGED_FROZEN_IDENTITIES_OR_PAST')
        if selection.get('B_commands_sha256', plan_hash(selection['plan_B'])) != plan_hash(selection['plan_B']):
            raise ValueError('SELECTED_B_HASH_CHANGED')
        home = next(r for r in source['records'] if r['household_id'] == row['household_id'])
        packpath, pairpath = bound(stage, home['path']), bound(stage, row['source_pair'])
        if sha(packpath) != context['source']['household_sha256'] or sha(pairpath) != context['source']['pair_sha256']:
            raise ValueError('ORIGINAL_INPUT_CHANGED')
        pack, old = read(packpath), read(pairpath)
        zones = [d['room_id'] for d in pack['world']['parameter_pack']['devices'] if 'ac' in d['types']]
        if len(zones) != len(set(zones)):
            raise ValueError('LEGACY_WORLD_UNSUPPORTED:MULTIPLE_INDEPENDENT_AC_IN_ONE_ZONE')
        if plan_hash(old['A']) != result['A_commands_sha256']:
            raise ValueError('EXPORTED_A_CHANGED')
        annual_path = bound(annual_A_root, pack['household_id'] + '.json.gz') if annual_A_root else None
        pack = attach_legacy_requirements(pack, annual_path)
        pair = {k: copy.deepcopy(old[k]) for k in ('case_id', 'household_id', 'date', 'decision_min', 'A', 'needs_A', 'EV_continuous_reference', 'VPP_events')}
        pair['B'] = selection['plan_B']
        pair['needs_B'] = copy.deepcopy(pair['needs_A'])
        pair['schedule_hashes'] = {s: digest({k: pair[s][k] for k in ('tasks', 'operations', 'controls')}) for s in ('A', 'B')}
        pair['AB_generation'] = {'schema': result['schema'], 'rules_sha256': result['rules_sha256'],
                                 'event_meter_scope': context['event_meter_scope'],
                                 'reference_sha256': result['reference_sha256'], 'policy': 'explicit_candidate_probe' if candidate_id else policy,
                                 'candidate_ids': selection['candidate_ids'], 'status': selection['status'],
                                 'legacy_pair_sha256': context['source']['pair_sha256'],
                                 'old_B_thermal_SOC_or_acceptance_labels_reused': False}
        pair['source_pair_sha256'] = digest(pair)
        key = digest(case_id)[:24]
        hname, pname = 'inputs/homes/' + key + '.json.gz', 'inputs/pairs/' + key + '.json.gz'
        save(resources / hname, pack)
        save(resources / pname, pair)
        weather = bound(stage, pack['weather'])
        if sha(weather) != pack['weather_sha256']:
            raise ValueError('WEATHER_CHANGED')
        target = bound(resources, pack['weather'])
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(weather, target)
        hashes[pack['weather']] = pack['weather_sha256']
        entry = {'id': key, 'case_id': case_id,
                      'household': {'path': hname, 'sha256': sha(resources / hname)},
                      'pair': {'path': pname, 'sha256': sha(resources / pname)}}
        pairs.append(entry)
        initial = context['source']['initialization']
        history = initial['history_days']
        if initial['run_interval_min'][0] != -history * 1440:
            raise ValueError('AMBIGUOUS_A_INITIALIZATION')
        tail = (initial['run_interval_min'][1] + 1439) // 1440
        groups.setdefault((history, tail), []).append(entry)
    jobs = []
    for (history, tail), entries in sorted(groups.items()):
        name = 'physics_job.json' if len(groups) == 1 else f'physics_job_history_{history}_tail_{tail}.json'
        save(out / name, {'schema': 'eb.housing_physics.input.v1', 'resource_root': 'resources',
                         'resources': hashes,
                         'settings': {'history_days': history, 'tail_days': tail, 'reference_ach': .35, 'portal_flow_scale': 1.0},
                         'pairs': entries})
        jobs.append(name)
    save(out / 'JOBS.json', {'jobs': jobs, 'initialization_policy': 'exact_imported_A_history;no_implicit_truncation'})
    seal(out, {'schema': 'eb.ab_generation.physical_export.v1', 'policy': policy,
               'cases': case_ids, 'generation_manifest_sha256': sha(generated / 'MANIFEST.json'),
               'A_and_VPP_frozen': True, 'actual_outcomes': None})
    return {'cases': len(pairs), 'physics_jobs': [str(out / p) for p in jobs]}
