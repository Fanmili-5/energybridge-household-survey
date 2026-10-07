"""General EP24.1 cross-year/TMY correction; preserve sealed inputs and failed evidence."""
import calendar, concurrent.futures, datetime as dt, hashlib, json, os, re, subprocess, time
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];SOURCE=ROOT.parent/'joint_static_production_20261007_v16';ENGINE=Path('/home/hku_user3/energybridge-compute/EnergyPlus-24-1-0/energyplus')
def read(p):return json.loads(p.read_text())
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def save(p,v):p.parent.mkdir(parents=True,exist_ok=True);p.write_text(json.dumps(v,ensure_ascii=False,sort_keys=True,indent=2)+'\n')
def sql_days(path):
 import sqlite3
 db=sqlite3.connect('file:'+str(path)+'?mode=ro',uri=True)
 rows=db.execute('SELECT SimulationDays,Year,Month,Day,count(*) FROM Time WHERE WarmupFlag=0 GROUP BY SimulationDays,Year,Month,Day ORDER BY SimulationDays').fetchall();db.close();return rows
selection=read(ROOT/'SELECTION50.json');review=read(ROOT/'EP_RUN_REVIEW.json');jobs=[];mapping={}
for h in selection['records']:
 for c in h['rounds']:
  for arm in ('A','B'):
   mapping[h['household_id'],c['round_index'],arm]=(h,c)
   start=dt.date.fromisoformat(c[arm]['start_date']);end=dt.date.fromisoformat(c[arm]['end_date']);weather=Path(h['weather']['path'])
   header=next(line.split(',') for line in weather.read_text().splitlines()[:8] if line.startswith('HOLIDAYS/DAYLIGHT SAVING'))
   # WeatherManager.cc v24.1.0: cross-year start ordinal uses Gregorian leap,
   # but elapsed weather days skip it when the EPW disables leap years.
   needs_bridge=start.year!=end.year and calendar.isleap(start.year) and start.month>2 and header[1].strip().lower()=='no'
   if needs_bridge:jobs.append((h,c,arm))
def one(job):
 h,c,arm=job;src=SOURCE/c[arm]['IDF_path'];text=src.read_text();match=re.search(r'(?m)^RunPeriod,[^;]+;',text);assert match
 fields=[v.strip() for v in match.group().rstrip(';').split(',')];oldend=dt.date.fromisoformat(c[arm]['end_date']);adjusted=oldend+dt.timedelta(days=1);fields[5:8]=[str(adjusted.month),str(adjusted.day),str(adjusted.year)]
 effective=ROOT/'effective_idfs'/h['household_id']/f'{c["round_index"]:02d}_{arm}.idf';effective.parent.mkdir(parents=True,exist_ok=True);effective.write_text(text[:match.start()]+',\n  '.join(fields)+';'+text[match.end():])
 out=ROOT/'calendar_v2_runs'/h['household_id']/f'{c["round_index"]:02d}_{arm}';out.mkdir(parents=True,exist_ok=True);t0=time.monotonic()
 p=subprocess.run([str(ENGINE),'-w',h['weather']['path'],'-d',str(out),str(effective)],stdout=subprocess.PIPE,stderr=subprocess.STDOUT,text=True,env={**os.environ,'OMP_NUM_THREADS':'1'},timeout=1200);(out/'engine.log').write_text(p.stdout)
 err=(out/'eplusout.err').read_text();severe=[x.strip() for x in err.splitlines() if re.search(r'\*\*\s*(Severe|Fatal)\s*\*\*',x)]
 days=sql_days(out/'eplusout.sql') if p.returncode==0 and not severe else []
 origin=dt.date.fromisoformat(c[arm]['start_date']);expected=[(i+1,(origin+dt.timedelta(days=i)).year,(origin+dt.timedelta(days=i)).month,(origin+dt.timedelta(days=i)).day,144) for i in range(10)]
 assert days==expected,(h['household_id'],c['round_index'],arm,days,expected)
 result={'household_id':h['household_id'],'round_index':c['round_index'],'date':c['date'],'arm':arm,'runtime_pass':True,'returncode':p.returncode,'severe_fatal':severe,'warning_count':len(re.findall(r'\*\*\s*Warning\s*\*\*',err)),'elapsed_seconds':round(time.monotonic()-t0,3),'SQL_path':str((out/'eplusout.sql').relative_to(ROOT)),'SQL_sha256':sha(out/'eplusout.sql'),'source_IDF_sha256':sha(src),'effective_IDF_path':str(effective.relative_to(ROOT)),'effective_IDF_sha256':sha(effective),'calendar_input_end':adjusted.isoformat(),'intended_output_end':oldend.isoformat(),'actual_SQL_days':days,'engine_host':'school Linux','calendar_bridge_rule_sha256':sha(Path(__file__))}
 save(out/'RUN_RECORD.json',result);return result
if __name__=='__main__':
 import sys
 assert sys.platform=='linux'
 with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:fixes=list(pool.map(one,jobs))
 index={(r['household_id'],r['round_index'],r['arm']):r for r in fixes}
 current=[index.get((r['household_id'],r['round_index'],r['arm']),r) for r in review['records']]
 evidence={'rule':'EP24.1 cross-year Gregorian leap start ordinal versus nonleap TMY: extend input end by one day,then require actual10day calendar equality','primary_source':'https://github.com/NREL/EnergyPlus/blob/v24.1.0/src/EnergyPlus/WeatherManager.cc#L8184-L8228','original_day_count_failures':18,'corrected_runs':len(fixes),'source_IDFs_modified':0,'original_results_preserved':True,'records':fixes}
 save(ROOT/'CALENDAR_BRIDGE_REVIEW.json',evidence)
 save(ROOT/'CURRENT_EP_RESULTS.json',{'records':current,'passed_runs':sum(r['runtime_pass'] for r in current),'current_runs':len(current),'actual_EP_calls_including_corrective_runs':len(review['records'])+len(fixes),'human_answers':0,'model_API_calls':0,'calendar_review_sha256':sha(ROOT/'CALENDAR_BRIDGE_REVIEW.json')})
 print(json.dumps({'current_runs':len(current),'calendar_corrected_runs':len(fixes),'all_corrected_calendars_exact':True}))
