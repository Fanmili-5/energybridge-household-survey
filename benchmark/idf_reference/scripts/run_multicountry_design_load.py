"""Independent design-load instrument versus the unchanged installed heat pump.

Ideal loads exist only in the separate diagnostic branch. Native real-coil and
fan electricity must be zero there. This is a declared 3-person reference slice,
not a completed envelope of arbitrary household peak services or sizing choice.
"""
import copy
import argparse
from pathlib import Path
import shutil
import subprocess

from national_idf.common import ROOT, read, require, save
from national_idf.idf import Fields, objects, parse, render
from national_idf.source_adapter import source_file, housing_fingerprint
from national_idf.reference_workflow import ref
from national_idf.reference_design import design_pair
from national_idf.program_resources import plan_resources

OUT=ROOT/'reports/multicountry_joint_review_20261108'


def program_schedules(rows, fixture, fields, mode, step):
    """Replay complete source resource windows, including water and all gains."""
    require(mode in ('none','source_windows'),'DESIGN_RESOURCE_MODE')
    pack=read(source_file(fixture['resource_pack'],ROOT))
    schedules={s for p in pack['programs'].values() for s in p['schedules']}
    values={name:[0.]*(1440//step) for name in schedules}
    events=[]
    if mode=='source_windows':
        plan=plan_resources(rows,fixture['engine_schema'],fixture['resource_pack'])
        require(plan['step_min']==step,'DESIGN_RESOURCE_PROFILE_STEP_NOT_BOUND')
        starts={'washer':720,'dishwasher':720,'dryer':780}
        for device,program in plan['values']['programs'].items():
            start=starts[device]//step
            for name,profile in program['channels'].items():
                require(start+len(profile)<=len(values[name]),'DESIGN_PROGRAM_CROSSES_DAY')
                values[name][start:start+len(profile)]=profile
            events.append({'device':device,'start_min':starts[device],'duration_min':program['duration_min'],
                'source_profile':plan['profile'],'physically_shared_asset_claimed':False})
    result=copy.deepcopy(rows)
    for i,row in enumerate(result):
        if row[0]!='Schedule:File' or row[1] not in schedules:continue
        if mode=='none':result[i]=['Schedule:Constant',row[1],row[2],'0'];continue
        compact=['Schedule:Compact',row[1],row[2],'Through: 12/31','For: AllDays','Interpolate: No']
        for j,value in enumerate(values[row[1]],1):
            minute=j*step;compact += [f'Until: {minute//60:02d}:{minute%60:02d}',format(value,'.17g')]
        result[i]=compact
    return result,events


def execute(*, output_base=None, persons=3, resource_mode='none', fixture_path=None, ddy_path=None, solver_step=None):
    parent=ROOT/'reports/multicountry_life_20261108/ES'
    fixture_path=Path(fixture_path).resolve() if fixture_path else parent/'FIXTURE_SCOPED.json'
    fixture=read(fixture_path);source=parse(source_file(fixture['model'],ROOT).read_text())
    fields=Fields(source_file(fixture['engine_schema'],ROOT))
    site=read(ROOT/'reports/multicountry_idf_20261107/ES_SITE_PACK_v2.json')
    ddy=ref(Path(ddy_path).resolve()) if ddy_path else site['design_conditions']['ddy']
    location,days,join=design_pair(ddy,fixture['weather'],fields)
    join.update(annual_weather_used_for_design_simulation=True,
                annual_weather_used_for_design_day_meteorology=False,
                annual_weather_role='Kiva initialization;DDY supplies the design-day meteorology')
    require(type(persons) is int and 0<=persons<=3,'DESIGN_OCCUPANCY_OUTSIDE_CURRENT_DOMAIN')
    step=read(source_file(fixture['input_domain'],ROOT))['solver_step_min']
    solver_step=solver_step or step
    require(solver_step in (1,2,5),'DESIGN_UNREGISTERED_SOLVER_STEP')
    prepared,events=program_schedules(source,fixture,fields,resource_mode,step)
    activity=read(source_file(fixture['input_domain'],ROOT))['bounds']['activity_W']
    require(activity[0]==activity[1],'DESIGN_ACTIVITY_NOT_FIXED')
    scope={'schema':'national_idf.reference_design_load_slice.v1','fixture':ref(fixture_path),
        'design_conditions':join,'persons':persons,'activity_W_per_person':activity[0],
        'program_resource_windows':events if events else 'none during design instrument;not a household coincidence claim',
        'general_water_draws':'none;retained independent aggregate heat/moisture background',
        'setpoints_C':{'heating':20.,'cooling':25.5555555555556},
        'solver_step_min':solver_step,'unchanged_source_programme_grid_min':step,
        'design_day_meteorology':'Selected source DDY rows',
        'annual_epw_required_for_Kiva_initialization':True,
        'soil_and_foundation':'unchanged complete public experimental reference;not measured site soil',
        'ideal_load_parameters_source':ref(ROOT/'work/p1_hpxml_004ca3ce/HPXMLtoOpenStudio/resources/hvac.rb'),
        'household_generator_or_AB_changed':False,'capacity_selection_approved':False,'formal_admitted':False}
    base=Path(output_base).resolve() if output_base else OUT/'ES_design_slice'
    require(base.is_relative_to(ROOT),'DESIGN_OUTPUT_OUTSIDE_PROJECT')
    base.mkdir(parents=True,exist_ok=True)
    if (base/'SCOPE.json').exists():require(read(base/'SCOPE.json')==scope,'DESIGN_SOURCE_SCOPE_CHANGED')
    save(base/'SCOPE.json',scope)
    for branch in ('independent_ideal_load','installed_heatpump'):
        folder=base/branch;folder.mkdir(exist_ok=True);rows=copy.deepcopy(prepared)
        objects(rows,'Timestep')[0][1]=str(60//solver_step)
        rows=[r for r in rows if r[0] not in ('Site:Location','RunPeriod','Output:Variable') and not r[0].startswith('SizingPeriod:')]
        rows.extend([location,*days.values()])
        for row in objects(rows,'SimulationControl'):
            for name,value in {'do_zone_sizing_calculation':'No','do_system_sizing_calculation':'No',
                'do_plant_sizing_calculation':'No','run_simulation_for_sizing_periods':'Yes',
                'run_simulation_for_weather_file_run_periods':'No'}.items():fields.set(row,name,value)
        constants={r[1]:r for r in objects(rows,'Schedule:Constant')}
        for name,value in [('EB_LIFE_count',format(persons/3,'.17g')),('EB_LIFE_fixture_flow','0'),
                           ('EB source HVAC availability','0' if branch=='independent_ideal_load' else '1')]:
            require(name in constants,'DESIGN_INPUT_CONSTANT_MISSING',name);fields.set(constants[name],'hourly_value',value)
        mapping=fixture['EB_mapping'];ev=next(r for r in objects(rows,'ElectricEquipment') if r[1]==mapping['equipment']['ev']['equipment'])
        ev_schedule=fields.get(ev,'schedule_name');fields.set(constants[ev_schedule],'hourly_value','0')
        rows += [['Schedule:Constant','DESIGN_HEATING','Temperature','20'],
                 ['Schedule:Constant','DESIGN_COOLING','Temperature','25.5555555555556']]
        for row in objects(rows,'ThermostatSetpoint:DualSetpoint'):
            fields.set(row,'heating_setpoint_temperature_schedule_name','DESIGN_HEATING')
            fields.set(row,'cooling_setpoint_temperature_schedule_name','DESIGN_COOLING')
        if branch=='independent_ideal_load':
            require(not objects(rows,'ZoneHVAC:IdealLoadsAirSystem'),'DESIGN_SOURCE_HAS_IDEAL')
            ideal=['ZoneHVAC:IdealLoadsAirSystem']
            values={'name':'DESIGN_IDEAL_INSTRUMENT','availability_schedule_name':'Always On Discrete',
                'zone_supply_air_node_name':'DESIGN_IDEAL_SUPPLY','maximum_heating_supply_air_temperature':'50',
                'minimum_cooling_supply_air_temperature':'10','maximum_heating_supply_air_humidity_ratio':'0.015',
                'minimum_cooling_supply_air_humidity_ratio':'0.01','heating_limit':'NoLimit','cooling_limit':'NoLimit',
                'dehumidification_control_type':'None','humidification_control_type':'None'}
            for key,value in values.items():fields.set(ideal,key,value)
            rows.append(ideal)
            equipment=objects(rows,'ZoneHVAC:EquipmentList');require(len(equipment)==1,'DESIGN_ZONE_EQUIPMENT_SCOPE')
            old=equipment[0];require(old[3:7]==['ZoneHVAC:AirDistributionUnit','ADU mshp terminal','1','1'],'DESIGN_SOURCE_EQUIPMENT_SEQUENCE')
            old[5:7]=['2','2'];old.extend(['ZoneHVAC:IdealLoadsAirSystem','DESIGN_IDEAL_INSTRUMENT','1','1','',''])
            connections=objects(rows,'ZoneHVAC:EquipmentConnections')[0]
            name=fields.get(connections,'zone_air_inlet_node_or_nodelist_name')
            inlet=next(r for r in objects(rows,'NodeList') if r[1]==name);inlet.append('DESIGN_IDEAL_SUPPLY')
        require(housing_fingerprint(rows)==housing_fingerprint(source),'DESIGN_CHANGED_HOUSING')
        for variable in ('Site Outdoor Air Drybulb Temperature','Zone Mean Air Temperature',
            'Zone Thermostat Heating Setpoint Temperature','Zone Thermostat Cooling Setpoint Temperature',
            'Zone Ideal Loads Supply Air Total Heating Rate','Zone Ideal Loads Supply Air Total Cooling Rate',
            'Heating Coil Heating Rate','Cooling Coil Total Cooling Rate',
            'Heating Coil Electricity Energy','Cooling Coil Electricity Energy','Fan Electricity Energy',
            'People Occupant Count','People Total Heating Rate','Electric Equipment Electricity Energy',
            'Other Equipment Convective Heating Energy','Other Equipment Latent Gain Energy',
            'Water Use Equipment Total Volume'):
            rows.append(['Output:Variable','*',variable,'Timestep'])
        (folder/'in.idf').write_text(render(rows))
        for dep in fixture['dependencies']:
            target=folder/dep['output_path'];target.parent.mkdir(parents=True,exist_ok=True)
            shutil.copyfile(source_file(dep['source'],ROOT),target)
        engine=next(source_file(item,ROOT) for item in fixture['official_engine_files'] if item['path'].endswith('/energyplus'))
        end=folder/'output/eplusout.end'
        if end.is_file() and '0 Severe Errors' not in end.read_text():
            archive=folder/'output_failed_attempt1';require(not archive.exists(),'DESIGN_PREVIOUS_FAILURE_ALREADY_ARCHIVED')
            (folder/'output').rename(archive)
        if not (folder/'output/eplusout.end').is_file():
            with (folder/'ENGINE.log').open('w') as stream:
                result=subprocess.run([str(engine),'-w',str(source_file(fixture['weather'],ROOT)),
                    '-d',str(folder/'output'),str(folder/'in.idf')],cwd=folder,stdout=stream,stderr=subprocess.STDOUT)
            require(result.returncode==0,'DESIGN_ENGINE_RUN_FAILED',branch)
        require('0 Severe Errors' in (folder/'output/eplusout.end').read_text(),'DESIGN_ENGINE_SEVERE',branch)
        save(folder/'PREPARATION.json',{'source_scope':ref(base/'SCOPE.json'),'branch':branch,
            'housing_unchanged':True,'official_engine':ref(engine),'formal_admitted':False})
        print(fixture['id'],branch,'design days executed',flush=True)


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--out');p.add_argument('--persons',type=int,default=3)
    p.add_argument('--resource-mode',choices=['none','source_windows'],default='none')
    p.add_argument('--fixture');p.add_argument('--ddy');p.add_argument('--step',type=int);args=p.parse_args()
    execute(output_base=args.out,persons=args.persons,resource_mode=args.resource_mode,fixture_path=args.fixture,ddy_path=args.ddy,solver_step=args.step)
