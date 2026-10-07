"""Admit opaque reference properties by original Access numeric layer match.

Each source stays an author-designed reference model. Matching numeric
conversion properties is not stock prevalence, construction-code compliance,
glazing equivalence, or empirically measured heat transfer.
"""
import collections,hashlib,json,re,sys
from pathlib import Path
OUT=Path(__file__).resolve().parent.parent;BASE=OUT.parent
sys.path[:0]=json.loads((BASE/'idf_joint_production_20261005/RUNTIME.json').read_text())['stable_PYTHONPATH'].split(':')
from access_parser_c import AccessParser

def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def rows(table):return [dict(zip(table,v)) for v in zip(*table.values())]
def parse(p):return [[v.strip() for v in q.split(',')] for q in re.sub(r'!.*','',Path(p).read_text()).split(';') if q.strip()]
def extract(registry):
    rr=parse(registry['conversion_path']);mats={r[1]:r for r in rr if r[0]=='Material'}
    cons={r[1]:r for r in rr if r[0]=='Construction' and '[Reverse]' not in r[1]}
    names={kind:next(n for n in cons if n.startswith(prefix)) for kind,prefix in [('exterior','ExtWall'),('interior','IntWall'),('floor','Ceiling')]}
    simple={r[1]:r for r in rr if r[0]=='WindowMaterial:SimpleGlazingSystem'}
    names['window']=next(n for n in cons if len(cons[n])==3 and cons[n][2] in simple)
    db=AccessParser(registry['source_path']);native={r['MATERIAL_ID']:r for r in rows(db.parse_table('SYS_MATERIAL'))};reports=[]
    enclosures=rows(db.parse_table('MAIN_ENCLOSURE'))
    used_constructions={r[3] for r in rr if r[0] in ['BuildingSurface:Detailed','FenestrationSurface:Detailed']}
    assert set(names.values())<=used_constructions,'selected_source_construction_not_used_in_converted_model'
    for kind,table in [('exterior','SYS_OUTWALL_MATERIAL'),('interior','SYS_INWALL_MATERIAL'),('floor','SYS_MIDDLEFLOOR_MATERIAL')]:
        vectors=[tuple(float(mats[n][j]) for j in [3,4,5,6]) for n in cons[names[kind]][2:]]
        table=rows(db.parse_table(table));matches=[]
        for sid in sorted({r['STRUCT_ID'] for r in table}):
            native_rows=sorted([r for r in table if r['STRUCT_ID']==sid],key=lambda r:r['LAYER_NO'])
            if len(native_rows)!=len(vectors):continue
            data=[(r['LENGTH']/1000,native[r['MATERIAL_ID']]['CONDUCTIVITY'],native[r['MATERIAL_ID']]['DENSITY'],native[r['MATERIAL_ID']]['SPECIFIC_HEAT']) for r in native_rows]
            for order,values in [('original',data),('reversed',data[::-1])]:
                error=max(abs(a-b)/max(abs(b),1e-12) for x,y in zip(vectors,values) for a,b in zip(x,y))
                if error<1e-6:matches.append({'native_struct_id':sid,'order':order,'material_ids':[r['MATERIAL_ID'] for r in native_rows],'max_relative_difference':error})
        if not matches:raise ValueError('source_layer_match_missing:'+registry['model_key']+':'+kind)
        native_kind={'exterior':1,'interior':2,'floor':4}[kind];used_native_ids={e['CONSTRUCTION'] for e in enclosures if e['KIND']==native_kind}
        used_matches=[m for m in matches if m['native_struct_id'] in used_native_ids]
        if not used_matches:raise ValueError('matched_library_construction_not_used_by_original_enclosures:'+registry['model_key']+':'+kind)
        reports.append({'kind':kind,'converted_construction':names[kind],'layer_numeric_vectors_t_lambda_rho_cp':vectors,'native_matches':matches,
          'native_actual_enclosure_kind_code':native_kind,'matched_actual_enclosure_struct_ids':[m['native_struct_id'] for m in used_matches],
          'thickness_m':sum(v[0] for v in vectors),'series_R_without_surface_films_m2K_W':sum(v[0]/v[1] for v in vectors),
          'layer_semantic_names_from_native':[native[mid]['CNAME'] for mid in matches[0]['material_ids']]})
    material_rows=[r for r in rr if r[0] in ['Material','WindowMaterial:SimpleGlazingSystem','Construction']]
    return {'model_key':registry['model_key'],'rows':material_rows,'names':names,
      'source_path':registry['source_path'],'source_sha256':registry['source_sha256'],'source_conversion_sha256':registry['conversion_sha256'],
      'exterior_thickness_m':reports[0]['thickness_m'],'interior_thickness_m':reports[1]['thickness_m'],
      'climate_identity':registry['model_key']+'_author_reference_not_observed_generated_home',
      'opaque_layer_provenance':reports,'converted_glazing_reference_U_SHGC_visible':list(map(float,simple[cons[names['window']][2]][2:])),
      'simple_glazing_equivalence_to_detailed_native_window_validated':False,
      'native_floor_name_does_not_authorize_RC_identity':True,'floor_policy_for_new_pilot':'same_explicit_RC_reference_as_V7_not_automatic_native_floor_identity'}

def main():
    from evidence_guard import ensure_unsealed
    ensure_unsealed(OUT)
    regs=json.loads((OUT/'NATIVE_REFERENCE_REGISTRY.json').read_text())['models'];folder=OUT/'assemblies';folder.mkdir(exist_ok=True);items=[]
    for r in regs:
        d=extract(r);path=folder/(r['model_key']+'.json');path.write_text(json.dumps(d,ensure_ascii=False,indent=2,allow_nan=False)+'\n')
        items.append({'model_key':r['model_key'],'bundle_path':str(path.relative_to(OUT)),'sha256':sha(path),
          'source_sha256':d['source_sha256'],'opaque_constructions_matched':3,
          'source_reference_thickness_m':{'exterior':d['exterior_thickness_m'],'interior':d['interior_thickness_m']},
          'exterior_series_R_without_films':d['opaque_layer_provenance'][0]['series_R_without_surface_films_m2K_W'],
          'simple_glazing_equivalence_validated':False})
    report={'models':items,'original_native_models_numeric_verified':len(items),'opaque_construction_provenance_comparisons':3*len(items),
      'actual_household_stock_or_empirical_thermal_admission':False,'glazing_semantic_fidelity_remaining_gap':True}
    (OUT/'REGIONAL_ASSEMBLY_ADMISSION.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')
    print(json.dumps({k:v for k,v in report.items() if k!='models'},ensure_ascii=False))
if __name__=='__main__':main()
