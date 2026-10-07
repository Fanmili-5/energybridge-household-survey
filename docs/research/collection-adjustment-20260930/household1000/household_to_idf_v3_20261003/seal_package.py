#!/usr/bin/env python3
"""Seal two distinct input cohorts; never transfer annual evidence between them."""
import hashlib,json
from pathlib import Path

HERE=Path(__file__).resolve().parent
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def track(name,annual=None):
    folder=HERE/name;summary=json.loads((folder/'SUMMARY.json').read_text());inputs=json.loads((folder/'EXPERIMENT_INPUTS.json').read_text())
    sources=sorted({(x.get('generation_binding',{}).get('profile_file_path'),x.get('generation_binding',{}).get('profile_file_sha256')) for x in inputs if x.get('generation_binding')})
    locked=[]
    for path,expected in sources:
        if not path or sha(Path(path))!=expected:raise RuntimeError('actual profile source hash mismatch')
        locked.append({'path':path,'sha256':expected})
    return {'batch_path':str(folder),'batch_summary_sha256':sha(folder/'SUMMARY.json'),'input_lock_sha256':sha(folder/'INPUT_LOCK.json'),'generated_profile_sources':locked,'cases':summary['case_count'],'conditional_thermal_shells':summary['IDF_ready'],'blocked':summary['blocked'],'actual_household_geography_certified':False,'functional_layout_status':'not_validated','device_placement_status':'not_validated','collectable':False,'annual_evidence_path':str(HERE/annual) if annual else None,'annual_evidence_scope':'seven controlled capability witnesses from this original profile only; not all1000 or other cohort' if annual else 'no annual run claimed for this input cohort','annual_runs_for_full_cohort':summary['actual_EP_annual_runs']}
def main():
    if (HERE/'PACKAGE_MANIFEST.json').exists():raise RuntimeError('package already sealed; use explicit later revision')
    current={'schema':'eb.household_to_idf.v3.current','tracks':{'frozen_v2_family_housing_inputs':track('frozen_v2_context_comparison_v1','capability_annual_v1'),'revised_generated_family_housing_under_independent_shape_conditions':track('revised_generation_contexts_v2')},'historical_intermediate_tracks':{'generation_before_global_area_endpoint_support_repair':{'status':'pre_repair_historical_not_final_recommended_generation',**track('revised_generation_contexts_v1')}},'scope':'conditional thermal-shell compiler policy revision; population profiles, functional validity and household load remain distinct','code_frozen':True,'frozen_V2_or_GEN_modified':False,'no_reuse_of_old_annual_as_new_profile_validation':True,'actual_household_city_IDFs':0,'complete_actor_roles':0,'empirical_calibration':False,'collection_release':False,'training_release':False}
    (HERE/'CURRENT.json').write_text(json.dumps(current,ensure_ascii=False,indent=2)+'\n')
    files={str(p.relative_to(HERE)):sha(p) for p in sorted(HERE.rglob('*')) if p.is_file() and p.name!='PACKAGE_MANIFEST.json' and '__pycache__' not in p.parts}
    manifest={'schema':'eb.household_to_idf.v3.package_manifest','files':files,'self_excluded':True,'transient_python_caches_excluded':True,'CURRENT_sha256':sha(HERE/'CURRENT.json'),'scope':'exact V3 artifacts only; actual external profile/resource locks retained in each experiment','code_frozen':True,'collection_release':False,'training_release':False}
    (HERE/'PACKAGE_MANIFEST.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2)+'\n');print(json.dumps({'files':len(files),'manifest_sha256':sha(HERE/'PACKAGE_MANIFEST.json'),'CURRENT_sha256':sha(HERE/'CURRENT.json')}))

if __name__=='__main__':main()
