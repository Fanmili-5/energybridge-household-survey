"""Read all original DeST environment records and independent EPW headers.

Catalogue epochs are reference scenarios; station cities are not household
population locations. Existing converted IDFs are independent conversions.
"""
import concurrent.futures,collections,csv,hashlib,json,re,sys,math
from pathlib import Path

OUT=Path(__file__).resolve().parent.parent;BASE=OUT.parent;REPO=OUT.parents[4]
runtime=json.loads((BASE/'idf_joint_production_20261005/RUNTIME.json').read_text());sys.path[:0]=runtime['stable_PYTHONPATH'].split(':')
from access_parser_c import AccessParser

def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def read(p):return json.loads(p.read_text())
def save(name,d):(OUT/name).write_text(json.dumps(d,ensure_ascii=False,indent=2,allow_nan=False)+'\n')
def rows(d):return [dict(zip(d,v)) for v in zip(*d.values())]
def canon(v):return re.sub(r'[^a-z0-9]','',str(v).lower())
def city_same(a,b):
    # Explicit bilingual alias verified in original ENVIRONMENT, not a fuzzy
    # nearest-city substitution. The raw spelling disagreement is retained.
    return canon(a)==canon(b) or (a=='Kunming' and b=='昆明')
def distance(lat,lon,a,b):
    x,y=map(math.radians,[lat,a]);dl=math.radians(b-lon)
    h=math.sin((y-x)/2)**2+math.cos(x)*math.cos(y)*math.sin(dl/2)**2
    return 6371*2*math.asin(min(1,math.sqrt(h)))

def main():
    from evidence_guard import ensure_unsealed
    ensure_unsealed(OUT)
    weather=[]
    weather_paths=list((REPO/'artifacts/private_research/role_weather_300_20260925').glob('*.epw'))+list((OUT/'raw/weather').glob('*.epw'))
    for p in sorted(weather_paths):
        m=read(p.with_suffix('.manifest.json'));header=next(csv.reader([p.read_text(errors='replace').splitlines()[0]]))
        assert header[0]=='LOCATION' and sha(p)==m['epw_sha256']
        w={'station_key':p.stem,'path':str(p),'sha256':sha(p),'city':header[1],'province':header[2],
           'country':header[3],'source_type':header[4],'WMO':header[5],'latitude':float(header[6]),'longitude':float(header[7]),'time_zone':float(header[8]),'elevation_m':float(header[9]),
           'source_zip_url':m['source_zip_url'],'population_city_or_weights_observed':False,'actual_household_weather_observed':False}
        weather.append(w)
    paths=sorted((REPO/'artifacts/private_research/dest_batch_300_sources_20260925').glob('**/*.accdb'))
    def inspect(p):
        manifest=read(p.parent/'manifest.json');assert sha(p)==manifest['source_accdb_sha256']
        db=AccessParser(str(p));env=rows(db.parse_table('ENVIRONMENT'));assert len(env)==1
        env=env[0];key=p.stem;match=re.fullmatch(r'(Low|HighS|HighT|Th)_(.+)_(\d{4})',key)
        assert match,'unknown_catalogue_key:'+key
        typ,city,year=match.groups();year=int(year)
        direct=[w for w in weather if str(env['CITY_ID'])+'0'==w['WMO']]
        located=[w for w in direct if distance(env['LATITUDE'],env['LONGITUDE'],w['latitude'],w['longitude'])<5]
        nearby=sorted(weather,key=lambda w:distance(env['LATITUDE'],env['LONGITUDE'],w['latitude'],w['longitude']))[:3]
        rooms_table=db.parse_table('ROOM');storeys=db.parse_table('STOREY');doors=db.parse_table('DOOR')
        converted=p.with_suffix('.idf');idf_hash=sha(converted)
        return {'model_key':key,'source_path':str(p),'source_sha256':sha(p),'conversion_path':str(converted),
          'conversion_sha256':idf_hash,'conversion_matches_manifest':idf_hash==manifest['idf_sha256'],
          'catalogue_type':typ,'catalogue_city':city,'catalogue_reference_epoch':year,
          'catalogue_epoch_is_observed_house_construction_year':False,'original_environment':env,
          'catalogue_city_matches_original_environment':city_same(city,env['CITY_NAME']),
          'raw_catalogue_environment_spelling_differs':canon(city)!=canon(env['CITY_NAME']),
          'bilingual_alias_resolution':'Kunming=昆明; Yunnan=云南' if city=='Kunming' and env['CITY_NAME']=='昆明' else None,
          'original_room_count':len(next(iter(rooms_table.values()))),'original_storey_count':len(next(iter(storeys.values()))),
          'original_door_count':len(next(iter(doors.values()))),
          'source_WMO5_to_EPW6_convention':'append0 inferred forChina station identifiers; independently checkcoordinates',
          'coordinate_confirmed_WMO_station_candidates':[{'station_key':w['station_key'],'path':w['path'],'sha256':w['sha256'],
             'distance_km':distance(env['LATITUDE'],env['LONGITUDE'],w['latitude'],w['longitude'])} for w in located],
          'nearby_reference_stations_not_automatic_match':[{'station_key':w['station_key'],'distance_km':distance(env['LATITUDE'],env['LONGITUDE'],w['latitude'],w['longitude'])} for w in nearby],
          'native_embedded_weather_not_imported_or_validated':True,'materials_geometry_household_and_stock_frequency_admission_complete':False,
          'reference_source_city_is_not_generated_household_observed_city':True}
    with concurrent.futures.ThreadPoolExecutor(4) as pool:models=list(pool.map(inspect,paths))
    # Additional explicitly parsed tower/terraced references are registered
    # separately; do not silently include them in the187batch count.
    extra=[]
    for typ in ['HighT','Th']:
        p=BASE/'idf_unit_evidence_20261004'/f'{typ}_Beijing_2018_NATIVE.json';d=read(p);native=Path(d['source_path'])
        assert sha(native)==d['source_sha256']
        extra.append({'model_key':d['source_key'],'source_path':str(native),'sha256':sha(native),'catalogue_type':typ,
          'catalogue_reference_epoch':2018,'catalogue_city':'Beijing','door_table_empty':d['door_table_empty'],'not_counted_in187batch':True})
    save('WEATHER_REFERENCE_REGISTRY.json',{'stations':weather,'files_hash_verified':len(weather),'weather_type_is_reference_typical_year_not_single_house_observation':True})
    summary={'models':models,'batch_native_files':len(models),'types':dict(collections.Counter(m['catalogue_type'] for m in models)),
      'catalogue_cities':len({m['catalogue_city'] for m in models}),'reference_epochs':dict(collections.Counter(m['catalogue_reference_epoch'] for m in models)),
      'WMO_and_coordinate_weather_reference_supported_models':sum(bool(m['coordinate_confirmed_WMO_station_candidates']) for m in models),
      'catalogue_environment_city_disagreements':sum(not m['catalogue_city_matches_original_environment'] for m in models),
      'raw_spelling_differences_resolved_with_explicit_bilingual_alias':sum(m['raw_catalogue_environment_spelling_differs'] and m['catalogue_city_matches_original_environment'] for m in models),
      'converted_IDF_manifest_mismatches':sum(not m['conversion_matches_manifest'] for m in models),
      'additional_tower_terraced_native_references':extra,'native_library_or_prototype_counts_are_not_population_frequencies':True,
      'town_rural_households_not_added_to_target_population':True}
    save('NATIVE_REFERENCE_REGISTRY.json',summary)
    print(json.dumps({k:v for k,v in summary.items() if k not in ['models','additional_tower_terraced_native_references']},ensure_ascii=False,indent=2))

if __name__=='__main__':main()
