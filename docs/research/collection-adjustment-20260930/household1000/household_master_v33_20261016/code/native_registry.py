"""Join author labels to native keys before filtering city/type.

For example author label Xian maps to native key XianShi. The author mapping
is the authority for that alias. An empty text-prefix join must not move a
reference household to another city. Inherited environment is planning only;
native_bundle.extract still verifies the downloaded bytes and station identity.
"""
import copy,hashlib
from pathlib import Path

def build(metadata,author_mapping,native_cache):
 caches=[Path(p)for p in native_cache]if isinstance(native_cache,(list,tuple))else[Path(native_cache)]
 bykey={r['model_key']:r for r in metadata};cities={r['catalogue_city']:r for r in metadata};result=[]
 for city,base in cities.items():
  for kind in ['Low','HighS','HighT']:
   entries=sorted((int(key.rsplit('_',1)[1]),key,label)for label,key in author_mapping.items()
       if key.startswith(kind+'_'+city+'_'))
   for i,(year,key,label)in enumerate(entries):
    r=copy.deepcopy(bykey.get(key,base));r.update(model_key=key,catalogue_key=label,catalogue_type=kind,catalogue_city=city,
       catalogue_reference_epoch=year,regime_begin=year,regime_end=entries[i+1][0]-1 if i+1<len(entries)else 2020,
       catalogue_intervals_are_inferred_not_verified_local_adoption=True)
    if key not in bykey:
     p=next((base/key/(key+'.accdb')for base in caches if(base/key/(key+'.accdb')).exists()),caches[0]/key/(key+'.accdb'));r.update(source_path=str(p),
      source_sha256=hashlib.sha256(p.read_bytes()).hexdigest()if p.exists()else None,
      metadata_environment_inherited_for_download_planning=True)
    r['native_original_available']=Path(r['source_path']).exists();result.append(r)
 return result
