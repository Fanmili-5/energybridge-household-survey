"""Install source People and dedicate existing plant input schedules.

No occupant count, activity, heat fraction or fixture peak is inferred here.
Spatial placement is an explicit engineering installation input. General water
gains stay in their published background model, not an invented event model.
"""
import copy
from pathlib import Path

from .common import ROOT, read, require, sha
from .idf import Fields, objects, parse, render
from .life_binding import LifeBinding
from .program_resources import model_signature
from .source_adapter import housing_fingerprint, selected, source_file


def install(rows, pack_ref, schema_ref, *, root=ROOT):
    pack = read(source_file(pack_ref, root))
    require(pack.get('schema') == 'national_idf.source_life_installation.v1'
            and pack.get('formal_admitted') is False, 'LIFE_INSTALLATION_SCOPE')
    require(pack['spatial_scope'] == 'explicit_single_zone_engineering_port_not_household_distribution',
            'LIFE_INSTALLATION_SPATIAL_SCOPE')
    base = parse(source_file(pack['target_model'], root).read_text())
    require(model_signature(rows) == model_signature(base), 'LIFE_INSTALLATION_TARGET_CHANGED')
    require(not objects(rows, 'People'), 'LIFE_INSTALLATION_OLD_PEOPLE_NOT_RETIRED')
    source = parse(source_file(pack['people_source_model'], root).read_text())
    fields = Fields(source_file(schema_ref, root))
    original = copy.deepcopy(selected(source, pack['people_object']))
    activity = selected(source, pack['activity_object'])
    require(original[0] == 'People' and activity[0] == 'Schedule:Constant'
            and fields.get(original, 'activity_level_schedule_name') == activity[1], 'LIFE_INSTALLATION_SOURCE_LINK')
    require(fields.get(original, 'number_of_people_calculation_method') == 'People', 'LIFE_INSTALLATION_SOURCE_COUNT')
    zone = pack['target_zone']
    require(len([r for r in objects(rows, 'Zone') if r[1] == zone]) == 1, 'LIFE_INSTALLATION_TARGET_ZONE')
    mapping = pack['mapping']
    require(set(mapping['people']) == {zone}, 'LIFE_INSTALLATION_SINGLE_PORT_MAPPING')
    pmap = mapping['people'][zone]; wmap = mapping['mixed_water']
    result, additions, modifications = copy.deepcopy(rows), [], []
    for ref in pack['type_limit_objects']:
        row = copy.deepcopy(selected(source, ref))
        require(row[0] == 'ScheduleTypeLimits', 'LIFE_INSTALLATION_TYPE_LIMIT_SOURCE')
        row[1] = 'EB_LIFE_' + row[1]
        require(not any(r[:2] == row[:2] for r in result+additions), 'LIFE_INSTALLATION_NAME_COLLISION')
        additions.append(row)
    person = copy.deepcopy(original)
    person[1] = pmap['object']
    for key, value in {
        'zone_or_zonelist_or_space_or_spacelist_name': zone,
        'number_of_people_schedule_name': pmap['count_schedule'],
        'activity_level_schedule_name': pmap['activity_schedule'],
    }.items(): fields.set(person, key, value)
    additions += [person,
        fields.obj('Schedule:Constant', name=pmap['count_schedule'], schedule_type_limits_name='EB_LIFE_Fractional', hourly_value='0'),
        fields.obj('Schedule:Constant', name=pmap['activity_schedule'], schedule_type_limits_name='EB_LIFE_ActivityLevel',
                   hourly_value=fields.get(activity, 'hourly_value'))]
    uses = [wmap['delivered_object'], *wmap['distribution_waste_objects']]
    require(len(uses) == len(set(uses)) == len(pack['water_objects']), 'LIFE_INSTALLATION_WATER_OWNERSHIP')
    originals = [selected(base, s) for s in pack['water_objects']]
    require(set(uses) == {r[1] for r in originals} and all(r[0] == 'WaterUse:Equipment' for r in originals),
            'LIFE_INSTALLATION_WATER_SOURCE')
    target_names = {fields.get(r, 'target_temperature_schedule_name') for r in originals}
    require(len(target_names) == 1, 'LIFE_INSTALLATION_WATER_TARGET_MISMATCH')
    targets = [r for r in objects(base, 'Schedule:Constant') if r[1] in target_names]
    require(len(targets) == 1, 'LIFE_INSTALLATION_WATER_TARGET_NOT_CONSTANT')
    for row in result:
        if row in originals:
            before = copy.deepcopy(row)
            fields.set(row, 'flow_rate_fraction_schedule_name', wmap['flow_schedule'])
            fields.set(row, 'target_temperature_schedule_name', wmap['target_schedule'])
            modifications.append({'before': before, 'after': copy.deepcopy(row)})
    additions += [
        fields.obj('Schedule:Constant', name=wmap['flow_schedule'], schedule_type_limits_name='EB_LIFE_Fractional', hourly_value='0'),
        fields.obj('Schedule:Constant', name=wmap['target_schedule'], schedule_type_limits_name='EB_LIFE_Temperature',
                   hourly_value=fields.get(targets[0], 'hourly_value'))]
    keys = {(r[0].casefold(), r[1].casefold()) for r in result if len(r) > 1}
    require(all((r[0].casefold(), r[1].casefold()) not in keys for r in additions), 'LIFE_INSTALLATION_NAME_COLLISION')
    result += additions
    result = parse(render(result))
    LifeBinding(result, fields, mapping)
    require(housing_fingerprint(result) == housing_fingerprint(rows), 'LIFE_INSTALLATION_HOUSING_CHANGED')
    source_file(pack['source_physics_code'], root)
    receipt = {'pack': pack_ref, 'mapping': mapping, 'source_people': {'before': original, 'after': person},
        'source_activity_W_per_person': float(fields.get(activity, 'hourly_value')),
        'water_modifications': modifications, 'additions': additions,
        'installed_model_signature': model_signature(result), 'ready': True, 'formal_admitted': False,
        'general_water_gains_synchronized_to_CASE': False, 'spatial_scope': pack['spatial_scope'],
        'implementation': {'path': 'national_idf/life_installation.py', 'sha256': sha(Path(__file__))}}
    return result, receipt
