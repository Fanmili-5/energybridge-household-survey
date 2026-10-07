"""Make unimplemented facilities/stock facets explicit without changing IDFs.
Statistical controls, functional spaces and instantiated hardware are separate.
"""
from common import *
def main():
 guard();b=read(OUT/'JOINT_WORLD_BINDINGS.json');s=read(OUT/'SERVICE_PORT_BINDINGS.json');si={r['household_id']:r for r in s['records']}
 for r in b['records']:
  c=read(OUT/r['world_path']);sc=read(OUT/si[r['household_id']]['service_world_path']);w=c['world']
  for room in w['rooms']:
   room['census_toilet_facility_reference_present']=room.pop('toilet_fixture_present',room.get('census_toilet_facility_reference_present',False))
   room['toilet_facility_reference_class']=room.pop('toilet_fixture_class',room.get('toilet_facility_reference_class'))
   room['physical_toilet_fixture_geometry_instantiated']=False
  c['field_realization']={'population_N_G_H6_H7':'fixed synthetic calibrated/control values,not source actual household records',
   'building_storeys':'one-storey roof/ground physically implemented;multistorey baseline declared midfloor,actual unit storey and building stack unknown',
   'load_bearing_structure':'statistical reference facet only;no structural mechanics/frame reconstruction or independent consistency admission with thermal-layer library',
   'housing_epoch':'statistical reference facet only;regional source code epoch not household construction-year observation',
   'elevator':'statistical reference facet only;lift geometry,shared electricity and individual eligibility unmodelled',
   'housing_source_tenure':'statistical reference facet only;source-owned household observation not transferred',
   'cooking_fuel':'statistical reference facet only;hob/hood/fuel plumbing/cooking tasks and heat not instantiated',
   'piped_water':'typed eligibility for selected tank only;pressure/supply/sink/drainage alternatives unmodelled',
   'kitchen':'separate dedicated-room use rights,area partition and worktop witness;full sink/hob/hood/heater functional installation incomplete',
   'toilet':'typed census facility class and service space only;fixture body/drainage/shared WC rights unmodelled',
   'bathing_hot_water':'typed facility class;compatible selected electric tank standby ports only;draw/shower/drainage/care unmodelled'}
  c['all_ten_stock_facets_physically_realized_or_validated']=False;c['baseline_H6_inside_unit_fraction_is_reference_not_observed']=1.
  sc['world']=w;sc['field_realization']=c['field_realization'];sc['all_ten_stock_facets_physically_realized_or_validated']=False;sc['baseline_H6_inside_unit_fraction_is_reference_not_observed']=1.
  sc['full_sanitary_kitchen_fixtures_not_instantiated']=True
  save(OUT/r['world_path'],c);save(OUT/si[r['household_id']]['service_world_path'],sc)
  r['world_sha256']=sha(OUT/r['world_path']);si[r['household_id']]['world_sha256']=r['world_sha256'];si[r['household_id']]['service_world_sha256']=sha(OUT/si[r['household_id']]['service_world_path'])
 save(OUT/'JOINT_WORLD_BINDINGS.json',b);save(OUT/'SERVICE_PORT_BINDINGS.json',s)
 print({'updated_worlds':1000,'updated_service_worlds':1000,'IDF_bytes_changed':False,'full_facility_or_structure_claim':False})
if __name__=='__main__':main()
