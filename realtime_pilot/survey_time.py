"""Questionnaire clock parsing; legacy aliases keep their exact historical hours."""
LEGACY_STARTS={'morning':8,'noon':12,'evening':18,'night':20,'late':22}

def start_hour(value):
    return float(LEGACY_STARTS[value]) if value in LEGACY_STARTS else float(value)

def ac_available(record,hour):
    if not record.get('active'):return False
    start,end=record['use_start_h'],record['use_end_h']
    hour=hour%24
    return start<=hour<end if end<=24 else hour>=start or hour<end-24
