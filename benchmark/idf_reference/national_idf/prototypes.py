"""Original model audit, geometry-preserving transforms and explicit unit extraction."""
from __future__ import annotations

import copy
import math
from collections import Counter
from pathlib import Path
import numpy as np
from shapely.geometry import Polygon

from .common import require, digest, sha, locked
from .idf import parse, objects, Fields, one


def table(db, name):
    t = db.parse_table(name)
    require(len({len(v) for v in t.values()}) <= 1, "NATIVE_COLUMN_LENGTH", name)
    return [dict(zip(t, v)) for v in zip(*t.values())] if t else []


def native_summary(path: Path) -> dict:
    from access_parser_c import AccessParser
    db = AccessParser(str(path))
    env = table(db,"ENVIRONMENT")
    require(len(env)==1,"NATIVE_ENVIRONMENT_CARDINALITY")
    types = {r["ID"]:r["NAME"] for r in table(db,"ROOM_TYPE_DATA")}
    rooms = table(db,"ROOM")
    return {"source_sha256":sha(path),"environment":env[0],
      "rooms":[{k:r[k]for k in ("ID","NAME","OF_STOREY","TYPE","AREA","VOLUME")}
               | {"function":types.get(r["TYPE"],"unknown")}for r in rooms],
      "storeys":table(db,"STOREY"),
      "windows":len(table(db,"WINDOW")),
      "geometry_fingerprint":digest({n:table(db,n)for n in
         ("POINT","LOOP_POINT","GEOMETRY","PLANE")}),
      "source_assemblies":used_assemblies(db)}


def used_assemblies(db):
    enc = table(db,"MAIN_ENCLOSURE")
    mats = {r["MATERIAL_ID"]:r for r in table(db,"SYS_MATERIAL")}
    result=[]
    for kind,t in [(1,"SYS_OUTWALL"),(2,"SYS_INWALL"),(3,"SYS_ROOF"),
                   (4,"SYS_GROUNDFLOOR"),(5,"SYS_MIDDLEFLOOR")]:
        layers=table(db,t+"_MATERIAL")
        for sid in sorted({r["CONSTRUCTION"]for r in enc if r["KIND"]==kind}):
            ls=sorted((r for r in layers if r["STRUCT_ID"]==sid),key=lambda r:r["LAYER_NO"])
            require(bool(ls),"SOURCE_CONSTRUCTION_LAYERS_MISSING",[kind,sid])
            vectors=[[r['LENGTH']/1000,mats[r['MATERIAL_ID']]['CONDUCTIVITY'],
                      mats[r['MATERIAL_ID']]['DENSITY'],mats[r['MATERIAL_ID']]['SPECIFIC_HEAT']]
                     for r in ls]
            require(all(all(math.isfinite(x) and x>0 for x in v)for v in vectors),
                    "NATIVE_MATERIAL_RANGE")
            result.append({"kind":kind,"id":sid,"layers_m_k_rho_cp":vectors,
              "R_without_films_m2K_W":sum(v[0]/v[1]for v in vectors),
              "heat_capacity_J_m2K":sum(v[0]*v[2]*v[3]for v in vectors)})
    return result


def vertices(row):
    start = 12 if row[0].lower()=="buildingsurface:detailed" else 10
    require((len(row)-start)%3==0,"VERTEX_FIELDS",row[1])
    v = np.array([float(x) for x in row[start:]],float).reshape(-1,3)
    require(len(v)>=3 and np.isfinite(v).all(),"VERTEX_RANGE",row[1])
    require(int(row[start-1])==len(v),"VERTEX_COUNT",row[1])
    return v


def area(v):
    return float(np.linalg.norm(np.cross(v,np.roll(v,-1,axis=0)).sum(axis=0))/2)


def geometry_audit(rows):
    zones = {r[1]:r for r in objects(rows,"Zone")}
    surfaces = {r[1]:r for r in objects(rows,"BuildingSurface:Detailed")}
    require(len(surfaces)==len(objects(rows,"BuildingSurface:Detailed")),"DUPLICATE_SURFACE")
    errors=[]; window_area=0.; outside_area=Counter(); volume={}
    for name,z in zones.items():
        faces=[r for r in surfaces.values()if r[4]==name]
        vs=[vertices(f)for f in faces]
        normal_sum=np.sum([np.cross(v,np.roll(v,-1,axis=0)).sum(axis=0)/2 for v in vs],axis=0)
        scale=max(1,sum(area(v)for v in vs))
        if np.linalg.norm(normal_sum)>1e-5*scale:errors.append(["zone_not_closed",name])
        # Independent signed tetrahedral volume, translation invariant for closed polyhedra.
        vv=0.
        for v in vs:
            for i in range(1,len(v)-1):vv+=float(np.dot(v[0],np.cross(v[i],v[i+1]))/6)
        volume[name]=abs(vv)
        if len(z)>9 and str(z[9]).lower() not in ("autocalculate",""):
            if abs(abs(vv)-float(z[9]))>max(.05,abs(vv)*.005):errors.append(["zone_volume",name,abs(vv),z[9]])
    for name,r in surfaces.items():
        if r[4]not in zones:errors.append(["surface_zone_missing",name])
        a=area(vertices(r))
        if a<=1e-9:errors.append(["surface_area",name])
        if r[6].lower()=="outdoors":outside_area[r[2]]+=a
        if r[6].lower()=="surface":
            other=surfaces.get(r[7])
            if not other or other[7]!=name:errors.append(["peer_not_reciprocal",name])
            elif abs(area(vertices(other))-a)>max(.001,a*.001):errors.append(["peer_area",name])
    for r in objects(rows,"FenestrationSurface:Detailed"):
        host=surfaces.get(r[4])
        if not host:errors.append(["window_host_missing",r[1]]);continue
        v,h=vertices(r),vertices(host)
        n=np.cross(h[1]-h[0],h[2]-h[0]);n/=np.linalg.norm(n)
        if max(abs((v-h[0])@n))>.001:errors.append(["window_not_coplanar",r[1]])
        ax=int(np.argmax(abs(n)));hp=Polygon(np.delete(h,ax,axis=1));wp=Polygon(np.delete(v,ax,axis=1))
        if not hp.buffer(.001).covers(wp):errors.append(["window_outside_host",r[1]])
        window_area+=area(v)
    return {"passed":not errors,"errors":errors,"zones":len(zones),
      "opaque_surfaces":len(surfaces),"window_count":len(objects(rows,"FenestrationSurface:Detailed")),
      "window_area_m2":window_area,"external_surface_area_m2":dict(outside_area),
      "zone_volume_from_faces_m3":volume,"boundary_counts":dict(Counter(r[6]for r in surfaces.values()))}


def audit_conversion(native: Path, idf: Path) -> dict:
    ns=native_summary(native);rs=parse(idf.read_text());zs={r[1]:r for r in objects(rs,"Zone")}
    errors=[]
    for r in ns["rooms"]:
        z=zs.get(r["NAME"])
        if z is None:errors.append(["native_room_missing",r['NAME']]);continue
        if abs(float(z[10])-r["AREA"])>.001:errors.append(["native_floor_area",r['NAME']])
        if abs(float(z[9])-r["VOLUME"])>.01:errors.append(["native_volume",r['NAME']])
    if len(zs)!=len(ns["rooms"]):errors.append(["native_room_count"])
    if len(objects(rs,"FenestrationSurface:Detailed"))!=ns['windows']:
        errors.append(["native_window_count"])
    materials={r[1]:r for r in objects(rs,"Material")}; cs=objects(rs,"Construction")
    material_checks=[]
    for a in ns["source_assemblies"]:
        matching=[]
        for c in cs:
            if not all(n in materials for n in c[2:]):continue
            vec=[[float(materials[n][i])for i in (3,4,5,6)]for n in c[2:]]
            source=a['layers_m_k_rho_cp']
            if len(vec)==len(source) and np.allclose(vec,source,rtol=1e-5,atol=1e-7):matching.append(c[1])
        material_checks.append({"kind":a['kind'],"source_id":a['id'],"matched_constructions":matching})
        if not matching:errors.append(["native_layer_vector_not_preserved",a['kind'],a['id']])
    g=geometry_audit(rs)
    return {"schema":"national_idf.prototype_conversion.v1","source":ns,
       "idf_sha256":sha(idf),"passed":not errors and g['passed'],"errors":errors,
       "geometry":g,"material_checks":material_checks,
       "native_energy_output_comparison":"not_available",
       "glazing_conversion":"SC_to_SHGC_0.87_approximation;angular_and_frame_equivalence_not_validated",
       "converter":"destep_1d93a51c5dd6a48e0a108d9646f00a496f23d1ec",
       "empirical_calibration":False}


def scale_geometry(rows, factor, admitted_range=(1.,1.)):
    require(admitted_range[0]<=factor<=admitted_range[1],"GEOMETRY_SCALE_OUTSIDE_SOURCE_DOMAIN")
    rs=copy.deepcopy(rows)
    if factor == 1: return rs
    for r in rs:
        if r[0].lower() in ("buildingsurface:detailed","fenestrationsurface:detailed"):
            start=12 if r[0].lower()=="buildingsurface:detailed" else 10
            for i in range(start,len(r),3):r[i]=float(r[i])*factor;r[i+1]=float(r[i+1])*factor
        elif r[0].lower()=="zone":
            r[3]=float(r[3])*factor;r[4]=float(r[4])*factor
            for i in (9,10):
                if r[i]not in ("","Autocalculate"):r[i]=float(r[i])*factor**2
    return rs


def extract_unit(rows, selected, fields: Fields, neighbor_schedule="neighbor_temperature",ground_model=None):
    """Preserve source polygons; explicitly prescribed neighbors replace removed zones.

    No floor is made adiabatic by default. Ground requires a separate ground model.
    Unit membership is an input declaration, never inferred from occupant traits.
    """
    selected=set(selected);zones={r[1]:r for r in objects(rows,"Zone")}
    require(selected<=zones.keys() and selected,"UNIT_ZONES_MISSING")
    keep_types={"Version","Building","GlobalGeometryRules","Material","Material:NoMass",
      "Material:AirGap","WindowMaterial:SimpleGlazingSystem","WindowMaterial:Glazing",
      "WindowMaterial:Gas","Construction","Shading:Building:Detailed","Shading:Site:Detailed"}
    out=[copy.deepcopy(r)for r in rows if r[0]in keep_types]
    for name in sorted(selected):
        z=copy.deepcopy(zones[name]);fields.set(z,"multiplier",1);out.append(z)
    all_surfaces={r[1]:r for r in objects(rows,"BuildingSurface:Detailed")}
    selected_surfaces={n:r for n,r in all_surfaces.items()if r[4]in selected}
    boundary_changes=[]
    for r in selected_surfaces.values():
        r=copy.deepcopy(r)
        if r[6].lower()=="ground":
            require(ground_model and ground_model.get('kind')=='prescribed_under_slab_monthly',
                    'GROUND_MODEL_REQUIRED','generic_EPWs_2m_soil_temperature_is_not_under_slab_temperature')
            require(len(ground_model.get('temperature_C',[]))==12 and bool(ground_model.get('basis'))
                    and all(-30<=t<=50 for t in ground_model['temperature_C']),'GROUND_BOUNDARY_INPUT')
        peer=all_surfaces.get(r[7])if r[6].lower()=='surface'else None
        periodic_self=peer is not None and peer[4]==r[4]
        if r[6].lower()=="surface" and (r[7] not in selected_surfaces or periodic_self):
            other=all_surfaces.get(r[7]);require(other is not None,"SOURCE_PEER_MISSING",r[1])
            boundary_changes.append({"surface":r[1],"source_neighbor_zone":other[4],
               "source_boundary":r[6],"new_boundary":"prescribed_neighbor_temperature",
               "source_surface_type":r[2],'source_same_zone_periodic_boundary_removed':periodic_self})
            r[6],r[7],r[8],r[9]="OtherSideCoefficients","declared_neighbor","NoSun","NoWind"
        out.append(r)
    for r in objects(rows,"FenestrationSurface:Detailed"):
        if r[4]in selected_surfaces:
            require(not r[5] or any(x[1]==r[5]and x[4]in selected_surfaces for x in objects(rows,"FenestrationSurface:Detailed")),
                    "INTERIOR_WINDOW_PEER_REMOVED",r[1])
            out.append(copy.deepcopy(r))
    out.append(fields.obj("SurfaceProperty:OtherSideCoefficients",name="declared_neighbor",
        combined_convective_radiative_film_coefficient=3,constant_temperature=20,
        constant_temperature_coefficient=1,external_dry_bulb_temperature_coefficient=0,
        ground_temperature_coefficient=0,wind_speed_coefficient=0,
        zone_air_temperature_coefficient=0,constant_temperature_schedule_name=neighbor_schedule))
    if ground_model:
        out.append(['Site:GroundTemperature:BuildingSurface',*ground_model['temperature_C']])
    g=geometry_audit(out);require(g['passed'],"EXTRACTED_UNIT_GEOMETRY",g['errors'])
    return out,{"geometry":g,"source_zone_names":sorted(selected),
      "source_topology_and_polygons_preserved":True,"zone_multiplier_reset_to_one":True,
      "boundary_changes":boundary_changes,"neighbor_model":"prescribed_neighbor_air_temperature_and3W_m2K_film;not_observed_neighbors",
      'ground_model':ground_model,
      "source_household_membership_identified":False}


def match(request, records):
    candidates=[r for r in records if all(r.get(k)==request.get(k)for k in
                 ("city","building_type","epoch","floor_position"))]
    available=[r for r in candidates if r.get("conversion_admitted")]
    return {"status":"matched_source_prototype" if available else "unsupported_prototype",
            "selected_id":sorted(r['id']for r in available)[0]if available else None,
            "candidate_ids":[r['id']for r in candidates],"nearest_epoch_relabelled_as_renovation":False}
