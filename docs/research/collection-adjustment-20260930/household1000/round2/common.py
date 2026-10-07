"""Lossless projections and a bounded task contract; no production activation."""
import copy, hashlib, json
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
SCHEMA = 'eb.household_task_asset.diagnostic.v2'

def digest(x):
    return hashlib.sha256(json.dumps(x,ensure_ascii=False,sort_keys=True,separators=(',',':'),allow_nan=False).encode()).hexdigest()

def sha(p):
    h=hashlib.sha256()
    with Path(p).open('rb') as f:
        while b:=f.read(1048576):h.update(b)
    return h.hexdigest()

def read(p):return json.loads(Path(p).read_text())
def write(p,x):
    p=Path(p);p.parent.mkdir(parents=True,exist_ok=True)
    with p.open('x') as f:f.write(json.dumps(x,ensure_ascii=False,sort_keys=True,indent=2,allow_nan=False)+'\n')

def minutes(w):
    if w is None:return None
    return [[int(a.split(':')[0])*60+int(a.split(':')[1]),int(b.split(':')[0])*60+int(b.split(':')[1])] for a,b in w]

def project(row, source=None):
    p=row['profile'];r4=(source or {}).get('source_overrides',{}).get('r4',{}).get('household',{})
    people=[]
    for m in p['members']:
        people.append({'member_id':m['member_id'],'age_design':m.get('age_years_design'),
            'relationship_design':m.get('relationship_to_reference_adult',m.get('role')),
            'parent_member_ids':m.get('parent_member_ids',[]),'partner_member_id':m.get('partner_member_id'),
            'routine_design':m.get('routine'),
            'weekday_home_windows_min':m.get('weekday_home_windows_min',minutes(m.get('typical_weekday_home_windows',[]))),
            'weekend_home_windows_min':m.get('weekend_home_windows_min',minutes(m.get('typical_weekend_home_windows',[]))),
            'observed_age':None,'observed_routine':None,'caregiving_arrangement':m.get('caregiving_or_school_arrangements'),
            'source_path':'profile.members/'+m['member_id']})
    rawassets=(source or {}).get('source_overrides',{}).get('p2_assets',{}).get('assets')
    assets=[]
    if rawassets is not None:
        for a in rawassets:
            assets.append({'asset_id':a['asset_id'],'device_class':a['class'],'zone_id':a.get('zone_id'),
                'owner_scope':a.get('owner_scope'),'access_scope':a.get('access_scope'),
                'owned_design':True if a.get('owner_scope') in ['ours_private','ours_private_synthetic_new_tenancy'] else None,
                'installed_design':a.get('installed_design'),'accessible_design':a.get('usable_design'),
                'controllable_design':{'ours_device_only_offline_design':True,'none_for_ours':False}.get(a.get('control_scope')),
                'control_scope_design':a.get('control_scope'),
                'modeled':None,'human_permission':a.get('actual_control_permission'),
                'electrical_boundary_id':a.get('electrical_boundary_id'),'source_path':'source_overrides.p2_assets.assets/'+a['asset_id']})
    else:
        for a in p.get('device_instances',[]):
            assets.append({k:a.get(k) for k in ['asset_id','device_class','zone_id','owned_design','installed_design','accessible_design','controllable_design','modeled','human_permission']})
            assets[-1].update(owner_scope='ours_private' if a.get('owned_design') is True else None,
                access_scope='ours_device_only' if a.get('accessible_design') is True else None,
                electrical_boundary_id=row['role_id'],source_path='profile.device_instances/'+a['asset_id'])
    return {'schema':SCHEMA,'role_id':row['role_id'],'origin':row['origin'],'family_size':p['family_size'],
        'generation_design':p.get('generation_category',r4.get('generation_category')),
        'province':p.get('province'),'city':p.get('city'),'members':people,'assets':assets,
        'dwelling':copy.deepcopy(p['dwelling_interface']),'attitudes':copy.deepcopy(p.get('attitude_design')),
        'economics':copy.deepcopy(p.get('economic_context')),'driver_member_id':p.get('home_ev_driver_member_id'),
        'observed_profile':None,'population_weight':p.get('population_weight'),'human_answer':None,
        'physical_results':None,'source_hash':digest(row),'original_row':copy.deepcopy(row),
        'source_execution_reference':row.get('source_binding',{}).get('rich_execution_source') if row.get('source_binding') else None,
        'projection_source_hash':digest(source) if source else None,
        'original_execution_assets':copy.deepcopy(rawassets),'collection_release':False,'training_release':False}

def profile_errors(p):
    e=[];ms={m['member_id']:m for m in p['members']}; aset={a['asset_id']:a for a in p['assets']}
    if len(ms)!=p['family_size']:e.append('member_count')
    if len(aset)!=len(p['assets']):e.append('asset_id_duplicate')
    for m in ms.values():
        for parent in m['parent_member_ids']:
            if parent not in ms or ms[parent]['age_design']-m['age_design']<18:e.append('parent_age_gap')
        if m['partner_member_id'] and (m['partner_member_id'] not in ms or ms[m['partner_member_id']]['partner_member_id']!=m['member_id']):e.append('partner_reciprocity')
        for k in ['weekday_home_windows_min','weekend_home_windows_min']:
            if m[k] is None:e.append('home_window_unknown')
            elif any(not 0<=a<b<=1440 for a,b in m[k]):e.append('home_window')
    if p['driver_member_id'] and (p['driver_member_id'] not in ms or ms[p['driver_member_id']]['age_design']<18):e.append('driver')
    if p['city'] is None:e.append('city_missing')
    d=p['dwelling'];h7=d.get('room_count_design_minimum')
    if h7 is None:e.append('H7_missing')
    if d.get('whole_dwelling_building_area_design_m2') is None:e.append('area_missing')
    if any(a['human_permission'] is not None for a in p['assets']):e.append('unexpected_permission')
    if any(a['accessible_design'] is None or a['controllable_design'] is None for a in p['assets']):e.append('asset_access_or_control_unknown')
    return sorted(set(e))
