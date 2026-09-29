"""Compatibility adapter from historical v1 cases to the stable v2 consumer case."""
from copy import deepcopy

from joint_contract import bind, digest, validate_case, UNIFIED_SCHEMA


def physical_from_v1(case):
    physical=case.get('physical_readback')
    if physical:
        channels=[]
        for ch in physical['summary_48h']['channels']:
            if ch['kind'] not in {'device_electricity','ideal_cooling_thermal'}:continue
            channels.append({'kind':ch['kind'],'label':ch['label'],'scope':'48h','unit':ch['unit'],
                'A':{'value':ch['A'],'status':'computed'},'B':{'value':ch['B'],'status':'computed'},
                'evidence_sha256':physical['provenance']['paired_readback_sha256']})
        return {'schema':'eb.joint_b.physical.v2','status':'partial','channels':channels,
            'hold_reason':None,'whole_house_net_import':None,'VPP_target_met':None}
    a=case.get('A_only_readback')
    if a:
        held=a['status']=='held_thermal_psychrometric_diagnosis'
        names={d['asset_id']:d['device'] for d in case['profile']['profile']['devices']}
        channels=[{'kind':'device_electricity','label':names[x['asset_id']],'scope':'annual_A','unit':'kWh',
            'A':{'value':x['A_year_kWh'],'status':'computed'},'B':{'value':None,'status':'not_computed'},
            'evidence_sha256':a['source']['A_sql_sha256']} for x in a['selected_channels']]
        return {'schema':'eb.joint_b.physical.v2','status':'partial','channels':channels,
            'hold_reason':'A 湿球未收敛；气候相关热量与室温暂缓展示。' if held else None,
            'whole_house_net_import':None,'VPP_target_met':None}
    return {'schema':'eb.joint_b.physical.v2','status':'not_computed','channels':[],
            'hold_reason':None,'whole_house_net_import':None,'VPP_target_met':None}


def normalize_v1(source_case,manifest_sha):
    validate_case(source_case)
    case=deepcopy(source_case)
    case['schema']=UNIFIED_SCHEMA
    case['audit']={'source_binding':{'manifest_sha256':manifest_sha,'original_case_sha256':digest(source_case),
                                    'source_bindings':deepcopy(source_case['bindings'])},
                   'collection_linkage':deepcopy(source_case.get('collection_linkage'))}
    if source_case.get('physical_readback'):
        case['audit']['legacy_physical_readback']=deepcopy(source_case['physical_readback'])
    if source_case.get('A_only_readback'):
        case['audit']['legacy_A_only_readback']=deepcopy(source_case['A_only_readback'])
    case['physical']=physical_from_v1(source_case)
    case.pop('physical_readback',None);case.pop('A_only_readback',None)
    return bind(case)
