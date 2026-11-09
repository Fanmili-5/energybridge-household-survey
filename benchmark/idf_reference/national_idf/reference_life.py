"""Attach existing EB life ports through the existing source assembly compiler.

Source People physics, fixture peaks, tank and background loads are retained.
Only explicitly replaced schedules/People ownership change. No household,
personal routine, metabolic value or event heat/moisture fraction is inferred.
"""
from __future__ import annotations

import copy
import math
from pathlib import Path

from .assembly import compile_assembly, plan_assembly
from .common import ROOT, read, require, save
from .idf import Fields, objects, parse
from .program_resources import model_signature, plan_resources
from .reference_workflow import ref
from .source_adapter import selector, source_file


def inventory_receipt(spec, before, after, *, root=ROOT):
    """Rebind only after proving an inventory projection preserves life ports.

    The caller separately limits all other edits to isolated device retirement.
    A newly added person or changed general-water/background object is refused.
    """
    receipt = read(source_file(spec['life_installation_receipt'], root))
    parent_signature = model_signature(before)
    if spec.get('registered_numerical_overlay'):
        from .source_numerics import validate_model_overlay
        parent_signature = validate_model_overlay(before, spec['model'], spec['registered_numerical_overlay'],
            spec['engine_schema'], root=root)['source_model_signature']
    require(receipt['ready'] and not receipt['formal_admitted'] and
            receipt['installed_model_signature'] == parent_signature,
            'REFERENCE_LIFE_INVENTORY_PARENT_NOT_BOUND')
    source_file(receipt['pack'], root)
    mapping = receipt['mapping']
    names = {p['object'] for p in mapping['people'].values()}
    water = mapping['mixed_water']
    names.update([water['delivered_object'], *water['distribution_waste_objects']])
    schedules = {water['flow_schedule'], water['target_schedule']}
    schedules.update(p[k] for p in mapping['people'].values() for k in ('count_schedule', 'activity_schedule'))
    protected = lambda row: row[0] == 'People' or row[1] in names | schedules or (
        row[0] == 'OtherEquipment' and 'general water' in row[1].casefold())
    require([r for r in before if protected(r)] == [r for r in after if protected(r)],
            'REFERENCE_LIFE_INVENTORY_CHANGED_PORTS')
    derived = copy.deepcopy(receipt)
    derived.update(installed_model_signature=model_signature(after),
                   inventory_parent_receipt=spec['life_installation_receipt'],
                   inventory_life_ports_and_background_unchanged=True)
    return derived


def prepare(blueprint_ref, fixture_ref, out, *, root=ROOT, supply_receipt_ref=None):
    source_spec=read(source_file(blueprint_ref,root)); parent=read(source_file(fixture_ref,root))
    require(source_spec['id']==parent['id'],'REFERENCE_LIFE_PARENT_ID')
    source_plan=plan_assembly(parent['id'],root=root,blueprint_ref=blueprint_ref)
    original=parse(source_file(parent['model'],root).read_text())
    require(source_plan['engineering_compilation_ready'] and source_plan['new_model_rows']==original,
            'REFERENCE_LIFE_PARENT_SOURCE_COMPILER_MISMATCH')
    plan_resources(original,parent['engine_schema'],parent['resource_pack'],root=root)
    fields=Fields(source_file(parent['engine_schema'],root))
    people=objects(original,'People');require(len(people)==1,'REFERENCE_LIFE_PEOPLE_SOURCE_NOT_UNIQUE')
    person=people[0];zone=parent['EB_mapping']['hvac']['zone']
    activity_name=fields.get(person,'activity_level_schedule_name')
    activity=[r for r in objects(original,'Schedule:Constant') if r[1]==activity_name]
    require(len(activity)==1,'REFERENCE_LIFE_SOURCE_ACTIVITY_NOT_CONSTANT')
    names=['EB_WATER_dhw fixtures','EB_WATER_dhw distribution waste']
    require(len([r for r in objects(original,'WaterUse:Equipment') if r[1] in names])==2,
            'REFERENCE_LIFE_SOURCE_FIXTURES_MISSING')
    out=Path(out).resolve();require(out.is_relative_to(root.resolve()) and not out.exists(),'REFERENCE_LIFE_OUTPUT')
    out.mkdir(parents=True)
    declaration={'schema':'national_idf.reference_life_design.v1','parent_fixture':fixture_ref,
                 'parent_blueprint':blueprint_ref,'source_people_physics':'Unchanged complete public People object',
                 'spatial_scope':'Whole-home conditioned zone engineering input,not inferred room allocation',
                 'source_general_water_background':'Retained independent published aggregate;no invented event coefficients',
                 'household_or_AB_generated':False,'formal_admitted':False}
    save(out/'INSTALLATION_SCOPE.json',declaration)
    # Source selectors always address the adapter's untouched input, not a
    # relocated schedule file or a model whose object indices have shifted.
    adapter=read(source_file(source_spec['source_adapter'],root))
    adapter_rows=parse(source_file(adapter['model'],root).read_text())
    matches=[i for i,r in enumerate(adapter_rows) if r==person]
    require(len(matches)==1,'REFERENCE_LIFE_SOURCE_PEOPLE_PRECONDITION')
    spec=copy.deepcopy(source_spec);spec['id']=parent['id']+'__life_ports_v1'
    spec['changes'].append({'action':'remove','object':selector(adapter_rows,matches[0]),
                           'reason':'Replace source People schedule ownership with explicit CASE people port;preserve person physics',
                           'evidence':ref(out/'INSTALLATION_SCOPE.json',root),'affected_meters':['*']})
    spec['review_receipts']={}
    # Missing author outputs constrain reproduction claims; they are not a
    # prerequisite for an explicitly sourced reference experiment.
    spec['formal_release_gaps']=[g for g in spec['formal_release_gaps'] if g!='No comparison with author output']
    spec['formal_release_gaps']+=['New life-port service/physical/numerical support not yet reviewed',
                                  'Specific water-event room heat/moisture effects unsupported']
    save(out/'PRE_LIFE_BLUEPRINT.json',spec)
    compile_assembly(spec['id'],out/'pre_life_assembly',mode='engineering_reference',root=root,
                     blueprint_ref=ref(out/'PRE_LIFE_BLUEPRINT.json',root))
    pre_rows=parse((out/'pre_life_assembly/in.idf').read_text())
    mapping={'schema':'national_idf.life_channel_binding.v1','people':{zone:{
        'object':person[1],'count_schedule':'EB_LIFE_count','activity_schedule':'EB_LIFE_activity'}},
        'mixed_water':{'delivered_object':names[0],'distribution_waste_objects':names[1:],
                       'flow_schedule':'EB_LIFE_fixture_flow','target_schedule':'EB_LIFE_fixture_target'}}
    pack={'schema':'national_idf.source_life_installation.v1','formal_admitted':False,
          'spatial_scope':'explicit_single_zone_engineering_port_not_household_distribution',
          'target_model':ref(out/'pre_life_assembly/in.idf',root),'target_zone':zone,
          'people_source_model':parent['model'],'people_object':selector(original,original.index(person)),
          'activity_object':selector(original,original.index(activity[0])),
          'type_limit_objects':[selector(original,i) for i,r in enumerate(original)
                                if r[0]=='ScheduleTypeLimits' and r[1] in ('Fractional','Temperature','ActivityLevel')],
          'water_objects':[selector(pre_rows,i) for i,r in enumerate(pre_rows) if r[0]=='WaterUse:Equipment' and r[1] in names],
          'mapping':mapping,'source_physics_code':ref(root/'work/p1_hpxml_004ca3ce/HPXMLtoOpenStudio/resources/internal_gains.rb',root)}
    save(out/'LIFE_PACK.json',pack);spec['life_installation_pack']=ref(out/'LIFE_PACK.json',root)
    save(out/'BLUEPRINT.json',spec)
    compile_assembly(spec['id'],out/'assembly',mode='engineering_reference',root=root,blueprint_ref=ref(out/'BLUEPRINT.json',root))
    rows=parse((out/'assembly/in.idf').read_text());life=read(out/'assembly/LIFE_INSTALLATION.json')
    # Keep all equipment physics and water consumers except the two dedicated
    # general-demand schedule ports. Do not silently replace appliance water.
    for kind in ('Material','Construction','Zone','Space','BuildingSurface:Detailed','FenestrationSurface:Detailed',
                 'ElectricEquipment','OtherEquipment','WaterHeater:Stratified','WaterUse:Connections'):
        require(objects(rows,kind)==objects(original,kind),'REFERENCE_LIFE_UNRELATED_PHYSICS_CHANGED',kind)
    require(len(objects(rows,'People'))==1,'REFERENCE_LIFE_PEOPLE_DOUBLE_COUNT')
    resource=read(source_file(parent['resource_pack'],root));resource['binding_model_signature']=model_signature(rows)
    resource['source_evidence']=[*resource['source_evidence'],ref(out/'assembly/LIFE_INSTALLATION.json',root)]
    save(out/'RESOURCE_PACK.json',resource)
    domain=read(source_file(parent['input_domain'],root));domain['physics_configuration_id']=spec['id']
    count=float(fields.get(person,'number_of_people'));require(count>=1,'REFERENCE_LIFE_SOURCE_DESIGN_COUNT')
    delivered=next(r for r in objects(rows,'WaterUse:Equipment') if r[1]==names[0])
    flow=float(fields.get(delivered,'peak_flow_rate'))*60000
    target=next(r for r in objects(rows,'Schedule:Constant') if r[1]=='EB_LIFE_fixture_target')
    temperature=float(fields.get(target,'hourly_value'));watts=life['source_activity_W_per_person']
    domain.update(maximum_persons=math.floor(count),max_water_flow_L_min=flow,thermal_zones=[zone],
                  scope='Explicit whole-home people and aggregate fixture input under inherited reference background;not a personal routine')
    domain['bounds'].update(activity_W=[watts,watts],water_target_C=[temperature,max(temperature,domain['bounds']['tank_target_C'][1]+10)])
    for programme in domain['programs'].values():programme['resource_pack']=ref(out/'RESOURCE_PACK.json',root)
    save(out/'DOMAIN.json',domain)
    fixture=copy.deepcopy(parent);fixture.update(id=spec['id'],model=ref(out/'assembly/in.idf',root),
        input_domain=ref(out/'DOMAIN.json',root),resource_pack=ref(out/'RESOURCE_PACK.json',root),
        life_installation_receipt=ref(out/'assembly/LIFE_INSTALLATION.json',root),
        dependencies=read(out/'assembly/ASSEMBLY.json')['dependencies'])
    # Existing water-scope code supplies the interpretation of retained gains.
    if supply_receipt_ref is not None:
        source_file(supply_receipt_ref, root)
        scope={'schema':'national_idf.public_aggregate_water_scope.v1','mode':'independent_published_aggregate_background',
               'per_event_heat_moisture_coefficients':None,'supply_receipt':supply_receipt_ref,
               'fixture_draw_objects':names,'evidence':[ref(out/'INSTALLATION_SCOPE.json',root),pack['source_physics_code']]}
        save(out/'WATER_SCOPE.json',scope);fixture['water_effect_scope']=ref(out/'WATER_SCOPE.json',root)
        from .water_scope import describe
        describe(rows, fields, fixture['water_effect_scope'], root=root)
    save(out/'FIXTURE.json',fixture)
    case=read(source_file(parent['input_domain'],root).parent/'CASE.json')
    case['case_id']=spec['id']+'__engineering';case['environment']['physics_configuration_id']=spec['id']
    case['life'].update(basis='Fixed previously defined public engineering life-port instructions;not generated households or finalAB',
        maximum_persons=domain['maximum_persons'],people_values_basis='Unchanged source People activity and heat fractions',
        occupancy=[{'room_id':zone,'start_min':360,'end_min':480,'persons':1,'activity_W':watts},
                   {'room_id':zone,'start_min':1080,'end_min':1320,'persons':domain['maximum_persons'],'activity_W':watts}],
        mixed_water_daily=[{'start_min':420,'duration_min':10,'liters':flow*5,'target_C':temperature},
                           {'start_min':1080,'duration_min':20,'liters':flow*10,'target_C':temperature}],
        mixed_water_overrides={})
    save(out/'CASE.json',case)
    report={'schema':'national_idf.reference_life_preparation.v1','id':spec['id'],'parent_fixture':fixture_ref,
            'blueprint':ref(out/'BLUEPRINT.json',root),'fixture':ref(out/'FIXTURE.json',root),
            'source_design_people':count,'input_maximum_persons':domain['maximum_persons'],
            'source_activity_W_per_person':watts,'source_fixture_peak_L_min':flow,'source_fixture_target_C':temperature,
            'background_general_water_gains_event_synchronized':False,'unrelated_physics_unchanged':True,
            'source_people_physically_reused':True,'old_people_removed_not_duplicated':True,
            'per_person_or_water_event_parameters_invented':False,'author_output_comparison':False,
            'formal_admitted':False,'numerical_acceptance':False,'implementation':ref(Path(__file__),root)}
    save(out/'PREPARATION.json',report)
    return report
