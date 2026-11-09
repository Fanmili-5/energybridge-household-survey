"""Explicit household air-node reduction, preserving source room enclosures.

This experimental adapter supplies no physical data and grants no admission.
Its applicability must be established against the unreduced source model.
"""
import copy

from .common import digest, require
from .idf import objects


def group_air_nodes(rows, memberships, fields):
    """Keep every face and source Space; merge only explicitly listed air nodes.

    Input is an unoccupied enclosure/airflow fixture, not an installed household.
    Reassigning existing HVAC, people, water or equipment needs its own adapter.
    Prescribed ACH objects become exact original-volume flow objects, avoiding
    multiplying an old room ACH by the larger merged household volume.
    """
    zones = {r[1]: r for r in objects(rows, 'Zone')}
    require(len(zones) == len(objects(rows, 'Zone')), 'WHOLEHOME_DUPLICATE_ZONE')
    owner = {}
    for group, names in memberships.items():
        require(group and names and group not in zones, 'WHOLEHOME_GROUP_NAME')
        for name in names:
            require(name in zones and name not in owner, 'WHOLEHOME_PARTITION_CONFLICT', name)
            owner[name] = group
    require(set(owner) == set(zones), 'WHOLEHOME_PARTITION_INCOMPLETE')
    permitted = {'Version', 'Building', 'GlobalGeometryRules', 'Zone',
        'BuildingSurface:Detailed', 'FenestrationSurface:Detailed', 'Material',
        'Construction', 'WindowMaterial:SimpleGlazingSystem',
        'SurfaceProperty:ConvectionCoefficients', 'Schedule:Constant',
        'Schedule:Compact', 'ScheduleTypeLimits', 'ZoneVentilation:DesignFlowRate',
        'SimulationControl', 'Timestep', 'HeatBalanceAlgorithm',
        'SurfaceConvectionAlgorithm:Inside', 'SurfaceConvectionAlgorithm:Outside',
        'Site:Location', 'Site:GroundReflectance', 'Site:GroundTemperature:BuildingSurface',
        'Site:HeightVariation', 'ZoneAirHeatBalanceAlgorithm', 'ShadowCalculation',
        'RunPeriod', 'Output:SQLite', 'Output:VariableDictionary', 'Output:Diagnostics',
        'Output:Variable', 'OutputControl:Files', 'Output:Constructions'}
    require(all(r[0] in permitted for r in rows), 'WHOLEHOME_UNREVIEWED_INSTALLED_OBJECT',
            sorted({r[0] for r in rows} - permitted))
    geometry = objects(rows, 'GlobalGeometryRules')
    require(len(geometry) == 1 and geometry[0][3] == 'Relative', 'WHOLEHOME_COORDINATES')
    for zone in zones.values():
        require(all(float(fields.get(zone, key, 0)) == 0 for key in
            ('direction_of_relative_north', 'x_origin', 'y_origin', 'z_origin')) and
            float(fields.get(zone, 'multiplier', 1)) == 1 and
            float(fields.get(zone, 'volume')) > 0 and float(fields.get(zone, 'floor_area')) > 0,
            'WHOLEHOME_ZONE_GEOMETRY_UNSUPPORTED', zone[1])
    result = copy.deepcopy([r for r in rows if r[0] != 'Zone'])
    for group, names in memberships.items():
        result.append(fields.obj('Zone', name=group, direction_of_relative_north=0,
            x_origin=0, y_origin=0, z_origin=0, type=1, multiplier=1,
            ceiling_height='Autocalculate', volume=sum(float(fields.get(zones[n], 'volume')) for n in names),
            floor_area=sum(float(fields.get(zones[n], 'floor_area')) for n in names)))
        for name in names:
            result.append(fields.obj('Space', name='source_space_'+name, zone_name=group,
                ceiling_height='Autocalculate', volume=fields.get(zones[name], 'volume'),
                floor_area=fields.get(zones[name], 'floor_area')))
    changes = []
    for row in objects(result, 'BuildingSurface:Detailed'):
        zone = fields.get(row, 'zone_name')
        require(zone in owner and not fields.get(row, 'space_name'), 'WHOLEHOME_SURFACE_PORT')
        fields.set(row, 'zone_name', owner[zone])
        fields.set(row, 'space_name', 'source_space_'+zone)
    for row in objects(result, 'ZoneVentilation:DesignFlowRate'):
        zone = fields.get(row, 'zone_or_zonelist_or_space_or_spacelist_name')
        require(zone in zones and fields.get(row, 'design_flow_rate_calculation_method') == 'AirChanges/Hour',
                'WHOLEHOME_VENTILATION_PORT')
        before = copy.deepcopy(row)
        original_volume = float(fields.get(zones[zone], 'volume'))
        rate = float(fields.get(row, 'air_changes_per_hour'))
        fields.set(row, 'zone_or_zonelist_or_space_or_spacelist_name', 'source_space_'+zone)
        fields.set(row, 'design_flow_rate_calculation_method', 'Flow/Zone')
        fields.set(row, 'design_flow_rate', original_volume*rate/3600)
        fields.set(row, 'air_changes_per_hour', '')
        changes.append({'before': before, 'after': copy.deepcopy(row),
                        'original_room_volume_m3': original_volume})
    invariant = lambda values: digest([r for r in values if r[0] not in
        ('Zone', 'Space', 'BuildingSurface:Detailed', 'ZoneVentilation:DesignFlowRate')])
    require(invariant(rows) == invariant(result), 'WHOLEHOME_FOREIGN_PHYSICS_CHANGED')
    before_faces = objects(rows, 'BuildingSurface:Detailed')
    after_faces = objects(result, 'BuildingSurface:Detailed')
    strip_port = lambda r: r[:4]+r[6:]
    require([strip_port(r) for r in before_faces] == [strip_port(r) for r in after_faces],
            'WHOLEHOME_FACE_GEOMETRY_OR_BOUNDARY_CHANGED')
    return result, {'groups': memberships, 'original_air_nodes': len(zones),
        'grouped_air_nodes': len(memberships), 'source_room_spaces': len(zones),
        'all_face_geometry_materials_and_adjacency_retained': True,
        'prescribed_airflow_original_volume_conserved': changes,
        'uniform_household_air_is_experimental_reduction': True,
        'thermal_reduction_validated': False, 'formal_admitted': False}
