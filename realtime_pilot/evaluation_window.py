"""Common comparison horizon covering reported overnight schedules and deadlines."""
import math


def clock(hour):
    minutes=round(hour*60);day,minutes=divmod(minutes,1440)
    if day and minutes==0:return '24:00' if day==1 else f'第{day}日24:00'
    return ('次日' if day==1 else f'第{day+1}日' if day else '')+f'{minutes//60:02d}:{minutes%60:02d}'


def make_window(original):
    end=96.;reasons=[];depart=None
    for name,record in original['devices'].items():
        if not record.get('active'):continue
        if name in ('washer','dishwasher','dryer'):
            deadline=72+record['deadline_h']+(24 if record['deadline_h']<record['earliest_h'] else 0)
            end=max(end,deadline)
            if deadline>96:reasons.append({'device':name,'deadline_sim_h':deadline})
        if name=='home_ev':
            config=original['eb_appliance_config']['ev'];arrival=config['arrival_h'];departure=config['departure_h']
            if departure==arrival:raise ValueError('EV arrival and departure must define a nonzero native home window')
            depart=72+departure+(24 if departure<arrival else 0)
            end=max(end,depart)
            if depart>96:reasons.append({'device':'home_ev','deadline_sim_h':depart})
        if name=='ac':
            local_end=record['use_end_h']
            if local_end>24:
                end=max(end,72+local_end)
                reasons.append({'device':name,'deadline_sim_h':72+local_end})
    return {'start_sim_h':72,'end_sim_h':end,'simulation_days':math.ceil(end/24),
            'ev_departure_sim_h':depart,'end_label':clock(end-72),'extension_reasons':reasons,
            'semantics':'same time window in both branches; continue native daily routines; not an equal-service savings claim'}


def window_for(scenario):
    return scenario.get('evaluation_window',{'start_sim_h':72,'end_sim_h':96,'simulation_days':4,'ev_departure_sim_h':None,'end_label':'24:00'})
