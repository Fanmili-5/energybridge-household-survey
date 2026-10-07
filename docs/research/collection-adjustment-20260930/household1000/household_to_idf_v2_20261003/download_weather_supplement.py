#!/usr/bin/env python3
"""Acquire provider EPW inputs; a climate-resource inventory, not city allocation.

Named city resources are an explicit engineering coverage probe. Every profile keeps
its province slot, and this script never assigns a household to a capital.
Original resources/catalog and the v1 frozen package are not changed.
"""
import csv
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
import hashlib
from html.parser import HTMLParser
import io
import json
from pathlib import Path
import re
import urllib.request
from urllib.parse import urljoin
import zipfile

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[4]
INDEX = 'https://climate.onebuilding.org/WMO_Region_2_Asia/CHN_China/index.html'
# Prefixes identify the provider's resource directory; not urban-address codes.
CAPITALS = [
 ('北京','北京','BJ','Beijing-Capital'),('天津','天津','TJ','Tianjin'),
 ('河北','石家庄','HE','Shijiazhuang'),('山西','太原','SX','Taiyuan'),
 ('内蒙古','呼和浩特','NM','Hohhot'),('辽宁','沈阳','LN','Shenyang'),
 ('吉林','长春','JL','Changchun'),('黑龙江','哈尔滨','HL','Harbin'),
 ('上海','上海','SH','Shanghai-Hongqiao'),('江苏','南京','JS','Nanjing'),
 ('浙江','杭州','ZJ','Hangzhou'),('安徽','合肥','AH','Hefei'),
 ('福建','福州','FJ','Fuzhou'),('江西','南昌','JX','Nanchang'),
 ('山东','济南','SD','Jinan'),('河南','新郑','HA','Xinzheng'),
 ('湖北','武汉','HB','Tianhe-Wuhan'),('湖南','长沙','HN','Changsha'),
 ('广东','广州','GD','Guangzhou'),('广西','南宁','GX','Nanning'),
 ('海南','海口','HI','Haikou'),('重庆','重庆','CQ','Chongqing'),
 ('四川','成都','SC','Chengdu'),('贵州','贵阳','GZ','Guiyang'),
 ('云南','昆明','YN','Kunming'),('西藏','拉萨','XJ','Lhasa'),
 ('陕西','西安','SN','Xian'),('甘肃','兰州','GS','Lanzhou'),
 ('青海','西宁','QH','Xining'),('宁夏','银川','NX','Yinchuan'),
 ('新疆','乌鲁木齐','XZ','Urumqi-Diwopu')
]
PERIODS = ('2011-2025', '2009-2023')


def sha(data):
    return hashlib.sha256(data).hexdigest()


def dump(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n')


def fetch(url):
    request = urllib.request.Request(url, headers={'User-Agent': 'EnergyBridge-research-resource-check/2.0'})
    with urllib.request.urlopen(request, timeout=35) as response:
        chunks, total = [], 0
        while True:
            chunk = response.read(262144)
            if not chunk:
                break
            total += len(chunk)
            if total > 5_000_000:
                raise ValueError('resource exceeds declared 5 MB per-file limit')
            chunks.append(chunk)
        data = b''.join(chunks)
        if response.headers.get('Content-Length') and len(data) != int(response.headers['Content-Length']):
            raise ValueError('incomplete HTTP body; refuses archive admission')
        return data, dict(response.headers)


class Links(HTMLParser):
    def __init__(self):
        super().__init__()
        self.links = []

    def handle_starttag(self, tag, attrs):
        if tag.lower() == 'a':
            for key, value in attrs:
                if key == 'href' and value and value.endswith('.zip'):
                    self.links.append(urljoin(INDEX, value))


def obtain(plan):
    url = plan['url']
    resource_id = plan['id']
    folder = HERE / 'weather_resources' / resource_id
    folder.mkdir(parents=True, exist_ok=True)
    archive = folder / 'provider.zip'
    if archive.exists():
        data, headers = archive.read_bytes(), {}
        if not zipfile.is_zipfile(io.BytesIO(data)):
            rejected = folder / 'provider_rejected_incomplete.zip'
            if not rejected.exists():
                archive.replace(rejected)
            data, headers = fetch(url)
            if not zipfile.is_zipfile(io.BytesIO(data)):
                raise ValueError('response still lacks complete ZIP directory')
            archive.write_bytes(data)
    else:
        data, headers = fetch(url)
        archive.write_bytes(data)
    members = {}
    with zipfile.ZipFile(io.BytesIO(data)) as bundle:
        for suffix, output in [('.epw', 'weather.epw'), ('.ddy', 'design.ddy'), ('.stat', 'weather.stat')]:
            matched = [n for n in bundle.namelist() if n.lower().endswith(suffix)]
            if len(matched) != 1:
                if suffix == '.epw':
                    raise ValueError('expected exactly one provider EPW')
                continue
            raw = bundle.read(matched[0])
            if len(raw) > 10_000_000:
                raise ValueError('unpacked member exceeds declared bound')
            target = folder / output
            if target.exists() and target.read_bytes() != raw:
                raise ValueError('existing resource bytes differ; refuses overwrite')
            target.write_bytes(raw)
            members[output] = {'archive_member': matched[0], 'sha256': sha(raw), 'bytes': len(raw)}
    location = next(csv.reader((folder / 'weather.epw').read_text(encoding='utf-8-sig').splitlines()))
    entry = {
        **{k: plan[k] for k in ['id','province','city','period']},
        'station_name': location[1], 'wmo': location[5], 'series': 'TMYx.' + plan['period'],
        'latitude': float(location[6]), 'longitude': float(location[7]),
        'timezone': float(location[8]), 'altitude_m': float(location[9]),
        'source_url': url, 'status': 'verified',
        'verification_scope': 'provider archive extraction and LOCATION binding; annual QC remains separate',
        'match': 'explicit_named_city_resource_inventory', 'name_match': 'provider_directory_and_filename',
        'epw': str((folder / 'weather.epw').relative_to(REPO)),
        'epw_sha256': members['weather.epw']['sha256'],
        'ddy': str((folder / 'design.ddy').relative_to(REPO)) if 'design.ddy' in members else None,
        'ddy_sha256': members.get('design.ddy',{}).get('sha256'),
        'urban_household_address_verified': False,
        'local_stock_or_population_city_assignment': False,
    }
    source = {
        'url': url, 'archive_sha256': sha(data), 'archive_bytes': len(data),
        'archive_path': str(archive.relative_to(REPO)), 'members': members,
        'retrieved_at_UTC': datetime.now(timezone.utc).isoformat(),
        'response_headers': {k:v for k,v in headers.items() if k.lower() in ['last-modified','etag','content-type']},
        'provider_index_url': INDEX, 'provider_index_sha256': plan['index_sha256'],
        'typical_year_is_not_observed_household_year': True,
        'public_redistribution_license': 'not independently established by this acquisition',
    }
    if not (folder / 'source.json').exists():
        dump(folder / 'source.json', source)
    return entry


def main():
    index_path = HERE / 'WEATHER_PROVIDER_INDEX.html'
    if index_path.exists():
        html = index_path.read_bytes()
    else:
        html, _ = fetch(INDEX)
        index_path.write_bytes(html)
    parser = Links()
    parser.feed(html.decode('utf-8'))
    plans, missing = [], []
    for province, city, prefix, name in CAPITALS:
        for period in PERIODS:
            pattern = rf'/CHN_{prefix}_{re.escape(name)}[^/]*_TMYx\.{period}\.zip$'
            found = sorted(set(url for url in parser.links if re.search(pattern, url, re.I)))
            if not found:
                missing.append({'province': province, 'city': city, 'period': period, 'reason': 'no_matching_index_link'})
                continue
            # Freeze selection before reading hourly values: lexical first within
            # the explicit provider name/period, all planned periods are retained.
            plans.append({'province':province,'city':city,'period':period,'url':found[0],
                          'id':f'v2_{prefix.lower()}_{period.replace("-", "_")}',
                          'province_mapping_basis':'explicit city resource; directory prefix is not province truth; independent station metadata check follows',
                          'index_sha256':sha(html),'index_matching_links':found})
    dump(HERE / 'WEATHER_DOWNLOAD_PLAN.json', {
        'schema':'eb.weather.download_plan.v2', 'index_url':INDEX,'index_sha256':sha(html),
        'rule':'named provincial-city resource inventory; lexical provider name tie; retain both prespecified TMY periods; not household city allocation',
        'plans':plans,'missing_index_links':missing,
        'period_choice_is_design_not_population_reference_year':True,
    })
    entries, failures = [], []
    with ThreadPoolExecutor(max_workers=6) as pool:
        pending = {pool.submit(obtain, plan): plan for plan in plans}
        for future in as_completed(pending):
            plan = pending[future]
            try:
                entries.append(future.result())
            except Exception as exc:
                failures.append({'id':plan['id'],'url':plan['url'],'error':type(exc).__name__+': '+str(exc)})
    entries.sort(key=lambda x:x['id'])
    original = REPO / 'simulation_resources/catalog.json'
    native = json.loads(original.read_text())
    dump(HERE / 'WEATHER_SUPPLEMENT_CATALOG.json', {
        'schema':'eb.weather.supplement.v2','weather':entries,
        'planned_downloads':len(plans),'download_failures':failures,
        'not_population_city_allocation':True,
    })
    dump(HERE / 'WEATHER_CATALOG.json', {
        'version':'eb.weather.composite.v2','base_catalog_path':str(original),
        'base_catalog_sha256':sha(original.read_bytes()),
        'weather':native['weather']+entries,
        'scope':'unchanged old entries plus separately acquired climate inputs; no household assignments',
    })
    print(json.dumps({'planned':len(plans),'downloaded':len(entries),'missing_links':missing,'download_failures':failures},ensure_ascii=False))


if __name__ == '__main__':
    main()
