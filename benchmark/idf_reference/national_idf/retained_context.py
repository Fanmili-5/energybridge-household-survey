"""Preserve explicit source neighbours, never a target dwelling's ideal heater.

The optional scope is a hash-bound source record, not a CASE override. Current
support is deliberately limited to individually named source zones, each with
one IdealLoads system and its own equipment list, connection and thermostat.
"""
from pathlib import Path
from .common import ROOT, read, require, sha
from .idf import objects, parse
from .source_adapter import selected, selector, source_file


def unique(rows, kind, name):
    found = [r for r in objects(rows, kind) if r[1].casefold() == name.casefold()]
    require(len(found) == 1, 'CONTEXT_OBJECT_NOT_UNIQUE', [kind, name])
    return found[0]


def ideal_groups(rows, fields):
    zones = {r[1].casefold(): r[1] for r in objects(rows, 'Zone')}
    groups, claimed = {}, set()
    for connection in objects(rows, 'ZoneHVAC:EquipmentConnections'):
        zone = fields.get(connection, 'zone_name')
        require(zone.casefold() in zones and zone.casefold() not in groups,
                'CONTEXT_ZONE_CONNECTION_NOT_UNIQUE', zone)
        listing = unique(rows, 'ZoneHVAC:EquipmentList',
                         fields.get(connection, 'zone_conditioning_equipment_list_name'))
        # This source scope does not guess ownership of shared equipment,
        # multiple zone components, central loops or autosized neighbour fans.
        require(len(listing) == 7 and listing[3] == 'ZoneHVAC:IdealLoadsAirSystem',
                'CONTEXT_REQUIRES_SINGLE_SOURCE_IDEAL_SYSTEM', zone)
        ideal = unique(rows, listing[3], listing[4])
        require(ideal[1].casefold() not in claimed, 'CONTEXT_IDEAL_SYSTEM_SHARED', ideal[1])
        claimed.add(ideal[1].casefold())
        thermostats = [r for r in objects(rows, 'ZoneControl:Thermostat')
                       if fields.get(r, 'zone_or_zonelist_name').casefold() == zone.casefold()]
        require(len(thermostats) == 1, 'CONTEXT_THERMOSTAT_NOT_INDIVIDUAL', zone)
        groups[zone.casefold()] = [ideal, listing, connection, thermostats[0]]
    require(claimed == {r[1].casefold() for r in objects(rows, 'ZoneHVAC:IdealLoadsAirSystem')},
            'CONTEXT_UNMAPPED_SOURCE_IDEAL_SYSTEM')
    return groups


def source_scope(context_ref, fields, *, root=ROOT):
    context = read(source_file(context_ref, root))
    require(context.get('schema') == 'national_idf.retained_ideal_context.v1', 'CONTEXT_SCOPE_SCHEMA')
    require(context.get('complete_source_building_retained') is True and
            context.get('neighbours_are_not_household_backup') is True and
            context.get('formal_admitted') is False, 'CONTEXT_SCOPE_CLAIM')
    source = parse(source_file(context['source_model'], root).read_text())
    groups = ideal_groups(source, fields)
    target = context['target_zone'].casefold()
    require(target in groups, 'CONTEXT_TARGET_NOT_SOURCE_UNIT')
    mapping = read(source_file(context['source_dwelling_mapping'], root))
    units = mapping.get('households_explicitly_named_by_source', [])
    require(len([unit for unit in units if unit['id'].casefold() == target]) == 1,
            'CONTEXT_TARGET_NOT_IN_EXPLICIT_DWELLING_MAP')
    require(context['target_retirement'] == [selector(source, source.index(r)) for r in groups[target]],
            'CONTEXT_TARGET_RETIREMENT_CHANGED')
    expected = {zone: [selector(source, source.index(r)) for r in group]
                for zone, group in groups.items() if zone != target}
    require(context['neighbour_groups'] == expected and bool(expected), 'CONTEXT_NEIGHBOUR_GROUPS_CHANGED')
    return context, source, groups


def verify_retained(rows, context_ref, fields, *, root=ROOT):
    context, source, groups = source_scope(context_ref, fields, root=root)
    target = context['target_zone'].casefold()
    expected = [r for zone, group in groups.items() if zone != target for r in group]
    # Shared source thermostat definitions and schedules remain exact. Their
    # values cannot be accidentally rewritten while installing target controls.
    expected += [r for r in source if r[0].startswith(('Schedule:', 'ThermostatSetpoint:'))
                 or r[0] == 'ScheduleTypeLimits']
    expected += [r for r in source if r[0] in ('People', 'Lights', 'ElectricEquipment',
                    'ZoneInfiltration:DesignFlowRate') and len(r) > 2 and r[2].casefold() != target]
    for row in expected:
        require(rows.count(row) == 1, 'CONTEXT_SOURCE_OBJECT_CHANGED_OR_MISSING', row[:2])
    allowed_ideals = [group[0] for zone, group in groups.items() if zone != target]
    require(sorted(objects(rows, 'ZoneHVAC:IdealLoadsAirSystem')) == sorted(allowed_ideals),
            'CONTEXT_TARGET_OR_UNDECLARED_IDEAL_REMAINS')
    other_connections = [r for r in objects(rows, 'ZoneHVAC:EquipmentConnections')
                         if fields.get(r, 'zone_name').casefold() != target]
    require(sorted(other_connections) == sorted(group[2] for zone, group in groups.items() if zone != target),
            'CONTEXT_UNDECLARED_NEIGHBOUR_CONNECTION')
    for item in context['target_retirement']:
        require(selected(source, item) not in rows, 'CONTEXT_TARGET_OLD_SYSTEM_REMAINS', item)
    return {'context': context_ref, 'source_model': context['source_model'],
            'implementation': {'path': 'national_idf/retained_context.py', 'sha256': sha(Path(__file__))},
            'target_zone': context['target_zone'], 'verified_source_objects': len(expected),
            'source_neighbour_ideal_systems_retained': len(allowed_ideals),
            'target_ideal_systems_remaining': 0, 'context_values_modified': False,
            'target_has_hidden_ideal_backup': False, 'formal_admitted': False}
