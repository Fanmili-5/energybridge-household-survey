#!/usr/bin/env python3
"""Independent complete family/housing source-byte/slot/digest readback."""
import argparse,hashlib,json
from pathlib import Path

def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def digest(x):return hashlib.sha256(json.dumps(x,ensure_ascii=False,sort_keys=True,separators=(',',':'),allow_nan=False).encode()).hexdigest()
def main(run):
    summaries=json.loads((run/'SUMMARY.json').read_text());profiles={};results=[];global_errors=[]
    for r in summaries['records']:
        folder=run/'cases'/r['case_folder'];item=json.loads((folder/'INPUT.json').read_text());b=item.get('generation_binding');errors=[]
        if not isinstance(b,dict):errors.append('missing_generation_binding');results.append({'case_id':r['case_id'],'errors':errors});continue
        path=Path(b['profile_file_path']);actual=sha(path)
        if actual!=b['profile_file_sha256']:errors.append('source_file_hash_mismatch')
        key=(str(path),actual)
        if key not in profiles:
            raw=json.loads(path.read_text());index={p['slot_id']:p for p in raw['profiles']}
            if len(index)!=len(raw['profiles']):global_errors.append('duplicate_profile_slot')
            profiles[key]=index
        source=profiles[key].get(b['slot_id'])
        if source is None:errors.append('slot_not_found')
        else:
            for section in ['family','housing']:
                if item[section]!=source[section]:errors.append('full_'+section+'_semantics_changed')
                if digest(item[section])!=b[section+'_semantic_sha256'] or digest(source[section])!=b[section+'_semantic_sha256']:errors.append(section+'_bound_digest_mismatch')
        recorded=json.loads((folder/'GENERATION_BINDING_CHECK.json').read_text())
        if recorded.get('status')!='pass' or recorded.get('profile_file_sha256')!=actual:errors.append('recorded_generation_check_inconsistent')
        condition=json.loads((folder/'GEOMETRY_CONDITION_CHECK.json').read_text())
        facts={k:item['housing'].get(k) for k in ['dwelling_type','household_storeys','building_total_storeys_design']}
        if condition.get('housing_facts')!=facts or condition.get('housing_fact_signature')!=digest(facts):errors.append('raw_geometry_facts_signature_mismatch')
        if condition.get('condition')!=item.get('geometry_condition') or condition.get('condition_signature')!=digest(item.get('geometry_condition')):errors.append('separate_condition_signature_mismatch')
        if r['status']=='idf_ready':
            layout=json.loads((folder/'LAYOUT.json').read_text())
            if layout['gross_H6_m2']!=item['housing']['H6_building_area_m2'] or layout['H7_materialized_natural_rooms']!=item['housing']['H7_natural_rooms_exact']:errors.append('H6_H7_changed_by_compiler')
            assigned=[m for space in layout['spaces'] for m in space.get('member_ids_sleeping',[])]
            if sorted(assigned)!=sorted(item['family']['resident_member_ids']):errors.append('resident_sleep_attachment_changed')
            if layout.get('functional_layout_status')!='not_validated' or layout.get('device_placement_status')!='not_validated' or layout.get('collectable') is not False:errors.append('functional_claim_promoted')
        results.append({'case_id':r['case_id'],'slot_id':b['slot_id'],'status':r['status'],'source_profile_file_sha256':actual,'full_family_digest':digest(item['family']),'full_housing_digest':digest(item['housing']),'raw_dwelling_type':facts['dwelling_type'],'raw_household_storeys':facts['household_storeys'],'geometry_condition_signature':condition.get('condition_signature'),'errors':errors})
    if len(results)!=summaries['case_count']:global_errors.append('case_count_mismatch')
    out={'scope':'complete modeled source family/housing preservation and separate conditional geometry; not population/functional calibration','verifier_sha256':sha(Path(__file__)),'source_summary_sha256':sha(run/'SUMMARY.json'),'case_count':len(results),'passed_case_count':sum(not r['errors'] for r in results),'source_profiles':[{'path':p,'actual_sha256':h} for p,h in profiles],'global_errors':global_errors,'status':'pass' if not global_errors and all(not r['errors'] for r in results) else 'fail','microdata_read':False,'annual_evidence_borrowed':False,'results':results}
    (run/'INDEPENDENT_GENERATION_BINDING_CHECK.json').write_text(json.dumps(out,ensure_ascii=False,indent=2)+'\n');print(json.dumps({k:v for k,v in out.items() if k!='results'},ensure_ascii=False))

if __name__=='__main__':
    ap=argparse.ArgumentParser();ap.add_argument('--run',type=Path,required=True);args=ap.parse_args();main(args.run.resolve())
