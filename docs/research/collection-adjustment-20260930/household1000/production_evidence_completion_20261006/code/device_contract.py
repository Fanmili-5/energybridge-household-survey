"""Units, provenance, source exclusions and source-conditioned reference ports.

This is a component model contract with falsification tests, not an installed
whole-home IDF or a calibrated Chinese appliance population model.
"""
import copy,json,math
from pathlib import Path
import pandas as pd
from pypdf import PdfReader
from device_evidence import devices,physical_lower_bound,decode
OUT=Path(__file__).resolve().parent.parent;BASE=OUT.parent
MIELE='https://media.miele.com/downloads/83/d4/01_C7F12828BC641EDEA4EAE0B7FDA083D4.pdf'
def save(name,d):(OUT/name).write_text(json.dumps(d,ensure_ascii=False,indent=2,allow_nan=False)+'\n')
def clock_errors(task,start,operator_present,has_permission=True,active=False):
 errors=[]
 if start<task['release_min']:errors.append('before_release')
 if start+task['duration_min']>task['deadline_min']:errors.append('late_completion')
 if not operator_present:errors.append('no_operator_at_manual_start')
 if not has_permission:errors.append('no_control_permission')
 if active:errors.append('active_cycle_not_interruptible_in_reference_contract')
 return errors
def cycle_load(E,duration,start,step=1,total=1440):
 # Rectangular mean-power shape is an explicit design approximation. It
 # preserves cycle energy but has no claimed intra-cycle peak/duty validity.
 return [E/(duration/60)*max(0,min(t+step,start+duration)-max(t,start))/step for t in range(0,total,step)]
def main():
 if (OUT/'PACKAGE_MANIFEST.json').exists():raise SystemExit('sealed')
 raw=BASE/'crecs_admission_20261003/private_raw/CRECS2012.dta';r=pd.io.stata.StataReader(raw);r.read(1);ll=r.value_labels();fields={}
 for k in ['b1','b13','c2_dbx_1b','c2_dbx_1c','c3_1c','c3_1d','c3_1e','c3_1f','c3_1g','c4_1b','d4_1a','d4_1b','d4_1j__1','d6_1a','d6_1b','d6_1g']:
  lab=r._lbllist[r._varlist.index(k)];fields[k]={'source_label_name':lab,'source_value_labels':{str(v):decode(s) for v,s in ll.get(lab,{}).items()}}
 # Do not treat the CHEAA table as an original energy measurement: its footnote
 # says retailer listings and manufacturer manuals. Keep it as excluded lead.
 cheaa=PdfReader(OUT/'raw/CHEAA_washer_measurement.pdf').pages[70].extract_text();assert '数据摘自' in cheaa and '电商' in cheaa
 mipdf=PdfReader(OUT/'raw/Miele_WTD160_manual.pdf');mt=mipdf.pages[81].extract_text();assert '0.72' in mt and '2:39' in mt and 'GB12021.4-2013' in mt
 fridge=PdfReader(OUT/'raw/Haier_fridge.pdf');ft=fridge.pages[34].extract_text();assert '0.65' in ft and '342' in ft and '180' in ft
 catalog={'reference_models':{
  'Miele_WTD160_wash_test':{'class':'washer_service_on_combo','test_cycle_energy_kWh':.72,'duration_min':159,'load_kg':8,'water_L':50,
   'hardware_max_wash_kg':8,'hardware_max_dry_kg':5,'outer_width_depth_height_m':[.596,.637,.850],'door_open_depth_m':1.055,
   'source_URL':MIELE,'PDF_pages1based':[81,82],'conditions':'manufacturer GB12021.4-2013 comparison test;actual inlet water/load/etc can differ',
   'within_cycle_shape':'declared rectangular mean power, not measured compressor/heater duty','interrupt_active_cycle':False,
   'delay_start_permission_requires_design_operator_or_observed_authorization':True},
  'Miele_WTD160_dry_test':{'class':'dryer_service_on_same_combo','test_cycle_energy_kWh':2.60,'duration_min':165,'load_kg':5,'water_L':25,
   'source_URL':MIELE,'PDF_page1based':82,'conditions':'manufacturer EN61121 comparison test',
   'external_socket_interrupt_during_cooldown_prohibited_by_OEM':True,'OEM_safety_PDF_page1based':11,'separate_physical_washer_dryer_count':1},
  'Haier_KFR26GW_06ZFA22_rated_cooling':{'class':'split_AC','rated_thermal_cooling_W':2610,'rated_electric_input_W':700,
   'rated_point_COP_derived':2610/700,'source_URL':'https://www.haier.com/air_conditioners/20130503_99020.shtml',
   'primary_web_specification_verified_20261006':True,'full_offdesign_curve_validated':False,'whole_year_efficiency_is_not_rated_COP':True,
   'web_cache_retrieval_failed_403_but_primary_web_tool_read_succeeded':True,'remote_IoT_capability_for_this_model':False,
   'source_web_SEER_or_EER_label4_85_not_used_as_rated_point_COP':True},
  'Haier_ES60H_AFV2AU1_reference_tank':{'class':'electric_storage_reference','source_volume_L':60,'source_rated_power_W':3300,
   'source_alternate_power_W':2200,'source_max_temperature_C':75,'source_URL':'https://www.haier.com/water_heaters/drsq/20210819_167043.shtml',
   'primary_web_specification_verified_20261006':True,'marketing_heating_mode_label_instantaneous_not_used_to_infer_well_mixed_tank':True,
   'well_mixed_tank_topology_eta1_UA0_or1_5_is_declared_design_not_measured_product_model':True,
   'water_density_kg_L_reference':1,'water_cp_kJ_kgK_reference':4.186,'web_cache_failed_403':True,
   'product_reference_date2021_is_not_2020_stock_observation':True},
  'Haier_BCD342WLHFD9DB9U1_label':{'class':'refrigerator','volume_L':342,'label_kWh_24h':.65,'label_annual_kWh':237,
   'defrost_only_input_W':180,'outer_width_depth_height_m':[.640,.682,1.804],
   'source_URL':'https://file.c.haier.net/obs-cpzx/materialprod/2023/12/21/1737726717934243840/e6dcd3e59b3e573efb4fe2c23fb6ea01.pdf',
   'PDF_page1based':35,'constant_label_mean_W_design_only':.65*1000/24,
   'defrost_W_is_not_compressor_W':True,'label_daily_energy_is_not_observed_household_energy':True,
   'actual_food_temperature_or_interruption_safety_not_modelled':True,'default_DR_interrupt_eligible':False}},
  'catalog_is_selected_reference_hardware_not_national_ownership_or_installed_assets':True,
  'fuel_mapping':{'1':'electricity','2':'piped_gas','3':'LPG','4':'fuel_oil','5':'solar','6':'solar_with_electric_backup','7':'unspecified_other'},
  'electric_water_heater_instantiation_requires_source_fuel1_and_storage_type1_and_declared_installation':True,
  'solar_backup_without_split_solar_and_electric_model_not_relabelled_all_electric':True,
  'central_HVAC_is_common_system_not_automatically_personal_split_AC':True,
  'whole_house_baseload_lighting_cooking_and_all_device_inventory_unknown':True}
 save('DEVICE_MODEL_CATALOG.json',catalog)
 checks=[]
 def check(name,passed):checks.append({'check':name,'passed':bool(passed)})
 check('empty_questionnaire_slots_do_not_create_zero_assets',devices({})==[])
 check('combo_and_washer_not_summed_as_two_independent_hardware',physical_lower_bound([{'class':'washer'},{'class':'washer_dryer_combo_report'}])==1)
 check('central_unasked_capacity_not_admitted',devices({'d6_1a':1,'d6_1b':3})[0]['cooling_capacity_like_bin_not_electric_input'] is None)
 check('instantaneous_unasked_storage_not_admitted',devices({'d4_1a':2,'d4_1j__1':2})[0]['storage_volume_bin'] is None)
 check('mixed_washer_code24_is_quarantined',not devices({'c3_1c':24}))
 check('fridge_volume_out_of_domain_not_admitted',devices({'c2_dbx_1b':1,'c2_dbx_1c':9})[0]['volume_bin'] is None)
 task={'release_min':18*60,'duration_min':159,'deadline_min':24*60};baseline=cycle_load(.72,159,18*60+50);shifted=cycle_load(.72,159,20*60)
 check('cycle_energy_conserved_after_shift',abs(sum(baseline)/60-.72)<1e-12 and abs(sum(shifted)/60-.72)<1e-12)
 check('task_before_release_rejected','before_release' in clock_errors(task,17*60,True))
 check('late_completion_rejected','late_completion' in clock_errors(task,23*60,True))
 check('absent_manual_operator_rejected','no_operator_at_manual_start' in clock_errors(task,20*60,False))
 check('missing_control_permission_rejected','no_control_permission' in clock_errors(task,20*60,True,False))
 check('active_cycle_not_interruptible','active_cycle_not_interruptible_in_reference_contract' in clock_errors(task,20*60,True,True,True))
 check('post_event_shift_feasible_in_declared_context',not clock_errors(task,20*60,True))
 Eheat=60*4.186*(60-20)/3600;time=Eheat/3.3
 check('tank_heat_up_energy_and_time_units',abs(Eheat-2.790666666666667)<1e-12 and .84<time<.85)
 check('AC_thermal_and_electric_power_not_equal',2610!=700 and abs(2610/(2610/700)-700)<1e-10)
 check('fridge_label_mean_not_defrost_power',abs(.65*1000/24-180)>100)
 event_start,event_end=19*60,20*60;event_b=sum(baseline[event_start:event_end])/60;event_s=sum(shifted[event_start:event_end])/60
 save('DEVICE_SOURCE_SEMANTICS.json',{'source_fields':fields,'source_reference_year':2012,
   'refrigerator_volume_accepted_codes':[1,2,3,4,5],'heater_type3_boiler_retained_as_non_admitted_lead_not_specific_port':True,
   'CHEAA_energy_table_is_secondary_compilation_not_original_energy_test':True,'CHEAA_table_footnote_page1based':71,
   'no_CHFS_group_flag_to_specific_instance':True,'no_blank_to_zero_or_capacity_to_input_power':True})
 save('COMPONENT_MODEL_VERIFICATION.json',{'checks':checks,'analytic_reference_results':{
   'washer_Ecycle_kWh':.72,'declared_baseline_event_energy_kWh':event_b,'declared_shift_event_energy_kWh':event_s,
   'full_horizon_energy_difference_kWh':sum(baseline)/60-sum(shifted)/60,
   'reference_tank20_to60C_heat_kWh':Eheat,'UA0_eta1_heating_time_h':time,
   'AC_rated_point_COP':2610/700,'fridge_label_mean_W':.65*1000/24},
   'analytic_and_units_checks_not_EnergyPlus_or_actual_load_validation':True,
   'reference_event_clock_and_operator_presence_are_design_not_empirical_behavior':True})
 print(json.dumps({'checks':len(checks),'passed':sum(c['passed'] for c in checks),'reference_cycle_event_reduction_kWh':event_b-event_s,'physical_components_calibrated_to_households':0},ensure_ascii=False))
 assert all(c['passed'] for c in checks)
if __name__=='__main__':main()
