"""Independent V19 household-production readback against frozen source controls.

No generator imports, source resampling, EP, answer generation or production
edits. Shapes and statistics are audited within declared reference scope.
"""
import collections, concurrent.futures, datetime as dt, hashlib, json, math, sys
from pathlib import Path
O=Path(__file__).resolve().parents[1];H=O.parent;N=H/'evidence_conditioned_production_20261009_v19';S=O/'source_snapshots'
EXPECTED={'v6/ORDINARY_CITY_FRAME.json':'533ac5b3788e23fbcf7b42b1eeec5e28265983f8be113a67ca20f72e93520e30','v6/ORDINARY_ALLOCATION1000.json':'6b61dca146c6cde4db1b29c9b90250a534b6d424b6724f7aab1e40bd3ac01512','v6/HOUSEHOLDS1000_JOINT_CANDIDATE.json':'68a4350c06a68cdadd2247965540c87552a217d973c8d9f98f43759094989a1b','v7/HOUSEHOLDS1000_JOINT_GEOMETRY_CANDIDATE.json':'e81c55acb69660d0ff5e8b228484a0da4fb1932e294c0dbd23e3fe92e46e2c64'}
# Positive = elder, matching the frozen source contract. The first draft used
# the opposite convention; its false positives are preserved separately.
LEVEL={1:0,2:0,3:1,4:1,5:2,6:-1,7:-1,8:-2,9:-2,10:0};CORE=('member_id','age_years','sex','generation_level','ego_relation_code','current_work_source_proxy');KINDS={'ac','washer','dryer','dishwasher','water_heater','ev'}
def read(p):return json.loads(p.read_text())
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def save(name,v):(O/name).write_text(json.dumps(v,ensure_ascii=False,indent=2,sort_keys=True)+'\n')
def rect_area(r):return (r[2]-r[0])*(r[3]-r[1])
def contained(a,b):return a[0]>=b[0]-1e-7 and a[1]>=b[1]-1e-7 and a[2]<=b[2]+1e-7 and a[3]<=b[3]+1e-7
def intersect_area(a,b):return max(0,min(a[2],b[2])-max(a[0],b[0]))*max(0,min(a[3],b[3])-max(a[1],b[1]))
def one(args):
    h,source=args;w=read(N/h['world_path']);hid=w['household_id'];fail=[];c=collections.Counter();examples=collections.defaultdict(list)
    def check(v,label):
        if not v:fail.append(label)
    family=source['family'];members=w['members'];check(len(members)==w['N']==family['resident_count'],'N_ROSTER_SOURCE')
    check(w['G']==len({m['generation_level'] for m in members})==family['generation_count'],'G_OCCUPIED_LEVELS')
    check(w['province']==source['province'] and w['population_weight']==source['relative_population_weight'],'PROVINCE_WEIGHT_SOURCE')
    check(w['H6']==source['housing']['H6_census_building_area_design_m2'] and w['H7']==source['housing']['H7_independent_natural_rooms_design'],'H6_H7_GEOMETRY_ANCHORS')
    check([[m[k] for k in CORE] for m in members]==[[m[k] for k in CORE] for m in family['members']],'MEMBER_SOURCE_CORE')
    check(w['ego_relationships']==family['ego_relationships'],'EGO_RELATION_SOURCE')
    check(len({m['member_id'] for m in members})==len(members) and sum(m['ego_relation_code']==1 for m in members)==1,'MEMBER_IDS_EGO')
    root=next(m for m in members if m['ego_relation_code']==1);agegaps=[]
    for m in members:
        check(LEVEL[m['ego_relation_code']]==m['generation_level'],'RELATION_LEVEL_MAP')
        lo,hi=m['age_bin_reference'];check(m['age_years']>=lo and (hi is None or m['age_years']<=hi),'AGE_PUBLISHED_BIN')
        expected='has_work' if m['current_work_source_proxy'] in (1,2) else 'no_current_work' if m['current_work_source_proxy']==3 else 'unknown'
        check(m['employment_status']==expected,'WORK_CODE_SOURCE_UNKNOWN')
        check(m['activity_scenario_is_observed'] is False and m['exact_times_are_design_not_individual_diary'] is True,'ACTIVITY_EVIDENCE_STATUS')
        if expected=='unknown':
            c['unknown_work_members']+=1;c['unknown_work_adults']+=m['age_years']>=18
        if m['current_work_source_proxy']==2:c['work_code2_members']+=1
        if m['ego_relation_code'] in (3,5,6,8):
            gap=(m['age_years']-root['age_years']) if m['ego_relation_code'] in (3,5) else (root['age_years']-m['age_years'])
            check(gap>0,'DECLARED_CONVENTIONAL_AGE_ORDER');agegaps.append({'relation_code':m['ego_relation_code'],'gap_years':gap})
            if m['ego_relation_code']==3 and gap<12:
                c['parent_ego_age_gap_under12_reference_review']+=1
                examples['parent_ego_age_gap_under12_reference_review'].append({'household_id':hid,'ego_age':root['age_years'],'parent_role_age':m['age_years'],'gap_years':gap,'ego_bin':root['age_bin_reference'],'parent_bin':m['age_bin_reference'],'source_atom_hash':family['motif_group_hash'],'full_biological_parentage_identified':False,'meaning':'reference semantics needs review; descriptive threshold not biological/legal proof or source invalidity'})
        c['members']+=1;c['activity:'+m['reference_activity_role']]+=1
    check(w['actor_preferences_and_answers'] is None,'NO_SYNTHETIC_HUMAN_LABEL')
    check(w['economic_reference']['source_income_bin']==family['income_reference_bin'] and w['economic_reference']['calendar_year'] is None,'ECONOMIC_SOURCE_NOT_CURRENT_INCOME')
    c['source_income_unknown_households']+=family['income_reference_bin'] is None
    c['economic_count_unknown_households']+=family['economic_family_reference_count'] is None
    c['economic_count_known_differs_from_generated_N_households']+=family['economic_family_reference_count'] is not None and family['economic_family_reference_count']!=w['N']
    c['selected_atom_single_source_slots']+=family['selected_coarse_atom_source_count']==1
    c['motif_graft_slots']+=family['motif_graft_extrapolation'];c['source2022_fallback_slots']+=family['source_joint_attribute_visit_year']==2022
    c['under20_singletons']+=w['N']==1 and members[0]['age_years']<20
    c['no_adult_households']+=not any(m['age_years']>=18 for m in members)
    check(family['full_biological_pairwise_parentage_identified'] is False,'NO_FULL_PARENTAGE_IMPUTATION')
    layout=w['layout'];rooms=layout['rooms'];rmap={r['room_id']:r for r in rooms};alloc=collections.defaultdict(float)
    check(len(rooms)==len(rmap),'ROOM_IDS')
    for i,r in enumerate(rooms):
        box=r['gross_rect_m'];check(rect_area(box)>0 and contained(box,layout['metric_outer_rect_m']),'GROSS_ROOM_GEOMETRY')
        check(not any(intersect_area(box,z['gross_rect_m'])>1e-7 for z in rooms[:i]),'GROSS_ROOM_OVERLAP')
        check(abs(rect_area(box)-r['gross_area_m2'])<1e-6,'GROSS_ROOM_AREA_FIELD')
        check(contained(r['usable_rect_m'],box) and abs(rect_area(r['usable_rect_m'])-r['usable_area_m2'])<1e-6 and r['usable_area_m2']>0,'USABLE_GEOMETRY_AREA')
        check(abs(sum(r['area_allocation_fractions'].values())-1)<1e-8 and min(r['area_allocation_fractions'].values())>=0,'AREA_SHARES')
        for x,f in r['area_allocation_fractions'].items():alloc[x]+=r['gross_area_m2']*f
        check(r['energy_meter_allocation_fractions'] is None,'AREA_NOT_METER_ALLOCATION')
    check(abs(sum(r['gross_area_m2'] for r in rooms)-rect_area(layout['metric_outer_rect_m']))<1e-6,'WHOLE_GROSS_PARTITION')
    check(abs(alloc[hid]-w['H6'])<1e-6 and abs(sum(alloc.values())-layout['whole_unit_building_area_m2'])<1e-6,'H6_ALLOCATED_IDENTITY')
    check(sum(r['census_room_class']=='bedroom' and r['using_household_ids']==[hid] for r in rooms)==w['H7'],'H7_INDEPENDENT_NATURAL_ROOMS')
    check(all(m['reference_home_room_id'] in rmap and hid in rmap[m['reference_home_room_id']]['using_household_ids'] for m in members),'MEMBER_SLEEP_ROOM_RIGHT')
    berths=layout['sleep_reference']['berths'];frames=layout['sleep_reference']['frames'];beds=collections.defaultdict(list);fmap={f['frame_id']:f for f in frames}
    check(sorted(b['member_id'] for b in berths)==sorted(m['member_id'] for m in members),'ONE_BERTH_PER_RESIDENT')
    for b in berths:
        check(b['frame_id'] in fmap and b['room_id']==fmap[b['frame_id']]['room_id'],'BERTH_FRAME_BINDING')
        if b['level']>0:
            c['upper_bunk_berths']+=1
            if b['age_years']<6 or b['age_years']>=75:examples['upper_bunk_age_for_review'].append({'household_id':hid,'berth':b})
    for f in frames:
        rect=f['outer_rect_m'];rid=f['room_id'];check(contained(rect,rmap[rid]['usable_rect_m']),'BED_WITHIN_USABLE_ROOM')
        check(not any(intersect_area(rect,b)>1e-8 for b in beds[rid]),'BED_FRAME_OVERLAP');beds[rid].append(rect);c['bed_frame:'+f['kind']]+=1
    for q in w['joint_matching']['spatial_witnesses']:
        rid=q['room_id'];body=q['body_rect_m'];env=q['operation_envelope_rect_m'];check(contained(env,rmap[rid]['usable_rect_m']) and contained(body,env),'FIXTURE_BODY_ENVELOPE')
        check(not any(intersect_area(env,b)>1e-8 for b in beds[rid]),'FIXTURE_BED_OR_FIXTURE_OVERLAP');beds[rid].append(env);c['spatial_fixture:'+q['kind']]+=1
    devices=w['parameter_pack']['devices'];types={k for d in devices for k in d['types']}
    check(types<=KINDS and 4<=len(types)<=6 and ('dryer' not in types or 'washer' in types),'EB_CLASS_COVERAGE')
    check(sorted(types)==sorted(w['joint_matching']['types']),'COVERAGE_LEDGER')
    check(len({d['asset_id'] for d in devices})==len(devices),'PHYSICAL_ASSET_IDS')
    ops={x['operator_id']:x for x in w['operating_context']['operators']};mmap={m['member_id']:m for m in members}
    for d in devices:
        check(d['operator_id'] in ops,'DEVICE_OPERATOR_BINDING')
        if d['room_id']!='external_dedicated_EV_bay':check(d['room_id'] in rmap and hid in rmap[d['room_id']]['using_household_ids'],'DEVICE_ROOM_RIGHT')
        if ops[d['operator_id']]['resident']:check(d['operator_id'] in mmap and mmap[d['operator_id']]['age_years']>=18,'REFERENCE_ADULT_OPERATOR')
    c['K:'+str(len(types))]+=1
    for k in types:c['device_class:'+k]+=1
    c['physical_devices']+=len(devices);c['q:'+str(layout['shared_household_count_design'])]+=1
    original=w['evidence_layer']['original_housing_facets'];configured=layout['stock_reference_features'];changes=w['reference_change_ledger']
    for key in original:
        if original[key]!=configured[key]:
            c['configured_facet_changes:'+key]+=1
            if len(examples['configured_facet_changes'])<2:examples['configured_facet_changes'].append({'household_id':hid,'field':key,'source_reference':original[key],'configured_reference':configured[key],'change_ledger':changes})
    r=w['routine'];c['laundry_frequency_fallback_households']+=r['historical_frequency_bin'] is None
    c['historical_frequency_known_households']+=r['historical_frequency_bin'] is not None
    c['historical_high_frequency_normalized_households']+=bool(r['high_frequency_transport_normalized'])
    c['batch_mass_at_4_5kg_cap_households']+=r['laundry_batch_kg']==4.5
    c['N7plus_households']+=w['N']>=7
    check(r['batch_mass_is_reference_design'] is True,'BATCH_MASS_NOT_SOURCE_OBSERVATION')
    dates=[dt.date.fromisoformat(x['date']) for x in h['rounds']];check(len(dates)==10 and len(set(dates))==10 and all(d.year==2025 for d in dates),'TEN_ORIGINAL2025_DATES')
    qc=collections.Counter((d.month-1)//3+1 for d in dates);check(set(qc)=={1,2,3,4} and all(2<=v<=3 for v in qc.values()),'QUARTER_DATE_COVERAGE')
    need_counts=collections.Counter()
    for row in h['rounds']:
        pair=read(N/row['pair_path'])
        check(pair['needs_A']==pair['needs_B'],'COMMON_FIXED_DEMAND')
        for need in pair['needs_A']:
            if need['kind'] in ('washer','dishwasher'):
                need_counts[need['kind']+'_service_deadline_from_next_operator_window']+=1
                if len(examples['availability_derived_service_deadline'])<1:examples['availability_derived_service_deadline'].append({'case_id':pair['case_id'],'need':need,'source_rule':'plans.py operator_morning -> max(nend,nm+40) -> next_deadline'})
    return {'household_id':hid,'failures':sorted(set(fail)),'counts':dict(c),'examples':dict(examples),'N':w['N'],'G':w['G'],'H6':w['H6'],'H7':w['H7'],'province':w['province'],'weight':w['population_weight'],'area_bin':source['housing']['percap_area_bin_index'],'motif_group_hash':family['motif_group_hash'],'roster_signature':hashlib.sha256(json.dumps([[m[k] for k in CORE if k!='member_id'] for m in members],sort_keys=True).encode()).hexdigest(),'agegaps':agegaps,'need_counts':dict(need_counts),'K':len(types)}

def apportion(total,values):
    x=[v/sum(values)*total for v in values];out=[math.floor(v) for v in x]
    for i in sorted(range(len(x)),key=lambda i:(-(x[i]-out[i]),i))[:total-sum(out)]:out[i]+=1
    return out
def main():
    if sys.platform!='linux':raise RuntimeError('School Linux only')
    assert sha(N/'DELIVERY.json')=='66309e41f8eaba6ace847caaae0dac4fed8981eb5024c0adcf15035f2db6d89e'
    for path,value in EXPECTED.items():assert sha(S/path)==value,('source snapshot hash',path)
    frame=read(S/'v6/ORDINARY_CITY_FRAME.json');profiles=read(S/'v7/HOUSEHOLDS1000_JOINT_GEOMETRY_CANDIDATE.json')['profiles'];source={x['slot_id']:x for x in profiles};selection=read(N/'SELECTION1000.json')
    with concurrent.futures.ProcessPoolExecutor(max_workers=12) as pool:rows=list(pool.map(one,[(h,source[h['household_id']]) for h in selection['records']]))
    counts=collections.Counter();needs=collections.Counter();examples=collections.defaultdict(list)
    for r in rows:
        counts.update(r['counts']);needs.update(r['need_counts'])
        for k,v in r['examples'].items():examples[k].extend(v[:max(0,5-len(examples[k]))])
    fail=[{'household_id':r['household_id'],'checks':r['failures']} for r in rows if r['failures']];margfail=[]
    byp=collections.Counter(r['province'] for r in rows);totalw=sum(r['weight'] for r in rows)
    if byp!=frame['integer_allocation']['province_quota']:margfail.append('PROVINCE_QUOTAS')
    nc=collections.Counter(min(r['N'],10) for r in rows);gc=collections.Counter(r['G'] for r in rows);hc=collections.Counter(min(r['H7'],10) for r in rows);ac=collections.Counter(r['area_bin'] for r in rows)
    room_target=apportion(1000,[sum(x[b] for x in frame['ordinary_room10_counts']) for b in range(10)]);area_target=apportion(1000,[sum(x[b] for x in frame['ordinary_percap_area10_counts']) for b in range(10)])
    for label,actual,expected in [('N',[nc[i] for i in range(1,11)],frame['integer_allocation']['modeled_national_size_quotas']),('G',[gc[i] for i in range(1,6)],frame['integer_allocation']['national_generation_quotas']),('H7',[hc[i] for i in range(1,11)],room_target),('area_bin',[ac[i] for i in range(10)],area_target)]:
        if actual!=expected:margfail.append(label+'_NATIONAL_QUOTA')
    provincial=[]
    for pi,province in enumerate(frame['provinces']):
        group=[r for r in rows if r['province']==province];weighted_share=sum(r['weight'] for r in group)/totalw;target_share=frame['ordinary_household_counts'][pi]/frame['official_households']
        if abs(weighted_share-target_share)>1e-10:margfail.append('WEIGHTED_PROVINCE:'+province)
        for g in range(1,6):
            for b in range(1,6):
                actual=sum(r['G']==g and min(r['H7'],5)==b for r in group);expected=frame['ordinary_generation_room_counts'][pi][g-1][b-1]/frame['official_households']*1000
                if not math.floor(expected)<=actual<=math.ceil(expected):margfail.append('PROVINCE_G_H7:'+province)
        for b in range(10):
            actual=sum(r['area_bin']==b for r in group);expected=frame['ordinary_percap_area10_counts'][pi][b]/frame['official_households']*1000
            if not math.floor(expected)<=actual<=math.ceil(expected):margfail.append('PROVINCE_AREA_BIN:'+province)
        provincial.append({'province':province,'households':len(group),'weighted_share':weighted_share,'official_share':target_share,'mean_H6_design_m2':sum(r['H6'] for r in group)/len(group),'official_mean_H6_m2':frame['ordinary_mean_building_area_m2'][pi]})
    weighted_area=sum(r['weight']*r['H6'] for r in rows)/totalw;weighted_N=sum(r['weight']*r['N'] for r in rows)/totalw
    if abs(weighted_area-92.17)>.005:margfail.append('WEIGHTED_AREA_DECLARED_ROUNDING')
    duplicates={}
    for field in ('motif_group_hash','roster_signature'):
        pools=collections.defaultdict(list)
        for r in rows:pools[r[field]].append(r['household_id'])
        repeated=[v for v in pools.values() if len(v)>1];duplicates[field]={'distinct_groups':len(pools),'repeated_groups':len(repeated),'households_in_repeated_groups':sum(map(len,repeated)),'largest_group':max(map(len,pools.values())),'examples':repeated[:6],'meaning':'shared auxiliary motif or identical demographics,not proof of same true household or identical full task world'}
    signature_gaps=collections.defaultdict(list)
    for r in rows:
        for x in r['agegaps']:signature_gaps[x['relation_code']].append(x['gap_years'])
    result={'schema':'eb.independent_household_production_audit.v1','date':'2026-10-09','households':len(rows),'members':counts['members'],'source_snapshots_sha256':EXPECTED,'production_DELIVERY_sha256':sha(N/'DELIVERY.json'),'source_check_failures':fail,'population_control_failures':sorted(set(margfail)),'counts':dict(counts),'service_need_counts':dict(needs),'N_counts':dict(nc),'G_counts':dict(gc),'H7_counts':dict(hc),'area_bin_counts':dict(ac),'weighted_mean_N':weighted_N,'official_mean_N':frame['official_mean_residents'],'weighted_mean_H6':weighted_area,'official_H6_mean':92.17,'weighted_G_shares':{g:sum(r['weight'] for r in rows if r['G']==g)/totalw for g in range(1,6)},'official_G_shares':{g:sum(sum(x[g-1]) for x in frame['ordinary_generation_room_counts'])/frame['official_households'] for g in range(1,6)},'province_diagnostics':provincial,'duplicates':duplicates,'generation_age_gap_ranges':{k:[min(v),max(v)] for k,v in signature_gaps.items()},'examples':dict(examples),'EP_started':0,'human_answers':0,'production_modified':False,'scope_limits':['controls are fitted,not independent validation','source snapshots are public-control and already-coarsened synthetic outputs,not a fresh licensed-microdata re-extraction','rectangle and allocation checks do not establish access-path/code/clinical/real-housing validity','source weights do not identify actual installed-equipment/activity/attitude frequencies','shared motif is a split sensitivity consideration,not automatic train/test contamination','availability-derived deadlines are declared experimental conditions,not observed next-use needs']}
    save('PRODUCTION_DATA_AUDIT.json',result);save('HOUSEHOLD_CHECKS1000.json',{'records':rows,'EP_started':0,'source_ids_or_human_answers_exported':False})
    print({'households':len(rows),'members':counts['members'],'source_check_failure_count':len(fail),'source_check_failure_examples':fail[:3],'population_control_failures':result['population_control_failures'],'counts':dict(counts),'service_need_counts':dict(needs),'weighted_mean_N':weighted_N,'weighted_mean_H6':weighted_area,'duplicates':duplicates,'generation_age_gap_ranges':result['generation_age_gap_ranges'],'age_review_examples':list(examples['parent_ego_age_gap_under12_reference_review'])},flush=True)
if __name__=='__main__':main()
