"""Explicit automatic phases on one physical asset; no inferred capability.

The legacy life module still supplies calendars, mobility and thermal inputs.
Its incomplete wash-only program is not exposed as a full comparator.
"""
import copy
from pathlib import Path
from .. import life
from ..common import read,sha,digest
from .input_boundaries import require_no_downstream_fields


def bind_reference_contract(world, contract):
    """Bind a declared project device recipe, never learn capability from A.

    Callers explicitly select the old functional reference contract. This
    binding reads registered assets and a pinned static rule, not task times,
    daily requirements, habits, outcomes or answers.
    """
    if set(world)&{'A','B'}:raise ValueError('PLAN_INFORMATION_IN_CAPABILITY_SOURCE')
    require_no_downstream_fields(world,'AUTOMATIC_CAPABILITY_SOURCE')
    source=read(Path(__file__).with_name('AUTOMATIC_REFERENCE_SOURCE.json'))
    if contract!=source['contract']:raise ValueError('UNKNOWN_AUTOMATIC_REFERENCE_CONTRACT')
    evidence=Path(__file__).parent/source['bundled_source']
    if sha(evidence)!=source['source_sha256']:raise ValueError('AUTOMATIC_REFERENCE_SOURCE_CHANGED')
    result=copy.deepcopy(world);rows=[]
    for d in result['devices']:
        if not {'washer','dryer'}<=set(d.get('types',[])):continue
        if d.get('kind')!='washer':raise ValueError('AUTOMATIC_REFERENCE_PRIMARY_KIND_MISMATCH')
        if not all(isinstance(d['parameters'].get(k),dict) for k in ('washer','dryer')):
            raise ValueError('AUTOMATIC_REFERENCE_PHASE_PARAMETERS_MISSING')
        declared=d.get('automatic_programs')
        if declared is not None and declared!=['washer','dryer']:
            raise ValueError('EXPLICIT_AUTOMATIC_CAPABILITY_CONFLICT')
        original=copy.deepcopy(d)
        d['automatic_programs']=['washer','dryer']
        if declared is None:
            d['automatic_programs_source']=dict(contract=contract,source_sha256=source['source_sha256'],
                asset_source_sha256=digest(original),origin=source['origin'],inferred_from_A=False,
                hardware_or_permission_expanded=False)
        rows.append(dict(asset_id=d['asset_id'],previously_explicit=declared is not None,
                         source_sha256=source['source_sha256'],input_asset_sha256=digest(original)))
    return result,dict(contract=contract,source_sha256=source['source_sha256'],bindings=rows,
                       original_world_sha256=digest(world),bound_world_sha256=digest(result),
                       uses_A_or_daily_requirements=False,new_random_draws=0,execution_consent=False)


def hardware(device, kind):
    params=device['parameters']
    result=copy.deepcopy(params.get(kind,params))
    if 'nameplate_W' in params:result.setdefault('nameplate_W',params['nameplate_W'])
    return result


def legacy_view(spec, world):
    policies={p['service_id']:p for p in spec['program_policies']}
    assets={d['asset_id']:d for d in world['devices']};groups={}
    for child in spec['program_policies']:
        if child['trigger']!='after_service':continue
        parent=policies.get(child['upstream_service_id'])
        if not parent or child['asset_id']!=parent['asset_id']:continue
        d=assets.get(parent['asset_id'])
        life.require(d is not None and parent['kind']=='washer' and child['kind']=='dryer',
                     'INVALID_SHARED_AUTOMATIC_SEQUENCE')
        life.require(d.get('automatic_programs')==['washer','dryer'] and
                     {'washer','dryer'}<=set(d.get('types',[])),
                     'AUTOMATIC_SEQUENCE_CAPABILITY_NOT_EXPLICIT')
        life.require(all(isinstance(d['parameters'].get(k),dict) for k in ('washer','dryer')),
                     'AUTOMATIC_PHASE_PARAMETERS_NOT_EXPLICIT')
        life.require(parent['service_id'] not in groups,'DUPLICATE_AUTOMATIC_DRY_PHASE')
        fields={'service_id','asset_id','kind','trigger','duration_min','preferred_start_min',
                'maximum_preload_wait_min','maximum_retrieval_wait_min','deadline_after_release_min',
                'machine_windows_min','timer_allowed','priority','upstream_service_id'}
        life.require(set(child)-{'energy_model'}==fields,'UNKNOWN_AUTOMATIC_PHASE_POLICY_FIELD')
        life.require(child.get('energy_model','load_curve') in ('load_curve','legacy_constant_power'),
                     'UNKNOWN_AUTOMATIC_PHASE_ENERGY_MODEL')
        for key in ('duration_min','maximum_preload_wait_min','maximum_retrieval_wait_min','deadline_after_release_min'):
            life.minute(child[key],key)
        life.require(child['duration_min']>0 and child['deadline_after_release_min']>0 and
                     type(child['timer_allowed']) is bool,'INVALID_AUTOMATIC_PHASE_POLICY')
        life.require(type(child['priority']) is int and child['priority']>=0,'INVALID_AUTOMATIC_PHASE_PRIORITY')
        for name in ('weekday','weekend'):life.minute(child['preferred_start_min'][name],'preferred_start',1440)
        life.require(bool(child['machine_windows_min']),'EMPTY_AUTOMATIC_MACHINE_WINDOWS')
        for a,z in child['machine_windows_min']:
            life.require(life.minute(a,'machine_window',1440)<life.minute(z,'machine_window',1440),
                         'EMPTY_AUTOMATIC_MACHINE_WINDOW')
        for kind in ('washer','dryer'):
            hp=hardware(d,kind);life.positive(hp.get('power_kw'),'automatic_'+kind+'_power_kw')
            if 'nameplate_W' in hp:
                life.positive(hp['nameplate_W'],'automatic_nameplate_W')
                life.require(hp['power_kw']*1000<=hp['nameplate_W']+1e-9,'AUTOMATIC_POWER_EXCEEDS_NAMEPLATE')
        groups[parent['service_id']]=child
    if not groups:return spec,world,groups
    local_spec=copy.deepcopy(spec);local_world=copy.deepcopy(world)
    removed={p['service_id'] for p in groups.values()}
    local_spec['program_policies']=[p for p in local_spec['program_policies'] if p['service_id'] not in removed]
    for d in local_world['devices']:
        if any(policies[sid]['asset_id']==d['asset_id'] for sid in groups):
            d['parameters']=hardware(d,'washer')
    return local_spec,local_world,groups
