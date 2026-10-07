"""Extract native PDF vector performance lines, not guessed pixel values.
Restrict the documented rated-frequency right-hand branch; raw vector data,
axis anchors and visual page readback are retained for independent checking.
"""
import numpy as np
from pypdf import PdfReader
from pypdf.generic import ContentStream
from common import *
def strokes(page,reader):
 ctm=np.eye(3);stack=[];path=[];result=[];width=1.
 def point(x,y):return (ctm@np.array([float(x),float(y),1.]))[:2].tolist()
 for vals,op in ContentStream(page['/Contents'],reader).operations:
  if op==b'q':stack.append((ctm.copy(),width))
  elif op==b'Q':ctm,width=stack.pop()
  elif op==b'cm':
   a,b,c,d,e,f=map(float,vals);ctm=ctm@np.array([[a,c,e],[b,d,f],[0,0,1.]])
  elif op==b'w':width=float(vals[0])
  elif op==b'm':path=[point(*vals)]
  elif op==b'l':path.append(point(*vals))
  elif op==b'c':path.append(point(*vals[-2:]))
  elif op in [b'S',b's']:
   if len(path)>1:result.append({'vertices_pdfpoints':path[:],'line_width_raw':width})
   path=[]
  elif op in [b'f',b'f*',b'n']:path=[]
 return result
def main():
 guard();pdf=OUT/'raw/Mitsubishi_OBH789.pdf';reader=PdfReader(pdf);results=[]
 for page_number,roi,sign in [(15,[210,90,470,214],-1),(16,[185,640,440,745],1)]:
  paths=strokes(reader.pages[page_number-1],reader);roi_paths=[];sloped=[]
  for p in paths:
   vv=p['vertices_pdfpoints']
   if all(roi[0]<=x<=roi[2] and roi[1]<=y<=roi[3] for x,y in vv):
    roi_paths.append(p)
    if len(vv)==2:
     (x,y),(xx,yy)=vv
     if xx-x>60 and sign*(yy-y)>10 and p['line_width_raw']>.6:sloped.append(p)
  results.append({'PDF_page1based':page_number,'ROI_pdfpoints':roi,'all_strokes_in_ROI':roi_paths,'candidate_performance_lines':sloped})
 save(OUT/'HVAC_PDF_VECTOR_EXTRACTION.json',{'primary_PDF':'raw/Mitsubishi_OBH789.pdf','primary_sha256':sha(pdf),'page_vector_data':results,'not_OEM_auto_controller_or_partload_governor':True})
 print([{'page':r['PDF_page1based'],'candidate_count':len(r['candidate_performance_lines']),'lines':r['candidate_performance_lines']} for r in results])
if __name__=='__main__':main()
