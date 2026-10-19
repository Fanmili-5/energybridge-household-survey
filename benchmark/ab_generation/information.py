"""Explicit information available before B; no real-time forecaster is supplied."""
import copy


def information_set(mode, decision_min, reference_span_min):
    if mode not in ('offline_full_A_counterfactual', 'synthetic_interface_fixture', 'offline_unexecuted_A_plan'):
        raise ValueError('UNSUPPORTED_INFORMATION_MODE;no_real_time_forecaster_implemented')
    return {'schema': 'eb.ab_information_set.v1', 'mode': mode,
            'decision_min': decision_min, 'A_reference_span_min': list(reference_span_min),
            'future_A_scope': ('complete_supplied_commands_and_analytic_EV_plan;no_future_thermal_states'
                               if mode == 'offline_unexecuted_A_plan' else
                               'complete_supplied_A_reference;including_EV_connection_completion_and_tail'),
            'future_A_available': True, 'final_B_outcomes_available': False,
            'human_answers_available': False, 'real_time_deployment_claim': False,
            'forecaster': None}


def checked_information(context):
    value = context['reference'].get('information_set')
    if not isinstance(value, dict):
        raise ValueError('INFORMATION_SET_REQUIRED;rebuild_or_reimport_A_reference')
    if value.get('mode') == 'offline_unexecuted_A_plan' and context['reference'].get('thermal'):
        raise ValueError('UNEXECUTED_PLAN_CANNOT_DECLARE_THERMAL_STATE')
    span = value.get('A_reference_span_min')
    if (not isinstance(span, list) or len(span) != 2 or any(type(t) is not int for t in span)
            or not span[0] <= context['horizon_min'][0] < context['horizon_min'][1] <= span[1]):
        raise ValueError('INVALID_A_INFORMATION_COVERAGE')
    for rows in context['reference'].get('thermal', {}).values():
        if any(not span[0] <= r['minute'] < span[1] for r in rows):
            raise ValueError('A_INFORMATION_COVERAGE_UNDERSTATED')
    if any(not span[0] <= r['start_min'] < r['end_min'] <= span[1]
           for r in context['reference'].get('ev_charging_steps', [])):
        raise ValueError('A_INFORMATION_COVERAGE_UNDERSTATED')
    expected = information_set(value.get('mode'), context['decision_min'], span)
    # Require actual booleans: 0/1 must not silently satisfy an information claim.
    if value != expected or any(type(value.get(k)) is not bool for k in
            ('future_A_available', 'final_B_outcomes_available', 'human_answers_available', 'real_time_deployment_claim')):
        raise ValueError('INFORMATION_SET_CONTRADICTION')
    return copy.deepcopy(value)


PROPOSAL_PURPOSE = {
    'schema': 'eb.ab_proposal_purpose.v1',
    'purpose': 'synthetic_counterfactual_proposals_for_independent_judgment',
    'original_EnergyBridge_controller_output': False,
    'physical_execution_interpretation': 'counterfactual_if_B_applied;not_observed_household_consent',
    'rejection_reference': 'frozen_event_free_A',
    'human_acceptance': None,
    'human_satisfaction': None,
    'policy_ranks_are_human_preference_estimates': False,
}
