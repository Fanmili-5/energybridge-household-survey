"""Predeclared 50-household history-length sensitivity, without selecting outcomes."""
import argparse
from core import *
from analyze import values,energy,total

def compare_contrasts(folders,pair):
    traces={label:{side:read(folder.parent/side/'TRACE.json.gz')for side in('A','B')}for label,folder in folders.items()}
    baseline,other=list(folders)
    primary={label:{side:total(energy(trace,'Electricity:Facility'),480,1920)for side,trace in sides.items()}for label,sides in traces.items()}
    contrast={label:d['B']-d['A']for label,d in primary.items()}
    temp=0.;actual_occupied=0.;absolute_occupied=0.
    for key in traces[baseline]['A']['channels']:
        if not key.startswith('Zone Mean Air Temperature|'):continue
        room=key.split('|')[1]
        occ={label:{s:values(trace,'Zone People Occupant Count',room)for s,trace in sides.items()}for label,sides in traces.items()}
        for i in range(48,192):
            if max(occ[label][side][i]for label in traces for side in('A','B'))<=0:continue
            diffs={label:sides['B']['channels'][key][i][1]-sides['A']['channels'][key][i][1]for label,sides in traces.items()}
            actual_occupied=max(actual_occupied,abs(diffs[baseline]-diffs[other]))
            if min(occ[label][side][i]for label in traces for side in('A','B'))>0:temp=max(temp,abs(diffs[baseline]-diffs[other]))
            for side in ('A','B'):
                if occ[baseline][side][i]>0:absolute_occupied=max(absolute_occupied,abs(traces[baseline][side]['channels'][key][i][1]-traces[other][side]['channels'][key][i][1]))
    portfolio={}
    for label,sides in traces.items():
        portfolio[label]={}
        for side,trace in sides.items():
            control=energy(trace,'Electricity:HVAC')
            control=[x+y+z for x,y,z in zip(control,energy(trace,'WaterSystems:Electricity'),energy(trace,'ExteriorEquipment:Electricity'))]
            inputs=read(folders[label].parent/side/'INPUT.json.gz')
            for fan in inputs['thermal_environment']['spot_exhaust']:
                control=[a-b for a,b in zip(control,energy(trace,'Fan Electricity Energy',fan['name']))]
            for key in inputs['equipment_meter_mapping']:
                control=[a+b for a,b in zip(control,energy(trace,'Electric Equipment Electricity Energy',key))]
            portfolio[label][side]=control
    events=[]
    for ev in pair['VPP_events']:
        a,z=ev['start_min'],ev['end_min'];responses={}
        for label,sides in portfolio.items():
            kw=(total(sides['B'],a,z)-total(sides['A'],a,z))*60/(z-a)
            responses[label]=kw if ev['direction']=='up'else-kw
        v,w=responses[baseline],responses[other];material=max(.05,.1*ev['target_kw'])
        relation=lambda x:'unchanged'if abs(x)<1e-6 else'aligned'if x>0 else'opposing'
        changed=relation(v)!=relation(w)
        events.append({'event_id':ev['event_id'],'target_kw':ev['target_kw'],'requested_direction_response_kw':responses,
                       'response_sensitivity_kw':abs(v-w),'materiality_kw':material,
                       'raw_direction_classification_changed':changed,
                       'material_direction_classification_changed':changed and max(abs(v),abs(w))>material,
                       'target_met_changed':(v>=ev['target_kw']-1e-6)!=(w>=ev['target_kw']-1e-6)})
    bound=max(.1,.1*abs(contrast[baseline]));difference=abs(contrast[baseline]-contrast[other])
    robust=actual_occupied<=.2 and difference<=bound and not any(e['material_direction_classification_changed']or e['target_met_changed']for e in events)
    return {'primary_facility_B_minus_A_kWh':contrast,'energy_contrast_sensitivity_kWh':difference,'energy_contrast_bound_kWh':bound,
            'occupied_air_temperature_contrast_sensitivity_C':temp,
            'actual_occupied_union_air_temperature_contrast_sensitivity_C':actual_occupied,
            'own_occupied_absolute_air_temperature_sensitivity_C':absolute_occupied,'temperature_contrast_bound_C':.2,
            'VPP_events':events,'conditional_comparison_robust_under_tested_scenarios':robust}

def main():
    p=argparse.ArgumentParser();p.add_argument('--short',default='initialization112');p.add_argument('--long',default='initialization224');args=p.parse_args()
    manifest=read(ROOT/'INPUT_MANIFEST.json');records=[]
    short_runs=read(ROOT/'results'/args.short/'RUN_BINDINGS.json');long_runs=read(ROOT/'results'/args.long/'RUN_BINDINGS.json')
    selected={r['case_id']for r in short_runs['records']}
    if selected!={r['case_id']for r in long_runs['records']}:raise ValueError('SENSITIVITY_CASE_SETS_DIFFER')
    for row in manifest['records']:
        if row['household_id']not in manifest['subset50_ids']:continue
        for case in row['cases']:
            if case['case_id']not in selected:continue
            folders={label:ROOT/'results'/label/row['household_id']/case['date']/'A'for label in (args.short,args.long)}
            inputs={label:read(f/'INPUT.json.gz')for label,f in folders.items()}
            if any(v['nonleap_weather_year_shift']!=1 for v in inputs.values()):raise ValueError('WEATHER_YEAR_CONFOUND')
            ss={label:read(f/'TRACE.json.gz')for label,f in folders.items()};short=ss[args.short];long=ss[args.long]
            bs={label:read(f.parent/'B/TRACE.json.gz')for label,f in folders.items()}
            state={};contrast=0.
            for key,v in short['channels'].items():
                if key.startswith(('Zone Mean Air Temperature|','Zone Mean Radiant Temperature|','Water Heater Final Temperature Node ')):
                    state[key]={'decision_delta_C':abs(v[47][1]-long['channels'][key][47][1]),
                                'primary_max_delta_C':max(abs(a[1]-b[1])for a,b in zip(v[48:192],long['channels'][key][48:192]))}
                    contrast=max(contrast,max(abs((bs[args.short]['channels'][key][i][1]-v[i][1])-(bs[args.long]['channels'][key][i][1]-long['channels'][key][i][1]))for i in range(48,192)))
            es=total(energy(short,'Electricity:Facility'),480,1920);el=total(energy(long,'Electricity:Facility'),480,1920)
            energy_bound=max(.2,.03*max(es,el));state_bound=.2
            maximum=max(x['primary_max_delta_C']for x in state.values())
            records.append({'case_id':case['case_id'],'short_effective_history_days':inputs[args.short]['history_days'],
                            'long_effective_history_days':inputs[args.long]['history_days'],
                            'short_trace_sha256':sha(folders[args.short]/'TRACE.json.gz'),'long_trace_sha256':sha(folders[args.long]/'TRACE.json.gz'),
                            'state_sensitivity':state,'maximum_primary_state_delta_C':maximum,'AB_contrast_max_sensitivity_C':contrast,
                            'short_primary_kWh':es,'long_primary_kWh':el,'electricity_delta_kWh':el-es,
                            'temperature_bound_C':state_bound,'electricity_bound_kWh':energy_bound,
                            'within_predeclared_bounds':maximum<=state_bound and abs(el-es)<=energy_bound,
                            'contrast_sensitivity':compare_contrasts(folders,read(ROOT/case['path']))})
    report={'schema':VERSION,'physics_sha256':physics_hash(),'cases':len(records),'selection':'first and sixth saved dates of every original same-master subset50 household;fixed before revised runs,no outcome selection',
            'passed':all(r['within_predeclared_bounds']for r in records),'records':records,
            'short_run_bindings_sha256':sha(ROOT/'results'/args.short/'RUN_BINDINGS.json'),'long_run_bindings_sha256':sha(ROOT/'results'/args.long/'RUN_BINDINGS.json'),
            'short_label':args.short,'long_label':args.long,'weather_reference_year_fixed_across_histories':True,
            'criteria':{'maximum_primary_air_radiant_or_tank_node_delta_C':.2,'primary_facility_energy_delta':'max(0.2kWh,3%)'},
            'conditional_comparisons_robust':sum(r['contrast_sensitivity']['conditional_comparison_robust_under_tested_scenarios']for r in records),
            'distinct_effective_history_cases':sum(r['short_effective_history_days']!=r['long_effective_history_days']for r in records),
            'robust_distinct_history_cases':sum(r['short_effective_history_days']!=r['long_effective_history_days']and r['contrast_sensitivity']['conditional_comparison_robust_under_tested_scenarios']for r in records),
            'validation_execution_passed':True,'scope':'finite-history sensitivity of absolute states AND occupied A/B contrasts,VPP direction and targets;not field calibration'}
    save(ROOT/'INITIALIZATION_REVIEW.json',report)
    print(canonical({'cases':len(records),'passed':report['passed'],'outside_bounds':[{'case_id':r['case_id'],'state_C':r['maximum_primary_state_delta_C'],'energy_kWh':r['electricity_delta_kWh']}for r in records if not r['within_predeclared_bounds']]}))
    if not report['passed']:raise SystemExit(2)

if __name__=='__main__':main()
