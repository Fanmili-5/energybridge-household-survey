#!/usr/bin/env python3
"""Cache allowlisted primary-source public reports; never downloads microdata."""
import concurrent.futures
import hashlib
import json
from pathlib import Path
import urllib.request

HERE=Path(__file__).resolve().parent
CENSUS='https://www.stats.gov.cn/sj/pcsj/rkpc/7rp/zk/html/'
TABLES=['A0108a','A0109a','A0803a','B0901a','B0902a','B0903a','B0904a','B0905a','B0906a','B0913a']
SOURCES=[(t+'.xls',CENSUS+t+'.xls') for t in TABLES]+[
 ('timeuse_2024_1.html','https://www.stats.gov.cn/sj/zxfb/202410/t20241031_1957217.html'),
 ('timeuse_2024_2.html','https://www.stats.gov.cn/xxgk/sjfb/zxfb2020/202410/t20241031_1957216.html'),
 ('timeuse_2024_3.html','https://www.stats.gov.cn/xxgk/sjfb/zxfb2020/202410/t20241031_1957215.html'),
 ('CHFS_2026_release.html','https://chfs.swufe.edu.cn/info/1041/4171.htm'),
 ('CHFS_application.html','https://chfs.swufe.edu.cn/sjzx/sjsq.htm'),
 ('CHFS_use_terms.html','https://chfs.swufe.edu.cn/info/1041/2131.htm'),
 ('CRECS_about.html','https://crecs.ruc.edu.cn/jj/gyCRECS/index.htm'),
 ('haier_HW9_B176U1.html','https://www.haier.com/kitchen_appliances/xwj/20180710_91497.shtml')]

def fetch(item):
 name,url=item;p=HERE/'raw'/name;p.parent.mkdir(parents=True,exist_ok=True)
 if p.exists():
  b=p.read_bytes();status='cached'
 else:
  try:
   req=urllib.request.Request(url,headers={'User-Agent':'Mozilla/5.0'})
   with urllib.request.urlopen(req,timeout=25) as r:
    b=r.read();content_type=r.headers.get('Content-Type','')
   if name.endswith('.xls') and not b.startswith(bytes.fromhex('d0cf11e0a1b11ae1')):
    return {'name':name,'url':url,'status':'unexpected_not_xls','bytes':len(b),'content_type':content_type}
   p.write_bytes(b);status='downloaded'
  except Exception as exc:return {'name':name,'url':url,'status':'access_error','error':str(exc)}
 return {'name':name,'url':url,'status':status,'path':'raw/'+name,'bytes':len(b),'sha256':hashlib.sha256(b).hexdigest(),
         'retrieved_date_HKT':'2026-10-01','microdata':False}

if __name__=='__main__':
 with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
  rows=list(pool.map(fetch,SOURCES))
 out=HERE/'PUBLIC_DOWNLOADS.json'
 if out.exists():raise RuntimeError('immutable download manifest already exists')
 out.write_text(json.dumps({'batch_id':'CITY1000_PUBLIC_DOWNLOADS_20261001_V1','sources':rows},ensure_ascii=False,indent=2)+'\n')
 print(json.dumps({'statuses':__import__('collections').Counter(r['status'] for r in rows),
                   'not_cached':[r for r in rows if r['status'] not in ('downloaded','cached')]},ensure_ascii=False))
