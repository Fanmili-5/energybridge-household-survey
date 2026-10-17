"""Use pinned EPW reference weather; never label it actual 2025 observations."""
import csv
from functools import lru_cache
from common import sha

@lru_cache(maxsize=64)
def series(path, expected):
    if sha(path)!=expected: raise ValueError('WEATHER_CHANGED:'+path)
    with open(path, newline='') as stream:
        reader=csv.reader(stream)
        for _ in range(8):next(reader)
        result={}
        for row in reader:
            if len(row)<7:continue
            value=float(row[6])
            if not -60<value<60:raise ValueError('BAD_REFERENCE_DRYBULB')
            result[(int(row[1]),int(row[2]),int(row[3])-1)]=value
    return result

def daily(w,date):
    references=w['layout']['source_parameter_reference']['weather']
    if len(references)!=1:raise ValueError('AMBIGUOUS_WEATHER_REFERENCE')
    ref=references[0];values=series(ref['path'],ref['sha256'])
    temps=[values[(date.month,date.day,h)]for h in range(24)]
    return {'date':str(date),'hourly_drybulb_C':temps,'maximum_C':max(temps),'mean_C':sum(temps)/24,
            'station_key':ref['station_key'],'EPW_sha256':ref['sha256'],
            'actual_calendar_year_weather':False,'use':'declared normal-control context;not simulated indoor comfort'}
