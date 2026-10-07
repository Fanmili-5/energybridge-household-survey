"""Project typed relationships and the actual reference parameter pack to role cards."""
import copy,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];SRC=ROOT.parent/'joint_static_production_20261007_v16'
sys.path.insert(0,str(SRC/'code'))
from common import read,save,sha
NAMES={'ac':'空调','washer':'洗衣','dryer':'烘干','dishwasher':'洗碗','water_heater':'电热水器','ev':'电动车充电'}
RELATIONS={'partner_or_spouse_of':'配偶或伴侣','child_of':'子女','parent_of':'父母','grandchild_of':'孙辈','grandparent_of':'祖辈','sibling_of':'兄弟姐妹','child_partner_of':'子女的伴侣','parent_of_partner_of':'伴侣的父母'}

def project(w,source):
 a=copy.deepcopy(source);p=a['profile'];ego=w['members'][0]['member_id']
 relation={r['subject']:RELATIONS.get(r['type'],'其他给定亲属关系') for r in w['ego_relationships'] if r['object']==ego}
 for m in p['members']:
  m['relationship']='家庭参照人' if m['member_id']==ego else relation.get(m['member_id'],'成员，关系未细分')
  m['relationship_projection_basis']='same-world typed ego_relationships;legacy integer display dictionary excluded'
 p['routine']=copy.deepcopy(w['routine']);p['operating_context']=copy.deepcopy(w['operating_context']);p['devices']=[]
 for d in w['parameter_pack']['devices']:
  k=d['types'][0];p['devices'].append({'asset_id':d['asset_id'],'device_class':{'water_heater':'electric_water_heater','ev':'home_ev'}.get(k,k),
    'device':'洗烘一体机' if set(d['types'])=={'washer','dryer'} else NAMES[k],'functional_classes':d['types'],'zone':d['room_id'],
    'owned':None,'installed':True,'accessible':True,'controllable':True,'modelled':True,'parameters':copy.deepcopy(d['parameters']),
    'conditions_status':'configured reference,not observed ownership'})
 p['evidence_status']='source_anchored_reference_world_not_observed_home'
 a['source_world_content_sha256']=w['world_content_sha256'];a['parameter_pack_sha256']=w['parameter_pack_sha256']
 a['geometry_scope']='unchanged reference room geometry;new temporal schedules are in the paired plans'
 return a

if __name__=='__main__':
 assert sys.platform=='linux';selection=read(ROOT/('SELECTION50.json' if (ROOT/'SELECTION50.json').exists() else 'SELECTION1000.json'));rows=[]
 for h in selection['records']:
  w=read(ROOT/h['world_path']);src=SRC/'actors'/f'{h["household_id"]}.json';a=project(w,read(src));target=ROOT/'actors'/src.name
  assert len(a['profile']['members'])==w['N'];assert {m['member_id'] for m in a['profile']['members']}=={m['member_id'] for m in w['members']}
  save(target,a);rows.append({'household_id':h['household_id'],'actor_path':str(target.relative_to(ROOT)),'actor_sha256':sha(target),'source_actor_sha256':sha(src),'world_sha256':h['world_sha256'],'parameter_pack_sha256':w['parameter_pack_sha256']})
 save(ROOT/'ACTOR_BINDINGS.json',{'households':len(rows),'relation_source':'typed same-world relation graph','reference_device_parameters_and_routine_synchronized':True,'human_answers':0,'records':rows});print({'actor_profiles_projected':len(rows),'source_rosters_unchanged':True})
