"""Versioned source-weather replacement before a new paired execution.

Neither frozen plans nor household schedules are changed. A replacement must
be an independently identified EPW for the same station; no outcome is read.
Original exports and source weather stay intact. All dates using a changed
household weather source are recompiled (including water-mains correlation).
"""
import copy
import csv
import math
import shutil
from pathlib import Path
from benchmark.ab_generation.common import read,save,sha,seal,verify


def location(path):
    rows=list(csv.reader(Path(path).read_text().splitlines()))
    head=rows[0]
    if head[0]!='LOCATION' or len(rows)!=8768:raise ValueError('COMPLETE_NONLEAP_EPW_REQUIRED')
    return {'station':head[5],'latitude':float(head[6]),'longitude':float(head[7]),'elevation_m':float(head[9])},rows[8:]


def validate_replacement(old,new):
    a,_=location(old);b,rows=location(new)
    if a['station']!=b['station']:raise ValueError('WEATHER_STATION_CHANGED')
    lat1,lat2=map(math.radians,(a['latitude'],b['latitude']))
    dp=lat2-lat1;dl=math.radians(b['longitude']-a['longitude'])
    km=6371*2*math.asin(min(1,math.sqrt(math.sin(dp/2)**2+math.cos(lat1)*math.cos(lat2)*math.sin(dl/2)**2)))
    # Explicit conservative reference-data matching limits, not a claim of
    # meteorological equivalence or a literature-derived universal tolerance.
    if km>50 or abs(a['elevation_m']-b['elevation_m'])>100:raise ValueError('WEATHER_LOCATION_REQUIRES_SEPARATE_REVIEW')
    for row in rows:
        db,dew,rh,pressure=map(float,(row[6],row[7],row[8],row[9]))
        if not all(map(math.isfinite,(db,dew,rh,pressure))) or not(-90<db<70 and -100<dew<70 and 0<=rh<=100 and dew<=db+.2 and 31000<pressure<120000):
            raise ValueError('REPLACEMENT_WEATHER_DOMAIN_INVALID')
    hours=[(int(r[1]),int(r[2]),int(r[3]))for r in rows]
    import datetime as dt
    expected=[(d.month,d.day,h)for i in range(365)for d in [dt.date(2025,1,1)+dt.timedelta(days=i)]for h in range(1,25)]
    if hours!=expected:raise ValueError('REPLACEMENT_WEATHER_TIMELINE_INVALID')
    return {'old_location':a,'new_location':b,'horizontal_distance_km':km,
            'matching_limits_design_setting':{'max_horizontal_km':50,'max_elevation_difference_m':100},
            'full_year_hours':8760,'passed':True,'same_weather_realization_claim':False}


def rebind(exported,replacements,out):
    exported,out=map(lambda p:Path(p).resolve(),(exported,out));original=verify(exported)
    checked={}
    for old_hash,source in replacements.items():
        new=Path(source['path']).resolve()
        if sha(new)!=source['sha256'] or not source['source_url'].startswith('https://'):raise ValueError('REPLACEMENT_SOURCE_UNBOUND')
        old=exported/'resources/inputs/weather'/(old_hash+'.epw')
        if sha(old)!=old_hash:raise ValueError('ORIGINAL_WEATHER_CHANGED')
        checked[old_hash]={**source,'quality':validate_replacement(old,new)}
    shutil.copytree(exported,out)
    resources=out/'resources';homes={};lineage=[]
    for p in sorted((resources/'inputs/homes').glob('*.json.gz')):
        pack=read(p);old=pack['weather_sha256']
        if old not in checked:continue
        source=checked[old];new_hash=source['sha256'];new_path='inputs/weather/'+new_hash+'.epw'
        shutil.copyfile(source['path'],resources/new_path)
        before=copy.deepcopy(pack);pack.update(weather=new_path,weather_sha256=new_hash)
        assert {k:v for k,v in before.items()if k not in ('weather','weather_sha256')}=={k:v for k,v in pack.items()if k not in ('weather','weather_sha256')}
        save(p,pack);homes[pack['household_id']]={'path':str(p.relative_to(resources)),'sha256':sha(p)}
        lineage.append({'household_id':pack['household_id'],'old_sha256':old,'new_sha256':new_hash,'source_url':source['source_url'],'quality':source['quality']})
    review=read(out/'INPUT_REVIEW500.json')
    for row in review['records']:
        if row['household_id']in homes:row['household']=homes[row['household_id']]
    save(out/'INPUT_REVIEW500.json',review)
    for name in read(out/'JOBS.json')['jobs']:
        job=read(out/name)
        paths={entry['path']:entry for entry in homes.values()}
        for source in checked.values():job['resources']['inputs/weather/'+source['sha256']+'.epw']=source['sha256']
        for row in job['pairs']:
            if row['household']['path']in paths:row['household']=paths[row['household']['path']]
        save(out/name,job)
    save(out/'WEATHER_REBINDING.json',{'schema':'eb.reference50.weather_rebinding.v1','parent_export_manifest_sha256':sha(exported/'MANIFEST.json'),
        'records':lineage,'affected_cases':sum(r['household_id']in homes for r in review['records']),
        'frozen_A_B_changed':False,'native_runs':0,'selection_by_outcomes':False,
        'scope':'different typical-year source for same station;not actual weather on the human calendar date'})
    (out/'MANIFEST.json').unlink()
    return seal(out,{k:v for k,v in original.items()if k!='files'}|{'parent_export_manifest_sha256':sha(exported/'MANIFEST.json'),'weather_rebinding_sha256':sha(out/'WEATHER_REBINDING.json')})
