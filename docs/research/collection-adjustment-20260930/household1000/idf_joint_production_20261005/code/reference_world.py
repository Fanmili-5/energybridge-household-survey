"""Metric reference layouts with exact gross/net/shared-area bookkeeping.

These are declared corridor archetypes, NOT reconstructed source apartments.
Source envelope layer thicknesses define exterior/interior wall widths.
Historical room dimensions are engineering references, not stock prevalence.
No room assignment proves sleeping arrangements or appliance installation.
"""
import hashlib,json,math,re
from pathlib import Path
from functools import lru_cache
from scipy.optimize import brentq

OUT=Path(__file__).resolve().parent.parent
BASE=OUT.parent
SOURCE=BASE/'idf_unit_evidence_20261004/conditional_source_unit_witness_v2/source_unit.idf'
HEIGHT=2.9

@lru_cache(None)
def assemblies():
    rows=[[x.strip() for x in p.split(',')] for p in re.sub(r'!.*','',SOURCE.read_text()).split(';') if p.strip()]
    materials={r[1]:r for r in rows if r[0].lower()=='material'}
    constructions={r[1]:r for r in rows if r[0].lower()=='construction'}
    names={'exterior':next(n for n in constructions if n.startswith('ExtWall')),
           'interior':next(n for n in constructions if n.startswith('IntWall') and '[Reverse]' not in n),
           'floor':next(n for n in constructions if n.startswith('Ceiling') and '[Reverse]' not in n),
           'window':next(n for n in constructions if n.startswith('JGJ26'))}
    thickness=lambda name:sum(float(materials[m][3]) for m in constructions[name][2:])
    return {'rows':[r for r in rows if r[0].lower() in ['material','windowmaterial:simpleglazingsystem','construction']],
            'names':names,'exterior_thickness_m':thickness(names['exterior']),
            'interior_thickness_m':thickness(names['interior']),
            'source_path':str(SOURCE),'source_sha256':hashlib.sha256(SOURCE.read_bytes()).hexdigest(),
            'climate_identity':'Beijing2018_reference_envelope; not_all_China_climate_or_stock_calibration'}

def geometry(r,q,s=1.,household_id='target'):
    if not isinstance(r,int) or r<1 or q not in [1,2,4,8] or s<1:raise ValueError('outside_reference_world_domain')
    te,ti=assemblies()['exterior_thickness_m'],assemblies()['interior_thickness_m']
    households=[household_id]+[household_id+f'-aux-{i:02}' for i in range(1,q)]
    rooms=[]
    def add(name,kind,box,users):
        x0,y0,x1,y1=box
        net=[x0+(te if abs(x0)<1e-8 else ti/2),y0+(te if abs(y0)<1e-8 else ti/2),
             x1-(te if abs(x1-W)<1e-8 else ti/2),y1-(te if abs(y1-D)<1e-8 else ti/2)]
        thermal=[x0+(te/2 if abs(x0)<1e-8 else 0),y0+(te/2 if abs(y0)<1e-8 else 0),
                 x1-(te/2 if abs(x1-W)<1e-8 else 0),y1-(te/2 if abs(y1-D)<1e-8 else 0)]
        if net[2]<=net[0] or net[3]<=net[1]:raise ValueError('wall_thickness_exhausts_room')
        rooms.append({'room_id':name,'census_room_class':kind,'classification_evidence':'engineering_scenario',
          'using_household_ids':users,'gross_rect_m':box,'usable_rect_m':net,'thermal_centerline_rect_m':thermal,
          'gross_area_m2':(x1-x0)*(y1-y0),'usable_area_m2':(net[2]-net[0])*(net[3]-net[1]),
          'thermal_reference_area_m2':(thermal[2]-thermal[0])*(thermal[3]-thermal[1]),
          'function_evidence':'declared_reference_layout; not_inferred_source_door_or_real_home'})
    if r==1 and q==1:
        W=4*s+2*te;D=(3+1.2+2)*s+2*ti+2*te
        y1=te+3*s+ti/2;y2=y1+1.2*s+ti;x1=te+2*s+ti/2
        add('combined_bed_living','bedroom',[0,0,W,y1],households)
        add('corridor','corridor',[0,y1,W,y2],households)
        add('kitchen','kitchen',[0,y2,x1,D],households)
        add('toilet','toilet',[x1,y2,W,D],households)
    else:
        count=r*q;cols=math.ceil(count/2);private_width=cols*2.2*s+(cols-1)*ti
        W=private_width+4*s+ti+2*te;D=(2.5+1.2+2.5)*s+2*ti+2*te
        xp=te+private_width+ti/2;y1=te+2.5*s+ti/2;y2=y1+1.2*s+ti
        rows=[('south',math.ceil(count/2),0,y1),('north',count//2,y2,D)]
        index=0
        for side,num,y0,y3 in rows:
            if not num:raise ValueError('one_private_room_requires_combined_studio')
            width=(private_width-(num-1)*ti)/num
            breaks=[0]+[te+j*width+(j-.5)*ti for j in range(1,num)]+[xp]
            for j in range(num):
                owner=households[index//r];index+=1
                add(f'private_{index:02}','bedroom',[breaks[j],y0,breaks[j+1],y3],[owner])
        add('corridor','corridor',[0,y1,W,y2],households)
        xk=xp+ti+2*s
        add('living_hall','hall',[xp,0,W,y1],households)
        add('kitchen','kitchen',[xp,y2,xk,D],households)
        add('toilet','toilet',[xk,y2,W,D],households)
    common=sum(x['gross_area_m2'] for x in rooms if len(x['using_household_ids'])>1)
    private={h:sum(x['gross_area_m2'] for x in rooms if x['using_household_ids']==[h]) for h in households}
    # q1 facilities are exclusive, hence all gross space belongs to target.
    assert abs(sum(private.values())+common-W*D)<1e-7
    target_h6=private[household_id]+common/q
    own_usable=sum(x['usable_area_m2'] for x in rooms if x['using_household_ids']==[household_id])
    common_usable=sum(x['usable_area_m2'] for x in rooms if len(x['using_household_ids'])>1)
    from shapely.geometry import box as shapely_box
    from shapely.ops import unary_union
    polygons=[shapely_box(*x['gross_rect_m']) for x in rooms]
    assert abs(sum(p.area for p in polygons)-unary_union(polygons).area)<1e-7
    assert abs(unary_union(polygons).area-W*D)<1e-7
    access=[]
    corridor=next(x for x in rooms if x['room_id']=='corridor')
    for room in rooms:
        if room['room_id']=='corridor':continue
        segment=shapely_box(*room['gross_rect_m']).boundary.intersection(shapely_box(*corridor['gross_rect_m']).boundary)
        if segment.length<.8:raise ValueError('no_0_8m_reference_portal_to_corridor')
        access.append({'from':room['room_id'],'to':'corridor','width_design_m':.8,'height_design_m':2.,
                       'common_edge':list(segment.coords),'evidence':'new_engineering_door_or_opening; not_observed_source_door'})
    minima=[]
    for room in rooms:
        bound=12 if room['room_id']=='combined_bed_living' else 5 if room['census_room_class']=='bedroom' else 4 if room['census_room_class']=='kitchen' else 2.5 if room['census_room_class']=='toilet' else 10 if room['room_id']=='living_hall' else 0
        minima.append({'room_id':room['room_id'],'usable_area':room['usable_area_m2'],'reference_minimum':bound})
        if room['usable_area_m2']+1e-7<bound:raise ValueError('reference_functional_area_minimum_failed')
    world={'area_basis':'census_building_area_components','area_evidence':'engineering_scenario',
       'whole_unit_building_area_m2':W*D,'common_building_area_m2':common,
       'households':[{'household_id':h,'exclusive_building_area_m2':private[h],
         'is_population_target':h==household_id,'resident_count_observed':None if h!=household_id else 'join_target_roster'} for h in households],
       'rooms':rooms,'metric_outer_rect_m':[0,0,W,D],'target_household_id':household_id,'target_H6_unrounded_m2':target_h6,
       'target_H7':r,'shared_household_count_design':q,'uniform_room_size_scale_design':s,
       'usable_total_area_m2':sum(x['usable_area_m2'] for x in rooms),
       'thermal_reference_floor_area_m2':sum(x['thermal_reference_area_m2'] for x in rooms),
       'wall_footprint_area_m2':W*D-sum(x['usable_area_m2'] for x in rooms),
       'target_exclusive_usable_area_m2':own_usable,
       'common_actual_accessible_usable_area_m2':common_usable,
       'target_equal_share_allocated_usable_area_m2':own_usable+common_usable/q,
       'target_accessible_usable_area_m2':own_usable+common_usable,
       'whole_building_property_sales_common_area_outside_model':None,
       'census_geometry_operator_identity':'declared_outer_unit_plus_internal_household_common_allocation; not_verified_property_registered_or_real_home_area',
       'gross_to_net_constant_used':False,'access':access,'functional_minima_checked':minima,
       'source_original_floorplan_geometry_preserved':False,
       'layout_identity':'declared_double_loaded_corridor_or_studio_reference_archetype; NOT_image_or_native_IDF_reconstruction',
       'building_code_compliance_or_historical_stock_frequency_claimed':False,
       'sleeping_positions_and_operator_assignments_completed':False,
       'auxiliary_households_are_not_extra_population_target_rows':True,
       'physical_binding_approved':False,'actor_ready':False}
    return world

@lru_cache(None)
def minimum_area(r,q):return geometry(r,q)['target_H6_unrounded_m2']

def sized_world(r,q,target_area,household_id):
    f=lambda s:geometry(r,q,s,household_id)['target_H6_unrounded_m2']-target_area
    if f(1)>1e-7:raise ValueError('target_area_below_reference_domain; no_household_resampling')
    high=2
    while f(high)<0:high*=2
    s=brentq(f,1,high,xtol=1e-12)
    world=geometry(r,q,s,household_id)
    assert abs(world['target_H6_unrounded_m2']-target_area)<1e-6
    return world

if __name__=='__main__':
    print(json.dumps({str(r):{str(q):minimum_area(r,q) for q in [1,2,4,8]} for r in range(1,11)},indent=2))
