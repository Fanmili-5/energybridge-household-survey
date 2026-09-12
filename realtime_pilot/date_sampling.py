"""Weather-stratified sampling; no family attitudes, model output or human labels."""
import csv
from datetime import date, timedelta
from functools import lru_cache
from pathlib import Path
import random

SEASONS={'summer':(6,7,8),'winter':(12,1,2),'spring':(3,4,5),'autumn':(9,10,11)}
GROUPS=('relative_cool','middle','relative_hot')

ANNUAL_VERSION='annual_uniform_calendar_v1'
SEASON_LABELS={'spring':'春季','summer':'夏季','autumn':'秋季','winter':'冬季'}

def _annual_context(draw_id):
    from common import digest
    selected=date(2007,1,1)+timedelta(days=random.Random(draw_id).randrange(365))
    season=next(s for s,months in SEASONS.items() if selected.month in months)
    result={'version':ANNUAL_VERSION,'draw_id':draw_id,'date':selected.isoformat(),
        'season':season,'season_label':SEASON_LABELS[season],
        'calendar_year':2007,'pool_size':365,'date_probability':1/365,
        'assignment_unit':'browser_session','source':'system_random_assignment_not_household_fact',
        'uses_ratings':False,'weather_basis':'station_typical_year_not_historical_day',
        'label':f'{selected.month}月{selected.day}日 · {SEASON_LABELS[season]}',
        'instruction':'请设想您家在这个月份的一天，按该季节的习惯填写；季节按月份标注，具体天气以匹配站点为准。'}
    result['context_hash']=digest(result)
    return result

def assigned_context(session):
    """Stable assignment before answers; never expose the session credential."""
    from common import digest
    return _annual_context(digest({'policy':ANNUAL_VERSION,'session':session}))

def verify_context(context):
    import re
    draw_id=context.get('draw_id','') if isinstance(context,dict) else ''
    if not isinstance(draw_id,str) or not re.fullmatch('[a-f0-9]{64}',draw_id) or context!=_annual_context(draw_id):
        raise ValueError('本次问卷日期记录不一致，请刷新核对')
    return context

def annual_sample(epw,context):
    verify_context(context)
    stats={r['date']:r for r in weather_days(epw,context['calendar_year'],context['season'])}
    if context['date'] not in stats:raise ValueError('天气文件缺少本次日期，家庭资料已保留')
    return context['date'],{'version':ANNUAL_VERSION,'questionnaire_context':context,
        'selected_weather':stats[context['date']], 'uses_ratings':False,
        'date_probability':context['date_probability'],
        'validation_policy':'native_baseline_before_planning_no_resampling',
        'validation_status_at_assignment':'pending_case_baseline'}

@lru_cache(maxsize=512)
def _days(path,mtime,size,year,season):
    values={}
    with Path(path).open() as f:
        reader=csv.reader(f)
        for _ in range(8):next(reader)
        for row in reader:
            month,day=int(row[1]),int(row[2])
            if month not in SEASONS[season]:continue
            try:key=date(year,month,day).isoformat()
            except ValueError:continue  # Leap day absent in experiment calendar.
            temperature=float(row[6])
            if not -90<=temperature<=70:raise ValueError('Invalid EPW dry bulb temperature')
            values.setdefault(key,[]).append(temperature)
    if not values or any(len(v)!=24 for v in values.values()):raise ValueError('Incomplete daily EPW data')
    rows=[{'date':d,'mean_dry_bulb_c':sum(v)/24,'min_dry_bulb_c':min(v),'max_dry_bulb_c':max(v)} for d,v in values.items()]
    rows.sort(key=lambda r:(r['mean_dry_bulb_c'],r['date']))
    return tuple({**r,'stratum':GROUPS[min(2,i*3//len(rows))]} for i,r in enumerate(rows))

def weather_days(epw,year=2007,season='summer'):
    if season not in SEASONS:raise ValueError('Unknown season')
    p=Path(epw);s=p.stat()
    return [dict(r) for r in _days(str(p.resolve()),s.st_mtime_ns,s.st_size,year,season)]

def sample(epw,pool,seed,season='summer'):
    if not pool or len(set(pool))!=len(pool):raise ValueError('Invalid validated date pool')
    year=date.fromisoformat(pool[0]).year
    stats={r['date']:r for r in weather_days(epw,year,season)}
    if any(d not in stats for d in pool):raise ValueError('Date outside questionnaire season')
    groups={g:sorted(d for d in pool if stats[d]['stratum']==g) for g in GROUPS}
    available=[g for g in GROUPS if groups[g]]
    rng=random.Random('environment:'+str(seed));group=rng.choice(available);chosen=rng.choice(groups[group])
    return chosen,{'version':'weather_tertiles_verified_dates_v1','season':season,'seed':str(seed),
        'pool':list(pool),'stratum':group,'available_strata':available,
        'missing_strata':[g for g in GROUPS if not groups[g]],
        'stratum_sizes':{g:len(v) for g,v in groups.items()},
        'conditional_date_probability':1/len(available)/len(groups[group]),
        'selected_weather':stats[chosen],'uses_ratings':False,
        'conditioned_on':'station, questionnaire season, technical EP validation; equal available temperature strata',
        'interpretation':'Relative to this station and season, not national extreme-weather thresholds.'}

def candidates(epw,seed,per_stratum=3,season='summer',year=2007):
    if per_stratum<1:raise ValueError('At least one candidate per stratum')
    rows=weather_days(epw,year,season);rng=random.Random('candidate:'+str(seed));out=[]
    for group in GROUPS:
        choices=[r for r in rows if r['stratum']==group]
        out.extend(rng.sample(choices,min(per_stratum,len(choices))))
    return sorted(out,key=lambda r:r['date'])
