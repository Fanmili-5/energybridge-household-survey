#!/usr/bin/env python3
"""Create a strict version-bound physical attachment without rewriting facts."""
import argparse
import hashlib
import json
from collections import Counter
from pathlib import Path


def sha(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()
def digest(value):return hashlib.sha256(json.dumps(value,sort_keys=True,ensure_ascii=False,separators=(',',':'),allow_nan=False).encode()).hexdigest()


def build(facts_path,static):
    bundle=json.loads(facts_path.read_text());roles={r['slot_id']:r for r in bundle['roles']}
    if sha(bundle['profiles_path'])!=bundle['profiles_sha256']:
        raise ValueError('fact_bundle_profile_bytes_changed')
    profile=json.loads(Path(bundle['profiles_path']).read_text())
    if any(r['profile_version']!=profile['generation_model']['version'] for r in roles.values()):
        raise ValueError('fact_bundle_profile_version_changed')
    inputs=json.loads((static/'EXPERIMENT_INPUTS.json').read_text())
    records=json.loads((static/'SUMMARY.json').read_text())['records']
    cases={r['case_id']:r for r in records};by_slot={i['population_slot_id']:i for i in inputs}
    if not(len(bundle['roles'])==len(records)==len(roles)==len(inputs)==len(cases)==len(by_slot)==1000 and set(roles)==set(by_slot)):
        raise ValueError('complete1000 unique role/input/status correspondence required')
    rows=[]
    for slot,role in roles.items():
        item=by_slot[slot];record=cases[item['case_id']];binding=item.get('generation_binding',{})
        if binding.get('profile_file_sha256')!=bundle['profiles_sha256']:
            raise ValueError('physical_profile_version_mismatch:'+slot)
        for section in ['family','housing']:
            expected=role[section+'_semantic_sha256']
            if digest(item[section])!=expected or digest(role['facts'][section])!=expected or binding.get(section+'_semantic_sha256')!=expected:
                raise ValueError('physical_role_fact_mismatch:'+section+':'+slot)
        folder=static/'cases'/record['case_folder'];status_path=folder/'STATUS.json'
        status=json.loads(status_path.read_text())
        if status!=record:raise ValueError('summary_status_mismatch:'+slot)
        if record.get('generation_binding_status')!='pass':raise ValueError('generation_binding_not_verified:'+slot)
        row={'slot_id':slot,'profile_version':role['profile_version'],
             'fact_bundle_row_sha256':digest(role),'family_sha256':role['family_semantic_sha256'],
             'housing_sha256':role['housing_semantic_sha256'],'case_id':item['case_id'],
             'static_shell_status':record['status'],'stage_reached':record['stage_reached'],
             'errors':record['errors'],'case_path':str(folder.resolve()),
             'status_sha256':sha(status_path),'input_sha256':sha(folder/'INPUT.json'),
             'functional_layout_status':record.get('functional_layout_status','not_validated'),
             'device_placement_status':record.get('device_placement_status','not_validated'),
             'annual_for_this_exact_version':'not_attached',
             'geometry_condition':item.get('geometry_condition'),
             'actual_residence_city':role['facts']['site'].get('city'),
             'engineering_site':item['site'],
             'population_dwelling_form_identified_by_condition':False,
             'operational_attachment':None,'actor_response_attachment':None,
             'questionnaire_collectable':False}
        if record['status']=='idf_ready':
            required=['building.idf','LAYOUT.json','ASSEMBLY_BINDING.json','WEATHER_MATCH.json',
                      'PROTOTYPE_MATCH.json','INDEPENDENT_GEOMETRY_CHECK.json','IDF_OBJECT_LINEAGE.json']
            row['physical_files_sha256']={name:sha(folder/name) for name in required}
            if row['physical_files_sha256']['building.idf']!=record['idf_sha256']:
                raise ValueError('IDF_byte_binding_mismatch:'+slot)
            if sha(record['weather_epw_path'])!=record['weather_epw_sha256']:
                raise ValueError('weather_byte_binding_mismatch:'+slot)
            geometry=json.loads((folder/'INDEPENDENT_GEOMETRY_CHECK.json').read_text())
            if geometry.get('status')!='pass' or geometry.get('errors')!=[] or geometry.get('idf_sha256')!=record['idf_sha256']:
                raise ValueError('geometry_readback_not_passed:'+slot)
            row.update(idf_sha256=record['idf_sha256'],source_group_id=record['prototype_source_group_id'],
                       weather_epw_sha256=record['weather_epw_sha256'])
        else:
            if (folder/'building.idf').exists():raise ValueError('refused_case_has_accepted_IDF:'+slot)
            row.update(idf_sha256=None,physical_files_sha256=None)
        rows.append(row)
    return {'schema':'eb.physical_attachment_index.v1','fact_bundle_path':str(facts_path.resolve()),
        'fact_bundle_sha256':sha(facts_path),'profile_file_sha256':bundle['profiles_sha256'],
        'static_path':str(static.resolve()),'static_summary_sha256':sha(static/'SUMMARY.json'),
        'denominator':1000,'static_states':dict(Counter(r['static_shell_status'] for r in rows)),
        'rows':rows,'facts_were_rewritten':False,'annual_results_from_other_versions_reused':False,
        'collection_release':False,'training_release':False}


def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--facts',type=Path,required=True)
    ap.add_argument('--static',type=Path,required=True)
    ap.add_argument('--output',type=Path,required=True)
    args=ap.parse_args()
    if args.output.exists():raise ValueError('new immutable output file required')
    index=build(args.facts,args.static)
    index['builder_sha256']=sha(__file__)
    args.output.write_text(json.dumps(index,ensure_ascii=False,indent=2)+'\n')
    print(json.dumps({'denominator':1000,'states':index['static_states'],'questionnaire_collectable':0}))


if __name__=='__main__':main()
