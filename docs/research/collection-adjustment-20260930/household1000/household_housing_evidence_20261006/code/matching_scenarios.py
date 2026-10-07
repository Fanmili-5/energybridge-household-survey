"""1000 explicit partial-information routes; no fabricated observed years.

The negative developmental comparison excludes admission of a superior full
N/G/R/B/year model. Its N/G year marginal is a candidate auxiliary prior only.
Province-restricted native references and weather are physical alternatives,
not population-weighted, observed household locations or stock matches.
"""
import collections,json
from pathlib import Path
from build_year_bridge import distributions,joint
OUT=Path(__file__).resolve().parent.parent;BASE=OUT.parent;REPO=OUT.parents[4]
PROVINCES=dict(zip('Jilin Beijing Hunan Sichuan Yunnan Liaoning Guangdong Zhejiang Neimenggu Jiangsu Jiangxi Guangxi Xingjiang Anhui Shan1xi Heilongjiang Shandong Gansu Hubei Hebei Hainan Shanghai Tianjin Fujian Shan3xi Chongqing Qinghai Henan Guizhou Ningxia'.split(),
 '吉林 北京 湖南 四川 云南 辽宁 广东 浙江 内蒙古 江苏 江西 广西 新疆 安徽 山西 黑龙江 山东 甘肃 湖北 河北 海南 上海 天津 福建 陕西 重庆 青海 河南 贵州 宁夏'.split()))
PROVINCES['云南']='云南'
PROVINCES['Xizang']='西藏'
def save(name,data):(OUT/name).write_text(json.dumps(data,ensure_ascii=False,indent=2,allow_nan=False)+'\n')
def main():
    from evidence_guard import ensure_unsealed
    ensure_unsealed(OUT)
    source=json.loads((REPO/'artifacts/private_research/household_housing_evidence_20261006/OWNED_JOINT_YEAR_SOURCE_PRIVATE.json').read_text());glob,local=distributions(source)
    regs=json.loads((OUT/'NATIVE_REFERENCE_REGISTRY.json').read_text())['models'];assemblies={r['model_key']:r for r in json.loads((OUT/'REGIONAL_ASSEMBLY_ADMISSION.json').read_text())['models']}
    extra=OUT/'ADDITIONAL_REGIONAL_REFERENCES.json'
    if extra.exists():
        for r in json.loads(extra.read_text())['models']:
            regs.append(r);assemblies[r['model_key']]={'bundle_path':r['assembly_bundle_path'],'sha256':r['assembly_bundle_sha256']}
    support={r['household_id']:r for r in json.loads((OUT/'YEAR_SUPPORT1000.json').read_text())['households']}
    sleep={r['household_id']:r for r in json.loads((OUT/'SLEEP_GEOMETRY_AUDIT1000.json').read_text())['cases']}
    pp=json.loads((BASE/'idf_joint_production_20261005/HOUSEHOLDS1000_JOINT_GEOMETRY_CANDIDATE.json').read_text())['profiles'];result=[];regional=collections.defaultdict(list)
    for r in regs:
        province=PROVINCES[r['original_environment']['PROVINCE']];r['normalized_province']=province
        if r['catalogue_city_matches_original_environment'] and r['coordinate_confirmed_WMO_station_candidates']:regional[province].append(r)
    for p in pp:
        name=p['slot_id'];N=p['family']['resident_count'];G=p['family']['generation_count'];R=p['housing']['H7_independent_natural_rooms_design'];B=p['housing']['percap_area_bin_index'];sp=support[name]
        prior=joint(glob,local,N,G).sum((0,1));refs=regional[p['province']]
        ycounts=collections.Counter(0 if r['catalogue_reference_epoch']<1980 else 1 if r['catalogue_reference_epoch']<2000 else 2 if r['catalogue_reference_epoch']<2010 else 3 for r in refs)
        result.append({'household_id':name,'province':p['province'],'N':N,'G':G,'H7_design':R,'area_bin':B,
          'observed_household_effective_year':None,'observed_household_city':None,'observed_household_building_type':None,
          'year_reference_2020_but_source_visit2021':True,'candidate_effective_year_epoch_prior_NG':prior.tolist(),
          'prior_is_auxiliary_transport_model_not_national_joint_truth':True,'year_epoch_labels':['pre1980','1980_1999','2000_2009','2010_2020'],
          'candidate_year_model':'year_marginal_from_same_joint_shrunk_NG_table; developmental_negative_full_joint_result_retained',
          'year_room_area_independence_proven':False,'owned_prior_transport_to_other_tenure_or_sharing_required':sp['owned_prior_transport_to_other_tenure_or_sharing_required'],
          'source_support':sp,'sleep_reference0_6m_witness':sleep[name]['baseline0_6m']['capacity_witness_found'],
          'sleep_reference0_8m_witness':sleep[name]['alternative0_8m']['capacity_witness_found'],
          'same_province_opaque_reference_and_WMO_coordinate_weather_candidates':[
            {'model_key':r['model_key'],'reference_epoch':r['catalogue_reference_epoch'],'catalogue_type':r['catalogue_type'],
             'physical_reference_city':r['catalogue_city'],'source_native_sha256':r['source_sha256'],
             'additional_direct_native_opaque_extraction':r.get('original_Access_source_obtained',False),
             'glazing_regional_native_match_admitted':r.get('glazing_regional_native_match_admitted',False),
             'assembly_bundle_path':assemblies[r['model_key']]['bundle_path'],'assembly_bundle_sha256':assemblies[r['model_key']]['sha256'],
             'weather':r['coordinate_confirmed_WMO_station_candidates']} for r in refs],
          'same_province_reference_epoch_bin_candidate_counts':{str(y):ycounts[y] for y in range(4)},
          'missing_before_first_reference_epoch_not_filled_by_newer_code':not ycounts[0],
          'housing_age_implies_code_compliance':False,'shape_reference_population_weights':None,
          'automatic_city_reference_or_nearest_epoch_selection':False,'complete_household_IDF_ready':False,'actor_ready':False})
    report={'routes':result,'population_households_routed':len(result),
      'slots_with_same_province_opaque_reference_and_station_match':sum(bool(r['same_province_opaque_reference_and_WMO_coordinate_weather_candidates']) for r in result),
      'slots_without_regional_reference':[r['household_id'] for r in result if not r['same_province_opaque_reference_and_WMO_coordinate_weather_candidates']],
      'province_reference_coverage':{p:len(v) for p,v in regional.items()},
      'epoch_coverage_is_catalogue_capability_not_household_stock_frequency':True,
      'no_1000_household_years_cities_or_building_types_assigned':True,'no_point_matching_admitted_from_incomplete_evidence':True,
      'current_1000_population_and_world_anchor_unchanged':True,'complete_actor_packages':0}
    save('MATCHING_SCENARIOS1000.json',report);print(json.dumps({k:v for k,v in report.items() if k not in ['routes','slots_without_regional_reference']},ensure_ascii=False,indent=2))
if __name__=='__main__':main()
