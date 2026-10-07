import collections, hashlib, json
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
SOURCE=ROOT.parent/'joint_static_production_20261007_v16'
def load(p):return json.loads(p.read_text())
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def save(p,v):p.write_text(json.dumps(v,ensure_ascii=False,sort_keys=True,indent=2)+'\n')
worlds=load(SOURCE/'WORLD_BINDINGS1000.json')['records'];pool={}
for b in worlds:
 w=load(SOURCE/b['world_path']);classes=sorted(k for k,v in w['assets'].items() if v['present'])
 tags={('combination',','.join(classes)),('province',w['province']),('N',str(w['N'])),('G',str(w['G']))}
 pool[w['household_id']]={'binding':b,'classes':classes,'K':len(classes),'tags':tags,'N':w['N'],'G':w['G'],'province':w['province']}
selected=[r['household_id'] for r in load(ROOT.parent/'pilot_scope_20261007_v1/PILOT_SELECTION.json')['records']]
quota={4:17,5:17,6:16};covered=set().union(*(pool[x]['tags'] for x in selected));weights={'combination':100,'province':25,'N':10,'G':10}
while len(selected)<50:
 counts=collections.Counter(pool[x]['K'] for x in selected)
 options=[x for x,v in pool.items() if x not in selected and counts[v['K']]<quota[v['K']]]
 best=min(options,key=lambda x:(-sum(weights[t[0]] for t in pool[x]['tags']-covered),hashlib.sha256(('pilot50:'+x).encode()).hexdigest()))
 selected.append(best);covered|=pool[best]['tags']
counts=collections.Counter(pool[x]['K'] for x in selected)
assert dict(counts)==quota and len(set(selected))==50
pairs={x['household_id']:x for x in load(SOURCE/'PAIR_BINDINGS10000.json')['households']}
idfs={x['household_id']:x for x in load(SOURCE/'IDF_BINDINGS20000.json')['households']}
records=[]
for hid in selected:
 v=pool[hid];record={k:v[k] for k in ('classes','K','N','G','province')};record.update(v['binding']);record['rounds']=[]
 for p,i in zip(pairs[hid]['records'],idfs[hid]['records']):
  assert p['round_index']==i['round_index'] and p['pair_sha256']==i['pair_sha256']
  record['rounds'].append({'round_index':p['round_index'],'date':p['date'],'proposal_family':p['proposal_family'],'pair_path':p['pair_path'],'pair_sha256':p['pair_sha256'],'A':i['A'],'B':i['B']})
 assert len(record['rounds'])==10
 records.append(record)
summary={'schema':'eb.pilot50.selection.v1','status':'selected_before_execution','households':50,'pairs':500,'maximum_EP_runs':1000,'K_counts':dict(counts),'combination_count':sum(t[0]=='combination' for t in covered),'province_count':sum(t[0]=='province' for t in covered),'source_delivery_sha256':sha(SOURCE/'DELIVERY.json'),'source_manifest_sha256':sha(SOURCE/'PACKAGE_MANIFEST.json'),'method':'existing eight boundary households retained; deterministic weighted coverage with K quotas17/17/16; all ten frozen dates retained; no outcome selection','selection_is_population_representative':False,'records':records}
save(ROOT/'SELECTION50.json',summary)
save(ROOT/'EXECUTION_AUTHORIZATION.json',{'user_instruction':'拿50户做测试测试上服务器环境链接之前真实做的前端系统','authorized_scope':'50 selected households,existing ten random dates each,school Linux EnergyPlus and original frontend engineering test','EP_scope_hold_lifted_for_selected50':True,'full1000_EP_authorized':False,'source_V16_EP_hold_file_preserved':True,'human_collection_release':False,'training_release':False,'selection_sha256':sha(ROOT/'SELECTION50.json')})
save(ROOT/'FRONTEND_SOURCE_LOCK.json',{'live_url':'https://47.85.194.154/joint-b','live_release':'c1d48e955932db17','files':{p.name:sha(p) for p in sorted((ROOT/'frontend_snapshot').iterdir()) if p.is_file()},'renderer_policy':'reuse actual live frontend bytes; only frozen scene/profile data and isolated test prefix differ'})
print(json.dumps({k:v for k,v in summary.items() if k!='records'},ensure_ascii=False))
