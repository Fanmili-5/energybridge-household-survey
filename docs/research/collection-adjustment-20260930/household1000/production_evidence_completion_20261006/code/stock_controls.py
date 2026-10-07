"""Use official2020 city ordinary-housing long-form controls, not library counts.
Households are the denominator, not dwellings, floor area or population.
Three couplings preserve identical province margins while varying unidentified
correlations. Long-form proportions are calibrated auxiliary targets; sample
counts are not multiplied by10 into observed population counts.
"""
import collections,hashlib,json,math,shutil
from pathlib import Path
import numpy as np,pandas as pd
from scipy.optimize import linprog
OUT=Path(__file__).resolve().parent.parent;BASE=OUT.parent
def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def read(p):return json.loads(Path(p).read_text())
def save(name,d):(OUT/name).write_text(json.dumps(d,ensure_ascii=False,indent=2,allow_nan=False)+'\n')
def clean(x):return ''.join(str(x).split())
def apportion(n,p):
    desired=np.array(p)*n;counts=np.floor(desired).astype(int)
    for j in sorted(range(len(p)),key=lambda j:(-(desired[j]-counts[j]),j))[:n-int(counts.sum())]:counts[j]+=1
    return counts
def main():
    if (OUT/'PACKAGE_MANIFEST.json').exists():raise SystemExit('sealed')
    sources={};tables={}
    for key in ['B0901a','B0902a','B0903a','B0904a','B0906a']:
        path=OUT/'raw'/(key+'.xls')
        if not path.exists():shutil.copyfile(BASE/'evidence_contract_20261001/raw'/(key+'.xls'),path)
        data=pd.read_excel(path,header=None).fillna('');rows={clean(r[0]):list(r) for r in data.values.tolist() if isinstance(r[1],(float,int)) and r[1]>0}
        assert '城市' in data.iloc[0,0] and len(rows)==32
        sources[key]={'URL':'https://www.stats.gov.cn/sj/pcsj/rkpc/7rp/zk/html/'+key+'.xls','sha256':sha(path),'title':data.iloc[0,0],
          'original_path':str(path),'sheet_shape':list(data.shape),'original_national_row':rows['全国'],'header_rows':data.iloc[3:6].values.tolist()};tables[key]=rows
    pp=read(BASE/'idf_joint_production_20261005/HOUSEHOLDS1000_JOINT_GEOMETRY_CANDIDATE.json')['profiles'];byprovince=collections.defaultdict(list)
    for p in pp:byprovince[p['province']].append(p)
    features={'building_storeys':(['one_storey','2_to7','8_to33','34plus'],'B0901a',list(range(2,6))),
      'load_bearing_structure':(['steel_RC','mixed','brick_wood','bamboo_adobe','other'],'B0901a',list(range(6,11))),
      'effective_building_epoch':(['pre1949','1949_1959','1960_1969','1970_1979','1980_1989','1990_1999','2000_2009','2010_2014','2015_2020'],'B0902a',list(range(4,31,3))),
      'elevator':(['present','absent'],'B0903a',[2,3]),'main_cooking_fuel':(['gas','electricity','coal','firewood','other'],'B0903a',list(range(4,9))),
      'piped_water':(['present','absent'],'B0903a',[9,10]),'kitchen':(['exclusive','shared','none'],'B0903a',[11,12,13]),
      'toilet':(['flush_sanitary','flush_nonsanitary','sanitary_dry','ordinary_dry','none'],'B0903a',list(range(14,19))),
      'bathing_hot_water':(['central','self_installed_heater','other','none'],'B0903a',list(range(19,23))),
      'housing_source':(['rent_social','rent_other','purchase_new','purchase_used','purchase_public','purchase_policy','selfbuild','inherit_gift','other'],'B0904a',list(range(2,11)))}
    controls=[];assignments={mode:{} for mode in ['hash_reference','area_sorted_positive','area_sorted_negative']};population=np.array([p['relative_population_weight'] for p in pp]);nationalerrors={}
    # Controlled transportation rounding preserves each province total and
    # the national category totals, including rare categories lost when every
    # province is independently rounded. Every cell remains floor/ceil.
    balanced={};provinces=sorted(byprovince)
    for name,(labels,key,cols) in features.items():
        expected=np.array([[len(byprovince[prov])*tables[key][prov][j]/tables[key][prov][1] for j in cols] for prov in provinces]);floor=np.floor(expected).astype(int)
        rowneed=np.array([len(byprovince[prov]) for prov in provinces])-floor.sum(1);colneed=apportion(1000,expected.sum(0)/1000)-floor.sum(0)
        variables=[(i,j) for i in range(len(provinces)) for j in range(len(labels)) if expected[i,j]-floor[i,j]>1e-10]
        a=np.zeros((len(provinces)+len(labels),len(variables)))
        for k,(i,j) in enumerate(variables):a[i,k]=1;a[len(provinces)+j,k]=1
        res=linprog([-float(expected[i,j]-floor[i,j]) for i,j in variables],A_eq=a,b_eq=np.r_[rowneed,colneed],bounds=(0,1),method='highs');assert res.success,res.message
        integer=floor.copy()
        for (i,j),v in zip(variables,res.x):assert abs(v-round(v))<1e-7;integer[i,j]+=round(v)
        assert np.all(integer.sum(1)==np.array([len(byprovince[prov]) for prov in provinces]))
        balanced[name]={prov:integer[i] for i,prov in enumerate(provinces)}
    for prov,pool in sorted(byprovince.items()):
        total=tables['B0901a'][prov][1]
        assert all(tables[k][prov][1]==total for k in ['B0902a','B0903a','B0904a'])
        for name,(labels,key,columns) in features.items():
            values=np.array([tables[key][prov][j] for j in columns],dtype=int);assert values.sum()==total,(prov,name)
            probabilities=values/total;counts=balanced[name][prov];categories=[label for label,n in zip(labels,counts) for _ in range(int(n))]
            controls.append({'province':prov,'feature':name,'source_long_form_ordinary_city_households':int(total),'source_category_counts':dict(zip(labels,map(int,values))),
              'source_proportions':dict(zip(labels,map(float,probabilities))),'target1000_province_count':len(pool),'integer_reference_counts':dict(zip(labels,map(int,counts))),
              'maximum_absolute_province_proportion_integerization_error':float(np.max(abs(counts/len(pool)-probabilities))),
              'source_row_excel1based':next(i+1 for i,r in enumerate(pd.read_excel(OUT/'raw'/(key+'.xls'),header=None).values) if clean(r[0])==prov)})
            for mode in assignments:
                if mode=='hash_reference':ordered=sorted(pool,key=lambda p:hashlib.sha256((name+'|'+p['slot_id']+'|EB_STOCK_20261006').encode()).hexdigest())
                else:ordered=sorted(pool,key=lambda p:(p['housing']['H6_census_building_area_design_m2'],p['slot_id']),reverse=mode=='area_sorted_negative')
                for p,label in zip(ordered,categories):assignments[mode].setdefault(p['slot_id'],{})[name]=label
    scenarios=[]
    for mode,mapping in assignments.items():
        rows=[]
        for p in pp:
            record={'household_id':p['slot_id'],'province':p['province'],'official_marginal_calibrated_reference_assignments':mapping[p['slot_id']],
              'stock_attributes_observed_for_this_household':False,'same_city_marginals_not_observed_household_joint':True,
              'building_year_implies_efficiency_code_compliance':False,'building_storey_count_is_not_household_floor_number':True,
              'macro_structure_is_not_detailed_layer_material_identity':True,'elevator_joint_with_storeys_not_observed':True}
            rows.append(record)
        scenarios.append({'scenario_id':mode,'households':rows,'source_proportions_identical_across_couplings':True,
          'extreme_sorting_is_stress_scenario_not_national_observed_correlation':mode!='hash_reference',
          'hash_assignment_is_finite_reference_coupling_not_maximum_entropy_optimization':mode=='hash_reference'})
    totals={}
    for name,(labels,key,cols) in features.items():
        actual=collections.Counter(assignments['hash_reference'][p['slot_id']][name] for p in pp)
        estimated=np.array([sum(p['relative_population_weight'] for p in pp if assignments['hash_reference'][p['slot_id']][name]==label) for label in labels]);estimated/=estimated.sum()
        # Poststratify province proportions to the fixed ordinary-city frame.
        expected=sum(sum(p['relative_population_weight'] for p in pool)*np.array([tables[key][prov][j] for j in cols])/tables[key][prov][1] for prov,pool in byprovince.items());expected/=expected.sum()
        totals[name]={'reference1000_counts':dict(actual),'population_poststratified_long_form_proportions':dict(zip(labels,map(float,expected))),
          'reference_population_weighted_proportions':dict(zip(labels,map(float,estimated))),
          'max_abs_national_reference_proportion_error':float(np.max(abs(estimated-expected)))}
    bridge=[]
    for prov in sorted(byprovince):
        h=next(c for c in controls if c['province']==prov);a=tables['B0902a'][prov];bridge.append({'province':prov,'long_ordinary_hh':a[1],
          'mean_rooms':a[2]/a[1],'mean_building_area_m2':a[3]/a[1],
          'epoch_conditional_means':[{'epoch':label,'households':a[c],'mean_rooms':a[c+1]/a[c] if a[c] else None,'mean_building_area_m2':a[c+2]/a[c] if a[c] else None} for label,c in zip(features['effective_building_epoch'][0],range(4,31,3))],
          'whole_short_form_controls_not_replaced_by_long_form_counts_or_means':True})
    save('OFFICIAL_STOCK_SOURCE_REGISTER.json',{'sources':sources,'long_form10percent_sample_not_complete_count':True,'H5_scope_verified_in_census_scheme':'ordinary H5=1 proceeds throughH8-H17;2-5 skiptoindividualitems','stock_count_is_household_not_building_count':True})
    save('STOCK_CONTROLS.json',{'controls':controls,'national':totals,'source_long_form_total':tables['B0901a']['全国'][1],
      'ordinary_short_form_target_preserved':True,'unobserved_joint_not_identified_by_raking':True,'calibration_is_province_poststratified_auxiliary_estimate_not_raw_microdata':True})
    save('STOCK_SCENARIOS1000.json',{'scenarios':scenarios,'reference_households_per_scenario':1000,'unknown_correlations_varied_not_silently_identified':True,
      'not_yet_complete_IDF_bindings_or_actor_packages':True})
    save('LONG_SHORT_FORM_MOMENT_BRIDGE.json',{'provinces':bridge,'long_form_variation_retained_not_rescaled_to_claim_full_count_identity':True})
    print(json.dumps({'controls':len(controls),'scenarios':3,'households_each':1000,'national_reference_counts':{k:v['reference1000_counts'] for k,v in totals.items()},'worst_national_marginal_error':max(v['max_abs_national_reference_proportion_error'] for v in totals.values())},ensure_ascii=False,indent=2))
if __name__=='__main__':main()
