"""Freeze a common comparison horizon before either policy runs."""
import math
from evaluation_window import clock

START_DATE='2007-07-01'
def statistics_window(original):
    has_ev='home_ev' in original['devices']
    start=float(original['eb_appliance_config']['ev']['departure_h']) if has_ev else 0.
    if not 0<=start<24 or abs(start*6-round(start*6))>1e-6:
        raise ValueError('Departure must be a ten-minute clock time')
    start=round(start*6)/6
    return {'start_sim_h':start,'end_sim_h':round((start+24)*6)/6,'duration_h':24,
            'start_label':'当日'+clock(start),'end_label':clock(start+24),
            'policy':'departure_to_departure_24h_v1' if has_ev else 'calendar_day_24h_v1'}


def statistics_window_for(scenario):
    # Historical results retain their original accounting interval.
    return scenario.get('statistics_window',scenario['evaluation_window'])


def window(original):
    deadlines=[]
    departure=None
    for name,r in original['devices'].items():
        if name in ('washer','dishwasher','dryer'):
            deadline=r['deadline_h']+(24 if r['deadline_h']<r['earliest_h'] else 0)
            deadlines.append({'device':name,'deadline_sim_h':deadline})
        elif name=='home_ev':
            cfg=original['eb_appliance_config']['ev']
            departure=cfg['departure_h']+(24 if cfg['departure_h']<cfg['arrival_h'] else 0)
            deadlines.append({'device':name,'deadline_sim_h':departure})
        elif name=='ac':
            deadlines.append({'device':name,'deadline_sim_h':r['use_end_h']})
    end=max([statistics_window(original)['end_sim_h']]+[r['deadline_sim_h'] for r in deadlines])
    if not 24<=end<=48 or abs(end*6-round(end*6))>1e-6:
        raise ValueError('Comparison horizon must end on a ten-minute boundary within the following day')
    end=round(end*6)/6
    return {'start_sim_h':0,'end_sim_h':end,'simulation_days':math.ceil(end/24),
            'ev_departure_sim_h':departure,'end_label':clock(end),
            'extension_reasons':[r for r in deadlines if r['deadline_sim_h']>24],
            'unobserved_deadlines':[], 'policy':'simulation_covers_statistics_and_reported_deadlines_v2',
            'semantics':'simulation/display coverage; energy and cost use the separate frozen statistics_window'}
