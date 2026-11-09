"""One whole-home command broadcast to explicit, independently connected ports.

The existing EB binding owns all six device accounts exactly once. Additional
bindings have no appliances and only write HVAC schedules and observe room air.
No room merging, capacity allocation, or new appliance physics is performed.
"""
from .common import require
from .idf import objects


def validate_ports(rows, mapping, fields):
    extra = mapping.get('additional_hvac', [])
    require(isinstance(extra, list), 'EB_HVAC_PORTS_NOT_LIST')
    ports = [mapping['hvac']]+extra
    zones, controls = set(), set()
    for port in ports:
        def one(kind, name):
            found = [r for r in objects(rows, kind) if r[1].casefold() == name.casefold()]
            require(len(found) == 1, 'EB_OBJECT_MAPPING_MISSING_OR_AMBIGUOUS', [kind, name])
            return found[0]
        zone = port['zone']; one('Zone', zone)
        require(zone.casefold() not in zones, 'EB_HVAC_PORT_ZONE_REPEATED'); zones.add(zone.casefold())
        one('Schedule:Constant', port['availability'])
        require(any(fields.get(r, 'schedule_name').casefold() == port['availability'].casefold()
            for r in objects(rows, 'AvailabilityManager:Scheduled')), 'HVAC_AVAILABILITY_NOT_CONNECTED')
        for role in ('heating', 'cooling'):
            one(port[role]['kind'], port[role]['schedule'])
        thermostats = [r for r in objects(rows, 'ThermostatSetpoint:DualSetpoint')
            if fields.get(r, 'heating_setpoint_temperature_schedule_name') == port['heating']['schedule']
            and fields.get(r, 'cooling_setpoint_temperature_schedule_name') == port['cooling']['schedule']]
        require(thermostats, 'THERMOSTAT_NOT_CONNECTED')
        if extra:
            for name in [port['availability'], port['heating']['schedule'], port['cooling']['schedule']]:
                require(name.casefold() not in controls, 'EB_HVAC_CONTROL_SHARED_BETWEEN_PORTS')
                controls.add(name.casefold())
            connected = [r for r in objects(rows, 'ZoneHVAC:EquipmentConnections') if r[1].casefold() == zone.casefold()]
            require(len(connected) == 1, 'EB_HVAC_PORT_ZONE_NOT_CONNECTED')
            # A matching setpoint elsewhere in the building does not bind this room.
            require(len(thermostats) == 1 and any(
                fields.get(r, 'zone_or_zonelist_name').casefold() == zone.casefold()
                and fields.get(r, 'control_1_object_type') == 'ThermostatSetpoint:DualSetpoint'
                and fields.get(r, 'control_1_name') == thermostats[0][1]
                for r in objects(rows, 'ZoneControl:Thermostat')), 'EB_HVAC_PORT_THERMOSTAT_ZONE_MISMATCH')
    return ports


class MultiPortBinding:
    """Compose unmodified EB bindings; the primary retains device ownership."""
    def __init__(self, primary, extras):
        self.primary, self.extras = primary, extras
        require(all(not b.equipment and not b.suite._water_heater.present for b in extras),
            'EB_HVAC_EXTRA_BINDING_HAS_DEVICE_OWNER')

    def __getattr__(self, name):
        return getattr(self.primary, name)

    def request_outputs(self, exchange, state):
        self.primary.request_outputs(exchange, state)
        for binding in self.extras:
            variable, key = binding.outputs['zone_temperature_C']
            exchange.request_variable(state, variable, key)

    def initialize(self, exchange, state):
        self.primary.initialize(exchange, state)
        for binding in self.extras: binding.initialize(exchange, state)

    def write(self, exchange, state, powers, **control):
        self.primary.write(exchange, state, powers, **control)
        for binding in self.extras: binding.write(exchange, state, {}, **control)

    def observe_system(self, exchange, state, day_idx):
        self.primary.observe_system(exchange, state, day_idx)

    def observe(self, exchange, state, day_idx):
        row = self.primary.observe(exchange, state, day_idx)
        for binding in [self.primary]+self.extras:
            zone = binding.mapping['hvac']['zone']
            row['HVAC_zone_temperature_C:'+zone] = float(exchange.get_variable_value(
                state, binding.output_handles['zone_temperature_C']))
        return row


def bind(binding_module, suite_module, model, schema, suite, mapping, days):
    primary = binding_module.ApplianceBinding(model, schema, suite, mapping)
    if not mapping.get('additional_hvac'): return primary
    extras = []
    for port in mapping['additional_hvac']:
        empty = {name: {'present': False} for name in
            ('washer', 'dryer', 'dishwasher', 'water_heater', 'ev', 'refrigerator')}
        disabled = suite_module.ApplianceSuite(empty, days, [], explicit_only=True)
        extras.append(binding_module.ApplianceBinding(model, schema, disabled,
            {'equipment': {}, 'hvac': port}))
    return MultiPortBinding(primary, extras)
