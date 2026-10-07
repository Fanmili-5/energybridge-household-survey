#!/usr/bin/env python3
"""Build field bindings and the 11-step contract; no microdata access."""
import json
from pathlib import Path
from inspect_package import HERE, sha, write

def main():
    manifest=json.loads((HERE/'PACKAGE_MANIFEST.json').read_text())
    qc=json.loads((HERE/'CHFS_SOURCE_QC.json').read_text())
    meta={k:json.loads(next((HERE/'private_metadata').glob(f'chfs2021_{k}_pub*_metadata.json')).read_text())['variable_labels']
          for k in ['hh','ind','master_hh','master_ind']}
    def bind(kind,names):
        assert all(n in meta[kind] for n in names),(kind,names)
        return {'table':kind,'fields':[{'name':n,'actual_label':meta[kind][n]} for n in names]}
    def field(key,bindings,pages,meaning,rule,unknown):
        return {'group_id':key,'bindings':bindings,'document_pages_1based':pages,
                'measured_or_source_derived_meaning':meaning,'generation_rule':rule,'unresolved':unknown}
    fields=[
      field('city_scope',[bind('master_hh',['category','rural','istowns','istracking','prov','prov_code'])],
            {'usage':[5,6]},'111/112 city;121/122/123 town;210/220 rural',
            'Use category 111/112 only, keep unknown category out; describe published regional classification, not confirmed current city',
            ['category update after migration','istowns definition and its 768 city-classified positives']),
      field('family_weight_and_join',[bind('master_hh',['hhid','wgt_hh']),bind('master_ind',['hhid','pline','pline_order','wgt_ind','hhead'])],
            {'usage':[4,5,15,16]},'one household row for household totals; hhid+pline for member joins; pline_order is questionnaire list position',
            'Household statistics use actual field wgt_hh once per household; do not sum duplicated household totals on member rows',
            ['current package does not supply all phase/stratum design variables for design-based precision estimates']),
      field('time_reference',[bind('master_hh',['interviewtime','interviewtype']),bind('ind',['a2005'])],
            {'usage':[6,12],'questionnaire2021':[27,63,64,107,159,168],'questionnaire2022':[10,14,27,63,64,106,158,167]},
            '2021 wave; visits 2021/2022; specified financial flows refer to2020; 2022 housing/durables questions often July2021',
            'Retain wave, visit year and field-specific reference time separately; age is visit-year difference, not an observed exact birthdate age',
            ['not all questions time-audited','interviewyear-to-questionnaire mapping lacks a supplied explicit version field']),
      field('economic_and_residential_members',[bind('hh',['a2000']),bind('ind',['a2000c','a2001','a2003','a2005','a2024'])],
            {'usage':[5,6],'questionnaire2021':[11,12,13,14,16],'questionnaire2022':[11,12,13,14,16]},
            'economic family may include nonresidents; co-residence1/2 includes temporary absence<=3months; relations relative to respondent',
            'Do not equate roster count or co-resident count to census size; preserve nonresident economic members in financial provenance',
            ['census usual-residence bridge','generation mapping','full family graph','within-year age and relationship plausibility']),
      field('financial_totals',[bind('master_hh',['total_income','total_consump','total_asset','total_debt','hhwage_inc','agri_inc','busi_inc','prop_inc','transfer_inc'])],
            {'usage':[9,10,11,12,13,14,15],'calculation_workbook':['2021收入!A1:K129','2021消费!A1:K55','2021资产!A1:K98','2021负债!A1:K65']},
            'source-derived family aggregates with original, imputed and censored monetary components; negative income can be losses; annualized consumption mixes verified2020 flows with current/July2021 rent multiplied by12',
            'Use annual household yuan; retain source-imputed/source-derived status; do not drop negatives or rewrite as current monthly salary',
            ['component-level imputation/censor sensitivity','formula-version conflicts','financial-economic-family versus residential-family membership']),
      field('housing_tenure_rent',[bind('hh',['c1001','c1002','c1011','c1013_2_mc'])],
            {'questionnaire2021':[63,64],'questionnaire2022':[63,64]},
            'owned by member/rented/free residence; monthly rent and included fees',
            'Respect branch skips and field reference date; rent is not automatically separate from or inclusive of utility costs',
            ['census tenure bridge','ordinary versus nonordinary residence classification']),
      field('nonowned_area',[bind('hh',['c1004','c1013a','c1000ak'])],
            {'questionnaire2021':[63,64],'questionnaire2022':[63,64]},
            'usable/exclusively occupied area under nonowned branch, housing age band and independent kitchen/toilet',
            'Owned branch missing is not zero; do not label usable area as observed building area',
            ['census H6/H7 bridge','room geometry and sleeping layout']),
      field('owned_property_slots',[bind('hh',[f'{stem}_{i}' for stem in ['c2000c','c2003','c2004','c2005aa1','c2005aa2','c2008b'] for i in range(1,7)])],
            {'questionnaire2021':[66,67,72,74,75],'questionnaire2022':[66,68,74,75]},
            'property-specific old usable/new building/new usable area, room/hall counts and self-use confirmation',
            'Identify the current dwelling explicitly before binding dimensions; first owned property is not automatically the residence',
            ['unique current-dwelling selector across new/old slots','co-occupation','room/hall-to-H7 count']),
      field('combined_durables',[bind('hh',['c8001ab','c8001ab_2_mc','c8001ab_5_mc','c8001ab_19_mc'])],
            {'questionnaire2021':[107],'questionnaire2022':[106],'calculation_workbook':['2021资产!H80:I82','2021资产!H89:I89']},
            'combined equipment-group ownership/value; workbook split category wording conflicts with questionnaire/current fields',
            'Do not infer individual washer/dryer/fridge/AC/heater/dishwasher ownership or count from group positivity',
            ['appliance-specific ownership','instances','model and input power','installation','control permission']),
      field('utility_bundle',[bind('hh',['g1005'])],
            {'questionnaire2021':[159],'questionnaire2022':[158]},
            'average monthly combined water/electricity/fuel/property/heating expenditure',
            'Do not relabel as electricity bill, tariff, kWh, or measured load',
            ['separate metering boundary and bill','tariff and electricity use']),
      field('work_and_commute',[bind('ind',['a3100a','a3116a','a3133','a3134'])],
            {'questionnaire2021':[26,32],'questionnaire2022':[26,32]},
            'employment, one-way commute, average work days per month and hours per day',
            'Use as conditional time-budget support after actual branch checks; start/end times and appliance operator remain designed',
            ['per-field branch/time audit','daily clock','care work','availability and permission']),
      field('car_boundary',[bind('hh',['c7002','c7052b'])],
            {'questionnaire2021':[104],'questionnaire2022':[103]},
            'household car count/value, not home EV charging',
            'No EV, home charger, charging access or permission inferred from car ownership',
            ['powertrain','home-charging installation/access/control']),
    ]
    # Bindings contain variable metadata only, never household values or keys.
    write(HERE/'FIELD_SOURCE_RULES.json',{'batch_id':qc['batch_id'],'groups':fields,
          'source_rule_precedence':'actual data field + questionnaire branch/time + explicit version conflicts; not formula-table label alone',
          'raw_values_or_ids_exported':0})
    specs=[
      (1,'city_population_slots',['census2020_city_counts'],'seven-census quotas; no towns/rural/collective households',
       '1000 slots retain province and national size-generation quotas; topcodes retained'),
      (2,'members_and_economic_structure',['economic_and_residential_members','financial_totals','family_weight_and_join'],
       'CHFS weighted same-economic-family relationships; census residence and generation bridge before synthesis',
       'No raw one-to-one source household recitation; validate roster, relationship, chronology and residence bridge'),
      (3,'housing_and_room_structure',['housing_tenure_rent','nonowned_area','owned_property_slots','census2020_city_housing','CRECS2012_room_area'],
       'lock H7; ordinary-residence conditional margins; select actual residence slot before area matching',
       'Area/sleep/H7/geometry coherent; record nonordinary coverage gap and template failures'),
      (4,'city_weather_building',['city_scope','verified_IDF_EPW_route'],
       'independently assign target simulated city/climate; never decode CHFS city pseudocode into actual geography',
       'Weather climate/location and geometry checked; match status not direct observation'),
      (5,'appliance_instances',['combined_durables','CRECS2012_energy_devices','manufacturer_parameters','car_boundary'],
       'historical conditional appliance matches; separate owned/installed/access/control/selection/model boundary',
       'Grouped ownership does not resolve each appliance; model/capacity/input-power semantics explicit'),
      (6,'daily_activity_budget',['work_and_commute','CRECS_frequency_duration','time_use2024_auxiliary'],
       'constrain activity totals then design clocks, operators and movable windows',
       'No age/job-to-clock deterministic shortcut; all design values labelled'),
      (7,'economic_context_and_attitudes',['financial_totals','housing_tenure_rent','utility_bundle','time_reference'],
       'use stated historical financial conditions; attitude is independent experimental design',
       'Annual household flows not current wage; utilities bundle not electricity; no copied exact source household finances'),
      (8,'annual_A',['fixed_profile_assets_schedule','existing_annual_A_pipeline'],
       'generate demanded tasks with actor, materials, prerequisites and state recursion',
       'Preserve unmet demand; no device/task fabrication to create intervention opportunities'),
      (9,'ten_B_scenarios',['same_household_A_state','existing_B_pipeline'],
       'select ten legitimate situations using that household existing tasks',
       'Fixed household/assets/A; seasonal/topic coverage checked without rich-household selection bias'),
      (10,'physics_and_services',['versioned_weather_models_state','existing_physics_pipeline'],
       'same initial states and boundaries for A/B physics',
       'Energy plus temperature/hot-water/laundry/mobility service checks; runtime success not calibration'),
      (11,'human_actor_package',['verified_profile_A_B_service_results','structured_frontend_projection'],
       'faithful role card and ten scenarios only after prior gates',
       'One fixed household per actor; no source microdata/IDs; human answer fields empty until collection'),
    ]
    steps=[{'step':n,'name':name,'support':support,'generation_rule':rule,'acceptance':gate,'execution_status':'not_executed_in_this_source_admission'}
           for n,name,support,rule,gate in specs]
    contract={'batch_id':qc['batch_id'],'target':'1000 fixed China-city family roles x10 human scenarios; uniform regeneration',
       'population_reference_year':2020,'field_reference_times_separate':True,'exclusions':['town','rural','collective_households','known_under20_singletons'],
       'steps':steps,'field_rules':'FIELD_SOURCE_RULES.json',
       'prior_authority':'../evidence_contract_20261001/CITY_AUTHORITY_CONSTRAINTS_V2.json',
       'population_slots':'../evidence_contract_20261001/POPULATION_ALLOCATION_CANDIDATE_V2.json',
       'CRECS_rules':'../crecs_admission_20261003/FIELD_SOURCE_RULES.json',
       'CRECS_parameter_interpretation':'../crecs_admission_20261003/PARAMETER_INTERPRETATION.json',
       'pilot_gate':'../crecs_admission_20261003/PILOT_ACCEPTANCE.json',
       'next_executable_work':['census-residence/generation/property bridge','source-imputation and sparse-cell sensitivity','conditional synthetic model','bounded end-to-end pilot'],
       'source_rows_are_not_roles':True,'collection_release':False,'training_release':False}
    write(HERE/'GENERATION_SOURCE_CONTRACT.json',contract)
    sources=[]
    for e in manifest['entries']:
        sources.append({'source_id':e['package_relative_path'],'kind':'local_user_download','local_path':e['original_local_path'],
                        'sha256':e['sha256'],'bytes':e['bytes'],'provenance':e['provenance'],
                        'use':'local aggregate QC / document semantics; microdata not republished'})
    for n,url in [('CHFS_2026_release.html','https://chfs.swufe.edu.cn/info/1041/4171.htm'),
                  ('CHFS_application.html','https://chfs.swufe.edu.cn/sjzx/sjsq.htm'),
                  ('CHFS_use_terms.html','https://chfs.swufe.edu.cn/info/1041/2131.htm')]:
        path=HERE.parent/'evidence_contract_20261001/raw'/n
        sources.append({'source_id':n,'kind':'official_public_document','url':url,'local_path':str(path),
                        'sha256':sha(path),'bytes':path.stat().st_size})
    sources.append({'source_id':'CHFS2021_first_release','kind':'official_public_document',
                    'url':'https://chfs.swufe.edu.cn/info/1041/4051.htm','access':'independent agent full-page review; see DOCUMENT_REVIEW.md','local_bytes_cached':False})
    for n in ['CITY_AUTHORITY_CONSTRAINTS_V2.json','POPULATION_ALLOCATION_CANDIDATE_V2.json']:
        path=HERE.parent/'evidence_contract_20261001'/n
        sources.append({'source_id':n,'kind':'previous_verified_derived_artifact','local_path':str(path),'sha256':sha(path)})
    write(HERE/'SOURCE_LEDGER.json',{'batch_id':qc['batch_id'],'entries':sources,
        'source_manifest':'PACKAGE_MANIFEST.json','field_links':'FIELD_SOURCE_RULES.json','local_byte_hash_is_not_official_origin_authentication':True})
    write(HERE/'ADMISSION_STATUS.json',{'batch_id':qc['batch_id'],'stage':'CHFS local source admission and updated generation contract',
        'source_city_classified_rows':qc['scope']['city_records'],'source_joint_rule_rows':qc['member_semantics']['joint_member_income_consump_rule_n'],
        'source_family_weights_checked':True,'new_complete_roles':0,'new_A_days':0,'new_B_rounds':0,'new_physics_results':0,'human_answers':0,
        'remaining':['residence/member/generation bridge','property selector/H7 bridge','imputation sensitivity','sparse source support','fine appliance support','physics/service checks','actor package'],
        'collection_release':False,'training_release':False,'methodology_review':'DOCUMENT_REVIEW.md',
        'script_sha256':sha(Path(__file__))})
    print(json.dumps({'field_groups':len(fields),'steps':len(steps),'source_entries':len(sources),'release':False}))

if __name__=='__main__':main()
