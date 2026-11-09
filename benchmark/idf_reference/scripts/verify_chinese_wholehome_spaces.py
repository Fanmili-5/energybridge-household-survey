"""Compare explicit household air-node reduction against Chinese room nodes.

The IdealLoads systems are a load-calculation instrument, never hidden backup
for an EB physical configuration. No electrical consumption is inferred here.
"""
import copy
from pathlib import Path
import sqlite3
import subprocess

import numpy as np

from national_idf.common import ROOT, locked, read, require, save
from national_idf.idf import Fields, objects, parse, render
from national_idf.wholehome_spaces import group_air_nodes
from scripts.build_six_joint_source import ref


OUT = ROOT/'reports/china_wholehome_ports_20261102'
BASE = ROOT/'reports/china_native_semantics_20261102/ventilation_component/minimum_5min/in.idf'


def ideal_instrument(rows, zones, fields, controls):
    result = copy.deepcopy(rows)
    result += [['ScheduleTypeLimits','instrument_control_type',0,4,'Discrete'],
        ['Schedule:Constant','instrument_dual_control','instrument_control_type',4],
        ['ScheduleTypeLimits','instrument_temperature',-100,100,'Continuous','Temperature'],
        ['Schedule:Constant','instrument_heat','instrument_temperature',controls['heating_C']],
        ['Schedule:Constant','instrument_cool','instrument_temperature',controls['cooling_C']]]
    for zone in zones:
        name = 'instrument_'+zone
        result += [fields.obj('ThermostatSetpoint:DualSetpoint',name=name+'_targets',
            heating_setpoint_temperature_schedule_name='instrument_heat',
            cooling_setpoint_temperature_schedule_name='instrument_cool'),
            ['ZoneControl:Thermostat',name+'_control',zone,'instrument_dual_control',
                'ThermostatSetpoint:DualSetpoint',name+'_targets'],
            fields.obj('ZoneHVAC:IdealLoadsAirSystem',name=name,
                zone_supply_air_node_name=name+'_supply',maximum_heating_supply_air_temperature=50,
                minimum_cooling_supply_air_temperature=13,
                maximum_heating_supply_air_humidity_ratio=.015,
                minimum_cooling_supply_air_humidity_ratio=.009,
                heating_limit='NoLimit',cooling_limit='NoLimit',
                dehumidification_control_type='None',humidification_control_type='None',
                outdoor_air_economizer_type='NoEconomizer',heat_recovery_type='None'),
            ['ZoneHVAC:EquipmentList',name+'_list','SequentialLoad',
                'ZoneHVAC:IdealLoadsAirSystem',name,1,1],
            ['ZoneHVAC:EquipmentConnections',zone,name+'_list',name+'_supply','',name+'_air',name+'_return']]
    return result


def read_series(path):
    with sqlite3.connect(path) as c:
        times = c.execute('''select TimeIndex,Year,Month,Day,Hour,Minute,Interval
            from Time where coalesce(WarmupFlag,0)=0 order by TimeIndex''').fetchall()
        data = {}
        for di,key,name,units in c.execute('''select ReportDataDictionaryIndex,KeyValue,Name,Units
                from ReportDataDictionary where ReportingFrequency='Zone Timestep' '''):
            values = dict(c.execute('select TimeIndex,Value from ReportData where ReportDataDictionaryIndex=?',(di,)))
            if values:
                require(all(t[0] in values for t in times),'WHOLEHOME_MISSING_NATIVE_SERIES',[key,name])
                data[key.casefold(),name] = np.array([values[t[0]] for t in times])
        return [t[1:] for t in times], data


def main():
    runs_folder = OUT/'space_reduction_return_port';require(not runs_folder.exists(),'PRESERVE_REDUCTION_RUNS');runs_folder.mkdir()
    cards = read(ROOT/'reports/china_native_semantics_20261102/SOURCE_SERVICE_CARDS.json')
    fixture = read(ROOT/'reports/scoped_dwelling_installation_20261101/source_complete_observation/FIXTURE.json')
    engine = [locked(r,ROOT) for r in fixture['official_engine_files']]
    fields = Fields(next(p for p in engine if p.name.endswith('schema.epJSON')))
    original = parse(BASE.read_text())
    groups = {}
    for card in cards:
        groups[card['id']+'_conditioned'] = card['source_AC_flag_rooms']
        groups[card['id']+'_unconditioned'] = card['source_non_AC_flag_rooms']
    reduced,receipt = group_air_nodes(original,groups,fields)
    save(runs_folder/'REDUCTION.json',receipt)
    case_ref = ref(ROOT/'reports/shared_shadow_numerics_20261101/sources/winter/CASE.json')
    controls = read(locked(case_ref,ROOT))['controls']
    weather = read(ROOT/'reports/china_native_semantics_20261102/ventilation_component/PLAN.json')['weather']
    protocol = read(ROOT/'configs/study_protocol.json')
    save(runs_folder/'PLAN.json',{'source':ref(BASE),'household_service_scope':ref(ROOT/'reports/china_native_semantics_20261102/SOURCE_SERVICE_CARDS.json'),
        'engine':fixture['official_engine_files'],'weather':weather,'existing_EB_test_controls':case_ref,
        'protocol':ref(ROOT/'configs/study_protocol.json'),'implementation':ref(Path(__file__)),
        'space_adapter':ref(ROOT/'national_idf/wholehome_spaces.py'),
        'diagnostic_seasons':['winter','summer'],'duration_days':7,'timestep_min':5,
        'ideal_supply_test_boundary':{'heating_C':50,'cooling_C':13,'heating_humidity_ratio':.015,'cooling_humidity_ratio':.009,
            'purpose':'Unlimited ideal-load comparison instrument; not EB equipment or selected physical capacity'},
        'formal_admitted':False,'full_numerical_protocol':False})
    results = {}; native = {}
    for season,month in [('winter',1),('summer',7)]:
        for control in ('freefloat','load_instrument'):
            for topology,source in [('room_nodes',original),('household_nodes',reduced)]:
                label = season+'_'+control+'_'+topology
                folder = runs_folder/label;folder.mkdir()
                rows = copy.deepcopy(source)
                period = objects(rows,'RunPeriod')[0]
                for key,value in [('begin_month',month),('end_month',month),('begin_day_of_month',15),('end_day_of_month',21)]:
                    fields.set(period,key,value)
                if control == 'load_instrument':
                    zones = [n for c in cards for n in c['source_AC_flag_rooms']] if topology=='room_nodes' else [n for n in groups if n.endswith('_conditioned')]
                    rows = ideal_instrument(rows,zones,fields,controls)
                rows = [r for r in rows if r[0] != 'Output:Variable']
                for variable in ['Zone Mean Air Temperature','Zone Air Heat Balance Deviation Rate',
                    'Zone Ventilation Outdoor Density Volume Flow Rate','Zone Ventilation Fan Electricity Energy',
                    'Zone Ideal Loads Supply Air Sensible Heating Energy','Zone Ideal Loads Supply Air Sensible Cooling Energy']:
                    rows.append(['Output:Variable','*',variable,'Timestep'])
                target=folder/'in.idf';target.write_text(render(rows))
                cmd=[str(engine[0]),'-w',str(locked(weather,ROOT)),'-d',str(folder/'output'),str(target)]
                with (folder/'STDOUT.log').open('w') as log:
                    run=subprocess.run(cmd,cwd=folder,stdout=log,stderr=subprocess.STDOUT)
                end=folder/'output/eplusout.end'
                receipt={'input':ref(target),'command':cmd,'returncode':run.returncode,
                    'success':run.returncode==0 and end.exists() and 'Completed Successfully' in end.read_text()}
                save(folder/'RUN.json',receipt)
                require(receipt['success'],'WHOLEHOME_NATIVE_FAILURE',label)
                native[label]=read_series(folder/'output/eplusout.sql')
                results[label]=receipt
                save(runs_folder/'NATIVE_RUNS.json',results)
                print({'native_wholehome_run':label,'success':True},flush=True)
    analyze(runs_folder,original,cards,protocol,native)


def analyze(runs_folder,original,cards,protocol,native):
    fixture=read(ROOT/'reports/scoped_dwelling_installation_20261101/source_complete_observation/FIXTURE.json')
    fields=Fields(next(locked(r,ROOT) for r in fixture['official_engine_files'] if r['path'].endswith('schema.epJSON')))
    comparisons={}
    volume={r[1]:float(fields.get(r,'volume')) for r in objects(original,'Zone')}
    for season in ('winter','summer'):
        for control in ('freefloat','load_instrument'):
            prefix=season+'_'+control
            clock,a=native[prefix+'_room_nodes'];clock_b,b=native[prefix+'_household_nodes']
            require(clock==clock_b and len(clock)==2016,'WHOLEHOME_NATIVE_CLOCK')
            homes={}
            for card in cards:
                names=card['source_AC_flag_rooms'];group=card['id']+'_conditioned'
                first=sum(a[n.casefold(),'Zone Mean Air Temperature']*volume[n] for n in names)/sum(volume[n] for n in names)
                second=b[group.casefold(),'Zone Mean Air Temperature']
                # The existing protocol compares on a ten-minute grid.
                first,second=(v.reshape(-1,2).mean(axis=1) for v in (first,second))
                error=float(np.mean(np.abs(first-second)))
                loads={}
                for suffix in ('Heating','Cooling'):
                    variable='Zone Ideal Loads Supply Air Sensible '+suffix+' Energy'
                    if control=='load_instrument':
                        full=float(sum(a[('instrument_'+n).casefold(),variable].sum() for n in names))/3.6e6
                        grouped=float(b[('instrument_'+group).casefold(),variable].sum())/3.6e6
                        relative=abs(full-grouped)/abs(full) if full else (0 if grouped==0 else None)
                        loads[suffix]={'room_nodes_kWh_thermal':full,'household_nodes_kWh_thermal':grouped,
                            'relative_difference':relative,'passes_unchanged_1pct_target':relative is not None and relative<=protocol['numerical_criteria']['per_arm_energy_relative']}
                homes[card['id']]={'temperature_MAE_C':error,'passes_unchanged_temperature_target':error<=protocol['numerical_criteria']['zone_mean_absolute_C'],
                    'ideal_sensible_loads':loads,'complete_reduction_acceptance':False}
            comparisons[prefix]=homes
    passes=all(h['passes_unchanged_temperature_target'] and all(v['passes_unchanged_1pct_target'] for v in h['ideal_sensible_loads'].values()) for homes in comparisons.values() for h in homes.values())
    save(runs_folder/'COMPARISON.json',{'comparisons':comparisons,'passes_initial_component_screen':passes,
        'reduction_ready_for_formal_use':False,'formal_Chinese_configurations':0,
        'next_action':'Continue dynamic/annual validation before use' if passes else 'Keep source room air nodes; extend whole-home EB ports without merging failed topology',
        'no_electrical_consumption_inferred_from_ideal_thermal_loads':True})
    print({'wholehome_reduction_initial_screen':passes,'formal_admitted':False},flush=True)


if __name__=='__main__':
    import sys
    if sys.argv[1:]==['--analyze-existing']:
        folder=OUT/'space_reduction_return_port'
        require(not (folder/'COMPARISON.json').exists(),'PRESERVE_ANALYSIS')
        receipts=read(folder/'NATIVE_RUNS.json')
        require(len(receipts)==8 and all(r['success'] for r in receipts.values()),'NATIVE_MATRIX_INCOMPLETE')
        native={name:read_series(folder/name/'output/eplusout.sql') for name in receipts}
        analyze(folder,parse(BASE.read_text()),read(ROOT/'reports/china_native_semantics_20261102/SOURCE_SERVICE_CARDS.json'),
                read(ROOT/'configs/study_protocol.json'),native)
    else:
        require(not sys.argv[1:],'UNKNOWN_ARGUMENTS')
        main()
