"""Inspect exact inventory retirement and its air/water/thermal side effects."""
import copy
import re

from .common import ROOT, require
from .idf import objects
from .source_adapter import selected, selector


def rebase(source, pack, target):
    """Apply an existing source transaction after diagnostic/report preparation.

    Every nonreporting owner must still match its complete original row. This
    cannot delete a changed consumer,guess its share or modify HVAC/geometry.
    """
    changes = []
    for operation in pack['changes']:
        before = selected(source, operation['object'])
        hits = [i for i, row in enumerate(target) if row == before]
        if not hits and before[0].startswith('Output:'): continue
        require(len(hits) == 1, 'RETIREMENT_DIAGNOSTIC_OWNER_CHANGED', before[:2])
        value = copy.deepcopy(operation); value['object'] = selector(target, hits[0]); changes.append(value)
    return changes


def audit(before, after, pack, fields):
    protected = ('Zone', 'Space', 'BuildingSurface:Detailed', 'FenestrationSurface:Detailed',
        'Material', 'Construction', 'WaterHeater:Stratified', 'Site:WaterMainsTemperature',
        'WaterUse:Equipment', 'EnergyManagementSystem:Program')
    retired = {name for names in pack['retired_physical_object_names'].values() for name in names}
    for kind in protected:
        expected = [row for row in objects(before, kind) if row[1] not in retired]
        require(expected == objects(after, kind), 'RETIREMENT_UNRELATED_PHYSICS_CHANGED', kind)
    for prefix in ('Coil:', 'Fan:', 'Pump:', 'Foundation:'):
        require([r for r in before if r[0].startswith(prefix)] == [r for r in after if r[0].startswith(prefix)],
                'RETIREMENT_THERMAL_NETWORK_CHANGED', prefix)
    require(not any(r[0] in ('ElectricEquipment', 'OtherEquipment', 'WaterUse:Equipment') and r[1] in retired for r in after),
            'RETIREMENT_DEVICE_CONSUMER_REMAINS')
    water = {r[1] for r in objects(before, 'WaterUse:Equipment') if r[1] in retired}
    require(objects(after, 'WaterUse:Connections') == [[v for v in r if v not in water] for r in objects(before, 'WaterUse:Connections')],
            'RETIREMENT_WATER_CONNECTIONS_NOT_EXACT')
    dryer = None
    if 'dryer' in pack['retired_physical_object_names']:
        assignments = [line for row in objects(before, 'EnergyManagementSystem:Program') for line in row[2:]
                       if re.match(r'^\s*Set\s+Qdryer\s*=', line, re.I)]
        require(assignments and all(re.fullmatch(r'\s*Set\s+Qdryer\s*=\s*0(?:\.0*)?\s*', line, re.I) for line in assignments),
                'RETIREMENT_NONZERO_DRYER_EXHAUST_NOT_IMPLEMENTED')
        require(not any('dryer' in ' '.join(r).casefold() for r in objects(before, 'EnergyManagementSystem:Sensor')),
                'RETIREMENT_DRYER_FLOW_SENSOR_NOT_REVIEWED')
        require(not any('dryer' in ' '.join(r).casefold() for r in objects(before, 'Fan:ZoneExhaust')),
                'RETIREMENT_DRYER_FAN_NOT_REVIEWED')
        dryer = {'complete_source_explicit_Qdryer_assignments': assignments,
            'original_dryer_exhaust_already_zero': True, 'no_dryer_schedule_sensor_or_exhaust_fan': True,
            'arbitrary_vented_or_condensing_product_physics_claimed': False}
    return {'schema': 'national_idf.reference_inventory_side_effect_audit.v1',
        'retired_consumers': pack['retired_physical_object_names'], 'retired_water_consumers': sorted(water),
        'water_network_exactly_filtered': True, 'no_retired_power_water_or_gain_owner_remains': True,
        'remaining_geometry_materials_HVAC_tank_general_water_and_EMS_unchanged': True,
        'dryer_airflow': dryer, 'vehicle_ownership_inferred_from_absent_home_charging': False,
        'source_aggregate_water_gains_remain_explicit_independent_background': True, 'formal_admitted': False}
