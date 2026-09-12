"""Explicit provincial research proxies, not nearest-station claims."""
import json,sys,urllib.request,re
from pathlib import Path
from build_regional_resources import OUT,fetch_station
CAPITALS=dict(zip('安徽 北京 重庆 福建 广东 甘肃 广西 贵州 河南 湖北 河北 海南 黑龙江 湖南 吉林 江苏 江西 辽宁 内蒙古 宁夏 青海 四川 山东 上海 陕西 山西 天津 新疆 西藏 云南 浙江 香港 澳门 台湾'.split(),
 '合肥 北京 重庆 福州 广州 兰州 南宁 贵阳 郑州 武汉 石家庄 海口 哈尔滨 长沙 长春 南京 南昌 沈阳 呼和浩特 银川 西宁 成都 济南 上海 西安 太原 天津 乌鲁木齐 拉萨 昆明 杭州 香港 澳门 台北'.split()))
EXTRA=[('hongkong','香港','香港','HKG_Hong_Kong/HKG_HKI_Hong.Kong.Intl.AP.450070_TMYx.2011-2025.zip'),
 ('macau','澳门','澳门','MAC_Macau/MAC_MA_Macau.Intl.AP.450110_TMYx.2011-2025.zip'),
 ('taipei','台湾','台北','TWN_Taiwan/NOR_Northern_Region/TWN_NOR_Taipei.589680_TMYx.2011-2025.zip')]
def main():
 import build_regional_resources as builder
 from resource_versions import freeze
 freeze(OUT/'catalog.json')
 c=json.loads((OUT/'catalog.json').read_text())
 for key,province,city,relative in EXTRA:
  try:
   old=builder.URL;builder.URL='https://climate.onebuilding.org/WMO_Region_2_Asia/'
   row=fetch_station((key,province,city,relative));row.update(series='TMYx.2011-2025',name_match='explicit_city_station')
   if not any(r['id']==key for r in c['weather']):c['weather'].append(row)
   c['administrative_cities'].setdefault(province,[city])
  except Exception as exc:print('Optional region unavailable',province,str(exc),flush=True)
  finally:builder.URL=old
 c['province_representatives']={}
 for province,capital in CAPITALS.items():
  candidates=[r for r in c['weather'] if r['province']==province and r['city']==capital]
  from pypinyin import lazy_pinyin
  roman=''.join(lazy_pinyin(capital))
  english={'哈尔滨':'harbin','呼和浩特':'hohhot','乌鲁木齐':'urumqi','拉萨':'lhasa'}.get(capital,roman)
  candidates.sort(key=lambda r:(r.get('station_roman','').lower()!=english,r['series']!='CSWD',r['id']))
  if candidates:c['province_representatives'][province]=candidates[0]['id']
  else:print('Missing provincial representative:',province,flush=True)
 c['weather_match_policy']={'version':'city_then_province_v1','fallback':'explicit_provincial_representative',
  'nearest_station':False,'distance_km':None,'household_coordinates_collected':False,
  'user_authorized_scope':'same city when available; provincial representative otherwise',
  'limitations':'Provincial proxy may not represent local altitude/coast/urban microclimate; shown and stored as research approximation.'}
 (OUT/'catalog.json').write_text(json.dumps(c,ensure_ascii=False,indent=2)+'\n')
 print('Representatives',len(c['province_representatives']),'stations',len(c['weather']),flush=True)
if __name__=='__main__':main()
