"""Bind explicit CASE people and fixture demands to existing native objects.

This adapter supplies no household routine, metabolic value, water temperature,
heat fraction or installation parameter. Source-dependent gains remain a
separate review; successful input execution does not release a whole CASE.
"""
import math

from .common import require
from .idf import objects
from .source_adapter import equipment_zone


PEOPLE_OUTPUTS = {
    'persons': 'People Occupant Count',
    'total_W': 'People Total Heating Rate',
    'sensible_J': 'People Sensible Heating Energy',
    'latent_J': 'People Latent Gain Energy',
    'total_J': 'People Total Heating Energy',
}
WATER_OUTPUTS = {
    'total_m3': 'Water Use Equipment Total Volume',
    'flow_m3_s': 'Water Use Equipment Total Volume Flow Rate',
}


class LifeBinding:
    def __init__(self, rows, fields, mapping):
        require(mapping.get('schema') == 'national_idf.life_channel_binding.v1'
                and set(mapping) == {'schema', 'people', 'mixed_water'}, 'LIFE_MAPPING_SCHEMA')
        self.people, self.water, self.schedules = {}, {}, {}
        self.handles, self.output_handles = {}, {}

        def named(kind, name):
            found = [r for r in objects(rows, kind) if r[1].casefold() == name.casefold()]
            require(len(found) == 1, 'LIFE_OBJECT_MAPPING', [kind, name])
            return found[0]

        def exclusive(name, allowed):
            # Dedicated control schedules must not silently command another
            # object, an external interface or a competing EMS actuator.
            refs = {(r[0].casefold(), r[1].casefold()) for r in rows if r[0].casefold() != 'schedule:constant'
                    and any(str(x).casefold() == name.casefold() for x in r[2:])}
            require(refs == {(k.casefold(), n.casefold()) for k, n in allowed},
                    'LIFE_SCHEDULE_SHARED_OR_UNBOUND', name)

        def schedule(label, name, allowed):
            row = named('Schedule:Constant', name)
            value = float(fields.get(row, 'hourly_value'))
            require(math.isfinite(value), 'LIFE_SCHEDULE_NONFINITE', name)
            require(name.casefold() not in {n.casefold() for n in self.schedules.values()},
                    'LIFE_SCHEDULE_REUSED', name)
            exclusive(name, allowed)
            self.schedules[label] = name
            return value

        require(mapping['people'], 'LIFE_PEOPLE_MAPPING_EMPTY')
        controlled = set()
        for zone, spec in mapping['people'].items():
            require(set(spec) == {'object', 'count_schedule', 'activity_schedule'}, 'LIFE_PEOPLE_MAPPING_FIELDS')
            row = named('People', spec['object'])
            target = fields.get(row, 'zone_or_zonelist_or_space_or_spacelist_name')
            require(equipment_zone(rows, target, fields) == zone, 'LIFE_PEOPLE_ZONE_MISMATCH')
            z = named('Zone', zone)
            require(float(fields.get(z, 'multiplier', '1')) == 1, 'LIFE_ZONE_MULTIPLIER_UNSUPPORTED')
            for group in objects(rows, 'ZoneGroup'):
                listed = named('ZoneList', fields.get(group, 'zone_list_name'))
                require(zone.casefold() not in {n.casefold() for n in listed[2:]},
                        'LIFE_ZONE_GROUP_MULTIPLIER_UNSUPPORTED')
            require(fields.get(row, 'number_of_people_calculation_method').casefold() == 'people',
                    'LIFE_PEOPLE_DESIGN_METHOD')
            number = float(fields.get(row, 'number_of_people'))
            require(math.isfinite(number) and number > 0, 'LIFE_PEOPLE_DESIGN_MISSING')
            require(fields.get(row, 'number_of_people_schedule_name') == spec['count_schedule']
                    and fields.get(row, 'activity_level_schedule_name') == spec['activity_schedule'],
                    'LIFE_PEOPLE_SCHEDULE_MAPPING')
            allowed = [('People', row[1])]
            schedule('people:' + zone, spec['count_schedule'], allowed)
            activity = schedule('activity:' + zone, spec['activity_schedule'], allowed)
            self.people[zone] = {'object': row[1], 'design_persons': number, 'inactive_activity_W': activity}
            controlled.add(row[1].casefold())
        for row in objects(rows, 'People'):
            zone = equipment_zone(rows, fields.get(row, 'zone_or_zonelist_or_space_or_spacelist_name'), fields)
            require(zone not in self.people or row[1].casefold() in controlled, 'LIFE_UNOWNED_PEOPLE_IN_ZONE')

        water = mapping['mixed_water']
        require(set(water) == {'delivered_object', 'distribution_waste_objects', 'flow_schedule', 'target_schedule'},
                'LIFE_WATER_MAPPING_FIELDS')
        names = [water['delivered_object'], *water['distribution_waste_objects']]
        require(len({n.casefold() for n in names}) == len(names), 'LIFE_WATER_DUPLICATE_OWNERSHIP')
        allowed = [('WaterUse:Equipment', n) for n in names]
        schedule('water_flow', water['flow_schedule'], allowed)
        schedule('water_target', water['target_schedule'], allowed)
        for name in names:
            row = named('WaterUse:Equipment', name)
            require(fields.get(row, 'flow_rate_fraction_schedule_name') == water['flow_schedule']
                    and fields.get(row, 'target_temperature_schedule_name') == water['target_schedule'],
                    'LIFE_WATER_SCHEDULE_MAPPING')
            # This implementation deliberately does not guess zone/list
            # multipliers or independent fixture heat/moisture fractions.
            require(not fields.get(row, 'zone_name'), 'LIFE_WATER_ZONE_MODEL_UNSUPPORTED')
            peak = float(fields.get(row, 'peak_flow_rate'))
            require(math.isfinite(peak) and peak > 0, 'LIFE_WATER_PEAK_MISSING')
            self.water[name] = {'peak_m3_s': peak, 'delivered': name == water['delivered_object']}
        self.delivered = water['delivered_object']
        self.outputs = {(zone, key): (variable, spec['object']) for zone, spec in self.people.items()
                        for key, variable in PEOPLE_OUTPUTS.items()}
        self.outputs.update({(name, key): (variable, name) for name in names for key, variable in WATER_OUTPUTS.items()})

    def commands(self, frame):
        require(set(frame['people']) == set(self.people), 'LIFE_COMMAND_ZONE_MAPPING')
        result = {}
        for zone, spec in self.people.items():
            person = frame['people'][zone]
            number, activity = person['persons'], person['activity_per_person_W']
            require(type(number) in (int, float) and math.isfinite(number)
                    and 0 <= number <= spec['design_persons'], 'LIFE_PEOPLE_COMMAND_OUTSIDE_DESIGN')
            require((number == 0 and activity is None) or
                    (type(activity) in (int, float) and math.isfinite(activity) and activity > 0),
                    'LIFE_ACTIVITY_COMMAND_MISSING')
            require(abs(person['activity_total_W'] - number * (activity or 0)) < 1e-8,
                    'LIFE_ACTIVITY_TOTAL_MISMATCH')
            result['people:' + zone] = number / spec['design_persons']
            # With zero occupants the activity contributes exactly zero.
            # Retain the source value instead of inventing a resting level.
            result['activity:' + zone] = activity if number else spec['inactive_activity_W']
        water = frame['mixed_water']
        flow, target = water['flow_L_min'], water['target_C']
        fraction = flow / 60000 / self.water[self.delivered]['peak_m3_s']
        require(math.isfinite(fraction) and 0 <= fraction <= 1 + 1e-12, 'LIFE_WATER_FLOW_OUTSIDE_SOURCE_PEAK')
        require(abs(flow * frame['duration_min'] - water['requested_volume_L']) < 1e-8,
                'LIFE_WATER_VOLUME_MISMATCH')
        require((flow == 0 and target is None) or
                (type(target) in (int, float) and math.isfinite(target)), 'LIFE_WATER_TARGET_MISSING')
        result['water_flow'] = fraction
        if flow:
            result['water_target'] = target
        return result

    def request_outputs(self, exchange, state):
        for variable, name in self.outputs.values():
            exchange.request_variable(state, variable, name)

    def initialize(self, exchange, state):
        handles = {key: exchange.get_actuator_handle(state, 'Schedule:Constant', 'Schedule Value', name)
                   for key, name in self.schedules.items()}
        outputs = {key: exchange.get_variable_handle(state, variable, name)
                   for key, (variable, name) in self.outputs.items()}
        require(all(h >= 0 for h in [*handles.values(), *outputs.values()]), 'LIFE_NATIVE_HANDLE_MISSING')
        self.handles, self.output_handles = handles, outputs

    def write(self, exchange, state, frame):
        pending = self.commands(frame)
        require(self.handles, 'LIFE_NATIVE_NOT_INITIALIZED')
        for key, value in pending.items():
            exchange.set_actuator_value(state, self.handles[key], value)

    def observe(self, exchange, state, *, water):
        require(self.output_handles, 'LIFE_NATIVE_NOT_INITIALIZED')
        keys = WATER_OUTPUTS if water else PEOPLE_OUTPUTS
        names = self.water if water else self.people
        values = {name: {key: float(exchange.get_variable_value(state, self.output_handles[name, key]))
                         for key in keys} for name in names}
        require(all(math.isfinite(v) for row in values.values() for v in row.values()), 'LIFE_NATIVE_NONFINITE')
        return values
