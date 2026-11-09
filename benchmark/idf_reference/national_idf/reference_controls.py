"""Freeze noncontrollable services independently of physical device presence."""
import copy

from .common import ROOT, read, require
from .reference_scenarios import FUNCTIONS, inventory, validate_shared_asset_intervals
from .source_adapter import source_file


def validate(case, timeline, contract_ref, *, root=ROOT):
    contract=read(source_file(contract_ref,root))
    require(contract['schema']=='national_idf.reference_control_contract.v1','REFERENCE_CONTROL_CONTRACT_SCHEMA')
    inv=inventory(contract['equipment'])
    require(set(inv['installed'])==set(FUNCTIONS.values()),'REFERENCE_CONTROL_CONTRACT_INVENTORY_NOT_IMPLEMENTED')
    require(case['environment']['physics_configuration_id']==contract['physics_configuration_id'],'REFERENCE_CONTROL_CONTRACT_PHYSICS_ID')
    fixed=read(source_file(contract['fixed_background_case'],root))
    reverse={v:k for k,v in FUNCTIONS.items()}
    for device in ('washer','dryer','dishwasher'):
        if device not in inv['controlled']:
            require(case['life']['services_daily'][device]==fixed['life']['services_daily'][device],
                    'REFERENCE_UNCONTROLLED_BACKGROUND_CHANGED',device)
            require(case['controls']['program_starts_daily'][device]==fixed['controls']['program_starts_daily'][device],
                    'REFERENCE_UNCONTROLLED_BACKGROUND_CHANGED',device)
            for day in set(case['controls']['program_start_overrides'])|set(fixed['controls']['program_start_overrides']):
                require(case['controls']['program_start_overrides'].get(day,{}).get(device,[])==
                        fixed['controls']['program_start_overrides'].get(day,{}).get(device,[]),
                        'REFERENCE_UNCONTROLLED_BACKGROUND_CHANGED',device)
    tasks=[]
    for i in range(timeline.steps):
        for task in timeline.frame(i)['program_starts']:
            device=task['device'];start=i*timeline.step_min
            tasks.append({'id':device+':'+str(start),'function':reverse[device],
                          'start_elapsed_min':start,'end_elapsed_min':start+timeline.domain['programs'][device]['duration_min']})
    for task in tasks:
        if task['function']=='DR' and contract.get('wash_before_dry'):
            asset=contract['equipment']['DR']['asset_id']
            predecessors=[t for t in tasks if t['function']=='WM' and t['end_elapsed_min']<=task['start_elapsed_min']
                          and contract['equipment']['WM']['asset_id']==asset]
            require(predecessors,'REFERENCE_FIXED_WASH_PREDECESSOR_MISSING')
            task['after_tasks']=[max(predecessors,key=lambda x:x['end_elapsed_min'])['id']]
    result=validate_shared_asset_intervals(tasks,contract['equipment'])
    return {'contract':contract_ref,**result,'installed_devices':inv['installed'],'controlled_devices':inv['controlled'],
            'background_services_immutable':True,'combined_machine_product_physics_claimed':False,
            'service_unit':'published_source_resource_window','cleaning_or_dryness_verified':False}
