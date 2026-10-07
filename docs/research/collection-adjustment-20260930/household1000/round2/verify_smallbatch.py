#!/usr/bin/env python3
"""Read-only independent checks. Does not import the builder/task validator."""
import argparse, copy, hashlib, itertools, json, math
from datetime import date,timedelta
from pathlib import Path

def read(p):return json.loads(Path(p).read_text())
def digest(x):return hashlib.sha256(json.dumps(x,ensure_ascii=False,sort_keys=True,separators=(',',':'),allow_nan=False).encode()).hexdigest()
def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()

def present(p,mid,start,duration):
    m=next((m for m in p['members'] if m['member_id']==mid),None)
    if m is None or m['age_design']<18:return False
    for minute in range(start,start+duration):
        day,local=divmod(minute,1440);weekday=(date(2025,7,1)+timedelta(days=day)).weekday()<5
        windows=m['weekday_home_windows_min' if weekday else 'weekend_home_windows_min']
        if windows is None or not any(a<=local<b for a,b in windows):return False
    return True

def check_schedule(p,tasks,materials=()):
    assets={a['asset_id']:a for a in p['assets']};byid={t['task_id']:t for t in tasks};errors=[];consumed=[]
    stock={m['material_id']:m['available_abs_min'] for m in materials}
    for t in tasks:
        start=t['start_abs_min']
        if start is None:continue
        end=start+t['duration_min'];tid=t['task_id']
        if not t['release_abs_min']<=start<=end<=t['deadline_abs_min']:errors.append([tid,'window'])
        if not present(p,t['operator_member_id'],start,t['operator_minutes']):errors.append([tid,'presence'])
        if t['asset_id']:
            a=assets[t['asset_id']]
            if a['device_class']!=t['device_class'] or a['accessible_design'] is not True or a['controllable_design'] is not True:errors.append([tid,'asset'])
        produced=[]
        for dep in t['predecessor_task_ids']:
            d=byid[dep]
            if d['start_abs_min'] is None or start<d['start_abs_min']+d['duration_min']:errors.append([tid,'dependency'])
            produced.extend(d['material_outputs'])
        if not set(t['material_inputs'])<=set(produced)|set(stock):errors.append([tid,'material'])
        if any(start<stock[m] for m in t['material_inputs'] if m in stock):errors.append([tid,'material_release'])
        consumed.extend(t['material_inputs'])
        if t['device_class']=='home_ev':
            left,right=t['vehicle_present_interval_abs_min']
            if not left<=start<end<=right or end>t['next_departure_abs_min']:errors.append([tid,'departure'])
            expected=10*math.ceil(t['energy_grid_kWh_design']/3.3*60/10)
            if expected!=t['duration_min']:errors.append([tid,'charge_duration'])
    if len(consumed)!=len(set(consumed)):errors.append(['wet_material_double_consumption'])
    for x,y in itertools.combinations([t for t in tasks if t['start_abs_min'] is not None],2):
        overlap=lambda dx,dy:max(x['start_abs_min'],y['start_abs_min'])<min(x['start_abs_min']+dx,y['start_abs_min']+dy)
        if x['asset_id'] and x['asset_id']==y['asset_id'] and overlap(x['duration_min'],y['duration_min']):errors.append(['asset_overlap'])
        if x['operator_member_id']==y['operator_member_id'] and overlap(x['operator_minutes'],y['operator_minutes']):errors.append(['operator_overlap'])
    return errors

def verify(batch):
    manifest=read(batch/'MANIFEST.json');fail=[];checks=[]
    for rel,h in manifest['files'].items():
        if sha(batch/rel)!=h:fail.append(['manifest',rel])
    code=batch.parent
    for name,h in manifest['code'].items():
        if sha(code/name)!=h:fail.append(['code_drift',name])
    for name,h in manifest['mapped_old300'].items():
        path=batch/'mapped_old300'/name;p=read(path);r=p['original_row']
        if sha(path)!=h or digest(r)!=p['source_hash']:fail.append(['old_mapping_hash',name])
        if p['collection_release'] or p['training_release'] or p['physical_results'] is not None:fail.append(['old_release',name])
        if r['profile']!=read(r['profile_source']['path'])['effective_profile']:fail.append(['old_profile_roundtrip',name])
        ref=p['source_execution_reference'];src=read(ref['path'])
        if sha(ref['path'])!=ref['sha256'] or digest(src)!=p['projection_source_hash']:fail.append(['execution_source',name])
        if p['original_execution_assets']!=src['source_overrides']['p2_assets']['assets']:fail.append(['asset_roundtrip',name])
        for original,m in zip(r['profile']['members'],p['members']):
            for rawkey,key in [('typical_weekday_home_windows','weekday_home_windows_min'),('typical_weekend_home_windows','weekend_home_windows_min')]:
                value=original.get(rawkey)
                expected=None if value is None else [[int(a[:2])*60+int(a[3:]),int(b[:2])*60+int(b[3:])] for a,b in value]
                if m[key]!=expected:fail.append(['home_window_mapping',name])
    for row in manifest['cases']:
        rid=row['role_id'];base=batch/'cases'/rid
        for filename,h in row['files'].items():
            if sha(base/filename)!=h:fail.append(['case_hash',rid,filename])
        p,A,B=[read(base/n) for n in ['profile.json','A.json','B.json']]
        if A['profile_hash']!=digest(p):fail.append(['A_profile_binding',rid])
        errs=check_schedule(p,A['tasks'],A['material_sources'])
        if errs:fail.append(['A_schedule',rid,errs])
        if p['dwelling']['requested_H7_before_capacity_check']!=p['dwelling']['room_count_design_minimum']:fail.append(['H7_changed',rid])
        if (p.get('housing_source_tuple') or {}).get('L16_raw')==999 and p['dwelling']['whole_dwelling_building_area_design_m2'] is not None:fail.append(['999_not_unknown',rid])
        ev=[s for s in A['states'] if 'SOC_pre_day' in s];prev=.8
        for s in ev:
            if abs(s['SOC_pre_day']-prev)>1e-7:fail.append(['SOC_history',rid,s['day']])
            if s['SOC_post_day'] is None:continue
            if not 0<=s['SOC_post_day']<=1:fail.append(['SOC_bounds',rid,s['day']])
            if abs(s['trip_demand_kWh_design']-s['trip_kWh_design']-s['unserved_trip_demand_kWh_design'])>1e-7:fail.append(['trip_demand_balance',rid,s['day']])
            expected=s['SOC_after_trip']+s['charge_grid_kWh_design']*.9/50
            if abs(expected-s['SOC_post_day'])>1e-7:fail.append(['SOC_balance',rid,s['day']])
            prev=s['SOC_post_day']
        for r in B['rounds']:
            if r['A_sha256']!=digest(A) or r['profile_sha256']!=digest(p):fail.append(['B_binding',rid])
            if r['legal_prior_A_days']!=list(range(r['day_index'])) or r['prior_A_state_sha256']!=digest([s for s in A['states'] if s['day']<r['day_index']]):fail.append(['history_leakage',rid])
            changed=copy.deepcopy(A['tasks']);ids={t['task_id']:t for t in changed}
            if len({c['device_class'] for c in r['commands']})<2:fail.append(['two_classes',rid])
            for c in r['commands']:
                t=ids.get(c['task_id'])
                if t is None:fail.append(['B_invented_task',rid]);continue
                if c['asset_id']!=t['asset_id'] or c['device_class']!=t['device_class'] or c['duration_min']!=t['duration_min'] or c['A_start_abs_min']!=t['start_abs_min']:fail.append(['B_relabel',rid])
                t['start_abs_min']=c['B_start_abs_min']
            e=check_schedule(p,changed,A['material_sources'])
            if e:fail.append(['B_schedule',rid,e])
            if r['physics'] is not None or r['answer'] is not None or r['collectable']:fail.append(['B_false_release',rid])
        if B['round_shortfall']!=10-len(B['rounds']) or B['A_modified_for_B'] or B['new_tasks_for_B'] or B['physical_ready'] or B['human_answers']:fail.append(['B_counts',rid])
        checks.append({'role_id':rid,'A_checked':len(A['tasks']),'B_checked':len(B['rounds']),
            'unresolved_A_preserved':len(A['unresolved']),'round_shortfall_preserved':B['round_shortfall'],
            'crossday_EV_tasks':sum(t['device_class']=='home_ev' and t['start_abs_min'] is not None and t['start_abs_min']//1440!=(t['start_abs_min']+t['duration_min'])//1440 for t in A['tasks'])})
    return {'batch_id':manifest['batch_id'],'pass':not fail,'failures':fail,'old300_lossless_checked':len(manifest['mapped_old300']),
        'cases':checks,'scope':'hash, lossless mapping, fixed H7, operators, asset rights, dependencies, material consumption, EV energy/departure, history and B source identity; not life plausibility/thermal/human validity'}

if __name__=='__main__':
    ap=argparse.ArgumentParser();ap.add_argument('batch',type=Path);ap.add_argument('--report',type=Path,required=True);a=ap.parse_args()
    result=verify(a.batch)
    assert a.report.resolve().is_relative_to(Path(__file__).resolve().parent)
    with a.report.open('x') as f:json.dump(result,f,ensure_ascii=False,indent=2);f.write('\n')
    print(json.dumps(result,ensure_ascii=False));raise SystemExit(0 if result['pass'] else 1)
