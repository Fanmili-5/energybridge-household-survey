#!/usr/bin/env python3
"""Typed family-IDF-asset contract; presence never implies control or power."""
import hashlib
import json
import math
import re
from pathlib import Path

def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def digest(x):return hashlib.sha256(json.dumps(x,sort_keys=True,ensure_ascii=False,separators=(',',':'),allow_nan=False).encode()).hexdigest()
def rows(s):return [[x.strip() for x in p.split(',')] for p in re.sub(r'!.*','',s).split(';') if p.strip()]
def finite(v):return isinstance(v,(int,float)) and not isinstance(v,bool) and math.isfinite(v)

def check_bundle(bundle,base_case):
    errors=[];inp=json.loads((base_case/'INPUT.json').read_text());status=json.loads((base_case/'STATUS.json').read_text())
    binding=bundle['binding'];idf=Path(binding['base_idf_path'])
    for key,actual in [('family_sha256',digest(inp['family'])),('housing_sha256',digest(inp['housing'])),
        ('base_idf_sha256',sha(idf)),('base_input_sha256',sha(base_case/'INPUT.json'))]:
        if binding.get(key)!=actual:errors.append('binding_mismatch:'+key)
    if idf.resolve()!=Path(status['idf_path']).resolve() or sha(idf)!=status['idf_sha256']:
        errors.append('base_case_IDF_binding_mismatch')
    if status['status']!='idf_ready':errors.append('base_case_not_ready')
    if bundle.get('profile_file_sha256')!=status.get('generation_profile_file_sha256'):
        errors.append('profile_version_mismatch')
    if bundle.get('population_slot_id')!=status.get('generation_slot_id'):errors.append('slot_mismatch')
    profile_path=Path(status['generation_profile_file_path'])
    if sha(profile_path)!=bundle.get('profile_file_sha256'):errors.append('live_profile_bytes_changed')
    profile=next((x for x in json.loads(profile_path.read_text())['profiles'] if x['slot_id']==bundle['population_slot_id']),None)
    if profile is None or digest(profile['family'])!=binding['family_sha256'] or digest(profile['housing'])!=binding['housing_sha256']:
        errors.append('live_profile_family_housing_mismatch')
    rs=rows(idf.read_text());zones={r[1] for r in rs if r[0].lower()=='zone'}
    inventory=bundle['assets'];ids=[a['asset_id'] for a in inventory];hardware=[a['hardware_id'] for a in inventory]
    if len(ids)!=len(set(ids)):errors.append('duplicate_asset_id')
    if len(hardware)!=len(set(hardware)):errors.append('duplicate_physical_hardware_counted_twice')
    for a in inventory:
        prefix=a['asset_id']+':'
        if not re.fullmatch(r'[a-zA-Z][a-zA-Z0-9_]{0,80}',a['asset_id']):errors.append(prefix+'unsafe_IDF_name')
        if a['unit_count']!=1:errors.append(prefix+'instance_requires_unit_count1')
        if a.get('assignment_status') not in ['explicit_engineering_fixture','modeled_role_design']:
            errors.append(prefix+'asset_assignment_evidence_missing')
        if not a.get('evidence_id'):errors.append(prefix+'asset_evidence_id_missing')
        if a['class']=='washer_dryer_combo' and set(a['services'])!={'wash','dry'}:
            errors.append(prefix+'combo_must_be_one_hardware_two_services')
        if a['zone_name'] not in zones:errors.append(prefix+'zone_not_in_exact_IDF')
        if a['zone_assignment_status'] not in ['engineering_gain_zone','validated_functional_placement']:
            errors.append(prefix+'zone_assignment_scope_missing')
        if a['meter_scope']!='declared_household_experiment_meter':errors.append(prefix+'meter_boundary_unresolved')
        for state in ['installed','operable','control_available']:
            if a.get(state) is not True:errors.append(prefix+state+'_unresolved')
        if a['class'].startswith(('cooling','water_heater')):
            errors.append(prefix+'service_needs_HVAC_or_water_model_not_generic_ElectricEquipment')
        elif a['class'] not in ['washer','dryer','washer_dryer_combo','refrigerator','dishwasher','explicit_electric_trace']:
            errors.append(prefix+'asset_class_not_admitted_to_electric_trace')
        phases=a['operation_phases'];previous=0
        for p in sorted(phases,key=lambda p:p['start_minute']):
            start,end=p['start_minute'],p['end_minute']
            if type(start) is not int or type(end) is not int or not 0<=start<end<=1440:
                errors.append(prefix+'invalid_operation_interval');continue
            if start<previous:errors.append(prefix+'same_hardware_simultaneous_services')
            previous=end
            if p['service'] not in a['services']:errors.append(prefix+'phase_service_not_owned_by_asset')
            if p['power_quantity']!='electrical_input_W':errors.append(prefix+'capacity_cannot_be_electrical_input')
            if not finite(p['input_power_W']) or p['input_power_W']<0:errors.append(prefix+'invalid_electrical_input_power')
            if p['power_evidence'] not in ['explicit_test_design','verified_model_input_profile']:
                errors.append(prefix+'electrical_input_provenance_missing')
            f=p['heat_fractions']
            if set(f)!={'latent','radiant','lost'} or any(not finite(x) or not 0<=x<=1 for x in f.values()) or sum(f.values())>1+1e-12:
                errors.append(prefix+'heat_fraction_energy_balance')
    actor_issues=[]
    if status['functional_layout_status']!='validated':actor_issues.append('functional_layout_not_validated')
    for a in inventory:
        if a.get('role_operator_member_id') not in inp['family']['resident_member_ids']:
            actor_issues.append(a['asset_id']+':operator_not_bound_to_family')
        if a.get('role_permission_to_shift') is None:actor_issues.append(a['asset_id']+':role_control_permission_unknown')
        if a['zone_assignment_status']!='validated_functional_placement':actor_issues.append(a['asset_id']+':functional_placement_not_validated')
        if a['assignment_status']=='explicit_engineering_fixture':actor_issues.append(a['asset_id']+':test_fixture_not_actor_role')
    if bundle.get('collection_release') or bundle.get('training_release'):
        errors.append('engineering_component_cannot_open_collection_or_training_release')
    actor_issues.append('component_checker_does_not_verify_full_task_state_or_device_service')
    return {'component_binding_pass':not errors,'errors':errors,'actor_role_ready':False,
        'actor_issues':actor_issues,'full_device_service_validated':False,
        'scope':'family/housing/version/zone/instance/electric internal-gain binding only; no household ownership/behavior or service calibration'}

def compile_gains(bundle,base_case):
    report=check_bundle(bundle,base_case)
    if not report['component_binding_pass']:return None,report
    original=Path(bundle['binding']['base_idf_path']).read_text();rs=rows(original)
    if any(r[0].lower() in ['electricequipment','gasequipment','otherequipment','hotwaterequipment'] for r in rs):
        report['component_binding_pass']=False;report['errors'].append('existing_equipment_requires_explicit_reconciliation')
        return None,report
    additions=[['ScheduleTypeLimits','EB_InputWatts','0','','Continuous']]
    records=[]
    for a in bundle['assets']:
        cuts={0,1440}
        for p in a['operation_phases']:cuts.update([p['start_minute'],p['end_minute']])
        intervals=[]
        ordered=sorted(cuts)
        for start,end in zip(ordered,ordered[1:]):
            p=next((p for p in a['operation_phases'] if p['start_minute']<=start and end<=p['end_minute']),None)
            intervals.append((start,end,p))
        # Different thermal fractions use exclusive phase objects sharing one
        # physical asset. They are channels, not additional appliances.
        for k,p in enumerate(a['operation_phases']):
            obj=a['asset_id']+'_phase'+str(k);schedule=obj+'_InputW'
            fields=['Schedule:Compact',schedule,'EB_InputWatts','Through: 12/31','For: AllDays','Interpolate: Average']
            for start,end,active in intervals:
                fields.extend([f'Until: {end//60:02d}:{end%60:02d}',str(p['input_power_W'] if active is p else 0)])
            additions.append(fields);f=p['heat_fractions']
            # A 1 W scale factor and a W-valued schedule are legal in E+;
            # preserve real input Watt quantities rather than mixing kW.
            additions.append(['ElectricEquipment',obj,a['zone_name'],schedule,'EquipmentLevel','1','','',
                str(f['latent']),str(f['radiant']),str(f['lost']),'EB_'+a['asset_id']])
            records.append({'hardware_id':a['hardware_id'],'asset_id':a['asset_id'],'service':p['service'],
                'idf_equipment_name':obj,'schedule':schedule,'expected_kWh':p['input_power_W']*(p['end_minute']-p['start_minute'])/60000,
                'count_as_extra_physical_asset':False,'heat_fractions':f,'schedule_time_policy':'energy_average_at_zone_timestep'})
    additions.extend([['Output:SQLite','SimpleAndTabular'],
        ['Output:Variable','*','Electric Equipment Electricity Energy','Timestep'],
        ['Output:Meter','Electricity:Facility','Timestep']])
    rs=[r for r in rs if r[0].lower()!='output:sqlite']
    text='\n'.join(',\n  '.join(r)+';' for r in rs+additions)+'\n'
    report.update(physical_asset_count=len(bundle['assets']),IDF_phase_channel_count=len(records),
        expected_phase_kWh=records,expected_total_kWh=sum(x['expected_kWh'] for x in records),
        upstream_family_housing_modified=False,HVAC_or_water_service_added=False)
    return text,report
