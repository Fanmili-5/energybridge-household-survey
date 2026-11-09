"""Replay source construction and optional package rules for a cached house."""
from .common import ROOT,read,require
from .idf import parse,objects,Fields
from .source_adapter import source_file
from .reference_workflow import apply_site,schedule_dependency
from .envelope_adaptation import apply,construction_properties
from .condition_defaults import inspect
from .parameter_pack import inventory
from .weather import audit


def normalized(rows,fixture):
    from copy import deepcopy
    result=deepcopy(rows)
    for row in objects(result,'Schedule:File'):
        row[3]=schedule_dependency(fixture['dependencies'],row[3])['sha256']
    return result


def inspect_preparation(entry,fixture):
    folder=ROOT/entry['prepared_directory'];rows=parse(source_file(fixture['model'],ROOT).read_text())
    fields=Fields(source_file(fixture['engine_schema'],ROOT));geometry=read(folder/'GEOMETRY_CHECKS.json')
    require(geometry['fixture_model']==fixture['model'] and geometry['source_geometry_rows_exactly_preserved']
        and geometry['native_area_volume_and_multipliers_match_source'],'CONDITION_PHYSICS_GEOMETRY_NOT_BOUND')
    if 'base_housing_key' in entry['physical_definition']:
        workflow=read(folder/'WORKFLOW.json');parent=read(source_file(workflow['parent_fixture'],ROOT))
        parent_preparation=read(folder/'EXECUTION.json')['source_preparation']
        parent_entry=read(source_file(parent_preparation['cache_entry'],ROOT))
        from .housing_pipeline import validate_entry
        require(validate_entry(parent_entry)==parent,'CONDITION_PHYSICS_COMPOSED_PARENT_NOT_BOUND')
        parent_review=inspect_preparation(parent_entry,parent)
        source=parse(source_file(parent['model'],ROOT).read_text())
        expected,modifications=apply(source,workflow['envelope_pack'],fixture['engine_schema'])
        expected,site=apply_site(expected,workflow['site_pack'],fixture['engine_schema'])
        require(normalized(expected,parent)==normalized(rows,fixture),'CONDITION_PHYSICS_RECIPE_NOT_REPRODUCIBLE')
        require(modifications['geometry_and_adjacency_unchanged'] and modifications['unselected_objects_unchanged'],
                'CONDITION_PHYSICS_RECIPE_UNRELATED_CHANGE')
        source_for_defaults=source
    elif 'occupancy_design' in entry['physical_definition']:
        from .condition_occupancy import review as review_occupancy
        source,occupancy=review_occupancy(entry,fixture)
        source_for_defaults=source;modifications=None;site=None
    elif 'people_capacity' in entry['physical_definition']:
        from .condition_people_capacity import review as review_capacity
        source,capacity=review_capacity(entry,fixture)
        source_for_defaults=source;modifications=None;site=None
    elif 'water_normalization' in entry['physical_definition']:
        from .condition_water_port import review as review_water
        source,water=review_water(entry,fixture)
        source_for_defaults=source;modifications=None;site=None
    elif 'control_input_domain' in entry['physical_definition']:
        from .condition_control_domain import review as review_controls
        source,control_domain=review_controls(entry,fixture)
        source_for_defaults=source;modifications=None;site=None
    else:
        source=parse(source_file(geometry['source_idf'],ROOT).read_text());modifications=None;site=None
        source_faces={r[1]:r for r in objects(source,'BuildingSurface:Detailed')}
        for row in objects(rows,'BuildingSurface:Detailed'):
            require(fields.get(row,'construction_name')==fields.get(source_faces[row[1]],'construction_name'),
                    'CONDITION_PHYSICS_UNDECLARED_CONSTRUCTION')
        baseline={r[1]:r for r in source if r[0] in ('Material','Material:NoMass','Material:AirGap','Construction') or r[0].startswith('WindowMaterial:')}
        for row in rows:
            if len(row)>1 and row[1] in baseline and row[0] in ('Material','Material:NoMass','Material:AirGap','Construction') or row[0].startswith('WindowMaterial:'):
                require(row==baseline.get(row[1]),'CONDITION_PHYSICS_UNDECLARED_LAYER_CHANGE',row[:2])
        blueprint=read(folder/'life/BLUEPRINT.json');adapter=read(source_file(blueprint['source_adapter'],ROOT))
        source_for_defaults=parse(source_file(adapter['model'],ROOT).read_text())
    props={}
    for row in objects(rows,'BuildingSurface:Detailed'):
        name=fields.get(row,'construction_name');construction=next(r for r in objects(rows,'Construction') if r[1]==name)
        props[name]=construction_properties(rows,construction,fields)
    model=source_file(fixture['model'],ROOT)
    defaults=inspect(rows,inventory(rows,model.read_text(),read(source_file(fixture['engine_schema'],ROOT))),
                     fields,source_for_defaults,fixture['engine_schema'])
    require(defaults['all_schema_default_branches_accounted'] and not defaults['unreviewed'],'CONDITION_PHYSICS_DEFAULT_GAP')
    weather=audit(source_file(fixture['weather'],ROOT));require(not weather['errors'],'CONDITION_PHYSICS_WEATHER_QC')
    # Actual coil/fan/table performance is inherited from the complete source;
    # no inferred regional COP or cross-product point substitution is allowed.
    performance=lambda model:[r for r in model if r[0].startswith(('Coil:','Fan:','Table:'))]
    require(performance(rows)==performance(source),'CONDITION_PHYSICS_PERFORMANCE_NOT_INHERITED')
    tank=read(ROOT/'configs/component_models/EB_original_water_heater_c58a2a7a.json');tanks=objects(rows,'WaterHeater:Stratified')
    require(len(tanks)==1 and all(fields.get(tanks[0],k)==v for k,v in tank['physical_parameters'].items()),'CONDITION_PHYSICS_TANK_CHANGED')
    require(not objects(rows,'ZoneHVAC:IdealLoadsAirSystem') and not objects(rows,'Coil:Heating:Electric'),'CONDITION_PHYSICS_HIDDEN_HEATING')
    return {'geometry':geometry,'complete_opaque_layer_properties':props,'effective_defaults':defaults,
        'parent_package_review':parent_review if 'base_housing_key' in entry['physical_definition'] else None,
        'occupancy_design_review':occupancy if 'occupancy_design' in entry['physical_definition'] else None,
        'people_capacity_review':capacity if 'people_capacity' in entry['physical_definition'] else None,
        'water_input_normalization_review':water if 'water_normalization' in entry['physical_definition'] else None,
        'control_input_domain_review':control_domain if 'control_input_domain' in entry['physical_definition'] else None,
        'envelope_replay':modifications,'site_replay':site,'weather_QC':weather,'complete_source_performance_inherited':True,
        'original_EB_tank_unchanged':True,'no_hidden_heat':True,'source_author_result_comparison':False,
        'country_stock_or_measured_survey_home_claimed':False}
