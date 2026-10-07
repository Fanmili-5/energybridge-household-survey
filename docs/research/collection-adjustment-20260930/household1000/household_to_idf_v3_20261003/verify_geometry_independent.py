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
    from geometry_gate import inspect_idf
    results=[]
    for path in sorted((run_dir/'cases').glob('*/building.idf')):
        result=inspect_idf(path.read_text(),json.loads((path.parent/'LAYOUT.json').read_text()))
        result.update(case_id=path.parent.name,issues=result['errors'])
        results.append(result)
    ready={p.parent.name for p in (run_dir/'cases').glob('*/STATUS.json') if json.loads(p.read_text()).get('status')=='idf_ready'}
    preflight=[]
    if not ready:preflight.append('no_admitted_IDF_cases')
    if ready!={r['case_id'] for r in results}:preflight.append('admitted_IDF_artifact_set_mismatch')
    return {'case_root':str(run_dir/'cases'),'checker_uses_writer_grid_or_checks':False,'microdata_read':False,
        'annual_simulation_rerun':False,'expected_admitted_case_count':len(ready),'case_count':len(results),
        'passed_case_count':sum(r['status']=='pass' for r in results),'preflight_errors':preflight,
        'status':'pass' if not preflight and all(r['status']=='pass' for r in results) else 'fail','results':results}

def check_sources(run_dir):
    cache={};results=[]
    source_types={'construction','material','material:nomass','material:airgap','windowmaterial:simpleglazingsystem','windowmaterial:glazing','windowmaterial:gas'}
    for path in sorted((run_dir/'cases').glob('*/ASSEMBLY_BINDING.json')):
        if json.loads((path.parent/'STATUS.json').read_text()).get('status')!='idf_ready':continue
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
    parser.add_argument('--run-dir',type=pathlib.Path,required=True)
    args=parser.parse_args();run_dir=args.run_dir.resolve()
    outputs={'INDEPENDENT_GEOMETRY_CHECK.json':check_geometry(run_dir),'INDEPENDENT_SOURCE_CHECK.json':check_sources(run_dir)}
    for name,result in outputs.items():
        result.update(checker_path=str(pathlib.Path(__file__).resolve()),checker_sha256=sha(__file__))
        (run_dir/name).write_text(json.dumps(result,ensure_ascii=False,indent=2,allow_nan=False)+'\n')
        print(json.dumps({'file':name,'status':result['status'],'case_count':result['case_count'],'passed_case_count':result['passed_case_count']},ensure_ascii=False))
    return 0 if all(r['status']=='pass' for r in outputs.values()) else 1

if __name__=='__main__':raise SystemExit(main())
