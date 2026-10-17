#!/usr/bin/env python3
"""Independent extraction/hash/count and weather-interface controls."""
import copy
import csv
import hashlib
import json
from pathlib import Path
import tempfile
import zipfile
import weather_rules as weather

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[4]


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def main():
    supplement = json.loads((HERE/'WEATHER_SUPPLEMENT_CATALOG.json').read_text())
    qc = json.loads((HERE/'WEATHER_REGISTRY_QC.json').read_text())
    checks, metadata = [], []
    byid = {r['id']:r for r in qc['stations']}
    for entry in supplement['weather']:
        folder = (REPO/entry['epw']).parent
        source = json.loads((folder/'source.json').read_text())
        archive = REPO/source['archive_path']
        with zipfile.ZipFile(archive) as bundle:
            members_match = all(hashlib.sha256(bundle.read(v['archive_member'])).hexdigest()==v['sha256']
                                and sha(folder/name)==v['sha256']
                                for name,v in source['members'].items())
        checks.append({'id':entry['id'],'archive_and_extracted_bytes_match':
                       sha(archive)==source['archive_sha256'] and members_match,
                       'url_binding':source['url']==entry['source_url'],
                       'full_annual_policy_pass':byid[entry['id']]['file_quality_passed']})
    # NOAA's history may contain relocated station coordinates: report, don't
    # silently overwrite the EPW coordinates or call every identity exact.
    noaa = json.loads((HERE/'NOAA_STATION_IDENTITY.json').read_text())
    noaa_byid = {r['USAF']:r for r in noaa['rows']}
    for entry in supplement['weather']:
        if entry['wmo'] not in noaa_byid:
            continue
        reference = noaa_byid[entry['wmo']]
        delta = weather._distance_km(entry['latitude'],entry['longitude'],
                                     float(reference['LAT']),float(reference['LON']))
        metadata.append({'id':entry['id'],'province_assignment':entry['province'],'provider_url':entry['source_url'],
                         'provider_LOCATION':byid[entry['id']]['epw_location'],
                         'NOAA_history_record':reference,'coordinate_separation_km':delta,
                         'elevation_difference_m':entry['altitude_m']-float(reference['ELEV(M)']),
                         'interpretation':'station-name/code cross-reference; current/historical NOAA coordinates do not establish a specific EPW station position or an urban home'})
    reference = next(e for e in supplement['weather'] if e['province']=='北京' and e['period']=='2011-2025')
    target = {k:reference[k] for k in ['province','city','latitude','longitude','altitude_m','timezone']}
    target['coordinate_evidence']={'status':'declared_station_site_for_engineering_control','station':reference['id']}
    positive = weather.resolve_weather(target,REPO)
    explicit = copy.deepcopy(target);explicit['weather_resource_id']=reference['id']
    missing_id = copy.deepcopy(target);missing_id['weather_resource_id']='absent-resource-control'
    large = copy.deepcopy(target);large['latitude']=10**400
    escape = weather.resolve_weather(target,REPO,catalog_path='/private/tmp/non_repository_weather_catalog.json')
    incomplete = copy.deepcopy(target);incomplete['coordinate_evidence']=None
    controls = {
        'same_city_station_site_admitted':positive['selected'] is not None,
        'explicit_identity_admitted_without_fallback':weather.resolve_weather(explicit,REPO)['selected']['id']==reference['id'],
        'absent_explicit_identity_refused':weather.resolve_weather(missing_id,REPO)['selected'] is None,
        'giant_coordinate_structured_refusal':weather.resolve_weather(large,REPO)['status']=='invalid_target',
        'escaped_catalog_structured_refusal':escape['status']=='invalid_catalog',
        'missing_site_evidence_refused':weather.resolve_weather(incomplete,REPO)['status']=='missing_target',
        'all_31_provinces_have_file_candidates':len({r['province'] for r in qc['stations'] if r['file_quality_passed']})==31,
        'composite_base_catalog_matches':json.loads((HERE/'WEATHER_CATALOG.json').read_text())['base_catalog_sha256']==sha(REPO/'simulation_resources/catalog.json'),
        'NOAA_snapshot_matches':noaa['sha256']==sha(HERE/'NOAA_ISD_HISTORY.csv')
    }
    passed = all(all(r[k] for k in ['archive_and_extracted_bytes_match','url_binding','full_annual_policy_pass']) for r in checks) and all(controls.values())
    result = {
        'schema':'eb.weather.verification.v2','status':'pass' if passed else 'fail',
        'new_files_checked':len(checks),'checks':checks,'controls':controls,
        'station_identity_diagnostics':metadata,'empirical_climate_equivalence_certified':False,
        'population_city_allocation_performed':False,
        'source_geography_support':{
            'Lhasa_in_Tibet':'https://wlt.xizang.gov.cn/xwzx_69/wlyw/dsdt/201712/t20171226_116331.html',
            'Lhasa_geographic_context':'https://zrzyt.xizang.gov.cn/gk/gsgg/202310/t20231023_381983.html',
            'Urumqi_in_Xinjiang_context':'https://www.xinjiang.gov.cn/xinjiang/gfxwj/201204/8c6399fa120043448ca561d96eac2245.shtml',
            'NOAA_ISD':'https://www.ncei.noaa.gov/products/land-based-station/integrated-surface-database',
            'qualification':'government city/province context supports manual registry normalization; not proof of a household address or exact station-history equivalence'
        },
        'file_hashes':{p.name:sha(p) for p in [HERE/'weather_rules.py',HERE/'WEATHER_CATALOG.json',HERE/'WEATHER_SUPPLEMENT_CATALOG.json',HERE/'WEATHER_REGISTRY_QC.json',HERE/'NOAA_STATION_IDENTITY.json',Path(__file__)]}
    }
    (HERE/'WEATHER_VERIFICATION.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n')
    print(json.dumps({'status':result['status'],'new_files_checked':len(checks),'controls':controls},ensure_ascii=False))
    if not passed:
        raise SystemExit(1)


if __name__=='__main__':
    main()
