"""Cache/read the primary census scheme without installing extra libraries."""
from html.parser import HTMLParser
import requests
from common import *
class Text(HTMLParser):
 def __init__(self):super().__init__();self.parts=[];self.skip=0
 def handle_starttag(self,tag,attrs):
  if tag in ['style','script']:self.skip+=1
 def handle_endtag(self,tag):
  if tag in ['style','script']:self.skip=max(0,self.skip-1)
 def handle_data(self,data):
  if not self.skip and data.strip():self.parts.append(data.strip())
def main():
 guard();url='https://www.fuzhou.gov.cn/book/fztjnj/2020rkpcnj/fzrp2020/htms/347.htm';path=OUT/'raw/census2020_scheme_Fuzhou.html'
 if not path.exists():
  r=requests.get(url,timeout=60);r.raise_for_status();path.write_bytes(r.content)
 t=Text();t.feed(path.read_text(encoding='utf-8-sig'));plain='\n'.join(t.parts);assert '1.33' in plain and '厨房' in plain
 (OUT/'raw/census2020_scheme_Fuzhou.txt').write_text(plain)
 save(OUT/'raw/census2020_scheme_Fuzhou.manifest.json',{'url':url,'date_HKT':'2026-10-06','sha256':sha(path),'original_author':'NBS and State Council Seventh Census Office',
  'official_host':'Fuzhou census yearbook','cached_html_and_extracted_text_read':True,'encoding':'utf-8-sig',
  'context':'H6/H7 plus long-form facility definitions;official control source does not identify actual households or geometric common-area fraction'})
 print({'cached_bytes':path.stat().st_size,'sha256':sha(path)})
if __name__=='__main__':main()
