"""Replace a complete tank model through named installation ports only."""
import copy

from .common import ROOT, digest, read, require
from .idf import Fields, objects, parse
from .parameter_pack import field_definitions
from .source_adapter import source_file


def replace_complete_tank(rows, donor_ref, donor_schema_ref, target_schema_ref, *, target_name, root=ROOT):
    donor = parse(source_file(donor_ref, root).read_text())
    source_fields = Fields(source_file(donor_schema_ref, root))
    target_fields = Fields(source_file(target_schema_ref, root))
    source_schema = read(source_file(donor_schema_ref, root))
    target_schema = read(source_file(target_schema_ref, root))
    old = [r for r in objects(rows, 'WaterHeater:Stratified') if r[1] == target_name]
    tanks, sizes = objects(donor, 'WaterHeater:Stratified'), objects(donor, 'WaterHeater:Sizing')
    old_sizes = [r for r in objects(rows, 'WaterHeater:Sizing') if r[1] == target_name]
    require(len(old) == len(tanks) == len(sizes) == len(old_sizes) == 1
            and sizes[0][1] == tanks[0][1], 'COMPLETE_TANK_SOURCE_AMBIGUOUS')
    old, tank = old[0], tanks[0]
    require(source_fields.get(tank, 'ambient_temperature_indicator') ==
            target_fields.get(old, 'ambient_temperature_indicator') == 'Zone', 'COMPLETE_TANK_AMBIENT_PORT')
    for kind in ('WaterHeater:Stratified', 'WaterHeater:Sizing'):
        a, _ = field_definitions(source_schema, kind); b, _ = field_definitions(target_schema, kind)
        require([n for n, _ in a] == [n for n, _ in b], 'COMPLETE_TANK_FIELD_MIGRATION_REQUIRED', kind)
        require(all(x.get('default') == y.get('default') for (_, x), (_, y) in zip(a, b)),
                'COMPLETE_TANK_DEFAULT_MIGRATION_REQUIRED', kind)
    # Every physical field is retained, including explicit blanks and trailing
    # defaults. This is not changing a node-count field on the old tank.
    after = copy.deepcopy(tank); aliases = {}
    for key in ('name', 'heater_1_setpoint_temperature_schedule_name',
                'heater_2_setpoint_temperature_schedule_name', 'ambient_temperature_zone_name',
                'use_side_inlet_node_name', 'use_side_outlet_node_name'):
        value = target_fields.get(old, key)
        require(value, 'COMPLETE_TANK_INSTALLATION_PORT_MISSING', key)
        aliases[key] = {'source': source_fields.get(tank, key), 'installed': value}
        target_fields.set(after, key, value)
    require(not source_fields.get(tank, 'source_side_inlet_node_name')
            and not source_fields.get(tank, 'source_side_outlet_node_name')
            and not target_fields.get(old, 'source_side_inlet_node_name')
            and not target_fields.get(old, 'source_side_outlet_node_name'), 'COMPLETE_TANK_SECONDARY_LOOP_UNSUPPORTED')
    for key in source_fields.names(tank[0]):
        if key not in aliases:
            require(source_fields.get(tank, key) == target_fields.get(after, key),
                    'COMPLETE_TANK_PHYSICAL_PARAMETER_CHANGED', key)
    size = copy.deepcopy(sizes[0]); target_fields.set(size, 'waterheater_name', target_name)
    result = copy.deepcopy(rows)
    result[result.index(old)] = after; result[result.index(old_sizes[0])] = size
    return result, {'schema': 'national_idf.complete_tank_replacement.v1',
        'source_model': donor_ref, 'source_schema': donor_schema_ref, 'target_schema': target_schema_ref,
        'source_tank': tank, 'retired_tank': old, 'installed_tank': after,
        'source_sizing': sizes[0], 'retired_sizing': old_sizes[0], 'installed_sizing': size,
        'installation_aliases': aliases, 'physical_fields_and_defaults_preserved': True,
        'all_other_rows_retained': True, 'source_tank_row_sha256': digest(tank),
        'changes': [{'before': old, 'after': after}, {'before': old_sizes[0], 'after': size}],
        'formal_admitted': False}
