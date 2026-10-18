"""Parameterized extraction of the reviewed reference-shell kernel.

Rectangular corridor/studio geometry; midfloor north/south exposure only.
"""
import copy,math
from collections import defaultdict
from .faces import merge
from ..policy import reference, fingerprint

REF=reference('shell')

def area3(v):
    sums=[sum(a[1]*b[2]-a[2]*b[1] for a,b in zip(v,v[1:]+v[:1])),sum(a[2]*b[0]-a[0]*b[2] for a,b in zip(v,v[1:]+v[:1])),sum(a[0]*b[1]-a[1]*b[0] for a,b in zip(v,v[1:]+v[:1]))]
    return sum(x*x for x in sums)**.5/2

def points_flat(p):return [x for v in p for x in v]

def model(world,assembly,height=2.9,fixture=False,delta=3):
    HEIGHT=height
    rooms={x['room_id']:x for x in world['rooms']};a=assembly;cons=copy.deepcopy(a['names'])
    material_rows=copy.deepcopy(a['rows'])
    old_floor=next(r for r in material_rows if r[0]=='Construction' and r[1]==cons['floor'])
    # Preserve native extraction evidence; generated midfloor uses an explicit
    # reference core without assigning an unverified source material identity.
    core='Reference_RC_core_120mm';floor='Reference_RC_midfloor'
    material_rows += [['Material',core,'MediumRough',REF['floor_core_m'],REF['floor_conductivity_W_mK'],REF['floor_density_kg_m3'],REF['floor_cp_J_kgK'],REF['floor_thermal_absorptance'],REF['floor_solar_absorptance'],REF['floor_visible_absorptance']],
                      ['Construction',floor,old_floor[2],core,old_floor[-1]]]
    cons['floor']=floor
    # Compile only the dependency closure of actually used constructions.
    # Unused historical source alternatives remain in the immutable source.
    used={v for k,v in cons.items() if k!='window' or not fixture};construction_rows=[r for r in material_rows if r[0]=='Construction' and r[1] in used]
    required={n for r in construction_rows for n in r[2:]}
    material_rows=[r for r in material_rows if r[0]!='Construction' and r[1] in required]+construction_rows
    if fixture:
        for r in material_rows:
            if r[0].lower()=='material':r[7]='0.00000001';r[8]='0';r[9]='0'
    props=material_rows+[['Material:NoMass','ReferenceDoorR','Smooth',REF['door_R_m2K_W'],'.9','.7','.7'],['Construction','ReferenceDoor','ReferenceDoorR']]
    if fixture:props[-2][4]='0.00000001'
    rows=[['Version','24.1'],['Building','Declared_reference_geometry','0','Suburbs',
        '.00001' if fixture else '.04','.0001' if fixture else '.4','FullExterior','100' if fixture else '25','60' if fixture else '6'],
       ['Timestep','4'],['SimulationControl','No','No','No','No','Yes'],
       ['RunPeriod','Geometry_reference_day','7','1','2007','7','1','2007','Sunday','No','No','No','Yes','Yes'],
       ['GlobalGeometryRules','UpperLeftCorner','Counterclockwise','Relative','Relative'],*props,
       ['Output:SQLite','SimpleAndTabular'],['Output:Variable','*','Zone Mean Air Temperature','Hourly']]
    for name,r in rooms.items():
        rows.append(['Zone',name,'0','0','0','0','1','1',HEIGHT,r['usable_area_m2']*HEIGHT,r['usable_area_m2']])
    boxes={k:r['thermal_centerline_rect_m'] for k,r in rooms.items()}
    xs=sorted(set(v for x in boxes.values() for v in [x[0],x[2]]));ys=sorted(set(v for x in boxes.values() for v in [x[1],x[3]]))
    # Do not merge merely close vertices. Reference construction uses common
    # exact endpoints; all intervals have a single owning rectangular space.
    owner={}
    for i,(x0,x1) in enumerate(zip(xs,xs[1:])):
        for j,(y0,y1) in enumerate(zip(ys,ys[1:])):
            if x1-x0<1e-8 or y1-y0<1e-8:continue
            mid=((x0+x1)/2,(y0+y1)/2);containing=[n for n,(a,b,c,d) in boxes.items() if a<mid[0]<c and b<mid[1]<d]
            if len(containing)!=1:raise ValueError('thermal_centerline_partition_gap_or_overlap')
            owner[(i,j)]=containing[0]
    floors=[];walls=[]
    for name,(x0,y0,x1,y1) in boxes.items():
        fv=[[x0,y0,0],[x0,y1,0],[x1,y1,0],[x1,y0,0]];cv=[[x0,y1,HEIGHT],[x0,y0,HEIGHT],[x1,y0,HEIGHT],[x1,y1,HEIGHT]]
        for typ,vs in [('Floor',fv),('Ceiling',cv)]:
            floors.append({'name':name+'_'+typ,'zone':name,'type':typ,'construction':cons['floor'],'bc':'Adiabatic','peer':'','vertices':vs})
    sid=0
    for (i,j),name in owner.items():
        x0,x1,y0,y1=xs[i],xs[i+1],ys[j],ys[j+1]
        boundaries=[('south',(i,j-1),[[x0,y0,HEIGHT],[x1,y0,HEIGHT],[x1,y0,0],[x0,y0,0]]),
          ('north',(i,j+1),[[x1,y1,HEIGHT],[x0,y1,HEIGHT],[x0,y1,0],[x1,y1,0]]),
          ('east',(i+1,j),[[x1,y0,HEIGHT],[x1,y1,HEIGHT],[x1,y1,0],[x1,y0,0]]),
          ('west',(i-1,j),[[x0,y1,HEIGHT],[x0,y0,HEIGHT],[x0,y0,0],[x0,y1,0]])]
        for side,neigh,vs in boundaries:
            peer=owner.get(neigh)
            if peer==name:continue
            sid+=1
            outdoor=peer is None and (side in ['south','north'] or (side=='east' and name=='corridor'))
            walls.append({'name':f'wall_{sid:04}','zone':name,'type':'Wall','construction':cons['interior'] if peer else cons['exterior'],
             'bc':'Surface' if peer else 'Outdoors' if outdoor else 'Adiabatic','peer_zone':peer,'peer':'','side':side,
             'vertices':[vs[1],vs[0],vs[3],vs[2]]})
    walls=merge(walls)
    signatures=defaultdict(list)
    for w in walls:
        if w['peer_zone']:
            sig=tuple(sorted(tuple(round(x,8) for x in p) for p in w['vertices']));signatures[sig].append(w)
    for sig,faces in signatures.items():
        if len(faces)!=2 or faces[0]['zone']!=faces[1]['peer_zone']:raise ValueError('nonreciprocal_shared_wall')
        faces[0]['peer']=faces[1]['name'];faces[1]['peer']=faces[0]['name']
    openings=[]
    def aperture(face,width,height,name,typ,construction,z0=.8,peer=''):
        a,b=face['vertices'][:2];dx,dy=b[0]-a[0],b[1]-a[1];length=math.hypot(dx,dy)
        if width>length-.1 or z0+height>HEIGHT-.1:raise ValueError('opening_does_not_fit_parent')
        u=((length-width)/2/length,(length+width)/2/length)
        xy=[(a[0]+v*dx,a[1]+v*dy) for v in u]
        vs=[[xy[0][0],xy[0][1],z0+height],[xy[1][0],xy[1][1],z0+height],
            [xy[1][0],xy[1][1],z0],[xy[0][0],xy[0][1],z0]]
        openings.append({'name':name,'type':typ,'construction':construction,'parent':face['name'],'peer':peer,'vertices':vs,'zone':face['zone']})
    for access in world['access']:
        candidates=[w for w in walls if w['zone']==access['from'] and w['peer_zone']=='corridor' and math.dist(w['vertices'][0][:2],w['vertices'][1][:2])>=.9]
        if not candidates:raise ValueError('declared_portal_not_on_IDF_common_wall')
        f=max(candidates,key=lambda w:area3(w['vertices']));partner=next(w for w in walls if w['name']==f['peer'])
        n='door_'+access['from'];aperture(f,REF['door_width_m'],REF['door_height_m'],n,'Door','ReferenceDoor',REF['door_bottom_m'],n+'_peer')
        aperture(partner,REF['door_width_m'],REF['door_height_m'],n+'_peer','Door','ReferenceDoor',REF['door_bottom_m'],n)
    entrance=max([w for w in walls if w['zone']=='corridor' and w['side']=='east' and w['bc']=='Outdoors'],key=lambda w:area3(w['vertices']))
    aperture(entrance,REF['entry_width_m'],REF['door_height_m'],'entry_door','Door','ReferenceDoor',REF['door_bottom_m'])
    if not fixture:
        for name in rooms:
            ext=[w for w in walls if w['zone']==name and w['bc']=='Outdoors' and w['side'] in ['north','south']]
            if not ext:continue
            f=max(ext,key=lambda w:area3(w['vertices']));L=math.dist(f['vertices'][0][:2],f['vertices'][1][:2])
            width=min(L-.2,area3(f['vertices'])*REF['selected_face_WWR']/REF['window_height_m'])
            if width>.15:aperture(f,width,REF['window_height_m'],'window_'+name,'Window',cons['window'],REF['window_bottom_m'])
    if fixture:
        rows += [['SurfaceProperty:OtherSideCoefficients','Guard','18','20','1','0','0','0','0','','No','24',''],
                 ['Schedule:Constant','HeatingControl','','1'],['Schedule:Constant','CellTemperature','',20+delta],
                 ['Schedule:Constant','ElecFixture','','1']]
        for n in rooms:
            supply=n+'_supply';ret=n+'_return'
            rows += [['ZoneHVAC:IdealLoadsAirSystem',n+'_heater','',supply,'','','50','13','.015','.009','NoLimit','autosize','','LimitCapacity','autosize','0','','','None','','None'],
              ['ZoneHVAC:EquipmentList',n+'_equipment','SequentialLoad','ZoneHVAC:IdealLoadsAirSystem',n+'_heater','1','1'],
              ['ZoneHVAC:EquipmentConnections',n,n+'_equipment',supply,'',n+'_air',ret],
              ['ThermostatSetpoint:SingleHeating',n+'_setpoint','CellTemperature'],
              ['ZoneControl:Thermostat',n+'_thermostat',n,'HeatingControl','ThermostatSetpoint:SingleHeating',n+'_setpoint']]
    for f in floors+walls:
        bc,obj=f['bc'],f['peer']
        if fixture and bc=='Outdoors':bc,obj='OtherSideCoefficients','Guard'
        rows.append(['BuildingSurface:Detailed',f['name'],f['type'],f['construction'],f['zone'],'',bc,obj,
            'SunExposed' if bc=='Outdoors' else 'NoSun','WindExposed' if bc=='Outdoors' else 'NoWind','Autocalculate','4',*points_flat(f['vertices'])])
        if fixture:rows.append(['SurfaceProperty:ConvectionCoefficients',f['name'],'Inside','Value','3'])
    for f in openings:
        rows.append(['FenestrationSurface:Detailed',f['name'],f['type'],f['construction'],f['parent'],f['peer'],'Autocalculate','','1','4',*points_flat(f['vertices'])])
        if fixture:
            # Coefficients on an opaque parent do not fix its subsurface film.
            rows.append(['SurfaceProperty:ConvectionCoefficients',f['name'],'Inside','Value','3'])
    if fixture:
        private=next(n for n,r in rooms.items() if r['using_household_ids']==[world['target_household_id']] and r['census_room_class']=='bedroom')
        rows += [['ElectricEquipment','PrivateElectricalFixture',private,'ElecFixture','EquipmentLevel','1000','','','0','0','1','DiagnosticFixture'],
          ['ElectricEquipment','CommonElectricalFixture','corridor','ElecFixture','EquipmentLevel','500','','','0','0','1','DiagnosticFixture'],
          ['Output:Meter','Electricity:Facility','Hourly'],['Output:Variable','*','Electric Equipment Electricity Energy','Hourly'],
          ['Output:Variable','*','Zone Ideal Loads Supply Air Sensible Heating Rate','Hourly']]
    metadata={'surfaces':floors+walls,'openings':openings,'source_assemblies_sha256':a['source_sha256'],
      'source_envelope_identity':a['climate_identity'],'source_geometry_preserved':False,
      'floor_material_policy':'replace_native_floor_core_with_declared_RC_reference;not_source_material_identification',
      'material_semantic_admission_sha256':'explicit_120mm_RC_reference_in_this_kernel',
      'floor_core_thickness_design_m':REF['floor_core_m'],'floor_total_thickness_design_m':sum(float(r[3])for r in material_rows if r[0]=='Material'and r[1]in next(c[2:]for c in material_rows if c[0]=='Construction'and c[1]==floor)),
      'reference_assumptions_sha256':fingerprint(),'floor_parameters_are_not_stock_or_asbuilt_observations':True,
      'geometry_is_engineering_reference':True,'floor_and_side_neighbor_policy':'midfloor_north_south_exposed_east_west_zero_flux_except_gallery_entry; explicit_scenario',
      'windows':'new_reference_WWR0_25_on_selected_north_south_faces; not_observed_source_windows',
      'door_R_m2K_per_W':REF['door_R_m2K_W'],'door_R_is_engineering_reference_not_observed':True,
      'door_bottom_elevation_reference_m':REF['door_bottom_m'],
      'door_bottom_policy':'explicit10mm_reference_threshold; avoid_flush_subsurface_base_edge_shadow_geometry_warning; not_observed_source_threshold',
      'centerline_surface_geometry_convention':True,'Zone_floor_area_and_air_volume_use_computed_usable_area':True,
      'actual_household_appliance_instances_or_HVAC_installed':False,'fixture_is_household_device':False,
      'city_climate_and_real_neighbor_conditions_matched_to_household':False,
      'source_original_thermal_absorptance_preserved':False,
      'fixture_absorptance_override':1e-8 if fixture else None,'fixture_no_windows_for_opaque_UA_test':fixture}
    metadata['fixture_steady_initialization_policy']='minimum60 maximum100 warmup_days; load_convergence1e-5 temperature_convergence1e-4K' if fixture else None
    return rows,metadata
