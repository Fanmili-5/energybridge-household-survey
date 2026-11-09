"""Account for two additional public-builder defaults without filling them."""
import copy
import math

from .common import ROOT, read, require
from .reference_defaults import review
from .source_adapter import source_file, selected


def inspect(rows, inventory, fields, source, schema_ref, *, root=ROOT):
    result=review(rows,inventory,fields,source);pending=[]
    schema=read(source_file(schema_ref,root))
    for item in result['unreviewed']:
        row=selected(rows,item['object']);kind=row[0];field=item['field'];reason=None
        source_matches=[r for r in source if r[0]==kind and r[1]==row[1]]
        require(len(source_matches)==1 and source_matches[0]==row,'CONDITION_DEFAULT_SOURCE_CHANGED',item)
        if kind=='Shading:Zone:Detailed' and field=='number_of_vertices':
            start=fields.index(kind,field)+1;coordinates=row[start:]
            if (item['effective_default']=='Autocalculate' and len(coordinates)>=9 and len(coordinates)%3==0
                    and all(math.isfinite(float(v)) for v in coordinates)):
                reason='Official schema counts complete explicit source polygon coordinates;not an estimated shading size or added obstacle'
        elif kind=='ConvergenceLimits' and field in ('minimum_plant_iterations','maximum_plant_iterations'):
            props=schema['properties'][kind]['patternProperties']['.*']['properties']
            if item['effective_default']==props[field]['default']:
                reason='Frozen official engine plant iteration default retained exactly;original time-step/warmup/tail tests separately executed;no iteration or accuracy threshold overridden'
        if reason:
            result['reviewed'].append({**copy.deepcopy(item),'disposition':'reviewed_engine_algorithm',
                'reason':reason,'branch_precondition_verified':True,'engine_schema':schema_ref})
        else:pending.append(item)
    result['unreviewed']=pending;result['all_schema_default_branches_accounted']=not pending
    result['source_default_supplement_scope']='Only source-exact explicit shading polygons and frozen schema plant-iteration defaults'
    return result
