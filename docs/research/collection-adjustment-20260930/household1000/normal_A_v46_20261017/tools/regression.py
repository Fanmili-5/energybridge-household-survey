"""Reproduce the overwritten return, counterfactual protection, and stable weekday."""
import sys,copy,datetime as dt
from pathlib import Path
STAGE=Path(__file__).resolve().parents[1];sys.path.insert(0,str(STAGE/'code'))
from common import *
from design import resource_world
from activity_model import build_day
from life_integrity import inspect_day

def main():
    parent=BASE/'normal_A_v44_20261017';rows={r['household_id']:r for r in read(parent/'A_BINDINGS10000.json')['records']}
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
    from habits import circulation_slots
    options=list(range(480,1920,10));events=[(1000,'return_to_room:actual_return')]
    first,why=circulation_slots(options,events,'return_to_room','fixture','living')
    second,_=circulation_slots(options,[(1060,'return_to_room:actual_return')],'return_to_room','fixture','living')
    assert second==[x+60 for x in first]
    assert first==circulation_slots(options,events,'return_to_room','fixture','living')[0]
    sparse=[500,510,600,610,900,910];chosen,_=circulation_slots(sparse,[(600,'room_entry:real')],'return_to_room','fixture','living')
    assert chosen==sparse
    try:circulation_slots(sparse[:5],events,'return_to_room','fixture','living')
    except ValueError:pass
    else:raise AssertionError('missing occupancy silently fabricated')
    from review_circulation import genuine_anchor
    seq=lambda a,b,k:{'start_min':a,'end_min':b,'activity':k,'room_id':'bed','location':'home'}
    case={'date':'2025-03-15','days':[{'date':'2025-03-15','activity':{'member_calendars':{'one':[seq(0,480,'sleep_rest'),seq(480,1320,'home_free_activity'),seq(1320,1440,'sleep_rest')]},'member_specs':{}},'shared':{'member_calendars':{}}},{'date':'2025-03-16','activity':{'member_calendars':{'one':[seq(0,480,'sleep_rest'),seq(480,1440,'home_free_activity')]},'member_specs':{}},'shared':{'member_calendars':{}}}]}
    anchor={'room_id':'bed','activity_anchor':'evening_room_activity:sleep_start','activity_anchor_min':1440}
    assert not genuine_anchor(case,anchor)
    assert genuine_anchor(case,{**anchor,'activity_anchor_min':1320})
    from habits import hold_short_indoor_absences
    presence={500,510,540,550};rooms={'one':set(presence)};homes={'one':set(range(480,600,10))}
    permission,ledger=hold_short_indoor_absences(presence,rooms,homes,20)
    assert {520,530}<=permission and len(ledger)==1
    gone={'one':homes['one']-{530}}
    assert hold_short_indoor_absences(presence,rooms,gone,20)[0]==presence
    assert hold_short_indoor_absences({500,550},{'one':{500,550}},homes,20)[0]=={500,550}
    assert hold_short_indoor_absences(presence,{'one':{500,510},'two':{540,550}},{'one':homes['one'],'two':homes['one']},20)[0]==presence
    report={'short_indoor_same_person_return_preserves_control':True,'whole_home_absence_and_long_gaps_not_bridged':True,'different_people_are_not_false_return':True,'midnight_continuous_sleep_is_not_a_new_sleep_start':True,'circulation_actual_activity_shift_changes_fan_minutes':True,'same_habit_and_room_activity_repeats':True,'missing_room_presence_never_fabricated':True,'passed':True,'0001_Mar15_lunch_min':700,'0001_Mar15_return_min':[730,750],'travel_corruption_detected':True,'stable_0261_weekdays_preserved':True,'VPP_B_answers_do_not_change_A':True}
    save(OUT/'REGRESSION_RESULTS.json',report);print(canonical(report))
if __name__=='__main__':main()
