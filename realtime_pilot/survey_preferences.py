"""Direct preference questions adapted from the colleague's questionnaire.
Importance ratings are observations, never normalized into evaluator weights.
"""
from questionnaire_persona import question

def preference(qid,prompt,options,dimension,device=None):
    q=question(qid,prompt,options,group='stated_preference',dimension=dimension)
    q['required']=True
    if device:q.update(device=device,active_only=True)
    return q
IMPORTANCE=[(str(i),label) for i,label in enumerate(['不重要','不太重要','一般','比较重要','非常重要'],1)]
FAMILY=[
 preference('P_COMFORT','考虑用电调整时，保持家人舒适对您家有多重要？',IMPORTANCE,'comfort_importance'),
 preference('P_COST','考虑用电调整时，节省电费对您家有多重要？',IMPORTANCE,'cost_importance'),
 preference('P_GRID','不明显影响生活时，配合电网错峰用电对您家有多重要？',IMPORTANCE,'grid_support_importance'),
 preference('P_NOTICE','用电调整前，希望提前多久收到通知？（选择最接近的一项）',[('0','无需提前'),('0.5','半小时'),('1','1 小时'),('3','3 小时'),('6','6 小时'),('12','半天'),('24','一天'),('48','两天'),('72','三天或更早')],'notice_required_h'),
]
DEVICES=[
 preference('P_AC_RANGE','在本次指定月份，在家时，您家通常希望室温保持在哪个范围？（选择最接近的一项）',[(x,x.replace('_','—')+'℃') for x in ['18_20','20_22','22_24','23_25','24_26','25_27','26_28','28_30']],'preferred_room_temperature','ac'),
 preference('P_AC_CHANGE','为了配合错峰，您最多能接受室温比平时变化多少？（选择最接近的一项）',[(str(v),('不接受变化' if v==0 else f'约 {v:g}℃')) for v in [0,.5,1,1.5,2,2.5,3,4,5]],'temperature_change_tolerance','ac'),
 preference('P_EV_TARGET','离家出发时，希望电动汽车电量至少达到多少？（按10%档选择；含插混，不含电动自行车）',[(str(v),f'{v*100:.0f}%') for v in [0,.1,.2,.3,.4,.5,.6,.7,.8,.9,1]],'ev_target_soc','home_ev'),
 preference('P_EV_RESERVE','为临时出行，电动汽车平时至少希望保留多少电量？（按10%档选择）',[(str(v),f'{v*100:.0f}%') for v in [0,.1,.2,.3,.4,.5,.6,.7,.8,.9,1]],'ev_min_soc','home_ev'),
 preference('P_HOT_WATER','家里通常最需要热水的时间是？',[(str(i),f'{i:02d}:00') for i in range(24)],'bath_required_h','electric_water_heater'),
 preference('P_PREHEAT','保证使用时有热水的前提下，您是否愿意提前加热？',[('yes','可以提前安排'),('confirm','每次先确认'),('no','不希望提前加热')],'preheat_preference','electric_water_heater'),
]
