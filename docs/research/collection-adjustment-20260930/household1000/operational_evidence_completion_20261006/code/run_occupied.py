"""Run and read all fixed occupied reference inputs; retain every failure."""
import concurrent.futures,collections,re,sqlite3,subprocess
from common import *
ENGINE=Path('/Applications/EnergyPlus-24-1-0/energyplus')
def run(r):
 hid=r['household_id'];folder=OUT/'occupied_runs'/hid;folder.mkdir(parents=True,exist_ok=True);p=OUT/r['IDF_path'];assert sha(p)==r['IDF_sha256']
 s=subprocess.run([str(ENGINE),'-w',r['weather']['path'],'-d',str(folder),str(p)],capture_output=True,text=True,timeout=300);(folder/'console.txt').write_text(s.stdout+'\n'+s.stderr);err=(folder/'eplusout.err').read_text();sf=re.findall(r'\*\*\s*(?:Severe|Fatal)\s*\*\*([^\n]*)',err)
 result={'household_id':hid,'returncode':s.returncode,'severe_fatal':sf,'warnings':re.findall(r'\*\*\s*Warning\s*\*\*([^\n]*)',err),'IDF_path':r['IDF_path'],'IDF_sha256':sha(p),'weather_path':r['weather']['path'],'weather_sha256':sha(r['weather']['path']),'engine_sha256':sha(ENGINE)}
 if s.returncode or sf:return result
 sql=folder/'eplusout.sql';db=sqlite3.connect(sql);data=db.execute('SELECT d.KeyValue,d.Name,t.TimeIndex,r.Value FROM ReportData r JOIN ReportDataDictionary d USING(ReportDataDictionaryIndex) JOIN Time t USING(TimeIndex) WHERE COALESCE(t.WarmupFlag,0)=0 ORDER BY t.TimeIndex,d.KeyValue').fetchall();db.close();sums=collections.defaultdict(float);temps=[]
 for key,var,i,v in data:
  if var in ['Zone People Occupant Count','Zone People Total Heating Rate','Zone People Sensible Heating Rate','Zone People Latent Gain Rate']:sums[var,i]+=v
  if var=='Zone Mean Air Temperature':temps.append(v)
 counts=[v for (k,i),v in sums.items() if k=='Zone People Occupant Count'];assert counts and max(abs(v-r['N_conserved']) for v in counts)<1e-9
 result.update({'roster_count_per_reported_step':r['N_conserved'],'roster_count_error_max':max(abs(v-r['N_conserved']) for v in counts),'reported_zone_temperature_range_C':[min(temps),max(temps)],'SQL_path':str(sql.relative_to(OUT)),'SQL_sha256':sha(sql),'not_wholehome_or_measured_energy_validation':True})
 return result
def main():
 guard();records=read(OUT/'OCCUPIED_REFERENCE_BINDINGS1000.json')['records'];selected=records[:2] if '--first2' in sys.argv else records;res=[]
 with concurrent.futures.ThreadPoolExecutor(4) as pool:
  for i,r in enumerate(pool.map(run,selected)):
   res.append(r)
   if (i+1)%100==0:print({'occupied_inputs_completed':i+1,'planned':len(selected)},flush=True)
 save(OUT/('OCCUPIED_FIRST2_DEVELOPMENT.json' if '--first2' in sys.argv else 'OCCUPIED_RUNTIME_RESULTS1000.json'),{'runs':res,'inputs_run':len(res),'failures':[r for r in res if r['returncode'] or r['severe_fatal']],'purpose':'numerical/count conservation check of declared allhome quiet reference;not annual national or field validation'})
 print({'run':len(res),'failures':sum(bool(r['returncode'] or r['severe_fatal']) for r in res),'warnings':sum(len(r['warnings']) for r in res)},flush=True)
if __name__=='__main__':main()
