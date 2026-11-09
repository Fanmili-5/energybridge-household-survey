"""Describe sourced water boundaries without inventing event heat fractions."""
from pathlib import Path

from .common import ROOT, locked, read, require, sha
from .idf import objects


def describe(rows, fields, scope_ref, *, root=ROOT):
    scope=read(locked(scope_ref,root))
    require(scope['schema']=='national_idf.public_aggregate_water_scope.v1'
        and scope['mode']=='independent_published_aggregate_background'
        and scope['per_event_heat_moisture_coefficients'] is None,
        'WATER_SCOPE_UNREVIEWED_EVENT_MODEL')
    for item in scope['evidence']:locked(item,root)
    receipt=read(locked(scope['supply_receipt'],root))
    source=read(locked(receipt['pack'],root));locked(source['source_model'],root)
    changes=[item for item in receipt['source_objects'] if item['after'][0]=='OtherEquipment'
             and item['before'][1] in ('general water sensible','general water latent')]
    require(len(changes)==2,'WATER_SCOPE_SOURCE_AGGREGATE_MISSING')
    background=[]
    for change in changes:
        after=change['after'];require(rows.count(after)==1,'WATER_SCOPE_BACKGROUND_CHANGED',after[:2])
        require(fields.get(after,'fuel_type')=='None','WATER_SCOPE_NON_ELECTRIC_BACKGROUND')
        background.append({'name':after[1],'zone':fields.get(after,'zone_or_zonelist_or_space_or_spacelist_name'),
            'schedule':fields.get(after,'schedule_name'),'source_W':float(fields.get(after,'design_level')),
            'fraction_latent':float(fields.get(after,'fraction_latent')),
            'fraction_radiant':float(fields.get(after,'fraction_radiant'))})
    require(len({b['schedule'] for b in background})==1,'WATER_SCOPE_AGGREGATE_SCHEDULES_DIFFER')
    uses={r[1]:r for r in objects(rows,'WaterUse:Equipment')}
    names=scope['fixture_draw_objects'];require(names and all(n in uses for n in names),'WATER_SCOPE_FIXTURE_MISSING')
    require(all(not fields.get(uses[n],'zone_name') for n in names),'WATER_SCOPE_NEW_ZONE_WATER_MODEL')
    return {'schema':'national_idf.executed_water_effect_scope.v1','definition':scope_ref,
        'CASE_mixed_water_input_means':'mixed domestic-hot-water fixture draws plus sourced distribution waste',
        'source_general_water_background':background,
        'background_contains':'mopping, shower evaporation, wet surfaces, plant watering and other aggregate water activities',
        'fixture_draw_controls_background':False,'per_event_heat_moisture_coefficients':None,
        'supported_results':['native water/tank energy, mixed delivery and supply-temperature consequences',
            'zone results under the retained independent published aggregate background'],
        'unsupported_results':['causal room humidity or temperature effect of moving a specific shower or mopping event'],
        'new_physical_coefficients_or_heat_gains_added':False,
        'implementation':{'path':str(Path(__file__).resolve().relative_to(root)),'sha256':sha(__file__)},
        'formal_admission_granted':False}
