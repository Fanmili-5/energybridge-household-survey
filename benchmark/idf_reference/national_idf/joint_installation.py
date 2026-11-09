"""Bind existing complete source HVAC and install the frozen outdoor EB EV.

This does not transplant an HVAC air/EMS context into a different house. Such
targets receive an explicit gap while the independent EV installation proceeds.
"""
import copy

from .common import ROOT, read, require
from .ev_reference import hardware_parameters
from .idf import Fields, objects, parse
from .program_resources import model_signature
from .source_adapter import equipment_zone, housing_fingerprint, selected, source_file
from .source_hvac import isolate_hvac_availability


def apply(rows, pack_ref, schema_ref, *, root=ROOT):
    pack = read(source_file(pack_ref, root))
    require(pack.get('schema') == 'national_idf.EB_hvac_EV_installation.v1', 'JOINT_INSTALLATION_SCHEMA')
    for evidence in pack['evidence']: source_file(evidence, root)
    fields = Fields(source_file(schema_ref, root))
    zone = pack['installation_zone']; require(equipment_zone(rows, zone, fields) == zone, 'JOINT_TARGET_ZONE_MISSING')
    hardware = hardware_parameters(pack['EV_reference'], root)['hardware']
    template = parse(source_file(pack['EV_template_model'], root).read_text())
    ev = copy.deepcopy(selected(template, pack['EV_template_equipment']))
    schedule = copy.deepcopy(selected(template, pack['EV_template_schedule']))
    require(ev[0] == 'ElectricEquipment' and schedule[0] == 'Schedule:Constant'
        and float(fields.get(ev, 'design_level')) == hardware['charger_kw']*1000
        and all(float(fields.get(ev, name)) == value for name, value in (
            ('fraction_latent', 0), ('fraction_radiant', 0), ('fraction_lost', 1))), 'EV_INSTALLATION_TEMPLATE_NOT_BOUND')
    context_matched = model_signature(rows) == pack['expected_source_context_signature']
    existing = [r for r in objects(rows, 'ElectricEquipment') if r[1].casefold() == ev[1].casefold()]
    reuse_EV = pack.get('reuse_exact_source_EV', False)
    fields.set(ev, 'zone_or_zonelist_or_space_or_spacelist_name', zone)
    if reuse_EV:
        require(context_matched and existing == [ev] and objects(rows, 'Schedule:Constant').count(schedule) == 1,
            'JOINT_EXISTING_EV_NOT_EXACT_SOURCE')
    require(not any('Storage' in row[0] and row[0].startswith('ElectricLoadCenter:') for row in rows)
        and (reuse_EV or not existing), 'JOINT_UNRETIRED_EV_OR_STORAGE')
    result = copy.deepcopy(rows); changes, gaps = [], []
    network, group = None, None
    require(not (pack.get('hvac_network') and pack.get('hvac_network_group')), 'JOINT_AMBIGUOUS_HVAC_INSTALLATION')
    if pack.get('hvac_network_group'):
        from .hvac_network import apply_group
        group = read(source_file(pack['hvac_network_group'], root))
        require(group.get('schema') == 'national_idf.sourced_ductless_hvac_group.v1'
            and group.get('formal_admitted') is False
            and group.get('capacity_selection_approved') is False
            and group.get('whole_home_service_verified') is False, 'JOINT_HVAC_GROUP_SCOPE')
        require(group.get('ports') and group['ports'][0]['EB_port']['zone'] == zone,
            'JOINT_HVAC_EV_TARGET_ZONE_MISMATCH')
        scope = read(source_file(group['dwelling_scope'], root))
        require(scope.get('schema') == 'national_idf.housing_rule_derivation.v1'
            and scope.get('complete_source_model_kept') is True
            and all(p['EB_port']['zone'] in scope['reviewed_dwelling']['room_names'] for p in group['ports']),
            'JOINT_HVAC_GROUP_OUTSIDE_REVIEWED_DWELLING')
        result, networks = apply_group(result, [p['network'] for p in group['ports']], schema_ref, root=root)
        for port, item in zip(group['ports'], networks):
            require(port['EB_port']['zone'] == item['target_zone'], 'JOINT_HVAC_PORT_ZONE_MISMATCH')
            result, overlay = isolate_hvac_availability(result, fields, **port['availability_overlay'])
            require(port['EB_port']['availability'] == port['availability_overlay']['schedule_name'],
                'JOINT_HVAC_PORT_AVAILABILITY_MISMATCH')
            changes += [{'action': 'add', 'before': None, 'after': x['after']} for x in item['source_objects']]
            changes += overlay
        network = {'target_zone': zone, 'ports': networks, 'structural_installation_complete': True,
            'independent_target_load_sizing_approved': False, 'formal_admitted': False}
    if pack.get('hvac_network'):
        from .hvac_network import apply as install_hvac
        result, network = install_hvac(result, pack['hvac_network'], schema_ref, root=root)
        require(network['target_zone'] == zone, 'JOINT_HVAC_EV_TARGET_ZONE_MISMATCH')
        changes += [{'action': 'remove', 'before': row, 'after': None} for row in network['retired_objects']]
        changes += [{'action': 'add', 'before': None, 'after': item['after']} for item in network['source_objects']]
    if context_matched or network is not None:
        if group is None:
            result, overlay = isolate_hvac_availability(result, fields, **pack['HVAC_availability_overlay'])
            changes += overlay
        require(not any(row[0].startswith('Coil:Heating:') and row[0] != 'Coil:Heating:DX:MultiSpeed'
            for row in result), 'JOINT_HIDDEN_BACKUP_HEATER')
        if network is not None and network.get('retained_ideal_context'):
            require(network['retained_ideal_context']['target_zone'] == zone and
                    network['retained_ideal_context']['target_ideal_systems_remaining'] == 0,
                    'JOINT_TARGET_IDEAL_HVAC_REMAINS')
        else:
            require(not objects(result, 'ZoneHVAC:IdealLoadsAirSystem'), 'JOINT_IDEAL_HVAC_REMAINS')
    else:
        gaps.append({'code': 'HVAC_SOURCE_AIR_CONTEXT_TRANSFER_NOT_REVIEWED',
            'detail': 'Source curves/defrost are available; target air connections, installation and design sizing are not verified. No foreign air/EMS graph is spliced in.'})
    limits = fields.get(schedule, 'schedule_type_limits_name')
    extra = []
    if not reuse_EV and not any(row[1] == limits for row in objects(result, 'ScheduleTypeLimits')):
        matches = [r for r in objects(template, 'ScheduleTypeLimits') if r[1] == limits]
        require(len(matches) == 1, 'JOINT_EV_FRACTION_LIMITS_MISSING')
        extra = copy.deepcopy(matches)
    if not reuse_EV:
        require(not any(row[1].casefold() == schedule[1].casefold() for row in objects(result, 'Schedule:Constant')), 'JOINT_EV_SCHEDULE_COLLISION')
        result += extra+[schedule, ev]
    require(housing_fingerprint(result) == housing_fingerprint(rows), 'JOINT_INSTALLATION_CHANGED_HOUSING')
    return result, {'schema': 'national_idf.EB_hvac_EV_installation_receipt.v1', 'pack': pack_ref,
        'ready': not gaps, 'gaps': gaps, 'HVAC_source_context_matched': context_matched,
        'HVAC_changes': changes, 'EV_inserted': [] if reuse_EV else extra+[schedule, ev], 'EV_hardware': hardware,
        **({'HVAC_network': network, 'EV_reused_exact_source': reuse_EV} if network is not None else {}),
        **({'HVAC_ports': [p['EB_port'] for p in group['ports']],
            'HVAC_group': pack['hvac_network_group']} if group is not None else {}),
        'EV_outside_indoor_heat_balance': True, 'EV_physical_parameters_modified': False,
        'HVAC_performance_parameters_modified': False, 'formal_admitted': False}
