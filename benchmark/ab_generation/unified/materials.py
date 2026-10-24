"""Self-contained questionnaire projection; no answers or physical estimates."""
import copy
from ..common import digest


def project(c, profile, row, B):
    from benchmark.family_generation.portrait_v3 import render
    needs=set(row['program_needs'])
    related=[n for n in c['needs'] if n['need_id'] in needs or
             (n['release_min']<1920 and n['deadline_min']>480 and
              n['kind'] not in ('washer','dryer','dishwasher'))]
    projection=dict(schema='eb.questionnaire_context.v2',
        household_text=render(profile) if profile else None,
        equipment=copy.deepcopy(c['devices']), original_requirements=copy.deepcopy(related),
        operator_availability=copy.deepcopy(c['operator_windows']),
        room_occupancy=copy.deepcopy(c.get('occupancy',{})),
        reservations=copy.deepcopy(c.get('reservations',[])),
        electrical_constraints=copy.deepcopy(c.get('electrical')),
        original_authority=copy.deepcopy(c.get('authority',{})),
        nominal_EV_steps=copy.deepcopy(c['reference'].get('ev_charging_steps',[])),
        physical_EV_connections=copy.deepcopy(c.get('physical_ev_connections',[])),
        event=dict(start_min=1080,end_min=1140),
        reasons=copy.deepcopy(row['asset_change_reasons']),
        member_and_permission_context=copy.deepcopy(row['judgment_context']),
        plan_checks=copy.deepcopy(row['issues']),
        known_program_event_reduction_kWh=row['known_event_reduction_kWh'],
        analytic_quantity_scope='declared_fixed_program_and_nominal_EV_model;not_measured_physical_response',
        physical_outcomes=None,physical_status='not_computed',
        participant_notice='方案B是待确认提议；用电、费用、室温和供水等实际后果尚未计算。请依据家庭资料和安排判断，不必猜测实际结果。',
        human_acceptance=None,human_score=None,human_reason=None)
    projection['binding']=dict(A_sha256=digest(c['A']),B_sha256=digest(B),
        portrait_sha256=digest(profile),context_sha256=digest(c))
    return projection
