"""Check native resource timing, conservation and an intentional wiring fault."""
import math
import sqlite3

from national_idf.common import ROOT, read, require, save, sha
from scripts.run_whitegoods_shift import OUT, ALIASES, CHANNELS, ELECTRIC, SHIFTS, WATER


def series(folder):
    with sqlite3.connect(folder / 'output/eplusout.sql') as connection:
        values = connection.execute(
            'SELECT q.Name,q.KeyValue,t.Month,t.Day,t.Hour,t.Minute,d.Value FROM ReportData d '
            'JOIN ReportDataDictionary q ON q.ReportDataDictionaryIndex=d.ReportDataDictionaryIndex '
            'JOIN Time t ON t.TimeIndex=d.TimeIndex WHERE t.WarmupFlag=0 '
            "AND q.ReportingFrequency='Zone Timestep' ORDER BY d.TimeIndex").fetchall()
    result = {}
    for name, key, month, day, hour, minute, value in values:
        result.setdefault((name, (key or '').casefold()), []).append(value)
    return result


def difference(first, second, absolute=1e-10, relative=1e-11):
    require(len(first) == len(second), 'SERIES_LENGTH_CHANGED')
    maximum = max((abs(a-b) for a,b in zip(first,second)), default=0)
    scale = max((abs(v) for v in first + second), default=0)
    return {'count': len(first), 'max_abs': maximum, 'passed': maximum <= max(absolute,relative*scale)}


def translate(values, ticks):
    require(ticks >= 0 and all(v == 0 for v in values[len(values)-ticks:]) if ticks else True,
            'NONZERO_RESOURCE_TAIL_CLIPPED')
    return [0.0]*ticks + values[:len(values)-ticks] if ticks else values[:]


def compare_runs(first, second):
    a,b=series(first),series(second)
    require(set(a)==set(b),'SOURCE_ORACLE_OUTPUT_SET_CHANGED')
    reports={f'{key[0]} / {key[1]}':difference(a[key],b[key]) for key in a}
    return {'series':reports,'passed':all(r['passed'] for r in reports.values())}


def analyze():
    report={'cases':{},'formal_admitted':False,'measured_machine_cycle_validated':False,
            'Chinese_housing_admitted':False,'whole_house_numerical_acceptance_granted':False,
            'physical_cleaning_or_dryness_model':None,'resource_fidelity_tolerance':
            'Pointwise max(1e-10 native units,1e-11 peak scale); schedule fractions absolute1e-12. '
            'This is engineering replay fidelity, not a replacement of the study numerical protocol.'}
    report['analysis_implementation']={'path':str((ROOT/'scripts/analyze_whitegoods_shift.py').relative_to(ROOT)),
                                       'sha256':sha(ROOT/'scripts/analyze_whitegoods_shift.py')}
    report['water_heating_energy_meaning']='Native Water Use Equipment Heating Energy; not water-heater grid electricity and not added as another electric meter.'
    native={step:series(OUT/f'native_baseline_{step}min') for step in (1,2,5)}
    for folder in sorted(OUT.glob('eb_*min')):
        inputs=read(folder/'INPUTS.json');runtime=read(folder/'RUNTIME.json')
        require(runtime['exit_code']==0 and not runtime['progress']['errors'],'NATIVE_RUN_FAILED')
        step=inputs['step_min'];case=inputs['case'];base=native[step];actual=series(folder)
        result={'step_min':step,'case':case,'devices':{},'deliberate_fault':inputs['deliberate_fault']}
        for device,names in CHANNELS.items():
            shift=SHIFTS[case][device]*60//step;name=ALIASES[device]
            checks={}
            for schedule in names:
                key=('Schedule Value',schedule)
                checks[schedule]=difference(actual[key],translate(base[key],shift),absolute=1e-12,relative=0)
            gains={}
            for variable in ELECTRIC:
                key=(variable,name)
                gains[variable]=difference(actual[key],translate(base[key],shift))
            water={}
            for variable in WATER[:3]:
                key=(variable,name)
                water[variable]=difference(actual[key],translate(base[key],shift))
            account=max(abs(sum(actual[(v,name)][i] for v in ELECTRIC[1:])-actual[(ELECTRIC[0],name)][i])
                        for i in range(len(actual[(ELECTRIC[0],name)])))
            totals={'electricity_kWh':sum(actual[(ELECTRIC[0],name)])/3600000,
                    'source_device_heat_kWh':{v:sum(actual[(v,name)])/3600000 for v in ELECTRIC[1:]},
                    'native_water_L':{v:sum(actual[(v,name)])*1000 for v in WATER[:3]},
                    'native_external_water_heating_kWh':sum(actual[(WATER[-1],name)])/3600000}
            conserved={'electricity_kWh_difference':totals['electricity_kWh']-sum(base[(ELECTRIC[0],name)])/3600000,
                       'native_total_water_L_difference':totals['native_water_L'][WATER[2]]-sum(base[(WATER[2],name)])*1000}
            task_records=runtime['task_results'][device]
            completed=[row for row in task_records if row['scheduled_abs_h'] is not None]
            require(len(completed)==1 and completed[0]['completed'],'REFERENCE_TASK_DID_NOT_COMPLETE')
            draw=[i for i,v in enumerate(actual[(WATER[2],name)]) if v>0]
            delivery={'min_native_mixed_water_C':min(actual[('Water Use Equipment Mixed Water Temperature',name)][i] for i in draw),
                      'max_native_target_minus_mixed_K':max(max(0,actual[('Water Use Equipment Target Water Temperature',name)][i]
                          -actual[('Water Use Equipment Mixed Water Temperature',name)][i]) for i in draw),
                      'machine_cleaning_or_dryness_success':None}
            result['devices'][device]={'schedule_checks':checks,'electric_gain_timing':gains,'native_water_timing':water,
                'max_native_gain_account_residual_J':account,'totals':totals,'conservation':conserved,
                'native_delivery_observation':delivery,
                'reference_task_completed':True,'physical_service_success':None,
                'hot_cold_partition_translation_is_not_an_input_invariant':True,
                'source_resource_sync_passed':all(r['passed'] for r in checks.values())
                    and all(r['passed'] for r in gains.values())
                    and water['Water Use Equipment Total Volume']['passed']}
        # Dryer is not moved in this experiment; report exhaust separately.
        dryer_keys=[key for key in actual if key[1]=='clothes dryer' or key[0]=='ShiftAudit Dryer Exhaust Flow']
        result['uncontrolled_dryer_unchanged']={f'{k[0]}/{k[1]}':difference(actual[k],base[k]) for k in dryer_keys}
        result['all_selected_resource_sync_passed']=all(r['source_resource_sync_passed'] for r in result['devices'].values())
        report['cases'][folder.name]=result
    report['native_EB_baseline_comparison']=compare_runs(OUT/'native_baseline_1min',OUT/'eb_baseline_1min')
    report['independent_native_shifted_CSV_oracles']={str(step):compare_runs(
        OUT/f'native_both_shift_{step}min',OUT/f'eb_both_shift_{step}min') for step in (1,2,5)}
    report['hot_cold_partition_interpretation']=(
        'Total requested/delivered volume and source flow schedules must translate. Native hot/cold split, '
        'temperature and water heating energy are recomputed by the original hot-water system; they need not '
        'equal a shifted baseline. Their correctness is checked against an independently shifted native CSV '
        'oracle at each step, with the same fidelity threshold. First-pass invariance mismatches retained.')
    report['step_integrals']={}
    for step in (1,2,5):
        case=report['cases'][f'eb_both_shift_{step}min']
        report['step_integrals'][str(step)]={device:row['totals'] for device,row in case['devices'].items()}
    report['cross_step_resource_integrals']={}
    for step in (2,5):
        comparisons={}
        for device in CHANNELS:
            first=report['step_integrals']['1'][device];second=report['step_integrals'][str(step)][device]
            pairs={'electricity_kWh':(first['electricity_kWh'],second['electricity_kWh']),
                   'total_water_L':(first['native_water_L'][WATER[2]],second['native_water_L'][WATER[2]])}
            pairs.update({v:(first['source_device_heat_kWh'][v],second['source_device_heat_kWh'][v]) for v in ELECTRIC[1:]})
            comparisons[device]={key:difference([a],[b]) for key,(a,b) in pairs.items()}
        report['cross_step_resource_integrals'][str(step)]=comparisons
    fault=report['cases']['eb_washer_electric_only_1min']['devices']['washer']
    report['fault_detected_despite_integral_conservation']=(not fault['source_resource_sync_passed']
        and not fault['schedule_checks']['hot_water_clothes_washer']['passed']
        and fault['schedule_checks']['clothes_washer']['passed']
        and abs(fault['conservation']['electricity_kWh_difference'])<1e-10
        and abs(fault['conservation']['native_total_water_L_difference'])<1e-7)
    report['nonfault_replay_checks_passed']=all(row['all_selected_resource_sync_passed']
        for row in report['cases'].values() if not row['deliberate_fault'])
    save(OUT/'VALIDATION.json',report)
    print({'nonfault_passed':report['nonfault_replay_checks_passed'],
           'baseline_native_oracle_passed':report['native_EB_baseline_comparison']['passed'],
           'independent_shift_oracles_passed':{step:r['passed'] for step,r in report['independent_native_shifted_CSV_oracles'].items()},
           'deliberate_fault_detected':report['fault_detected_despite_integral_conservation'],
           'cases':len(report['cases'])})
    require(report['nonfault_replay_checks_passed'] and report['native_EB_baseline_comparison']['passed']
            and all(r['passed'] for r in report['independent_native_shifted_CSV_oracles'].values())
            and all(r['passed'] for comparison in report['cross_step_resource_integrals'].values()
                    for device in comparison.values() for r in device.values())
            and report['fault_detected_despite_integral_conservation'],'WHITEGOODS_SHIFT_VALIDATION_FAILED')


if __name__=='__main__':
    analyze()
