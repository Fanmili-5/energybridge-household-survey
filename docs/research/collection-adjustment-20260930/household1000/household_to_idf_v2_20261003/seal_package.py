#!/usr/bin/env python3
"""Seal new artifacts and independently retain/check old source-byte bindings."""
import hashlib
import json
import re
from pathlib import Path

HERE=Path(__file__).resolve().parent
REPO=HERE.parents[4]
GEN=HERE.parent/'generation_model_20261003'
OLD=HERE.parent/'household_to_idf_20261003'


def read(path):return json.loads(Path(path).read_text())
def sha(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()
def save(path,obj):Path(path).write_text(json.dumps(obj,ensure_ascii=False,indent=2,allow_nan=False)+'\n')
def verify_manifest(folder,manifest):
    files=manifest['files']
    entries=files.items() if isinstance(files,dict) else ((x['path'],x['sha256']) for x in files)
    return [{'path':str(folder/name),'expected_sha256':expected,'actual_sha256':sha(folder/name) if (folder/name).is_file() else None}
            for name,expected in entries]


def main():
    if (HERE/'PACKAGE_MANIFEST.json').exists() or (HERE/'PACKAGE_VERIFICATION.json').exists():
        raise ValueError('package already sealed; do not replace')
    bindings={};sources=[]
    def bind(path,expected,source_id):
        path=Path(path).resolve();key=str(path)
        if key in bindings and bindings[key]['expected_sha256']!=expected:raise ValueError('conflicting_source_hash:'+key)
        row=bindings.setdefault(key,{'path':key,'expected_sha256':expected,'source_ids':[]})
        row['source_ids'].append(source_id)
    inherited=read(OLD/'SOURCE_LEDGER.json')
    for source in inherited['sources']:
        for f in source.get('local_files',[]):
            expected=f.get('sha256')
            if f.get('exists') and expected:bind(f['path'],expected,'inherited:'+source['source_id'])
    glock=read(GEN/'final_v2/GENERATOR_LOCK.json')
    for f in glock['source_files']:bind(f['path'],f['sha256'],'anonymous_generation_input')
    authority_path=HERE.parent/'evidence_contract_20261001/CITY_AUTHORITY_CONSTRAINTS_V2.json'
    authority=read(authority_path)
    for key,table in authority['tables'].items():bind(authority_path.parent/table['file'],table['sha256'],'NBS:'+key)
    registry=read(HERE/'PROTOTYPE_REGISTRY.json')
    for gid,group in registry['groups'].items():
        for prefix in ['source_idf','parent_idf']:
            bind(REPO/group[prefix+'_path'],group[prefix+'_sha256'],gid+':'+prefix)
    weather=read(HERE/'WEATHER_SUPPLEMENT_CATALOG.json')['weather']
    for w in weather:bind(REPO/w['epw'],w['epw_sha256'],'weather:'+w['id'])
    for key,row in sorted(bindings.items()):
        row['actual_sha256']=sha(key) if Path(key).is_file() else None
        row['pass']=row['actual_sha256']==row['expected_sha256']
    sources=[
        {'id':'NBS_CITY_CENSUS2020','kind':'official_population_and_ordinary_housing_margins',
         'urls':[t['url'] for t in authority['tables'].values()],
         'supports':'specified city family-household size/generation and ordinary-housing margins/definitions',
         'does_not_identify':'complete province×N×G×age×relations×housing×city×behavior joint',
         'indicator_definitions':'https://www.stats.gov.cn/sj/pcsj/rkpc/7rp/zk/html/fu06.pdf'},
        {'id':'CHFS2021','kind':'licensed_local_microdata_reference_read_in_process',
         'source_lock':str(GEN/'final_v2/GENERATOR_LOCK.json'),
         'supports':'weighted coarse co-residence, age, composition and same-current-dwelling area/room proxy references',
         'limitations':['economic versus census-resident scope mismatch','field-specific2021/2022 reference transport','small conditional pools','no original source IDs/rows exported to candidates','raw redistribution permission not asserted']},
        {'id':'DEST_CONVERTED','kind':'uncalibrated_engineering_assembly_and_height_sources',
         'registry_sha256':sha(HERE/'PROTOTYPE_REGISTRY.json'),'groups':len(registry['groups']),
         'scope':'materials/height only; selected actual files hash-checked; catalog city/year labels are metadata',
         'local_calibration_verified':False,'source_original_measured_origin_verified':False,'redistribution_permission_verified':False},
        {'id':'ONEBUILDING_TMYX','kind':'derived_typical_year_weather_resources',
         'url':'https://climate.onebuilding.org/WMO_Region_2_Asia/CHN_China/index.html',
         'source_explanation':'https://climate.onebuilding.org/sources/default.html',
         'downloaded_resources':62,'periods':['2009-2023','2011-2025'],
         'supports':'engineering climate inputs under explicit file/geographic QC',
         'does_not_support':['population city allocation','actual home address','observed2020 household weather','calibrated thermal or latent-load accuracy'],
         'download_archive_and_metadata_bindings':'WEATHER_VERIFICATION.json'},
        {'id':'NOAA_ISD_HISTORY','kind':'official_station_metadata_identity_crosscheck',
         'url':'https://www.ncei.noaa.gov/pub/data/noaa/isd-history.csv',
         'local_sha256':sha(HERE/'NOAA_ISD_HISTORY.csv'),'coordinates_disagreements_retained':True,
         'home_location_or_climate_equivalence_certified':False},
        {'id':'ENERGYPLUS24_1','kind':'actual_executed_engine',
         'engine':read(HERE/'annual_witnesses_v1/SELECTION_LOCK.json')['engine'],
         'supports':'117 annual hourly shell runs and version-bound output evidence',
         'limitations':['41 cases have warning markers','not an operational/electricity model','no empirical household calibration']}
    ]
    save(HERE/'SOURCE_LEDGER.json',{'schema':'eb.household_to_idf.sources.v2','snapshot_date_HKT':'2026-10-03',
         'sources':sources,'local_byte_bindings':list(bindings.values()),
         'all_source_bytes_match':all(x['pass'] for x in bindings.values()),
         'inherited_source_ledger_path':str(OLD/'SOURCE_LEDGER.json'),'inherited_source_ledger_sha256':sha(OLD/'SOURCE_LEDGER.json'),
         'source_authenticity_calibration_and_permissions_are_separate_from_hash_integrity':True})
    old_rows=verify_manifest(OLD,read(OLD/'PACKAGE_MANIFEST.json'))
    audit_rows=verify_manifest(OLD/'reviewer_audit_20261003',read(OLD/'reviewer_audit_20261003/REVIEW_MANIFEST.json'))
    gen_rows=verify_manifest(GEN,read(GEN/'PACKAGE_MANIFEST.json'))
    broken=[];links=0
    for folder in [HERE,GEN]:
        for path in folder.rglob('*.md'):
            for target in re.findall(r'\[[^\]]*\]\(([^)]+)\)',path.read_text()):
                target=target.strip('<>')
                if re.match(r'^[a-zA-Z][a-zA-Z0-9+.-]*://',target) or target.startswith('#'):continue
                target=target.split('#')[0]
                target=re.sub(r':\d+$','',target)
                if not target:continue
                location=Path(target) if target.startswith('/') else path.parent/target
                links+=1
                if not location.exists() and location.resolve()!=HERE/'PACKAGE_VERIFICATION.json':
                    broken.append({'document':str(path),'target':target})
    files={str(p.relative_to(HERE)):sha(p) for p in HERE.rglob('*') if p.is_file() and
           p not in {HERE/'PACKAGE_MANIFEST.json',HERE/'PACKAGE_VERIFICATION.json'} and '__pycache__' not in p.parts}
    save(HERE/'PACKAGE_MANIFEST.json',{'schema':'eb.household_to_idf.package.v2','files':files,
         'source_ledger_sha256':sha(HERE/'SOURCE_LEDGER.json'),'generation_package_path':str(GEN/'PACKAGE_MANIFEST.json'),
         'generation_package_sha256':sha(GEN/'PACKAGE_MANIFEST.json'),
         'excluded_self_referential_files':['PACKAGE_MANIFEST.json','PACKAGE_VERIFICATION.json'],
         'static_experiment_id':read(HERE/'CURRENT.json')['static_experiment_id'],
         'annual_experiment_id':read(HERE/'CURRENT.json')['annual_experiment_id'],
         'collection_release':False,'training_release':False})
    current_rows=verify_manifest(HERE,read(HERE/'PACKAGE_MANIFEST.json'))
    mismatch=lambda rows:[x for x in rows if x['expected_sha256']!=x['actual_sha256']]
    report={'schema':'eb.household_to_idf.package_verification.v2',
            'manifest_sha256':sha(HERE/'PACKAGE_MANIFEST.json'),'new_package_files_checked':len(current_rows),
            'new_package_mismatches':mismatch(current_rows),'generation_files_checked':len(gen_rows),
            'generation_mismatches':mismatch(gen_rows),'old_frozen_package_files_checked':len(old_rows),
            'old_package_mismatches':mismatch(old_rows),'old_audit_files_checked':len(audit_rows),
            'old_audit_mismatches':mismatch(audit_rows),'external_source_bindings_checked':len(bindings),
            'source_mismatches':[x for x in bindings.values() if not x['pass']],
            'local_markdown_links_checked':links,'broken_local_links':broken,
            'verification_scope':'byte/source/link integrity; scientific validation claims remain separately bounded',
            'checker_sha256':sha(__file__),'collection_release':False,'training_release':False}
    report['pass']=not any(report[k] for k in ['new_package_mismatches','generation_mismatches','old_package_mismatches','old_audit_mismatches','source_mismatches','broken_local_links'])
    save(HERE/'PACKAGE_VERIFICATION.json',report)
    print(json.dumps(report,ensure_ascii=False))
    if not report['pass']:raise SystemExit(1)


if __name__=='__main__':main()
