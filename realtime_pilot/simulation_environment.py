"""Resolve and freeze questionnaire-based simulation inputs before any model call."""
from copy import deepcopy
from functools import lru_cache
import csv
import json
from pathlib import Path
import random
from common import STUDY, UPSTREAM, digest, file_hash
from native_assets import idf_objects

VERSION='eb.simulation_environment.v1'
QUESTION_IDS=('X_REGION','X_CITY','X_BUILDING','X_AREA','X_AREA_BASIS','X_FLOOR')
CATALOG=STUDY/'simulation_resources/catalog.json'

@lru_cache(maxsize=2)
def _catalog(path,mtime_ns,size):
    return json.loads(Path(path).read_text())

def catalog():
    stat=CATALOG.stat()
    return _catalog(str(CATALOG),stat.st_mtime_ns,stat.st_size)

def answer(profile,qid):
    cell=profile.get(qid,{})
    return cell.get('value') if cell.get('response_status')=='answered' else None

def city_key(value):
    return str(value or '').strip().removesuffix('市')

def asset(path,sha):
    # Paths come from the server's verified catalog, never from participant input.
    p=(STUDY/path).resolve()
    if STUDY.resolve() not in p.parents or not p.is_file() or file_hash(p)!=sha:
        raise ValueError('模拟资源校验失败，请联系研究人员')
    return p

def inspect_profile(profile):
    """Readiness preview; answers remain saveable even if resources are missing."""
    c=catalog();reported={qid:answer(profile,qid) for qid in QUESTION_IDS}
    issues=[]
    for qid,label in [('X_REGION','省级地区'),('X_CITY','常住城市'),('X_BUILDING','住宅类型'),
                      ('X_AREA','面积区间'),('X_AREA_BASIS','面积口径')]:
        if not reported[qid]:issues.append('请补充'+label)
    kind=reported['X_BUILDING'];floor=reported['X_FLOOR'] if kind=='apartment' else 'whole'
    if kind=='apartment' and not floor:issues.append('请补充楼层位置')
    model=next((r for r in c['models'] if r['kind']==kind and r['floor']==floor and
                r['area_band']==reported['X_AREA'] and r['area_basis']==reported['X_AREA_BASIS']
                and r['status']=='verified'),None)
    candidates=[r for r in c['weather'] if r['province']==reported['X_REGION'] and r['status']=='verified'
                and (model is None or c.get('validated_dates',{}).get(model['id']+'|'+r['id']))]
    weather=next((r for r in candidates if r['city'] and city_key(r['city'])==city_key(reported['X_CITY'])),None)
    match_method='city_station'
    if weather is None and reported['X_CITY']:
        representative=c.get('province_representatives',{}).get(reported['X_REGION'])
        weather=next((r for r in candidates if r['id']==representative),None)
        match_method='provincial_representative_proxy'
    if reported['X_CITY'] and not weather:issues.append('所选地区尚无已验证气象组合；资料可保存，暂不生成方案，请勿改填其他地区')
    if kind and reported['X_AREA'] and reported['X_AREA_BASIS'] and floor and not model:
        issues.append('该住房组合尚无已验证住宅原型；资料可保存，暂不生成方案')
    if weather and model and not c.get('validated_dates',{}).get(model['id']+'|'+weather['id']):
        issues.append('该住房与天气组合尚未通过仿真验证；资料可保存，暂不生成方案')
    return {'status':'ready' if not issues else 'unavailable','issues':issues,
        'reported':reported,'weather_id':weather['id'] if weather else None,
        'model_id':model['id'] if model else None,
        'weather_match':{'method':match_method,'reported_city':reported['X_CITY'],
            'station_id':weather['id'] if weather else None,'station_name':weather['station_name'] if weather else None,
            'uses_household_coordinates':False,'nearest_station_claim':False},
        'summary':(f"{weather['city'] or weather['station_name']}典型气象"+('（省内代表站）' if match_method=='provincial_representative_proxy' else '')+f" · {model['indoor_area_m2']:g}㎡室内研究原型" if weather and model else None),
        'assumptions':deepcopy(c['assumptions'])+(['未匹配到同城站点，本次使用省内代表站作研究近似；不表示最近站或您所在地实测天气。'] if weather and match_method=='provincial_representative_proxy' else [])}

def resolve(profile,seed,context=None):
    check=inspect_profile(profile)
    if check['status']!='ready':raise ValueError('；'.join(check['issues']))
    c=catalog()
    weather=next(r for r in c['weather'] if r['id']==check['weather_id'])
    model=next(r for r in c['models'] if r['id']==check['model_id'])
    for row,pathkey,hashkey in [(weather,'epw','epw_sha256'),(weather,'ddy','ddy_sha256'),(model,'idf','sha256')]:
        asset(row[pathkey],row[hashkey])
    # New intakes freeze an annual date before answers. Legacy fixtures retain
    # their verified summer pool; existing stored requests are never relabelled.
    dates=c['validated_dates'][model['id']+'|'+weather['id']]
    from date_sampling import sample,annual_sample
    selected,sampling=annual_sample(STUDY/weather['epw'],context) if context is not None else sample(STUDY/weather['epw'],dates,seed)
    result={'version':VERSION,'resource_catalog_sha256':file_hash(CATALOG),
      'weather':deepcopy(weather),'building':deepcopy(model),'reported_housing':check['reported'],
      'weather_match':check['weather_match'],
      'simulation_start_date':selected,'simulation_days':1,
      'date_sampling':sampling,
      'assumptions':check['assumptions'],'calibrated_to_household':False,
      'envelope_and_hvac_match':'shared_author_research_parameters_not_local_stock',
      'tariff_scope':'fixed_EB_Tianjin_normalized_TOU_experiment_not_local_real_tariff'}
    result['environment_hash']=digest(result)
    return result

def verify(environment):
    body={k:v for k,v in environment.items() if k!='environment_hash'}
    if environment.get('version')!=VERSION or environment.get('environment_hash')!=digest(body):
        raise ValueError('本次模拟环境记录已变化')
    from resource_versions import resolve_catalog,safe_asset
    catalog_path,base=resolve_catalog(CATALOG,environment['resource_catalog_sha256'])
    c=json.loads(catalog_path.read_text())
    for group,name in [('weather','weather'),('models','building')]:
        row=environment[name]
        if not any(r==row and r['status']=='verified' for r in c[group]):
            raise ValueError('模拟资源不属于已验证目录')
    weather=environment['weather'];model=environment['building']
    from date_sampling import ANNUAL_VERSION,annual_sample
    sampling=environment.get('date_sampling',{})
    if sampling.get('version')==ANNUAL_VERSION:
        if not c.get('validated_dates',{}).get(model['id']+'|'+weather['id']):
            raise ValueError('此住宅与天气组合缺少基础验证')
        selected,expected=annual_sample(safe_asset(base,weather['epw'],weather['epw_sha256']),sampling.get('questionnaire_context'))
        if selected!=environment['simulation_start_date'] or expected!=sampling or environment.get('simulation_days')!=1:
            raise ValueError('全年日期抽样记录不一致')
    elif environment['simulation_start_date'] not in c.get('validated_dates',{}).get(model['id']+'|'+weather['id'],[]):
        raise ValueError('此日期未通过该住宅与天气组合的验证')
    return (safe_asset(base,model['idf'],model['sha256']),safe_asset(base,weather['epw'],weather['epw_sha256']),
            safe_asset(base,weather['ddy'],weather['ddy_sha256']))

def render(rows):
    return '\n\n'.join(r[0]+',\n'+''.join('    '+v+(';' if i==len(r)-2 else ',')+'\n'
        for i,v in enumerate(r[1:])) for r in rows)+'\n'

def localize_idf(idf,epw,ddy):
    """Pair geometry with the station's design conditions and 2 m ground series."""
    rows=idf_objects(Path(idf).read_text())
    lines=Path(epw).read_text(errors='replace').splitlines()
    location=next(csv.reader([lines[0]]))
    ground=next(csv.reader([lines[3]]));temperatures=None
    for index in range(int(ground[1])):
        offset=2+index*16
        if abs(float(ground[offset])-2)<1e-6:temperatures=ground[offset+4:offset+16]
    if temperatures is None:raise ValueError('天气文件缺少已审核的2米月地温')
    design=[r for r in idf_objects(Path(ddy).read_text(errors='replace')) if r[0].lower()=='sizingperiod:designday']
    heat=next((r for r in design if '99.6%' in r[1] and r[4].lower()=='winterdesignday'),None)
    cool=next((r for r in design if '.4%' in r[1] and 'DB=>MWB' in r[1] and r[4].lower()=='summerdesignday'),None)
    if not heat or not cool:raise ValueError('天气资源缺少配套供暖/制冷设计日')
    remove={'site:location','site:groundtemperature:buildingsurface','sizingperiod:designday'}
    rows=[r for r in rows if r[0].lower() not in remove]
    rows += [['Site:Location',location[1],*location[6:10]],
             ['Site:GroundTemperature:BuildingSurface',*temperatures],heat,cool]
    Path(idf).write_text(render(rows))
    return {'source':'station_EPWs_2m_ground_and_companion_DDY',
            'weather_sha256':file_hash(epw),'design_days_sha256':file_hash(ddy),
            'ground_temperatures_c':list(map(float,temperatures)),
            'heating_design_day':heat[1],'cooling_design_day':cool[1]}

def bind_scenario(scenario,profile,seed,context=None):
    env=resolve(profile,seed,context)
    scenario['environment']=env
    scenario['simulation_start_date']=env['simulation_start_date']
    scenario['building']={'source':env['building']['id'],'binding':'questionnaire_matched_research_prototype',
                         'calibrated_to_household':False,'indoor_area_m2':env['building']['indoor_area_m2']}
    scenario['weather']={'file':env['weather']['epw'],'city':env['weather']['city'],
                         'date':env['simulation_start_date'],'actual_household_weather':False}
    scenario['facts']=[
      '两份安排使用相同的住宅、日期和天气；日常对照与EB调整安排均按您填写的设备和习惯生成。',
      f"您填报的城市为{env['reported_housing']['X_CITY']}；本次采用{env['weather']['city'] or env['weather']['station_name']}站的{env['simulation_start_date'][5:]}典型气象"+('（省内代表站近似）' if env['weather_match']['method']=='provincial_representative_proxy' else '')+'。住宅按房型、面积和楼层匹配研究原型，并非您家实测预测。',
      '住宅材料和冷热源沿用研究参数，未按当地住宅或建筑年代校准；采用原EB天津分时价格权重，不是您所在地的人民币电价。']
    return scenario
