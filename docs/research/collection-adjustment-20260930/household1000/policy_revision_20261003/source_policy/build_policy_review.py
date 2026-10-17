"""Build review contracts from documentation/metadata only; never read .dta."""
from pathlib import Path
import hashlib
import json
import re
from collections import Counter

HERE=Path(__file__).resolve().parent
H=HERE.parent.parent
V2=H/'household_to_idf_v2_20261003'
GEN=H/'generation_model_20261003'
META=H/'chfs_admission_20261003/private_metadata'

def sha(p): return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def write(name,obj): (HERE/name).write_text(json.dumps(obj,ensure_ascii=False,indent=2,allow_nan=False)+'\n')
def loc(path,line,end=None):
    return {'path':str(path),'line':line,**({'end_line':end} if end else {})}

source_files=[
    Path('/Users/fanmili/Downloads/2021/CHFS问卷-2021/2021年中国家庭金融调查(CHFS)问卷.pdf'),
    Path('/Users/fanmili/Downloads/2021/CHFS问卷-2021/2022年中国家庭金融调查(CHFS)问卷.pdf'),
    Path('/Users/fanmili/Downloads/2021/CHFS数据使用说明-2021.pdf'),
    H/'evidence_contract_20261001/raw/census2020_plan_retry.pdf',
    H/'evidence_contract_20261001/POPULATION_ALLOCATION_CANDIDATE_V2.json',
    GEN/'MODEL_CARD.md',GEN/'final_v2/code/generate_candidates.py',
    GEN/'final_v2/FAMILY_HOUSING_CANDIDATES.json',
    V2/'build_profile_contexts.py',V2/'PROTOTYPE_POLICY.md',V2/'PROTOTYPE_REGISTRY.json',
    V2/'idf_builder.py',V2/'TASK_CARD.json',V2/'context_input_plan_v2/CONTEXT_PLAN.json',
    V2/'population_contexts_v1/SUMMARY.json',HERE/'policy_checks.py']
terms=['楼层','层数','平房','楼房','别墅','公寓','复式','跃层','朝向','建筑结构','房屋结构','住宅形式','住房形式','住宅类型','住房类型','房屋类型']
metareview=[]
for file in sorted(META.glob('*_metadata.json')):
    if '_hh_' not in file.name and '_ind_' not in file.name:continue
    o=json.loads(file.read_text());labs=o.get('variable_labels',{})
    metareview.append({'path':str(file),'sha256':sha(file),'variable_labels_count':len(labs),
                      'keyword_hits':{t:[{'field':k,'label':v} for k,v in labs.items() if t in v] for t in terms},
                      'review_scope':'labels only; no microdata values'})
    source_files.append(file)

fields=[
 {'question':'A2001','actual_field':'ind.a2001;value_labels.indnew_a2001','pdf_pages':{'2021':[12,13],'2022':[12,13,14]},'scope':'relationship to respondent;10siblings,7777other;2spouseorpartner','supports':['siblings_relative_same_generation','respondent_relative_generation_proxy'],'does_not_support':['7777other_is_same_generation','complete_pairwise_family_graph_from_generation_count']},
 {'question':'A1002','actual_field':'hh.a1002','pdf_pages':{'2021':[8],'2022':[8]},'scope':'new sampled household residential-address filter; includes mixed business/residence','supports':['residential_filter'],'does_not_support':['apartment_or_detached_form','household_internal_storeys','census_H5_exact_identity']},
 {'question':'A2017b','actual_field':'ind.a2017b','pdf_pages':{'2021':[18],'2022':[18]},'scope':'only non-co-resident economic members A2000c=3/4; ownership/rent/free','supports':['nonresident_tenure'],'does_not_support':['current_coresident_dwelling_shape','household_internal_storeys']},
 {'question':'C1001','actual_field':'hh.c1001','pdf_pages':{'2021':[63],'2022':[63]},'scope':'current tenure in2021 version; 2021-07-end tenure in2022 version;1owned2rented3free','supports':['current_tenure_branch'],'does_not_support':['housing_geometry','building_storeys']},
 {'question':'C1000ak','actual_field':'hh.c1000ak','pdf_pages':{'2021':[63],'2022':[63]},'scope':'nonowned current dwelling path; five age ranges','supports':['building_age_bin_if_branch_known'],'does_not_support':['exact_construction_year','housing_geometry']},
 {'question':'C2008b','actual_field':'hh.c2008b_1..6','pdf_pages':{'2021':[67,75],'2022':[68,75]},'scope':'owned household only c1001=1; exactly one current dwelling marker1; 2022 version reference2021-07-end','supports':['same_j_current_owned_binding'],'does_not_support':['unmarked_first_property_is_current','exact_current_location','floorplan']},
 {'question':'C2000x','actual_field':'hh.c2000x_1..6','pdf_pages':{'2021':[66],'2022':[66]},'scope':'tracked old dwelling identity/status;4transferred/disposed; j shared across old/new loops','supports':['identity_and_disposal_check'],'does_not_support':['owned_property_is_current']},
 {'question':'C2005aa','actual_field':['hh.c2005aa1_1..6','hh.c2005aa2_1..6'],'pdf_pages':{'2021':[74],'2022':[74]},'scope':'new detailed owned dwelling; room count and hall count except kitchen/bath; not reasked for old/current nonowned path','supports':['rooms_halls_of_same_j','H7_proxy_only_with_scope_bridge'],'does_not_support':['floorplan_connectivity','bedroom_identity','household_internal_storeys']},
 {'question':'C2006','actual_field':'hh.c2006_1..6','pdf_pages':{'2021':[74],'2022':[74]},'scope':'acquisition method incl7self-build/extension','supports':['acquisition_method'],'does_not_support':['detached_house','apartment','internal_storeys']},
 {'question':'C2008ab','actual_field':'hh.c2008ab_1..6','pdf_pages':{'2021':[75],'2022':[75]},'scope':'property/land-right form; descriptive apartment example is not a measured morphology category','supports':['property_rights'],'does_not_support':['apartment_morphology_frequency','dwelling_internal_levels']},
 {'question':'C2012','actual_field':'hh.c2012_1..6','pdf_pages':{'2021':[78],'2022':[78]},'scope':'acquisition year of the property','supports':['acquisition_year'],'does_not_support':['construction_year']},
 {'question':'C2012a','actual_field':'hh.c2012a_1..6','pdf_pages':{'2021':[69,78],'2022':[70,78]},'scope':'construction/completion year of same property; new branch allows expected delivery date of unfinished property and definition includes >50% renovation/extension','supports':['construction_year_candidate_only_same_current_j_and_valid_reference'],'does_not_support':['current_house_without_same_j_binding','observed2020_household_date','renovation_definition_identical_to_census_H10']},
 {'question':'C2004','actual_field':'hh.c2004_1..6','pdf_pages':{'2021':[72],'2022':[74]},'scope':'recorded usable area; unknown can be system0.7xbuilding area','supports':['usable_area_record_with_mixed_origin'],'does_not_support':['independent_measured_net_thermal_area','universal_inverse1.33_geometry_ratio']}
]
for f in fields:
    f['pdf_page_numbering']='one-based PDF file page; not printed page footer'
    f['docs_verified']=True;f['values_reviewed']=False
write('CHFS_HOUSING_FIELD_REVIEW.json',{'schema':'eb.source_policy.chfs_fields.v1','date':'2026-10-03',
 'questionnaires_read':[{'year':y,'pages':n,'sha256':sha(source_files[i]),'path':str(source_files[i])} for i,(y,n) in enumerate([(2021,174),(2022,173)])],
 'negative_search_scope':'both complete questionnaires plus variable labels in four metadata subsets; semantic housing-module review, not proof about other CHFS waves or restricted files',
 'direct_household_internal_storeys_field_found':False,'direct_current_dwelling_morphology_field_found':False,
 'fields':fields,'public_metadata_diagnostics':metareview,
 'important_unknowns':['exact building floor position','household split levels/lofts','measured shape and topology','orientation','airtightness or infiltration','net thermal floor area','current actual city not available in reviewed hh schema'],
 'redistribution':'questionnaire PDFs stay in authorized local download; this review does not republish them'})

policy={
 'schema':'eb.source_housing_policy.v1','date':'2026-10-03','status':'implemented_review_contract;generator_and_runtime_integration_owned_elsewhere',
 'freeze':{'must_not_modify':[str(GEN/'final_v2'),str(V2)],'allocation_path':str(source_files[4]),'allocation_sha256':sha(source_files[4])},
 'target':{'categories':[111,112],'exclude_town_rural_collective':True,'age_rule':'exclude only known resident_count=1 age<20; unknown boundary stays unknown; no all-members20+ requirement',
           'age_cutoff_basis':'inherited explicit research target, not census household definition, legal adulthood or universal human-recruitment rule',
           'target_change_requires_new_named_version_and_recomputed_quotas':True},
 'field_priority':['documented_direct_same_current_dwelling_observation','documented_current_dwelling_scope_bridge','unknown'],
 'population_fields':{
  'building_total_storeys_bin':{'source':'census2020H8 / B0901a aggregate margins','status':'modeled_allocation_not_household_observation','categories':{'1':'平房 natural total1','2':'多层7及以下','3':'高层8–33','4':'超高层34+'},'preserve_macro_margins':True},
  'building_total_storeys_design':{'source':'within-H8-bin engineering draw','exact_top_bin_max50':'engineering prior, not population upper bound','must_not_identify_household_shape':True},
  'building_year_design':{'source':'censusH10/vintage margins plus within-bin draw','status':'modeled_year;not_CHFS_observed2020_building','construction_not_acquisition':True},
  'dwelling_type':{'no_direct_evidence_value':None,'status':'unknown','prohibited_derivation':['H8bin','building_total_storeys','tenure','self_build','property_rights','source_catalog_label','weather_city']},
  'household_storeys':{'no_direct_evidence_value':None,'status':'unknown','prohibited_derivation':['H8bin','building_total_storeys','5pct_random_maisonette','template_supported_geometry']},
  'H5_nonordinary_subtype':{'no_direct_evidence_value':None,'status':'unknown','must_not_default_to_shared_or_apartment_for_population_claim':True}},
 'separation':{'population_fact_bundle_immutable':True,'engineering_geometry_condition_is_separate':True,'unknown_fact_does_not_become_apartment_observation':True,
               'no_population_resampling_by_weather_template_capacity_or_energy_outcome':True,'conditional_branch_weights_are_design_weights':True},
 'engineering_admission':{
  'mode':'explicit_conditional_design','required_bindings':['profile_file_sha256','family_slot_id','family_before_sha256=family_after_sha256','housing_before_sha256=housing_after_sha256','source_group_id','source_idf_sha256','parent_idf_sha256','weather_sha256','prototype_target_sha256','exposure_sha256','experiment_lock_sha256'],
  'required_flags':{'population_type_identified':False,'empirical_transport_verified':False,'population_frequency_claim':False},
  'exact_lists':['accepted_unknown_population_fields','approved_actual_mismatch_axes'],
  'nonordinary_or_shared':'keep in1000 denominator; separate future supported branch, no bypass of H5/H6/H7 sharing gate',
  'single_level_condition_with_H8flat':'a one-level thermal geometry with roof/ground exposure may be DECLARED; does not identify detached stock or exclude uncounted lofts',
  'multi_level_condition':'only independent writer-supported geometry and explicit plan; do not assign5% as population rate'},
 'prototype_policy':{
  'catalog_low_high_form':'engineering bank labels only; no national morphology classifier',
  'six_storey_threshold':'retire as population-shape inference; censusH8multistorey ends7 but neither6nor7 proves apartment topology',
  'conditional_source_selection':'retain deterministic ranking/ties only in declared bank-selection track, freeze source choices before outcomes; compare alternative source_groups',
  'empirical_local_stock_match':'requires verified target/source actual city, construction/renovation time definition and shape evidence; currently unavailable for catalogue labels alone',
  'cross_city_cross_year_transport':'allowed only for explicitly named source×target×climate pairs frozen beforehand; no universal kilometre/year validity threshold is identified',
  'source_group_independence':'300keys collapse193source/parent fingerprints; groups are source-file units, not certified193independent observed buildings'},
 'experiment_design':{
  'primary_conditions_existing_frozen_v2':{'north_axis_deg':0,'infiltration_ach':0.5,'gross_to_zone_floor_ratio':1/1.33,'side_walls':'west/eastAdiabatic;north/southOutdoors','floor_position':'top when modeled total2;middle at floor2 when total>=3'},
  'new_revision_main_ground_condition_c':18,
  'primary_conditions_scope':'specified engineering main condition only; no measured China housing parameter distribution',
  'sensitivity_grid_status':'recommended explicitly designed tests, not completed runs or official/Chinese normative thresholds; owner must freeze selected plan BEFORE new execution',
  'selected_one_factor_grids':{'north_axis_deg':[0,90,180,270],'infiltration_ach':[0.3,0.5,0.8],'gross_to_zone_floor_ratio':[0.65,1/1.33,0.85],'ground_temperature_c':[10,18,25]},
  'grid_coordination':'synchronized with root ENGINEERING_SENSITIVITY_PLAN on2026-10-03;this review sets no second default',
  'ground_stress':'main18C;10/25C explicit shell stress. Retain actual engine warning for10C, which is outside engine-advised15–25C range;not a realistic measured ground temperature or hard physical admissibility standard',
  'other_factors':['source assembly_group_id alternatives fixed per target','compatible middle/top/ground exposure with explicitly modeled total/floor number','two/three/four outdoor wall exposure when geometry writer supports','alternate verified weather periods as context rather than actual residence'],
  'grid_values_basis':'controlled bracket around existing main setup; no population quantile interpretation; adjust via new prespecified version if external calibration becomes available',
  'run_schedule':'main condition plus each selected one-factor alternative on SAME households; prespecify any source×climate interaction submatrix and selection before viewing outputs; do not call OFAT a full uncertainty distribution',
  'denominator':'all1000population slots retained; all submitted conditional variants and refusals recorded separately',
  'metrics':['compile coverage by originalprovince/H5/sharing/H8/size/generation and exact refusal code','paired changes in annual mean/free-running temperature, temperature extrema and prespecified exceedance hours only if annual support witnessed','infiltration ACH readback and floor-area/source/boundary invariants'],
  'inapplicable_outcomes_without_later_data':['occupied thermal comfort calibration','household electricity','actual appliance energy','real household preference/adoption accuracy'],
  'dependence':'household variants/hours are repeated, source keys share parents, name-independent numeric physical closures can match across source_groups, one station perprovince confounds climate/province; specify distinct role/source/climate holdout tracks, not blind graph union',
  'reproducibility':'lock profile+policy+source/weather registry+source/parent/weather bytes+all executor code hashes and pair list before first run; local timestamps alone are not independent proof of preregistration'}
}
write('HOUSING_FORM_POLICY.json',policy)

problems=[
 ('P1-HOUSING-FORM','P1','unidentified','policy_defined_execution_pending','H8 natural building floors cannot identify detached/apartment morphology or internal levels;5%maisonette prior has no population evidence',loc(GEN/'final_v2/code/generate_candidates.py',429,434),'Keep H8/vintage margins;null unobserved shape/internal levels;separate explicit engineering condition;no fallback-all-apartment'),
 ('P1-AGE-TARGET','P1','under20singleton target identified;G1 detail not identified','policy_defined_execution_pending','G1 all20+ is stricter than inherited singleton-only exclusion',loc(GEN/'MODEL_CARD.md',58),'Preserve singleton-only target, quotas/slots and larger-household minors;do not claim cutoff is census/clinical/legal rule'),
 ('P2-LOW-HIGH','P2','population_shape_unidentified','policy_defined_execution_pending','<=6 floor source-bank classification does not identify housing morphology;7floor row conflicts with H8multistorey bin if portrayed as census mapping',loc(V2/'build_profile_contexts.py',66,67),'Remove population inference;explicit source bank condition or documented independent mapping only'),
 ('P2-TRANSPORT','P2','empirical_transfer_accuracy_unidentified','strong_bindings_implemented_in_frozen_v2;scope_policy_defined','Matching catalog city/year labels or approving mismatch axes does not establish local stock calibration',loc(V2/'PROTOTYPE_POLICY.md',17,21),'Freeze explicit source×target×weather pair matrix, compare source sensitivity;require actual locality/year evidence for empirical matching track'),
 ('P2-PARAMETERS','P2','actual_orientation_infiltration_net_ratio_boundaries_unidentified','design_trace_implemented;preregistered_sensitivity_pending','Fixed ACH.5/north0/net ratio1/1.33/twoAdiabatic walls are engineering setup',loc(V2/'build_profile_contexts.py',98,103),'Lock main setup and selected one-factor sensitivity before new outputs;preserve profile/H6/H7;report paired variance not population distribution'),
 ('P2-AREA-SEMANTICS','P2','net_thermal_area_unidentified','source_derived_labels_implemented;scope_policy_defined','Census permits usable×1.33 as survey H6 proxy;inverse factor is not measured universal thermal net ratio;CHFS C2004 may be0.7-derived',loc(GEN/'MODEL_CARD.md',62),'Keep survey area bridge and thermal area assumption in separate fields;never double-convert valid observed building area'),
 ('P2-TIME-RENOVATION','P2','contemporaneous_joint_unidentified','source_time_limits_disclosed','CHFS2021/22 housing state differs from2020target;C2012a renovation threshold and censusH10 renovation definition differ',loc(GEN/'MODEL_CARD.md',30),'Keep field reference time and precise construction/renovation definition;do not label transported age/year2020 observed'),
 ('P2-LICENSE','P2','derivative_redistribution_permission_unidentified','unknown_retained','CHFS authorized research download does not prove public release of derived actor profiles;DeST provenance/licence/calibration incomplete',loc(V2/'PROTOTYPE_POLICY.md',103),'Record source access/permissions separately;pending licence does not become permissive declaration;no raw question PDFs or microdata redistribution'),
 ('P2-DEPENDENCE','P2','fine_joint_and_independent_source_households_unidentified','scope_disclosed;benchmark_protocol_pending','Macro margins/source hashes do not identify independent1000real families;shared donor pools/source/parent/climate dependencies remain',loc(GEN/'MODEL_CARD.md',34),'Publish dependence-sensitive split tracks and source influence;all paired variants stay with family for that track'),
 ('REPAIRED-FLOOR-CONDITION','P2','engineering consistency identified;actual floor unknown','repaired_in_frozen_context_plan_v2','Earlier fixedmiddle conflicts with total2;v2 now explicitlytop at floor2',loc(V2/'build_profile_contexts.py',99,101),'Preserve actual total/floor consistency gate;do not promote designed floor to observed'),
 ('REPAIRED-COHORT-PRESERVATION','P2','population weather/city still unidentified','repaired_boundary_in_frozen_v2','All1000 slots and family/housing semantics retained;755ready245blocked static;not755representative local homes',loc(V2/'TASK_CARD.json',12,13),'Continue reporting1000denominator;geometry/source refusal codes and detailed cohort shifts;station context remains separate')
]
write('PROBLEM_LEDGER.json',{'schema':'eb.method_problem_ledger.v1','scope':'author internal source/method self-audit;not official venue review',
 'audit_date':'2026-10-03','frozen_files_modified':False,'survey_rows_read':False,
 'statuses_are_separate':'repair_status distinguishes executed code repair, written policy and pending integration;identification_status is never upgraded by a passing structural test',
 'problems':[dict(id=i,severity=s,identification_status=iden,repair_status=rep,problem=problem,local_evidence=ev,acceptance_rule=rule) for i,s,iden,rep,problem,ev,rule in problems]})

urls=[
 {'id':'NBS-CENSUS-PLAN','url':'https://www.stats.gov.cn/sj/pcsj/rkpc/7rp/zk/html/fu06.pdf','primary':True,'verified':'web opened and cached PDF locally parsed2026-10-03','supports':'H5types4/8/26;H6surveyarea26;H7naturalroom26–27;H8naturalbuildingfloors9/29;H10renovationdefinition30','does_not_support':'apartment/maisonette frequency;observed household topology;universal thermal netratio'},
 {'id':'NBS-H8-MARGINS','url':'https://www.stats.gov.cn/sj/pcsj/rkpc/7rp/zk/html/B0901a.xls','primary':True,'verified':'used frozen official-source constraint/cache;not redownloaded in this audit','supports':'province aggregate ordinary-residence building-floor category margins','does_not_support':'individual houseform/internallevels or full joint with household generation/size'},
 {'id':'NBS-H10-MARGINS','url':'https://www.stats.gov.cn/sj/pcsj/rkpc/7rp/zk/html/B0902a.xls','primary':True,'verified':'used frozen official-source constraint/cache;not redownloaded in this audit','supports':'province aggregate ordinary-residence vintage area means','does_not_support':'individually measured construction year/thermalcalibration'},
 {'id':'CHFS2021-RELEASE','url':'https://chfs.swufe.edu.cn/info/1041/4051.htm','primary':True,'verified':'web opened2026-10-03','supports':'2021round implemented2021/22;2026publicrelease and coverage','questionnaire_direct_public_download_url':'unknown;questionnaires obtained in authorized local download bundle','does_not_support':'specific microdata semantics without questionnaire/metadata or derivative-publication permission'},
 {'id':'CHFS-USE-TERMS','url':'https://chfs.swufe.edu.cn/info/1041/2131.htm','primary':True,'verified':'web opened2026-10-03','supports':'registered approved use;no unauthorized transfer/sale/website publication;subprovince geography pseudoids','does_not_support':'automatic permission for public synthetic derivative or redistribution ofsourcePDF'},
 {'id':'EP24-ACH','url':'https://bigladdersoftware.com/epx/docs/24-1/input-output-reference/group-airflow.html#zoneinfiltrationdesignflowrate','primary':True,'verified':'published E+24.1reference web opened2026-10-03;writer object locally read','supports':'ACH input defines design infiltration flow with zone volume,schedule and constant/temp/wind coefficients','does_not_support':'China observed/normative ACH.5;total natural ventilation or window-opening behavior'},
 {'id':'EP24-ORIENTATION','url':'https://bigladdersoftware.com/epx/docs/24-1/input-output-reference/group-simulation-parameters.html#field-north-axis','primary':True,'verified':'web opened2026-10-03','supports':'North Axis true-north clockwise rotation;onlyrelative coordinates use it','does_not_support':'Chinese dwelling orientationdistribution or defaultNorth0 validity'},
 {'id':'EP24-BOUNDARIES','url':'https://bigladdersoftware.com/epx/docs/24-1/input-output-reference/group-thermal-zone-description-geometry.html#field-outside-boundary-condition','primary':True,'verified':'web opened2026-10-03','supports':'Adiabatic no exterior heat transfer with retained thermal mass;interzone needs reciprocal surfaces;relative coordinate mechanism','does_not_support':'actual neighboring dwellings same temperatures or chosen two-party-wall stock frequency'},
 {'id':'METHOD-SKILL-PROVENANCE','url':'https://doi.org/10.48550/arXiv.2609.00065','primary':True,'verified':'arxiv authors/currentv2 checked2026-10-03','supports':'Kassis,Agarwal,He,Patel,Brueckner2026Scientific Agent Skills workflow provenance only','does_not_support':'housing/CHFS source accuracy,benchmark acceptance or official physical thresholds'}
]
profiles=json.loads((GEN/'final_v2/FAMILY_HOUSING_CANDIDATES.json').read_text())['profiles']
summary=json.loads((V2/'population_contexts_v1/SUMMARY.json').read_text())
write('SOURCE_POLICY_EVIDENCE.json',{'schema':'eb.source_policy.evidence.v1','date':'2026-10-03',
 'review_access':'documentation,metadata,anonymous frozen synthetic profiles,code and aggregate run summaries;no dta',
 'files':[{'path':str(p),'sha256':sha(p),'role':'review_input' if p.parent!=HERE else 'independent_policy_checker'} for p in source_files],
 'sources':urls,'frozen_baseline_counts':{'profiles':len(profiles),'dwelling_type_design_counts':dict(Counter(p['housing']['dwelling_type'] for p in profiles)),
 'static_IDF_ready':summary['IDF_ready'],'static_blocked':summary['blocked'],'static_batch_actual_annual_runs':summary['actual_EP_annual_runs'],
 'note':'new separate annual matrix is outside this source-method audit;do not infer all755annual-tested'},
 'limitations':['metadata audit cannot establish actual field values or fulljoint','no other CHFS wave/restricted-file completeness claim','no actual newgenerator runtime review in this artifact','legal adulthood not researched because20cutoff is explicitly a researchframe boundary;no legalageclaim made'],
 'admission_thresholds':'all numerical sensitivity grids and runtime ACH cap are engineering/project policy,not official physical/population standards'})
print('written policy/evidence/field review/problem ledger;no frozen files changed')
