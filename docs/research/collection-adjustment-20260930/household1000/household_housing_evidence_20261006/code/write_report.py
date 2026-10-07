"""Materialize a source -> construction -> output -> boundary research record."""
import collections,hashlib,json,platform,sys
from pathlib import Path
OUT=Path(__file__).resolve().parent.parent;BASE=OUT.parent;REPO=OUT.parents[4]
def read(name):return json.loads((OUT/name).read_text())
def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def save(name,d):(OUT/name).write_text(json.dumps(d,ensure_ascii=False,indent=2,allow_nan=False)+'\n')
def main():
    from evidence_guard import ensure_unsealed
    ensure_unsealed(OUT)
    year=read('YEAR_SOURCE_ADMISSION.json');cv=read('YEAR_JOINT_HOLDOUT.json');sleep=read('SLEEP_GEOMETRY_AUDIT1000.json');pilot=read('REGIONAL_PILOT_RESULTS.json');routes=read('MATCHING_SCENARIOS1000.json');native=read('NATIVE_REFERENCE_REGISTRY.json');weather=read('WEATHER_REFERENCE_REGISTRY.json');extra=read('ADDITIONAL_REGIONAL_REFERENCES.json')
    delta=max(r['max_abs_hourly_temperature_difference_C'] for r in pilot['paired_reference_sensitivity']);warnings=collections.Counter(w for r in pilot['cases'] for w in r['warnings'])
    save('WARNING_CLASSIFICATION.json',{'total_warning_entries':sum(warnings.values()),'messages':dict(warnings),
      'gross_centerline_surface_vs_net_Zone_floor_area_air_volume':'112 entries from56 runs: intentionally declared net area/air volume differs from centerline floor/volume; remain physical geometry convention limitation',
      'Lhasa_meridian_time_zone':'4 entries: preserve original EPW longitude91.13/time_zone8; no metadata alteration to silence meridian warning',
      'interzone_reverse_layer_identity_current_warnings':sum(v for k,v in warnings.items() if 'reverse order' in k),
      'symmetric_layer_alias_warning_repair':'same native material identity deduplicated;4 old warnings preserved in development; temperature outputs unchanged',
      'no_empirical_validation_from_warning_classification':True})
    decisions=[
      {'id':'D01','issue':'source_year_field_eligibility_and_current_dwelling_unit','decision':'admit_only_unique_current_property_with_correct_old_new_questionnaire_branch; keep_missing_unasked_future_and_post2020_separate','evidence':['YEAR_SOURCE_ADMISSION.json','code/year_rules.py'],'status':'implemented'},
      {'id':'D02','issue':'full_NG_RB_year_joint_complexity','decision':'no_superiority_admission;retain_negative_comparison;NG_year_marginal_is_candidate_auxiliary_prior_only','evidence':['YEAR_JOINT_HOLDOUT.json'],'status':'negative_result_retained'},
      {'id':'D03','issue':'province_reference_year_and_city_missing','decision':'same_province_candidates_with_original_environment_WMO_and_coordinates;no_automatic_nearest_city_or_year_assignment','evidence':['MATCHING_SCENARIOS1000.json','ADDITIONAL_REGIONAL_REFERENCES.json'],'status':'all1000_have_reference_candidates_not_stock_matches'},
      {'id':'D04','issue':'H7_not_sleeping_capacity','decision':'census_original_design_purpose_and_living_hall_exclusion;separate_private_bed_and_door_clearance_witness;no_witness_is_not_uninhabitability_proof','evidence':['SLEEP_GEOMETRY_AUDIT1000.json','raw/Census2020_Jiangsu_QA3.manifest.json'],'status':'1000_audited;77_baseline_no_witness'},
      {'id':'D05','issue':'one_Beijing_envelope_for_all_China','decision':'prototype_parameter_and_weather_alternatives;wall_widths_recompute_net_geometry_at_fixed_H6;no_national_type_or_stock_frequency_inferred','evidence':['REGIONAL_ASSEMBLY_ADMISSION.json','REGIONAL_PILOT_RESULTS.json'],'status':'14_families28_worlds56_runs;not_national_physical_admission'}]
    save('METHOD_DECISIONS.json',{'decisions':decisions,'no_full_1000_population_or_housing_anchor_regenerated':True})
    fields=[
      ('province_N_G_weights','NBS2020 ordinary-city tables + sealedV6 bounded completion','source aggregate and model completion','V7 fixed1000 household anchor','unidentified ordinary N/G full joint retained'),
      ('members_age_ego_relation','CHFS actual2021 source motif + V6 city controls','matched prior and explicitly transported role age','fixed2524 generated residents','not1000 actual CHFS households;full pairwise parentage not observed'),
      ('H6_H7_area_bin_q','NBS ordinary-city controls + source owned current direct C2003/SHI proxy + V7 metric design','source-controlled and engineered','fixedV7 worlds and H6/H7 quotas','SHI not census H7;q not national sharing frequency;registered external common area unknown'),
      ('effective_year_or_age_interval','CHFS questionnairePDF63/69/74/75/78','source-specific year eligibility;renovation/expected semantics and categorical intervals','YEAR_SOURCE_ADMISSION.json and YEAR_SUPPORT1000.json','no exact year assigned to generated roles;completion vs major renovation not separated'),
      ('year_candidate_prior','1495 admitted owned direct-area source records','training-shrunk auxiliary NG year marginal','MATCHING_SCENARIOS1000.json','full joint lost developmental comparison;transport to other tenure/sharing unknown;not population year weights'),
      ('native_opaque_assemblies','187 original DeST Access + two newly obtained Lasa originals','numeric layers matched to actually used source structures','189 source assembly bundles','no national morphology weights or actual household code compliance;native floor names not RC evidence'),
      ('native_reference_location_and_epoch','original ENVIRONMENT and official model catalogue','province candidate restriction;catalogue epoch as code reference','NATIVE_REFERENCE_REGISTRY.json + ADDITIONAL_REGIONAL_REFERENCES.json','source station city not observed generated home;Lasa wall library names retain Beijing template identity'),
      ('reference_weather','113 original-header/hash-verified CSWD EPWs,7 newly downloaded official files','WMO plus latitude/longitude diagnostic under5km','WEATHER_REFERENCE_REGISTRY.json','typical weather not actual2020/2021;5 batch models fail coordinate diagnostic;threshold is design not geographic law'),
      ('sleep_bed_and_access','actual V7 IDF doors + metric net rooms + manufacturer single-bed footprint','one2.05x0.94m reference bed per member;0.6/0.8m clearances','SLEEP_GEOMETRY_AUDIT1000.json','manufacturer geometry not Chinese ownership distribution;clearance not regulatory;finite-search no-witness not proof impossible'),
      ('generation_sleep_assignment','fixed generated roster generation_level','deterministic reference assignment to found private bed rectangles','sleep bed member_id placements','privacy and child care incomplete;generation mixing does not infer spouse/parent links'),
      ('regional_IDF_and_temperature','actual native opaque source + declared V7 geometry/compiler + source EPW + EnergyPlus24.1','paired reference periods at fixedN/G/H6/H7/q;28 worlds56 empty-shell runs','REGIONAL_PILOT_RESULTS.json and pilot/','not native floorplan reconstruction;floor RC/window positions/WWR/neighbors engineered;not household electricity,comfort or calibration'),
      ('appliance_instances_HVAC_schedules','CHFS C8001ab groups2/5/19 + prior source admission','retain group evidence only;no specific instance from group membership','no installed devices or household-service IDFs added','group5 is AC/purifier/ventilation union;group2 is TV/washer/fridge/satellite union;cannot imply specific appliance,count,power or controls'),
      ('benchmark_actor_and_human_labels','separate future admission','explicit false/zero','SCIENTIFIC_REVIEW.json','runtime and implementation checks cannot admit physical stock or human validity')]
    save('FIELD_EVIDENCE_DICTIONARY.json',{'fields':[dict(zip(['field','source','construction','output','evidence_boundary'],r)) for r in fields],'separate_observed_matched_engineered_simulated_and_unknown':True})
    sources=[
      {'id':'NBS2020','authority':'国家统计局','type':'official census population tables and questionnaire instructions','URL':'https://www.stats.gov.cn/sj/pcsj/rkpc/7rp/zk/html/fu06.pdf','actual_local_originals':'in inheritedV6/V7 input locks','supports':'ordinary-city frame and source H6/H7 operators','does_not_support':'complete household joint,registered source dwellings or stock morphology'},
      {'id':'NBS_QA_H7','authority':'江苏省第七次全国人口普查问题解答之三;灌南县官方转发','document_date':'2020-09-27','web_publication_date':'2020-10-30','URL':'https://xxgk.guannan.gov.cn/news/show-30555.html','read_depth':'official originalHTML housing question6;crosschecked national scheme','supports':'H7 original design purpose;living/kitchen sleeping does not add rooms;unpartitioned combined space count1','does_not_support':'any bed clearance or actual generated layout national frequency'},
      {'id':'CHFS2021_questionnaire','authority':'西南财经大学中国家庭金融调查','type':'original licensed-local questionnaire and survey files','path':'/Users/fanmili/Downloads/2021/CHFS问卷-2021/2021年中国家庭金融调查(CHFS)问卷.pdf','sha256':'84c8cf52535a986bcdfe0be42722b5553dd2f9c4817c11d81a480a0e6fe463ac','PDF_pages1based':[63,69,74,75,78,107],'supports':'current property selection/branch eligibility/year and age/group ownership semantics','does_not_support':'actual source household2020 provenance or source code compliance'},
      {'id':'An2023','authors':['Jingjing An','Yi Wu','Chenxi Gui','Da Yan'],'title':'Chinese prototype building models for simulating the energy performance of the nationwide building stock','journal':'Building Simulation','year':2023,'volume':16,'pages':'1559–1582','DOI':'10.1007/s12273-023-1058-5','URL':'https://link.springer.com/article/10.1007/s12273-023-1058-5','read_depth':'publisher metadata/abstract and original downloaded Access tables;fullSciOpenPDF retrieval404 notclaimedread','supports':'climate/type/standard-period prototype reference method;151 reference models expanded to9225 models270cities','does_not_support':'187 or189 local model frequency equals population stock or current household shape'},
      {'id':'DeST_originals','authority':'author DeST typical building library','URL':'https://www.dest.net.cn/dxjzk','retrieval_endpoint':'https://svr.dest.net.cn/api/v1/load_model_file','actual_input_files':'187 prior batch originals plusLow_Lasa_1995/2018 originalAccess retrieved2026-10-06','supports':'actual assigned opaque material layer vectors and project environment','does_not_support':'native door reconstruction or national prototype weights'},
      {'id':'CSWD_EnergyPlus','authority':'EnergyPlus original CSWD distribution;Tsinghua/China Meteorological Bureau weather dataset attribution','URL':'https://energyplus.net/assets/nrel_custom/pdfs/pdfs_v9.6.0/AuxiliaryPrograms.pdf','actual_versioned_manual_path':'/Applications/EnergyPlus-24-1-0/Documentation/AuxiliaryPrograms.pdf','actual_manual_sha256':sha('/Applications/EnergyPlus-24-1-0/Documentation/AuxiliaryPrograms.pdf'),'actualPDF_page1based':84,'supports':'270 reference typical-hourly CSWD files;original EPW headers and weather source identity','does_not_support':'observed2020 weather or household city weights'},
      {'id':'bed_outer_dimensions','authority':'original manufacturer IKEA NEIDEN article403.952.45','URL':'https://www.ikea.com/nl/en/p/neiden-bed-frame-pine-40395245/','read_depth':'original product dimension section initiallyread;later webretrytimedout','outer_dimensions_m':[2.05,.94],'mattress_dimensions_not_outer_footprint_m':[2,.9],'supports':'one explicit reference footprint','does_not_support':'Chinese bedroom stock/bed ownership frequency or regulatory clearances'},
      {'id':'GB_T3328_metadata','authority':'国家标准元数据','URL':'https://std.samr.gov.cn/gb/search/gbDetailed?id=eG7XIMvw230%3D&mode=p','read_depth':'metadata only;numeric fullstandardnotobtained','numeric_dimensions_or_clearance_support_used':False},
      {'id':'procedural_skill_only','authors':['Timothy Kassis','Vinayak Agarwal','Yuhuan He','Darshil Patel','Aubrey M. Brueckner'],'year':2026,'title':'Scientific Agent Skills: A Library of Procedural Knowledge for Research Agents','URL':'https://arxiv.org/abs/2609.00065v2','role':'procedural scientific-critical-thinking tool reference only;no Chinese housing/material/population support'}]
    save('SOURCE_REGISTER.json',{'review_type':'targeted_primary_technical_review_not_exhaustive_systematic_literature_review','sources':sources})
    save('SEARCH_LOG.json',{'date_HKT':'2026-10-06','presearch_protocol':'PROTOCOL.json','searches':[
      {'query':'DeST151 prototype China residential;official EnergyPlus Nanjing CSWD','included':'original An2023 publisher and actual native/EPW files','excluded_as_authority':'LinkedIn/gists/ResearchGate summaries'},
      {'query':'CHFS2021 C1000ak C2012a C2006 C2008ab','method':'original local questionnaire and actual licensed source fields','included':'PDF63/69/74/75/78;old/new branch distinction'},
      {'query':'IKEA NEIDEN40395245 original outerdimensions;GB/T3328-2016 officialmetadata','included':'manufacturer outergeometry scenario','excluded_claim':'numerical regulatory bedroom clearances;fullstandard unavailable'},
      {'query':'第七次全国人口普查H7住房间数客厅厨房原设计用途','included':'NBSscheme and Jiangsu official question6','failed_download':'Guangdong/YunfuPDF failed;notclaimed fullPDF read'},
      {'query':'Lasa vs Lhasa in official DeST catalogue;missing WMO CSWD files','included':'original ENVIRONMENT Xizang55591;officialAccess retrieval1995/2018;7 header-verified official EPWdownloads','retained_failed_URLs':'WEATHER_GAP_ACQUISITION.json'}],
      'full_An2023_paper_not_obtained_this_phase':True,'no_secondary_source_estimates_promoted_to_population_or_physical_truth':True})
    gaps=[
      {'priority':'critical','topic':'national physical stock representativeness','evidence':'sameprovince candidate coverage1000,year joint unidentifiable,morphology/q frequencies unknown','required_resolution':'empirical building-type/era/neighbor evidence or explicitmulti-reference robustness benchmark;no year-to-code shortcut','gate':'not_admitted'},
      {'priority':'critical','topic':'complete household services and specific devices','evidence':'all shell models lack People/installed appliances/HVAC;CHFS groups cannot identify specificdevice','required_resolution':'separately qualified individual appliance count/rating/installation/operator/schedule/control/world assumptions and electrical end-use accounting','gate':'not_admitted'},
      {'priority':'major','topic':'sleep/function/care world completeness','evidence':'923/864 bed witnesses;77/136 no-witness;271 baseline successful designs mix generations','required_resolution':'constrain next household-housing generation by reference functional capacity with fixed census controls;explicitalternative sleep design,privacy and care scenarios;retainfailedassignments','gate':'reference_geometry_only'},
      {'priority':'major','topic':'native floorplan and glazing/neighbor fidelity','evidence':'new corridor designs;regional opaque provenance189;window approximation unvalidated;Lasa windows heldBeijingreference;adiabaticneighbors and fixedRCfloor','required_resolution':'source door/layout and detailed glazing mapping plus boundary-condition validation;no source-name identityshortcut','gate':'partial'},
      {'priority':'major','topic':'source selection and temporal/geographic transport','evidence':'1495owned joint subset;1073nonowned intervals;740roles ownerexclusive proxy;396 exactprovinceNG_RBsupport','required_resolution':'explicit missingness/selection/transport sensitivity and independent data check;priors remain candidates','gate':'partial'}]
    save('SCIENTIFIC_REVIEW.json',{'decision':'major_revision;foundational_source_and_engineering_evidence_strengthened;not_scientific_benchmark_admission',
      'basis':'primarysource_semantics+negative_development_comparison+189original_material_provenance+1000sleep_audit+28regional_referenceworlds',
      'method_decisions':decisions,'remaining_findings':gaps,'national_joint_observed':False,'national_physical_stock_representativeness_established':False,
      'complete_household_IDFs':0,'actor_ready_packages':0,'formal_human_answers':0,'scientific_benchmark_admitted':False,'collection_release':False,'training_release':False})
    current={'date_HKT':'2026-10-06','phase':'household_housing_evidence','population_anchor':'../idf_joint_production_20261005/HOUSEHOLDS1000_JOINT_GEOMETRY_CANDIDATE.json','fixed_households':1000,'fixed_residents':2524,
      'owned_joint_effective_year_source_records':1495,'nonowned_age_interval_source_records':1073,'year_joint_NLL':cv['joint_conditional_year_NLL_nats'],'year_simpler_NLL':cv['factorized_year_NLL_nats'],
      'original_native_sources_opaque_properties_bound':189,'weather_files_header_hash_verified':len(weather['stations']),'new_official_weather_files':7,
      'all1000_sameprovince_opaque_weather_reference_candidates':routes['slots_with_same_province_opaque_reference_and_station_match'],
      'sleep0_6m_constructive_witness':sleep['baseline0_6m_witness_found'],'sleep0_8m_constructive_witness':sleep['alternative0_8m_witness_found'],
      'pilot_family_profiles':pilot['family_profiles'],'pilot_parameter_reference_worlds':pilot['source_parameter_reference_worlds'],'winter_summer_empty_shell_runs':pilot['winter_summer_empty_shell_runs'],
      'runtime_severe_fatal':pilot['severe_or_fatal'],'runtime_warning_entries':pilot['warning_entries'],'max_paired_hourly_temperature_difference_C':delta,
      'complete_household_IDFs':0,'complete_actor_packages':0,'formal_human_answers':0,'scientific_benchmark_admitted':False,'active_V5_not_replaced':True,'sealed_V7_not_modified':True}
    save('CURRENT.json',current)
    report=f'''# 家庭—住房—IDF基础证据推进记录（2026-10-06）

本轮完成来源口径修正、1000户的逐户匹配路径、真实房间门位置下的睡位检查和地区参数试验。**基础证据得到实质补强；全国代表性物理benchmark尚未获准入。** 当前对象仍为2020年中国城市普通住宅家庭户，排除镇、乡村、集体户及非普通住所。沿用封存V7的1000户、2524人，不以删除难匹配家庭来提高通过率；现行V5和八个历史封存包均未改动。

## 1. 科研对象与证据层次

人口、住房的已公开普查边际是观察事实；N/G未知联合的补全、CHFS家庭关联移植及年份迁移是模型；q、平面、床位、楼板、邻居边界是参考设计；EnergyPlus温度是这些输入下的仿真输出。四者不互相替代。1000户可以用于研究**固定人口住房控制下的参考家庭情景**，尚不能用于宣称实际全国住宅类型或家庭用电的总体估计。

完整字段链见 `FIELD_EVIDENCE_DICTIONARY.json`。每一行给出来源、构造、输出和证据边界；具体年份、城市、建筑类型未知时保留null。

## 2. 当前住房年份/房龄：先纠正来源，再选择方法

CHFS实际2021访次采用唯一选中的当前住房。产权循环中的其他房产不能替代当前住房。原有住房与新增住房题目分开解析；新增房产C2006=7且C2008ab不属于2/6时跳过年份题，旧住房年份题不盲套这一跳转。有效年份问卷范围1900—2029；将问卷未询问、缺答、跳转冲突、预计未来年份、2021晚于2020参考年分别记录。

问卷新增住房年份包含完工以及翻修/改建面积超过50%后的年份，期房可以报告预计年份。这个口径无法识别原始建造年代与能效规范实际执行。租借住房C1000ak是五个区间：[0,3]、[3,5]、[5,10]、[10,20]、[20,∞)；端点精度不足，既不取区间中点，也不把编码5当5年。2021向2020的转移仍属模型。[源问卷见来源表；PDF页63/69/74/75/78]

保留原1779条自有当前整套、直接建筑面积和间数代理联合源样本的过滤规则。其中**1495条**年份可作为2020参照辅助信息；261条有资格但缺答、17条跳转与填值冲突、3条2021年份、3条资格未决。1495条Kish有效样本量约{year['owned_joint_year_Kish_ESS']:.1f}。另有**1073条**非自有住房房龄区间。它们不识别全国自有/租借比例或全国房龄分布，缺失也不能当随机缺失。

111/112是来源抽样地址的城市分类，不能仅凭该代码证明当前住房等同七普普通住宅H5=1或当前地址仍在该抽样城市。源当前住房循环选择已经落实，这一总体范围对齐仍属于运输假设；不能把房产产权类别或建筑名称当H5的替代观测。

开发阶段固定5折、整户划分、训练折内权重归一；固定全局每格0.1伪计数和局部10户等价收缩。比较同一联合表的P(Y|N,G,R,B)与其P(Y|N,G)年份边际，权重计分。

| 方法 | 留出年份NLL（nats，越低越好） |
| --- | ---: |
| 人数/代数/间数/面积/年份全联合条件模型 | {cv['joint_conditional_year_NLL_nats']:.6f} |
| 同一模型的简约年份边际 | {cv['factorized_year_NLL_nats']:.6f} |
| 全联合减简约 | +{cv['delta_joint_minus_factorized']:.6f} |

全联合模型在这次预先固定比较中较差，**不获得优越方法的准入**。简约年份边际只作为辅助候选先验；本结果不证明房龄和面积独立，也不证明所有联合方法都失败。未取得PSU设计误差，未作显著性结论；这是开发留出，不是最终盲测、外部调查或全国运输验证。

1000名额中，同省且相同N/G/R/B有年份来源支持的396户，全国相同组合有958户。740户在来源先验中为自有且设计q=1，其余260户必须显式保留产权/合住运输问题。每户的真实来源年份仍为未知，未生成1000个伪观察年份。

## 3. 地区与标准年代：原始文件核查和新增来源

An等（2023）的[原始论文](https://link.springer.com/article/10.1007/s12273-023-1058-5)支持按气候、建筑类型、标准年代设计参考原型，不能给出本库原型的全国住房占比。本轮读到出版方摘要/元数据与实际Access文件；未取得全文，不能声称全文审阅。

187个原始DeST模型逐一核对源文件哈希、实际ENVIRONMENT和已转换IDF，涵盖100个目录城市、74个板式高层/113个低层以及1986/1995/2001/2003/2010/2012/2018/2019参考年代。**561项不透明构造**的厚度、导热率、密度、比热逐层匹配原始材料表，且核实匹配构造实际用于源MAIN_ENCLOSURE，而非只在材料库存在。目录Kunming与ENVIRONMENT昆明的差异经明确双语对应解决；其他实际城市身份未任意替换。

从DeST原站进一步下载**Low_Lasa_1995、Low_Lasa_2018**两个原始Access。原项目省份为Xizang、站号55591、坐标29.66667/91.13333。旧R转换运行环境不可用，本轮直接从原始实际围护结构ID和四项材料属性提取参考层，**没有声称转换了整栋原生IDF**。源外墙名称仍为JGJ26-1995/2018-Beijing，保留这一作者模板沿用事实，不能把站点移植等同拉萨本地规范执行。拉萨玻璃保留V7北京简化玻璃为明示参照，表面吸收率/粗糙度为工程设计。

另从[EnergyPlus原始CSWD分发](https://energyplus-weather.s3.amazonaws.com/asia_wmo_region_2/CHN/CHN_Tibet.Lhasa.555910_CSWD/CHN_Tibet.Lhasa.555910_CSWD.zip)新增7份天气文件，合计**{len(weather['stations'])}份**逐文件哈希及LOCATION头核验。EnergyPlus24.1原手册PDF84页说明CSWD为典型逐时参照天气，不是2020/2021实测天气。站号5位到6位末尾0的对应同时用坐标复核。5km是明确的工程核查阈值，不是官方行政范围。

187个批量模型中182个通过站号加坐标检查；南京3个模型的纬度32.00与EPW32.83差异、焉耆经度差异、玉山经度差异仍保留，**5个模型不自动绑定**。新增拉萨两个通过原站号/坐标核验。189个不透明参数来源建立逐文件证据链；模型数绝不当全国类型/年代权重。

`MATCHING_SCENARIOS1000.json`为**1000/1000户**提供同省不透明参数及天气候选，包括西藏；候选城市、建筑类型、标准年代仍不是该户的真实观察。没有默认省会、最近城市或最近标准年代。1980年前住房无对应年代原型的缺口不以新规范替填。

## 4. H7、睡位和实际门位置分开核验

[官方普查解释](https://xxgk.guannan.gov.cn/news/show-30555.html)规定间数按原设计用途与自然间计算，客厅、厨房住人不因此加入H7；无分隔的卧室/客厅/厨房合并空间按1间。参考语法的H7房间被声明为卧室，厅、厨房、走廊、厕所独立排除；这是一种设计，不是所有真实H7房间均为卧室的事实。

逐户从封存V7的实际IDF读出门的坐标，在计算出的室内净矩形中布置每名成员一张参考单人床。外框2.05×0.94m来自[IKEA原制造商尺寸](https://www.ikea.com/nl/en/p/neiden-bed-frame-pine-40395245/)，没有使用较小床垫尺寸2.00×0.90m冒充外框。0.6m和0.8m是声明的工程通行情景，不是法规、适老或无障碍合规要求。

布置搜索检查床外框、无重叠、门内可用入口和到每张床长边的连通净空。0.6m有**{sleep['baseline0_6m_witness_found']}户**找到完整布置，0.8m有**{sleep['alternative0_8m_witness_found']}户**；对应77/136户未找到本规则下的布置。失败集中于3人及以上家庭，包含N=12个案。搜索只覆盖规则单人床阵列，不穷尽双人床、上下铺、其他方向或形态，失败不能证明现实住房不可住；更不能通过删户或把客厅临时住人重新计H7来修饰通过率。

0.6m成功布置中271户在所选设计里有跨代同室，0.8m为239户。它们只说明参考位置，并未完成夫妻/亲子隐私、儿童照护、厨房活动或设备操作。独立校验器使用输出的世界坐标重新检查，校验4629个已布置床外框；移动床到室外、重复成员且重叠床、尺寸合法但挡住实际门的床三个负对照均被拒绝。检查结果不是人类居住合理性的证明。

## 5. 地区参数—几何—IDF小批试验

按原协议的省区、G=1/2/3、q>1和原睡位失败选覆盖样本；最初北京、上海、广东13户。发现西藏原始资源缺口后，作明示覆盖扩展，在西藏新病例仿真前按同样条件加入固定人口中的1户，共**{pilot['family_profiles']}个家庭**，不根据地区温度结果择优选户。每户保留N/G/H6/H7/q，比较两个同地区来源的标准年代，产生**{pilot['source_parameter_reference_worlds']}个住房参照世界**与**{pilot['winter_summer_empty_shell_runs']}次**冬/夏24小时空壳运行。参数变化时重算墙厚、室内净面积和睡位；没有等比例缩放墙厚，也没有保持旧净面积而悄悄换墙。

全部运行0 Severe/Fatal。当前**{pilot['warning_entries']}条警告**：112条来自声明的净Zone面积/空气体积与中心线表面几何差别；4条来自拉萨原EPW经度与时区的标准子午线检查，保持原数据；新直接提取中同一对称材料的不同对象名引发的4条反序警告已用原材料身份去重修复，修复前文件保留且前后温度变化为0。警告不是被忽略的校准证据。

28个参考世界中18个在两个睡位通道情景均找到布置；覆盖样本故意包含失败，其通过率不估计全国比例。配对逐时私人房间净面积加权温度差最大**{delta:.4f}℃**，说明地区/标准参数假设具有实质影响。固定建筑面积时墙厚同时改变可用几何，因此这是**参考参数与几何联合情景敏感性**，不能解释为隔离后的材料因果效应、节电量或真实全国住宅的节能收益。

IDF仍无People、家电、渗透、安装HVAC与完整家庭服务。楼板采用明确RC参照，玻璃近似尚未经原生详细玻璃验证，门窗位置/WWR/层高/邻居边界为设计；原生真实户型未重建。56次运行只是这些来源与声明假设下的空壳响应证据。

## 6. 审稿判断与下一条生产门槛

本轮已经补强当前住房年份语义、复杂模型负结果、31省候选资源、实际源构造与气象、人员到睡位和地区IDF响应这条链。独立验证同时复核历史8包9726个文件，内容未改动。**完整家庭服务IDF=0、actor-ready=0、真人回答=0、全国物理benchmark准入=false。**

下一轮必须把可入住几何作为家庭—住房联合生成的约束：保留普查控制，不逐户随意改面积或删掉困难家庭；同时为未知形态、共享权利、年代和邻居边界输出替代世界。再用经过资格/时间/粒度核准的单项设备证据建立安装数量、额定参数、热区、使用者、服务需求、时序和端用途电量。CHFS2/5/19是耐用品组，组5的阳性可能来自空气净化器或新风，不能直接生成空调；其他组同理。

全国建筑类型/年代/共享比例仍缺能验证的总体联合证据。若后续取得相容实证则校准；若未取得，benchmark必须明确为普查边际约束的**多参照合成家庭情景**，对替代假设报告稳定性，不能发布单一“全国真实住房匹配”或总体节电结论。这是科学对象和可识别性边界，补引用本身无法消除。

全部代码、源注册、输入锁、负对照、失败与警告解释见同目录JSON及 `REPRODUCE.md`。研究审查使用literature-review/scientific-critical-thinking过程；工具流程引用[Kassis等，Scientific Agent Skills，2026](https://arxiv.org/abs/2609.00065v2)仅说明审查程序，不是中国住房的证据来源。
'''
    (OUT/'METHODS_AND_RESULTS.md').write_text(report)
    (OUT/'README.md').write_text(f'''# 家庭—住房基础证据（2026-10-06）

本轮推进完成；全国代表性物理benchmark仍需修订。范围保持2020年城市普通住宅家庭户，排除镇、乡村。V5现行与V7封存均未替换。

- 房龄：核准1495条自有住房联合源记录、1073条租借区间；复杂年份联合模型留出NLL1.209882，简约边际1.168613，保留负结果，不生成假观察年份。
- 地区：189个原始DeST不透明参数来源、113份CSWD；新增拉萨两个原始模型及7份官方天气。1000户均有同省候选，候选不等于真实住房匹配或全国比例。
- 睡位：实际IDF门坐标下，0.6/0.8m设计通道分别找到923/864户单人床布置；77/136户无有限搜索见证，未删户。
- IDF：14家庭、28参数参考世界、56次冬夏空壳运行，0严重/致命错误，116条已说明的警告。未知设备、HVAC、真实户型和统计总体权重未伪造。

[完整方法与结果](METHODS_AND_RESULTS.md) · [逐户匹配路径](MATCHING_SCENARIOS1000.json) · [证据字典](FIELD_EVIDENCE_DICTIONARY.json) · [独立核验](VERIFICATION.json) · [审稿缺口](SCIENTIFIC_REVIEW.json)

完整家庭IDF、actor-ready、真人回答仍为0；科学benchmark、收集及训练准入为false。下一道门槛是有普查控制的功能容量生成与单项设备/服务/操作链。
''')
    (OUT/'REPRODUCE.md').write_text('''# 复现与不可变性

使用固定本地Python、原始授权CHFS文件、既有Access解析/几何依赖和EnergyPlus24.1。不能从README表格还原原始调查。输入锁包含当前实际源文件；不安装依赖、不写历史封存包。

完整运行入口为 `code/run_pipeline.py`。可在未封存的目录中运行；已存在PACKAGE_MANIFEST.json时入口拒绝写入。另行复制研究包到新目录复现，先核对输入锁。源CHFS派生缓存留在private_research，不作为角色微数据公开。

依次执行 build_year_bridge → fetch_weather_gap → fetch_native_gap → inventory_references → regional_assemblies → admit_native_gap → sleep_geometry → matching_scenarios → regional_pilot → verify_evidence → write_report。网络失败保留；原始资源缺失不猜测填补。采集、训练、部署、现行候选替换不属于这个入口。

睡位搜索需数十秒至数分钟。地区pilot按IDF、EPW、engine、SQL四重哈希复用已经完成的相同运行，仅新增或改变输入时重跑。任何解析或源准入失败必须停止依赖步骤。路径假定本地workspace结构；Python虚拟环境重定位及旧Rdestep运行环境不保证可用，两个拉萨模型不依赖该R转换。

独立检查只证明本次语义/实现/记录一致性。原型统计权重、玻璃物理近似、真实服务电量与人类扮演回答不在这一验证的证明范围。
''')
    print(json.dumps(current,ensure_ascii=False,indent=2))
if __name__=='__main__':main()
