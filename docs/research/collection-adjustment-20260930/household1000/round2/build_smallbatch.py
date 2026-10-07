#!/usr/bin/env python3
"""Only 13 boundary cases + projections of existing 300; never regenerates 1000."""
import argparse, collections as C, copy, importlib.util, math, sys, time
from pathlib import Path
from common import HERE,ROOT,digest,sha,read,write,project,profile_errors
from daily import generate,select_B

def module(name,path):
    s=importlib.util.spec_from_file_location(name,path);m=importlib.util.module_from_spec(s);s.loader.exec_module(m);return m

def hist(values):return dict(sorted(C.Counter(str(x) for x in values).items()))
def metrics(profiles):
    areas=[p['dwelling'].get('whole_dwelling_building_area_design_m2') for p in profiles]
    known=[x for x in areas if x is not None]
    return {'n':len(profiles),'size':hist(p['family_size'] for p in profiles),
        'generation':hist(p['generation_design'] for p in profiles),'province':hist(p['province'] for p in profiles),
        'H7':hist(p['dwelling'].get('room_count_design_minimum') for p in profiles),
        'elder_households':sum(any(m['age_design']>=65 for m in p['members']) for p in profiles),
        'area_known':len(known),'area_unknown':len(areas)-len(known),'area_mean':sum(known)/len(known) if known else None,
        'area_bins':hist('unknown' if x is None else '<50' if x<50 else '50-99' if x<100 else '100-199' if x<200 else '200-499' if x<500 else '500+' for x in areas)}

def main(output):
    start=time.monotonic();lock=read(ROOT/'INPUT_LOCK.json');f=lock['files']
    for label in ['CHNS_asset','CHNS_roster','CHNS_probe_code','layout_config','geometry_code','retained_source_lock']:
        assert sha(f[label]['path'])==f[label]['sha256'],label
    out=Path(output).resolve();assert out.is_relative_to(HERE) and out!=HERE;out.mkdir(exist_ok=False,parents=True)
    sys.path[:0]=[str(Path(f['CHNS_probe_code']['path']).parent),str(Path(f['CHNS_asset']['path']).parents[3]/'scripts')]
    raw=module('r2_chns',f['CHNS_probe_code']['path']);geom=module('r2_geom',f['geometry_code']['path']);conf=read(f['layout_config']['path'])
    import pandas as pd
    asset=pd.read_sas(f['CHNS_asset']['path']);roster=pd.read_sas(f['CHNS_roster']['path']);usable,audit=raw.prepare(asset,roster)
    pools=C.defaultdict(C.Counter)
    for r in usable.itertuples(index=False):
        pools[str(int(r.resident_count)) if r.resident_count<5 else '5+'][(float(r.L16),int(r.L17),int(r.resident_count))]+=1
    weighted_stats=[]
    for key,pool in sorted(pools.items()):
        n=sum(pool.values());u=len(pool)
        weighted_stats.append({'resident_group':key,'source_households':n,'distinct_tuples':u,
            'weighted_mean_L16':sum(t[0]*w for t,w in pool.items())/n,'dedup_uniform_mean_L16':sum(t[0] for t in pool)/u,
            'source_999_probability':sum(w for t,w in pool.items() if t[0]==999)/n,
            'dedup_999_probability':sum(t[0]==999 for t in pool)/u})
    metadata=[]
    survey=Path(f['CHNS_asset']['path']).with_name('surveys_pub_12.sas7bdat')
    for path in [Path(f['CHNS_asset']['path']),Path(f['CHNS_roster']['path']),survey]:
        with pd.read_sas(path,iterator=True) as reader:
            cols=list(reader.column_names)
            metadata.append({'file':path.name,'sha256':sha(path),'columns':cols,
                'weight_named_variables':[c for c in cols if 'weight' in c.lower() or c.lower().startswith('wgt')],
                'design_named_variables':[c for c in cols if any(k in c.lower() for k in ['stratum','psu'])]})
    write(out/'SOURCE_AUDIT.json',{'unit':'HHID x 2015; FM0 household; resident roster person-year joined one-to-one',
        'selection':audit,'weights_available_to_this_generator':False,'weight_search_scope':'names in asset/rst/surveys_pub_12; source code does not apply weights; not a claim about all CHNS releases',
        'metadata':metadata,'frequency_pool':weighted_stats,'L16_999_rows':int(usable.L16.eq(999).sum()),
        'L16_ge500_rows':int(usable.L16.ge(500).sum()),'999_meaning':'unresolved endpoint/topcode/entry ambiguity; no confirmed special missing label',
        'source_links':['https://chns.cpc.unc.edu/wp-content/uploads/C15HH_Chi.pdf#page=17','https://chns.cpc.unc.edu/about/design/survey/','https://chns.cpc.unc.edu/about/design/sample/'],
        'L16':'current dwelling usable m2','L17':'rooms excluding bathroom/toilet; not census H7','national_population_claim':False})
    source_lock=read(f['retained_source_lock']['path']);refs={h['role_id']:h for h in source_lock['households']}
    old=[];old_checks=[]
    for rid,ref in sorted(refs.items()):
        row=read(ROOT/'candidate_v2/roles'/f'{rid}.json');src=read(ref['rich_execution_source']['path'])
        assert sha(ref['rich_execution_source']['path'])==ref['rich_execution_source']['sha256']
        p=project(row,src);old.append(p)
        write(out/'mapped_old300'/f'{rid}.json',p)
        old_checks.append({'role_id':rid,'lossless_roundtrip':p['original_row']==row,'asset_roundtrip':p['original_execution_assets']==src['source_overrides']['p2_assets']['assets'],
            'same_profile_check_errors':profile_errors(p),'physics_recertified':False,'source_behavior_hold':True})
    write(out/'OLD300_MAPPING_AUDIT.json',{'n':len(old),'rows':old_checks,'checks':'projection integrity and common static checks; not annual/physical recertification'})
    new_rows=[read(path) for path in sorted((ROOT/'candidate_v2/roles').glob('*.json')) if int(path.stem.split('-')[1])>300]
    projected_new=[project(r) for r in new_rows]
    write(out/'PATH_COMPARISON.json',{'existing300':metrics(old),'prior_new700_diagnostic':metrics(projected_new),
        'same_static_contract':{'existing300_errors':hist(e for p in old for e in profile_errors(p)),
            'prior_new700_errors':hist(e for p in projected_new for e in profile_errors(p))},
        'retaining300_does_not_grant_qualification':True,'regeneration1000_performed':False,
        'unmeasured_for_both':['member/home schedule plausibility','source geometry and behavior binding under common schema','annual task qualification','fresh physical results']})
    choose=lambda predicate:next(r for r in new_rows if predicate(r['profile']))
    cases=[('control',choose(lambda p:p['family_size']==2)),
        ('small_area',choose(lambda p:p['family_size']==3)),
        ('multigeneration',choose(lambda p:p['generation_category']==3)),
        ('multi_routine',choose(lambda p:p['family_size']>=3)),
        ('multi_AC',read(ROOT/'candidate_v2/roles/cityrole-0001.json')),
        ('overnight_EV',read(ROOT/'candidate_v2/roles/cityrole-0001.json')),
        ('manual_wash_dry',choose(lambda p:p['family_size']==2)),
        ('shared_housing',choose(lambda p:p['family_size']==2)),
        ('no_operator',choose(lambda p:p['family_size']==1)),
        ('unknown_999',choose(lambda p:p['family_size']==1)),
        ('missing_city',read(ROOT/'candidate_v2/roles/cityrole-0382.json')),
        ('four_generation',choose(lambda p:p['generation_category']==4)),
        ('tight_deadline',choose(lambda p:p['family_size']==2))]
    # 13 cases: seven required boundaries plus independent negative controls.
    before=[];after=[];housing=[];summaries=[];role_manifest=[]
    for i,(case,row) in enumerate(cases,1):
        src=read(refs[row['role_id']]['rich_execution_source']['path']) if row['role_id'] in refs else None
        p=project(row,src)
        prior_selected_H7=p['dwelling']['room_count_design_minimum']
        p['dwelling']['room_count_design_minimum']=p['dwelling'].get('requested_H7_before_capacity_check',prior_selected_H7)
        before.append(copy.deepcopy(p));original_rid=p['role_id'];p['role_id']=f'diagnostic-r2-{i:02d}'
        p['derived_from_role_id']=original_rid;p['case']=case;p['origin']='explicit_boundary_experiment_not_population_sample'
        for a in p['assets']:
            a['asset_id']=a['asset_id'].replace(original_rid,p['role_id']);a['electrical_boundary_id']=p['role_id']
        # Boundary workloads share a declared rich diagnostic inventory, not a
        # fitted ownership distribution. Empty/unknown rights remain distinct.
        for cls in ['washer','dryer','dishwasher','home_ev']:
            if not any(a['device_class']==cls for a in p['assets']):
                p['assets'].append({'asset_id':f"{p['role_id']}:{cls}:1",'device_class':cls,'zone_id':None,
                    'owner_scope':'ours_private','access_scope':'ours_device_only','owned_design':True,'installed_design':True,
                    'accessible_design':True,'controllable_design':True,'modeled':False,'human_permission':None,
                    'electrical_boundary_id':p['role_id'],'source_path':'explicit_r2_boundary_inventory_design'})
        adult=next(m for m in p['members'] if m['age_design']>=18);p['driver_member_id']=adult['member_id'];adult['routine_design']='out_regular'
        if case=='multi_routine':
            for j,m in enumerate(p['members']):
                m['weekday_home_windows_min']=[[0,1440]] if j%2==0 else [[0,450],[1110,1440]]
        if case=='no_operator':
            for m in p['members']:m['weekday_home_windows_min']=[];m['weekend_home_windows_min']=[]
        if case=='shared_housing':
            p['dwelling']['housing_form_design']='shared_dwelling';p['dwelling']['household_attributed_building_area_m2']=None
            p['dwelling']['shared_or_other_household_area_m2']=None
            for a in p['assets']:a.update(owner_scope='shared_unknown',access_scope='booking_unknown',accessible_design=None,controllable_design=None)
        if case=='manual_wash_dry':p['assets']=[a for a in p['assets'] if a['device_class']!='washer']
        h7=p['dwelling']['room_count_design_minimum'];n=p['family_size'];pool=pools[str(n) if n<5 else '5+'];eligible=[];rejected=C.Counter();cache={}
        def layout_for(t):
            if t in cache:return cache[t]
            area=math.floor(t[0]/t[2]*n*1.33+.5);role={'role_id':p['role_id'],'family_size':n,'members':[{'member_id':m['member_id'],'age_years_design':m['age_design'],'parent_member_ids':m['parent_member_ids'],'partner_member_id':m['partner_member_id'],'role':m['relationship_design'],'relationship_to_reference_adult':m['relationship_design']} for m in p['members']]}
            try:
                layout,error=geom.plan(role,area,h7,conf,{'x+':1,'x-':1,'y+':1,'y-':1});errors=geom.full_layout_errors(role,layout) if layout else [error]
            except Exception as exc:layout=None;errors=[type(exc).__name__+':'+str(exc)]
            cache[t]=(area,layout,errors);return cache[t]
        for t,w in sorted(pool.items()):
            if t[1]<h7:rejected['L17_less_than_fixed_H7_proxy']+=w;continue
            if t[0]==999:eligible.append((t,w,None));continue
            area,layout,errors=layout_for(t)
            if errors:rejected['layout_infeasible']+=w
            else:eligible.append((t,w,(area,layout)))
        support=sum(w for t,w,layout in eligible);u=int(digest([20260930,'row_frequency',case])[:16],16)/2**64
        target=u*support;cumulative=0;chosen=None
        for t,w,layout in eligible:
            cumulative+=w
            if target<cumulative:chosen=(t,w,layout);break
        if case=='unknown_999':chosen=next(((t,w,None) for t,w in sorted(pool.items()) if t[0]==999),None)
        d=p['dwelling'];d['requested_H7_before_capacity_check']=h7;d['source_specific_exterior_and_IDF']=None;d['layout']=None
        t,w,result=chosen if chosen else (None,0,None)
        if t is None or t[0]==999:d['whole_dwelling_building_area_design_m2']=None;d['household_modeled_net_area_design_m2']=None
        else:
            area,layout=result
            if case=='small_area':
                # Do not upsize an infeasible stress case to manufacture success.
                area=40;test_t=(area/1.33/n*n,h7,n);area,layout,errors=layout_for(test_t)
                if errors:layout=None
            d['whole_dwelling_building_area_design_m2']=area;d['household_modeled_net_area_design_m2']=round(area/1.33,6);d['layout']=layout
            if layout:
                layout['status']='unbound_parametric_design';layout['source_exterior_normal_direction_counts']=None
                layout['exterior_mapping']='four_face_prospective_design_not_observed_source'
        # Remove conflicting historical area/binding assertions in derived cases.
        for k in ['physical_whole_dwelling_building_area_m2','whole_dwelling_modeled_net_floor_area_m2','whole_dwelling_area_evidence','physical_binding']:
            if k in d:d[k]=None
        d['binding_status']='diagnostic_unbound';d['area_evidence']='experimental_1.33_conversion_of_unweighted_CHNS_current_usable_area; 999_unknown'
        if case=='small_area':d['area_evidence']='explicit_40m2_stress_input_not_selected_source_area'
        p['housing_source_tuple']={'L16_raw':t[0],'L17_raw':t[1],'residents':t[2],'frequency':w,'L16_semantics_resolved':t[0]!=999} if t else None
        housing.append({'case':case,'role_id':p['role_id'],'fixed_H7':h7,'selected_H7':d['room_count_design_minimum'],'prior_diagnostic_selected_H7':prior_selected_H7,
            'source_households_before':sum(pool.values()),'source_households_admitted_known_or_unknown':support,'unknown_999_admitted_weight':sum(w for t,w,l in eligible if t[0]==999),
            'rejected_household_weight':dict(rejected),'before_mean_L16':sum(t[0]*w for t,w in pool.items())/sum(pool.values()),
            'after_mean_L16_known':sum(t[0]*w for t,w,l in eligible if t[0]!=999)/sum(w for t,w,l in eligible if t[0]!=999) if any(t[0]!=999 for t,w,l in eligible) else None,
            'row_frequency_preserved':True,'area_selected':d['whole_dwelling_building_area_design_m2'],
            'raw999_numeric_sensitivity_mean_L16':sum(t[0]*w for t,w,l in eligible)/support if support else None,
            '999_exclusion_is_sensitivity_only':True,'boundary_area_override':40 if case=='small_area' else None,
            '999_forced_raw_boundary_outside_admission_if_needed':case=='unknown_999'})
        A=generate(p,case);B=select_B(p,A);errors=profile_errors(p)
        if d['layout'] is None:errors.append('layout_missing_or_infeasible_or_unknown')
        rp=out/'cases'/p['role_id'];write(rp/'profile.json',p);write(rp/'A.json',A);write(rp/'B.json',B)
        after.append(p);summaries.append({'case':case,'role_id':p['role_id'],'profile_errors':sorted(set(errors)),
            'A_tasks':len(A['tasks']),'A_scheduled':sum(t['start_abs_min'] is not None for t in A['tasks']),
            'A_unresolved':len(A['unresolved']),'A_constraint_errors':len(A['scheduled_task_errors']),
            'B_rounds':len(B['rounds']),'B_shortfall':B['round_shortfall'],'physical_ready':0,'collectable':0})
        role_manifest.append({'role_id':p['role_id'],'files':{x.name:sha(x) for x in rp.iterdir()}})
    batch_id='R2_20260930_'+out.name.upper()
    write(out/'SELECTION_BIAS.json',{'batch':batch_id,'scope':'purposive boundaries; not national 13-household quota',
        'before':metrics(before),'after':metrics(after),'qualified_profile_subset':metrics([p for p,s in zip(after,summaries) if not s['profile_errors']]),
        'marginal_residuals_all_cases':{k:0 for k in ['size','generation','elder_household_count','province','H7']},
        'housing':housing,'fixed_H7_never_reassigned':True,'prior_diagnostic700':read(ROOT/'candidate_v2/COVERAGE.json'),
        'old300_common_profile_check_errors':hist(e for c in old_checks for e in c['same_profile_check_errors']),
        'whole_regeneration_not_performed':True,'population_target_residual':'not defined for purposive boundary sample'})
    write(out/'SUMMARY.json',{'batch_id':batch_id,'case_count':len(cases),'old300_lossless_mapped':len(old),
        'source_ready_B_rounds_diagnostic_only':sum(s['B_rounds'] for s in summaries),'cases_reaching10':sum(s['B_rounds']==10 for s in summaries),
        'physical_ready':0,'human_answers':0,'collectable':0,'days_per_case':14,'cases':summaries,
        'wall_seconds':round(time.monotonic()-start,3),'not_connected':['full_year_behavior','C_IDF_EPW','thermal_cooling_and_water','questionnaire_backend','uncertainty_split'],
        'release':False})
    write(out/'MANIFEST.json',{'batch_id':batch_id,'seed':20260930,'input_lock_sha256':sha(ROOT/'INPUT_LOCK.json'),
        'code':{x.name:sha(x) for x in HERE.glob('*.py')},'cases':role_manifest,'files':{x.name:sha(x) for x in out.iterdir() if x.is_file()},
        'mapped_old300':{x.name:sha(x) for x in (out/'mapped_old300').glob('*.json')},'collection_release':False})
    print(read(out/'SUMMARY.json'))

if __name__=='__main__':
    ap=argparse.ArgumentParser();ap.add_argument('--output',type=Path,required=True);a=ap.parse_args();main(a.output)
