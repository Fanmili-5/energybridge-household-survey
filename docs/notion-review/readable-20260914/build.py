from pathlib import Path
import html, json

ROOT = Path(__file__).resolve().parents[3]
OUT = Path(__file__).parent
q = {x['id']: x for x in json.loads((ROOT/'QUESTIONNAIRE_CODEBOOK.json').read_text())['questions']}
groups = []
seen = []
def group(title, intro, rows):
    groups.append((title,intro,rows))
    seen.extend(r[0] for r in rows)

group('家庭日常','先了解人数和在家情况。',[
('B02','一起居住几个人？','1—5人／6人及以上','设置人员数量'),
('B04','白天通常有人在家吗？','大部分／部分／大部分没人／不固定','设置白天在家比例'),
('F_EVENING','18:00—22:00有人在家吗？','大部分／部分／大部分没人／不固定','设置傍晚在家比例'),
('F_REGULARITY','全家的作息规律吗？','大体固定／部分固定／变化较多','给EB提供作息背景'),
('F_LATE_USE','零点后还经常使用电器吗？','经常／偶尔／很少或没有','给EB提供深夜活动背景')])
group('家庭成员','每位成员分别填一组。生活节奏必填，其余选填；由同一人代填，不是每位成员独立回答。',[
('M.age_band','这位成员属于哪个年龄段？','未满18岁／18—59岁／60岁及以上','保留家庭年龄构成'),
('M.life_roles','平时处于什么生活状态？','上学、工作、退休等，可多选','补充成员背景'),
('M.routine','主要的生活节奏是什么？','固定外出／主要在家／内外兼有／不规律','给EB提供成员作息'),
('M.comfort','对室温变化敏感吗？','较大变化也能适应／只接受小幅变化／小幅也不适','记录舒适偏好'),
('M.task','电器时间可以调整多少？','按时完成即可／只接受小幅调整／尽量不调','记录时间弹性'),
('M.participation','怎样参与家庭用电安排？','通常不参与／共同商量／主要决定','记录决策参与情况'),
('M.needs_priority','家人通常优先考虑其需要吗？','会优先考虑／没有特别优先','记录需求优先程度'),
('M.cost_importance','多重视节省电费？','1—5档：不重要 → 非常重要','记录个人节费偏好'),
('M.grid_importance','多重视配合错峰？','1—5档：不重要 → 非常重要','记录个人错峰态度'),
('M.control','愿意让系统自动安排吗？','范围内自动／每次先问／自己安排','记录个人控制偏好')])
group('家里有哪些电器','只展开所选设备的问题。',[
('B05','哪些设备纳入本次安排？','空调／洗衣／洗碗／烘干／热水器／家用EV／都没有','确定参与模拟的设备')])
group('空调','时间按10分钟选择，温度可选到0.1℃。',[
('H_ac','一般在哪个时段使用？','下午到睡前／傍晚到睡前／全天／自选','确定原使用日程'),
('H_ac_start','自选时段几点开始？','时刻滑块','确定原使用起点'),
('H_ac_end','自选时段几点结束？','时刻滑块，可跨午夜','确定原使用终点'),
('H_ac_temp','通常设定多少度？','22—28℃','确定原制冷设定'),
('P_AC_RANGE','希望室温保持在哪个范围？','在18—30℃内选最低和最高值','提供舒适范围'),
('P_AC_CHANGE','最多接受室温变化多少？','0—5℃','提供可接受变化幅度')])
for dev,name in [('washer','洗衣机'),('dishwasher','洗碗机'),('dryer','烘干机')]:
    group(name,'每种设备单独填写以下四题。',[
    ('H_'+dev,'平时几点启动？','时刻滑块，10分钟一档','形成原安排'),
    ('T_'+dev,'一次运行多久？','10—240分钟','设置任务时长'),
    ('E_'+dev,'最早几点可以开始？','时刻滑块，10分钟一档','提供调度起点'),
    ('D_'+dev,'最晚几点必须完成？','时刻滑块，10分钟一档','提供完成期限')])
group('电热水器','时间按10分钟选择。当前午夜或跨夜加热可保存，但暂不能生成模拟。',[
('H_electric_water_heater','通常几点开始加热？','时刻滑块','设置原加热起点'),
('D_electric_water_heater','通常加热到几点？','时刻滑块','设置原加热终点'),
('P_HOT_WATER','几点最需要热水？','时刻滑块','提供热水需求时点'),
('P_PREHEAT','能否提前加热？','可以／每次先确认／不希望','提供提前加热偏好')])
group('家用电动车','仅包括能在家充电的汽车。电池容量和初始电量来自模型。',[
('H_home_ev','几点在家接上充电设备？','时刻滑块，10分钟一档','设置车辆接入时刻'),
('D_home_ev','接入后几点离家？','时刻滑块，可表示次日','设置离家期限和24小时统计起点'),
('P_EV_TARGET','离家时至少要有多少电？','0—100%，10%一档','设置离家目标'),
('P_EV_RESERVE','临时出行至少保留多少电？','0—100%，10%一档','提供备用电量要求')])
group('全家更在意什么','这里是一份综合家庭意见，与逐成员偏好分开保留。',[
('A_EB_CONTROL','愿意让系统自动安排到什么程度？','范围内自动／每次先问／自己安排','提供家庭控制偏好'),
('P_COMFORT','保持舒适有多重要？','1—5档：不重要 → 非常重要','提供舒适取舍'),
('P_COST','节省电费有多重要？','1—5档：不重要 → 非常重要','提供费用取舍'),
('P_GRID','配合错峰有多重要？','1—5档：不重要 → 非常重要','提供错峰取舍'),
('P_NOTICE','希望提前多久通知？','无需提前至三天或更早，分档选择','提供通知偏好')])
group('住房情况','用于选择研究模型，不是还原某户真实住宅。',[
('X_REGION','常住哪个省级地区？','省级地区列表','匹配天气资源'),
('X_CITY','常住哪个城市？','联动选择或填写','优先匹配同城天气站'),
('X_BUILDING','是哪种住房？','楼房一套／独立／联排／其他','匹配建筑类型'),
('X_AREA','住房面积大约多大？','五档：不足50㎡至160㎡及以上','匹配面积原型'),
('X_AREA_BASIS','填的是哪种面积？','建筑面积／套内可使用面积','确定面积换算口径'),
('X_FLOOR','在楼房的什么位置？','底层／中间层／顶层','匹配楼层边界'),
('X_TENURE','自住还是租住？','自有／整租／合租／其他','留作后续研究'),
('X_BUILDING_AGE','大约哪年建成？','2000年前至2020年后，四档','留作后续研究')])
group('补充背景（选填）','这些答案目前只保存，不改变EB规划或EP仿真。',[
('X_INCOME','家庭月总收入大约多少？','五档：不足5000至30000元及以上','后续分组研究'),
('X_BILL','最近一个月电费大约多少？','五档：不足100至1000元及以上','后续分组研究'),
('X_TARIFF','平时使用哪种电价？','单一时段／峰谷／其他','后续分组研究'),
('X_EXTRA_DEVICES','还有哪些用能设备？','冰箱、采暖、光伏、储能等，多选','补充设备背景'),
('X_PROTECTED','最不希望打扰哪些活动？','工作学习、休息、照护等，多选','保留生活影响偏好'),
('X_SMART','用过定时或自动控制吗？','经常／偶尔／没有','记录使用经验'),
('X_DR','参加过错峰用电活动吗？','参加过／没有','记录参与经验'),
('X_RESTORE','影响生活时，会改回原安排吗？','保留自动／先看影响／改回原安排','记录恢复倾向')])
rows=[]
for dev,name in [('ac','空调'),('washer','洗衣机'),('dishwasher','洗碗机'),('dryer','烘干机'),('home_ev','家用电动车'),('electric_water_heater','电热水器')]:
    rows.extend([('X_COUNT_'+dev,name+'有多少台（辆）？','1／2／3及以上','保留设备数量'),('X_FREQ_'+dev,name+'一周使用几天？','0／1／2—3／4—6／每天','保留使用频率')])
group('设备数量与频率（选填）','只问已选设备。模拟仍按每类一个设备模型运行。',rows)
assert set(seen)==(set(q)-{'M_MEMBERS'})|{'M.'+f['id'] for f in q['M_MEMBERS']['fields']}
assert len(seen)==len(set(seen))

def table(rows):
    return '<table fit-page-width="true" header-row="true">\n<colgroup><col width="220"><col width="280"><col width="200"></colgroup>\n' + '\n'.join('<tr>'+''.join('<td>'+html.escape(c)+'</td>' for c in row)+'</tr>' for row in [('问什么','怎么回答','用在哪里')]+[r[1:] for r in rows])+'\n</table>\n'
md='\n'.join('### '+title+'\n'+intro+'\n'+table(rows) for title,intro,rows in groups)
(OUT/'field-introduction.md').write_text(md)
web='<html lang="zh"><meta charset="utf-8"><title>字段介绍 · 阅读检查</title><style>body{margin:0;padding:28px;background:#fff;color:#25342f;font:16px/1.6 -apple-system,BlinkMacSystemFont,"PingFang SC",sans-serif}main{width:700px}h2{font-size:26px;margin:30px 0 10px}p{color:#5c6861}table{border-collapse:collapse;width:700px;table-layout:fixed}th,td{border:1px solid #dce3df;padding:13px 12px;vertical-align:top;font-size:16px}th{text-align:left;background:#edf3ee}th:nth-child(1){width:29%}th:nth-child(2){width:40%}th:nth-child(3){width:25%}</style><main>'
for title,intro,rows in groups:
    web+='<h2>'+title+'</h2><p>'+intro+'</p><table><tr><th>问什么</th><th>怎么回答</th><th>用在哪里</th></tr>'+''.join('<tr>'+''.join('<td>'+html.escape(c)+'</td>' for c in r[1:])+'</tr>' for r in rows)+'</table>'
(OUT/'field-preview.html').write_text(web+'</main></html>')
print(json.dumps({'rows':len(seen),'groups':len(groups),'top_level_fields':len(q),'member_subfields':10}))
