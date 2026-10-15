"""V28 invariant: personal preparation and meals cannot overwrite a journey."""
import hashlib,json
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]

def change(s,a,b):
    if s.count(a)!=1:raise RuntimeError('expected one reference fragment: '+a[:100])
    return s.replace(a,b,1)
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def main():
    path=ROOT/'code/activity_model.py';before=sha(path);s=path.read_text()
    s=change(s,"for s in range(max(0,a)//10,min(1440,b)//10):grid[s]=(activity,room,location)",
        "for s in range(max(0,a)//10,min(1440,b)//10):\n        if location=='home'and grid[s][2]=='outside':\n            # These contexts are given optional at-home windows, not mandatory services.\n            if activity in ('home_commitment','household_chores','school_home_study'):continue\n            raise ValueError('home-only activity conflicts with declared outside episode: '+activity)\n        grid[s]=(activity,room,location)")
    s=change(s,'dep=510+varied;duration=', 'dep=max(510+varied,wake+30);duration=')
    s=change(s,"location='outside' if dep is not None and dep<=720<arr else 'home'\n        stamp(grid,720,750,'meal_and_rest',None if location=='outside' else rooms['meal'],location)",
        "# Keep each lunch step at the already declared journey location.\n        for minute in range(720,750,10):\n            location=grid[minute//10][2]\n            stamp(grid,minute,minute+10,'meal_and_rest',None if location=='outside'else rooms['meal'],location)")
    s=change(s,"dinners={m['member_id']:min(dinner,specs[m['member_id']]['sleep_min']-90) if m['age_years']<6 else dinner for m in ms}",
        "dinners={m['member_id']:max((specs[m['member_id']]['arrival_min']or 0)+20,min(dinner,specs[m['member_id']]['sleep_min']-90)if m['age_years']<6 else dinner)for m in ms}")
    s=change(s,"mid=m['member_id'];s=specs[mid];age=m['age_years'];dinnertime=min(dinner,s['sleep_min']-90) if age<6 else dinner", "mid=m['member_id'];s=specs[mid];age=m['age_years'];dinnertime=dinners[mid]")
    path.write_text(s)
    world_path=ROOT/'code/worlds.py';world_before=sha(world_path);s=world_path.read_text()
    s=change(s,"w['activity_contract']['role_policy_sha256']=policy['policy_sha256']",
        "w['activity_contract']['role_policy_sha256']=policy['policy_sha256']\n    w['activity_contract']['home_context_rule']='given optional home commitments/chores/study apply only to at-home portions of their windows;declared outside episodes retain location;not an observed or mandatory activity dose'")
    world_path.write_text(s)
    audit=ROOT/'code/audit_calendar.py';audit_before=sha(audit);s=audit.read_text()
    marker="if any(i['location']=='home' and i['room_id'] not in rooms for i in ints):fail.append([p['case_id'],mid,'ROOM_ACCESS'])"
    addition=marker+"\n                spec=day['member_specs'][mid];dep,arr=spec['departure_min'],spec['arrival_min']\n                if dep is not None:\n                    if dep<spec['wake_min']+30:fail.append([p['case_id'],mid,'PREPARATION_JOURNEY_OVERLAP'])\n                    if any(i['location']!='outside'for i in ints if overlap((dep,arr),(i['start_min'],i['end_min']))):fail.append([p['case_id'],mid,'ALL_MEMBER_JOURNEY_CHRONOLOGY'])"
    s=change(s,marker,addition);audit.write_text(s)
    report={'schema':'eb.chronology_rule_repair.v28','rules':[
        'variable outside episode begins after the complete given30min personal preparation',
        'lunch retains each10min step outside/home location across journey boundaries',
        'individual dinner follows that member actual return plus given20min preparation',
        'independent chronology gate covers every member, not only EV travellers'],
        'optional_home_contexts_do_not_overwrite_declared_outside_episodes':True,
        'clock_doses_are_declared_reference_not_population_estimates':True,
        'households_types_dates_hardware_unchanged':True,'audit_not_relaxed':True,
        'before_sha256':{'activity_model.py':before,'audit_calendar.py':audit_before,'worlds.py':world_before},
        'after_sha256':{'activity_model.py':sha(path),'audit_calendar.py':sha(audit),'worlds.py':sha(world_path)},'EP_started':0}
    (ROOT/'CHRONOLOGY_RULE_REPAIR.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n');print(json.dumps(report),flush=True)
if __name__=='__main__':main()
