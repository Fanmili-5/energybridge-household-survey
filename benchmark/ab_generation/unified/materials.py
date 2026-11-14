"""Self-contained questionnaire projection; no answers or physical estimates."""
import copy
from ..common import digest


def project(c, profile, row, B):
    from benchmark.family_generation.portrait_v3 import render
    events=c.get('events', [])
    event=copy.deepcopy(row.get('scene_event') or (events[0] if len(events)==1 else None))
    scene=bool(row.get('scene_event') or row.get('scene_policy'))
    if scene and event is None:raise ValueError('QUESTIONNAIRE_EVENT_CONTEXT_REQUIRED')
    if scene and (len(events)!=1 or event!=events[0]):
        raise ValueError('QUESTIONNAIRE_SCENE_EVENT_MISMATCH')
    # Pre-scene public fixtures declared the fixed event via their recipe.
    # This compatibility path is never available to a scene-marked proposal.
    legacy_fixed_event=event is None
    if legacy_fixed_event:event=dict(start_min=1080,end_min=1140)
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
        event=event,event_context_source='legacy_fixed18_19_recipe' if legacy_fixed_event else 'explicit_scene_context',
        reasons=copy.deepcopy(row['asset_change_reasons']),
        member_and_permission_context=copy.deepcopy(row['judgment_context']),
        plan_checks=copy.deepcopy(row['issues']),
        known_program_event_reduction_kWh=row['known_event_reduction_kWh'],
        analytic_quantity_scope='declared_fixed_program_and_nominal_EV_model;not_measured_physical_response',
        physical_outcomes=None,physical_status='not_computed',
        participant_notice='方案B是待确认提议；用电、费用、室温和供水等实际后果尚未计算。请依据家庭资料和安排判断，不必猜测实际结果。',
        human_acceptance=None,human_score=None,human_reason=None)
    if row.get('change_axes_version'):
        from .change_axes import presentation
        projection['action_changes']=[dict(component_id=x['id'],family=x['family'],
            axes=copy.deepcopy(x['change_axes']),text=presentation(x)) for x in row['components']]
        projection['change_axes_version']=row['change_axes_version']
    projection['binding']=dict(A_sha256=digest(c['A']),B_sha256=digest(B),
        portrait_sha256=digest(profile),context_sha256=digest(c))
    return projection
