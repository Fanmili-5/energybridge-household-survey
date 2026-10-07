"""Cache only public primary scientific/technical evidence and its hashes."""
import concurrent.futures,hashlib,json
from pathlib import Path
import requests
OUT=Path(__file__).resolve().parent.parent
SOURCES={
 'Haier_AC.html':'https://www.haier.com/air_conditioners/20130503_99020.shtml',
 'Haier_washer.html':'https://www.haier.com/laundry/20120229_97977.shtml',
 'Haier_heater.html':'https://www.haier.com/water_heaters/drsq/20210819_167043.shtml',
 'Haier_fridge.pdf':'https://file.c.haier.net/obs-cpzx/materialprod/2023/12/21/1737726717934243840/e6dcd3e59b3e573efb4fe2c23fb6ea01.pdf',
 'CHEAA_washer_measurement.pdf':'https://www.cheaa.org/upload/files/2016/2/4141546561.pdf',
 'LBNL_window_SC.html':'https://hes-documentation.lbl.gov/calculation-methodology/calculation-of-energy-consumption/heating-and-cooling-calculation/doe2-inputs-assumptions-and-calculations/the-doe2-model',
 'LBNL_WINDOW4.pdf':'https://escholarship.org/content/qt64k6f52j/qt64k6f52j.pdf',
 'ResStock2024_1.pdf':'https://www.nrel.gov/docs/fy24osti/88109.pdf',
 'Partial_identification_Ahfock2016.pdf':'https://digital.library.adelaide.edu.au/server/api/core/bitstreams/3826e064-edd5-4d60-9778-31a5f8697748/content',
 'IKEA_TUFFING.html':'https://www.ikea.com/gb/en/p/tuffing-bunk-bed-frame-dark-grey-00239233/',
 'NBS_scheme.pdf':'https://www.stats.gov.cn/sj/pcsj/rkpc/7rp/zk/html/fu06.pdf'}
SOURCES.update({'Miele_WTD160_manual.pdf':'https://media.miele.com/downloads/83/d4/01_C7F12828BC641EDEA4EAE0B7FDA083D4.pdf',
 'LBNL_WINDOW4_primary.pdf':'https://eta-publications.lbl.gov/sites/default/files/33943.pdf'})
def get(item):
 name,url=item;p=OUT/'raw'/name
 if p.exists():data=p.read_bytes();status='existing_cache'
 else:
  try:r=requests.get(url,timeout=45);r.raise_for_status();data=r.content
  except requests.RequestException as e:return {'name':name,'URL':url,'retrieved':False,'error':str(e)}
  if name.endswith('.pdf') and not data.startswith(b'%PDF'):return {'name':name,'URL':url,'retrieved':False,'error':'not_PDF_response'}
  p.write_bytes(data);status='retrieved'
 return {'name':name,'URL':url,'retrieved':True,'status':status,'path':str(p),'bytes':len(data),'sha256':hashlib.sha256(data).hexdigest(),'retrieved_HKT_date':'2026-10-06'}
def main():
 if (OUT/'PACKAGE_MANIFEST.json').exists():raise SystemExit('sealed')
 with concurrent.futures.ThreadPoolExecutor(4) as pool:results=list(pool.map(get,SOURCES.items()))
 (OUT/'PRIMARY_SOURCE_CACHE.json').write_text(json.dumps({'sources':results,'not_a_systematic_literature_review':True},ensure_ascii=False,indent=2)+'\n');print(json.dumps(results,ensure_ascii=False))
if __name__=='__main__':main()
