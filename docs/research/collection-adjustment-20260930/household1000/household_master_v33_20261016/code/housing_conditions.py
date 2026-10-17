"""Joint reference-housing conditions, separate from independently assigned priors.

The benchmark's high-rise reference is a lift-served RC apartment. This is a
declared scenario definition, not a retrospective law or stock-rate estimate.
"""
import copy


def facets(world):
    f=copy.deepcopy(world['layout']['stock_reference_features'])
    if world['layout']['shared_household_count_design']>1:
        f['kitchen']='shared'
    if f['building_storeys']in('8_to33','34plus'):
        f['load_bearing_structure']='steel_RC';f['elevator']='present'
        if f['housing_source']=='selfbuild':f['housing_source']='rent_other'
    return f


def apply(world):
    w=copy.deepcopy(world);old=copy.deepcopy(w['layout']['stock_reference_features']);new=facets(w)
    w['layout']['stock_reference_features']=new
    w['housing_condition_changes']=[{'field':k,'before':old[k],'after':v,
        'reason':'joint reference definition:shared homes use the one modeled common kitchen;high-rise homes are lift-served RC apartments with declared acquisition',
        'original_reference_assignment_retained_as_evidence':True}for k,v in new.items()if old[k]!=v]
    return w
