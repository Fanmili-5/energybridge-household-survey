#!/usr/bin/env python3
"""Hash-bound source assemblies + explicit closed-layout/boundary policy -> IDF."""
import importlib.util
import copy
import math
import sys
from collections import Counter,defaultdict,OrderedDict
from pathlib import Path
from household_model import REPO,sha,digest,decision

LEGACY_PATH=REPO/'docs/research/UX_LOGIC_REVIEW_20260926/PHYSICAL_GATE_V1/V5_DOWNSTREAM/C_IDF/build_v5_idfs.py'
spec=importlib.util.spec_from_file_location('reviewed_assembly_reader',LEGACY_PATH)
legacy=importlib.util.module_from_spec(spec);spec.loader.exec_module(legacy)
parse_idf=legacy.parse_idf
dump=legacy.dump
wall_vertices=legacy.wall_vertices
floor_vertices=legacy.floor_vertices
fmt=legacy.fmt
EPS=1e-6
_SOURCE_PARSE_CACHES=OrderedDict()

def coordinate_grid(layout):
    # Exact float sets can leave a skipped <EPS cell between grid neighbors.
    # Merge co-incident coordinates before indexing, not after face creation.
    normalized=copy.deepcopy(layout)
    axes=[]
    for indices in [(0,2),(1,3)]:
        values=sorted({r['rect_m'][i] for r in layout['spaces'] for i in indices})
        anchors=[]
        for v in values:
            if not anchors or v-anchors[-1]>EPS:anchors.append(v)
        axes.append(anchors)
    for room in normalized['spaces']:
        for i,v in enumerate(room['rect_m']):
            room['rect_m'][i]=min(axes[i%2],key=lambda x:abs(x-v))
    return legacy.grid(normalized)

def bind_assemblies(prototype,weather,trace):
    c=dict(prototype)
    c['weather_epw_path']=weather['epw_path'];c['weather_epw_sha256']=weather['epw_sha256']
    # Cache parsing only, scoped to immutable expected bytes. Rehash every call
    # independently of legacy assert statements (also correct under python -O).
    for pathkey,hashkey in [('source_idf_path','source_idf_sha256'),('parent_idf_path','parent_idf_sha256'),('weather_epw_path','weather_epw_sha256')]:
        if sha(c[pathkey])!=c[hashkey]:raise ValueError('current_byte_hash_mismatch:'+pathkey)
    cachekey=(str(Path(c['parent_idf_path']).resolve()),c['parent_idf_sha256'])
    cache=_SOURCE_PARSE_CACHES.setdefault(cachekey,{})
    _SOURCE_PARSE_CACHES.move_to_end(cachekey)
    while len(_SOURCE_PARSE_CACHES)>8:_SOURCE_PARSE_CACHES.popitem(last=False)
    b=legacy.source_binding(c,cache)
    # Retain exact full-building roof assembly for an explicitly designed top
    # unit; source selected unit ceiling alone would not identify the roof.
    roofs=[r[3] for r in b['rows'] if r[0].lower()=='buildingsurface:detailed' and r[2].lower()=='roof' and r[6].lower()=='outdoors']
    if roofs:b['constructions']['roof']=min(Counter(roofs),key=lambda k:(-Counter(roofs)[k],k))
    library={r[1]:r.copy() for r in b['rows'] if r[0].lower() in ['material','material:nomass','material:airgap','windowmaterial:simpleglazingsystem','windowmaterial:glazing','windowmaterial:gas','construction']}
    used=set(b['constructions'].values())
    for name in list(used):
        if name not in library or library[name][0].lower()!='construction':raise ValueError('construction_dependency_unresolved:'+name)
        used.update(x for x in library[name][2:] if x)
    if not used<=set(library):raise ValueError('material_dependency_unresolved')
    b['material_rows']=[library[k] for k in sorted(used)]
    decision(trace,'thermal_assemblies',b['constructions'],'source_template',
        ['prototype.source_idf_path','prototype.parent_idf_path'],
        'read hash-bound DeST-derived assembly closure; use selected-unit wall/window and full-building roof',
        ['prototype properties are not empirical calibration of this family home','template-vintage label is not household building year'])
    return b

def build_idf(item,layout,prototype,weather,trace):
    b=bind_assemblies(prototype,weather,trace);policy=item['model_policy'];spaces={x['name']:x for x in layout['spaces']}
    height=b['height_m'];cons=b['constructions'];floor=policy['floor_position']
    if floor=='top' and 'roof' not in cons:raise ValueError('top_roof_assembly_unavailable')
    floorbc='Ground' if floor=='ground' else 'Adiabatic'
    roofbc='Outdoors' if floor=='top' else 'Adiabatic'
    loc=weather['location']
    base=[
        ['Version','24.1'],
        ['Building',item['case_id'],fmt(policy['north_axis_deg']),'Suburbs','.04','.4','FullExterior','60','6'],
        ['Site:Location',loc['city'],fmt(loc['latitude']),fmt(loc['longitude']),fmt(loc['timezone']),fmt(loc['altitude_m'])],
        ['Timestep','4'],['SimulationControl','No','No','No','No','Yes'],
        ['RunPeriod','Annual_shell_witness','1','1','2007','12','31','2007','Monday','No','No','No','Yes','Yes'],
        ['GlobalGeometryRules','UpperLeftCorner','Counterclockwise','Relative','Relative'],
        ['ScheduleTypeLimits','Fraction','0','1','Continuous'],
        ['Schedule:Constant','On','Fraction','1'],
        ['Material:NoMass','Declared_Interior_Door','MediumSmooth','.2','.9','.7','.7'],
        ['Construction','Declared_Door','Declared_Interior_Door'],
        *b['material_rows']
    ]
    if floorbc=='Ground':base.append(['Site:GroundTemperature:BuildingSurface',*map(fmt,policy['ground_monthly_temperatures_C'])])
    for name,s in spaces.items():
        x0,y0,x1,y1=s['rect_m'];area=(x1-x0)*(y1-y0)
        base.append(['Zone',name,'0','0','0','0','1','1',fmt(height),fmt(area*height),fmt(area)])
    faces=[];walls={};_,xs,ys,cells=coordinate_grid(layout)
    # One floor/ceiling face per rectangular zone; perimeter walls are split
    # only where adjacent zone/boundary actually changes, then collinear parts
    # merge. Global service grid lines do not fragment exterior windows.
    for name,s in spaces.items():
        box=s['rect_m']
        for typ,con,bc,z in [('Floor',cons['floor'],floorbc,0),('Roof' if roofbc=='Outdoors' else 'Ceiling',cons.get('roof',cons['ceiling']) if roofbc=='Outdoors' else cons['ceiling'],roofbc,height)]:
            faces.append(['BuildingSurface:Detailed',name+'_'+typ,typ,con,name,'',bc,'','SunExposed' if bc=='Outdoors' else 'NoSun','WindExposed' if bc=='Outdoors' else 'NoWind','Autocalculate','4',*floor_vertices(*box,z,typ!='Floor')])
    segments=defaultdict(list)
    for (i,j),name in cells.items():
        for side,di,dj,axis,fixed,lo,hi,outward in [
            ('west',-1,0,'x',xs[i],ys[j],ys[j+1],-1),('east',1,0,'x',xs[i+1],ys[j],ys[j+1],1),
            ('south',0,-1,'y',ys[j],xs[i],xs[i+1],-1),('north',0,1,'y',ys[j+1],xs[i],xs[i+1],1)]:
            neighbor=cells.get((i+di,j+dj))
            if neighbor==name:continue
            bc='Surface' if neighbor is not None else policy['wall_boundaries'][side]
            segments[(name,neighbor,side,axis,fixed,outward,bc)].append((lo,hi))
    for key,values in sorted(segments.items(),key=lambda kv:str(kv[0])):
        name,neighbor,side,axis,fixed,outward,bc=key
        merged=[]
        for lo,hi in sorted(values):
            if merged and abs(merged[-1][1]-lo)<EPS:merged[-1][1]=hi
            else:merged.append([lo,hi])
        for part,(lo,hi) in enumerate(merged):
            namekey=f'{name}_Wall_{side}_{neighbor or "exterior"}_{part}'
            con=cons['external_wall'] if bc=='Outdoors' else cons['internal_wall']
            row=['BuildingSurface:Detailed',namekey,'Wall',con,name,'',bc,'','SunExposed' if bc=='Outdoors' else 'NoSun','WindExposed' if bc=='Outdoors' else 'NoWind','Autocalculate','4',*wall_vertices(axis,fixed,lo,hi,height,outward)]
            faces.append(row);walls[namekey]={'row':row,'room':name,'neighbor':neighbor,'axis':axis,'fixed':fixed,'lo':lo,'hi':hi,'outward':outward,'bc':bc}
    for key,w in walls.items():
        if w['neighbor'] is None:continue
        matches=[n for n,v in walls.items() if v['room']==w['neighbor'] and v['neighbor']==w['room'] and v['axis']==w['axis'] and all(abs(v[t]-w[t])<EPS for t in ['fixed','lo','hi'])]
        if len(matches)!=1:raise ValueError('interzone_face_pair_unresolved:'+key)
        w['row'][7]=matches[0]
    base.extend(faces)
    def host(edge,span,room,other,bc):
        axis,value=edge.split('=');value=float(value)
        matches=[(key,w) for key,w in walls.items() if w['room']==room and w['neighbor']==other and w['bc']==bc and w['axis']==axis and abs(w['fixed']-value)<EPS and span[0]>=w['lo']-EPS and span[1]<=w['hi']+EPS]
        if len(matches)!=1:raise ValueError('opening_not_in_one_host:'+str((room,edge,span,bc)))
        return matches[0]
    for i,w in enumerate(layout['windows']):
        key,v=host(w['edge'],w['span_m'],w['space'],None,'Outdoors')
        base.append(['FenestrationSurface:Detailed',f'Window_{i}','Window',cons['window'],key,'','Autocalculate','','1','4',*wall_vertices(v['axis'],v['fixed'],*w['span_m'],w['height_m'],v['outward'],w['sill_m'])])
    for i,d in enumerate(layout['doors']):
        if d['from']=='entry':
            if d['thermal_status']=='explicit_exterior_door':
                key,v=host(d['edge'],d['span_m'],d['to'],None,'Outdoors')
                base.append(['FenestrationSurface:Detailed',f'Door_{i}_entry','Door','Declared_Door',key,'','Autocalculate','','1','4',*wall_vertices(v['axis'],v['fixed'],*d['span_m'],2,v['outward'])])
            continue
        aa=host(d['edge'],d['span_m'],d['from'],d['to'],'Surface')
        bb=host(d['edge'],d['span_m'],d['to'],d['from'],'Surface')
        for (key,v),name,other in [(aa,f'Door_{i}_a',f'Door_{i}_b'),(bb,f'Door_{i}_b',f'Door_{i}_a')]:
            base.append(['FenestrationSurface:Detailed',name,'Door','Declared_Door',key,other,'Autocalculate','','1','4',*wall_vertices(v['axis'],v['fixed'],*d['span_m'],2,v['outward'])])
    for name in spaces:
        base.append(['ZoneInfiltration:DesignFlowRate',name+'_AirExchange',name,'On','AirChanges/Hour','','','',fmt(policy['air_exchange_ach']),'1','0','0','0'])
    # This stage exports a thermal shell. Resident heat, devices and controls
    # must be attached through explicit later interfaces, never inherited
    # source density or background40W/m2.
    base += [
        ['Output:Variable','*','Zone Mean Air Temperature','Hourly'],
        ['Output:Variable','*','Zone Infiltration Air Change Rate','Hourly'],
        ['Output:Variable','*','Zone Infiltration Current Density Volume Flow Rate','Hourly'],
        ['Output:SQLite','SimpleAndTabular'],['Output:Table:SummaryReports','AllSummary'],
        ['Output:Variable','*','Site Outdoor Air Drybulb Temperature','Hourly']
    ]
    used_constructions={r[3] for r in base if r[0].lower() in ['buildingsurface:detailed','fenestrationsurface:detailed']}
    base=[r for r in base if r[0].lower()!='construction' or r[1] in used_constructions]
    decision(trace,'source_height_m',height,'source_template',['prototype.household_owned_zones'],'median source selected-zone volume/floor area',['not household observed ceiling height'])
    decision(trace,'boundaries',{'floor':floorbc,'ceiling':roofbc,'walls':policy['wall_boundaries']},'designed',
        ['model_policy.floor_position','model_policy.wall_boundaries'],'explicit face boundary map; adiabatic neighbors proxy adjacent conditioned units',
        ['neighbor dwelling temperatures and common corridor omitted','single-storey household only; building storeys distinct'])
    decision(trace,'air_exchange_ach',policy['air_exchange_ach'],'designed',['model_policy.air_exchange_ach'],
        'fixed ACH infiltration-only diagnostic boundary',['not measured ventilation; source prototype schedules are not copied'])
    decision(trace,'door_panel_design',{'thermal_resistance_m2K_W':.2},'designed',['rectangular_layout'],
        'massless door panel with explicit experimental resistance; entry follows declared west boundary',['not a source-template measured door','adiabatic entry omits common corridor; outdoor entry is explicit aperture; egress is not code certified'])
    decision(trace,'orientation',policy['north_axis_deg'],'designed',['model_policy.north_axis_deg'],
        'Building North Axis applies to relative zone/surface coordinates',['not observed home orientation'])
    decision(trace,'solver_settings',{'EnergyPlus':'24.1','timesteps_per_hour':4,'run_calendar_year':2007,'run_hours':8760},'designed',[],
        'fixed non-leap annual weather run and numerical settings',['calendar labels are model settings, not measured2007 household weather'])
    decision(trace,'operation_mode',item['operation_mode'],'designed',['operation_mode'],
        'free-floating thermal shell; no source People/Lights/Equipment/HVAC/40W background inherited',
        ['no occupancy heat or equipment power simulated','thermal demand/electricity and annual household load not claimed'])
    header='! Household-to-IDF research thermal shell; input '+digest(item)+'\n! Layout '+digest(layout)+'; source assembly '+prototype['parent_idf_sha256']+'; EPW '+weather['epw_sha256']+'\n'
    body=header+dump(base)
    index=[{'object_index':i,'type':r[0],'name':r[1] if len(r)>1 else None,
            'source_decision_ids':['door_panel_design'] if len(r)>1 and r[1] in ['Declared_Interior_Door','Declared_Door'] else
             ['air_exchange_ach'] if r[0].lower()=='zoneinfiltration:designflowrate' else
             ['weather_binding'] if r[0].lower()=='site:location' else
             ['thermal_assemblies'] if r[0].lower() in ['material','material:nomass','material:airgap','windowmaterial:simpleglazingsystem','windowmaterial:glazing','windowmaterial:gas','construction'] else
             ['rectangular_layout','source_height_m'] if r[0].lower()=='zone' else
             ['rectangular_layout','source_height_m','boundaries','thermal_assemblies'] if r[0].lower()=='buildingsurface:detailed' else
             ['rectangular_layout','source_height_m','door_panel_design' if r[2]=='Door' else 'thermal_assemblies'] if r[0].lower()=='fenestrationsurface:detailed' else
             ['orientation','solver_settings'] if r[0].lower() in ['building','globalgeometryrules'] else
             ['boundaries'] if r[0].lower()=='site:groundtemperature:buildingsurface' else ['operation_mode','solver_settings']} for i,r in enumerate(base)]
    ledger={'source_reader_path':str(LEGACY_PATH),'source_reader_sha256':sha(LEGACY_PATH),
        'prototype_id':prototype['role_id'],'prototype_catalog_key':prototype['source_catalog_key'],
        'source_idf_path':prototype['source_idf_path'],'source_idf_sha256':prototype['source_idf_sha256'],
        'parent_idf_path':prototype['parent_idf_path'],'parent_idf_sha256':prototype['parent_idf_sha256'],
        'source_accdb_sha256':prototype.get('source_accdb_sha256'),
        'construction_map':cons,'material_rows_sha256':digest(b['material_rows']),
        'source_assembly_rows':b['material_rows'],
        'source_height_m':height,'H6_building_area_m2':item['housing']['H6_building_area_m2'],
        'IDF_zone_floor_area_m2':layout['net_proxy_m2'],'natural_rooms':layout['H7_materialized_natural_rooms'],
        'zone_count':len(spaces),'surface_count':len(faces),'wall_policy':policy['wall_boundaries'],
        'appliance_occupancy_binding_status':'explicit_later_stage_not_inherited','calibrated':False}
    return body,ledger,index

def idf_checks(body,layout):
    rows=parse_idf(body);errors=[]
    def corners(pts):
        # Collinear vertex subdivision does not change a polygon boundary.
        pts=list(pts);changed=True
        while changed and len(pts)>3:
            changed=False
            for i,p in enumerate(pts):
                a,b=pts[i-1],pts[(i+1)%len(pts)]
                if abs(math.dist(a,p)+math.dist(p,b)-math.dist(a,b))<1e-7:
                    pts.pop(i);changed=True;break
        return {tuple(round(v,7) for v in p) for p in pts}
    named=[(r[0].lower(),r[1].lower()) for r in rows if len(r)>1 and r[0].lower() in ['zone','buildingsurface:detailed','fenestrationsurface:detailed']]
    if len(named)!=len(set(named)):errors.append('duplicate_geometry_object_name')
    zones={r[1]:r for r in rows if r[0].lower()=='zone'}
    surfaces={r[1]:r for r in rows if r[0].lower()=='buildingsurface:detailed'}
    opening={r[1]:r for r in rows if r[0].lower()=='fenestrationsurface:detailed'}
    minimum=math.inf;area=sum(float(r[10]) for r in zones.values())
    materials={r[1].lower() for r in rows if r[0].lower().startswith(('material','windowmaterial'))}
    constructions={r[1].lower():r for r in rows if r[0].lower()=='construction'}
    for key,r in constructions.items():
        if any(v.lower() not in materials for v in r[2:] if v):errors.append('construction_layer_missing:'+key)
    for name,r in zones.items():
        if float(r[7])!=1:errors.append('zone_multiplier_not1:'+name)
    if next(r for r in rows if r[0].lower()=='globalgeometryrules')[3]!='Relative':errors.append('building_orientation_not_applied')
    if abs(area-layout['net_proxy_m2'])>1e-6:errors.append('IDF_zone_floor_area_mismatch')
    if len(zones)!=len(layout['spaces']):errors.append('IDF_zone_count_mismatch')
    for name,r in {**surfaces,**opening}.items():
        if r[3].lower() not in constructions:errors.append('surface_construction_missing:'+name)
        start=12 if r[0].lower()=='buildingsurface:detailed' else 10
        pts=[tuple(map(float,r[i:i+3])) for i in range(start,len(r),3)]
        edges=[math.dist(pts[i],pts[(i+1)%len(pts)]) for i in range(len(pts))]
        minimum=min(minimum,*edges)
        if min(edges)<.01-1e-6:errors.append('sub1cm_surface_edge:'+name)
        if start==10:
            host=surfaces.get(r[4])
            if host is None:errors.append('opening_missing_host:'+name);continue
            hp=[tuple(map(float,host[i:i+3])) for i in range(12,len(host),3)]
            if any(min(p[a] for p in pts)<min(p[a] for p in hp)-1e-6 or max(p[a] for p in pts)>max(p[a] for p in hp)+1e-6 for a in range(3)):errors.append('opening_outside_host:'+name)
            if r[5] and (r[5] not in opening or opening[r[5]][5]!=name):errors.append('door_pair_not_reciprocal:'+name)
            elif r[5]:
                mate=opening[r[5]]
                mp=[tuple(map(float,mate[i:i+3])) for i in range(10,len(mate),3)]
                if corners(pts)!=corners(mp):errors.append('door_pair_vertex_mismatch:'+name)
        elif r[6]=='Surface':
            mate=surfaces.get(r[7])
            if mate is None or mate[7]!=name:errors.append('surface_pair_not_reciprocal:'+name)
            elif corners([tuple(map(float,r[i:i+3])) for i in range(12,len(r),3)])!=corners([tuple(map(float,mate[i:i+3])) for i in range(12,len(mate),3)]):errors.append('surface_pair_vertex_mismatch:'+name)
    def cross(a,b):return (a[1]*b[2]-a[2]*b[1],a[2]*b[0]-a[0]*b[2],a[0]*b[1]-a[1]*b[0])
    def sub(a,b):return tuple(x-y for x,y in zip(a,b))
    def normal(row,start):
        pts=[tuple(map(float,row[i:i+3])) for i in range(start,len(row),3)]
        n=(0.,0.,0.)
        for a,b in zip(pts,pts[1:]+pts[:1]):n=tuple(x+y for x,y in zip(n,cross(a,b)))
        return n
    for pool,start,field in [(surfaces,12,7),(opening,10,5)]:
        for name,r in pool.items():
            if r[field] in pool:
                n,m=normal(r,start),normal(pool[r[field]],start)
                if sum(a*b for a,b in zip(n,m))>=0:errors.append('paired_face_normals_not_opposite:'+name)
    geometric={}
    for name,z in zones.items():
        sums=[0.,0.,0.];volume=0.;floora=0.
        for r in surfaces.values():
            if r[4]!=name:continue
            pts=[tuple(map(float,r[i:i+3])) for i in range(12,len(r),3)]
            for i in range(1,len(pts)-1):
                area_vector=cross(sub(pts[i],pts[0]),sub(pts[i+1],pts[0]))
                sums=[a+b/2 for a,b in zip(sums,area_vector)]
                triple=cross(pts[i],pts[i+1]);volume+=sum(a*b for a,b in zip(pts[0],triple))/6
                if r[2]=='Floor':floora+=math.sqrt(sum(a*a for a in area_vector))/2
        if max(map(abs,sums))>1e-5:errors.append('zone_surface_not_closed:'+name)
        if abs(volume-float(z[9]))>1e-5:errors.append('geometric_volume_mismatch:'+name)
        if abs(floora-float(z[10]))>1e-5:errors.append('geometric_floor_area_mismatch:'+name)
        geometric[name]={'floor_area_m2':floora,'volume_m3':volume,'oriented_area_vector_residual_m2':sums}
    unwanted=[r[0] for r in rows if r[0].lower() in ['people','lights','electricequipment','zonegroup']]
    if unwanted:errors.append('unreviewed_source_internal_gains_or_multiplier')
    return {'errors':sorted(set(errors)),'zone_count':len(zones),'zone_floor_area_m2':area,
            'surface_count':len(surfaces),'opening_count':len(opening),'minimum_edge_m':minimum,
            'H7_from_layout_semantics':sum(s['kind']=='natural_room' for s in layout['spaces']),
            'geometric_zone_witness':geometric,
            'no_inherited_occupancy_devices_or_multipliers':not unwanted and all(float(r[7])==1 for r in zones.values())}
