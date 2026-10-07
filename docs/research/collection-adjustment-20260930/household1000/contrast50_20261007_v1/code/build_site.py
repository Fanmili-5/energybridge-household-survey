"""Adapt actual frozen worlds and SQL readback to the existing live joint-b page."""
import collections, datetime as dt, hashlib, html, json, re, shutil
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];SOURCE=ROOT;PREFIX='/household50'
NAMES={'ac':'空调','washer':'洗衣','dryer':'烘干','dishwasher':'洗碗','water_heater':'电热水器','ev':'电动车充电'}
ICONS={'water_heater':'electric_water_heater','ev':'home_ev'}
def read(p):return json.loads(p.read_text())
def canon(x):return json.dumps(x,ensure_ascii=False,sort_keys=True,separators=(',',':'),allow_nan=False)
def dig(x):return hashlib.sha256(canon(x).encode()).hexdigest()
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def save(p,v):p.parent.mkdir(parents=True,exist_ok=True);p.write_text(canon(v)+'\n')
def clock(t):return ('当天' if t<1440 else '次日' if t<2880 else '第3天')+f' {t%1440//60:02d}:{t%60:02d}'
def geometry(path,labels):
 rows=[[v.strip() for v in r.split(',')] for r in re.sub(r'!.*','',path.read_text()).split(';') if r.strip()];floors=[];walls=[];openings=[];surfaces={v[1]:v[4] for v in rows if v[0]=='BuildingSurface:Detailed'}
 for v in rows:
  if v[0] not in ['BuildingSurface:Detailed','FenestrationSurface:Detailed']:continue
  surface=v[0]=='BuildingSurface:Detailed';zone=v[4] if surface else surfaces[v[4]];offset=11 if surface else 9;n=int(v[offset]);coords=list(map(float,v[offset+1:offset+1+n*3]));points=[[coords[j],coords[j+1]] for j in range(0,len(coords),3)];unique=list(map(list,dict.fromkeys(map(tuple,points))))
  if surface and v[2]=='Floor':floors.append({'zone':zone,'points':points})
  elif surface and v[2]=='Wall' and len(unique)==2:walls.append({'zone':zone,'points':unique})
  elif not surface and len(unique)==2:openings.append({'type':v[2].lower(),'points':unique})
 return {'floors':floors,'walls':walls,'openings':openings,'zone_labels':labels,'source_IDF_sha256':sha(path),'reference_layout_only_not_asbuilt_survey':True}
def profile(w):
 a=read(SOURCE/'actors'/f'{w["household_id"]}.json');p=a['profile'];p['household']['building_type']={'8_to33':'8—33层城市住宅参考','4_to7':'4—7层城市住宅参考','1_to3':'1—3层城市住宅参考'}.get(w['layout']['stock_reference_features']['building_storeys'],'城市住宅参考')
 relation_names={'partner_or_spouse_of':'配偶或伴侣','child_of':'子女','parent_of':'父母','grandchild_of':'孙辈','grandparent_of':'祖辈','sibling_of':'兄弟姐妹','child_partner_of':'子女的伴侣','parent_of_partner_of':'伴侣的父母'}
 ego=w['members'][0]['member_id'];relations={r['subject']:relation_names.get(r['type'],'其他给定亲属关系') for r in w['ego_relationships'] if r['object']==ego}
 for m in p['members']:
  m['relationship']='家庭参照人' if m['member_id']==ego else relations.get(m['member_id'],'成员，关系未细分')
  m['relationship_projection_basis']='same-world typed ego_relationships graph;legacy display code dictionary excluded'
 devices=[]
 for d in w['parameter_pack']['devices']:
  k=d['types'][0];devices.append({'asset_id':d['asset_id'],'device_class':ICONS.get(k,k),'device':'洗烘一体机' if set(d['types'])=={'washer','dryer'} else NAMES[k],'functional_classes':d['types'],'zone':d['room_id'],'owned':None,'installed':True,'accessible':True,'controllable':True,'modelled':True,'parameters':d['parameters'],'conditions_status':'configured reference;not observed ownership'})
 p['routine']=w['routine'];p['operating_context']=w['operating_context'];p['devices']=devices;p['evidence_status']='source_anchored_reference_world_not_observed_home';p['household']['budget_explanation']='偏好由扮演者判断；没有预设采纳或评分。'
 if not w['operating_context']['operators'][0]['resident']:p['household']['control_condition']+='；本户由非同住监护人协助操作，监护人不计入常住人数。'
 p['household']['household_net_share_m2']=round(p['household']['household_net_share_m2'],2)
 labels={**a['geometry']['zone_labels'],'external_dedicated_EV_bay':'室外专用充电车位'};g=geometry(SOURCE/'idfs'/w['household_id']/'01_A.idf',labels)
 return {'role_id':w['household_id'],'sha256':dig(p),'profile':p,'geometry':g,'source_world_sha256':w['world_content_sha256']}
def plan_rows(w,p,side):
 rows=[]
 for d in w['parameter_pack']['devices']:
  aid=d['asset_id'];events=[]
  for t in p[side]['tasks']:
   if t['asset_id']==aid and t['start_min']<2880:events.append({'event_id':t['need_id'],'start_abs_min':t['start_min'],'end_abs_min':min(2880,t['end_min']),'operation_kind':'program_power','operation_label':NAMES[t['kind']]+'程序','functional_class':t['kind']})
  for c in p[side]['controls']:
   if c['asset_id']==aid and c['start_min']<2880:events.append({'start_abs_min':c['start_min'],'end_abs_min':min(2880,c['end_min']),'operation_kind':'heater_availability' if c['kind']=='tank_setpoint' else 'temperature_setpoint' if c['kind']=='ac_setpoint' else 'charge_availability',**({'setpoint_C':c['value_C']} if 'value_C' in c else {}),'operation_label':('允许加热，目标 '+str(c['value_C'])+' ℃') if c['kind']=='tank_setpoint' else '允许充电' if c['kind']=='ev_charge_window' else '设定温度 '+str(c['value_C'])+' ℃'})
  rows.append({'asset_id':aid,'device_class':ICONS.get(d['types'][0],d['types'][0]),'events':sorted(events,key=lambda e:e['start_abs_min']),'schedule_complete':True})
 return {'window_start_abs_min':0,'window_end_abs_min':2880,'rows':rows}
def commands(w,p):
 out=[];A={t['need_id']:t for t in p['A']['tasks']};controlA=p['A']['controls']
 for t in p['B']['tasks']:
  a=A[t['need_id']]
  if t!=a:out.append({'asset_id':t['asset_id'],'device_class':ICONS.get(t['kind'],t['kind']),'kind':'event_interval','start_abs_min':t['start_min'],'end_abs_min':t['end_min'],'A_start_abs_min':a['start_min'],'A_end_abs_min':a['end_min'],'reason_text':p['proposal']['family']})
 for c in p['B']['changed_controls']:
  matching=[x for x in controlA if x['asset_id']==c['asset_id'] and x['kind']==c['kind']]
  a=next((x for x in matching if x['start_min']<=c['start_min']<x['end_min']),min(matching,key=lambda x:abs(x['start_min']-c['start_min'])))
  if c['kind']=='ac_setpoint' and a.get('value_C')==c.get('value_C'):continue
  out.append({'asset_id':c['asset_id'],'device_class':ICONS.get({'ac_setpoint':'ac','tank_setpoint':'water_heater','ev_charge_window':'ev'}[c['kind']],{'ac_setpoint':'ac','tank_setpoint':'water_heater','ev_charge_window':'ev'}[c['kind']]),'kind':'ac_setpoint' if c['kind']=='ac_setpoint' else 'control_interval','start_abs_min':c['start_min'],'end_abs_min':c['end_min'],'A_start_abs_min':a['start_min'],'A_end_abs_min':a['end_min'],**({'from_setpoint_C':c.get('from_C',a.get('value_C')),'to_setpoint_C':c['value_C']} if c['kind']=='ac_setpoint' else {}),'reason_text':p['proposal']['family']})
 if not out:out=[{'asset_id':w['parameter_pack']['devices'][0]['asset_id'],'kind':'identity_control','start_abs_min':1080,'end_abs_min':1140,'A_start_abs_min':1080,'A_end_abs_min':1140,'is_noop_reference':True,'reason_text':p['proposal']['family']}]
 for i,c in enumerate(out):c['command_id']=f'{p["case_id"]}/command/{i}'
 return out
def weather(path,date):
 d=dt.date.fromisoformat(date);wanted={(x.month,x.day) for x in [d,d+dt.timedelta(days=1)]};groups=collections.defaultdict(list)
 for line in Path(path).read_text().splitlines()[8:]:
  f=line.split(',');key=(int(f[1]),int(f[2]))
  if key in wanted:groups[key].append(float(f[6]))
 return [{'min_drybulb_C_derived':min(groups[x.month,x.day]),'max_drybulb_C_derived':max(groups[x.month,x.day]),'source':'TMY EPW month/day;not observed2025 weather'} for x in [d,d+dt.timedelta(days=1)]]
def scene(w,h,p,r,prof):
 needs=[]
 for n in p['needs_A']:
  if n.get('release_min',0)>=2880:continue
  name=NAMES[n['kind']];deadline=n.get('deadline_min',2880)
  unit={'kg':'公斤','EBprogram':'个完整程序','L mixed water':'升混合热水','kWh trip traction energy':'千瓦时出行用电'}.get(n['unit'],n['unit'])
  needs.append(f'{clock(n.get("release_min",0)).split()[0]}：{name}需求 {n["quantity"]:g} {unit}；{clock(deadline)}前满足'+(f'，目标 {n["target_C"]:.1f} ℃' if 'target_C' in n else ''))
 impacts=[{'status':'computed','description':f'目标时段移峰量为 {r["electricity"]["event"]["A_minus_B_kWh"]:.3f} kWh；两天总电量另列，用于检查后续回补。'}, {'status':'computed','description':'结果来自这户、这一天的配对参考模型；室温不等同于个人舒适，费用尚未计算。'}]
 for side in ['A','B']:
  s=r['services'][side]
  if 'hot_water' in s:
   q=s['hot_water'];impacts.append({'status':'computed','description':f'{side}：48小时混合热水需求 {q["requested_mixed_L_48h"]:g} L，模型供水 {q["delivered_mixed_L_48h"]:.1f} L；用水时段最低平均温度 {q["minimum_timestep_mixed_C"]:.1f} ℃。'+('低于给定目标，存在热水温度缺口。' if not q['temperature_pass'] else '达到给定混水温度目标。')})
  if 'EV' in s:
   debt=sum(x['energy_shortfall_kWh'] for x in s['EV']['trips_in_target48h']);impacts.append({'status':'computed','description':f'{side}：给定出行需求的电量缺口 {debt:.2f} kWh；后续晨间电量占比 {s["EV"]["terminal_SOC_service_tail"]*100:.1f}%。电量状态由模型充电用电和给定行程推算。'})
 if p['proposal']['family']=='identity_control':impacts.append({'status':'computed','description':'本轮为A/B相同安排对照，未实施设备调整。'})
 if p['proposal']['family']=='no_legal_change':impacts.append({'status':'computed','description':'给定操作和服务约束下，本轮未找到合法修改；B保留A。'})
 air=[v for k,v in r['predecision_state'].items() if k.startswith('Zone Mean Air Temperature|')];tank=[v for k,v in r['predecision_state'].items() if k.startswith('Water Heater Tank Temperature|')]
 state='通知前模型房间空气温度 '+f'{min(air):.1f}—{max(air):.1f} ℃'+(f'；水箱平均温度 {tank[0]:.1f} ℃' if tank else '')
 vpp={'start_abs_min':p['event_window_min'][0],'end_abs_min':p['event_window_min'][1],'notice_abs_min':p['decision_abs_min'],'household_request':{'text':'平均购电负荷比A降低0.5 kW，同时满足给定生活需求'},'incentive':None}
 plans={s:plan_rows(w,p,s) for s in ['A','B']};cmd=commands(w,p);quantities=[]
 changed_ids={c['asset_id'] for c in cmd}
 for plan in plans.values():plan['rows'].sort(key=lambda row:row['asset_id'] not in changed_ids)
 for key,label in [('event','目标时段家庭购电（本次移峰目标）'),('48h','48小时家庭购电'),('48h_plus_service_tail','含后续晨间服务段的家庭购电')]:
  e=r['electricity'][key];quantities.append({'label':label,**{s:{'value':e[s+'_kWh'],'unit':'kWh','status':'computed'} for s in ['A','B']},'scope':key,'evidence_sha256':dig(r)})
 e=r['electricity']['event'];physical={'status':'complete','channels':[{'label':'家庭购电','unit':'kWh',**{s:{'status':'computed','value':e[s+'_kWh']} for s in ['A','B']},'evidence_sha256':dig(r),'start_abs_min':p['event_window_min'][0],'end_abs_min':p['event_window_min'][1]}]}
 c={'schema':'eb.joint_b.consumer.v2','identity':{'role_id':w['household_id'],'case_id':p['case_id'],'date':p['date'],'round_index':p['round_index'],'day_index':0,'split':None},'profile':prof,'plans':plans,'commands':cmd,'vpp':vpp,'context':{'daily_need_texts':needs,'weather_days':weather(h['weather']['path'],p['date']),'pre_event_state':{'display_text':state}},'quantities':quantities,'impacts':impacts,'physical':physical,'after_horizon':{'status':'reported_model_tail','service_tail_min':p['service_tail_min'],'terminal_states':r['terminal_states']},'display_assignment':{'left':'A','right':'B'},'audit':{'source_pair_sha256':r['source_pair_sha256'],'actual_readback_sha256':dig(r),'physical_calibration_complete':False},'human_label_count':0,'collection_release':False,'training_release':False}
 c['bindings']={k:dig(v) for k,v in [('profile_sha256',prof),('commands_sha256',cmd),('A_plan_sha256',plans['A']),('B_plan_sha256',plans['B']),('vpp_sha256',vpp),('physical_sha256',physical)]};c['bindings']['source_pair_sha256']=r['source_pair_sha256']
 return c
if __name__=='__main__':
 report=read(ROOT/'READBACK_REVIEW.json');assert not report['failures'] and report['pairs_checked']==500
 entries={(r['household_id'],r['round_index']):r for r in report['records']};selection=read(ROOT/'SELECTION50.json');release=ROOT/'frontend_release';release.mkdir(exist_ok=False);index=[];template=(ROOT/'frontend_snapshot/index.html').read_text();assets=['style.css','candidate.css','joint-view.css','plan-view.js','source-draft.js','household-view.js','joint-view.js']
 for h in selection['records']:
  hid=h['household_id'];w=read(SOURCE/h['world_path']);prof=profile(w);cases=[]
  for b in h['rounds']:
   p=read(SOURCE/b['pair_path']);r=read(ROOT/entries[hid,b['round_index']]['result_path']);cases.append(scene(w,h,p,r,prof))
  site=release/'households'/hid;site.mkdir(parents=True)
  page=template
  values={'profile-data':{hid:prof},'source-cases-data':{hid:[]},'source-selection-data':{hid:{}},'joint-cases-data':cases,'visible-inputs-data':[{'schema':'eb.joint_b.semantic_input.v1','date':c['identity']['date'],'profile':c['profile']['profile'],'plans':c['plans'],'given_context':c['context']} for c in cases],'source-hashes-data':[dig(c) for c in cases]}
  for key,value in values.items():
   page,n=re.subn(r'(<script[^>]+id="'+key+r'"[^>]*>).*?(</script>)',lambda m:m[1]+canon(value).replace('<','\\u003c')+m[2],page,flags=re.S);assert n==1,key
  route=PREFIX+'-'+hid
  page=page.replace('<div id="joint-changes" class="change-summary"></div>','',1).replace('<div id="joint-timeline"></div>','<div id="joint-changes" class="change-summary"></div><div id="joint-timeline"></div>',1)
  page=page.replace('</header>','<a href="/household50">选择测试家庭</a></header>',1)
  for name in assets:page=page.replace('href="'+name+'"','href="'+route+'/'+name+'"').replace('src="'+name+'"','src="'+route+'/'+name+'"')
  (site/'index.html').write_text(page)
  for name in assets:shutil.copyfile(ROOT/'frontend_snapshot'/name,site/name)
  # Same layout and question contract; add explicit wash/dry/program labels for new data.
  js=site/'joint-view.js';text=js.read_text();text=text.replace("const label=e=>e.operation_kind", "const label=e=>e.operation_label|| (e.operation_kind",1).replace("'安排时段';","'安排时段');",1);js.write_text(text)
  index.append({'household_id':hid,'route':route,'N':w['N'],'G':w['G'],'province':w['province'],'K':h['K'],'cases':10,'case_hashes':values['source-hashes-data']})
 save(release/'INDEX50.json',{'households':index,'pairs':500,'readback_review_sha256':sha(ROOT/'READBACK_REVIEW.json'),'live_source_lock_sha256':sha(ROOT/'FRONTEND_SOURCE_LOCK.json'),'engineering_only':True,'human_collection_release':False,'training_release':False})
 shutil.copyfile(ROOT/'frontend_snapshot/unified_live_server.py',release/'unified_live_server.py')
 save(release/'RENDERER_DIFF.json',{'baseline':'actual live /joint-b release c1d48e955932db17','identical_assets':[x for x in assets if x!='joint-view.js'],'changed_asset':'joint-view.js','change':'single label helper reads explicit operation_label; preserves layout,questions,submit/export logic','scope':'wash/dry labels on shared physical combo and thermal/EV availability labels'})
 print(json.dumps({'households':50,'actual_pairs':500,'frontend_release':str(release),'questions':'original live binary adoption,four1to5scores,reason'}))
