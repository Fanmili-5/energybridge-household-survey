"""Freeze a common comparison horizon before either policy runs."""
import math
from evaluation_window import clock

START_DATE='2007-07-01'
MINIMUM_END_H=30.  # Include the following morning's first six hours.


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
    end=max([MINIMUM_END_H]+[r['deadline_sim_h'] for r in deadlines])
    if not 24<end<=48 or abs(end*6-round(end*6))>1e-6:
        raise ValueError('Comparison horizon must end on a ten-minute boundary within the following day')
    end=round(end*6)/6
    return {'start_sim_h':0,'end_sim_h':end,'simulation_days':math.ceil(end/24),
            'ev_departure_sim_h':departure,'end_label':clock(end),
            'extension_reasons':[r for r in deadlines if r['deadline_sim_h']>24],
            'unobserved_deadlines':[], 'policy':'next_morning_and_reported_deadlines_v1',
            'semantics':'fixed before planning; both native policies continue daily routines to the same cutoff; not an equal-service savings claim'}
