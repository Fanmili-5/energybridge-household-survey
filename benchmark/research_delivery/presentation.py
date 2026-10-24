"""Semantic display projection of bound plans; private row keys are not actions."""
import copy
from benchmark.ab_generation.common import canonical
from benchmark.project.questionnaire import display_plans,changes


def plans(material):
    result=display_plans(material)
    for side in ('A','B'):
        groups={}
        for original in result[side]['controls']:
            r={k:v for k,v in original.items() if k not in ('_unified_id','_ab_control_id')}
            key=canonical({k:v for k,v in r.items() if k not in ('start_min','end_min')})
            groups.setdefault(key,[]).append(r)
        merged=[]
        for rows in groups.values():
            rows.sort(key=lambda r:r['start_min']);current=None
            for r in rows:
                if current is not None and current['end_min']==r['start_min']:current['end_min']=r['end_min']
                else:current=copy.deepcopy(r);merged.append(current)
        result[side]['controls']=sorted(merged,key=lambda r:(r['start_min'],r['asset_id'],r['kind']))
    return result


def state_at(rows,minute):
    return sorted((canonical({k:v for k,v in r.items() if k not in ('start_min','end_min','_unified_id','_ab_control_id')})
                   for r in rows if r['start_min']<=minute<r['end_min']))


def equivalent_display(material,projected):
    original=display_plans(material)
    for side in ('A','B'):
        points=sorted({r[k] for rs in (original[side]['controls'],projected[side]['controls']) for r in rs for k in ('start_min','end_min')})
        for a,b in zip(points,points[1:]):
            if a<b and state_at(original[side]['controls'],a)!=state_at(projected[side]['controls'],a):return False
        if original[side]['tasks']!=projected[side]['tasks'] or original[side]['operations']!=projected[side]['operations']:return False
    return True
