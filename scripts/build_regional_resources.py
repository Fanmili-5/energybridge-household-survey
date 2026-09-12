"""Build an explicitly approximate residential library and freeze EPW resources.

Geometry is a documented research parameterization, not a measured Chinese
housing stock dataset. Materials and HVAC/DHW come from the pinned EB model.
This script never changes the author checkout or calls an LLM.
"""
from __future__ import annotations
import argparse
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
import hashlib
import io
import json
import math
from pathlib import Path
import sys
import urllib.request
import zipfile

PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT/'realtime_pilot'))
from native_assets import idf_objects

OUT = PROJECT/'simulation_resources'
BASE = PROJECT/'models/tianjin_family_eb_v1/family_all_appliances.idf'
URL = 'https://climate.onebuilding.org/WMO_Region_2_Asia/CHN_China/'
STATIONS = [
 ('beijing','北京','北京','BJ_Beijing/CHN_BJ_Beijing.545110_CSWD.zip'),
 ('tianjin','天津','天津','TJ_Tianjin/CHN_TJ_Tianjin.545270_CSWD.zip'),
 ('shanghai','上海','上海','SH_Shanghai/CHN_SH_Shanghai.583620_CSWD.zip'),
 ('guangzhou','广东','广州','GD_Guangdong/CHN_GD_Guangzhou.592870_CSWD.zip'),
 ('chengdu','四川','成都','SC_Sichuan/CHN_SC_Chengdu.562940_CSWD.zip'),
 ('chongqing','重庆','重庆','CQ_Chongqing/CHN_CQ_Chongqing.Shapingba.575160_CSWD.zip'),
 ('wuhan','湖北','武汉','HB_Hubei/CHN_HB_Wuhan.574940_CSWD.zip'),
 ('nanjing','江苏','南京','JS_Jiangsu/CHN_JS_Nanjing.582380_CSWD.zip'),
 ('hangzhou','浙江','杭州','ZJ_Zhejiang/CHN_ZJ_Hangzhou.584570_CSWD.zip'),
]
AREA = {'lt50':40, '50_89':70, '90_119':105, '120_159':140, 'ge160':180}

def sha(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()
def render(rows):
    return '\n\n'.join(r[0]+',\n'+''.join('    '+v+(';' if i==len(r)-2 else ',')+'\n'
        for i,v in enumerate(r[1:])) for r in rows)+'\n'

def model(kind, floor, area):
    rows=deepcopy(idf_objects(BASE.read_text()))
    removed={'buildingsurface:detailed','window','door','windowshadingcontrol'}
    rows=[r for r in rows if r[0].lower() not in removed
          and not r[0].lower().startswith(('airflownetwork:','shading:'))
          and not (r[0].lower()=='zone' and r[1]=='attic_unit1')]
    for r in rows:
        if r[0].lower()=='building':r[7]='60'  # More warmup days; retain convergence tolerances.
    # Single-storey equivalent unit. Input area is usable indoor floor area;
    # gross-to-usable assumptions belong in the resolved environment record.
    w=math.sqrt(area/0.9);d=w*.9;h=2.8
    bottom='Ground' if kind!='apartment' or floor=='ground' else 'Adiabatic'
    top='Outdoors' if kind!='apartment' or floor=='top' else 'Adiabatic'
    side='Outdoors' if kind=='detached' else 'Adiabatic'
    surfaces={
      'Floor_unit1':('Floor','CN_GroundSlab_Concrete_Finish',bottom,[(0,0,0),(0,d,0),(w,d,0),(w,0,0)]),
      'ceiling_unit1':('Roof' if top=='Outdoors' else 'Ceiling','CN_AtticFloor_RockWool_Cold',top,[(0,0,h),(w,0,h),(w,d,h),(0,d,h)]),
      'South':('Wall','CN_ExteriorWall_AAC_RockWool_Cold','Outdoors',[(0,0,0),(w,0,0),(w,0,h),(0,0,h)]),
      'North':('Wall','CN_ExteriorWall_AAC_RockWool_Cold','Outdoors',[(w,d,0),(0,d,0),(0,d,h),(w,d,h)]),
      'East':('Wall','CN_ExteriorWall_AAC_RockWool_Cold',side,[(w,0,0),(w,d,0),(w,d,h),(w,0,h)]),
      'West':('Wall','CN_ExteriorWall_AAC_RockWool_Cold',side,[(0,d,0),(0,0,0),(0,0,h),(0,d,h)]),
    }
    for name,(typ,cons,bc,pts) in surfaces.items():
        rows.append(['BuildingSurface:Detailed',name,typ,cons,'living_unit1','',bc,'',
            'SunExposed' if bc=='Outdoors' else 'NoSun','WindExposed' if bc=='Outdoors' else 'NoWind',
            'autocalculate','4',*[f'{x:.9f}' for p in pts for x in p]])
    windows=[]
    for side_name in ('South','North','East','West') if kind=='detached' else ('South','North'):
        width=w if side_name in ('South','North') else d
        name='Window_'+side_name;windows.append(name)
        rows.append(['Window',name,'CN_LowE_Insulated_Window_Cold',side_name,'','1',
                     f'{width*.2:.9f}','0.8',f'{width*.6:.9f}','1.4'])
    rows.append(['WindowShadingControl','Shades-living_unit1','living_unit1','1','InteriorBlind',
        'CN_LowE_Insulated_Window_Blinds_Cold','OnIfScheduleAllows','shading_2012iecc','','Yes','No',
        '','','','','','Sequential',*windows])
    return '! EB regional research prototype v1; see catalog.json for assumptions.\n'+render(rows)

def fetch_station(station):
    key,province,city,relative=station
    folder=OUT/'weather'/key;folder.mkdir(parents=True,exist_ok=True)
    url=URL+relative
    provenance=folder/'source.json'
    if provenance.exists() and json.loads(provenance.read_text()).get('url') != url:
        raise ValueError('Station ID already belongs to a different source URL: '+key)
    if not provenance.exists():
        req=urllib.request.Request(url,headers={'User-Agent':'EnergyBridge research resource verification'})
        payload=urllib.request.urlopen(req,timeout=45).read()
        with zipfile.ZipFile(io.BytesIO(payload)) as archive:
            for suffix,name in (('.epw','weather.epw'),('.ddy','design.ddy')):
                names=[n for n in archive.namelist() if n.lower().endswith(suffix)]
                if len(names)!=1:raise ValueError((key,suffix,names))
                (folder/name).write_bytes(archive.read(names[0]))
        provenance.write_text(json.dumps({'url':url,'archive_sha256':hashlib.sha256(payload).hexdigest()},indent=2)+'\n')
    epw=folder/'weather.epw';ddy=folder/'design.ddy'
    lines=epw.read_text(errors='replace').splitlines();loc=lines[0].split(',')
    if len(lines)!=8768 or loc[0]!='LOCATION':raise ValueError('Invalid annual EPW '+key)
    if not any(r[0].lower()=='sizingperiod:designday' for r in idf_objects(ddy.read_text(errors='replace'))):
        raise ValueError('Missing design days '+key)
    return {'id':key,'province':province,'city':city,'station_name':loc[1],'wmo':loc[5],
      'latitude':float(loc[6]),'longitude':float(loc[7]),'timezone':float(loc[8]),
      'epw':str(epw.relative_to(PROJECT)),'epw_sha256':sha(epw),
      'ddy':str(ddy.relative_to(PROJECT)),'ddy_sha256':sha(ddy),
      'source_url':url,'series':'CSWD','match':'explicit_city_station_not_actual_home_weather',
      'status':'candidate'}

def main():
    parser=argparse.ArgumentParser();parser.add_argument('--models-only',action='store_true');a=parser.parse_args()
    if (OUT/'catalog.json').exists():
        from resource_versions import freeze
        freeze(OUT/'catalog.json')
    OUT.mkdir(exist_ok=True);(OUT/'models').mkdir(exist_ok=True)
    models=[]
    for kind,floor in [('apartment',f) for f in ('ground','middle','top')]+[('detached','whole'),('rowhouse','whole')]:
        for band,representative in AREA.items():
            # Two distinct, declared area bases; never treat gross area as usable.
            for basis,ratio in [('usable',1.),('gross',.8)]:
                area=representative*ratio;key=f'{kind}_{floor}_{band}_{basis}'
                path=OUT/'models'/(key+'.idf');path.write_text(model(kind,floor,area))
                models.append({'id':key,'kind':kind,'floor':floor,'area_band':band,'area_basis':basis,
                  'reported_band_representative_m2':representative,'gross_to_usable_ratio':ratio,
                  'indoor_area_m2':area,'idf':str(path.relative_to(PROJECT)),'sha256':sha(path),
                  'status':'candidate','match':'type_area_boundary_research_approximation'})
    weather=[]
    if not a.models_only:
        with ThreadPoolExecutor(max_workers=3) as pool:
            for row in pool.map(fetch_station,STATIONS):weather.append(row);print(row['id'],'download verified',flush=True)
    catalog={'version':'eb.regional_resources.v1','source_idf_sha256':sha(BASE),
      'builder_sha256':sha(__file__),'weather':weather,'models':models,
      'assumptions':['单居住热区、2.8米层高、南北朝向的矩形等效住宅；不重建真实户型。',
        '公寓及联排住宅侧墙按相邻空间等温处理；公寓楼板按所报楼层位置设置。',
        '围护结构材料及冷热源、热水设备继承原EB天津模型，未按建筑年代或当地存量住宅校准。',
        '取消独立住宅阁楼及对应AirflowNetwork/旧遮阳几何，采用闭合的住宅单元几何；不模拟阁楼风管漏风。',
        '面积区间采用代表值；建筑面积转室内面积时暂用0.8研究假设，不作为用户实测面积。',
        'ge160档采用180平方米代表值，不表示覆盖任意大小住宅。',
        '最大预热天数增至60，保持原收敛容差；预热不作为问卷的比较日。'],
      'readiness':'candidate_until_real_ep_matrix_validation'}
    (OUT/'catalog.json').write_text(json.dumps(catalog,ensure_ascii=False,indent=2)+'\n')
    print('Generated',len(models),'prototype variants;',len(weather),'weather stations.')

if __name__=='__main__':main()
