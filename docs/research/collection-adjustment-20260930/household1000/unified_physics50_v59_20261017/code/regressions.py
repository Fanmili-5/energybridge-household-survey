"""Adversarial readback checks; edits apply only to temporary copies."""
import argparse
import copy
import tempfile
from core import *
from compiler import day_people,merged_plan
from analyze import summarize_side,electricity_interpretation

def main():
    p=argparse.ArgumentParser();p.add_argument('--label',default='pilot50');args=p.parse_args()
    manifest=read(ROOT/'INPUT_MANIFEST.json');row=next(r for r in manifest['records']if r['household_id']==manifest['subset50_ids'][0]);case=row['cases'][0]
    original=ROOT/'results'/args.label/row['household_id']/case['date']/'A';pair=read(ROOT/case['path']);trace=read(original/'TRACE.json.gz');inputs=read(original/'INPUT.json.gz')
    records=[]
    def test(name,mutate,expected):
        with tempfile.TemporaryDirectory(prefix='eb58-negative-')as tmp:
            target=Path(tmp);tt=copy.deepcopy(trace);ii=copy.deepcopy(inputs);mutate(tt,ii)
            save(target/'TRACE.json.gz',tt);save(target/'INPUT.json.gz',ii)
            errors=summarize_side(pair,'A',target)[-1]['errors'];codes={x['code']for x in errors}
            records.append({'test':name,'caught':expected in codes,'observed_codes':sorted(codes)})
    def facility(t,i):t['channels']['Electricity:Facility|'][48][1]+=3600000
    test('omit_or_duplicate_facility_energy',facility,'FACILITY_METER_NOT_CLOSED')
    def program(t,i):
        name=next(k for k in t['channels']if k.startswith('Electric Equipment Electricity Energy|PROGRAM_')and any(x[1]>0 for x in t['channels'][k][48:192]))
        point=next(x for x in t['channels'][name]if 480<=x[0]<1920 and x[1]>0);point[1]=0
    test('silently_missing_program_electricity',program,'PROGRAM_METER_MISMATCH')
    def ev(t,i):i['EV_grid_steps'].append([480,1.])
    test('EV_grid_energy_not_equal_SOC_delivery',ev,'EV_GRID_METER_MISMATCH')
    def battery(t,i):i['EV']['energy_balance_error_kWh']=1
    test('EV_state_reset_disguised_as_recovery',battery,'EV_BATTERY_LEDGER_MISMATCH')
    def fans(t,i):
        key=next(k for k in t['channels']if k.startswith('Zone Combined Outdoor Air Fan Electricity Energy|')and any(x[1]>0 for x in t['channels'][k]))
        next(x for x in t['channels'][key]if x[1]>0)[1]=0
    test('missing_background_fan_energy',fans,'BACKGROUND_VENTILATION_METER_MISMATCH')
    okay={'service_outcomes':{'all_known_program_services_completed':True,'future_unexecuted_batches':[],'failed_retrieval_batches':[]},'EV_trips':[],'water_delivery':[]}
    failed=copy.deepcopy(okay);failed['service_outcomes'].update(all_known_program_services_completed=False,future_unexecuted_batches=[{'need_id':'future_wash'}])
    result=electricity_interpretation({'assessment_B':{'constraint_flags':[]}},okay,failed,'within_declared_tolerances_to_horizon',-1,-54,12960)
    records.append({'test':'unserved_future_programs_never_become_equal_service_savings','caught':not result['equal_service_and_recovery_verified']and result['equal_service_net_reduction_kWh']is None and result['B_future_unexecuted_batches']==1})
    result=electricity_interpretation({'assessment_B':{'constraint_flags':[]}},okay,okay,'within_declared_tolerances_to_horizon',-5,0,12960)
    records.append({'test':'energy_deferred_past_primary_day_is_not_net_saving','caught':result['interpretation']=='consumption_shifted_across_primary_boundary;no_net_saving_in_observation'and result['equal_service_net_reduction_kWh']==0})
    pack=read(ROOT/row['path']);before=digest(pair);merged_plan(pack,pair,'B',-28*1440,10*1440)
    records.append({'test':'request_objects_remain_immutable_during_compilation','caught':digest(pair)==before})
    # An external actor actually loading a machine is physically present even
    # without a resident calendar; off-site EV handling contributes no room heat.
    fake={'world':{'parameter_pack':{'devices':[{'asset_id':'washer','room_id':'washroom'}]}},
          'days':{'2025-01-01':{'calendars':{},'shared':{'member_calendars':{}},'external_visits':[]}}}
    ops=[{'operator_id':'external_guardian','asset_id':'washer','kind':'load','start_min':1080,'end_min':1090}]
    people,_=day_people(fake,dt.date(2025,1,1),ops,['washroom'])
    records.append({'test':'declared_external_handler_contributes_once_at_actual_operation','caught':people['washroom'][108]==1 and sum(people['washroom'])==1})
    report={'schema':VERSION,'physics_sha256':physics_hash(),'passed':all(r['caught']for r in records),'records':records,'source_result_label':args.label,'source_pair_sha256':pair['source_pair_sha256'],'temporary_copies_only':True}
    save(ROOT/'REGRESSION_RESULTS.json',report);print(canonical(report))
    if not report['passed']:raise SystemExit(2)

if __name__=='__main__':main()
