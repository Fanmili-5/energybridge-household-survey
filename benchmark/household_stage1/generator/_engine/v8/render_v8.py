"""Readable complete cards remain on the server beside the frozen records."""
from pathlib import Path
from collections import Counter
import json
import adapter_v8 as a
ROOT=Path(__file__).resolve().parent
COUNTRY={'CN':'中国','US':'美国','GB':'英国','ES':'西班牙','IN':'印度','MX':'墨西哥','AU':'澳大利亚','DE':'德国'}
FUNCTION={'AC':'空调','WM':'洗衣','DR':'烘干','DW':'洗碗','WH':'储水式电热水','EV':'电动车充电'}
JOB={'employed':'就业','employed_full_time':'全职','employed_part_time':'兼职','retired':'退休','not_employed':'未就业','home_caregiver':'居家照护','student':'学生','not_in_workforce':'非劳动力','unable_to_work':'不能工作'}
KIND={'work':'工作与通勤','study':'学习','school':'上学','nursery':'托幼','transport':'上学交通','escort':'接送','community_program':'外出办事/活动','family_outing':'共同外出','extended_school_care':'校前后照护','school_waiting':'学校等候/自习','overnight_visit':'过夜外出'}
REL={1:'户主',2:'配偶',3:'父母',4:'配偶父母',5:'子女',6:'子女配偶',7:'兄弟姐妹',8:'祖父母',9:'孙辈'}
DAY=['周一','周二','周三','周四','周五','周六','周日']
def rows(p):return [json.loads(x) for x in p.read_text().splitlines()]
def clock(v):v=int(v);return f'{v//60:02d}:{v%60:02d}'
def span(a,b):return clock(a)+'—'+clock(b)
def compact(v):return json.dumps(v,ensure_ascii=False,sort_keys=True)
def card(c):
    h=c['household'];p=c['household_provenance'];co=c['source']['country'];role=c['benchmark_role']
    text=[f'## {COUNTRY[co]} {role}类：{c["card"]["core"]}',f'案例 `{c["case_id"]}`；源调查 {c["source"]["dataset"]}；源户键 `{c["source"]["household_key"]}`。',
      f'【同户调查支持】家庭总人数 {c["household_size"]["value"]}。源事实保持原始调查年份；不是2026年实户重建。',
      f'【实验】角色承担者 {h["decision_maker_id"]}；六类角色和态度由EB实验条件指定，不是调查对该户的自然分类。']
    if co=='CN':
        text+=['源户主只作为记录锚点 '+h['source_record_anchor_member_id']+'；调查实际回答者没有逐人链接，不把户主自动说成回答者。',
          '【同户调查】平常是否有人整天在家：'+compact(c['known_presence']['value'])+'；人数原答复 '+compact(c['source_presence_details']['reported_usual_all_day_person_count']['value'])+'；在家工作人数 '+compact(c['source_presence_details']['reported_teleworker_count']['value'])+'。',
          '【实验解释】通常“整天在家”不是逐人逐日轨迹。肯定回答要求参考工作日有成人09—15点在家；否定回答要求每名成人09—17点有外出，不能推成全屋无人。原人数不冒充参考周实测人数。']
    elif co in ('GB','ES','DE'):
        text+=['【同户调查】女性人数档（≤18、18—65、>65）：'+compact([x['value'] for x in c['members_summary']['value'][:3]])+'；男性对应档：'+compact([x['value'] for x in c['members_summary']['value'][3:]])+'。',
          '个人C4G供暖语境原答复：'+compact(c['known_presence']['value'])+'；不是“全家某人在家天数”。2019为数据发布年，逐人访问年未链接。',
          '调查受访者绑定参考槽位：'+str(h['source_respondent_member_id'])+'，依原性别、出生年区间和职业核对；其他成员是性别年龄人数支持的匿名槽位。']
    else:text+=['【同户调查/派生】在家回答原范围：'+compact(c['known_presence'])+'。原答复不等同精确钟点。']
    text+=['','| 成员 | 年龄与来源 | 职业与来源 | 补充说明 |','|---|---|---|---|']
    for m in h['members']:
        mid=m['id'];status=p[f'members.{mid}.reference_age']['status'];jobstatus=p[f'members.{mid}.employment']['status']
        note='源人员键 '+str(m.get('source_person_key','未识别具体人'))
        if co=='CN':note+='；同户亲属关系 '+REL.get(m['relationship_to_head'],str(m['relationship_to_head']))+'；出生年 '+str(m['source_birth_year'])
        if m.get('sex_from_source'):note+='；原性别/人数槽位 '+m['sex_from_source']
        if m.get('observed_age_is_censored_lower_bound'):note+='；98为上端编码，真实年龄可更高'
        text+=[f'| {mid} | {m["reference_age"]}岁【{status}】；源区间{compact(m["source_age_band"])} | {JOB.get(m["employment"],m["employment"])}【{jobstatus}】 | {note} |']
    text+=['','住房原信息【同户调查】：类型 '+compact(c['dwelling']['observed_type'])+'；面积/房间数 '+compact(c['dwelling']['size'])+'。',
      '本卡运行住房【匹配或实验，以字段标记为准】：'+compact(h['dwelling'])+'。面积不是已验收IDF。']
    if co=='MX':text+=['墨西哥住房类型来自ENIGH跨户匹配，完整匹配条件、候选池和未匹配维度：'+compact(c['dwelling']['reference_type'])+'。不得称为ENASIC同户实测房型。']
    text+=['','| 六类功能 | 源调查支持 | 参考控制接入【实验】 |','|---|---|---|']
    for f,key in a.KEY.items():
        inv=h['control_inventory'][f];source=c['devices'][key]
        support='有' if source['value'] is True else '明确无' if source['value'] is False else '原调查未确认'
        text+=[f'| {FUNCTION[f]} | {support}【{source["status"]}】，原字段 {compact(source["fields"])} | '+('控制；' if inv['enabled'] else '不控制；')+('有安装/技术替换台账' if inv.get('installation_or_retyping') else '无新增安装/替换')+' |']
    if co in ('GB','ES','DE'):text+=['原H11G独立电热水器子类型：'+compact(c['source_technology_presence'])+'。没有该子类型不等于没有热水。冰箱用H11D，H11A是炉灶；这些背景电器不计入六类覆盖。']
    if co=='IN':text+=['原每周洗衣机使用次数【同户调查】：'+compact(c['source_laundry_weekly_uses'])+'；原电热水器容量：'+compact(c['source_device_details'])+'。']
    text+=['实验态度：'+compact(h['attitudes'])+'；舒适边界：'+compact(h['comfort'])+'。',
      '设备增配/技术替换均为实验场景条件；原始“没有/未知”保持不变。储水箱、EV与停车接电并未因此取得物理验收。',
      '每周完整洗衣需求 '+str(h['routine']['laundry_cycles_per_week'])+' 次；具体程序时长另由后续阶段绑定。洗/烘/洗碗为不可任意切断的完整周期；烘干要等同批洗衣；EV连续一次补能。',
      '角色控制授权【实验】：'+compact(h['decision_authorization'])+'。不是实际家庭同意的证据。']
    if h.get('observed_care_links'):text+=['同户调查照护联系（原调查期间，非参考周实测）：'+compact(h['observed_care_links'])+'。']
    if h.get('role_care_binding'):text+=['角色照护绑定：'+compact(h['role_care_binding'])+'；来源状态按本字段保留，具体参考周安排为实验。']
    text+=['','以下是完整参考周【实验】。有原始工作量、托幼时长和频率时必须保留；具体钟点、未测身份、外部照护和通勤安排不冒充同户实测。','']
    for d,day in enumerate(h['routine']['daily_services']):
        base=d*1440;text+=['### '+DAY[d],'']
        events=[e for e in h['calendar']['weekly_events'] if base<=e['start']<base+1440 and e['kind']!='bathing']
        for e in events:
            suffix=('在家' if e['location']=='home' else '在外')
            if e['kind']=='work':suffix+=f'；计薪{e["paid_minutes"]/60:g}h，往返通勤{e["commute_roundtrip_minutes"]}min'
            text+=['- '+e['member_id']+' '+span(e['start']-base,e['end']-base)+' '+KIND.get(e['kind'],e['kind'])+'，'+suffix+'。']
        text+=['- 未列外出的成员在家；居家工作、学习、洗浴仍占用其时间。']
        for meal in day['meals']:text+=['- '+{'breakfast':'早餐','lunch':'午餐','dinner':'晚餐'}[meal['kind']]+' '+span(meal['start'],meal['end'])+'：'+','.join(meal['participants'])+' '+meal['location']+'。']
        text+=['- 洗浴：'+'；'.join(x['member_id']+' '+span(x['start'],x['end'])+('，协助 '+x['assistant_id'] if x['assistant_id'] else '') for x in day['bathing_services'])+'。',
          '- 实际手动操作窗口：'+'；'.join(x['member_id']+' '+span(x['start'],x['end']) for x in day['manual_operation_opportunities'])+'。电器完整运行窗口另按服务接口约束。']
        for arrangement in h['care_arrangements']:
            pieces=[x for x in arrangement['home_supervision'] if max(base,x['start'])<min(base+1440,x['end'])]
            if pieces:text+=['- '+arrangement['child_id']+'居家照护：'+'；'.join(x['caregiver_id']+' '+span(max(base,x['start'])-base,min(base+1440,x['end'])-base)+' '+x.get('mode','') for x in pieces)+'。']
    if h['ev']:text+=['','EV连续补能与停车机会【实验】：'+compact(h['ev'])+'。停车机会不等于每天重复一份SOC需求。']
    text+=['','原始数据中的未测量项目保持未测量；运行所需信息由显式实验条件补齐。10题是覆盖蓝图，当前实际A/B问题、物理结果和真人回答均为0。','','---','']
    return '\n'.join(text)
