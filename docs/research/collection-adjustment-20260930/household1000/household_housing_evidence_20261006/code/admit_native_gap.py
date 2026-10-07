"""Direct original-table opaque reference extraction for two Lasa models.

No unavailable R conversion is claimed. MAIN_ENCLOSURE selects actually used
opaque construction IDs; four layer properties come directly from native
tables. Glazing/absorptance are explicitly inherited reference assumptions.
"""
import json,sys
from pathlib import Path
OUT=Path(__file__).resolve().parent.parent;BASE=OUT.parent
sys.path[:0]=json.loads((BASE/'idf_joint_production_20261005/RUNTIME.json').read_text())['stable_PYTHONPATH'].split(':')
sys.path.insert(0,str(BASE/'idf_joint_production_20261005/code'))
from access_parser_c import AccessParser
from reference_world import assemblies
from regional_assemblies import rows,sha
from inventory_references import distance

def main():
    from evidence_guard import ensure_unsealed
    ensure_unsealed(OUT)
    weather=json.loads((OUT/'WEATHER_REFERENCE_REGISTRY.json').read_text())['stations'];extra=[];checks=[];frozen=assemblies()
    for r in json.loads((OUT/'NATIVE_GAP_ACQUISITION.json').read_text())['sources']:
        if not r.get('original_Access_source_obtained'):continue
        db=AccessParser(r['source_path']);env=rows(db.parse_table('ENVIRONMENT'))[0];enc=rows(db.parse_table('MAIN_ENCLOSURE'));material={m['MATERIAL_ID']:m for m in rows(db.parse_table('SYS_MATERIAL'))};names={};props=[];reports=[];material_name_by_identity={}
        for kind,code,table in [('exterior',1,'SYS_OUTWALL'),('interior',2,'SYS_INWALL'),('floor',4,'SYS_MIDDLEFLOOR')]:
            ids={e['CONSTRUCTION'] for e in enc if e['KIND']==code};assert len(ids)==1,(r['model_key'],kind,ids);sid=ids.pop()
            labels={s['STRUCT_ID']:s for s in rows(db.parse_table(table))};layers=sorted([x for x in rows(db.parse_table(table+'_MATERIAL')) if x['STRUCT_ID']==sid],key=lambda x:x['LAYER_NO']);assert layers
            name=r['model_key']+'_'+kind;names[kind]=name;layer_names=[];vectors=[]
            for i,layer in enumerate(layers):
                m=material[layer['MATERIAL_ID']];v=[layer['LENGTH']/1000,m['CONDUCTIVITY'],m['DENSITY'],m['SPECIFIC_HEAT']];vectors.append(v)
                identity=(layer['MATERIAL_ID'],*v)
                if identity not in material_name_by_identity:
                    mn=r['model_key']+'_native_layer_'+str(len(material_name_by_identity));material_name_by_identity[identity]=mn
                    props.append(['Material',mn,'MediumRough',*map(str,v),'.9','.7','.7'])
                layer_names.append(material_name_by_identity[identity])
            props.append(['Construction',name,*layer_names]);reports.append({'kind':kind,'native_actual_enclosure_kind_code':code,'native_used_struct_id':sid,
              'native_construction_CNAME':labels[sid]['CNAME'],'layer_numeric_vectors_t_lambda_rho_cp':vectors,'native_material_ids':[l['MATERIAL_ID'] for l in layers],
              'native_layer_CNAME':[material[l['MATERIAL_ID']]['CNAME'] for l in layers],'thickness_m':sum(v[0] for v in vectors),
              'series_R_without_surface_films_m2K_W':sum(v[0]/v[1] for v in vectors)})
        names['window']=frozen['names']['window'];window=next(x for x in frozen['rows'] if x[0]=='Construction' and x[1]==names['window']);glazing=next(x for x in frozen['rows'] if x[1]==window[2]);props += [window,glazing]
        bundle={'model_key':r['model_key'],'rows':props,'names':names,'source_path':r['source_path'],'source_sha256':r['source_sha256'],
          'source_conversion_sha256':None,'direct_native_opaque_extraction_not_whole_native_IDF_conversion':True,
          'exterior_thickness_m':reports[0]['thickness_m'],'interior_thickness_m':reports[1]['thickness_m'],
          'climate_identity':r['model_key']+'_author_code_reference_with_Lasa_station_not_observed_home',
          'opaque_layer_provenance':reports,'glazing_policy':'V7_Beijing2018_converted_simple_glazing_held_as_explicit_reference_assumption_NOT_Lasa_native_window',
          'glazing_reference_source_path':frozen['source_path'],'glazing_reference_source_sha256':frozen['source_sha256'],
          'opaque_absorptance0_9_0_7_0_7_and_roughness_are_engineering_reference':True,
          'floor_policy_for_pilot':'V7_declared_RC_floor_not_native_fibreboard_identity','actual_stock_or_local_building_code_compliance_observed':False}
        path=OUT/'assemblies'/(r['model_key']+'.json');path.write_text(json.dumps(bundle,ensure_ascii=False,indent=2)+'\n')
        station=[w for w in weather if w['WMO']==str(env['CITY_ID'])+'0' and distance(env['LATITUDE'],env['LONGITUDE'],w['latitude'],w['longitude'])<5]
        extra.append({**r,'original_environment':env,'catalogue_city':'Lasa','catalogue_type':'Low','catalogue_reference_epoch':int(r['model_key'].split('_')[-1]),
          'catalogue_city_matches_original_environment':env['CITY_NAME']=='Lasa','catalogue_epoch_is_observed_house_construction_year':False,
          'coordinate_confirmed_WMO_station_candidates':[{'station_key':w['station_key'],'path':w['path'],'sha256':w['sha256'],'distance_km':distance(env['LATITUDE'],env['LONGITUDE'],w['latitude'],w['longitude'])} for w in station],
          'reference_source_city_is_not_generated_household_observed_city':True,'assembly_bundle_path':str(path.relative_to(OUT)),
          'assembly_bundle_sha256':sha(path),'glazing_regional_native_match_admitted':False})
        checks.append({'model_key':r['model_key'],'native_source_sha256':r['source_sha256'],'actual_enclosure_structs':reports,
          'bundle_path':str(path.relative_to(OUT)),'bundle_sha256':sha(path),'WMO_coordinate_supported':bool(station)})
    report={'models':extra,'original_native_files_added':len(extra),'method':'direct_native_used_enclosure_and_four_material_properties',
      'full_native_geometry_or_windows_converted':False,'native_model_count_is_population_frequency':False,'glazing_and_absorptance_limit_retained':True,
      'independent_native_property_record':checks}
    (OUT/'ADDITIONAL_REGIONAL_REFERENCES.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')
    print(json.dumps({'original_native_added':len(extra),'matched_weather':sum(bool(r['coordinate_confirmed_WMO_station_candidates']) for r in extra)},ensure_ascii=False))
if __name__=='__main__':main()
