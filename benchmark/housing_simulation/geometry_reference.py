"""Bound a generated dwelling to explicitly mapped Chinese unit references.

Only bedroom count and area scaling are admitted. The paper's undimensioned
plans do not certify our coordinates, topology, gross-area mapping or materials.
"""
import math
from .pipeline import HERE, read, sha


def check_geometry_reference(household,layout):
    declaration=household.get('geometry_reference')
    if declaration is None:
        return {'mode':'project_parametric_geometry','source_original_layout_claimed':False}
    allowed={'profile_id','source_area_to_model_gross_factor','mapping_rationale'}
    if set(declaration)!=allowed or not isinstance(declaration['mapping_rationale'],str)or len(declaration['mapping_rationale'])<10:
        raise ValueError('GEOMETRY_REFERENCE:explicit area mapping and rationale required')
    catalog=read(HERE/'geometry_references.json')
    matches=[p for p in catalog['profiles']if p['id']==declaration['profile_id']]
    if not matches:raise ValueError('GEOMETRY_REFERENCE:unknown profile')
    source=matches[0];factor=declaration['source_area_to_model_gross_factor']
    if type(factor)not in(int,float)or not math.isfinite(factor)or not 1<=factor<=1.5:raise ValueError('GEOMETRY_REFERENCE:project mapping factor outside[1,1.5]')
    count=sum(r['census_room_class']=='bedroom'for r in layout['rooms'])
    if count!=source['bedrooms']:raise ValueError('GEOMETRY_REFERENCE:whole dwelling bedroom count differs')
    whole=layout['whole_unit_building_area_m2'];scale=math.sqrt(whole/(source['area_m2']*factor))
    lo,hi=catalog['admitted_linear_scale_range']
    if not lo<=scale<=hi:raise ValueError('GEOMETRY_REFERENCE:outside admitted source-scaled area domain')
    living=sum(r['usable_area_m2']for r in layout['rooms']if r['census_room_class']=='hall'or r['room_id']=='combined_bed_living')
    return {'mode':'Chinese_reference_bounded_parametric_geometry','source_id':catalog['source_id'],
            'catalog_sha256':sha(HERE/'geometry_references.json'),'profile':source,
            'comparison_scope':'whole physical dwelling including shared context',
            'source_area_basis':catalog['area_basis'],'model_area_basis':'whole allocated building gross area',
            'mapping_factor':factor,'mapping_rationale':declaration['mapping_rationale'],
            'mapping_is_project_assumption':True,'derived_linear_scale':scale,'admitted_linear_scale_range':[lo,hi],
            'checks':{'whole_dwelling_bedroom_count':True,'explicit_area_basis_mapping':True,'bounded_linear_scaling':True},
            'diagnostic_model_living_net_to_mapped_indoor_area_ratio':living/(whole/factor),
            'paper_living_ratio_not_enforced':'room/net/gross measurement definitions and topology differ;retain diagnostic only',
            'source_original_layout_claimed':False,'population_weight_inferred':False}
