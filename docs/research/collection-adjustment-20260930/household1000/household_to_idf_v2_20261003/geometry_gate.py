#!/usr/bin/env python3
"""Independent IDF readback for declared axis-aligned rectangular zone prisms.

Standard library only. It imports neither the writer nor its grid/vertices.
Atomic directed edges permit legal collinear vertex and face subdivision.
This gate does not certify arbitrary concave geometry or building-code egress.
"""
import collections,hashlib,math,pathlib
EPS=1e-6

def rows(text):
    text='\n'.join(line.split('!',1)[0] for line in text.splitlines())
    return [[field.strip() for field in obj.split(',')] for obj in text.split(';') if obj.strip()]
def sub(a,b):return tuple(x-y for x,y in zip(a,b))
def dot(a,b):return sum(x*y for x,y in zip(a,b))
def cross(a,b):return (a[1]*b[2]-a[2]*b[1],a[2]*b[0]-a[0]*b[2],a[0]*b[1]-a[1]*b[0])
def normal(poly):
    n=(0.,0.,0.)
    for a,b in zip(poly,poly[1:]+poly[:1]):n=tuple(x+y for x,y in zip(n,cross(a,b)))
    return n
def q(point):return tuple(round(x,7) for x in point)
def vertices(row):
    start=12 if row[0].lower()=='buildingsurface:detailed' else 10
    if len(row)<=start or (len(row)-start)%3:raise ValueError('vertex_field_count')
    count=int(row[start-1])
    if count<3 or count!=(len(row)-start)//3:raise ValueError('declared_vertex_count')
    pts=[tuple(float(v) for v in row[i:i+3]) for i in range(start,len(row),3)]
    if not all(math.isfinite(v) for p in pts for v in p):raise ValueError('nonfinite_vertex')
    if any(math.dist(a,b)<EPS for a,b in zip(pts,pts[1:]+pts[:1])):raise ValueError('zero_length_edge')
    n=normal(pts)
    if not all(math.isfinite(v) for v in n) or math.hypot(*n)<EPS:raise ValueError('degenerate_or_nonfinite_normal')
    return pts
def atom_edges(poly,allpoints):
    result=[]
    for a,b in zip(poly,poly[1:]+poly[:1]):
        d=sub(b,a);length2=dot(d,d)
        if not math.isfinite(length2) or length2<=EPS*EPS:raise ValueError('edge_length_outside_numeric_support')
        cuts=[]
        for p in allpoints:
            ap=sub(p,a);t=dot(ap,d)/length2
            residual=sub(ap,tuple(t*x for x in d))
            if -EPS<=t<=1+EPS and math.hypot(*residual)<EPS:cuts.append((max(0,min(1,t)),p))
        cuts=sorted({(round(t,8),q(p)) for t,p in cuts})
        result.extend((a,b) for (_,a),(_,b) in zip(cuts,cuts[1:]) if a!=b)
    return result

def same_opposed_polygon(a,b):
    points=set(a+b)
    return collections.Counter(atom_edges(a,points))==collections.Counter((y,x) for x,y in atom_edges(b,points))

def convex_contains(poly,point):
    n=normal(poly);scale=math.hypot(*n)
    return all(dot(cross(sub(b,a),sub(point,a)),n)/(scale*math.dist(a,b))>=-EPS for a,b in zip(poly,poly[1:]+poly[:1]))

def inspect_idf(body,layout):
    """Return structured pass/fail even for malformed numeric/geometry input."""
    errors=[];zone_results=[]
    result={'schema':'eb.independent_rectangular_geometry.v2',
       'scope':'declared rectangular zone prisms, collinear subdivisions, dependencies, reciprocal surfaces and openings; no arbitrary-geometry/code/empirical certification',
       'checker_uses_writer_grid_or_vertices':False,'checker_path':str(pathlib.Path(__file__).resolve()),
       'checker_sha256':hashlib.sha256(pathlib.Path(__file__).read_bytes()).hexdigest(),
       'idf_sha256':hashlib.sha256(body.encode()).hexdigest(),'zone_results':zone_results}
    try:
        rr=rows(body)
        gg=[r for r in rr if r[0].lower()=='globalgeometryrules']
        if len(gg)!=1 or gg[0][2].lower()!='counterclockwise' or gg[0][3].lower()!='relative':errors.append('geometry_coordinate_rule_unsupported')
        named_types={'zone','buildingsurface:detailed','fenestrationsurface:detailed','construction','material','material:nomass','material:airgap','windowmaterial:simpleglazingsystem','windowmaterial:glazing','windowmaterial:gas'}
        names=[(r[0].lower(),r[1].lower()) for r in rr if r[0].lower() in named_types]
        if len(names)!=len(set(names)):errors.append('duplicate_type_name')
        geometry_names=[r[1].lower() for r in rr if r[0].lower() in ['zone','buildingsurface:detailed','fenestrationsurface:detailed']]
        if len(geometry_names)!=len(set(geometry_names)):errors.append('duplicate_geometry_name_across_types')
        material_names=[r[1].lower() for r in rr if r[0].lower().startswith(('material','windowmaterial'))]
        if len(material_names)!=len(set(material_names)):errors.append('duplicate_material_namespace_name')
        zones={r[1].lower():r for r in rr if r[0].lower()=='zone'}
        surfaces={r[1].lower():r for r in rr if r[0].lower()=='buildingsurface:detailed'}
        openings={r[1].lower():r for r in rr if r[0].lower()=='fenestrationsurface:detailed'}
        cons={r[1].lower():r for r in rr if r[0].lower()=='construction'}
        materials={r[1].lower():r for r in rr if r[0].lower().startswith(('material','windowmaterial'))}
        if layout.get('schema')!='eb.closed_rectangular_layout.v1':errors.append('layout_support_schema_unsupported')
        spaces={s['name'].lower():s for s in layout['spaces']}
        if len(spaces)!=len(layout['spaces']):errors.append('duplicate_layout_space_name')
        if not zones or set(zones)!=set(spaces):errors.append('zone_layout_name_set_mismatch')
        for key,c in cons.items():
            if any(layer.lower() not in materials for layer in c[2:] if layer):errors.append('construction_material_missing:'+key)
        gains=[r[0] for r in rr if r[0].lower() in ['people','lights','electricequipment','gasequipment','hotwaterequipment','otherequipment','zonegroup','zonehvac:idealloadsairsystem']]
        if gains:errors.append('internal_gain_hvac_or_zonegroup')
        polys={}
        for key,r in {**surfaces,**openings}.items():
            if r[3].lower() not in cons:errors.append('missing_construction:'+key)
            try:polys[key]=vertices(r)
            except (ValueError,OverflowError,IndexError) as exc:errors.append('invalid_geometry:'+key+':'+str(exc))
        for key,r in surfaces.items():
            if r[4].lower() not in zones:errors.append('surface_zone_missing:'+key)
        for name,z in zones.items():
            if name not in spaces:continue
            box=spaces[name]['rect_m'];h=float(z[8]);volume=float(z[9]);area=float(z[10])
            if len(box)!=4 or not all(isinstance(v,(int,float)) and not isinstance(v,bool) and math.isfinite(float(v)) for v in box):raise ValueError('invalid_layout_rectangle:'+name)
            x0,y0,x1,y1=map(float,box)
            if not all(math.isfinite(v) and v>0 for v in [h,volume,area]) or x1<=x0 or y1<=y0:raise ValueError('invalid_zone_dimensions:'+name)
            if float(z[7])!=1:errors.append('zone_multiplier_not_one:'+name)
            if any(float(z[i])!=0 for i in [2,3,4,5]):errors.append('relative_zone_transform_unsupported:'+name)
            center=((x0+x1)/2,(y0+y1)/2,h/2);bounds=[(x0,x1),(y0,y1),(0,h)]
            ff=[r for r in surfaces.values() if r[4].lower()==name and r[1].lower() in polys]
            pp=[polys[r[1].lower()] for r in ff];allpoints={p for poly in pp for p in poly}
            edges=collections.Counter();vol=0.;floora=0.
            for r,p in zip(ff,pp):
                key=r[1].lower();n=normal(p);m=math.hypot(*n);fc=tuple(sum(v[a] for v in p)/len(p) for a in range(3))
                if dot(n,sub(fc,center))<=EPS:errors.append('face_normal_not_outward:'+key)
                if max(abs(dot(n,sub(v,p[0])))/m for v in p)>EPS:errors.append('nonplanar_face:'+key)
                if any(not convex_contains(p,v) for v in p):errors.append('nonconvex_face_unsupported:'+key)
                axes=[a for a in range(3) if max(v[a] for v in p)-min(v[a] for v in p)<=EPS]
                if len(axes)!=1 or not any(abs(p[0][axes[0]]-edge)<=EPS for edge in bounds[axes[0]]):errors.append('face_not_on_declared_rectangular_boundary:'+key)
                if any(v[a]<bounds[a][0]-EPS or v[a]>bounds[a][1]+EPS for v in p for a in range(3)):errors.append('face_outside_declared_zone:'+key)
                typ=r[2].lower()
                if typ=='floor' and any(abs(v[2])>EPS for v in p):errors.append('floor_not_at_zero:'+key)
                if typ in ['ceiling','roof'] and any(abs(v[2]-h)>EPS for v in p):errors.append('ceiling_not_at_declared_height:'+key)
                for i in range(1,len(p)-1):vol+=dot(p[0],cross(p[i],p[i+1]))/6
                for a,b in atom_edges(p,allpoints):edges[(a,b)]+=1
                if typ=='floor':floora+=m/2
            bad=[(a,b,count,edges[(b,a)]) for (a,b),count in edges.items() if count!=1 or edges[(b,a)]!=1]
            if not ff or bad:errors.append('zone_shell_not_closed_or_opposite_edges:'+name)
            if not math.isfinite(vol) or abs(vol-volume)>1e-5:errors.append('zone_volume_not_geometric:'+name)
            if not math.isfinite(floora) or abs(floora-area)>1e-5:errors.append('zone_floor_area_not_geometric:'+name)
            if abs(area-(x1-x0)*(y1-y0))>1e-5:errors.append('zone_area_not_declared_rectangle:'+name)
            zone_results.append({'zone':name,'closed_oriented_edge_complex':bool(ff) and not bad,'edge_atoms':len(edges),
                'unpaired_edge_atoms':len(bad),'readback_volume_m3':vol if math.isfinite(vol) else None,'readback_floor_area_m2':floora if math.isfinite(floora) else None})
        for key,r in surfaces.items():
            if r[6].lower()!='surface' or key not in polys:continue
            mate=surfaces.get(r[7].lower());mk=r[7].lower()
            if mate is None or mate[7].lower()!=key or mk==key:errors.append('wall_mate_not_reciprocal:'+key);continue
            if mk not in polys:continue
            p,mp=polys[key],polys[mk]
            if not same_opposed_polygon(p,mp):errors.append('wall_vertices_not_coincident:'+key)
            if dot(normal(p),normal(mp))>=-EPS:errors.append('wall_mate_normal_not_opposite:'+key)
            if r[4].lower()==mate[4].lower():errors.append('wall_mate_same_zone:'+key)
            a,b=cons.get(r[3].lower()),cons.get(mate[3].lower())
            if a and b and [x.lower() for x in a[2:]]!=[x.lower() for x in b[2:]][::-1]:errors.append('wall_mate_layer_order_not_reversed:'+key)
        for key,r in openings.items():
            host=surfaces.get(r[4].lower())
            if host is None:errors.append('opening_host_missing:'+key);continue
            hk=host[1].lower()
            if key not in polys or hk not in polys:continue
            p,hp=polys[key],polys[hk];n=normal(hp);m=math.hypot(*n);np=normal(p)
            if max(abs(dot(n,sub(v,hp[0])))/m for v in p)>EPS:errors.append('opening_not_coplanar:'+key)
            if dot(n,np)<=EPS:errors.append('opening_host_normal_not_same:'+key)
            if any(not convex_contains(p,v) for v in p):errors.append('nonconvex_opening_unsupported:'+key)
            if any(min(v[a] for v in p)<min(v[a] for v in hp)-EPS or max(v[a] for v in p)>max(v[a] for v in hp)+EPS for a in range(3)):errors.append('opening_not_inside_host:'+key)
            if any(not convex_contains(hp,v) for v in p):errors.append('opening_not_inside_convex_host:'+key)
            if float(r[8])!=1:errors.append('opening_multiplier_not_one:'+key)
            if r[5]:
                mate=openings.get(r[5].lower());mk=r[5].lower()
                if mate is None or mate[5].lower()!=key or mk==key:errors.append('door_mate_not_reciprocal:'+key);continue
                if mk not in polys:continue
                mp=polys[mk]
                if not same_opposed_polygon(p,mp):errors.append('door_vertices_not_coincident:'+key)
                if dot(np,normal(mp))>=-EPS:errors.append('door_mate_normal_not_opposite:'+key)
                if r[3].lower()!=mate[3].lower():errors.append('door_mate_construction_mismatch:'+key)
                if host[7].lower()!=mate[4].lower() or host[6].lower()!='surface':errors.append('door_hosts_not_interzone_mates:'+key)
            elif host[6].lower()!='outdoors':errors.append('unpaired_opening_host_not_outdoors:'+key)
        area=sum(r['readback_floor_area_m2'] or 0 for r in zone_results)
        if not math.isfinite(area) or abs(area-float(layout['net_proxy_m2']))>1e-5:errors.append('aggregate_area_mismatch')
        result.update(zone_count=len(zones),surface_count=len(surfaces),opening_count=len(openings))
    except (ValueError,TypeError,KeyError,IndexError,OverflowError,ZeroDivisionError) as exc:
        errors.append('geometry_readback_error:'+type(exc).__name__+':'+str(exc))
    result.update(status='pass' if not errors else 'fail',errors=sorted(set(errors)))
    return result
