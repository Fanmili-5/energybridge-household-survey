"""Adapt the pinned runner's planning checks and evidence review, not its scorer.

The native policy closure lives inside run_family_agent and cannot be imported.
Keep its calls/order here; tests compare against that actual closure via AST.
"""
from eb_execution import upstream


def runtime_errors(plan, *, loop, config, sim_h, horizon, bounds, event):
    runner, _ = upstream()
    if not isinstance(plan, dict):
        return ['selected plan is not an executable object']
    errors = runner._adaptive_v3_plan_control_errors(
        plan, sim_h=sim_h, total_sim_hours=horizon,
        setpoint_min_c=bounds['minimum_c'], setpoint_max_c=bounds['maximum_c'])
    actions = plan.get('appliances') or {}
    completed = runner._adaptive_v3_completed_services(
        runner._adaptive_v3_realtime_device_state(loop, sim_h))
    missing = runner._missing_explicit_appliance_actions(
        actions, config, adaptive_contract=True, completed_services=completed)
    if missing:
        errors.append('missing explicit appliance commands: ' + ', '.join(missing))
    errors.extend('adaptive action contract: ' + item for item in
        runner._adaptive_v3_appliance_action_contract_errors(actions, config))
    errors.extend('adaptive runtime contract: ' + item for item in
        runner._adaptive_v3_shiftable_runtime_errors(
            actions, getattr(loop, 'appliance_suite', None), sim_h=sim_h))
    errors.extend('shiftable service infeasible: ' + item for item in
        runner._shiftable_service_window_errors(actions, config))
    if event:
        active = event['trigger_h'] <= sim_h < event['end_h']
        errors.extend('VPP schedule conflict: ' + item for item in
            runner._vpp_appliance_conflicts(actions, config, event,
                current_hod=sim_h % 24 if active else None))
    errors.extend('EV service infeasible: ' + item for item in
        runner._ev_service_window_errors(actions, config, vpp_event=event))
    return errors


SEMANTIC_FEEDBACK = (
    '\n\n[SEMANTIC VALIDATION FEEDBACK]\n'
    'The previous response did not yield a valid model-selected executable plan. '
    'Use these findings as evidence, revise the portfolio as needed, and explicitly select '
    'one of your own feasible candidates. Do not select an advisor reference and do not '
    'merely rename an invalid plan.\n'
)
IMPACT_FEEDBACK = (
    '\n\n[INDEPENDENT PHYSICAL AND TARIFF EVIDENCE]\n'
    'A method-blind accounting tool checked the portfolio below. It reports fixed-load '
    'arithmetic, event overlap, tariff integration, service feasibility, physical direction, '
    'and explicit uncertainty; it does not rank or choose a candidate. Reconsider your own '
    'selection using this evidence. If it changes a material claim or tradeoff, revise the '
    'portfolio. Otherwise return a complete confirmed portfolio. Keep unsupported energy or '
    'savings claims null and preserve your own decision authority. A zero changed-path count '
    'means the candidate is physically the ordinary plan: do not describe inherited timing or '
    'cost as an offer-specific benefit. When exact fixed-load cost deltas are present, use their '
    'reported normalized tariff unit rather than inventing a currency payment or incentive. If '
    'the household-facing explanation states a numeric cost change, it must match a listed '
    'supported_benefit_claim amount and unit; otherwise correct it or remove the number.\n'
)


def resolve(raw, *, inputs, loop, config, sim_h, horizon, bounds, event, ask):
    import json
    runner, _ = upstream()
    # Same event/stage/context cache scope as the native adaptive controller.
    event_id = str((event or {}).get('id', ''))
    active = bool(event and event['trigger_h'] <= sim_h < event['end_h'])
    key = f"{event_id}:{'active' if active else 'pre_event'}" if event_id else ''
    fingerprint = runner._adaptive_v3_review_cache_key(key, {
        'planning_inputs': inputs, 'advisor_candidates': []})
    cache = getattr(loop, 'agent_professional_review_cache', {})
    if not isinstance(cache, dict):
        cache = {}
    loop.agent_professional_review_cache = cache

    def review(payload):
        return runner._adaptive_v3_cached_impact_review(
            cache, scope=f'{key}:{fingerprint}' if key else '',
            evidence_payload=payload,
            call_model=lambda: ask(IMPACT_FEEDBACK + json.dumps(payload, ensure_ascii=False),
                                   purpose='evidence_review'))

    return runner._adaptive_v3_resolve_planning_response(
        raw, planning_inputs=inputs,
        policy_error_fn=lambda plan: runtime_errors(plan, loop=loop, config=config,
            sim_h=sim_h, horizon=horizon, bounds=bounds, event=event),
        replan_fn=lambda feedback: ask(
            SEMANTIC_FEEDBACK + json.dumps(feedback, ensure_ascii=False), purpose='semantic_repair'),
        impact_review_fn=review if key else None)
