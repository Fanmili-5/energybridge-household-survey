"""Install a source-bound context meter and reconcile a dwelling independently.

Facility electricity remains the full building. The dwelling decrement is
explicit and does not assign any unreviewed shared plant to that dwelling.
Currently source neighbours must use only the reviewed ideal-HVAC context and
explicit Lights/ElectricEquipment loads. Other neighbour systems are rejected.
"""
import copy
from pathlib import Path

from .common import ROOT, digest, read, require, sha
from .idf import Fields, objects, parse
from .retained_context import source_scope, verify_retained
from .source_adapter import housing_fingerprint, source_file

CONTEXT_VARIABLES = {'Lights': 'Lights Electricity Energy',
                     'ElectricEquipment': 'Electric Equipment Electricity Energy'}
ELECTRICITY_OUTPUTS = ('Lights Electricity Energy', 'Pump Electricity Energy',
                      'Electric Equipment Electricity Energy', 'Other Equipment Electricity Energy',
                      'Heating Coil Electricity Energy', 'Cooling Coil Electricity Energy',
                      'Heating Coil Defrost Electricity Energy',
                      'Heating Coil Crankcase Heater Electricity Energy',
                      'Cooling Coil Crankcase Heater Electricity Energy',
                      'Fan Electricity Energy', 'Water Heater Electricity Energy')


def signature(rows, fields):
    canonical = copy.deepcopy([r for r in rows if r[0] not in ('RunPeriod', 'Timestep')
                               and not r[0].startswith('Output')])
    for row in objects(canonical, 'Building'):
        for key in ('minimum_number_of_warmup_days', 'maximum_number_of_warmup_days'):
            fields.set(row, key, '__NUMERICAL_WARMUP__')
    return digest(canonical)


def definitions(rows, pack_ref, schema_ref, *, root=ROOT):
    pack = read(source_file(pack_ref, root))
    require(pack.get('schema') == 'national_idf.dwelling_electricity_scope.v1', 'DWELLING_METER_SCHEMA')
    fields = schema_ref if isinstance(schema_ref, Fields) else Fields(source_file(schema_ref, root))
    context, source, _ = source_scope(pack['retained_ideal_context'], fields, root=root)
    require(pack['target_zone'] == context['target_zone'], 'DWELLING_METER_TARGET_MISMATCH')
    target = pack['target_zone'].casefold()
    # Full source systems must stay within the reviewed ideal-only boundary.
    # A source with pumps, electric heaters or other shared electrical systems
    # requires a new ownership review, not facility-minus-a-few-plugs inference.
    unsupported = [r[:2] for r in source if r[0].startswith(
        ('AirLoopHVAC', 'Fan:', 'Coil:', 'Pump:', 'WaterHeater:', 'ElectricLoadCenter:'))
        or r[0] == 'OtherEquipment']
    require(not unsupported, 'DWELLING_SOURCE_SHARED_ELECTRICITY_UNREVIEWED', unsupported)
    terms = []
    for row in source:
        if row[0] not in CONTEXT_VARIABLES or row[2].casefold() == target:
            continue
        require(rows.count(row) == 1, 'DWELLING_CONTEXT_ELECTRIC_LOAD_CHANGED', row[:2])
        terms.append([row[1], CONTEXT_VARIABLES[row[0]]])
    require(terms and len({tuple(x) for x in terms}) == len(terms), 'DWELLING_CONTEXT_METER_TERMS')
    require(pack['context_terms'] == terms, 'DWELLING_CONTEXT_METER_TERMS_CHANGED')
    household, neighbour = pack['household_meter'], pack['context_meter']
    require(isinstance(household, str) and isinstance(neighbour, str) and household and neighbour
            and household.casefold() != neighbour.casefold()
            and all(x.casefold() != 'electricity:facility' for x in (household, neighbour)),
            'DWELLING_METER_NAMES')
    custom = [['Meter:Custom', neighbour, 'Electricity', *[v for term in terms for v in term]],
              ['Meter:CustomDecrement', household, 'Electricity', 'Electricity:Facility', '', neighbour]]
    return pack, fields, custom


def install(rows, pack_ref, schema_ref, *, root=ROOT):
    pack, fields, custom = definitions(rows, pack_ref, schema_ref, root=root)
    require(signature(rows, fields) == pack['installed_context_signature'], 'DWELLING_METER_CONTEXT_NOT_BOUND')
    for name in (pack['household_meter'], pack['context_meter']):
        require(not any(len(r) > 1 and r[1].casefold() == name.casefold()
                        for r in rows if r[0].startswith('Meter:')), 'DWELLING_METER_NAME_COLLISION')
    result = copy.deepcopy(rows) + custom
    result += [['Output:Meter', name, 'Timestep'] for name in
               ('Electricity:Facility', pack['household_meter'], pack['context_meter'])
               if ['Output:Meter', name, 'Timestep'] not in result]
    result += [['Output:Variable', '*', name, 'Timestep'] for name in ELECTRICITY_OUTPUTS
               if ['Output:Variable', '*', name, 'Timestep'] not in result]
    require(housing_fingerprint(rows) == housing_fingerprint(result), 'DWELLING_METER_CHANGED_HOUSING')
    return result, verify(result, pack_ref, schema_ref, root=root)


def verify(rows, pack_ref, schema_ref, *, root=ROOT):
    pack, fields, custom = definitions(rows, pack_ref, schema_ref, root=root)
    for row in custom:
        require(rows.count(row) == 1, 'DWELLING_NATIVE_METER_DEFINITION_CHANGED', row[:2])
    remaining = copy.deepcopy(rows)
    for row in custom:
        remaining.remove(row)
    require(signature(remaining, fields) == pack['installed_context_signature'],
            'DWELLING_METER_PHYSICAL_CONTEXT_CHANGED')
    context = verify_retained(rows, pack['retained_ideal_context'], fields, root=root)
    return {'pack': pack_ref, 'household_meter': pack['household_meter'],
            'context_meter': pack['context_meter'], 'facility_meter': 'Electricity:Facility',
            'target_zone': pack['target_zone'], 'retained_context': context,
            'context_term_count': len(pack['context_terms']), 'native_meter_objects': custom,
            'independent_direct_dwelling_energy_balance_verified': False,
            'implementation': {'path': 'national_idf/dwelling_metering.py', 'sha256': sha(Path(__file__))},
            'formal_admitted': False, 'facility_is_whole_building_not_household': True}
