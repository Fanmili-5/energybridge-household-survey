"""Acquire missing official EnergyPlus CSWD files, verify actual EPW headers.
No substitution of station metadata or nearest-location automatic bindings.
"""
import concurrent.futures,csv,hashlib,io,json,urllib.request,zipfile
from pathlib import Path
OUT=Path(__file__).resolve().parent.parent
STATIONS=['CHN_Jilin.Baicheng.509360_CSWD','CHN_Chongqing.Youyang.576330_CSWD',
 'CHN_Anhui.Anqing.584240_CSWD','CHN_Xinjiang.Yanqi.515670_CSWD',
 'CHN_Jiangxi.Yushan.586340_CSWD','CHN_Liaoning.Zhangwu.542360_CSWD','CHN_Xizang.Lhasa.555910_CSWD',
 'CHN_Xinjiang.Uygur.Yanqi.515670_CSWD','CHN_Xizang.Zizhiqu.Lhasa.555910_CSWD','CHN_Tibet.Lhasa.555910_CSWD']
def sha(data):return hashlib.sha256(data).hexdigest()
def main():
    from evidence_guard import ensure_unsealed
    ensure_unsealed(OUT)
    folder=OUT/'raw/weather';folder.mkdir(parents=True,exist_ok=True)
    def fetch(key):
        url=f'https://energyplus-weather.s3.amazonaws.com/asia_wmo_region_2/CHN/{key}/{key}.zip'
        path=folder/(key+'.epw');manifest=path.with_suffix('.manifest.json')
        if path.exists() and manifest.exists():
            m=json.loads(manifest.read_text());assert sha(path.read_bytes())==m['epw_sha256'];return m
        try:
            payload=urllib.request.urlopen(urllib.request.Request(url,headers={'User-Agent':'EnergyBridge primary-source evidence audit'}),timeout=40).read()
            archive=zipfile.ZipFile(io.BytesIO(payload));names=[n for n in archive.namelist() if n.lower().endswith('.epw')];assert len(names)==1
            data=archive.read(names[0]);header=next(csv.reader([data.decode('utf-8-sig',errors='replace').splitlines()[0]]));assert header[0]=='LOCATION' and header[4]=='CSWD' and header[5] in key
            path.write_bytes(data);m={'station_key':key,'source_zip_url':url,'source_zip_sha256':sha(payload),'epw_sha256':sha(data),'EPW_header':header,
               'download_date_HKT':'2026-10-06','weather_type':'CSWD_reference_typical_hourly_year;not_actual2020_or2021_weather',
               'native_or_household_matching_admitted_by_download':False}
            manifest.write_text(json.dumps(m,ensure_ascii=False,indent=2)+'\n');return m
        except Exception as e:return {'station_key':key,'source_zip_url':url,'download_error':str(e),'matched':False}
    with concurrent.futures.ThreadPoolExecutor(4) as pool:results=list(pool.map(fetch,STATIONS))
    (OUT/'WEATHER_GAP_ACQUISITION.json').write_text(json.dumps({'attempts':results,'files_header_verified':sum('epw_sha256' in r for r in results),'failed':sum('download_error' in r for r in results)},ensure_ascii=False,indent=2)+'\n')
    print(json.dumps({'verified':sum('epw_sha256' in r for r in results),'failures':[r for r in results if 'download_error' in r]},ensure_ascii=False))
if __name__=='__main__':main()
