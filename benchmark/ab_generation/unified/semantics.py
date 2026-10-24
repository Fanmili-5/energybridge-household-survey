"""Versioned plan semantics; no generator, solver or acceptance-model imports."""
from ..common import canonical, digest

VERSION = 'eb.plan_semantics.v2'
LINK_VERSION = 'eb.judgment_component_links.v1'
LINKED_SIGNATURE_VERSION = 'eb.device_linked_judgment_signature.v3'


def within_daily_windows(start, end, windows):
    """Half-open interval containment, including unions and midnight wrap."""
    if end <= start:
        return False
    cursor = start
    while cursor < end:
        clock = cursor % 1440
        bounds = [min(end, cursor - clock + z) for a, z in windows
                  if a <= clock < z]
        if not bounds:
            return False
        cursor = max(bounds)
    return True


def program_window_issues(context, plan, needs):
    result = set()
    for n in context['needs']:
        if n['need_id'] not in needs or 'machine_windows_min' not in n:
            continue
        ts = [t for t in plan['tasks'] if t['need_id'] in
              (n['need_id'], n['need_id'] + ':dry')]
        if ts and not within_daily_windows(min(t['start_min'] for t in ts),
                                           max(t['end_min'] for t in ts),
                                           n['machine_windows_min']):
            result.add('MACHINE_WINDOW_VIOLATED')
    return result


def mechanism(name):
    return {'retimed_handling_full_grid':'retimed_handling',
            'event_pause_and_recover':'ev_pause_recover'}.get(name,name)


def legacy_judgment_signature(row, details, axes):
    """Decision relations, not names, opaque IDs, dates or unrelated demands.

    Numeric margins remain in the literal proposal. These declared relation
    bins are experimental semantic proxies, not validated human equivalence.
    """
    opinions = []
    for j in row.get('judgment_context', []):
        opinion = {k: j.get(k) for k in (
            'exceeds_original_numeric_scope', 'machine_time_tension',
            'handling_tension', 'member_opinions_differ',
            'authorization_preference')}
        # Preserve the positions themselves while removing member identifiers.
        members = []
        for mid,m in j.get('member_preferences', {}).items():
            position={k: m[k] for k in (
                'routine_sensitive', 'handling_change_sensitive',
                'comfort_sensitive', 'confirmation_preferred') if k in m}
            position.update(is_proposed_operator=mid in j.get('actual_proposed_operator_ids',[]),
                is_reference_member=mid==j.get('reference_member'),
                is_confirmation_holder=mid==j.get('confirmation_holder'))
            related=[c for c in row.get('components',[]) if c['asset_id']==j.get('asset_id')]
            bound=m.get('preferred_shift_limit_min')
            position['outside_member_machine_scope']=None if bound is None else any(c['magnitude'].get('machine_shift_min',c['magnitude'].get('pause_min',0))>bound for c in related)
            preferred=m.get('cooling_preferred_C');relations=set()
            if preferred is not None:
                for c in related:
                    for p in c['magnitude'].get('ac_intervention',{}).get('phases',[]):
                        b=p.get('B',{});temp=b.get('cooling_setpoint_C')
                        if b.get('mode')=='cooling_stop_fallback':relations.add('stop_request')
                        elif temp is not None:relations.add('at_preference' if abs(temp-preferred)<1e-8 else 'above_preference' if temp>preferred else 'below_preference')
            position['cooling_preference_relation']=sorted(relations) if preferred is not None else None
            members.append(position)
        opinion['member_positions'] = sorted(members, key=canonical)
        opinion['confirmation_reasons'] = sorted(j.get('confirmation_reasons', []))
        opinions.append(opinion)
    return digest(dict(version=VERSION, detail={f: sorted(v) for f, v in details.items()},
                       axes=axes, positions=sorted(opinions, key=canonical),
                       issues=sorted(set(row['issues']))))


def linked_contexts(row):
    """Explicit component references, including separate batches on one asset."""
    components=row.get('components',[]);judgments=row.get('judgment_context',[])
    ids=[c['id'] for c in components]
    if len(ids)!=len(set(ids)) or len(components)!=len(judgments):
        raise ValueError('JUDGMENT_COMPONENT_COUNT_OR_ID_MISMATCH')
    byid={j.get('component_id'):j for j in judgments}
    if len(byid)!=len(judgments) or set(byid)!=set(ids):
        raise ValueError('JUDGMENT_COMPONENT_LINK_MISMATCH')
    result=[]
    for component in components:
        judgment=byid[component['id']]
        if (judgment.get('asset_id')!=component['asset_id'] or
                'service_need_id' not in judgment or
                judgment['service_need_id']!=component.get('service_need_id')):
            raise ValueError('JUDGMENT_COMPONENT_SERVICE_MISMATCH')
        result.append((component,judgment))
    return result


def linked_relation_nodes(row):
    nodes=[]
    for component,judgment in linked_contexts(row):
        magnitude=component['magnitude'];signed=magnitude.get('signed_machine_shift_min')
        slack=magnitude.get('service_slack_min')
        node=dict(family=component['family'],mechanism=mechanism(component['mechanism']),
            axis=magnitude.get('axis','program'),event_role=component['event_relevance']['role'],
            relative_position=component.get('relative_level'),
            machine_direction=None if signed is None else 'earlier' if signed<0 else 'later' if signed>0 else 'unchanged',
            handling_changed=bool(magnitude.get('manual_total_shift_min')),
            service_margin='unknown' if slack is None else 'shortfall' if slack<0 else 'under_30' if slack<30 else 'ample')
        local=dict(components=[component],judgment_context=[judgment],issues=[])
        node['member_and_permission_relations']=legacy_judgment_signature(local,{}, {})
        nodes.append(node)
    return sorted(nodes,key=canonical)


def judgment_signature(row,details,axes):
    version=row.get('judgment_context_version')
    if version is None:
        return legacy_judgment_signature(row,details,axes)
    if version!=LINK_VERSION:raise ValueError('UNKNOWN_JUDGMENT_CONTEXT_VERSION')
    return digest(dict(version=LINKED_SIGNATURE_VERSION,
        detail={f:sorted(v) for f,v in details.items()},axes=axes,
        device_linked_positions=linked_relation_nodes(row),issues=sorted(set(row['issues']))))
