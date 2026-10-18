"""Declared authority and inherited project constraints; never infer preferences."""
import copy


def authority(pack, windows):
    world = pack['world']; devices = world['parameter_pack']['devices']
    target = pack['household_id']; members = world.get('members', [])
    modern = bool(members) and all('household_id' in m and 'can_operate_asset_ids' in m for m in members)
    context_ids = {mid for day in pack['days'].values() for mid in day['shared']['member_calendars']}
    if modern:
        target_ids = {m['member_id'] for m in members if m['household_id'] == target}
        context_ids |= {m['member_id'] for m in members if m['household_id'] != target}
    else:
        # AC84 operator windows are the declared original A46 operators, including
        # any explicitly given assistance. Shared resident calendars grant no rights.
        target_ids = set(windows) - context_ids
    assets = {}
    for d in devices:
        aid = d['asset_id']
        operators = ({m['member_id'] for m in members if aid in m['can_operate_asset_ids']
                      and m['household_id'] in d['using_household_ids']} if modern else set(target_ids))
        assets[aid] = {'authorized_operator_ids': sorted(operators),
                       'target_control_authorized': bool(operators & target_ids) if modern else d.get('operator_id') in target_ids}
    return {'schema': 'eb.ab_authority.v1', 'assets': assets,
            'immutable_operator_ids': sorted(context_ids),
            'origin': 'declared_spatial_member_and_asset_rights' if modern else 'inherited_A46_original_operator_windows'}


def legacy_program_constraints(needs):
    """Explicit transfer of the pinned A46 scheduler's project assumptions."""
    result = copy.deepcopy(needs)
    for n in result:
        if n['kind'] in ('washer', 'dryer', 'dishwasher'):
            n.update(timer_allowed=True, maximum_preload_wait_min=720,
                     machine_windows_min=[[390, 1410]],
                     constraint_origin='pinned_A46_scheduler_project_rules;not_observed_hardware_capability')
    return result
