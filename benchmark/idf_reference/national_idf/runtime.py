"""Isolated native engine execution and read-only SQL; no success from missing runs."""
from __future__ import annotations
import datetime as dt
import csv
import math
from pathlib import Path
import re
import sqlite3
import subprocess
import os
import time
import numpy as np

from .common import ROOT, require, read, save, sha, verify, seal,digest,code_identity
from .devices import select_hvac, performance_reference
from .idf import parse, objects


def execute(compiled:Path,out:Path,engine:Path,timeout_s=600,*,mode='formal'):
    from .governance import reference_only
    reference_only(mode)
    engine=engine.resolve()
    verify(compiled);c=read(compiled/'COMPILATION.json')
    require(not out.exists(),'RUN_OUTPUT_EXISTS',str(out));out.mkdir(parents=True)
    executable=engine/'energyplus';pin=read(ROOT/'configs/engine.json')
    require(sha(executable)==pin['executable']['sha256'],'UNREGISTERED_ENGINE')
    require(c['expected_engine_sha256']==sha(executable)and c['engine_schema_sha256']==sha(engine/'Energy+.schema.epJSON')
            and c['engine_idd_sha256']==sha(engine/'Energy+.idd'),'COMPILED_ENGINE_VERSION_MISMATCH')
    require(sha(engine/'Energy+.idd')==pin['idd_sha256'],'ENGINE_IDD_CHANGED')
    overlay=pin.get('numerical_patch')
    require(c.get('engine_overlay_identity',digest(None))==digest(overlay),'ENGINE_OVERLAY_CONFIGURATION_MISMATCH')
    env=os.environ.copy();env['OMP_NUM_THREADS']='1'
    # Research builds may retain a build-directory LC_RPATH. Pin that actual
    # library as well as the packaged copy, and exclude ambient loader hooks.
    for name in ('DYLD_INSERT_LIBRARIES','DYLD_LIBRARY_PATH','DYLD_FRAMEWORK_PATH','LD_PRELOAD','LD_LIBRARY_PATH'):
        env.pop(name,None)
    linked=pin.get('loader_library')
    if linked:
        require(sha(linked['path'])==linked['sha256']==pin['library_sha256'],'LINKED_ENGINE_LIBRARY_CHANGED')
    library=list(engine.glob('libenergyplusapi.*.dylib'))
    if library:require(sha(library[0])==pin['library_sha256'],'ENGINE_LIBRARY_CHANGED')
    weather=Path(c['weather']['path']);require(sha(weather)==c['weather']['sha256'],'RUN_WEATHER_CHANGED')
    cmd=[str(executable),'-w',str(weather),'-d',str(out.resolve()),str((compiled/'model.idf').resolve())]
    started=time.monotonic();error=None;rc=None
    with (out/'stdout.log').open('w')as stdout,(out/'stderr.log').open('w')as stderr:
        try:rc=subprocess.run(cmd,stdout=stdout,stderr=stderr,cwd=compiled,timeout=timeout_s,env=env).returncode
        except subprocess.TimeoutExpired:error='timeout'
        except OSError as e:error=str(e)
    err=(out/'eplusout.err').read_text(errors='replace')if(out/'eplusout.err').exists()else''
    end=(out/'eplusout.end').read_text(errors='replace')if(out/'eplusout.end').exists()else''
    severe=re.findall(r'\*\*\s*Severe\s*\*\*.*',err,re.I)
    fatal=re.findall(r'\*\*\s*Fatal\s*\*\*.*',err,re.I)
    unresolved=[line for line in err.splitlines()if re.search(
      r'did not converge|not converged|failed to converge|iteration limit exceeded|convergence.*not achieved',line,re.I)]
    resolution=None
    if overlay and rc==0:
        from .numerics import review
        resolution=review((out/'stderr.log').read_text(errors='replace'),overlay)
    remaining=unresolved
    if resolution and resolution['passed']and resolution['summary']['repairs']>0:
        remaining=[s for s in unresolved if 'WetBulb not converged'not in s]
    passed=rc==0 and not error and not severe and not fatal and not remaining and (out/'eplusout.sql').is_file()
    if resolution and not resolution['passed']:passed=False
    r={'schema':'national_idf.native_run.v1','compilation_sha256':sha(compiled/'COMPILATION.json'),
      'execution_mode':'engineering_reference','formal_admitted':False,
      'compiled_path':str(compiled.resolve()),'engine_sha256':sha(executable),'engine_idd_sha256':pin['idd_sha256'],
      'weather_sha256':sha(weather),'model_sha256':sha(compiled/'model.idf'),
      'command':cmd,'exit_code':rc,'error':error,'elapsed_s':time.monotonic()-started,
      'passed_numerical_execution':passed,'severe':severe,'fatal':fatal,'unresolved_iterations':unresolved,
      'remaining_unresolved_iterations':remaining,'numerical_resolution':resolution,
      'numerical_patch':overlay,
      'loader_library':linked,'ambient_loader_overrides_removed':True,
      'warning_count':len(re.findall(r'\*\*\s*Warning\s*\*\*',err,re.I)),
      'end_message':end,'sql_sha256':sha(out/'eplusout.sql')if(out/'eplusout.sql').is_file()else None,
      'err_sha256':sha(out/'eplusout.err')if(out/'eplusout.err').is_file()else None,
      'research_patch_applied':bool(overlay),'official_base_binary_modified':False,
      'physical_or_empirical_validity_inferred_from_exit':False}
    save(out/'RUN.json',r);seal(out,{'schema':'national_idf.run_manifest.v1','run_sha256':sha(out/'RUN.json')})
    return r


class SQL:
    def __init__(self,path:Path,environment_type=3):
        require(path.is_file(),'SQL_MISSING',str(path))
        self.conn=sqlite3.connect(path.resolve().as_uri()+'?mode=ro',uri=True)
        self.environment_type=environment_type
        self.dictionary=self.conn.execute('SELECT ReportDataDictionaryIndex,Name,KeyValue,Units,Type,ReportingFrequency FROM ReportDataDictionary').fetchall()
        self._rows=None;self._series={}
    def close(self):self.conn.close()
    def find(self,name,key=None):
        return [r for r in self.dictionary if r[1].lower()==name.lower()and(key is None or str(r[2]).lower()==key.lower())]
    def series(self,name,key=None,required=True):
        ds=self.find(name,key)
        if not ds:
            require(not required,'SQL_CHANNEL_MISSING',[name,key]);return None
        require(len(ds)==1,'SQL_CHANNEL_AMBIGUOUS',[name,key,len(ds)])
        idx,_,_,unit,kind,freq=ds[0]
        if idx in self._series:return self._series[idx]
        if self._rows is None:
            # The native SQLite file often has no dictionary-index covering
            # index. Stream it once, retaining the original read-only file.
            self._rows={}
            cursor=self.conn.execute('''SELECT r.ReportDataDictionaryIndex,t.TimeIndex,t.Month,t.Day,t.Hour,t.Minute,t.Interval,r.Value
          FROM ReportData r JOIN Time t USING(TimeIndex)
          JOIN EnvironmentPeriods e USING(EnvironmentPeriodIndex)
          WHERE COALESCE(t.WarmupFlag,0)=0 AND e.EnvironmentType=? ORDER BY t.TimeIndex''',(self.environment_type,))
            for row in cursor:self._rows.setdefault(row[0],[]).append(row[1:])
        rs=self._rows.get(idx,[])
        require(rs,'SQL_CHANNEL_EMPTY',[name,key])
        vals=np.array([r[6]for r in rs],float)
        require(np.isfinite(vals).all(),'SQL_NONFINITE',[name,key])
        result={'dictionary':ds[0],'rows':rs,'values':vals,'units':unit,'type':kind,'frequency':freq}
        self._series[idx]=result
        return result
    def energy(self,name,key=None,required=True):
        s=self.series(name,key,required)
        if s is None:return None
        require(s['type'].lower()=='sum'and s['units']in ('J','kWh'),'SQL_ENERGY_TYPE',[name,s['type'],s['units']])
        return float(s['values'].sum()/(3600000 if s['units']=='J'else 1))


def sizing_receipt(compiled:Path,run:Path):
    c=read(compiled/'COMPILATION.json');case=read(compiled/'case.json');r=read(run/'RUN.json')
    require(c['mode']=='ideal_load_sizing_diagnostic_only','SIZING_MODE')
    require(r['compilation_sha256']==sha(compiled/'COMPILATION.json')and r['passed_numerical_execution'],
            'SIZING_NATIVE_EXECUTION_FAILED')
    sql=SQL(run/'eplusout.sql',environment_type=1);zones={}
    try:
        for z in case['environment']['devices']['air_conditioner']['room_ids']:
            heat=sql.series('Zone Ideal Loads Supply Air Sensible Heating Rate','sizing_'+z)
            cool=sql.series('Zone Ideal Loads Supply Air Total Cooling Rate','sizing_'+z)
            zones[z]={'heating_W':float(heat['values'].max()),'cooling_W':float(cool['values'].max())}
    finally:sql.close()
    weather=c['weather']['registry_record'];temps=[]
    for info in weather.get('design_day_files',[]):
        p=ROOT/info['path'];require(sha(p)==info['sha256'],'DDY_HASH')
        for row in objects(parse(p.read_text(errors='replace')),'SizingPeriod:DesignDay'):
            if 'Htg' in row[1]and('99.6' in row[1]or'99.6%'in row[1]):temps.append(float(row[5]))
    # No design-day substitution with an arbitrary daily mean or a reference COP.
    require(bool(temps),'HEATING_DESIGN_DAY_MISSING')
    design_C=min(temps)
    profile=performance_reference()
    loads={'heating_design_C':design_C,'zones':zones,
      'load_basis':'actual_EnergyPlus_ideal_load_diagnostic_on_registered_99.6pct_heating_and0.4pct_cooling_DDY',
      'run_start':case['run']['start_date'],'run_end':case['run']['end_date'],
      'DDY_design_condition_applied_to_capacity_selection':True,
      'native_design_day_load_simulation_completed':True}
    selection=select_hvac(loads,profile,margin=case['design']['margin'],
                           max_units_per_zone=case['design']['max_units_per_zone'])
    selection.update({'design_environment_hash':c['design_inputs_hash'],
      'sizing_compilation_sha256':sha(compiled/'COMPILATION.json'),'sizing_sql_sha256':sha(run/'eplusout.sql'),
      'design_loads':loads,'load_and_DDY_temperature_not_identical_conditions':False})
    return selection


def audit(compiled:Path,run:Path):
    verify(compiled);verify(run)
    c=read(compiled/'COMPILATION.json');case=read(compiled/'case.json');r=read(run/'RUN.json')
    require(r['compilation_sha256']==sha(compiled/'COMPILATION.json'),'RUN_COMPILATION_BINDING')
    require(r['sql_sha256']and sha(run/'eplusout.sql')==r['sql_sha256'],'SQL_CHANGED_OR_MISSING')
    require(r['err_sha256']and sha(run/'eplusout.err')==r['err_sha256'],'NATIVE_LOG_CHANGED')
    checks={'native_numerical_execution':r['passed_numerical_execution']};metrics={};gaps=[]
    start=dt.date.fromisoformat(c['run']['start_date']);end=dt.date.fromisoformat(c['run']['end_date'])
    duration_hours=((end-start).days+1)*24
    expected=duration_hours if c['run']['reporting']=='Hourly'else duration_hours*60//c['run']['solver_step_min']
    sql=SQL(run/'eplusout.sql')
    try:
        facility=sql.series('Electricity:Facility')
        checks['facility_time_axis']=len(facility['values'])==expected
        checks['facility_nonnegative']=bool(np.min(facility['values'])>=-1e-6)
        metrics['facility_kWh']=sql.energy('Electricity:Facility')
        demand=sql.series('Facility Total Electricity Demand Rate')['values']
        metrics['power_connection']={'configured_W':case['environment']['supply_capacity_W'],
          'maximum_zone_timestep_mean_W':float(demand.max()),
          'overload_intervals':int(sum(demand>case['environment']['supply_capacity_W'])),
          'instantaneous_starting_current_not_modelled':True,
          'overload_does_not_implicitly_curtail_devices':True}
        category_names=['Heating:Electricity','Cooling:Electricity','Fans:Electricity',
                        'WaterSystems:Electricity','InteriorEquipment:Electricity','InteriorLights:Electricity']
        categories={name:sql.energy(name,required=False)for name in category_names}
        metrics['category_kWh']=categories
        if any(v is None for v in categories.values()):
            checks['meter_category_channels']=False
        else:
            residual=metrics['facility_kWh']-sum(categories.values());metrics['meter_residual_kWh']=residual
            checks['facility_meter_closure']=abs(residual)<=max(1e-5,metrics['facility_kWh']*1e-6)
        metrics['rooms']={}
        outdoor=sql.series('Site Outdoor Air Drybulb Temperature','Environment')
        for z in case['environment']['unit_zones']:
            t=sql.series('Zone Mean Air Temperature',z);rh=sql.series('Zone Air Relative Humidity',z)
            checks['room_time_axis:'+z]=len(t['values'])==expected and len(rh['values'])==expected
            checks['room_physical_bounds:'+z]=bool(t['values'].min()>-80 and t['values'].max()<80 and
              rh['values'].min()>=-.1 and rh['values'].max()<=100.1)
            metrics['rooms'][z]={'min_C':float(t['values'].min()),'max_C':float(t['values'].max()),
              'mean_C':float(t['values'].mean()),'RH_max_pct':float(rh['values'].max()),
              'RH_over_80_report_intervals':int(sum(rh['values']>80)),
              'actively_conditioned':z in case['environment']['devices']['air_conditioner']['room_ids']}
            names=['Internal Convective Heat Gain','Surface Convection','Interzone Air Transfer',
                   'Outdoor Air Transfer','System Air Transfer','System Convective Heat Gain']
            terms=[sql.series('Zone Air Heat Balance '+name+' Rate',z)['values']for name in names]
            storage=sql.series('Zone Air Heat Balance Air Energy Storage Rate',z)['values']
            residual=np.sum(terms,axis=0)-storage
            metrics['rooms'][z]['maximum_air_balance_residual_W']=float(max(abs(residual)))
            scale=float(sum(np.sum(abs(term))for term in terms))
            ratio=float(sum(abs(residual))/max(scale,1.))
            metrics['rooms'][z]['absolute_air_balance_residual_fraction']=ratio
            metrics['rooms'][z]['air_balance_exceeds_2W_intervals']=int(sum(abs(residual)>2))
            checks['zone_air_energy_balance:'+z]=ratio<=.01
            co2=sql.series('Zone Air CO2 Concentration',z)['values']
            metrics['rooms'][z]['CO2_max_ppm']=float(max(co2))
            metrics['rooms'][z]['CO2_over_1000_report_intervals']=int(sum(co2>1000))
            checks['CO2_finite_nonnegative:'+z]=bool(len(co2)==expected and min(co2)>=0)
        metrics['air_balance_criterion']={'integrated_absolute_residual_over_absolute_transfers_max':.01,
          'initial_2W_absolute_development_screen_retained_as_diagnostic':True,
          'criterion_revision_precedes_registered_study':True,
          'not_independent_empirical_accuracy':True}
        if c['airflow']['model']=='native_AirflowNetwork':
            balance={z:np.zeros(expected)for z in case['environment']['unit_zones']}
            for link in c['airflow']['links']:
                a=sql.series('AFN Linkage Node 1 to Node 2 Mass Flow Rate',link['surface'])['values']
                b=sql.series('AFN Linkage Node 2 to Node 1 Mass Flow Rate',link['surface'])['values']
                require(len(a)==expected and len(b)==expected,'AFN_LINK_TIME_AXIS')
                net=a-b;balance[link['zone']]-=net
                if link['peer_zone']:balance[link['peer_zone']]+=net
            metrics['airflow_mass_balance_max_kg_s']={z:float(max(abs(v)))for z,v in balance.items()}
            for z,v in metrics['airflow_mass_balance_max_kg_s'].items():checks['airflow_mass_balance:'+z]=v<=1e-5
        data=np.genfromtxt(compiled/'schedules.csv',delimiter=',',names=True,deletechars='',encoding='utf8')
        a=(start-dt.date(start.year,1,1)).days*144;b=a+duration_hours*6
        metrics['devices_kWh']={}
        for name in ['washer','dryer','dishwasher','ev']:
            measured=sql.energy('Electric Equipment Electricity Energy','target_'+name)
            expected_energy=float(data[name+'_power_W'][a:b].sum()/6000)
            metrics['devices_kWh'][name]={'measured':measured,'expected':expected_energy}
            checks['program_energy:'+name]=abs(measured-expected_energy)<=max(1e-5,abs(expected_energy)*1e-6)
        if case['environment']['devices']['dryer']['technology']=='vented':
            metrics['devices_kWh']['dryer']['exhaust_fan_kWh']=sql.energy('Fan Electricity Energy','target_dryer_exhaust')
        tank=sql.energy('Water Heater Electricity Energy','target_tank')
        metrics['devices_kWh']['water_heater']={'measured':tank}
        checks['tank_finite_energy']=tank>=0
        heater=sql.energy('Water Heater Heating Energy','target_tank')
        metrics['tank_energy']={'heating_kWh':heater,'electric_kWh':tank,
          'heat_loss_kWh':sql.energy('Water Heater Heat Loss Energy','target_tank'),
          'use_side_kWh':sql.energy('Water Heater Use Side Heat Transfer Energy','target_tank'),
          'net_transfer_kWh':sql.energy('Water Heater Net Heat Transfer Energy','target_tank'),
          'independent_node_storage_balance_not_claimed':True}
        names=['Heating','Heat Loss','Use Side Heat Transfer','Source Side Heat Transfer',
               'Off Cycle Parasitic Tank Heat Transfer','On Cycle Parasitic Tank Heat Transfer']
        terms={name:sql.energy('Water Heater '+name+' Energy','target_tank')for name in names}
        net=metrics['tank_energy']['net_transfer_kWh']
        vent=sql.energy('Water Heater Venting Heat Transfer Energy','target_tank')
        metrics['tank_energy']['native_signed_component_residual_kWh']=sum(terms.values())-vent-net
        checks['tank_component_energy_account']=abs(metrics['tank_energy']['native_signed_component_residual_kWh'])<max(1e-6,heater*1e-6)
        checks['tank_electric_conversion']=abs(heater-tank*case['environment']['devices']['water_heater']['efficiency'])<=max(1e-6,heater*1e-6)
        mixed_flow=sql.series('Mixed Delivery Flow','EMS')
        outlet=sql.series('Water Heater Use Side Outlet Temperature','target_tank')
        mains=sql.series('Site Mains Water Temperature','Environment')
        draw_schedule=sql.series('Schedule Value','hot_draw_fraction')
        require(len({len(x['values'])for x in [mixed_flow,outlet,mains,draw_schedule]})==1,'WATER_TIME_AXIS')
        hot_flow=draw_schedule['values']*c['water_heater']['peak_hot_flow_m3_s']
        active=mixed_flow['values']>1e-8
        fraction=np.divide(hot_flow,mixed_flow['values'],out=np.zeros_like(hot_flow),where=active)
        delivered=mains['values']+fraction*(outlet['values']-mains['values'])
        metrics['mixed_water']={'mixed_liters':float(sum(v*row[5]*60000 for v,row in zip(mixed_flow['values'],mixed_flow['rows']))),
          'minimum_report_interval_C':float(delivered[active].min())if active.any()else None,
          'flow_weighted_C':float(np.average(delivered[active],weights=mixed_flow['values'][active]))if active.any()else None,
          'not_instantaneous_minimum':True,'service_failure_intervals':int(sum(active&(delivered<
              case['environment']['devices']['water_heater']['minimum_delivery_C'])))}
        checks['mixed_water_volume']=abs(metrics['mixed_water']['mixed_liters']-float(data['mixed_demand_L_min'][a:b].sum()*10))<.02
        if c['mode']=='operational_six_devices':
            metrics['air_conditioners']={}
            heat_sp=sql.series('Schedule Value','heat_sp')['values']
            cool_sp=sql.series('Schedule Value','cool_sp')['values']
            available=sql.series('Schedule Value','hvac_available')['values']>.5
            for z,e in c['equipment'].items():
                h=sql.energy('Heating Coil Electricity Energy',e['heating_coil'])
                co=sql.energy('Cooling Coil Electricity Energy',e['cooling_coil'])
                fan=sql.energy('Fan Electricity Energy',e['fan'])
                aux=sql.energy('Heating Coil Electricity Energy',e['supplemental_coil'],required=False)
                heat=sql.series('Heating Coil Heating Energy',e['heating_coil'])
                zone_t=sql.series('Zone Mean Air Temperature',z)['values']
                intervals=np.array([row[5]/60 for row in outdoor['rows']])
                below=outdoor['values'] < -25
                metrics['air_conditioners'][z]={'heating_kWh':h,'cooling_kWh':co,'fan_kWh':fan,
                  'auxiliary_kWh':aux,'weather_below_operating_min_hours':float(sum(intervals[below])),
                  'heating_energy_below_operating_min_kWh':float(heat['values'][below].sum()/3600000),
                  'below_commanded_heating_setpoint_hours':float(sum(intervals[(zone_t<heat_sp-.5)&available])),
                  'above_commanded_cooling_setpoint_hours':float(sum(intervals[(zone_t>cool_sp+.5)&available])),
                  'manufacturer_point_bracket_exceeded_while_heating_intervals':int(sum((heat['values']>1)&
                     (outdoor['values']>c['profile']['outdoor_C'][-1])))}
                checks['explicit_auxiliary:'+z]=(aux is None or abs(aux)<1e-8)if e['supplemental_capacity_W']==0 else bool(e['supplemental_source'])
        eio=(run/'eplusout.eio').read_text(errors='replace')
        locations=[line for line in eio.splitlines()if line.lstrip().startswith('Site:Location,')]
        checks['engine_location_report_present']=bool(locations)
        if locations:
            location=next(csv.reader(locations));lat,lon,tz,elevation=map(float,location[2:6])
            expected_location=c['weather']['identity']
            checks['engine_location_matches_weather']=all(abs(a-b)<=limit for a,b,limit in
              [(lat,expected_location['latitude'],.011),(lon,expected_location['longitude'],.011),
               (tz,expected_location['timezone'],.011),(elevation,expected_location['elevation_m'],.11)])
        metrics['engine_location_lines']=locations
        gaps=c['unvalidated_assumptions']+['native_energy_comparison_not_available',
          'annual_hourly_outputs_do_not_validate_ten_minute_response']if c['run']['reporting']=='Hourly'else c['unvalidated_assumptions']
    finally:sql.close()
    result={'schema':'national_idf.physical_audit.v1','compilation_sha256':sha(compiled/'COMPILATION.json'),
      'execution_mode':'engineering_reference','formal_admitted':False,
      'auditor_code_identity':code_identity(),
      'run_sha256':sha(run/'RUN.json'),'checks':checks,'engineering_passed':all(checks.values()),
      'metrics':metrics,'evidence_gaps':gaps,'empirical_calibration':False,
      'scientific_scope':'frozen_source_bound_reference_case;not_national_stock_or_measured_home',
      'service_failures_are_results_not_numerical_failures':True,'human_answers_created':0}
    return result
