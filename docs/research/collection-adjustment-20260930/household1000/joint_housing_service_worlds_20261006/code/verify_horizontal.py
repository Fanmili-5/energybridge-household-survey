"""Re-read primary Access data; compare namespaces and all exported layers.
Does not import horizontal source extraction or the reference IDF generator.
This tests the transformation, not as-built orientation, structure or energy.
"""
import concurrent.futures,math
from common import *
from access_parser_c import AccessParser
def table(db,name):
 t=db.parse_table(name);return [dict(zip(t,v)) for v in zip(*t.values())]
def check(item):
 db=AccessParser(item['native_path']);enc=table(db,'MAIN_ENCLOSURE');mats={m['MATERIAL_ID']:m for m in table(db,'SYS_MATERIAL')};issues=[]
 for key,kind,tname in [('roof',3,'SYS_ROOF'),('ground',4,'SYS_GROUNDFLOOR'),('middle',5,'SYS_MIDDLEFLOOR')]:
  admitted=next(r for r in item['horizontal_records'] if r['kind']==key);ids={e['CONSTRUCTION'] for e in enc if e['KIND']==kind}
  if ids!={admitted['native_used_struct_ID']}:issues.append(key+'_namespace')
  layers=sorted([l for l in table(db,tname+'_MATERIAL') if l['STRUCT_ID']==admitted['native_used_struct_ID']],key=lambda l:l['LAYER_NO'])
  numeric=[[l['LENGTH']/1000,mats[l['MATERIAL_ID']]['CONDUCTIVITY'],mats[l['MATERIAL_ID']]['DENSITY'],mats[l['MATERIAL_ID']]['SPECIFIC_HEAT']] for l in layers]
  if numeric!=admitted['numeric_vectors_t_lambda_rho_cp']:issues.append(key+'_primary_numeric_vectors')
  if [l['MATERIAL_ID'] for l in layers]!=admitted['native_material_IDs']:issues.append(key+'_material_IDs')
  if key!='middle':
   a=read(OUT/item['bundle_path']);cons=next(z for z in a['rows'] if z[0]=='Construction' and z[1]==a['names'][key]);mm={z[1]:z for z in a['rows'] if z[0]=='Material'}
   actual=[[float(v) for v in mm[n][3:7]] for n in cons[2:]]
   if actual!=numeric:issues.append(key+'_compiled_numeric_order')
 return {'model_key':item['model_key'],'issues':issues}
def main():
 guard();items=read(OUT/'HORIZONTAL_SOURCE_ADMISSION.json')['models']
 with concurrent.futures.ThreadPoolExecutor(4) as pool:result=list(pool.map(check,items))
 fail=[r for r in result if r['issues']];assert not fail,fail
 save(OUT/'INDEPENDENT_HORIZONTAL_VERIFICATION.json',{'native_models_checked':len(items),'kind_namespace_layer_records_checked':len(items)*3,'failures':fail,
  'primary_Access_re_read_independently':True,'asbuilt_layer_orientation_frame_compliance_or_energy_not_admitted':True,
  'orientation_reference':'stored ascending LAYER_NO;converter also supports SIDE1 reversal;synthetic surface orientation not recovered from original native geometry'})
 print({'models':len(items),'layer_records':len(items)*3,'failures':len(fail)})
if __name__=='__main__':main()
