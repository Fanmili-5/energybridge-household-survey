"""Numeric layer comparison against original DeST Access tables.

String decoding is not used to infer layer identity. Matches retain original
material/struct IDs and reversal identity. This is provenance, not calibration.
"""
import hashlib,json,math
from pathlib import Path
from access_parser_c import AccessParser
from reference_world import OUT,assemblies

def rows(table):return [dict(zip(table,v)) for v in zip(*table.values())]

def main():
    repo=OUT.parents[4]
    path=repo/'artifacts/private_research/dest_batch_300_sources_20260925/HighS_Beijing_2018/HighS_Beijing_2018.accdb'
    db=AccessParser(str(path));materials={r['MATERIAL_ID']:r for r in rows(db.parse_table('SYS_MATERIAL'))}
    source_tables={kind:rows(db.parse_table(table)) for kind,table in [('exterior','SYS_OUTWALL_MATERIAL'),('interior','SYS_INWALL_MATERIAL'),('floor','SYS_MIDDLEFLOOR_MATERIAL')]}
    converted=assemblies();mats={r[1]:r for r in converted['rows'] if r[0].lower()=='material'}
    constructions={r[1]:r for r in converted['rows'] if r[0].lower()=='construction'}
    reports=[]
    for kind,table in source_tables.items():
        name=converted['names'][kind];layers=constructions[name][2:]
        vectors=[tuple(float(mats[n][j]) for j in [3,4,5,6]) for n in layers]
        structs={r['STRUCT_ID'] for r in table};matches=[]
        for sid in sorted(structs):
            rr=sorted([r for r in table if r['STRUCT_ID']==sid],key=lambda r:r['LAYER_NO'])
            if len(rr)!=len(vectors):continue
            native=[(r['LENGTH']/1000,materials[r['MATERIAL_ID']]['CONDUCTIVITY'],materials[r['MATERIAL_ID']]['DENSITY'],materials[r['MATERIAL_ID']]['SPECIFIC_HEAT']) for r in rr]
            for order,data in [('original',native),('reversed',native[::-1])]:
                maxerror=max(abs(a-b)/max(abs(b),1e-12) for x,y in zip(vectors,data) for a,b in zip(x,y))
                if maxerror<1e-6:matches.append({'native_struct_id':sid,'layer_order':order,'native_material_ids':[r['MATERIAL_ID'] for r in rr],
                   'native_layer_thickness_mm':[r['LENGTH'] for r in rr],'max_relative_numeric_serialization_difference':maxerror})
        if not matches:raise ValueError('opaque_construction_not_matched_to_native_table:'+kind)
        reports.append({'kind':kind,'converted_construction':name,'converted_layer_names':layers,'matches':matches,
                        'total_thickness_m':sum(v[0] for v in vectors),'series_thermal_resistance_m2K_per_W':sum(v[0]/v[1] for v in vectors)})
    output={'native_source_path':str(path),'native_source_sha256':hashlib.sha256(path.read_bytes()).hexdigest(),
      'converted_reference_source_sha256':converted['source_sha256'],'opaque_layer_matches':reports,
      'all_three_opaque_constructions_have_numeric_native_layer_matches':True,'matched_properties':['thickness','conductivity','density','specific_heat'],
      'window_simple_glazing_parameters_verified_against_detailed_native_glazing':False,
      'original_outside_inside_orientation_empirically_verified':False,
      'conversion_property_provenance_not_actual_household_or_energy_calibration':True}
    (OUT/'NATIVE_ASSEMBLY_VERIFICATION.json').write_text(json.dumps(output,ensure_ascii=False,indent=2)+'\n')
    floor=next(r for r in reports if r['kind']=='floor');rc=materials[837899393]
    assert rc['CNAME']=='钢筋混凝土' and abs(rc['CONDUCTIVITY']-1.74)<1e-6 and rc['DENSITY']==2500. and rc['SPECIFIC_HEAT']==920.
    normative=OUT/'raw/Zhejiang_residential_energy2021.pdf'
    assert hashlib.sha256(normative.read_bytes()).hexdigest()=='a26c0272e6973c57097832041c8a5c141f834895ab44522703f9ea0db65d6328'
    admission={'native_source_sha256':output['native_source_sha256'],'numeric_native_matches_do_not_prove_material_semantics':True,
      'native_floor':floor,'native_floor_RC_identity_admitted':False,
      'reason':'Native SYS_MIDDLEFLOOR_MATERIAL struct1 uses IDs55/76/55 with25/120/20mm; middle layer is fibreboard(lambda0.058,rho150,c2512), despite RC floor construction name.',
      'replacement':{'identity':'declared_RC_reference_floor_not_actual_household_floor',
         'native_reference_material_id':837899393,'native_reference_material_row':rc,
         'reference_material_parameters':{'conductivity_W_mK':1.74,'density_kg_m3':2500.,'specific_heat_J_kgK':920.},
         'conductivity_and_density_normative_crosscheck':{'source':'DB33/1015-2021','official_URL':'https://zjjcmspublic.oss-cn-hangzhou-zwynet-d01-a.internet.cloud.zj.gov.cn/jcms_files/jcms1/web3162/site/attach/0/33fa7399ca7c494baeff6af61a063d9a.pdf',
           'pdf_sha256':hashlib.sha256(normative.read_bytes()).hexdigest(),'pdf_page1based':76,'printed_page':68,'table':'D.1.1-3 row1',
           'visually_verified_RC_density_kg_m3':2500,'visually_verified_RC_conductivity_W_mK':1.74,
           'table_specific_heat_given':False,'table_heat_storage_coefficient_W_m2K':17.20,
           'specific_heat_source':'Native RC material ID837899393, NOT derived from rounded normative S',
           'published':'2021-12-27','effective':'2022-02-01','applied_as_reference_material_parameters_not_2020_stock_compliance':True},
         'core_thickness_m':.12,'core_thickness_evidence':'retain_native_geometry_thickness_as_reference_design; actual_RC_floor_thickness_unknown',
         'finishes':'source cement_mortar25mm and20mm; native numeric identity and normative rho/lambda crosscheck',
         'IR_solar_visible_absorptance_reference':[.9,.7,.7],
         'regional_stock_frequency_or_empirical_thermal_validation':False},
      'admission_levels':{'numeric_provenance':True,'RC_parameter_category_crosscheck':True,'regional_vintage_stock_matching':False,'empirical_floor_validation':False},
      'floor_is_adiabatic_in_steady_UA_diagnostics_so_UA_does_not_validate_its_mass_or_R':True,
      'source_files_modified':False}
    (OUT/'MATERIAL_SEMANTIC_ADMISSION.json').write_text(json.dumps(admission,ensure_ascii=False,indent=2)+'\n')
    print(json.dumps({'constructions_matched':3,'thickness_m':{r['kind']:r['total_thickness_m'] for r in reports}},indent=2))

if __name__=='__main__':main()
