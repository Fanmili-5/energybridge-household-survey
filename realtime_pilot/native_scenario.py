"""Questionnaire experiment inputs, distinct from EB controller defaults."""
SIMULATION_DAYS=1
START_DATE='2007-07-01'


def window(original):
    unobserved=[]
    departure=None
    for name,r in original['devices'].items():
        if name in ('washer','dishwasher','dryer'):
            deadline=r['deadline_h']+(24 if r['deadline_h']<r['earliest_h'] else 0)
            if deadline>24:unobserved.append({'device':name,'deadline_sim_h':deadline})
        elif name=='home_ev':
            cfg=original['eb_appliance_config']['ev']
            departure=cfg['departure_h']+(24 if cfg['departure_h']<cfg['arrival_h'] else 0)
            if departure>24:unobserved.append({'device':name,'deadline_sim_h':departure})
        elif name=='ac' and r['use_end_h']>24:
            unobserved.append({'device':name,'deadline_sim_h':r['use_end_h']})
    return {'start_sim_h':0,'end_sim_h':24,'simulation_days':SIMULATION_DAYS,
            'ev_departure_sim_h':departure,'end_label':'24:00','extension_reasons':[],
            'unobserved_deadlines':unobserved,
            'semantics':'single-day experiment; overnight completion not observed after cutoff'}
