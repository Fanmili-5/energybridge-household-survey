"""Independent IDF geometry/source readback; no writer, grid or checker imports.

Run: python3 verify_geometry_independent.py --run-dir final_v5
Writes INDEPENDENT_GEOMETRY_CHECK.json and INDEPENDENT_SOURCE_CHECK.json.
This proves admitted shell artifacts only; it does not rerun EnergyPlus.
"""
import argparse,json,math,collections,pathlib,hashlib
EPS=1e-6

def rows(text):
 text='\n'.join(x.split('!',1)[0] for x in text.splitlines())
 return [[f.strip() for f in obj.split(',')] for obj in text.split(';') if obj.strip()]
def vertices(r):
 start=12 if r[0].lower()=='buildingsurface:detailed' else 10
 return [tuple(map(float,r[i:i+3])) for i in range(start,len(r),3)]
def sub(a,b):return tuple(x-y for x,y in zip(a,b))
def dot(a,b):return sum(x*y for x,y in zip(a,b))
def cross(a,b):return (a[1]*b[2]-a[2]*b[1],a[2]*b[0]-a[0]*b[2],a[0]*b[1]-a[1]*b[0])
def normal(p):
 acc=(0,0,0)
 for a,b in zip(p,p[1:]+p[:1]):acc=tuple(x+y for x,y in zip(acc,cross(a,b)))
 return acc

def q(p):return tuple(round(x,7) for x in p)
def atom_edges(p,allpoints):
 edges=[]
 for a,b in zip(p,p[1:]+p[:1]):
  d=sub(b,a);length2=dot(d,d)
  cuts=[]
  for point in allpoints:
   ap=sub(point,a);t=dot(ap,d)/length2
   residual=sub(ap,tuple(t*x for x in d))
   if -EPS<=t<=1+EPS and math.sqrt(dot(residual,residual))<EPS:cuts.append((max(0,min(1,t)),point))
  cuts=sorted({(round(t,8),q(p)) for t,p in cuts})
  for (_,aa),(_,bb) in zip(cuts,cuts[1:]):
   if aa!=bb:edges.append((aa,bb))
 return edges

def check_geometry(run_dir):
    ROOT=run_dir/'cases'
    results=[]
    for path in sorted(ROOT.glob('*/building.idf')):
     rr=rows(path.read_text());issues=[];status=json.loads((path.parent/'STATUS.json').read_text());layout=json.loads((path.parent/'LAYOUT.json').read_text())
     surfaces={r[1]:r for r in rr if r[0].lower()=='buildingsurface:detailed'}
     openings={r[1]:r for r in rr if r[0].lower()=='fenestrationsurface:detailed'}
     zones={r[1]:r for r in rr if r[0].lower()=='zone'}
     cons={r[1]:r for r in rr if r[0].lower()=='construction'}
     materials={r[1]:r for r in rr if r[0].lower().startswith('material') or r[0].lower().startswith('windowmaterial')}
     names=[(r[0].lower(),r[1].lower()) for r in rr if len(r)>1 and r[0].lower() in ['zone','buildingsurface:detailed','fenestrationsurface:detailed','construction','material','material:nomass','material:airgap','windowmaterial:simpleglazingsystem','windowmaterial:glazing','windowmaterial:gas','schedule:constant','scheduletypelimits']]
     if len(names)!=len(set(names)):issues.append('duplicate_type_name')
     for r in [*surfaces.values(),*openings.values()]:
      if r[3] not in cons:issues.append('missing_construction:'+r[1])
     for key,r in cons.items():
      if any(v not in materials for v in r[2:] if v):issues.append('construction_material_missing:'+key)
     gain_types=[r[0] for r in rr if r[0].lower() in ['people','lights','electricequipment','gasequipment','hotwaterequipment','otherequipment','zonegroup','zonehvac:idealloadsairsystem']]
     if gain_types:issues.append('internal_gain_hvac_or_zonegroup:'+str(gain_types))
     zone_results=[]
     for name,z in zones.items():
      ff=[r for r in surfaces.values() if r[4]==name];polys=[vertices(r) for r in ff]
      allpoints={p for poly in polys for p in poly}
      center=tuple(sum(p[a] for p in allpoints)/len(allpoints) for a in range(3))
      vol=0;edges=collections.Counter();floor_area=0
      for r,p in zip(ff,polys):
       n=normal(p);fc=tuple(sum(v[a] for v in p)/len(p) for a in range(3))
       if dot(n,sub(fc,center))<=EPS:issues.append('face_normal_not_outward:'+r[1])
       for i in range(1,len(p)-1):vol+=dot(p[0],cross(p[i],p[i+1]))/6
       for aa,bb in atom_edges(p,allpoints):edges[(aa,bb)]+=1
       if r[2].lower()=='floor':floor_area+=math.sqrt(dot(n,n))/2
      bad_edges=[(a,b,n,edges[(b,a)]) for (a,b),n in edges.items() if n!=1 or edges[(b,a)]!=1]
      if bad_edges:issues.append('zone_shell_not_closed_or_opposite_edges:'+name)
      if abs(vol-float(z[9]))>1e-5:issues.append('zone_volume_not_geometric:'+name)
      if abs(floor_area-float(z[10]))>1e-5:issues.append('zone_floor_area_not_geometric:'+name)
      if float(z[7])!=1:issues.append('zone_multiplier_not_one:'+name)
      zone_results.append({'zone':name,'closed_oriented_edge_complex':not bad_edges,'edge_atoms':len(edges),'readback_volume_m3':vol,'readback_floor_area_m2':floor_area})
     wall_pairs=door_pairs=0
     for name,r in surfaces.items():
      if r[6].lower()=='surface':
       mate=surfaces.get(r[7]);p=vertices(r)
       if mate is None or mate[7]!=name:issues.append('wall_mate_not_reciprocal:'+name);continue
       mp=vertices(mate)
       if {q(x) for x in p}!={q(x) for x in mp}:issues.append('wall_vertices_not_coincident:'+name)
       if dot(normal(p),normal(mp))>=-EPS:issues.append('wall_mate_normal_not_opposite:'+name)
       if r[3]!=mate[3]:issues.append('wall_mate_construction_mismatch:'+name)
       wall_pairs+=1
     for name,r in openings.items():
      host=surfaces.get(r[4]);p=vertices(r)
      if host is None:issues.append('opening_host_missing:'+name);continue
      hp=vertices(host);n=normal(hp);np=normal(p)
      if max(abs(dot(n,sub(v,hp[0]))) for v in p)>EPS:issues.append('opening_not_coplanar:'+name)
      if dot(n,np)<=EPS:issues.append('opening_host_normal_not_same:'+name)
      if any(min(v[a] for v in p)<min(v[a] for v in hp)-EPS or max(v[a] for v in p)>max(v[a] for v in hp)+EPS for a in range(3)):issues.append('opening_not_inside_rectangular_host:'+name)
      if r[5]:
       mate=openings.get(r[5])
       if mate is None or mate[5]!=name:issues.append('door_mate_not_reciprocal:'+name);continue
       mp=vertices(mate)
       if {q(x) for x in p}!={q(x) for x in mp}:issues.append('door_vertices_not_coincident:'+name)
       if dot(np,normal(mp))>=-EPS:issues.append('door_mate_normal_not_opposite:'+name)
       if r[3]!=mate[3]:issues.append('door_mate_construction_mismatch:'+name)
       if host[7]!=mate[4]:issues.append('door_hosts_not_interzone_mates:'+name)
       door_pairs+=1
     if abs(sum(z['readback_floor_area_m2'] for z in zone_results)-layout['net_proxy_m2'])>1e-5:issues.append('aggregate_area_mismatch')
     results.append({'case_id':path.parent.name,'idf_sha256':hashlib.sha256(path.read_bytes()).hexdigest(),'status':status['status'],'zone_count':len(zones),'reciprocal_wall_pair_count':wall_pairs//2,'reciprocal_door_pair_count':door_pairs//2,'zone_results':zone_results,'issues':sorted(set(issues))})
    ready={p.parent.name for p in ROOT.glob('*/STATUS.json') if json.loads(p.read_text()).get('status')=='idf_ready'}
    artifacts={r['case_id'] for r in results}
    preflight=[]
    if not ready:preflight.append('no_admitted_IDF_cases')
    if ready!=artifacts:preflight.append('admitted_IDF_artifact_set_mismatch')
    return {'case_root':str(ROOT),'checker_uses_writer_grid_or_checks':False,'microdata_read':False,'annual_simulation_rerun':False,'expected_admitted_case_count':len(ready),'case_count':len(results),'passed_case_count':sum(not r['issues'] for r in results),'preflight_errors':preflight,'status':'pass' if not preflight and all(not r['issues'] for r in results) else 'fail','results':results}

def check_sources(run_dir):
    cache={};results=[]
    source_types={'construction','material','material:nomass','material:airgap','windowmaterial:simpleglazingsystem','windowmaterial:glazing','windowmaterial:gas'}
    for path in sorted((run_dir/'cases').glob('*/ASSEMBLY_BINDING.json')):
        binding=json.loads(path.read_text());issues=[]
        parent=pathlib.Path(binding['parent_idf_path']);selected=pathlib.Path(binding['source_idf_path'])
        if sha(parent)!=binding['parent_idf_sha256']:issues.append('parent_hash_mismatch')
        if sha(selected)!=binding['source_idf_sha256']:issues.append('selected_source_hash_mismatch')
        reader=pathlib.Path(binding['source_reader_path'])
        if sha(reader)!=binding['source_reader_sha256']:issues.append('source_reader_hash_mismatch')
        if parent not in cache:cache[parent]={(r[0].lower(),r[1].lower()):r for r in rows(parent.read_text()) if len(r)>1}
        parent_rows=cache[parent];dest=rows((path.parent/'building.idf').read_text());compared=0
        constructions={r[1].lower():r for r in dest if r[0].lower()=='construction'}
        materials={r[1].lower():r for r in dest if r[0].lower().startswith(('material','windowmaterial'))}
        for r in dest:
            if r[0].lower() not in source_types or r[1] in ['Declared_Interior_Door','Declared_Door']:continue
            if parent_rows.get((r[0].lower(),r[1].lower()))!=r:issues.append('source_assembly_row_not_exact:'+r[1])
            compared+=1
        for name,r in constructions.items():
            if any(v.lower() not in materials for v in r[2:] if v):issues.append('construction_material_missing:'+name)
        for r in dest:
            if r[0].lower() in ['buildingsurface:detailed','fenestrationsurface:detailed'] and r[3].lower() not in constructions:issues.append('surface_construction_missing:'+r[1])
        if constructions.get('declared_door')!=['Construction','Declared_Door','Declared_Interior_Door']:issues.append('designed_door_construction_mismatch')
        if materials.get('declared_interior_door')!=['Material:NoMass','Declared_Interior_Door','MediumSmooth','.2','.9','.7','.7']:issues.append('designed_door_panel_mismatch')
        results.append({'case_id':path.parent.name,'idf_sha256':sha(path.parent/'building.idf'),'source_objects_exactly_compared':compared,'issues':sorted(set(issues))})
    ready={p.parent.name for p in (run_dir/'cases').glob('*/STATUS.json') if json.loads(p.read_text()).get('status')=='idf_ready'}
    preflight=[]
    if not ready:preflight.append('no_admitted_IDF_cases')
    if ready!={r['case_id'] for r in results}:preflight.append('admitted_assembly_artifact_set_mismatch')
    return {'scope':'actual selected and parent IDF hashes, exact copied assembly rows, designed door and construction closure; not family calibration','microdata_read':False,'case_count':len(results),'passed_case_count':sum(not r['issues'] for r in results),'preflight_errors':preflight,'status':'pass' if not preflight and all(not r['issues'] for r in results) else 'fail','results':results}

def sha(path):return hashlib.sha256(pathlib.Path(path).read_bytes()).hexdigest()
def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run-dir',type=pathlib.Path,default=pathlib.Path(__file__).resolve().parent/'final_v5')
    args=parser.parse_args();run_dir=args.run_dir.resolve()
    outputs={'INDEPENDENT_GEOMETRY_CHECK.json':check_geometry(run_dir),'INDEPENDENT_SOURCE_CHECK.json':check_sources(run_dir)}
    for name,result in outputs.items():
        result.update(checker_path=str(pathlib.Path(__file__).resolve()),checker_sha256=sha(__file__))
        (run_dir/name).write_text(json.dumps(result,ensure_ascii=False,indent=2,allow_nan=False)+'\n')
        print(json.dumps({'file':name,'status':result['status'],'case_count':result['case_count'],'passed_case_count':result['passed_case_count']},ensure_ascii=False))
    return 0 if all(r['status']=='pass' for r in outputs.values()) else 1

if __name__=='__main__':raise SystemExit(main())
