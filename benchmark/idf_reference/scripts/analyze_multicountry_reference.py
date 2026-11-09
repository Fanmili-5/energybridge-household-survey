"""Native ledgers and control checks; execution alone does not grant admission."""
import csv
from pathlib import Path

from national_idf.common import ROOT, read, require, save
from scripts.analyze_whitegoods_shift import series
from scripts.run_supply_reference import METERS

OUT=ROOT/'reports/multicountry_idf_20261107'


def analyze(folder,fixture,installed):
    data=series(folder);trace=list(csv.DictReader((folder/'TRACE.csv').open()));count=len(trace)
    get=lambda name,key='':data[name,key.casefold()]
    maximum=lambda a:max((abs(v) for v in a),default=0)
    runtime=read(folder/'RUNTIME.json');end=(folder/'output/eplusout.end').read_text()
    require(runtime['exit_code']==0 and not runtime['progress']['errors'] and '0 Severe Errors' in end,'REFERENCE_ENGINE_ERRORS')
    require(all(len(v)==count for v in data.values()),'REFERENCE_NATIVE_CLOCK_LENGTH')
    total=get('Electricity:Facility');leaves=[get(v+':Electricity') for v in METERS]
    facility=maximum(total[i]-sum(v[i] for v in leaves) for i in range(count))
    heaters=[get(v,'EB_WATER_water heater') for v in ('Water Heater Electricity Energy','Water Heater Off Cycle Parasitic Electricity Energy','Water Heater On Cycle Parasitic Electricity Energy')]
    tank=maximum(get('WaterSystems:Electricity')[i]-sum(v[i] for v in heaters) for i in range(count))
    equipment=[v for (name,key),v in data.items() if name in ('Electric Equipment Electricity Energy','Other Equipment Electricity Energy')]
    interior=maximum(get('InteriorEquipment:Electricity')[i]-sum(v[i] for v in equipment) for i in range(count))
    water={};volumes=[]
    names=['dhw fixtures','dhw distribution waste']+[name for device,name in [('washer','clothes washer'),('dishwasher','dishwasher')] if device in installed]
    for name in names:
        h,c,t=[get('Water Use Equipment '+v,'EB_WATER_'+name) for v in ('Hot Water Volume','Cold Water Volume','Total Volume')]
        water[name]={'total_L':sum(t)*1000,'hot_plus_cold_residual_m3':maximum(h[i]+c[i]-t[i] for i in range(count))}
        volumes.append(t)
    connection=maximum(get('Water Use Connections Total Volume','EB_WATER_Water Use Connections 1')[i]-sum(v[i] for v in volumes) for i in range(count))
    step=read(ROOT/fixture['input_domain']['path'])['solver_step_min'];powers={}
    for device,name in [('washer','clothes washer'),('dryer','clothes dryer'),('dishwasher','dishwasher'),('ev','EB outdoor reference EV')]:
        if device not in installed:
            require(('Electric Equipment Electricity Energy',name.casefold()) not in data,'ABSENT_DEVICE_STILL_METERED',device)
            continue
        values=get('Electric Equipment Electricity Energy',name)
        commands=[float(row[device+'_command_kW'])*step/60*3.6e6 for row in trace]
        powers[device]={'kWh':sum(values)/3.6e6,'command_minus_native_max_J':maximum(a-b for a,b in zip(commands,values))}
    control={}
    for schedule,key in [('heating setpoint','heating_C'),('cooling setpoint','cooling_C'),('EB source HVAC availability','hvac_available'),('EB_WATER_water heater setpoint','tank_target_C')]:
        expected=[float(row[key]) if key!='hvac_available' else float(row[key]=='True') for row in trace]
        control[key]=maximum(a-b for a,b in zip(expected,get('Schedule Value',schedule)))
    off=[i for i,row in enumerate(trace) if row['hvac_available']=='False']
    off_error=max((abs(get(variable,key)[i]) for variable,key in [('Heating Coil Electricity Energy','mshp htg coil'),('Cooling Coil Electricity Energy','mshp clg coil'),('Fan Electricity Energy','mshp supply fan')] for i in off),default=None)
    ev=runtime['EV']['EB_ledger'] if 'ev' in installed else None
    ev_error=abs(powers['ev']['kWh']-ev['grid_kwh']) if ev is not None else None
    tank_trace_error=abs(sum(float(row['water_heater']) for row in trace)-sum(get('Water Heater Electricity Energy','EB_WATER_water heater'))/3.6e6)
    gains={}
    for device,name in [('washer','clothes washer'),('dryer','clothes dryer'),('dishwasher','dishwasher')]:
        if device in installed:
            heat=[get('Electric Equipment '+v,name) for v in ('Convective Heating Energy','Radiant Heating Energy','Latent Gain Energy','Lost Heat Energy')]
            electricity=get('Electric Equipment Electricity Energy',name)
            gains[device]=maximum(electricity[i]-sum(v[i] for v in heat) for i in range(count))
    passed=max(facility,tank,interior,*gains.values(),*[v['command_minus_native_max_J'] for v in powers.values()])<1e-7
    passed=passed and (off_error is None or off_error<1e-7)
    passed=passed and connection<1e-12 and all(v['hot_plus_cold_residual_m3']<1e-12 for v in water.values()) and max(control.values())<1e-12 and tank_trace_error<1e-9
    if ev is not None:passed=passed and max(ev_error,abs(ev['residual_kwh']))<1e-9
    else:require(runtime['EV'] is None,'ABSENT_EV_WAS_SIMULATED')
    report={'schema':'national_idf.multicountry_native_checks.v1','passed_component_checks':passed,'ticks':count,
            'facility_kWh':sum(total)/3.6e6,'native_tank_kWh':sum(heaters[0])/3.6e6,
            'heating_kWh':sum(get('Heating:Electricity'))/3.6e6,'cooling_kWh':sum(get('Cooling:Electricity'))/3.6e6,
            'fan_kWh':sum(get('Fans:Electricity'))/3.6e6,
            'facility_enduse_residual_J':facility,'tank_meter_residual_J':tank,'interior_equipment_residual_J':interior,
            'water_connection_residual_m3':connection,'water_uses':water,'appliances':powers,'heat_partition_residual_J':gains,
            'control_readback_errors':control,'off_compressor_fan_max_J':off_error,
            'HVAC_off_check_applicable':bool(off),'HVAC_off_steps_checked':len(off),
            'EV_native_grid_minus_ledger_kWh':ev_error,'EV_battery_ledger_residual_kWh':ev['residual_kwh'] if ev is not None else None,
            'EV_departure_service':runtime['EV']['departure_service'] if ev is not None else None,'EB_tank_native_account_residual_kWh':tank_trace_error,
            'installed_devices':installed,'author_result_comparison':False,'numerical_acceptance':False,'formal_admitted':False,
            'source_resource_windows_not_measured_machine_cycles':True,'cleaning_and_dryness_not_validated':True}
    save(folder/'COMPONENT_CHECKS.json',report)
    require(passed,'REFERENCE_COMPONENT_CHECKS_FAILED',report)
    return report


def main():
    results={}
    for country in ('US','ES'):
        folder=OUT/(country+'_v2');fixture=read(folder/'FIXTURE.json')
        results[country]={}
        for name,devices in [('run',['air_conditioner','washer','dryer','dishwasher','water_heater','ev']),
                             ('four_run_v3',['air_conditioner','washer','water_heater','ev'])]:
            results[country][name]=analyze(folder/name,fixture,devices)
            print(country,name,'native component checks pass',results[country][name]['facility_kWh'])
    save(OUT/'NATIVE_COMPONENT_VALIDATION.json',{'schema':'national_idf.multicountry_component_validation.v1',
        'results':results,'method_acceptance_complete':False,'full_numerical_validation':False,'formal_admitted':False})


if __name__=='__main__':main()
