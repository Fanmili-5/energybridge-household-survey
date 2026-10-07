"""Read-only semantic checks, separate from the world/plan generators."""
import copy, collections
from common import digest
from legacy_semantics import validate as legacy_validate
def clip_prefix(plan,decision):
    return sorted([{**c,'end_min':min(c['end_min'],decision)} for c in plan['controls'] if c['start_min']<decision],key=lambda x:repr(sorted(x.items())))
def validate(p):
    errors=legacy_validate(p);decision=p['decision_abs_min'];ns={n['need_id']:n for n in p['needs_A']};assets={a['asset_id']:a for a in p['world']['devices']}
    if digest(p['A'])!=p['A_frozen_before_B_sha256']:errors.append('A_REWRITTEN_AFTER_B')
    if clip_prefix(p['A'],decision)!=clip_prefix(p['B'],decision):errors.append('CONTROL_PREFIX_CHANGED')
    for side,plan in [('A',p['A']),('B',p['B'])]:
        tasks={t['need_id']:t for t in plan['tasks']};ops=plan['operations']
        if plan['parameter_pack_sha256']!=p['parameter_pack_sha256']:errors.append(side+':PARAMETER_PACK_CHANGED')
        for op in ops:
            if any(type(op[k])!=int or op[k]%10 for k in ['start_min','end_min']):errors.append(side+':HANDLING_CLOCK')
            if op['end_min']-op['start_min']!=op['duration_min'] or op['end_min']<=op['start_min']:errors.append(side+':HANDLING_DURATION')
        for n in ns.values():
            k=n['kind'];nid=n['need_id']
            if k in ['washer','dishwasher']:
                if nid not in tasks:continue  # Coverage failure already reported by the base checker.
                loads=[o for o in ops if o['need_id']==nid and o['kind']=='load']
                unloads=[o for o in ops if o['need_id']==nid and o['kind']=='unload']
                end=tasks[nid+':dry']['end_min'] if nid+':dry' in tasks else tasks[nid]['end_min']
                if len(loads)!=1 or loads[0]['start_min']<n['release_min']:errors.append(side+':LOAD_RELEASE')
                if len(unloads)!=1 or unloads[0]['start_min']<end or unloads[0]['end_min']>(n['release_min']//1440)*1440+1890:errors.append(side+':UNLOAD_SERVICE')
                if k=='washer' and n['quantity']>5:errors.append(side+':LAUNDRY_MASS_CAPACITY')
            if k=='dryer':
                if nid not in tasks or n['upstream_need_id'] not in tasks:continue
                upstream=tasks[n['upstream_need_id']]
                if tasks[nid]['start_min']-upstream['end_min']>120:errors.append(side+':WET_LAUNDRY_RESIDENCE')
                if ns[n['upstream_need_id']]['quantity']!=n['quantity']:errors.append(side+':LAUNDRY_MASS_CHANGED')
            if k=='ev':
                cs=[c for c in plan['controls'] if c['kind']=='ev_charge_window' and n['connection_start_min']<=c['start_min']<n['departure_min']]
                plugs=[o for o in ops if o['need_id']==nid and o['kind']=='EV_plug'];unplugs=[o for o in ops if o['need_id']==nid and o['kind']=='EV_unplug']
                if len(cs)!=1 or len(plugs)!=1 or len(unplugs)!=1:errors.append(side+':EV_CONNECTION_OPERATION')
                elif cs[0]['start_min']<plugs[0]['end_min'] or cs[0]['end_min']>unplugs[0]['start_min']:errors.append(side+':EV_PLUG_BOUNDARY')
            if k=='ac' and n['reference_upper_control_C']!=assets[n['asset_id']]['reference_upper_setpoint_C']:errors.append(side+':AC_NEED_PARAMETER_BOUNDARY')
        for i,a in enumerate(ops):
            for b in ops[i+1:]:
                if a['operator_id']==b['operator_id'] and max(a['start_min'],b['start_min'])<min(a['end_min'],b['end_min']):errors.append(side+':OPERATOR_DOUBLE_BOOKED')
        # Declared inlet bound includes fixed background reservation, excludes the
        # separate EV bay feed. This does not substitute for later EP meter checks.
        for m in range(0,p['horizon_min'],10):
            active={t['asset_id'] for t in tasks.values() if t['start_min']<=m<t['end_min']}
            active.update(c['asset_id'] for c in plan['controls'] if c['start_min']<=m<c['end_min'])
            kw=p['world']['background_reserved_kw']+sum(assets[a]['max_electric_kw'] for a in active if assets[a]['circuit']!='EV_bay')
            if kw>p['world']['home_service_limit_kw']+1e-8:errors.append(side+':DECLARED_INLET_CAPACITY');break
    beforeA=sorted([o for o in p['A']['operations'] if o['start_min']<decision],key=lambda o:o['operation_id'])
    beforeB=sorted([o for o in p['B']['operations'] if o['start_min']<decision],key=lambda o:o['operation_id'])
    if beforeA!=beforeB:errors.append('HANDLING_PREFIX_CHANGED')
    for aid in assets:
        for side in ['A','B']:
            cs=[c for c in p[side]['controls'] if c['asset_id']==aid]
            for i,a in enumerate(cs):
                for b in cs[i+1:]:
                    if max(a['start_min'],b['start_min'])<min(a['end_min'],b['end_min']):errors.append(side+':CONTROL_RESOURCE_OVERLAP')
    return sorted(set(errors))
