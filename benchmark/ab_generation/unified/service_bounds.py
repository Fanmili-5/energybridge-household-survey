"""Relaxed release/precedence bounds from inputs, never candidate catalogues.

The bound deliberately ignores convenience, deadlines, resources and consent.
If even this relaxed earliest start follows the event, an unstarted service
cannot gain a direct event interval. Unknown chains never certify exclusion.
"""


def earliest(c, need_id):
    needs = {n['need_id']: n for n in c['needs']}
    cache = {}

    def visit(nid, stack):
        if nid in cache:
            return cache[nid]
        if nid in stack:
            return dict(status='unknown', reason='dependency_cycle')
        n = needs.get(nid)
        own = [t for t in c['A']['tasks'] if t['need_id'] == nid]
        if not n or not own:
            return dict(status='unknown', reason='missing_need_or_task')
        asset = own[0]['asset_id']
        # Automatic combo stage: one loading and retrieval pair, no new person.
        stages = own + [t for t in c['A']['tasks']
                        if t['need_id'] == nid+':dry' and t['asset_id'] == asset]
        loads = [o for o in c['A']['operations'] if o['need_id'] == nid and o['kind'] == 'load']
        unloads = [o for o in c['A']['operations'] if o['need_id'] == nid and o['kind'] == 'unload']
        if len(loads) != 1 or len(unloads) != 1:
            return dict(status='unknown', reason='missing_unique_handling')
        load, unload = loads[0], unloads[0]
        first = min(t['start_min'] for t in stages)
        duration = max(t['end_min'] for t in stages)-first
        if duration <= 0 or 'release_min' not in n:
            return dict(status='unknown', reason='missing_release_or_duration')
        ld, ud = load['end_min']-load['start_min'], unload['end_min']-unload['start_min']
        if ld <= 0 or ud <= 0:
            return dict(status='unknown', reason='nonpositive_handling_duration')
        parents = sorted({t['depends_on_need_id'] for t in own if t.get('depends_on_need_id')})
        proofs = [visit(p, stack | {nid}) for p in parents]
        if any(p['status'] != 'bounded' for p in proofs):
            return dict(status='unknown', reason='upstream_bound_unknown', parents=proofs)
        # Already-started stages and loading are fixed facts, not new actions.
        if first < c['decision_min']:
            start = first
            end = (unload['end_min'] if unload['start_min'] < c['decision_min'] else
                   max(c['decision_min'], max(t['end_min'] for t in stages))+ud)
            rule = 'started_program_fixed;future_retrieval_relaxed'
        elif load['start_min'] < c['decision_min']:
            start = max(c['decision_min'], load['end_min'])
            end = start+duration+ud
            rule = 'fixed_executed_loading;relaxed_machine_and_retrieval'
        else:
            ready = max([c['decision_min'], n['release_min']] +
                        [p['earliest_unload_end_min'] for p in proofs])
            start = ready+ld
            end = start+duration+ud
            rule = 'release_and_parent_collection_then_loading'
        result = dict(status='bounded', need_id=nid, asset_id=asset, rule=rule,
            earliest_start_min=start, earliest_unload_end_min=end,
            release_min=n['release_min'], decision_min=c['decision_min'],
            load_duration_min=ld, program_duration_min=duration, unload_duration_min=ud,
            parent_certificates=proofs, relaxed_away=['calendars', 'deadlines', 'resources', 'consent'])
        cache[nid] = result
        return result

    return visit(need_id, set())


def event_exclusion(c, need_id, event):
    proof = earliest(c, need_id)
    if proof['status'] != 'bounded':
        return None
    stages = [t for t in c['A']['tasks'] if t['need_id'] in (need_id, need_id+':dry')
              and t['asset_id'] == proof['asset_id']]
    if any(max(t['start_min'], event['start_min']) < min(t['end_min'], event['end_min']) for t in stages):
        return None
    if proof['earliest_start_min'] < event['end_min']:
        return None
    return dict(reason='release_and_complete_upstream_service_after_event',
                event_end_min=event['end_min'], certificate=proof,
                scope='direct_event_interval_only;necessary_support_is_separate')
