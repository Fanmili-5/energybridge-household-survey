"""Import China's CSWD archive plus city-named TMYx gaps; preserve resource provenance.
Administrative names are a frozen 2023 open data snapshot, not a current official registry.
No fuzzy nearest-city matching: unmatched station names remain in the resource inventory.
"""
from concurrent.futures import ThreadPoolExecutor
from collections import defaultdict
from pathlib import Path
import hashlib,json,re,sys,urllib.request
from pypinyin import lazy_pinyin
from build_regional_resources import fetch_station,OUT,STATIONS
ROOT=Path(__file__).resolve().parents[1]
PREFIX=dict(zip('AH BJ CQ FJ GD GS GX GZ HA HB HE HI HL HN JL JS JX LN NM NX QH SC SD SH SN SX TJ XJ XZ YN ZJ'.split(),
 '安徽 北京 重庆 福建 广东 甘肃 广西 贵州 河南 湖北 河北 海南 黑龙江 湖南 吉林 江苏 江西 辽宁 内蒙古 宁夏 青海 四川 山东 上海 陕西 山西 天津 新疆 西藏 云南 浙江'.split()))
MUNICIPAL={'北京','天津','上海','重庆'}
def roman(name):return ''.join(lazy_pinyin(name)).lower().replace('ü','v')
def bare(name):return re.sub(r'(自治县|自治州|特别行政区|自治区|地区|市|县|区|盟|旗)$','',name)
def main():
 from resource_versions import freeze
 freeze(OUT/'catalog.json')
 admin=OUT/'administrative';raw=json.loads((admin/'pca-code.json').read_text())
 by_province={};city_lookup={};station_lookup={}
 for p in raw:
  province=next((v for v in PREFIX.values() if p['name'].startswith(v)),None)
  if not province:continue
  names=[];city_lookup[province]=defaultdict(set);station_lookup[province]=defaultdict(set)
  for c in p['children']:
   entries=c['children'] if '直辖县级' in c['name'] else [c]
   for entry in entries:
    city=province if province in MUNICIPAL else entry['name'].removesuffix('市')
    if city not in names:names.append(city)
    city_lookup[province][roman(bare(city))].add(city)
    for place in [entry]+entry.get('children',[]):
     station_lookup[province][roman(bare(place['name']))].add(city)
  by_province[province]=names
 # Matched aliases are explicit historic/transliterated names; never nearest guessing.
 aliases={'Harbin':'haerbin','Hohhot':'huhehaote','Qiqihar':'qiqihaer','Xian':'xian',
  'Urumqi':'wulumuqi','Lhasa':'lasa','Qamdo':'changdu','Nyingchi':'linzhi',
  'Boxian':'bozhou','Congwu':'chongwu','Zhengcheng':'zengcheng','Exi':'enshi',
  'Ankangan':'ankang','Huaiyang-Qingjiang':'huaian','Hongjia':'jiaojiang','Quxian':'quzhou',
  'Simao':'simao','Golmud':'geermu','Arxan':'aershan','Erenhot':'erlianhaote','Manzhouli':'manzhouli',
  'Hailar':'hailaer','Aksu':'akesu','Altay':'aletai','Hotan':'hetian','Karamay':'kelamayi',
  'Kuqa':'kuche','Turpan':'tulufan','Barkam':'maerkang','Garze':'ganzi','Deqen':'deqin'}
 text=(ROOT/'artifacts/national_weather_inventory_20260912/china-index.html').read_text()
 links=sorted(set(re.findall(r'href="([^"]+\.zip)"',text,re.I)))
 selected={};unmapped=[]
 old=json.loads((OUT/'catalog.json').read_text());old_by_url={r['source_url']:r for r in old['weather']}
 from build_regional_resources import URL
 for link in links:
  name=Path(link).name;m=re.match(r'CHN_([A-Z]+)_(.+?)\.(\d{6})_(.+)\.zip$',name)
  if not m or m[1] not in PREFIX:continue
  province=PREFIX[m[1]];station,wmo,series=m.groups()[1:];token=aliases.get(station,station.split('.')[0]).lower().replace('-','')
  direct=city_lookup.get(province,{}).get(token,set())
  parents=direct or station_lookup.get(province,{}).get(token,set())
  prior=old_by_url.get(URL+link)
  city=prior['city'] if prior else next(iter(parents)) if len(parents)==1 else None
  # All 270 CSWD resources, plus explicit city-name TMYx candidates (one per WMO).
  if series!='CSWD' and not direct:continue
  rank=0 if series=='CSWD' else 1 if series=='TMYx.2011-2025' else 2 if series=='TMYx.2009-2023' else 3 if series=='TMYx' else 4
  key=m[1]+'_'+wmo
  item={'id':prior['id'] if prior else 'chn_'+wmo,'province':province,'city':city,
        'station_roman':station,'relative':link,'series':series,'rank':rank,
        'name_match':'explicit_existing_city_mapping' if prior else 'province_scoped_romanized_admin_name' if city else 'unmapped_station'}
  if key not in selected or rank<selected[key]['rank']:selected[key]=item
 def fetch(item):
  try:
   row=fetch_station((item['id'],item['province'],item['city'],item['relative']))
   row.update(series=item['series'],name_match=item['name_match'],station_roman=item['station_roman'])
   if row['source_url'] in old_by_url:row['status']=old_by_url[row['source_url']]['status']
   return row
  except Exception as exc:return {**item,'download_error':str(exc),'status':'unavailable'}
 result=[]
 with ThreadPoolExecutor(8) as pool:
  for row in pool.map(fetch,selected.values()):
   result.append(row)
   if len(result)%25==0:print(f'{len(result)}/{len(selected)} weather files inspected',flush=True)
 available=[r for r in result if r.get('epw')]
 old['weather']=available
 old['administrative_cities']=by_province
 old['administrative_source']={'repository':'https://github.com/modood/Administrative-divisions-of-China','snapshot':'2023-06-30',
  'files':{str(p.relative_to(ROOT)):hashlib.sha256(p.read_bytes()).hexdigest() for p in admin.glob('*.json')},
  'note':'Frozen names for input convenience; manual entry remains available. Station association is derived and separately recorded.'}
 old['national_expansion']={'inventoried':len(selected),'downloaded':len(available),'missing_city_mapping':sum(not r['city'] for r in available),
  'validation_status':'New combinations must pass EP before generation. Original successful combinations retained.'}
 (OUT/'national_download_report.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n')
 (OUT/'catalog.json').write_text(json.dumps(old,ensure_ascii=False,indent=2)+'\n')
 print(json.dumps(old['national_expansion'],ensure_ascii=False),flush=True)
if __name__=='__main__':main()
