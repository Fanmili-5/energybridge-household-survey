"""Inspect actual and room-type-reference gains; do not assume either measured."""
import concurrent.futures,collections
from common import *
from access_parser_c import AccessParser
def table(db,n):
 t=db.parse_table(n);return [dict(zip(t,v)) for v in zip(*t.values())]
def audit(r):
 assert sha(r['source_path'])==r['source_sha256'];db=AccessParser(r['source_path']);room={x['ID']:x for x in table(db,'ROOM')};types={x['ID']:x for x in table(db,'ROOM_TYPE_DATA')};result={}
 for name,keys in [('LIGHT_GAINS',['MAXPOWER','MINPOWER','PER_AREA','HEAT_RATE','DIST_MODE']),('EQUIPMENT_GAINS',['MAXPOWER','MINPOWER','PER_AREA','MAX_HUM','MIN_HUM','DIST_MODE']),('OCCUPANT_GAINS',['MAXNUMBER','MINNUMBER','PER_AREA','HEAT_PER_PERSON','DAMP_PER_PERSON','MIN_REQUIRE_FRESH_AIR','DIST_MODE'])]:
  data=table(db,name);vectors=collections.Counter(tuple(x[k] for k in keys) for x in data);bytype=collections.defaultdict(list)
  for x in data:bytype[types[room[x['OF_ROOM']]['TYPE']]['NAME']].append(x)
  result[name]={'fields':keys,'vectors':[{'values':list(k),'instances':v} for k,v in vectors.items()],'one_identical_vector_across_all_rooms':len(vectors)==1,'room_types':{k:{'count':len(v),'first_actual_row':v[0]} for k,v in bytype.items()}}
 return {'model_key':r['model_key'],'source_path':r['source_path'],'source_sha256':r['source_sha256'],'gains':result,'room_type_reference_parameters':list(types.values()),'uniformity_does_not_prove_default_origin_or_measurement':True,'admission':'software_reference_parameter_only;publishedresidentialparameter orindependentobservation needed before empirical transport'}
def main():
 guard();refs=read(V8/'NATIVE_REFERENCE_REGISTRY.json')['models']+read(V8/'ADDITIONAL_REGIONAL_REFERENCES.json')['models']
 with concurrent.futures.ThreadPoolExecutor(4) as pool:rows=list(pool.map(audit,refs))
 counts={k:sum(x['gains'][k]['one_identical_vector_across_all_rooms'] for x in rows) for k in ['LIGHT_GAINS','EQUIPMENT_GAINS','OCCUPANT_GAINS']};save(OUT/'NATIVE_GAIN_SEMANTIC_AUDIT189.json',{'records':rows,'native_models':len(rows),'uniform_allroom_models_by_gain_kind':counts,'V11_109W_quietperson_remains_declared_reference_not_age_specificmeasuredphysiology':True,'do_not_blindly_add_genericequipment_andspecificappliances':True,'no_sealed_source_or_V11_rewritten':True});print({'native_models':len(rows),'uniform_by_kind':counts})
if __name__=='__main__':main()
