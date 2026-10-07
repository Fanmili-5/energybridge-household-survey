"""Create1000reviewable assigned-role packets with explicit epistemic masks.
Public material excludes numerical task outcomes; private model labels and
future human answers are separate. No actor consent,personality,income or
actual installation is invented. These are review candidates,not releases.
"""
import collections,hashlib
from common import *
KITCHEN={'exclusive':'独立使用专用厨房','shared':'与其他户合用专用厨房','none':'没有专用厨房'}
TOILET={'flush_sanitary':'水冲式卫生厕所','flush_nonsanitary':'水冲式非卫生厕所','sanitary_dry':'卫生旱厕','ordinary_dry':'普通旱厕','none':'住房内无厕所'}
REL={'partner_or_spouse_of':'伴侣或配偶','child_of':'子女','parent_of':'父母','grandchild_of':'孙辈','grandparent_of':'祖辈','sibling_of':'兄弟姐妹','child_partner_of':'子女的伴侣','parent_of_partner_of':'伴侣的父母'}
WASH_DURATION={1:15,2:30,3:45,4:60,5:90,6:120,7:159}
def main():
 guard();profiles=read(V7/'HOUSEHOLDS1000_JOINT_GEOMETRY_CANDIDATE.json')['profiles'];bindings={r['household_id']:r for r in read(V10/'SERVICE_PORT_BINDINGS.json')['records']};event=read(OUT/'EVENT_RESULTS.json');pairs=collections.defaultdict(list)
 for p in event['pairs']:pairs[p['household_id']].append(p)
 runs={(r['household_id'],r['kind'],r['variant']):r for r in event['runs']};historic={r['household_id']:r for r in read(V9/'DEVICE_PRIOR_ROUTES1000.json')['routes']}
 for folder in ['role_packets','public_role_cards','private_case_labels']:(OUT/folder).mkdir(exist_ok=True)
 records=[];counts=collections.Counter();candidates=[]
 for profile in profiles:
  hid=profile['slot_id'];r=bindings[hid];case=read(V10/r['service_world_path']);w=case['world'];f=w['stock_reference_features'];family=profile['family'];adult=w['operator_context']['adult_reference_candidates'];ports=case['service_model']['instantiated_reference_ports'];tasks=[]
  for pair in sorted(pairs[hid],key=lambda p:p['kind']):
   base=runs[hid,pair['kind'],'baseline'];kind=pair['kind'];op=base['operator_reference_ID']
   if kind=='washer':
    tasks.append({'task_id':hid+'_wash_shift','kind':'washer','public_event_context':{'event_window':'19:00–20:00','release_time':'18:00','original_start':'18:50','suggested_start':'20:00','duration_minutes':159,'completion_deadline':'24:00','clothes_reference_load_kg':8,
     'proposal':'在启动前把本次指定洗衣程序推迟至20:00；程序开始后不中断。'},'stipulated_operator_ID':op,'operator_presence_and_permission':'provided experimentally for this task;not observed source or willingness','task_source_and_state':{'device_program':'V9 Miele8kg namedtest;V11 timing declared','initial_state':'idle before declared release'},'state_known_in_this_reference_task':True,'factual_income_or_care_or_usual_clock_not_added':True})
   else:
    tasks.append({'task_id':hid+'_tank_defer','kind':'water_heater','public_event_context':{'event_window':'19:00–20:00','proposal':'参考储水热水器在19:00–20:00暂缓加热，20:00恢复；满足随后规定的取水服务。','requested_water_volume_L':30,'draw_window':'20:30–20:40','requested_temperature_metric':'取水时段的5分钟平均出水温度','requested_temperature_C':40,
     'tank_volume_L':60,'target_setpoint_C':55,'recovery_reference_power_W':3300},'stipulated_operator_ID':op,'operator_presence_and_permission':'provided experimentally for this task;not observed source or willingness','task_source_and_state':{'hardware':'V9 Haier60L selectedscalar port;UA/Mixed controller are reference','preconditioning':'same six-day history and one quiet reference operator;not personal diary'},'state_known_in_this_reference_task':True,'factual_income_or_care_or_usual_clock_not_added':True})
  facts={'household_id':hid,'role_representative_member_id':family['reference_member_id'],'representative_is_not_claimed_observed_household_head':True,'population_frame':'2020年城市普通住宅家庭户的合成参考；不含镇/乡村/集体/非普通住所','province':profile['province'],'resident_count':family['resident_count'],'generation_count':family['generation_count'],
   'members':[{'member_id':m['member_id'],'age_years_reference':m['age_years'],'sex_reference':m['sex'],'generation_level':m['generation_level']} for m in family['members']],
   'member_relations':family['ego_relationships'],'H6_building_area_reference_m2':profile['housing']['H6_census_building_area_design_m2'],'H7_independent_natural_rooms_reference':profile['housing']['H7_independent_natural_rooms_design'],
   'census_marginal_reference_housing_features':f,'kitchen_reference':KITCHEN[f['kitchen']],'toilet_reference':TOILET[f['toilet']],
   'physical_reference_device_instances':[{'instance_ID':p['instance_reference_ID'],'kind':p['kind'],'room_id':p['room_id'],'parameter_port':p['parameter_port'],'installation_identity':'declared reference,not observed home hardware'} for p in ports],
   'reference_household_adult_candidates':adult,'no_adult_requires_assistance_or_nonmanual_task':not bool(adult)}
  evidence={'demographic_housing_controls':{'status':'official_marginal_calibrated_and_synthetic_joint','source_file':'../idf_joint_production_20261005/HOUSEHOLDS1000_JOINT_GEOMETRY_CANDIDATE.json','sha256':sha(V7/'HOUSEHOLDS1000_JOINT_GEOMETRY_CANDIDATE.json')},
   'housing_facets':{'status':'official_marginal_reference_assignment_not_observed_individual','source_file':'../production_evidence_completion_20261006/PRODUCTION_REFERENCE1000.json','sha256':sha(V9/'PRODUCTION_REFERENCE1000.json')},
   'housing_and_installed_partial_ports':{'status':'declared_experimental_world','source_file':str((V10/r['service_world_path']).relative_to(BASE)),'sha256':r['service_world_sha256']},
   'historical_asset_auxiliary_pattern':{'status':'matched2012auxiliary_not2020current_inventory','match_route':historic[hid]['match_route'],'source_pool_count':historic[hid]['source_pool_count']},
   'task_context':{'status':'experimentally_stipulated_and_model_checked_where_supported','usual_household_clock_observed':False},
   'preference_or_willingness':{'status':'to_be_observed_in_future_assigned_role_collection','value':None},
   'wholehome_inventory_income_health_mobility_care_actual_city_floor':{'status':'not_identified_from_inputs','value':None,'handling':'request additional assigned context;do not invent or relabel missing as absence'}}
  # Each role has a reviewable collection episode. Source-supported functional
  # proposals are a distinct semantic track; they are not new installed devices
  # or unverified kWh labels. Unknown-info episodes remain a legitimate stratum.
  semantic=None
  if not tasks:
   assets=historic[hid]['auxiliary_reported_assets'];wash=next((a for a in assets if a['class']=='washer' and a.get('duration_bin') in WASH_DURATION),None)
   ac=next((a for a in assets if a['class']=='split_AC'),None)
   if wash:
    code=wash['duration_bin'];duration=WASH_DURATION[code]
    semantic={'track':'source_supported_functional_proposal','component_class':'washer','historical_report_reference_id':wash['report_reference_id'],
     'historical_reference_year':2012,'source_duration_bin':code,'exact_task_duration_minutes_design':duration,'exact_duration_is_experiment_not_observed_clock':True,
     'proposal':f'本次参考洗衣任务原拟18:50启动，给定时长{duration}分钟、24:00前完成；希望你考虑把启动推迟至20:00，程序开始后不进行断电中断。',
     'assigned_role_device_condition':'本提案以角色可使用该类洗衣服务为条件；类别及区间来自历史辅助报告，具体品牌/功率/完整安装未恢复',
     'operator_context':{'resident_adult_candidate':adult[0] if adult else None,'manual_action_if_no_adult':'requires an explicitly provided nonresident helper or other plan;not automatically enabled'},
     'permission_presence_and_other_personal_constraints':'if not supplied,request clarification rather than assume','physical_kWh_or_delivered_reduction_label':None,'physical_model_admitted':False}
   elif ac:
    semantic={'track':'source_supported_functional_proposal','component_class':'split_AC','historical_report_reference_id':ac['report_reference_id'],'historical_reference_year':2012,
     'capacity_like_source_bin':ac['cooling_capacity_like_bin_not_electric_input'],'proposal':'事件窗19:00–20:00，考虑改变空调设定以减少该时段用电。请先说明你需要知道的在场成员、室温、舒适要求及控制条件，再表达接受、拒绝或调整。',
     'assigned_role_device_condition':'仅给定分体空调服务这一参考条件；不会把热容量码解释为电功率或假定遥控权限',
     'physical_kWh_or_delivered_reduction_label':None,'physical_model_admitted':False}
   else:semantic={'track':'information_elicitation','proposal':'请根据给定家庭、住房和部分信息，列出制定家庭负荷调整方案前必须澄清的设备、时钟、操作者与服务约束。未给出的内容回答未知。','physical_kWh_or_delivered_reduction_label':None,'physical_model_admitted':False,'no_supported_report_is_not_device_absence':True}
  public={'facts':facts,'tasks':tasks,'additional_collection_episode':semantic,'instruction':'请按给定合成角色和任务情景表达判断。事实、实验设定和你的价值判断分开；未给出的具体收入、健康、照护、作息、硬件等信息，可明确回答无法判断或请求补充。接受、拒绝、调整和需要澄清都保留。',
   'response_fields':['decision:accept/reject/modify/need_clarification/unknown','reasons_in_your_own_words','facts_used_from_packet','information_needed','modified_plan_if_any'],
   'no_task_handling':'本户使用功能条件或信息澄清场景；技术电量标签未准入，回答用于条件角色意见，不补成节能/交付真值。' if not tasks else None}
  packet={'household_id':hid,'public_role_material':public,'evidence':evidence,'numeric_oracle_separated_path':'private_case_labels/'+hid+'.json',
   'role_material_schema_complete':True,'review_candidate_created':True,'complete_wholehome_actor_world':False,'human_review_complete':False,'formal_human_answer':None,'collection_release':False,'training_release':False}
  private={'household_id':hid,'component_model_labels':pairs[hid],'not_human_acceptance_truth':True,'formal_human_answers':None,'coverage_no_supported_task_is_not_zero_DR_or_no_appliances':True}
  save(OUT/'role_packets'/(hid+'.json'),packet);save(OUT/'private_case_labels'/(hid+'.json'),private)
  members='；'.join(str(m['age_years_reference'])+'岁'+('女' if m['sex_reference']=='female' else '男' if m['sex_reference']=='male' else '性别未指定') for m in facts['members'])
  text='# 角色审阅卡 '+hid+'\n\n'+facts['population_frame']+'。你扮演家庭代表'+family['reference_member_id']+'。\n\n'+f"所在省份：{facts['province']}；参考常住{facts['resident_count']}人、{facts['generation_count']}代；成员：{members}。参考建筑面积{facts['H6_building_area_reference_m2']}m²，独立自然间{facts['H7_independent_natural_rooms_reference']}间。\n\n"+facts['kitchen_reference']+'；'+facts['toilet_reference']+'。这些是分配给本角色的参考条件，不是实际住户观察。\n\n'
  text+='成员关系：'+('；'.join(rr['subject']+'是'+rr['object']+'的'+REL[rr['type']] for rr in family['ego_relationships']) if family['ego_relationships'] else '单人参考家庭')+'。未声明的成员之间具体亲生/姻亲关系保持未指定。\n\n'
  text+='本轮明确的参考组件：'+('、'.join(p['kind'] for p in ports) if ports else '尚无已核验组件端口')+'。完整现实设备清单未提供。\n\n'
  for t in tasks:text+='任务：'+t['public_event_context']['proposal']+'\n\n'+('洗衣时长159分钟、18:00释放、24:00前完成；原18:50启动，提议20:00启动。' if t['kind']=='washer' else '20:30—20:40参考取水30L，取水时段5分钟平均出水温度至少40°C。')+'指定操作员：'+t['stipulated_operator_ID']+'；在场和控制许可为本次实验设定，接受意愿尚未给出。\n\n'
  if not tasks:text+=public['no_task_handling']+'\n\n'+semantic['proposal']+'\n\n'
  if not adult:text+='参考成员中没有成年人。手动动作保持未启用；协助者与权限必须另行明确，不增加常住成员来凑条件。\n\n'
  text+=public['instruction']+'\n\n请回答是否接受、拒绝、希望修改或需要更多信息，并解释理由。\n';path=OUT/'public_role_cards'/(hid+'.md');path.write_text(text)
  records.append({'household_id':hid,'packet_path':'role_packets/'+hid+'.json','packet_sha256':sha(OUT/'role_packets'/(hid+'.json')),'public_card_path':str(path.relative_to(OUT)),'public_card_sha256':sha(path),'private_labels_path':'private_case_labels/'+hid+'.json','private_labels_sha256':sha(OUT/'private_case_labels'/(hid+'.json')),'supported_component_tasks':len(tasks),'ready_for_human_protocol_review':True,'collection_admitted':False})
  counts['role_review_packets']+=1;counts['role_materials_with_component_tasks']+=bool(tasks);counts['component_tasks']+=len(tasks);counts['role_materials_without_physical_task_labels']+=not bool(tasks);counts['no_adult_roles']+=not bool(adult)
  if semantic:counts[semantic['track']+'_episodes']+=1
  # Positive historical reports that fit additional manufacturer parameter
  # ports do not silently become installed devices or equivalent Haier units.
  cand=[]
  for a in historic[hid]['auxiliary_reported_assets']:
   if a['class']!='split_AC':continue
   b=a['cooling_capacity_like_bin_not_electric_input'];model={2:'MUZ-AP25VG',4:'MUZ-AP35VG',5:'MUZ-AP42VG',6:'MUZ-AP50VG'}.get(b)
   if model:cand.append({'report_reference_id':a['report_reference_id'],'historical_capacity_bin':b,'reference_performance_model':model,'status':'parameter_candidate_only;indoor_pair,installation,fan/latent/control anddomain must be resolved', 'actual_source_model_identity_observed':False})
  candidates.append({'household_id':hid,'supported_reference_parameter_candidates':cand,'bin3_2500W_shared_endpoint_quarantined':any(a['class']=='split_AC' and a['cooling_capacity_like_bin_not_electric_input']==3 for a in historic[hid]['auxiliary_reported_assets'])})
 save(OUT/'ROLE_PACKET_BINDINGS1000.json',{'records':records,'counts':dict(counts),'public_materials_do_not_contain_model_energy_or_outcome_labels':True,'formal_human_answers':0,'complete_wholehome_actor_packages':0,'collection_release':False,'training_release':False})
 save(OUT/'ADDITIONAL_HVAC_PARAMETER_CANDIDATES1000.json',{'records':candidates,'households_with_parameter_candidates':sum(bool(r['supported_reference_parameter_candidates']) for r in candidates),'parameter_candidate_reports':sum(len(r['supported_reference_parameter_candidates']) for r in candidates),'not_installed_devices_or_empirical_prevalence':True})
 print(dict(counts))
if __name__=='__main__':main()
