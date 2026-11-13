"""Fixed/shared service permissions over existing EB physical inventories."""
import copy

from .common import ROOT,read,require,save
from .reference_scenarios import FUNCTIONS,inventory,validate_shared_asset_intervals
from .reference_workflow import ref
from .source_adapter import source_file


BACKGROUND_DEVICES = {'washer', 'dryer', 'dishwasher', 'water_heater'}


def fixed_control_fields(equipment):
    """Backend setpoint writes do not grant the user heater control."""
    heater = equipment.get('WH', {})
    return {'tank_target_C'} if heater.get('physically_present') is True and heater.get('control_enabled') is False else set()


def bind(contract_ref,case,identifier,folder,*,root=ROOT,recovery_extension=False,diagnostic_parent_id=None):
    contract=copy.deepcopy(read(source_file(contract_ref,root)))
    fixed=read(source_file(contract['fixed_background_case'],root))
    expected_parent=diagnostic_parent_id if recovery_extension else identifier
    require(contract.get('physics_configuration_id') in (None,expected_parent),'CONDITION_FIXED_SERVICE_CONFIGURATION_CONFLICT')
    require(fixed['environment'].get('physics_configuration_id') in (None,expected_parent),'CONDITION_FIXED_CASE_CONFIGURATION_CONFLICT')
    require(fixed['run']['start_date']==case['run']['start_date'],'CONDITION_FIXED_SERVICE_START_DATE')
    if recovery_extension:fixed['run']=copy.deepcopy(case['run'])
    require(fixed['run']==case['run'],'CONDITION_FIXED_SERVICE_WINDOW')
    fixed['environment']['physics_configuration_id']=identifier
    contract['physics_configuration_id']=identifier
    save(folder/'FIXED_CASE.json',fixed);contract['fixed_background_case']=ref(folder/'FIXED_CASE.json',root)
    save(folder/'CONTRACT.json',contract);return ref(folder/'CONTRACT.json',root)


def validate(case,timeline,equipment,contract_ref,*,root=ROOT):
    inv=inventory(equipment);require(not inv['unknown_presence'],'CONDITION_CONTROL_PRESENCE_UNKNOWN')
    uncontrolled=set(inv['installed'])-set(inv['controlled'])
    require(uncontrolled<=BACKGROUND_DEVICES,'CONDITION_UNREVIEWED_BACKGROUND_CHANNEL')
    contract=read(source_file(contract_ref,root))
    require(contract['schema']=='national_idf.reference_control_contract.v1','CONDITION_CONTROL_CONTRACT_SCHEMA')
    require(contract['physics_configuration_id']==case['environment']['physics_configuration_id'],'CONDITION_CONTROL_CONFIGURATION')
    expected=contract['equipment'];inventory(expected)
    for key in FUNCTIONS:
        require(all(expected[key][f]==equipment[key][f] for f in ('physically_present','control_enabled')),
                'CONDITION_CONTROL_EQUIPMENT_CONFLICT',key)
        if equipment[key]['physically_present'] and not equipment[key]['control_enabled']:
            require(expected[key].get('background_service_id')==equipment[key].get('background_service_id'),
                    'CONDITION_BACKGROUND_SERVICE_CONFLICT',key)
    present=[k for k,v in equipment.items() if v['physically_present']]
    for i,a in enumerate(present):
        for b in present[i+1:]:
            shared=equipment[a]['asset_id']==equipment[b]['asset_id']
            require(shared==(expected[a]['asset_id']==expected[b]['asset_id']),'CONDITION_SHARED_GRAPH_CONFLICT')
            require(not shared or {a,b}=={'WM','DR'},'CONDITION_SHARED_DEVICE_PHYSICS_NOT_REVIEWED')
    fixed=read(source_file(contract['fixed_background_case'],root))
    require(fixed['run']==case['run'],'CONDITION_FIXED_SERVICE_WINDOW')
    for device in uncontrolled:
        if device == 'water_heater':
            require(case['controls'].get('water_heater_windows_by_date')==fixed['controls'].get('water_heater_windows_by_date'),'CONDITION_UNCONTROLLED_HEATER_WINDOW_CHANGED')
            # Demand is an input, not permission to preheat the fixed asset.
            for field in ('mixed_water_daily', 'mixed_water_overrides'):
                require(case['life'].get(field, {}) == fixed['life'].get(field, {}),
                        'CONDITION_UNCONTROLLED_WATER_DEMAND_CHANGED', field)
            from .case_commands import CaseTimeline
            fixed_timeline = CaseTimeline(fixed, timeline.domain, root=root)
            require(all(timeline.frame(i)['control']['tank_target_C'] ==
                        fixed_timeline.frame(i)['control']['tank_target_C'] for i in range(timeline.steps)),
                    'CONDITION_UNCONTROLLED_HEATER_SETPOINT_CHANGED')
            continue
        require(case['life']['services_daily'][device]==fixed['life']['services_daily'][device]
            and case['controls']['program_starts_daily'][device]==fixed['controls']['program_starts_daily'][device],
            'CONDITION_UNCONTROLLED_SERVICE_CHANGED',device)
        for day in set(case['controls']['program_start_overrides'])|set(fixed['controls']['program_start_overrides']):
            require(case['controls']['program_start_overrides'].get(day,{}).get(device,[])==
                    fixed['controls']['program_start_overrides'].get(day,{}).get(device,[]),
                    'CONDITION_UNCONTROLLED_SERVICE_CHANGED',device)
    reverse={v:k for k,v in FUNCTIONS.items()};tasks=[]
    for i in range(timeline.steps):
        for task in timeline.frame(i)['program_starts']:
            require(task['device'] in inv['installed'],'CONDITION_ABSENT_DEVICE_PROGRAMME')
            start=i*timeline.step_min;tasks.append({'id':task['device']+':'+str(start),'function':reverse[task['device']],
                'start_elapsed_min':start,'end_elapsed_min':start+timeline.domain['programs'][task['device']]['duration_min']})
    shared_laundry=all(k in present for k in ('WM','DR')) and equipment['WM']['asset_id']==equipment['DR']['asset_id']
    if shared_laundry:
        require(contract.get('wash_before_dry') is True,'CONDITION_SHARED_WASH_DEPENDENCY_REQUIRED')
        for task in tasks:
            if task['function']!='DR':continue
            previous=[v for v in tasks if v['function']=='WM' and v['end_elapsed_min']<=task['start_elapsed_min']]
            require(previous,'CONDITION_SHARED_WASH_PREDECESSOR_MISSING')
            task['after_tasks']=[max(previous,key=lambda v:v['end_elapsed_min'])['id']]
    checks=validate_shared_asset_intervals(tasks,equipment)
    return {'contract':contract_ref,**checks,'installed_devices':inv['installed'],'controlled_devices':inv['controlled'],
        'fixed_background_devices':sorted(uncontrolled),'backend_actuation_is_not_user_permission':True,
        'fixed_control_fields':sorted(fixed_control_fields(equipment)),
        'combined_machine_product_physics_or_cleanliness_claimed':False}
