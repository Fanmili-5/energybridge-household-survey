"""Questionnaire clock parsing; legacy aliases keep their exact historical hours."""
LEGACY_STARTS={'morning':8,'noon':12,'evening':18,'night':20,'late':22}

def clock_options(first=0, last=1430, *, aliases=False):
    """Minutes on the UI, decimal-hour strings for the native EB interface."""
    reverse={hour:label for label,hour in LEGACY_STARTS.items()} if aliases else {}
    return [(reverse.get(m/60,f'{m/60:.12g}'),f'{m//60:02d}:{m%60:02d}') for m in range(first,last+1,10)]

def duration_options():
    # Keep existing canonical values (e.g. '1.0') for saved-answer compatibility.
    return [(str(float(m/60)),f'{m} 分钟') for m in range(10,241,10)]

def clock_label(hours):
    minutes=round(float(hours)*60)
    return f'{minutes//60:02d}:{minutes%60:02d}'

def temperature_range(value, question):
    from decimal import Decimal, InvalidOperation
    try:
        if not isinstance(value,str):raise ValueError()
        low,high=map(Decimal,value.split('_'))
        if not all(x.is_finite() for x in (low,high)):raise ValueError()
        minimum=Decimal(str(question.get('minimum',18)))
        maximum=Decimal(str(question.get('maximum',30)))
        step=Decimal(str(question.get('step',.1)))
        if not minimum<=low<high<=maximum or low%step or high%step:raise ValueError()
        return f'{float(low):g}_{float(high):g}'
    except (ValueError,InvalidOperation):
        raise ValueError('室温范围须在18—30℃内，最低温度小于最高温度，精确到0.1℃') from None

def start_hour(value):
    return float(LEGACY_STARTS[value]) if value in LEGACY_STARTS else float(value)

def ac_available(record,hour):
    if not record.get('active'):return False
    start,end=record['use_start_h'],record['use_end_h']
    hour=hour%24
    return start<=hour<end if end<=24 else hour>=start or hour<end-24
