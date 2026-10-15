"""Explicit shared thermostat per thermal zone, with individually available units.

The native compiler uses one zone load/setpoint. Never claim that an otherwise
unused second unit schedule represents independent room temperature control.
"""
from common import *

def groups(w):
    result={}
    for d in w['parameter_pack']['devices']:
        if 'ac' in d['types']:result.setdefault(d['room_id'],[]).append(d['asset_id'])
    return result

def value_at(plan,aid,t):
    return next((c['value_C']for c in plan['controls']if c['kind']=='ac_setpoint'and c['asset_id']==aid and c['start_min']<=t<c['end_min']),None)

def validate_plan(w,plan):
    for room,aids in groups(w).items():
        cs=[c for c in plan['controls']if c['kind']=='ac_setpoint'and c['asset_id']in aids]
        edges=sorted({c[k]for c in cs for k in ('start_min','end_min')})
        for t in edges[:-1]:
            active={aid:value_at(plan,aid,t)for aid in aids};active={aid:v for aid,v in active.items()if v is not None}
            if active and (aids[0]not in active or len(set(active.values()))!=1):
                raise ValueError('UNIMPLEMENTABLE_INDEPENDENT_AC_SETPOINT:'+room+':'+str(t))
    return True

def change_room(q,aid,start,end,increase=None,value=None):
    ds=q['world']['devices'];target=next(d for d in ds if d['asset_id']==aid)
    aids=[d['asset_id']for d in ds if 'ac'in d['types']and d['room_id']==target['room_id']]
    out=[]
    for c in q['B']['controls']:
        a,b=max(start,c['start_min']),min(end,c['end_min'])
        if c['kind']!='ac_setpoint'or c['asset_id']not in aids or a>=b:out.append(c);continue
        if c['start_min']<a:out.append({**c,'end_min':a})
        out.append({**c,'start_min':a,'end_min':b,'value_C':value if value is not None else c['value_C']+increase})
        if b<c['end_min']:out.append({**c,'start_min':b})
    q['B']['controls']=out
    q['AC_control_contract']={'kind':'given_shared_zone_thermostat','room_id':target['room_id'],
        'controller_asset_id':aids[0],'affected_asset_ids':aids,'not_independent_unit_thermostats':True,
        'source':'explicit EnergyPlus thermal-zone control representation;not observed home wiring'}
    return aids

def repair_legacy(w,p):
    """Project a legacy single-unit temperature request onto its actual zone."""
    import copy
    from contrast_core import control_segments
    q=copy.deepcopy(p);q['B']['controls']=copy.deepcopy(p['A']['controls'])
    # Replay differences from the original request. Shared units get the same
    # requested zone value; availability changes keep their original semantics.
    for x in control_segments(p):
        if x['kind']=='ac_setpoint'and x['A']is not None and x['B']is not None:
            change_room(q,x['asset_id'],x['start_min'],x['end_min'],value=x['B'])
    for x in control_segments(p):
        if x['kind']=='ac_setpoint'and x['A']is not None and x['B']is not None:continue
        # Most source requests have no availability change in the same asset;
        # retain the complete source controls for all non-temperature assets.
        aid=x['asset_id'];q['B']['controls']=[c for c in q['B']['controls']if c['asset_id']!=aid]+[copy.deepcopy(c)for c in p['B']['controls']if c['asset_id']==aid]
    validate_plan(w,q['A']);validate_plan(w,q['B'])
    return q

def idf_bindings(w,p,compiled):
    """Verify the emitted thermostat really consumes each declared zone change."""
    from contrast_core import control_segments
    validate_plan(w,p['A']);validate_plan(w,p['B'])
    report=[]
    for side in ('A','B'):
        b=compiled[side];rows=parse(OUT/b['IDF_path']);names=b['signal_names']
        for room,aids in groups(w).items():
            thermostat=next(r for r in rows if r[0]=='ThermostatSetpoint:DualSetpoint'and r[1]=='v16_heat_'+room+'_sp')
            assert thermostat[3]==names[aids[0]]
            report.append({'arm':side,'room_id':room,'controller_asset_id':aids[0],
                'shared_assets':aids,'actual_thermostat_schedule':thermostat[3],
                'IDF_sha256':sha(OUT/b['IDF_path'])})
    for x in control_segments(p,'ac_setpoint'):
        if x['A']is None or x['B']is None:continue
        room=next(d['room_id']for d in w['parameter_pack']['devices']if d['asset_id']==x['asset_id'])
        controller=groups(w)[room][0]
        assert value_at(p['A'],controller,x['start_min'])==x['A']
        assert value_at(p['B'],controller,x['start_min'])==x['B']
    return report
