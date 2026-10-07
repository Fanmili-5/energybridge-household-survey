"""Cache original expanded HVAC technical data; no mirror substitutions."""
import requests
from common import *
SOURCES={'Daikin_RXS_B_2003':'https://www.daikintech.co.uk/Data/Split-Sky-Air-Outdoor/RXS/2003/RXS-BVMB/RXS-BVMB_Databook.pdf',
 'Daikin_HK_technical104':'https://www.daikin.com.hk/admin/upload/product/download/104.pdf',
 'Mitsubishi_OBH789':'https://library.mitsubishielectric.co.uk/pdf/download_full/3756',
 'Mitsubishi_OBH788':'https://library.mitsubishielectric.co.uk/pdf/download_full/3755',
 'EnergyPlus_WaterThermalTanks24_1':'https://raw.githubusercontent.com/NREL/EnergyPlus/v24.1.0/src/EnergyPlus/WaterThermalTanks.cc',
 'BOPTEST_PNNL':'https://www.pnnl.gov/publications/building-optimization-testing-framework-boptest-simulation-based-benchmarking-control',
 'Daikin_FTXS_L_expanded':'https://www.daikinac.com/content/assets/DOC/EngineeringManuals/EDUS091128%20FTXS-L%2CFDXS-L%20Heat%20Pump%20Engineering%20Data.pdf'}
def main():
 guard();records=[]
 for key,url in SOURCES.items():
  filename={'EnergyPlus_WaterThermalTanks24_1':'WaterThermalTanks_v24_1.cc','BOPTEST_PNNL':'BOPTEST_PNNL.html'}.get(key,key+'.pdf');path=OUT/'raw'/filename
  if path.exists():records.append({'id':key,'URL':url,'path':str(path.relative_to(OUT)),'sha256':sha(path),'original_manufacturer_host':True,'retrieved':True});continue
  if '--new-only' in sys.argv and key in ['Daikin_RXS_B_2003','Daikin_HK_technical104']:continue
  try:
   r=requests.get(url,timeout=40);r.raise_for_status()
   if path.suffix=='.pdf':assert r.content.startswith(b'%PDF')
   path.write_bytes(r.content);records.append({'id':key,'URL':url,'path':str(path.relative_to(OUT)),'sha256':sha(path),'original_primary_host':True,'retrieved':True})
  except Exception as e:records.append({'id':key,'URL':url,'retrieved':False,'error':str(e)})
 if (OUT/'PRIMARY_DOWNLOADS.json').exists():
  old=read(OUT/'PRIMARY_DOWNLOADS.json')['sources'];records=old+[r for r in records if r not in old]
 save(OUT/'PRIMARY_DOWNLOADS.json',{'sources':records});print(records)
if __name__=='__main__':main()
