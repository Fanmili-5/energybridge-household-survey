"""Explicit task equipment, separated from immutable source ownership."""
from copy import deepcopy
from itertools import combinations
from collections import Counter
import hashlib
import activity_model as activity
FUNCTIONS=('AC','WM','DR','DW','WH','EV')
KEY={'AC':'space_ac_available','WM':'washer_available','DR':'dryer_available','DW':'dishwasher_available','WH':'water_heater_available','EV':'home_vehicle_charging'}
NAMES={'AC':'空调','WM':'洗衣','DR':'烘干','DW':'洗碗','WH':'储水式电热水','EV':'电动车充电'}
MODES={'AC':'bounded_temperature_setpoint','WM':'non_interruptible_whole_cycle','DR':'non_interruptible_whole_cycle','DW':'non_interruptible_whole_cycle','WH':'electric_storage_temperature_and_preheat','EV':'single_contiguous_charge_session'}
def configure(c,enabled):
    h=c['household'];p=c['household_provenance'];before=deepcopy(h['equipment']);h['equipment_before_control_configuration']=before;ledger=[];inventory={}
    for name,q in h['equipment'].items():q['control_enabled']=False
    for f in FUNCTIONS:
        name=KEY[f];q=h['equipment'][name];old=before[name];selected=f in enabled;raw=c['devices'][name]
        if not selected:
            inventory[f]={'device_key':name,'enabled':False,'coverage_counted':False,'reason':'not enrolled in this reference task configuration; source ownership is not changed'}
            continue
        changes=[]
        if not q['present']:
            q.update(present=True,energy_carrier='electricity',appliance_type='reference_'+{'AC':'room_air_conditioner','WM':'washer','DR':'electric_dryer','DW':'dishwasher','WH':'electric_storage_water_heater','EV':'home_vehicle_charger'}[f])
            changes.append('install_reference_service')
            activity.tag(p,'equipment.'+name+'.present','experimental reference installation; raw source ownership remains in devices',status='benchmark_installed')
            activity.tag(p,'equipment.'+name+'.energy_carrier','electric reference equipment, not observed target-household fuel',status='benchmark_assigned')
            activity.tag(p,'equipment.'+name+'.appliance_type','explicit electrical reference prototype',status='benchmark_assigned')
        if f=='DR' and q.get('energy_carrier')!='electricity':
            q.update(energy_carrier='electricity',appliance_type='reference_electric_dryer');changes.append('replace_reference_gas_drying_with_electric')
            activity.tag(p,'equipment.'+name+'.energy_carrier','electric drying experiment; original gas dryer preserved in source layer',status='benchmark_intervention')
            activity.tag(p,'equipment.'+name+'.appliance_type','electric dryer reference replaces incompatible drying service',status='benchmark_intervention')
        if f=='WH':
            n=len(h['members']);volume=100 if n<=2 else 150 if n==3 else 200 if n<=5 else 300
            q.update(energy_carrier='electricity',appliance_type='reference_electric_storage_water_heater',thermal_storage_model='explicit_reference_tank',storage_capacity_litres=volume,reference_heater_kw=3.0,storage_shift_eligible=True)
            changes.append('bind_explicit_electric_storage_reference')
            for field in ('energy_carrier','appliance_type','thermal_storage_model','storage_capacity_litres','reference_heater_kw','storage_shift_eligible'):
                activity.tag(p,'equipment.'+name+'.'+field,'declared electric storage reference; not measured target-household tank/fuel; physical binding pending',status='benchmark_intervention')
        q['control_enabled']=True;q['control_function_id']=f;q['control_mode']=MODES[f]
        asset=(q.get('source_asset_key') if not changes else None) or f"{c['case_id']}-{f}-reference"
        q['reference_asset_id']=asset
        activity.tag(p,'equipment.'+name+'.control_enabled','controlled reference task enrollment, not source IoT/control-access observation')
        inventory[f]={'device_key':name,'enabled':True,'coverage_counted':True,'name_zh':NAMES[f],'energy_carrier':q['energy_carrier'],'control_mode':MODES[f],'reference_asset_id':asset,'source_presence':deepcopy(raw),'source_reference_before':deepcopy(old),'installation_or_retyping':changes,'control_access_status':'benchmark_assigned','physical_execution_verified':False}
        if changes:ledger.append({'function':f,'source_fact':deepcopy(raw),'before':old,'after':deepcopy(q),'actions':changes,'status':'experimental_reference_configuration','population_ownership_inference':False})
    h['control_inventory']=inventory;h['controlled_function_ids']=list(enabled);h['controlled_function_count']=len(enabled);h['control_configuration_interventions']=ledger
    h['control_configuration_scope']={'counted_universe':list(FUNCTIONS),'background_devices_counted':False,'source_ownership_equals_control_access':False,'physical_model_execution_complete':False,'layout_and_installation_are_reference_conditions':True}
    h['reference_installation_conditions']={'water_and_drain_service_for_enabled_wet_appliances':'assumed experimental availability, not inferred source infrastructure','electrical_connection':'reference connection needed; building circuit admission belongs to physical stage','EV_parking_and_charging_access':'explicit reference accessible parking connection' if 'EV' in enabled else 'not added for control coverage'}
    if h['equipment']['space_ac_available']['present'] and not h['comfort']:
        role=c['benchmark_role'];h['comfort']={'preferred_cooling_c':[24,25] if role=='B' else [24,26],'allowed_short_adjustment_c':{'A':1,'B':0.5,'C':1,'D':2,'E':0.5,'F':1}[role],'comfort_ceiling_c':26}
        activity.tag(p,'comfort','original role-compatible reference comfort, not observed temperature preference')
    if h['equipment']['home_vehicle_charging']['present']:
        adults=[m for m in h['members'] if m['age_band'][0]>=18]
        if c['benchmark_role']=='F':driver=h['decision_maker_id']
        else:
            old_events=h['calendar']['weekly_events']
            driver=max(adults,key=lambda m:(sum(e['end']-e['start'] for e in old_events if e['member_id']==m['id'] and e['kind']=='work' and e['location']=='away'),-m['age_band'][0]))['id']
        if not h['ev']:
            h['ev']={'reference_powertrain':'battery_electric','charger_type':'Level_2','reference_charger_kw':3.6,'reference_battery_kwh':60,'arrival_soc':0.5,'departure_soc_target':0.8,'charge_efficiency':0.9,'commute_use':'conditional_personal_mobility_experiment','charging_contiguity':'one_continuous_session_is_required_for_base_need'}
            activity.tag(p,'ev.charger_type','reference Level2 access, not observed ownership or charger type')
        h['ev']['vehicle_user_member_id']=driver
        h['ev']['controlled']='EV' in enabled
        h['ev']['driver_access_basis']='reference adult vehicle user; source driving license and actual commuting vehicle not inferred'
        activity.tag(p,'ev','single-event reference vehicle and charging service; source home-charging observation kept separately')
    shared=[]
    if 'WM' in enabled and 'DR' in enabled:
        w=inventory['WM']['reference_asset_id'];d=inventory['DR']['reference_asset_id']
        if w==d:shared.append({'asset_id':w,'functions':['WM','DR'],'max_parallel_functions':1,'precedence':'wash_before_dry'})
    h['shared_control_asset_constraints']=shared
    activity.tag(p,'control_inventory','six-function constrained task design; background appliances excluded, raw survey equipment unchanged')
    return c

def blueprint(c,pair_counts):
    fs=c['household']['controlled_function_ids'];role=c['benchmark_role'];slots=[{'slot':i+1,'focus_functions':[f],'kind':'single_function'} for i,f in enumerate(fs)];exposure=Counter(fs);used=set()
    for i in range(len(fs),10):
        candidates=list(combinations(fs,2))
        def score(pair):
            deficit=sum(max(0,2-exposure[f]) for f in pair)
            tie=int(hashlib.sha256(str((c['case_id'],i,pair)).encode()).hexdigest()[:8],16)/2**32
            return (deficit,pair not in used,-pair_counts[(role,pair)],-sum(exposure[f] for f in pair),tie)
        pair=max(candidates,key=score);used.add(pair);pair_counts[(role,pair)]+=1;exposure.update(pair)
        slots.append({'slot':i+1,'focus_functions':list(pair),'kind':'joint_function','resource_rule':'wash_before_dry_if_both; shared assets cannot overlap'})
    assert len(slots)==10 and all(exposure[f]>=2 for f in fs)
    c['household']['question_coverage_blueprint']={'slots':slots,'minimum_reference_exposure_per_enabled_function':2,'actual_questions_generated':False,'actual_device_demand_and_physical_consequences_verified':False,'realization_gate':'only instantiate a slot when actual service need exists; otherwise select another supported event/date or record the unmet coverage target; do not invent activity to satisfy counts'}
    return c
