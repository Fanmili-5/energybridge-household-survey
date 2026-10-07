"""Use the correct native (KIND,STRUCT_ID) namespace for roof/ground/midfloor.
The pinned converter maps3=roof,4=ground,5=middle floor. Old sealed stage's
kind4-labelled middle-floor test is corrected here, not silently rewritten.
"""
import concurrent.futures,copy
from common import *
from access_parser_c import AccessParser
MAP={'roof':(3,'SYS_ROOF'),'ground':(4,'SYS_GROUNDFLOOR'),'middle':(5,'SYS_MIDDLEFLOOR')}
def rows(t):return [dict(zip(t,v)) for v in zip(*t.values())]
def extract(r):
 assert sha(r['source_path'])==r['source_sha256'];db=AccessParser(r['source_path']);enc=rows(db.parse_table('MAIN_ENCLOSURE'));mats={m['MATERIAL_ID']:m for m in rows(db.parse_table('SYS_MATERIAL'))}
 a=read(V9/'assemblies'/(r['model_key']+'.json'));reports=[]
 for kind,(code,table) in MAP.items():
  ids={e['CONSTRUCTION'] for e in enc if e['KIND']==code};native=rows(db.parse_table(table+'_MATERIAL'));labels={x['STRUCT_ID']:x for x in rows(db.parse_table(table))}
  assert len(ids)==1,(r['model_key'],kind,ids);sid=next(iter(ids));layers=sorted([x for x in native if x['STRUCT_ID']==sid],key=lambda x:x['LAYER_NO']);assert layers
  vectors=[];names=[]
  for i,l in enumerate(layers):
   m=mats[l['MATERIAL_ID']];v=[l['LENGTH']/1000,m['CONDUCTIVITY'],m['DENSITY'],m['SPECIFIC_HEAT']];assert min(v)>0;vectors.append(v)
   mn=r['model_key']+'_'+kind+'_layer'+str(i);names.append(mn)
   if kind!='middle':a['rows'].append(['Material',mn,'MediumRough',*map(str,v),'.9','.7','.7'])
  name=r['model_key']+'_'+kind+'_native_reference'
  if kind!='middle':a['rows'].append(['Construction',name,*names]);a['names'][kind]=name
  reports.append({'kind':kind,'native_enclosure_KIND':code,'native_material_table':table+'_MATERIAL','native_used_struct_ID':sid,
   'native_used_enclosure_count':sum(e['KIND']==code and e['CONSTRUCTION']==sid for e in enc),
   'native_construction_name':labels[sid]['CNAME'],'native_material_IDs':[l['MATERIAL_ID'] for l in layers],
   'native_material_names':[mats[l['MATERIAL_ID']]['CNAME'] for l in layers],'numeric_vectors_t_lambda_rho_cp':vectors,
   'series_R_without_films_m2K_W':sum(v[0]/v[1] for v in vectors),'thickness_m':sum(v[0] for v in vectors)})
 previous=read(V9/'assemblies'/(r['model_key']+'.json'))['opaque_layer_provenance'][-1]
 # Converted middle-floor numeric vectors retain their own evidence. Recheck
 # whether they equal the actually used KIND5 construction, not a KIND4 ID.
 oldvectors=previous['layer_numeric_vectors_t_lambda_rho_cp'];actual=next(x for x in reports if x['kind']=='middle')['numeric_vectors_t_lambda_rho_cp']
 delta=max(abs(x-y)/max(abs(y),1e-12) for a,b in zip(oldvectors,actual) for x,y in zip(a,b)) if len(oldvectors)==len(actual) else None
 a['horizontal_native_provenance']=reports;a['roof_and_ground_used_native_numeric_reference_not_asbuilt']=True
 a['middle_floor_thermal_policy']='retain explicitly declared V7 RC reference for adiabatic midfloor;never claim native fibreboard is RC'
 p=OUT/'assemblies'/(r['model_key']+'.json');save(p,a)
 return {'model_key':r['model_key'],'native_path':r['source_path'],'native_sha256':r['source_sha256'],'bundle_path':str(p.relative_to(OUT)),'bundle_sha256':sha(p),
  'horizontal_records':reports,'previous_converted_middle_numeric_difference_to_actual_kind5':delta,
  'previous_kind4_middle_label_was_wrong':True,'previous_numeric_equality_not_sufficient_namespace_proof':True}
def main():
 guard();(OUT/'assemblies').mkdir(exist_ok=True);refs=read(V8/'NATIVE_REFERENCE_REGISTRY.json')['models']+read(V8/'ADDITIONAL_REGIONAL_REFERENCES.json')['models']
 with concurrent.futures.ThreadPoolExecutor(4) as pool:items=list(pool.map(extract,refs))
 save(OUT/'HORIZONTAL_SOURCE_ADMISSION.json',{'models':items,'native_models_checked':len(items),'actual_kind3_4_5_constructions_checked':len(items)*3,
  'maximum_previous_middle_numeric_relative_difference':max(r['previous_converted_middle_numeric_difference_to_actual_kind5'] or 0 for r in items),
  'previous_kind_namespace_error_corrected_only_in_new_package':True,
  'kind_mapping_primary_evidence':'raw/destep_R_source/conv-const.R:154-170;commit1d93a51c5dd6a48e0a108d9646f00a496f23d1ec',
  'previous_middle_layer_RC_semantic_rejection_and_declared_RC_reference_retained':True,'actual_house_stock_or_code_compliance_observed':False})
 print({'models':len(items),'horizontal_records':len(items)*3,'previous_kind4_label_corrected_to_kind5':True})
if __name__=='__main__':main()
