#!/usr/bin/env python3
"""Audit same-record family/housing/service references without donor exports."""
import argparse
import collections
import hashlib
import json
import shutil
from pathlib import Path
import pandas as pd
from source_semantics import normalize,inventory_signature,contains

HERE=Path(__file__).resolve().parent
H1000=HERE.parent
CRECS=H1000/'crecs_admission_20261003'
def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def save(p,d):p.write_text(json.dumps(d,ensure_ascii=False,indent=2,allow_nan=False)+'\n')
def freq(xs,key):return dict(collections.Counter(str(x[key]) for x in xs))

def summarize(records):
    return {'records':len(records),'G_proxy_known':sum(x['G_proxy'] is not None for x in records),
        'by_N':freq(records,'N'),'by_ownership':freq(records,'ownership_scope'),
        'interior_levels_category':freq(records,'interior_levels_category'),
        'positive_service_report_households':{k:sum(any(r['family']==k for r in x['service_reports']) for x in records)
            for k in ['refrigerator','washer','drying_service','hot_water_service','cooling_service']},
        'not_population_ownership_rates':True}

def main():
    ap=argparse.ArgumentParser();ap.add_argument('--profiles',type=Path,required=True)
    ap.add_argument('--output',type=Path,required=True);args=ap.parse_args()
    if args.output.exists():raise ValueError('new_immutable_reference_directory_required')
    args.output.mkdir(parents=True)
    (args.output/'code').mkdir()
    for name in ['source_semantics.py','build_joint_references.py']:
        shutil.copy2(HERE/name,args.output/'code'/name)
    data_path=CRECS/'private_raw/CRECS2012.dta'
    raw=pd.read_stata(data_path,convert_categoricals=False)
    metadata=json.loads((CRECS/'private_metadata/CRECS2012_stata_metadata.json').read_text())
    expected=[*[f'a2_{i}_{s}' for i in range(1,9) for s in ['a','b','c']],
        *[f'b15_ws_{i}a' for i in range(1,6)],*[f'c2_dbx_{i}b' for i in range(1,4)],
        *[f'd4_{i}a' for i in range(1,6)],*[f'd6_{i}a' for i in range(1,6)]]
    missing=set(expected)-set(metadata['variable_labels'])
    if missing:raise ValueError('source_schema_missing:'+','.join(sorted(missing)))
    city=[normalize(r) for r in raw[(raw.valid==1)&(raw.b1==1)].to_dict('records')]
    member=[r for r in city if r['member_reference_admitted']]
    usable=[r for r in member if r['gross_area_interval'] and r['usable_area_interval'] and not r['impossible_area_interval_order']]
    joint=[r for r in usable if r['G_proxy'] is not None]
    body=json.loads(args.profiles.read_text());profiles=body['profiles']
    if len(profiles)!=1000 or len({p['slot_id'] for p in profiles})!=1000:raise ValueError('complete_fixed1000_required')
    supports=[]
    for p in profiles:
        n=p['family']['resident_count'];g=p['family']['generation_count_design'];h=p['housing']
        area=h['H6_building_area_m2'];H7=h['H7_natural_rooms_exact']
        # This is a reference-coverage audit, not a source admission to target.
        # Membership/housing dates and natural-room meanings remain proxies.
        NG=[r for r in joint if r['N']==n and r['G_proxy']==g]
        NGA=[r for r in NG if contains(r['gross_area_interval'],area)] if area is not None else []
        compact=[r for r in NGA if H7 is not None and r['rooms_positive_reports']['ws']<=H7]
        singlelevel=[r for r in compact if r['interior_levels_category']==1]
        supports.append({'slot_id':p['slot_id'],'N':n,'G':g,'ordinary':h['H5_is_ordinary_model_assigned'],
            'target_area_scope':h['occupancy_scope'],
            'whole_scope_reference_applicable':h['H5_is_ordinary_model_assigned'] and h['occupancy_scope']=='whole_household_private',
            'national_same_N_G_proxy_records':len(NG),'same_N_G_gross_interval_records':len(NGA),
            'reported_bedroom_lower_bound_compatible_records':len(compact),
            'same_context_plus_single_level_reference_records':len(singlelevel),
            'other_owned_same_N_G_area_records':sum(r['ownership_scope']=='other_owned_not_equivalent_to_rented' for r in NGA),
            'slot_retained':True,'devices_generated':False,'reference_does_not_observe_target_household':True})
    # Broad inventory support is summarized, never a rare whole-record donor.
    associations=[]
    for tenure in ['self_owned','other_owned_not_equivalent_to_rented','unknown']:
        for n in range(1,9):
            xs=[r for r in usable if r['ownership_scope']==tenure and r['N']==n]
            if not xs:continue
            sigs=[inventory_signature(r) for r in xs]
            associations.append({'ownership_scope':tenure,'N':n,'records':len(xs),
                'positive_report_counts':{k:sum(s[k]>0 for s in sigs) for k in sigs[0]},
                'washer_and_split_AC_positive_reports':sum(s['washer_reports']>0 and s['split_AC_reports']>0 for s in sigs),
                'combo_with_washer_report_identity_unlinked':sum(s['combo_service_reports']>0 and s['washer_reports']>0 for s in sigs),
                'unweighted_historical_auxiliary_only':True})
    qc={'schema':'eb.same_record_reference_audit.v1','year':2012,
        'source_stages':{k:summarize(v) for k,v in [('city_labeled',city),('roster_birth_single_age_checked',member),
            ('member_area_interval_checked',usable),('generation_proxy_known',joint)]},
        'invalid_type_codes':dict(collections.Counter(f"{e['field']}:{e['reason']}" for r in city for e in r['invalid_type_codes'])),
        'impossible_gross_usable_interval_order_city':sum(r['impossible_area_interval_order'] for r in city),
        'other_owned_label_does_not_identify_rent_free_or_shared':True,
        'no_population_weights_available':True,'room_reports_are_lower_bounds_not_exact_H7':True,
        'empty_service_slots_are_not_zero_ownership':True,
        'washer_combo_cross_table_hardware_identity_not_verified':True,
        'profiles_generated':0,'source_household_identifiers_exported':False,'source_rows_exported':False}
    save(args.output/'JOINT_SOURCE_AUDIT.json',qc)
    save(args.output/'HISTORICAL_SAME_RECORD_ASSOCIATIONS.json',{'schema':'eb.historical_appliance_joint_diagnostics.v1','groups':associations,
        'interpretation':'within-record reported co-occurrence only; no zero-ownership or target2020-rate inference'})
    save(args.output/'SLOT1000_REFERENCE_SUPPORT.json',{'schema':'eb.slot_joint_reference_support.v1','rows':supports,
        'summary':{'slots':1000,'same_N_G_proxy_zero':sum(r['national_same_N_G_proxy_records']==0 for r in supports),
            'same_N_G_gross_interval_zero':sum(r['same_N_G_gross_interval_records']==0 for r in supports),
            'same_context_single_level_zero':sum(r['same_context_plus_single_level_reference_records']==0 for r in supports)},
        'matches_are_not_target_population_equivalence':True,'unknown_target_city_not_filled':True})
    inputs=[data_path,CRECS/'private_raw/CRECS2012.pdf',CRECS/'private_metadata/CRECS2012_stata_metadata.json',
        CRECS/'FIELD_SOURCE_RULES.json',args.profiles.resolve()]
    save(args.output/'REFERENCE_LOCK.json',{'inputs':{str(p.resolve()):sha(p) for p in inputs},
        'code':{n:sha(args.output/'code'/n) for n in ['source_semantics.py','build_joint_references.py']},
        'outputs':{p.name:sha(p) for p in args.output.glob('*.json')},
        'reference_scope':'historical_city_labeled_same_record_auxiliary_only','formal_production_allowed':False})
    print(json.dumps({'source_joint_proxy_records':len(joint),'source_area_member_records':len(usable),
        'source_other_owned_records':sum(r['ownership_scope']=='other_owned_not_equivalent_to_rented' for r in usable),
        'source_signature':sha(data_path),'slots':1000},ensure_ascii=False))

if __name__=='__main__':main()
