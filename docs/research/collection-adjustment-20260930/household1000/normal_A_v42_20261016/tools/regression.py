"""Reproduce the overwritten return, counterfactual protection, and stable weekday."""
import sys,copy,datetime as dt
from pathlib import Path
STAGE=Path(__file__).resolve().parents[1];sys.path.insert(0,str(STAGE/'code'))
from common import *
from design import resource_world
from activity_model import build_day
from life_integrity import inspect_day

def main():
    parent=BASE/'normal_A_v40_20261016';rows={r['household_id']:r for r in read(parent/'A_BINDINGS10000.json')['records']}
    w=resource_world(read(parent/rows['ordinary-v6-0001']['A_world_path']));d=build_day(w,dt.date(2025,3,15));mid=w['members'][0]['member_id']
    assert not inspect_day(d)
    assert any(x['activity']=='travel'and x['start_min']==730 and x['end_min']==750 for x in d['member_calendars'][mid])
    assert d['meal_appointments'][mid]['actual_lunch_min']==700
    corrupted=copy.deepcopy(d)
    for x in corrupted['protected_travel_ledger'][mid]:
        if x['start_min']==730:x['activity']='wrong'
    assert inspect_day(corrupted)
    stable=resource_world(read(parent/rows['ordinary-v6-0261']['A_world_path']))
    days=[build_day(stable,dt.date.fromisoformat(x['date']))for x in rows['ordinary-v6-0261']['cases']]
    assert len({canonical(x['member_calendars'])for x in days})==1
    other=copy.deepcopy(w);other['VPP_events']=[{'target_kw':999}];other['B']={'bad':True};other['human_answers']={'accepted':False}
    assert build_day(other,dt.date(2025,3,15))==d
    report={'passed':True,'0001_Mar15_lunch_min':700,'0001_Mar15_return_min':[730,750],'travel_corruption_detected':True,'stable_0261_weekdays_preserved':True,'VPP_B_answers_do_not_change_A':True}
    save(OUT/'REGRESSION_RESULTS.json',report);print(canonical(report))
if __name__=='__main__':main()
