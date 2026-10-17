"""Conserve the family stock frame; select a reference candidate, not a new age.

Catalogue intervals inferred from adjacent entries are planning aids, never
verified local adoption dates. Old stock requires an envelope bridge, never
resampled family age or a move to a city with a convenient prototype.
"""
import copy,hashlib
PROVINCES=dict(zip('Jilin Beijing Hunan Sichuan Yunnan Liaoning Guangdong Zhejiang Neimenggu Jiangsu Jiangxi Guangxi Xingjiang Anhui Shan1xi Heilongjiang Shandong Gansu Hubei Hebei Hainan Shanghai Tianjin Fujian Shan3xi Chongqing Qinghai Henan Guizhou Ningxia Xizang'.split(),
    '吉林 北京 湖南 四川 云南 辽宁 广东 浙江 内蒙古 江苏 江西 广西 新疆 安徽 山西 黑龙江 山东 甘肃 湖北 河北 海南 上海 天津 福建 陕西 重庆 青海 河南 贵州 宁夏 西藏'.split()))
def rank(*xs):return hashlib.sha256('|'.join(map(str,xs)).encode()).hexdigest()
def bounds(label):
    if label=='pre1949':return 0,1948
    lo,hi=label.split('_');return int(lo),int(hi)
def choose(world,registry):
    hid=world['household_id'];old=world['layout']['stock_reference_features']
    kind='HighS'if old['building_storeys']in('8_to33','34plus')else'Low'
    type_order=['HighT','HighS']if old['building_storeys']=='34plus'else['HighS','HighT']if kind=='HighS'else['Low']
    city=world['layout']['source_parameter_reference']['physical_reference_city']
    available=[r for r in registry if r.get('native_reference_admission')!='rejected'
        and r['catalogue_type']in type_order and r['catalogue_city']==city
        and PROVINCES.get(r['original_environment']['PROVINCE'])==world['province']
        and r['catalogue_city_matches_original_environment']and r['coordinate_confirmed_WMO_station_candidates']]
    if not available:raise ValueError('NO_NATIVE_REFERENCE_IN_FIXED_CITY_AND_TYPE:'+hid+':'+city+':'+kind)
    preferred=min(type_order.index(r['catalogue_type'])for r in available)
    available=[r for r in available if type_order.index(r['catalogue_type'])==preferred]
    kind=type_order[preferred]
    lo,hi=bounds(old['effective_building_epoch'])
    exact=[r for r in available if max(lo,r['regime_begin'])<=min(hi,r['regime_end'])]
    gap=lambda r:max(r['regime_begin']-hi,lo-r['regime_end'],0)
    pool=exact or available;best=min(map(gap,pool));pool=[r for r in pool if gap(r)==best]
    original_key=world['layout']['source_parameter_reference']['model_key']
    selected=min(pool,key=lambda r:(r['model_key']!=original_key,rank('V32-fixed-family-candidate',hid,r['model_key'])))
    facet=copy.deepcopy(old)
    record={'old_independent_stock_assignment':copy.deepcopy(old),'physical_stock_reference':copy.deepcopy(old),
        'source_model_key':selected['model_key'],'required_catalogue_type':kind,'source_catalogue_type':selected['catalogue_type'],
        'source_reference_epoch':selected['catalogue_reference_epoch'],'source_reference_period':old['effective_building_epoch'],
        'catalogue_inferred_regime':[selected['regime_begin'],selected['regime_end']],
        'catalogue_regime_is_verified_local_adoption_interval':False,
        'physical_construction_reference_year':None,'construction_year_is_synthetic':None,
        'original_reference_period_supported':None,'catalogue_interval_intersects_given_period':bool(exact),
        'catalogue_interval_covers_whole_given_period':selected['regime_begin']<=lo and selected['regime_end']>=hi,
        'old_period_retained_as_observed_fact':False,'given_synthetic_stock_frame_preserved':True,
        'reference_vintage_resynthesized':False,'fixed_reference_city_preserved':True,
        'candidate_count':len(available),'same_given_period_candidates':len(exact),
        'fallback_rule':'planning candidate only; retain original stock and require historical bridge'if not exact else None,
        'minimum_unsupported_temporal_gap_years':gap(selected),'historical_envelope_bridge_required':not bool(exact),
        'vintage_physics_admitted':False,'selection_uses_EP_or_human_outcomes':False,
        'reference_epoch_is_household_observed_build_year':False,
        'scientific_scope':'fixed-family native candidate; local implementation and historical evidence assessed separately'}
    return copy.deepcopy(selected),facet,record
