"""Offline EnergyPlus interface controls against an unmodified author checkout.

Uses the author's actual init/write functions and HVAC-availability injector.
The diagnostic repair has zero indoor heat gains to isolate electrical binding;
it is not a proposed calibrated building model or a production change.
"""
from __future__ import annotations
import argparse
import ast
from contextlib import redirect_stdout
from datetime import date, timedelta
import hashlib
import json
from pathlib import Path
import re
import sqlite3
import subprocess
import sys
from types import SimpleNamespace
from audit_upstream_appliance_binding import extract_function, DEVICES


def method(path, cls, name, namespace):
    tree=ast.parse(path.read_text())
    node=next(n for c in tree.body if isinstance(c,ast.ClassDef) and c.name==cls
              for n in c.body if isinstance(n,ast.FunctionDef) and n.name==name)
    module=ast.Module(body=[ast.ImportFrom(module='__future__',names=[ast.alias(name='annotations')],level=0),node],type_ignores=[])
    exec(compile(ast.fix_missing_locations(module),str(path),'exec'),namespace)
    return namespace[name]


def measure(root,ep,out,body,writer,init,generator,inject,design,variant):
    out.mkdir(parents=True)
    raw=out/'source.idf';raw.write_text(body)
    idf=generator(raw,out,start_date=date(2007,7,1),days=1)
    lines=inject(idf.read_text().splitlines())
    report=['Output:SQLite,SimpleAndTabular;', 'Output:Meter,Electricity:Facility,Timestep;',
            'Output:Meter,Cooling:Electricity,Timestep;']
    for name in ('Electric Equipment Electricity Energy','Water Heater Electricity Energy',
                 'Water Heater Tank Temperature','Zone Mean Air Temperature',
                 'Zone Thermostat Cooling Setpoint Temperature'):
        report.append('Output:Variable,*,'+name+',Timestep;')
    idf.write_text('\n'.join(lines+report)+'\n')
    sys.path.insert(0,str(ep))
    from pyenergyplus.api import EnergyPlusAPI
    api=EnergyPlusAPI();state=api.state_manager.new_state();ex=api.exchange
    api.runtime.set_console_output_status(state,False)
    loop=SimpleNamespace(ready=False,appliance_suite=None)
    handles={};commands=[];errors=[]
    def callback(s):
        try:
            if not init(loop,ex,s):return
            if not handles:
                handles.update({key:getattr(loop,'h_'+key) for key in (*DEVICES,'ev','ewh_sp','cool','heat','hvac_avail')})
            if ex.warmup_flag(s) or ex.kind_of_sim(s)!=3:return
            h=round(ex.current_time(s),8)
            start=20 if variant=='fixed_shifted' else 18
            active=start<=h<start+1
            frac=1 if variant=='fixed_full' else .5
            four=variant in ('original_four','fixed_half','fixed_full','fixed_shifted')
            powers={key:design[key]/1000*frac if active and four else 0.0 for key in DEVICES}
            powers['ev']=3.5 if variant=='original_ev' and active else 0.0
            wh=SimpleNamespace(_days={0:{'preheat_requested':variant=='original_ewh',
                'preheat_start_h':18,'preheat_end_h':19,'preheat_temp_c':65}},
                pre_heat_window_start_h=18,pre_heat_window_end_h=19,explicit_only=True)
            loop.appliance_suite=SimpleNamespace(_water_heater=wh)
            writer(ex,s,loop,powers,h)
            cool=24 if variant=='original_cool24' else 28 if variant=='original_cool28' else 26
            ex.set_actuator_value(s,loop.h_cool,cool)
            ex.set_actuator_value(s,loop.h_heat,18)
            ex.set_actuator_value(s,loop.h_hvac_avail,1)
            commands.append({'hour':h,'powers_kw':powers,'cooling_c':cool,
                             'ewh_setpoint_c':ex.get_actuator_value(s,loop.h_ewh_sp)})
        except Exception as e:
            errors.append(repr(e));api.runtime.stop_simulation(s)
    api.runtime.callback_end_system_timestep_after_hvac_reporting(state,callback)
    weather=root/'experiments/weather/epw/CHN_TJ_Tianjin.545270_CSWD.epw'
    with (out/'console.txt').open('w') as log,redirect_stdout(log):
        code=api.runtime.run_energyplus(state,['-w',str(weather),'-d',str(out),str(idf)])
    api.state_manager.delete_state(state)
    assert code==0 and not errors,(variant,code,errors)
    db=sqlite3.connect(out/'eplusout.sql')
    rows=db.execute('''SELECT d.Name,d.KeyValue,d.Units,t.Hour,t.Minute,r.Value
       FROM ReportData r JOIN ReportDataDictionary d USING(ReportDataDictionaryIndex)
       JOIN Time t USING(TimeIndex) JOIN EnvironmentPeriods e USING(EnvironmentPeriodIndex)
       WHERE t.WarmupFlag=0 AND e.EnvironmentType=3
       AND d.ReportingFrequency IN ('Zone Timestep','HVAC System Timestep') ORDER BY t.TimeIndex''').fetchall();db.close()
    series={}
    for name,key,unit,h,m,value in rows:
        series.setdefault(name+'|'+(key or ''),{'unit':unit,'values':[]})['values'].append([h+m/60,value])
    result={'exit_code':code,'handles':handles,'series':series,'commands':commands,
            'idf_sha256':hashlib.sha256(idf.read_bytes()).hexdigest(),
            'weather_sha256':hashlib.sha256(weather.read_bytes()).hexdigest()}
    (out/'readback.json').write_text(json.dumps(result,indent=2))
    return result


def values(row,name,key=None):
    found=[v for k,v in row['series'].items() if k.split('|')[0].lower()==name.lower()
           and (key is None or k.split('|')[1].lower()==key.lower())]
    assert len(found)==1,(name,key,list(row['series']))
    if name.endswith('Energy') or name.endswith(':Electricity') or name=='Electricity:Facility':
        assert found[0]['unit']=='J',(name,found[0]['unit'])
    return found[0]['values']


def kwh(row,name,key=None):return sum(v for h,v in values(row,name,key))/3600000


def main():
    p=argparse.ArgumentParser();p.add_argument('--upstream',type=Path,required=True)
    p.add_argument('--ep-root',type=Path,required=True);p.add_argument('--output',type=Path,required=True)
    a=p.parse_args();root=a.upstream.resolve();a.output.mkdir(parents=True,exist_ok=False)
    def audit(event,args):
        if event in ('socket.connect','socket.getaddrinfo'):raise RuntimeError('Offline interface test forbids network')
    sys.addaudithook(audit)
    runner=root/'experiments/benchmark/family_runner.py';tree=ast.parse(runner.read_text())
    design=next(ast.literal_eval(n.value) for n in tree.body if isinstance(n,ast.Assign)
       and any(isinstance(t,ast.Name) and t.id=='_APPL_DESIGN_W' for t in n.targets))
    writer=extract_function(runner,'_write_appliance_actuators',{'_APPL_DESIGN_W':design})
    init=method(runner,'_FamilyLoop','init',{})
    namespace={'Path':Path,'date':date,'timedelta':timedelta}
    extract_function(root/'energybridge/data/day_ahead.py','_idf_field',namespace)
    generator=extract_function(root/'energybridge/data/day_ahead.py','generate_runperiod_idf',namespace)
    prep_namespace={}
    extract_function(root/'experiments/benchmark/run_persona_json.py','_idf_field',prep_namespace)
    inject=extract_function(root/'experiments/benchmark/run_persona_json.py','_enable_hvac_availability_control',prep_namespace)
    report={'commit':subprocess.check_output(['git','-C',str(root),'rev-parse','HEAD'],text=True).strip(),
      'energyplus_version':subprocess.check_output([str(a.ep_root/'energyplus'),'--version'],text=True).strip(),
      'test_script_sha256':hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
      'writer_sha256':hashlib.sha256(ast.dump(next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name=='_write_appliance_actuators')).encode()).hexdigest(),
      'paid_api_calls':0,'network_forbidden':True,'production_changed':False,
      'scope':'Electrical/mechanical interface controls; both templates use Tianjin weather. Diagnostic repair uses zero indoor heat, not a calibrated model.',
      'templates':{}}
    for template in ('family_simple_3day.idf','berlin_family_geg_final.idf'):
        body=(root/'experiments/models/family_home'/template).read_text()
        fixed=body+'\n! Diagnostic electrical-only coupling, NOT production thermal parameters\n'
        for key,(prefix,_) in DEVICES.items():
            fixed+=f'Schedule:Constant,{prefix}_Power_Frac,Fraction,0;\nElectricEquipment,{prefix}_Appliance,living_unit1,{prefix}_Power_Frac,EquipmentLevel,{design[key]},,,0,0,1,Appliance interface probe;\n'
        runs={}
        for variant in ('original_off','original_four','original_ev','original_ewh','original_cool24',
                        'original_cool28','fixed_off','fixed_half','fixed_full','fixed_shifted'):
            row=measure(root,a.ep_root,a.output/template/variant,fixed if variant.startswith('fixed') else body,
                        writer,init,generator,inject,design,variant)
            runs[variant]=row
        off=runs['original_off']
        assert len(values(off,'Electricity:Facility'))==144
        assert all(off['handles'][key]==-1 for key in DEVICES)
        assert all(off['handles'][key]!=-1 for key in ('ev','ewh_sp','cool','heat','hvac_avail'))
        assert values(off,'Electricity:Facility')==values(runs['original_four'],'Electricity:Facility')
        assert values(off,'Electricity:Facility')==values(runs['fixed_off'],'Electricity:Facility')
        ev=kwh(runs['original_ev'],'Electric Equipment Electricity Energy','EV_CHARGER')
        assert abs(ev-3.5)<1e-8,ev
        four={}
        for variant in ('fixed_half','fixed_full','fixed_shifted'):
            row=runs[variant];factor=1 if variant=='fixed_full' else .5;start=20 if variant=='fixed_shifted' else 18
            assert all(row['handles'][key]!=-1 for key in DEVICES)
            expected_total=sum(design[key] for key in DEVICES)/1000*factor
            assert abs(kwh(row,'Electricity:Facility')-kwh(off,'Electricity:Facility')-expected_total)<1e-7
            four[variant]={}
            for key,(prefix,_) in DEVICES.items():
                points=values(row,'Electric Equipment Electricity Energy',prefix+'_Appliance')
                amount=kwh(row,'Electric Equipment Electricity Energy',prefix+'_Appliance')
                active=[h for h,v in points if v>1e-8]
                assert abs(amount-design[key]/1000*factor)<1e-7,(template,variant,key,amount)
                assert len(active)==6 and all(start<h<=start+1+1e-7 for h in active),(key,active)
                four[variant][key]={'kwh':amount,'active_end_hours':active}
        wh_off=kwh(off,'Water Heater Electricity Energy','WATER HEATER_TANK_UNIT1')
        wh_on=kwh(runs['original_ewh'],'Water Heater Electricity Energy','WATER HEATER_TANK_UNIT1')
        assert abs(wh_off-wh_on)>1e-5,(wh_off,wh_on)
        cold=kwh(runs['original_cool24'],'Cooling:Electricity')
        warm=kwh(runs['original_cool28'],'Cooling:Electricity')
        assert abs(cold-warm)>1e-5,(cold,warm)
        report['templates'][template]={'passed':True,'cases':len(runs),'original_handles':off['handles'],
          'four_dynamic_inputs_original_meter_unchanged':True,'zero_input_fix_preserves_facility':True,
          'original_facility_kwh':kwh(off,'Electricity:Facility'),'ev_pulse_kwh':ev,
          'ewh_40c_kwh':wh_off,'ewh_65c_window_kwh':wh_on,
          'cooling_24c_kwh':cold,'cooling_28c_kwh':warm,'device_readbacks':four}
        (a.output/'report.json').write_text(json.dumps(report,indent=2))
        print(template,'PASS',flush=True)
    print('All interface positive and negative controls passed; no model calls.',flush=True)

if __name__=='__main__':main()
