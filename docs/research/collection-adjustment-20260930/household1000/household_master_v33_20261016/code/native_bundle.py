"""Extract actually used native constructions and the used scalar window type.

Correct DeST namespaces:1 outer wall,2 inner wall,3 roof,4 ground,5 middle.
Geometry, optical angular equivalence and actual code compliance are not claimed.
"""
import hashlib,math
from access_parser_c import AccessParser
from model_matching import PROVINCES
def rows(table):return [dict(zip(table,values))for values in zip(*table.values())]
def distance(a,b,c,d):
    rad=math.pi/180;da=(c-a)*rad;db=(d-b)*rad
    return 6371*2*math.asin(min(1,math.sqrt(math.sin(da/2)**2+math.cos(a*rad)*math.cos(c*rad)*math.sin(db/2)**2)))
def extract(record):
    from pathlib import Path
    source=Path(record['source_path']);signature=hashlib.sha256(source.read_bytes()).hexdigest()
    if not record.get('source_sha256'):raise ValueError('NATIVE_SOURCE_LOCK_REQUIRED')
    if record['source_sha256']!=signature:raise ValueError('NATIVE_SOURCE_HASH')
    db=AccessParser(str(source));env=rows(db.parse_table('ENVIRONMENT'))[0]
    expected=record['original_environment']
    if env['CITY_NAME']!=expected['CITY_NAME']or PROVINCES.get(env['PROVINCE'])!=PROVINCES.get(expected['PROVINCE']):raise ValueError('NATIVE_ENVIRONMENT_DOES_NOT_MATCH_PLANNED_CITY_PROVINCE')
    stations=[]
    for s in record['coordinate_confirmed_WMO_station_candidates']:
        epw=Path(s['path'])
        if hashlib.sha256(epw.read_bytes()).hexdigest()!=s['sha256']:raise ValueError('RAW_EPW_HASH_CHANGED')
        header=epw.read_text().splitlines()[0].split(',')
        if header[0]!='LOCATION'or header[5]!=str(int(env['CITY_ID']))+'0':raise ValueError('NATIVE_WMO_EPW_ID_MISMATCH')
        km=distance(env['LATITUDE'],env['LONGITUDE'],float(header[6]),float(header[7]))
        if km<5:stations.append({**s,'distance_km':km,'EPW_header':header,'actual_native_WMO_and_EPW_hash_checked':True})
    if not stations:raise ValueError('NATIVE_WEATHER_IDENTITY_MISSING')
    enc=rows(db.parse_table('MAIN_ENCLOSURE'));mats={x['MATERIAL_ID']:x for x in rows(db.parse_table('SYS_MATERIAL'))};props=[];names={};proof=[]
    for kind,code,table in [('exterior',1,'SYS_OUTWALL'),('interior',2,'SYS_INWALL'),('roof',3,'SYS_ROOF'),('ground',4,'SYS_GROUNDFLOOR'),('floor',5,'SYS_MIDDLEFLOOR')]:
        ids={x['CONSTRUCTION']for x in enc if x['KIND']==code}
        if len(ids)!=1:raise ValueError('MULTIPLE_OR_MISSING_USED_CONSTRUCTIONS:'+kind)
        sid=next(iter(ids));structs={x['STRUCT_ID']for x in rows(db.parse_table(table))}
        if sid not in structs:raise ValueError('NATIVE_USED_STRUCT_FOREIGN_KEY_MISSING:'+kind+':'+str(sid))
        layers=sorted([x for x in rows(db.parse_table(table+'_MATERIAL'))if x['STRUCT_ID']==sid],key=lambda x:x['LAYER_NO'])
        if not layers:raise ValueError('EMPTY_NATIVE_LAYERS:'+kind)
        layernames=[];vectors=[]
        for j,x in enumerate(layers):
            m=mats[x['MATERIAL_ID']];v=[x['LENGTH']/1000,m['CONDUCTIVITY'],m['DENSITY'],m['SPECIFIC_HEAT']]
            if not all(math.isfinite(z)and z>0 for z in v):raise ValueError('BAD_NATIVE_MATERIAL_VECTOR')
            name=f'{record["model_key"]}_{kind}_{j}';props.append(['Material',name,'MediumRough',*map(str,v),'.9','.7','.7']);layernames.append(name);vectors.append(v)
        name=record['model_key']+'_'+kind;props.append(['Construction',name,*layernames]);names[kind]=name
        proof.append({'kind':kind,'native_enclosure_KIND':code,'native_used_struct_ID':sid,'native_layer_table':table+'_MATERIAL',
            'material_IDs':[x['MATERIAL_ID']for x in layers],'vectors_thickness_conductivity_density_specific_heat':vectors,
            'thickness_m':sum(v[0]for v in vectors),'series_R_without_films':sum(v[0]/v[1]for v in vectors)})
    window=rows(db.parse_table('WINDOW'));types={x['ID']:x for x in rows(db.parse_table('WINDOW_TYPE_DATA'))};used={x['TYPE']for x in window}
    if len(used)!=1:raise ValueError('EXPLICIT_WINDOW_MAPPING_REQUIRED')
    t=types[next(iter(used))];u=float(t['K']);sc=float(t['SC']);vt=float(t['LIGHT_TRANS_RATIO'])
    if not u>0 or not 0<=sc*.87<=1 or not 0<=vt<=1:raise ValueError('INVALID_USED_NATIVE_SCALAR_WINDOW')
    name=record['model_key']+'_scalar_window';con=record['model_key']+'_window'
    props += [['WindowMaterial:SimpleGlazingSystem',name,str(u),str(sc*.87),str(vt)],['Construction',con,name]];names['window']=con
    updated={**record,'source_sha256':signature,'original_environment':env,'metadata_environment_inherited_for_download_planning':False,
        'native_original_available':True,'actual_environment_and_used_parameter_tables_verified':True,
        'coordinate_confirmed_WMO_station_candidates':stations}
    for key in ['conversion_path','conversion_sha256','conversion_matches_manifest','original_room_count','original_storey_count','original_door_count']:
        updated.pop(key,None) # Inherited catalogue planning metadata is not evidence from the new file.
    bundle={'model_key':record['model_key'],'rows':props,'names':names,'source_path':str(source),'source_sha256':signature,'source_conversion_sha256':None,
        'exterior_thickness_m':proof[0]['thickness_m'],'interior_thickness_m':proof[1]['thickness_m'],
        'climate_identity':record['model_key']+'_native_parameter_reference','native_opaque_provenance':proof,
        'scalar_window_provenance':{'type_ID':t['ID'],'type_NAME':t['NAME'],'U':u,'SC':sc,'visible':vt,'SC_to_SHGC':.87,
            'optical_pairs_quarantined':float(t['ENERGY_TRANS_RATIO'])+float(t['ENERGY_REFLECT_RATIO'])>1+1e-6 or vt+float(t['LIGHT_REFLECT_RATIO'])>1+1e-6,
            'angular_spectral_or_frame_boundary_equivalence_validated':False},
        'native_absorptance_or_roughness_measured':False,'actual_source_house_or_code_compliance':False}
    if hashlib.sha256(source.read_bytes()).hexdigest()!=signature:raise ValueError('NATIVE_SOURCE_CHANGED_DURING_PARSE')
    return updated,bundle
