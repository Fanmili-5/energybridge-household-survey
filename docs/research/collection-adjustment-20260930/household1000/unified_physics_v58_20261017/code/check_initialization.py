"""Predeclared 50-household history-length sensitivity, without selecting outcomes."""
import argparse
from core import *
from analyze import values,energy,total

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
                            'within_predeclared_bounds':maximum<=state_bound and abs(el-es)<=energy_bound})
    report={'schema':VERSION,'physics_sha256':physics_hash(),'cases':len(records),'selection':'first and sixth saved dates of every original same-master subset50 household;fixed before revised runs,no outcome selection',
            'passed':all(r['within_predeclared_bounds']for r in records),'records':records,
            'short_run_bindings_sha256':sha(ROOT/'results'/args.short/'RUN_BINDINGS.json'),'long_run_bindings_sha256':sha(ROOT/'results'/args.long/'RUN_BINDINGS.json'),
            'short_label':args.short,'long_label':args.long,'weather_reference_year_fixed_across_histories':True,
            'criteria':{'maximum_primary_air_radiant_or_tank_node_delta_C':.2,'primary_facility_energy_delta':'max(0.2kWh,3%)'},
            'scope':'finite-history reference sensitivity;not measured annual thermal state or calibration'}
    save(ROOT/'INITIALIZATION_REVIEW.json',report)
    print(canonical({'cases':len(records),'passed':report['passed'],'outside_bounds':[{'case_id':r['case_id'],'state_C':r['maximum_primary_state_delta_C'],'energy_kWh':r['electricity_delta_kWh']}for r in records if not r['within_predeclared_bounds']]}))
    if not report['passed']:raise SystemExit(2)

if __name__=='__main__':main()
