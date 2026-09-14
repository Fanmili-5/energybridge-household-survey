### 字段对应表
每行一个字段。原始值保存在 `raw_answers`，第二列为其中的键；成员字段中的 `[i]` 表示第几位成员。研究补充项只保存，不参与当前EB／EP。

**家庭日常**

<table fit-page-width="true" header-row="true">
<colgroup><col width="220"><col width="220"><col width="260"></colgroup>
<tr><td>问卷内容</td><td>JSON字段</td><td>后续用途</td></tr>
<tr><td>一起居住几个人？</td><td>B02</td><td>EP人员数量；6人以上按成员数</td></tr>
<tr><td>白天通常有人在家吗？</td><td>B04</td><td>EP白天在家比例</td></tr>
<tr><td>18:00—22:00有人在家吗？</td><td>F_EVENING</td><td>EP傍晚在家比例</td></tr>
<tr><td>全家的作息规律吗？</td><td>F_REGULARITY</td><td>EB作息背景，不改EP在家时段</td></tr>
<tr><td>零点后还经常使用电器吗？</td><td>F_LATE_USE</td><td>EB深夜活动背景，不改EP在家时段</td></tr>
</table>

**家庭成员**

<table fit-page-width="true" header-row="true">
<colgroup><col width="220"><col width="220"><col width="260"></colgroup>
<tr><td>问卷内容</td><td>JSON字段</td><td>后续用途</td></tr>
<tr><td>这位成员属于哪个年龄段？</td><td>M_MEMBERS[i].age_band</td><td>EB成员需求背景（由家庭代表代填）</td></tr>
<tr><td>平时处于什么生活状态？</td><td>M_MEMBERS[i].life_roles</td><td>EB成员需求背景（由家庭代表代填）</td></tr>
<tr><td>主要的生活节奏是什么？</td><td>M_MEMBERS[i].routine</td><td>EB成员需求背景（由家庭代表代填）</td></tr>
<tr><td>对室温变化敏感吗？</td><td>M_MEMBERS[i].comfort</td><td>EB成员需求背景（由家庭代表代填）</td></tr>
<tr><td>电器时间可以调整多少？</td><td>M_MEMBERS[i].task</td><td>EB成员需求背景（由家庭代表代填）</td></tr>
<tr><td>怎样参与家庭用电安排？</td><td>M_MEMBERS[i].participation</td><td>EB成员需求背景（由家庭代表代填）</td></tr>
<tr><td>家人通常优先考虑其需要吗？</td><td>M_MEMBERS[i].needs_priority</td><td>EB成员需求背景（由家庭代表代填）</td></tr>
<tr><td>多重视节省电费？</td><td>M_MEMBERS[i].cost_importance</td><td>EB成员需求背景（由家庭代表代填）</td></tr>
<tr><td>多重视配合错峰？</td><td>M_MEMBERS[i].grid_importance</td><td>EB成员需求背景（由家庭代表代填）</td></tr>
<tr><td>愿意让系统自动安排吗？</td><td>M_MEMBERS[i].control</td><td>EB成员需求背景（由家庭代表代填）</td></tr>
</table>

**家里有哪些电器**

<table fit-page-width="true" header-row="true">
<colgroup><col width="220"><col width="220"><col width="260"></colgroup>
<tr><td>问卷内容</td><td>JSON字段</td><td>后续用途</td></tr>
<tr><td>哪些设备纳入本次安排？</td><td>B05</td><td>确定进入本次EB／EP的设备</td></tr>
</table>

**空调**

<table fit-page-width="true" header-row="true">
<colgroup><col width="220"><col width="220"><col width="260"></colgroup>
<tr><td>问卷内容</td><td>JSON字段</td><td>后续用途</td></tr>
<tr><td>一般在哪个时段使用？</td><td>H_ac</td><td>选择空调原使用日程</td></tr>
<tr><td>自选时段几点开始？</td><td>H_ac_start</td><td>自选日程的开始时刻</td></tr>
<tr><td>自选时段几点结束？</td><td>H_ac_end</td><td>自选日程的结束时刻</td></tr>
<tr><td>通常设定多少度？</td><td>H_ac_temp</td><td>原方案制冷设定温度</td></tr>
<tr><td>希望室温保持在哪个范围？</td><td>P_AC_RANGE</td><td>EB舒适偏好，不直接改温控设定</td></tr>
<tr><td>最多接受室温变化多少？</td><td>P_AC_CHANGE</td><td>EB室温变化容忍度</td></tr>
</table>

**洗衣机**

<table fit-page-width="true" header-row="true">
<colgroup><col width="220"><col width="220"><col width="260"></colgroup>
<tr><td>问卷内容</td><td>JSON字段</td><td>后续用途</td></tr>
<tr><td>平时几点启动？</td><td>H_washer</td><td>形成原安排</td></tr>
<tr><td>一次运行多久？</td><td>T_washer</td><td>设置任务时长</td></tr>
<tr><td>最早几点可以开始？</td><td>E_washer</td><td>提供调度起点</td></tr>
<tr><td>最晚几点必须完成？</td><td>D_washer</td><td>提供完成期限</td></tr>
</table>

**洗碗机**

<table fit-page-width="true" header-row="true">
<colgroup><col width="220"><col width="220"><col width="260"></colgroup>
<tr><td>问卷内容</td><td>JSON字段</td><td>后续用途</td></tr>
<tr><td>平时几点启动？</td><td>H_dishwasher</td><td>形成原安排</td></tr>
<tr><td>一次运行多久？</td><td>T_dishwasher</td><td>设置任务时长</td></tr>
<tr><td>最早几点可以开始？</td><td>E_dishwasher</td><td>提供调度起点</td></tr>
<tr><td>最晚几点必须完成？</td><td>D_dishwasher</td><td>提供完成期限</td></tr>
</table>

**烘干机**

<table fit-page-width="true" header-row="true">
<colgroup><col width="220"><col width="220"><col width="260"></colgroup>
<tr><td>问卷内容</td><td>JSON字段</td><td>后续用途</td></tr>
<tr><td>平时几点启动？</td><td>H_dryer</td><td>形成原安排</td></tr>
<tr><td>一次运行多久？</td><td>T_dryer</td><td>设置任务时长</td></tr>
<tr><td>最早几点可以开始？</td><td>E_dryer</td><td>提供调度起点</td></tr>
<tr><td>最晚几点必须完成？</td><td>D_dryer</td><td>提供完成期限</td></tr>
</table>

**电热水器**

<table fit-page-width="true" header-row="true">
<colgroup><col width="220"><col width="220"><col width="260"></colgroup>
<tr><td>问卷内容</td><td>JSON字段</td><td>后续用途</td></tr>
<tr><td>通常几点开始加热？</td><td>H_electric_water_heater</td><td>设置原加热起点</td></tr>
<tr><td>通常加热到几点？</td><td>D_electric_water_heater</td><td>设置原加热终点</td></tr>
<tr><td>几点最需要热水？</td><td>P_HOT_WATER</td><td>热水需求时刻</td></tr>
<tr><td>能否提前加热？</td><td>P_PREHEAT</td><td>EB提前加热偏好</td></tr>
</table>

**家用电动车**

<table fit-page-width="true" header-row="true">
<colgroup><col width="220"><col width="220"><col width="260"></colgroup>
<tr><td>问卷内容</td><td>JSON字段</td><td>后续用途</td></tr>
<tr><td>几点在家接上充电设备？</td><td>H_home_ev</td><td>设置车辆接入时刻</td></tr>
<tr><td>接入后几点离家？</td><td>D_home_ev</td><td>设置离家期限和24小时统计起点</td></tr>
<tr><td>离家时至少要有多少电？</td><td>P_EV_TARGET</td><td>EV离家目标电量</td></tr>
<tr><td>临时出行至少保留多少电？</td><td>P_EV_RESERVE</td><td>EV最低备用电量</td></tr>
</table>

**全家更在意什么**

<table fit-page-width="true" header-row="true">
<colgroup><col width="220"><col width="220"><col width="260"></colgroup>
<tr><td>问卷内容</td><td>JSON字段</td><td>后续用途</td></tr>
<tr><td>愿意让系统自动安排到什么程度？</td><td>A_EB_CONTROL</td><td>EB家庭控制偏好，不代替最终同意</td></tr>
<tr><td>保持舒适有多重要？</td><td>P_COMFORT</td><td>EB舒适取舍，不自动生成评分</td></tr>
<tr><td>节省电费有多重要？</td><td>P_COST</td><td>EB费用取舍，不自动生成评分</td></tr>
<tr><td>配合错峰有多重要？</td><td>P_GRID</td><td>EB错峰取舍，不自动生成评分</td></tr>
<tr><td>希望提前多久通知？</td><td>P_NOTICE</td><td>EB通知偏好</td></tr>
</table>

**住房情况**

<table fit-page-width="true" header-row="true">
<colgroup><col width="220"><col width="220"><col width="260"></colgroup>
<tr><td>问卷内容</td><td>JSON字段</td><td>后续用途</td></tr>
<tr><td>常住哪个省级地区？</td><td>X_REGION</td><td>匹配天气资源</td></tr>
<tr><td>常住哪个城市？</td><td>X_CITY</td><td>优先匹配同城天气站</td></tr>
<tr><td>是哪种住房？</td><td>X_BUILDING</td><td>匹配建筑类型</td></tr>
<tr><td>住房面积大约多大？</td><td>X_AREA</td><td>建筑面积档位对应的原型</td></tr>
<tr><td>填的是哪种面积？</td><td>X_AREA_BASIS</td><td>室内面积或建筑面积换算</td></tr>
<tr><td>在楼房的什么位置？</td><td>X_FLOOR</td><td>匹配楼层边界</td></tr>
<tr><td>自住还是租住？</td><td>X_TENURE</td><td>留作后续研究</td></tr>
<tr><td>大约哪年建成？</td><td>X_BUILDING_AGE</td><td>研究补充，不改变建筑材料</td></tr>
</table>

**补充背景**

<table fit-page-width="true" header-row="true">
<colgroup><col width="220"><col width="220"><col width="260"></colgroup>
<tr><td>问卷内容</td><td>JSON字段</td><td>后续用途</td></tr>
<tr><td>家庭月总收入大约多少？</td><td>X_INCOME</td><td>后续分组研究</td></tr>
<tr><td>最近一个月电费大约多少？</td><td>X_BILL</td><td>后续分组研究</td></tr>
<tr><td>平时使用哪种电价？</td><td>X_TARIFF</td><td>研究补充，不替换仿真电价</td></tr>
<tr><td>还有哪些用能设备？</td><td>X_EXTRA_DEVICES</td><td>研究补充，不新增仿真设备</td></tr>
<tr><td>最不希望打扰哪些活动？</td><td>X_PROTECTED</td><td>保留生活影响偏好</td></tr>
<tr><td>用过定时或自动控制吗？</td><td>X_SMART</td><td>记录使用经验</td></tr>
<tr><td>参加过错峰用电活动吗？</td><td>X_DR</td><td>记录参与经验</td></tr>
<tr><td>影响生活时，会改回原安排吗？</td><td>X_RESTORE</td><td>记录恢复倾向</td></tr>
</table>

**设备数量与频率**

<table fit-page-width="true" header-row="true">
<colgroup><col width="220"><col width="220"><col width="260"></colgroup>
<tr><td>问卷内容</td><td>JSON字段</td><td>后续用途</td></tr>
<tr><td>空调有多少台（辆）？</td><td>X_COUNT_ac</td><td>研究补充；不增加仿真设备台数</td></tr>
<tr><td>空调一周使用几天？</td><td>X_FREQ_ac</td><td>研究补充；不自动生成周日程</td></tr>
<tr><td>洗衣机有多少台（辆）？</td><td>X_COUNT_washer</td><td>研究补充；不增加仿真设备台数</td></tr>
<tr><td>洗衣机一周使用几天？</td><td>X_FREQ_washer</td><td>研究补充；不自动生成周日程</td></tr>
<tr><td>洗碗机有多少台（辆）？</td><td>X_COUNT_dishwasher</td><td>研究补充；不增加仿真设备台数</td></tr>
<tr><td>洗碗机一周使用几天？</td><td>X_FREQ_dishwasher</td><td>研究补充；不自动生成周日程</td></tr>
<tr><td>烘干机有多少台（辆）？</td><td>X_COUNT_dryer</td><td>研究补充；不增加仿真设备台数</td></tr>
<tr><td>烘干机一周使用几天？</td><td>X_FREQ_dryer</td><td>研究补充；不自动生成周日程</td></tr>
<tr><td>家用电动车有多少台（辆）？</td><td>X_COUNT_home_ev</td><td>研究补充；不增加仿真设备台数</td></tr>
<tr><td>家用电动车一周使用几天？</td><td>X_FREQ_home_ev</td><td>研究补充；不自动生成周日程</td></tr>
<tr><td>电热水器有多少台（辆）？</td><td>X_COUNT_electric_water_heater</td><td>研究补充；不增加仿真设备台数</td></tr>
<tr><td>电热水器一周使用几天？</td><td>X_FREQ_electric_water_heater</td><td>研究补充；不自动生成周日程</td></tr>
</table>
