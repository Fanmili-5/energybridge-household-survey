"""Opt-in life-conditioned targets over frozen v3 coordinates, before A.

An unassigned qualified household member is a conditional witness, not a
habit owner, promised helper or execution consent. The experiment maps a
frozen time quantile to a finite feasible domain; no extra draw is made.
"""
import math

from ..common import digest

VERSION = 'life_conditional_v1'


def source_view(problem, portrait):
    # In particular omit legacy A, VPP, answers and consequences.
    return dict(household_id=problem['household_id'], anchor=problem['anchor'],
                days=problem['days'], jobs=problem['jobs'], world=problem['world'],
                joint_sampling=portrait.get('joint_sampling', {}))


def qualified_members(problem, asset):
    members = [m['member_id'] for m in problem['world']['members']
               if asset['asset_id'] in m['can_operate_asset_ids']
               and m['household_id'] in asset['using_household_ids']]
    registered, normal = asset.get('operator_id'), asset.get('normal_operator_ids')
    if registered:
        members = [mid for mid in members if mid == registered]
    if normal is not None:
        members = [mid for mid in members if mid in normal]
    if not registered and normal is None:
        residents = {m['member_id'] for m in problem['world']['members']
                     if m['household_id'] == problem['household_id']}
        members = [mid for mid in members if mid in residents]
    return sorted(members)


def local_candidates(problem, job, earliest_load=None, shared=None):
    """Existence by 10-minute enumeration, not a whole-house assignment.

    Loading and retrieval each have a qualified witness. Multiple jobs may
    conflict; the original whole-house solver must still resolve them.
    """
    asset = next(d for d in problem['world']['devices'] if d['asset_id'] == job['asset_id'])
    members = qualified_members(problem, asset)
    policy, shared = job['policy'], shared or {}
    if ('earliest_h' in shared) != ('latest_h' in shared):
        return [], 'incomplete_explicit_shared_preference_window'
    release = max(job['release_min'], earliest_load if earliest_load is not None else job['release_min'])
    deadline = min(job['deadline_min'], len(problem['days'])*1440)
    duration = policy['duration_min']+job.get('automatic_tail_duration_min',0)
    phases=[(0,policy['duration_min'],policy['machine_windows_min'])]
    if job.get('automatic_child_need_id'):
        child=next(j for j in problem['jobs'] if j['need_id']==job['automatic_child_need_id'])
        phases.append((policy['duration_min'],child['policy']['duration_min'],child['policy']['machine_windows_min']))
        deadline=min(deadline,child['deadline_min'])
    slots = []
    for day in problem['days'].values():
        for mid in members:
            for lo, hi in day['operator_windows'].get(mid, []):
                for t in range(math.ceil(max(release, lo)/10)*10, min(deadline, hi)-9, 10):
                    if any(r['room_id'] == asset['room_id'] and
                           max(t, day['base_min']+r['start_min']) < min(t+10, day['base_min']+r['end_min'])
                           for r in day['reservations']):
                        continue
                    slots.append((t, mid))
    slots = sorted(set(slots))
    candidates = []
    for start in range(math.ceil((release+10)/10)*10, deadline-duration-9, 10):
        end = start+duration
        if not all(any(a <= q % 1440 and q % 1440+10 <= z for a, z in windows)
                   for offset,length,windows in phases for q in range(start+offset,start+offset+length,10)):
            continue
        if 'earliest_h' in shared:
            lo, hi = shared['earliest_h']*60, shared['latest_h']*60
            if not any(k*1440+lo <= start and end <= k*1440+hi+(1440 if hi <= lo else 0)
                       for k in range(start//1440-1, start//1440+1)):
                continue
        loads = [(t, mid) for t, mid in slots if t+10 <= start and
                 start-t-10 <= policy['maximum_preload_wait_min'] and
                 (policy['timer_allowed'] or t+10 == start)]
        retrieval_max=policy['maximum_retrieval_wait_min']
        if job.get('automatic_child_need_id'):retrieval_max=min(retrieval_max,child['policy']['maximum_retrieval_wait_min'])
        unloads = [(t, mid) for t, mid in slots if end <= t and t-end <= retrieval_max]
        if not loads or not unloads:
            continue
        load = min(loads, key=lambda x: (-x[0], x[1]))
        unload = min(unloads)
        candidates.append(dict(start_min=start, end_min=end, load_min=load[0], loader=load[1],
                               unload_min=unload[0], retriever=unload[1]))
    reason = None if candidates else 'no_local_witness_under_declared_inputs'
    if not members:
        reason = 'no_originally_qualified_normal_or_resident_operator'
    return candidates, reason


def derive(problem, portrait):
    from .a_solver import dated_targets
    if portrait.get('household_id') != problem['household_id']:
        raise ValueError('TARGET_CONTEXT_HOUSEHOLD_MISMATCH')
    original = dated_targets(portrait, problem['anchor'])
    prefs = {(d['asset_id'], d['kind']): d for d in portrait.get('joint_sampling', {}).get('devices', [])}
    jobs = {j['need_id']: j for j in problem['jobs']}
    rows, pending = {}, set(jobs)
    while pending:
        ready = sorted(n for n in pending if not (jobs[n].get('depends_on_need_id') or jobs[n].get('automatic_parent_need_id')) or
                       (jobs[n].get('depends_on_need_id') or jobs[n].get('automatic_parent_need_id')) in rows)
        if not ready:
            raise ValueError('TARGET_CONTEXT_DEPENDENCY_CYCLE_OR_MISSING_PARENT')
        for nid in ready:
            job = jobs[nid]; pref = prefs.get((job['asset_id'], job['kind']), {})
            automatic_parent=job.get('automatic_parent_need_id')
            if automatic_parent:
                parent=rows[automatic_parent];value=parent['target_min']
                if value is not None:value+=jobs[automatic_parent]['policy']['duration_min']
                witness=parent['local_witness']
                if witness:witness={**witness,'start_min':witness['start_min']+jobs[automatic_parent]['policy']['duration_min']}
                rows[nid]=dict(need_id=nid,asset_id=job['asset_id'],kind=job['kind'],source_date=job['date'],
                    target_min=value,origin='fixed_automatic_phase_offset;not_independent_dryer_draw',
                    reason=None if value is not None else 'upstream_automatic_target_missing',
                    local_witness=witness,local_candidate_count=parent['local_candidate_count'],
                    domain_sha256=parent['domain_sha256'],reference_member_assigned=False,execution_consent=False,
                    scope='derived_phase_target;no_separate_handling;whole_house_feasibility_pending',
                    source_v3_target_missing=(job['asset_id'],job['date'],nid) not in original,
                    independent_source_target=original.get((job['asset_id'],job['date'],nid)),
                    independent_source_target_applied=False)
                pending.remove(nid);continue
            parent = rows.get(job.get('depends_on_need_id'))
            key = (job['asset_id'], job['date'], nid)
            known = original.get(key, original.get(key[:2]+(None,)))
            early = parent['local_witness']['unload_min']+10 if parent and parent.get('local_witness') else None
            domain, reason = local_candidates(problem, job, early, pref.get('explicit_shared_declaration'))
            coordinates = pref.get('coordinates', {})
            value, witness, origin = known, None, 'frozen_v3_dated_target' if known is not None else None
            if known is not None:
                witness = next((r for r in domain if r['start_min'] == known), None)
            elif parent and not parent.get('local_witness'):
                reason = 'upstream_target_has_no_local_transfer_witness'
            elif not domain:
                pass
            elif parent:
                witness = domain[0]; value = witness['start_min']
                origin = 'experimental_earliest_after_parent_retrieval;not_independent_dryer_draw'
            elif 'time_orientation' not in coordinates:
                reason = 'missing_frozen_time_coordinate'
            else:
                # Preserve v3's earliest feasible service day, then clock rank.
                day = domain[0]['start_min']//1440
                candidates = [r for r in domain if r['start_min']//1440 == day]
                clock = pref.get('explicit_shared_declaration', {}).get('preferred_h')
                if clock is not None:
                    witness = min(candidates, key=lambda r: (abs(r['start_min'] % 1440-clock*60), r['start_min']))
                else:
                    witness = candidates[min(len(candidates)-1, math.floor(coordinates['time_orientation']*len(candidates)))]
                value = witness['start_min']; origin = 'experimental_household_target_conditioned_on_qualified_operator_assignment'
            rows[nid] = dict(need_id=nid, asset_id=job['asset_id'], kind=job['kind'], source_date=job['date'],
                target_min=value, origin=origin, reason=None if value is not None else reason,
                local_witness=witness, local_candidate_count=len(domain), domain_sha256=digest(domain),
                reference_member_assigned=False, execution_consent=False,
                scope='soft_target;local_witness_only;whole_house_feasibility_pending',
                source_v3_target_missing=known is None)
            pending.remove(nid)
    result = dict(version=VERSION, source_sha256=digest(source_view(problem, portrait)),
                  rows=[rows[n] for n in sorted(rows)], new_random_draws=0,
                  parameter_origin='project_experimental_mapping;not_measured_preferences')
    result['sha256'] = digest(result)
    return result
