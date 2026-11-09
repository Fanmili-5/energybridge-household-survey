"""Replay fixed source schedules through isolated EB bindings, not a new policy.

The original US source context remains intact. This is component integration
evidence only; it neither installs a China housing release nor generates tasks.
"""
import argparse
import importlib.util
import math
from pathlib import Path
import shutil
import sqlite3
import sys
import traceback

from national_idf.assembly import transform
from national_idf.common import ROOT, read, require, save, sha
from national_idf.idf import Fields, objects, parse, render
from national_idf.source_adapter import ADAPTER, housing_fingerprint, load_adapter, selector
from scripts.run_hpxml_component_reference import OUT, SOURCE, CHECKOUT

PROBE=OUT/'eb_reference_replay'


def artifact(path):return {'path':str(path.relative_to(ROOT)),'sha256':sha(path)}


def module(name,path):
    spec=importlib.util.spec_from_file_location(name,path)
    value=importlib.util.module_from_spec(spec);sys.modules[name]=value;spec.loader.exec_module(value)
    return value


def prepare(instrument=False):
    origin=OUT/'source_published_schedule/run';model=origin/'in.idf';rows=parse(model.read_text())
    sdk=read(SOURCE/'OFFICIAL_SDK.json');sdk_root=ROOT/sdk['extracted_to']
    engine=next(sdk_root.glob('*/EnergyPlus'));fields=Fields(engine/'Energy+.schema.epJSON')
    manifest={'schema':'national_idf.source_adapter.v1','adapter':ADAPTER,
        'id':'oshpxml_004ca3ce_component_reference','package_id':'OpenStudioHPXML_1.13_004ca3ce',
        'model':artifact(model),'engine_version':'25.2.0','housing_sha256':housing_fingerprint(rows),
        'thermal_zones':[r[1] for r in objects(rows,'Zone')],'legacy_groups':{},
        'schedule_files':[{'object':selector(rows,i),'original_filename':r[3],
            'file':artifact((origin/r[3]).resolve())} for i,r in enumerate(rows) if r[0]=='Schedule:File'],
        'support_conditions':{'use':'component_source_replay_only','source_country':'USA',
            'source_weather':'original Denver TMY3','Chinese_household_admitted':False},
        'source_scope_gaps':['Foreign source geometry is a component test context, not a Chinese housing original',
            'Published schedule replay does not establish per-cycle task or actual machine performance',
            'Source annual occupancy/use equations are not adopted for household generation']}
    path=ROOT/'configs/source_adapters/oshpxml_component_reference.json';save(path,manifest)
    ref=artifact(path);manifest,original=load_adapter(ref)
    spec={'changes':[],'legacy_group_policy':{}}
    new,inventory,dependencies=transform(spec,manifest,original)
    observations=[]
    if instrument:
        for name in ('Zone Mean Air Temperature','Zone Air Humidity Ratio'):
            observations.append(['Output:Variable','*',name,'Timestep'])
        programs=[r for r in objects(new,'EnergyManagementSystem:Program')
                  if any(line.lower().startswith('set qdryer') for line in r[2:])]
        require(len(programs)==1,'DRYER_AIRFLOW_SOURCE_PROGRAM_AMBIGUOUS')
        observations += [['EnergyManagementSystem:OutputVariable','Reference Dryer Exhaust Flow',
            'Qdryer','Averaged','ZoneTimestep',programs[0][1],'m3/s'],
            ['Output:Variable','*','Reference Dryer Exhaust Flow','Timestep']]
        new+=observations
    require(not PROBE.exists(),'OUTPUT_EXISTS',str(PROBE));PROBE.mkdir()
    (PROBE/'in.idf').write_text(render(new))
    for dep in dependencies:
        dest=PROBE/dep['output_path'];dest.parent.mkdir(exist_ok=True)
        shutil.copyfile(ROOT/dep['source']['path'],dest)
    mapping={'equipment':{},'water_heater':None,'hvac':{'zone':'conditioned space','availability':'Always On Discrete'}}
    cfg={key:{'present':False} for key in ('ev','water_heater','refrigerator')}
    aliases={'washer':'clothes washer','dryer':'clothes dryer','dishwasher':'dishwasher'}
    schedule_rows={r[1].casefold():r for r in new if r[0].startswith('Schedule:')}
    for key,name in aliases.items():
        obj=next(r for r in objects(new,'ElectricEquipment') if r[1]==name)
        power=float(fields.get(obj,'design_level'))
        schedule=fields.get(obj,'schedule_name')
        mapping['equipment'][key]={'equipment':name,'schedule_kind':schedule_rows[schedule.lower()][0]}
        cfg[key]={'present':True,'power_kw':power/1000}
    thermostat=objects(new,'ThermostatSetpoint:DualSetpoint')[0]
    for key,schedule in [('heating',thermostat[2]),('cooling',thermostat[3])]:
        mapping['hvac'][key]={'kind':schedule_rows[schedule.lower()][0],'schedule':schedule}
    auxiliary={r[1]:r[4] for r in objects(new,'WaterUse:Equipment') if r[1] in ('clothes washer','dishwasher')}
    # Dryer exhaust reads the same clothes_dryer Schedule:File as its power;
    # source airflow and normalization coefficients remain untouched.
    save(PROBE/'ADAPTER.json',{'source_adapter':ref,'changes':inventory,'dependencies':dependencies,
        'output_only_observations':observations,
        'housing_unchanged':housing_fingerprint(new)==manifest['housing_sha256'],
        'equipment_mapping':mapping,'suite_configuration_for_binding_only':cfg,'auxiliary_water_schedules':auxiliary,
        'source_control_scope':'fixed published schedule values; no generated activity, task or A/B control',
        'formal_admitted':False})
    return engine,new,mapping,cfg,auxiliary


def run(control=True,instrument=False):
    engine,rows,mapping,cfg,auxiliary=prepare(instrument)
    sql=OUT/'source_published_schedule/run/eplusout.sql';connection=sqlite3.connect(sql)
    times=connection.execute('SELECT TimeIndex,Month,Day,Hour,Minute FROM Time '
        'WHERE WarmupFlag=0 AND IntervalType=-1 ORDER BY TimeIndex').fetchall()
    schedules={}
    names={r[3] for r in objects(rows,'ElectricEquipment') if r[1] in ('clothes washer','clothes dryer','dishwasher')}
    names.update(auxiliary.values());names.update(mapping['hvac'][role]['schedule'] for role in ('heating','cooling'))
    for name in names:
        values=connection.execute("SELECT d.TimeIndex,d.Value FROM ReportData d JOIN ReportDataDictionary q "
            "ON d.ReportDataDictionaryIndex=q.ReportDataDictionaryIndex WHERE q.Name='Schedule Value' "
            "AND upper(q.KeyValue)=upper(?) AND q.ReportingFrequency='Zone Timestep' ORDER BY d.TimeIndex",(name,)).fetchall()
        require([r[0] for r in values]==[r[0] for r in times],'SOURCE_SCHEDULE_TIME_ALIGNMENT',name)
        schedules[name]=[r[1] for r in values]
    connection.close()
    new_eb=ROOT/'work/eb-native-component-20261029'
    suite_module=module('eb_reference_appliance_suite',new_eb/'appliance_sim.py')
    binding_module=module('eb_reference_appliance_binding',new_eb/'appliance_binding.py')
    suite=suite_module.ApplianceSuite(cfg,1,[],explicit_only=True)
    binding=binding_module.ApplianceBinding((PROBE/'in.idf').read_text(),engine/'Energy+.schema.epJSON',suite,mapping)
    implementation=[Path(__file__).resolve(),ROOT/'national_idf/source_adapter.py',ROOT/'national_idf/assembly.py',
                    new_eb/'appliance_binding.py',new_eb/'appliance_sim.py',engine/'energyplus',
                    engine/'Energy+.schema.epJSON']
    implementation_before={str(p.relative_to(ROOT)):sha(p) for p in implementation}
    sys.path.insert(0,str(engine))
    from pyenergyplus.api import EnergyPlusAPI
    api=EnergyPlusAPI();state=api.state_manager.new_state();binding.request_outputs(api.exchange,state)
    progress={'ticks':0,'writes':0,'auxiliary_writes':0,'initialized':False,'errors':[]}
    auxiliary_handles={}

    def active(s):return api.exchange.api_data_fully_ready(s) and not api.exchange.warmup_flag(s) and api.exchange.kind_of_sim(s)==3

    def before(s):
        if not active(s):return
        try:
            if not control:return
            if not progress['initialized']:
                binding.initialize(api.exchange,s)
                for schedule in auxiliary.values():
                    handle=api.exchange.get_actuator_handle(s,'Schedule:File','Schedule Value',schedule)
                    require(handle>=0,'SOURCE_WATER_SCHEDULE_ACTUATOR_MISSING',schedule)
                    auxiliary_handles[schedule]=handle
                progress['initialized']=True
            i=progress['ticks'];require(i<len(times),'REPLAY_TOO_MANY_TIMESTEPS')
            _,month,day,hour,minute=times[i]
            require((api.exchange.month(s),api.exchange.day_of_month(s))==(month,day)
                    and abs(api.exchange.current_time(s)-(hour+minute/60))<1e-8,'SOURCE_CLOCK_CHANGED',i)
            powers={name:schedules[spec['schedule']][i]*spec['design_W']/1000 for name,spec in binding.equipment.items()}
            binding.write(api.exchange,s,powers,
                cooling_C=schedules[mapping['hvac']['cooling']['schedule']][i],
                heating_C=schedules[mapping['hvac']['heating']['schedule']][i],available=True)
            for schedule,handle in auxiliary_handles.items():
                value=schedules[schedule][i]
                require(math.isfinite(value) and 0<=value<=1,'SOURCE_WATER_SCHEDULE_RANGE')
                api.exchange.set_actuator_value(s,handle,value);progress['auxiliary_writes']+=1
            progress['writes']+=1
        except Exception:
            progress['errors'].append(traceback.format_exc());api.runtime.stop_simulation(s)

    def after(s):
        if active(s):progress['ticks']+=1

    api.runtime.callback_begin_zone_timestep_before_init_heat_balance(state,before)
    api.runtime.callback_end_zone_timestep_after_zone_reporting(state,after)
    code=api.runtime.run_energyplus(state,['-w',str(CHECKOUT/'weather/USA_CO_Denver.Intl.AP.725650_TMY3.epw'),
         '-d',str(PROBE/'output'),str(PROBE/'in.idf')])
    api.state_manager.delete_state(state)
    save(PROBE/'RECEIPT.json',{'exit_code':code,'source_SQL':artifact(sql),'progress':progress,
        'EB_control_applied':control,'output_only_instrumentation':instrument,
        'expected_zone_steps':len(times),'source_profiles_used_without_generation':True,
        'physical_source_geometry_equipment_weather_unchanged':True,
        'source_source_file_references_relocated':True,'formal_admitted':False,
        'implementation_sha256':implementation_before,
        'implementation_unchanged':all(sha(ROOT/p)==h for p,h in implementation_before.items()),
        'runtime_scope':('EB component replay' if control else 'native source observer')+', not household policy or China configuration'})
    require(code==0 and not progress['errors'] and progress['ticks']==len(times)
            and progress['writes']==(len(times) if control else 0),'EB_SOURCE_REPLAY_FAILED',progress)
    print('EB source component replay completed',progress)


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--mode',choices=['original','native_observer','eb_instrumented',
        'native_observer_v2','eb_instrumented_v2'],default='original')
    args=parser.parse_args()
    if args.mode!='original':PROBE=OUT/args.mode
    run(control=not args.mode.startswith('native_observer'),instrument=args.mode!='original')
