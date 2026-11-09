"""Reuse life ports, scoped water background and exact inventory retirements."""
import argparse
import copy

from national_idf.common import ROOT, read, require, save
from national_idf.idf import Fields, objects, parse, render
from national_idf.joint_case_runtime import compile_joint_case, run_joint_case
from national_idf.program_resources import plan_resources
from national_idf.reference_inventory import compile_case, run
from national_idf.reference_scenarios import FUNCTIONS
from national_idf.reference_workflow import ref
from national_idf.source_adapter import selector, source_file
from national_idf.water_scope import describe
from scripts.validate_multicountry_life import OUT, SIX, validate


def scoped_fixture(folder):
    fixture=read(folder/'FIXTURE.json')
    if fixture.get('water_effect_scope'):
        return folder/'FIXTURE.json', folder/'run'
    # Explicit source-class dependency, not a guessed same-folder filename.
    receipt=ROOT/'reports/eb_six_joint_20261031/profiles/native_baseline_2min/WATER_INSTALLATION.json'
    scope={'schema':'national_idf.public_aggregate_water_scope.v1',
           'mode':'independent_published_aggregate_background','per_event_heat_moisture_coefficients':None,
           'supply_receipt':ref(receipt),
           'fixture_draw_objects':['EB_WATER_dhw fixtures','EB_WATER_dhw distribution waste'],
           'evidence':[ref(folder/'INSTALLATION_SCOPE.json')]}
    if not (folder/'WATER_SCOPE_EXPLICIT.json').exists():save(folder/'WATER_SCOPE_EXPLICIT.json',scope)
    fixture['water_effect_scope']=ref(folder/'WATER_SCOPE_EXPLICIT.json')
    rows=parse(source_file(fixture['model'],ROOT).read_text())
    describe(rows,Fields(source_file(fixture['engine_schema'],ROOT)),fixture['water_effect_scope'])
    path=folder/'FIXTURE_SCOPED.json'
    if not path.exists():save(path,fixture)
    require(read(path)==fixture,'LIFE_SCOPE_FIXTURE_DRIFT')
    if not (folder/'compiled_scoped').exists():
        compile_joint_case(ref(path),read(folder/'CASE.json'),folder/'compiled_scoped',mode='engineering_reference')
    if not (folder/'run_scoped').exists():run_joint_case(folder/'compiled_scoped',folder/'run_scoped',mode='engineering_reference')
    return path,folder/'run_scoped'


def variant(folder, fixture_path, count):
    fixture=read(fixture_path);rows=parse(source_file(fixture['model'],ROOT).read_text())
    fields=Fields(source_file(fixture['engine_schema'],ROOT))
    plan=plan_resources(rows,fixture['engine_schema'],fixture['resource_pack'])
    absent={'dryer','dishwasher'} if count==4 else {'ev'}
    keys={'dryer':'DR','dishwasher':'DW','ev':'EV'}
    path=folder/('four' if count==4 else 'five');path.mkdir(exist_ok=True)
    equipment={k:{'physically_present':k not in {keys[d] for d in absent},
                  'control_enabled':k not in {keys[d] for d in absent},
                  'presence_basis':'Fixed explicit engineering inventory;not survey ownership',
                  'asset_id':'engineering-'+k if k not in {keys[d] for d in absent} else None}
               for k in FUNCTIONS}
    declaration={'schema':'national_idf.reference_inventory_design.v1','equipment':equipment,
                 'basis':'Retire isolated native electric/water/gain consumers;retain original EB kernels and complete life ports'}
    save(path/'DECLARATION.json',declaration)
    retired={}
    for device in absent:
        if device=='ev':
            retired[device]=[fixture['EB_mapping']['equipment']['ev']['equipment']]
        else:
            program=plan['definition']['programs'][device]
            retired[device]=[r[1] for r in rows if
                r[0]=='ElectricEquipment' and r[1]==program['equipment'] or
                r[0] in ('OtherEquipment','WaterUse:Equipment') and
                fields.get(r,'schedule_name' if r[0]=='OtherEquipment' else 'flow_rate_fraction_schedule_name') in program['schedules']]
    names={v for items in retired.values() for v in items}
    water_names={r[1] for r in objects(rows,'WaterUse:Equipment') if r[1] in names}
    changes=[];replacements=[]
    for i,row in enumerate(rows):
        if row[0] in ('ElectricEquipment','OtherEquipment','WaterUse:Equipment','Output:Variable') and row[1] in names:
            op={'action':'remove'}
        elif row[0]=='WaterUse:Connections' and any(n in row[2:] for n in water_names):
            after=[v for v in row if v not in water_names];replacements.append(after)
            op={'action':'replace','after_index':len(replacements)-1}
        else:continue
        op.update(object=selector(rows,i),reason='Explicit absence;retire native device consumers',
            evidence=ref(path/'DECLARATION.json'),affected_meters=['Electricity:Facility','InteriorEquipment:Electricity','Water'])
        changes.append(op)
    if replacements:
        (path/'REPLACEMENTS.idf').write_text(render(replacements))
        for op in changes:
            if 'after_index' in op:
                index=op.pop('after_index');op['after']={'file':ref(path/'REPLACEMENTS.idf'),'object':selector(replacements,index)}
    pack={'schema':'national_idf.reference_inventory_pack.v1','id':fixture['id']+f'__{count}_functions',
          'parent_model':fixture['model'],'equipment':equipment,'changes':changes,'retired_physical_object_names':retired}
    save(path/'PACK.json',pack)
    case=copy.deepcopy(read(folder/'CASE.json'));case['case_id']=pack['id']+'__engineering'
    case['environment']['physics_configuration_id']=pack['id']
    for device in absent-{'ev'}:
        case['life']['services_daily'][device]['cycles']=0
        case['controls']['program_starts_daily'][device]=[]
        for value in case['controls']['program_start_overrides'].values():value[device]=[]
    if 'ev' in absent:
        case['life']['ev_connection_daily']=[];case['life']['ev_daily'].update(traction_kWh=0,required_departure_SOC=0)
        case['controls'].update(ev_daily_windows=[],ev_window_overrides={},ev_target_SOC=0)
    save(path/'CASE.json',case)
    if not (path/'compiled_v2').exists():compile_case(ref(fixture_path),ref(path/'PACK.json'),case,path/'compiled_v2')
    if not (path/'run_v2').exists():run(path/'compiled_v2',path/'run_v2')
    if (path/'compiled/in.idf').is_file():
        require((path/'compiled/in.idf').read_bytes()==(path/'compiled_v2/in.idf').read_bytes(),
                'INVENTORY_VALIDATION_PLUMBING_CHANGED_PHYSICAL_IDF')
    save(path/'CURRENT.json',{'compiled':ref(path/'compiled_v2/MANIFEST.json'),'run':str((path/'run_v2').relative_to(ROOT)),
                            'historical_v1_implementation':'reports/multicountry_life_20261108/runtime_v1'})
    installed=[d for d in SIX if d not in absent]
    return validate(path/'run_v2',fixture,case,installed,path/'compiled_v2/DOMAIN.json')


def execute(label):
    folder=OUT/label;fixture_path,six_run=scoped_fixture(folder)
    six=validate(six_run,read(fixture_path),read(folder/'CASE.json'))
    result={'six':six,'four':variant(folder,fixture_path,4),'five':variant(folder,fixture_path,5),
            'formal_admitted':False,'method_acceptance_complete':False}
    save(folder/'INVENTORY_LIFE_VALIDATION.json',result)
    print(label,'4/5/6 native life and existing device checks passed',flush=True)


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--label',choices=['US','ES','US_apartment'],required=True)
    execute(p.parse_args().label)
