"""Trace original used window types; admit a declared scalar reference only.

DeST WINDOW.K/SC are retained as instance fields, not mistaken for type U.
Invalid transmission+reflection pairs are quarantined. The .87 conversion
requires a common whole-window/glazing boundary; that boundary is not proved
for native models, so outputs remain parameter reference scenarios.
"""
import concurrent.futures,json,sys,hashlib
from pathlib import Path
OUT=Path(__file__).resolve().parent.parent;BASE=OUT.parent;V8=BASE/'household_housing_evidence_20261006'
sys.path[:0]=json.loads((BASE/'idf_joint_production_20261005/RUNTIME.json').read_text())['stable_PYTHONPATH'].split(':')
from access_parser_c import AccessParser
def rows(t):return [dict(zip(t,v)) for v in zip(*t.values())]
def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def read(p):return json.loads(p.read_text())
def extract(r):
 assert sha(r['source_path'])==r['source_sha256']
 db=AccessParser(r['source_path']);ww=rows(db.parse_table('WINDOW'));tt={t['ID']:t for t in rows(db.parse_table('WINDOW_TYPE_DATA'))};used={w['TYPE'] for w in ww};bundle=read(V8/'assemblies'/(r['model_key']+'.json'));result=[]
 for tid in sorted(used):
  t=tt[tid];u=float(t['K']);sc=float(t['SC']);vt=float(t['LIGHT_TRANS_RATIO']);assert u>0 and 0<=sc<=1/.87 and 0<=vt<=1
  tx=float(t['ENERGY_TRANS_RATIO']);rx=float(t['ENERGY_REFLECT_RATIO']);vr=float(t['LIGHT_REFLECT_RATIO'])
  instances=[w for w in ww if w['TYPE']==tid]
  result.append({'native_type_ID':tid,'native_type_NAME':t['NAME'],'source_window_count':len(instances),'native_type_U_W_m2K':u,
   'native_type_SC':sc,'native_visible_transmittance':vt,'native_instance_K_values':sorted({w['K'] for w in instances}),
   'native_instance_SC_values':sorted({w['SC'] for w in instances}),
   'reference_SHGC_SC_times0_87':sc*.87,'alternative_reference_SC_times0_86':sc*.86,
   'native_solar_trans_reflect_sum':tx+rx,'native_visible_trans_reflect_sum':vt+vr,
   'unphysical_optical_pair_fields_quarantined':tx+rx>1+1e-6 or vt+vr>1+1e-6,
   'native_frame_vs_glass_boundary_verified':False,'native_angular_or_spectral_equivalence_verified':False})
 converted=bundle.get('converted_glazing_reference_U_SHGC_visible');first=result[0]
 comparison=None if converted is None else {'converted_U_SHGC_visible':converted,
  'max_abs_difference_to_declared_scalar_reference':max(abs(a-b) for a,b in zip(converted,[first['native_type_U_W_m2K'],first['reference_SHGC_SC_times0_87'],first['native_visible_transmittance']]))}
 assert len(result)==1,'multiple_native_used_types_require_explicit_mapping'
 # For Lasa, use its original used native type instead of the old held-Beijing
 # glazing. This is a new bundle; sealed old files stay untouched.
 mat=r['model_key']+'_scalar_window_reference';name=r['model_key']+'_window_reference'
 output={**bundle,'names':{**bundle['names'],'window':name},
  'rows':[row for row in bundle['rows'] if row[0]!='WindowMaterial:SimpleGlazingSystem' and row[1]!=bundle['names']['window']]+[
   ['WindowMaterial:SimpleGlazingSystem',mat,str(first['native_type_U_W_m2K']),str(first['reference_SHGC_SC_times0_87']),str(first['native_visible_transmittance'])],['Construction',name,mat]],
  'glazing_policy':'original_used_native_type_U_SC_visible_to_declared0_87_scalar_reference;no_optical_equivalence_claim',
  'glazing_provenance':result,'glazing_and_absorptance_are_reference_model_parameters_not_measured_home_properties':True}
 p=OUT/'assemblies'/(r['model_key']+'.json');p.write_text(json.dumps(output,ensure_ascii=False,indent=2,allow_nan=False)+'\n')
 return {'model_key':r['model_key'],'native_source_path':r['source_path'],'native_source_sha256':r['source_sha256'],
  'native_used_type_records':result,'previous_converted_reference_comparison':comparison,'new_bundle_path':str(p.relative_to(OUT)),
  'new_bundle_sha256':sha(p),'source_boundary_equivalence_admitted':False}
def main():
 if (OUT/'PACKAGE_MANIFEST.json').exists():raise SystemExit('sealed')
 (OUT/'assemblies').mkdir(exist_ok=True);regs=read(V8/'NATIVE_REFERENCE_REGISTRY.json')['models']+read(V8/'ADDITIONAL_REGIONAL_REFERENCES.json')['models']
 with concurrent.futures.ThreadPoolExecutor(4) as pool:results=list(pool.map(extract,regs))
 comparisons=[r['previous_converted_reference_comparison'] for r in results if r['previous_converted_reference_comparison'] is not None]
 report={'models':results,'original_used_native_types_traced':len(results),'converted_scalar_comparisons':len(comparisons),
   'max_abs_converted_scalar_difference':max(r['max_abs_difference_to_declared_scalar_reference'] for r in comparisons),
   'models_with_quarantined_optical_pairs':sum(any(t['unphysical_optical_pair_fields_quarantined'] for t in r['native_used_type_records']) for r in results),
   'Lasa_native_U_replaces_Beijing_held_glazing_in_new_reference_bundles_only':True,
   'native_physical_radiative_equivalence_or_empirical_stock_validation':False,
   'scalar_conversion_authority':'LBNL Home Energy Saver equation2: whole-window SC=SHGC/0.87',
   'authority_URL':'https://hes-documentation.lbl.gov/calculation-methodology/calculation-of-energy-consumption/heating-and-cooling-calculation/doe2-inputs-assumptions-and-calculations/the-doe2-model',
   '0_86_counter_reference':'LBNL WINDOW4 discusses reference-spectrum convention change;not an empirical confidence interval'}
 (OUT/'GLAZING_PROVENANCE.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')
 print(json.dumps({k:v for k,v in report.items() if k!='models'},ensure_ascii=False))
if __name__=='__main__':main()
