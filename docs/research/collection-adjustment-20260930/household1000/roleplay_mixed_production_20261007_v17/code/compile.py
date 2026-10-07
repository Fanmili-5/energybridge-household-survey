import concurrent.futures,os,sys,json
os.environ.setdefault('EB_EP_ROOT','/home/hku_user3/energybridge-compute/EnergyPlus-24-1-0')
from pathlib import Path
OUT=Path(__file__).resolve().parents[1];SRC=OUT.parent/'joint_static_production_20261007_v16'
sys.path.insert(0,str(SRC/'code'))
import compile_inputs as compiler
from common import read,save,sha
compiler.OUT=OUT
def one(h):
 w=read(OUT/h['world_path']);background=compiler.parse(compiler.V12/'background_idfs'/f"{w['household_id']}.idf");rows=[]
 for c in h['rounds']:
  p=read(OUT/c['pair_path']);rows.append({**c,'A':compiler.compile_one(w,p,'A',background),'B':compiler.compile_one(w,p,'B',background)})
 return {**h,'rounds':rows}
if __name__=='__main__':
 assert sys.platform=='linux'
 name='SELECTION50.json' if (OUT/'SELECTION50.json').exists() else 'SELECTION1000.json'
 sel=read(OUT/name);rows=[]
 with concurrent.futures.ProcessPoolExecutor(max_workers=16) as pool:
  for h in pool.map(one,sel['records']):rows.append(h)
 save(OUT/('SOURCE_'+name),sel);sel['records']=rows;save(OUT/name,sel)
 auth=read(OUT/'EXECUTION_AUTHORIZATION.json');auth['selection_sha256']=sha(OUT/name);save(OUT/'EXECUTION_AUTHORIZATION.json',auth)
 print({'paired_inputs':sel['pairs'],'IDFs':2*sel['pairs']},flush=True)
