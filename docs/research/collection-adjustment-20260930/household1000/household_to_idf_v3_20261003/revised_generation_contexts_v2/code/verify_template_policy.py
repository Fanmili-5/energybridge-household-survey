#!/usr/bin/env python3
"""Counterfactual policy probes in tmp; never mutate frozen profiles/resources."""
import argparse,copy,json,tempfile
from pathlib import Path
from household_model import (HERE,sha,digest,save,input_errors,make_layout,layout_checks,
                             effective_geometry,effective_boundary_policy,MODELED_H6_EVIDENCES,MODELED_H7_EVIDENCE)
from run_stage import build_one
from geometry_gate import inspect_idf,rows
from idf_builder import dump

V2=HERE.parent/'household_to_idf_v2_20261003'

def main(output):
    output=output.resolve()
    if output.exists():raise RuntimeError('use new probe output')
    output.mkdir(parents=True)
    tmp=Path(tempfile.mkdtemp(prefix='v3_policy_probe_',dir='/private/tmp'))
    source=V2/'population_contexts_v1/cases'
    checks=[]
    def check(name,ok,evidence):checks.append({'name':name,'passed':bool(ok),'evidence':evidence})
    def fixture(slot,label):
        x=json.loads((source/('context_'+slot)/'INPUT.json').read_text())
        x['case_id']=label;x.pop('generation_binding',None)
        x['housing'].update(H6_evidence='declared_design',H7_evidence='declared_design')
        return x
    studio=fixture('cityslot-0588','compact_small_studio')
    l,e=make_layout(studio,[])
    check('studio_no_invented_hall_or_corridor',not e and len(l['spaces'])==3 and not any(s['kind'] in ['hall_not_H7','circulation'] for s in l['spaces']),{'spaces':[s['name'] for s in l['spaces']]})
    check('functional_device_status_not_promoted',l['functional_layout_status']=='not_validated' and l['device_placement_status']=='not_validated' and l['collectable'] is False,l['legacy_capacity_diagnostic'])
    check('sleep_member_attachment_without_bed_claim',not layout_checks(studio,l) and not any(s.get('bed_footprints') for s in l['spaces']),{'layout_errors':layout_checks(studio,l)})
    bad=copy.deepcopy(l);bad['spaces'][0]['member_ids_sleeping']=[]
    check('missing_sleep_member_detected','sleep_members_not_exact_resident_partition' in layout_checks(studio,bad),layout_checks(studio,bad))
    bad=copy.deepcopy(l);bad['spaces'][0]['bed_footprints']=[{'member_id':studio['family']['resident_member_ids'][0],'rect_m':[0,1.2,.1,1.3]}]
    check('unexpected_furniture_not_implicitly_validated','unexpected_furniture_in_thermal_only_layout' in layout_checks(studio,bad),layout_checks(studio,bad))
    tiny=copy.deepcopy(studio);tiny['housing']['H6_building_area_m2']=.1
    layout,err=make_layout(tiny,[])
    check('still_refuse_unsupported_tiny_thermal_partition',layout is None and err==['compact_thermal_partition_support_limit_no_area_or_H7_repair'],err)
    for slot in ['cityslot-0448','cityslot-0653','cityslot-0782','cityslot-0799']:
        x=fixture(slot,'probe_'+slot);layout,err=make_layout(x,[])
        check('fixed_H6_H7_residents_'+slot,not err and not layout_checks(x,layout) and layout['H7_materialized_natural_rooms']==x['housing']['H7_natural_rooms_exact'] and abs(sum(s['floor_area_m2'] for s in layout['spaces'])-layout['net_proxy_m2'])<1e-6,{'errors':err,'natural_rooms':layout['H7_materialized_natural_rooms'] if layout else None,'residents':x['family']['resident_count'],'legacy':layout.get('legacy_capacity_diagnostic') if layout else None})
    condition={'kind':'conditional_engineering_design','dwelling_type':'apartment','household_storeys':1,'does_not_identify_population_type':True,'evidence_id':'counterfactual-policy-test','rationale':'explicit thermal shape while population type remains unknown'}
    x=copy.deepcopy(studio);x['housing'].update(dwelling_type=None,household_storeys=None);x['geometry_condition']=condition
    before=digest(x['housing']);errs=input_errors(x)
    check('unknown_shape_explicit_condition_preserves_facts',not errs and before==digest(x['housing']) and effective_geometry(x)['housing_facts']['dwelling_type'] is None,{'errors':errs,'geometry':effective_geometry(x)})
    bad=copy.deepcopy(x);bad.pop('geometry_condition')
    check('unknown_shape_without_condition_blocked','dwelling_type_unsupported' in input_errors(bad),input_errors(bad))
    bad=copy.deepcopy(x);bad['geometry_condition']['does_not_identify_population_type']=False
    check('condition_cannot_identify_population_type','geometry_condition_population_boundary_missing' in input_errors(bad),input_errors(bad))
    bad=copy.deepcopy(x);bad['geometry_condition'].pop('evidence_id')
    check('missing_condition_evidence_blocked','geometry_condition_evidence_id_missing' in input_errors(bad),input_errors(bad))
    bad=copy.deepcopy(x);bad['housing']['occupancy_scope']='shared_exclusive_model_assigned'
    check('condition_does_not_bypass_shared','shared_scope_not_resolved' in input_errors(bad),input_errors(bad))
    bad=copy.deepcopy(x);bad['housing']['H5_status']='nonordinary_model_assigned'
    check('condition_does_not_bypass_nonordinary','H5_not_ordinary_or_unresolved' in input_errors(bad),input_errors(bad))
    bad=copy.deepcopy(x);bad['housing']['household_storeys']=2
    check('known_household_multistorey_cannot_be_overridden','geometry_condition_conflicts_with_known_household_storeys' in input_errors(bad),input_errors(bad))
    for field,label in [('H6_evidence',v) for v in sorted(MODELED_H6_EVIDENCES)]+[('H7_evidence',v) for v in sorted(MODELED_H7_EVIDENCE)]:
        bad=copy.deepcopy(studio);bad['housing'][field]=label;errs=input_errors(bad)
        check('modeled_label_requires_actual_binding:'+label,any(e.startswith('generation_binding:') for e in errs),errs)
    # Synthetic local profile tests the real new-label/unknown-condition path.
    # Its evidence is explicitly a compiler counterfactual, never census data.
    modeled=copy.deepcopy(x);modeled['case_id']='new_labels_unknown_geometry_probe'
    modeled['housing'].update(H6_evidence='modeled_coarsened_CHFS_area_reference_with_ESS_hierarchical_shrinkage',H7_evidence='modeled_census_ordinary_conditional_integer_calibration_with_ESS_shrunk_CHFS_association_source_association')
    profile=output/'SYNTHETIC_COMPILER_PROBE_PROFILE.json'
    save(profile,{'scope':'synthetic compiler counterfactual only, not actual generated population','profiles':[{'slot_id':'probe-only','family':modeled['family'],'housing':modeled['housing']}]})
    modeled['generation_binding']={'profile_file_path':str(profile),'profile_file_sha256':sha(profile),'slot_id':'probe-only','family_semantic_sha256':digest(modeled['family']),'housing_semantic_sha256':digest(modeled['housing'])}
    errs=input_errors(modeled)
    check('new_modeled_labels_actual_file_slot_digest_binding',not errs,errs)
    bad=copy.deepcopy(modeled);bad['housing']['H6_building_area_m2']+=.01
    check('new_labels_do_not_bypass_full_housing_digest',any('generation_housing_semantic_hash_mismatch' in e for e in input_errors(bad)),input_errors(bad))
    admitted=build_one(modeled,tmp,{})
    check('actual_compile_unknown_population_shape_new_labels',admitted['status']=='idf_ready' and modeled['housing']['dwelling_type'] is None and admitted.get('collectable') is False,admitted)
    single=fixture('cityslot-0240','single_ground_roof');before=digest(single)
    check('single_known_total_one_uses_separate_effective_boundary',not input_errors(single) and effective_boundary_policy(single)['floor_position']=='single_storey' and digest(single)==before,{'raw_position':single['model_policy']['floor_position'],'effective':effective_boundary_policy(single)})
    bad=copy.deepcopy(single);bad['housing']['building_total_storeys_design']=4
    check('single_boundary_conflicts_known_multistorey','single_storey_boundary_conflicts_with_building_total_storeys' in input_errors(bad),input_errors(bad))
    bad=copy.deepcopy(single);bad['model_policy'].update(ground_temperature_method='explicit_research_boundary',ground_monthly_temperatures_C=[18]*11)
    check('malformed_ground_months_blocked','ground_boundary_unresolved' in input_errors(bad),input_errors(bad))
    bad=copy.deepcopy(single);bad['model_policy'].update(ground_temperature_method='explicit_research_boundary',ground_monthly_temperatures_C=[float('nan')]+[18]*11)
    check('nonfinite_ground_month_blocked',any('number_not_finite_binary64' in e for e in input_errors(bad)),input_errors(bad))
    for item in [studio,single]:
        r=build_one(item,tmp,{})
        check('actual_compile_'+item['case_id'],r['status']=='idf_ready',r)
        if r['status']!='idf_ready':continue
        folder=tmp/'cases'/item['case_id'];body=(folder/'building.idf').read_text();layout=json.loads((folder/'LAYOUT.json').read_text());rr=rows(body)
        check('independent_geometry_'+item['case_id'],inspect_idf(body,layout)['status']=='pass',inspect_idf(body,layout))
        if item is single:
            fs=[r for r in rr if r[0].lower()=='buildingsurface:detailed']
            check('single_all_floors_ground_all_roofs_outdoor',all(r[6]=='Ground' for r in fs if r[2]=='Floor') and all(r[2]=='Roof' and r[6]=='Outdoors' for r in fs if r[2] in ['Roof','Ceiling']),{'boundaries':sorted(set((r[2],r[6]) for r in fs))})
            ground=next(r for r in rr if r[0].lower()=='site:groundtemperature:buildingsurface')
            check('explicit18C_ground_not_EPW_soil',[float(v) for v in ground[1:]]==[18]*12,ground)
            bind=json.loads((folder/'ASSEMBLY_BINDING.json').read_text());parent=rows(Path(bind['parent_idf_path']).read_text())
            candidates=[r[3] for r in parent if r[0].lower()=='buildingsurface:detailed' and r[2].lower()=='floor' and r[6].lower()=='ground']
            check('ground_floor_uses_actual_parent_ground_construction',bind['construction_map']['ground_floor'] in candidates,{'selected':bind['construction_map']['ground_floor'],'source_frequencies':bind['full_parent_boundary_assemblies']})
        # Three distinct defects that used to evade algebraic closure checks.
        changed=copy.deepcopy(rr);face=next(r for r in changed if r[0].lower()=='buildingsurface:detailed' and r[2]=='Floor')
        for k in range(12,len(face),3):face[k]=str(float(face[k])+.123)
        result=inspect_idf(dump(changed),layout)
        check('translated_floor_rejected_'+item['case_id'],result['status']=='fail',result['errors'])
        changed=copy.deepcopy(rr);changed.remove(next(r for r in changed if r[0].lower()=='buildingsurface:detailed' and r[2]=='Floor'))
        result=inspect_idf(dump(changed),layout)
        check('missing_floor_rejected_'+item['case_id'],result['status']=='fail',result['errors'])
        changed=copy.deepcopy(rr);window=next(r for r in changed if r[0].lower()=='fenestrationsurface:detailed' and r[2]=='Window');window[4]='no_such_host'
        result=inspect_idf(dump(changed),layout)
        check('opening_wrong_host_rejected_'+item['case_id'],result['status']=='fail',result['errors'])
    save(output/'TEMPLATE_POLICY_VERIFICATION.json',{'scope':'direct adversarial compiler probes; tmp synthetic mutations never rewrite source or release','checks':checks,'passed':sum(c['passed'] for c in checks),'total':len(checks),'status':'pass' if all(c['passed'] for c in checks) else 'fail','temporary_compilation_path':str(tmp),'script_sha256':sha(__file__),'template_policy_sha256':sha(HERE/'TEMPLATE_POLICY.json'),'source_frozen_summary_sha256':sha(V2/'population_contexts_v1/SUMMARY.json'),'source_code':{p.name:sha(p) for p in HERE.glob('*.py')},'source_profiles_or_frozen_V2_modified':False,'EnergyPlus_runs':0})
    print(json.dumps({'passed':sum(c['passed'] for c in checks),'total':len(checks),'failed':[c['name'] for c in checks if not c['passed']]},ensure_ascii=False))

if __name__=='__main__':
    ap=argparse.ArgumentParser();ap.add_argument('--output',type=Path,required=True);main(ap.parse_args().output)
