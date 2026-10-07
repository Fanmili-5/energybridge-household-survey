"""Independent SQL,source-vector and role-evidence audit with negative controls.
Does not call generators or their task/thermal/permission calculators.
"""
import collections,copy,sqlite3,math
from common import *
def energy_balance(variables):
 names=['Water Heater Electricity Energy','Water Heater Heat Loss Energy','Water Heater Use Side Heat Transfer Energy','Water Heater Net Heat Transfer Energy'];x={v['variable']:v['values'] for v in variables if v['variable'] in names};assert set(x)==set(names);n=len(x[names[0]]);assert all(len(v)==n for v in x.values());res=[]
 for values in zip(*(x[k] for k in names)):
  assert all(v[:4]==values[0][:4] for v in values);e,loss,use,net=[v[-1] for v in values];res.append(e+loss+use-net)
 return max(abs(v) for v in res),{k:sum(v[-1] for v in vals)/3.6e6 for k,vals in x.items()}
def role_errors(packet,profile,world):
 facts=packet['public_role_material']['facts'];out=[];family=profile['family'];hid=profile['slot_id']
 if facts['resident_count']!=family['resident_count'] or facts['generation_count']!=family['generation_count']:out.append('N_G_changed')
 if facts['role_representative_member_id']!=family['reference_member_id']:out.append('role_person_not_identified')
 if {m['member_id'] for m in facts['members']}!=set(family['resident_member_ids']):out.append('roster_changed')
 if packet['formal_human_answer'] is not None:out.append('manufactured_human_answer')
 if packet['evidence']['wholehome_inventory_income_health_mobility_care_actual_city_floor']['value'] is not None:out.append('unsupported_private_context_added')
 if packet['evidence']['preference_or_willingness']['value'] is not None:out.append('physics_as_human_willingness')
 if facts['H6_building_area_reference_m2']!=profile['housing']['H6_census_building_area_design_m2'] or facts['H7_independent_natural_rooms_reference']!=profile['housing']['H7_independent_natural_rooms_design']:out.append('H6_H7_changed')
 if facts['census_marginal_reference_housing_features']!=world['world']['stock_reference_features']:out.append('housing_facets_changed')
 valid={m['member_id'] for m in family['members'] if m['age_years']>=18}
 for task in packet['public_role_material']['tasks']:
  if task['stipulated_operator_ID'] not in valid:out.append('operator_adult_not_in_roster')
 if any(k in str(packet['public_role_material']) for k in ['event_energy_change_kWh','day_energy_change_kWh','shifted_reference_service_threshold_met']):out.append('numeric_oracle_leaked_to_actor')
 episode=packet['public_role_material']['additional_collection_episode']
 if not packet['public_role_material']['tasks'] and episode is None:out.append('missing_review_episode')
 if episode and (episode['physical_model_admitted'] or episode['physical_kWh_or_delivered_reduction_label'] is not None):out.append('functional_proposal_given_false_physics_label')
 return out
def main():
 guard();events=read(OUT/'EVENT_RESULTS.json');results=[];max_balance=0.;grouped=collections.defaultdict(dict)
 for r in events['runs']:
  assert sha(OUT/r['IDF_path'])==r['IDF_sha256'] and sha(OUT/r['SQL_path'])==r['SQL_sha256'];db=sqlite3.connect(OUT/r['SQL_path'])
  rows=db.execute('SELECT t.Hour,t.Minute,r.Value FROM ReportData r JOIN ReportDataDictionary d USING(ReportDataDictionaryIndex) JOIN Time t USING(TimeIndex) WHERE COALESCE(t.WarmupFlag,0)=0 AND t.Month=7 AND t.Day=7 AND d.KeyValue=? AND d.Name=? AND d.ReportingFrequency="Zone Timestep" ORDER BY t.TimeIndex',(r['instance_reference_ID'].upper(),r['meter_variable'])).fetchall();db.close();assert rows
  E=sum(v for h,m,v in rows)/3.6e6;event=sum(v for h,m,v in rows if 1140<h*60+m<=1200)/3.6e6;assert abs(E-r['day_energy_kWh'])<1e-10 and abs(event-r['event19to20_kWh'])<1e-10
  if r['kind']=='washer':
   assert abs(E-.72)<1e-9;expected=.72*60/159 if r['variant']=='baseline' else 0.;assert abs(event-expected)<1e-9
  else:
   residual,sums=energy_balance(r['thermal_energy_balance_series']);max_balance=max(max_balance,residual);assert residual<1e-5
   assert abs(sums['Water Heater Electricity Energy']-E)<1e-9
   temps=next(x['values'] for x in r['thermal_energy_balance_series'] if x['variable']=='Water Heater Final Tank Temperature');assert all(0<v[-1]<75 for v in temps)
   r['verified_energy_terms_kWh']=sums
  grouped[r['household_id'],r['kind']][r['variant']]=r
 for (hid,kind),v in grouped.items():
  a,b=v['baseline'],v['shifted'];assert a['pre_intervention_states']==b['pre_intervention_states'];record={'household_id':hid,'kind':kind,'event_delta_kWh':a['event19to20_kWh']-b['event19to20_kWh'],'day_electric_delta_kWh':a['day_energy_kWh']-b['day_energy_kWh']}
  if kind=='water_heater':
   aa,bb=a['verified_energy_terms_kWh'],b['verified_energy_terms_kWh'];storage=aa['Water Heater Net Heat Transfer Energy']-bb['Water Heater Net Heat Transfer Energy'];loss=-(aa['Water Heater Heat Loss Energy']-bb['Water Heater Heat Loss Energy']);served=-(aa['Water Heater Use Side Heat Transfer Energy']-bb['Water Heater Use Side Heat Transfer Energy'])
   assert abs(record['day_electric_delta_kWh']-storage-loss-served)<1e-8
   record.update({'terminal_storage_net_delta_kWh':storage,'loss_to_ambient_delta_kWh':loss,'heat_served_delta_kWh':served,'day_electric_difference_is_not_automatically_total_energy_savings':True})
  results.append(record)
 ground=read(OUT/'GROUND_HISTORY_RESULTS.json');ext=read(OUT/'GROUND_EXTENDED_RESULTS.json');allpairs={x['household_id']:x for x in ground['pairs']};allpairs.update({x['household_id']:x for x in ext['pairs']});assert len(allpairs)==61 and all(x['lastyear_perturbation_tolerance_met'] for x in allpairs.values())
 for r in ground['runs']+ext['runs']:
  assert sha(OUT/r['IDF_path'])==r['IDF_sha256'] and sha(OUT/r['SQL_path'])==r['SQL_sha256'];d=read(OUT/r['hourly_path']);assert sha(OUT/r['hourly_path'])==r['hourly_sha256']
  assert all(math.isfinite(v[3]) and -100<v[3]<100 for s in d['series'] for v in s['hourly'])
 # The final61 criteria are recalculated from raw SQL, independently of
 # exported hourly JSON and the generator's pass flags.
 finalruns={}
 for r in ground['runs']+ext['runs']:finalruns[r['household_id'],r['initial_indoor_reference_C']]=r
 direct_ground=[]
 for hid,pair in allpairs.items():
  values=[]
  for initial in [10,30]:
   r=finalruns[hid,initial];db=sqlite3.connect(OUT/r['SQL_path']);last=db.execute('SELECT max(Year) FROM Time WHERE COALESCE(WarmupFlag,0)=0').fetchone()[0]
   a=db.execute('SELECT d.KeyValue,t.Month,t.Day,t.Hour,t.Minute,r.Value FROM ReportData r JOIN ReportDataDictionary d USING(ReportDataDictionaryIndex) JOIN Time t USING(TimeIndex) WHERE COALESCE(t.WarmupFlag,0)=0 AND t.Year=? AND d.Name="Zone Mean Air Temperature" ORDER BY d.KeyValue,t.Month,t.Day,t.Hour,t.Minute',(last,)).fetchall();db.close();assert a;values.append(a)
  a,b=values;assert len(a)==len(b) and all(x[:-1]==y[:-1] for x,y in zip(a,b));delta=max(abs(x[-1]-y[-1]) for x,y in zip(a,b));assert delta<=.1 and abs(delta-pair['years'][-1]['max_abs_zone_hourly_initial10_vs30_difference_C'])<1e-10;direct_ground.append({'household_id':hid,'direct_SQL_finalyear_maxdelta_C':delta,'points':len(a)})
 save(OUT/'DIRECT_SQL_GROUND_CONVERGENCE61.json',{'cases':direct_ground,'criterion_C':.1,'passed':len(direct_ground),'worst_finalyear_C':max(x['direct_SQL_finalyear_maxdelta_C'] for x in direct_ground),'not_other_ground_parameters_or_occupied_HVAC_convergence_validation':True})
 # Compare the extracted line endpoints and independently calculated factor
 # axes; rated anchors were checked separately, not hidden by normalization.
 kernel=read(OUT/'HVAC_SOURCE_KERNEL.json');vectors=read(OUT/'HVAC_PDF_VECTOR_EXTRACTION.json');lines=0
 for key,page in [('capacity_factor',15),('total_input_factor',16)]:
  source=sorted(next(x for x in vectors['page_vector_data'] if x['PDF_page1based']==page)['candidate_performance_lines'],key=lambda x:x['vertices_pdfpoints'][0][1]);axis=kernel[key]['axis_calibration']
  for row,original in zip(kernel[key]['curves'],source):
   assert row['PDF_vector_endpoints']==original['vertices_pdfpoints']
   for (x,y),(t,f) in zip(original['vertices_pdfpoints'],row['temperature_factor_endpoints']):
    tt=-10.+55*(x-axis['outdoor_DB_minus10_pdfx'])/axis['outdoor_DB45_minus_minus10_pdf_span'];ff=1.+.1*(y-axis['factor1_pdfy'])/axis['factor0_1_pdf_dy'];assert abs(tt-t)<1e-10 and abs(ff-f)<1e-10
   lines+=1
 profiles={p['slot_id']:p for p in read(V7/'HOUSEHOLDS1000_JOINT_GEOMETRY_CANDIDATE.json')['profiles']};bindings=read(OUT/'ROLE_PACKET_BINDINGS1000.json')['records'];worlds={r['household_id']:r for r in read(V10/'SERVICE_PORT_BINDINGS.json')['records']};fail=[]
 for r in bindings:
  assert sha(OUT/r['packet_path'])==r['packet_sha256'] and sha(OUT/r['public_card_path'])==r['public_card_sha256'] and sha(OUT/r['private_labels_path'])==r['private_labels_sha256'];p=read(OUT/r['packet_path']);w=read(V10/worlds[r['household_id']]['service_world_path']);issues=role_errors(p,profiles[r['household_id']],w)
  if issues:fail.append({'household_id':r['household_id'],'issues':issues})
 assert len(bindings)==1000 and not fail
 negatives=[];r=bindings[0];p=read(OUT/r['packet_path']);f=profiles[r['household_id']];w=read(V10/worlds[r['household_id']]['service_world_path']);q=copy.deepcopy(p);q['formal_human_answer']='accept';negatives.append({'injection':'manufactured_human_answer','detected':'manufactured_human_answer' in role_errors(q,f,w)});q=copy.deepcopy(p);q['evidence']['wholehome_inventory_income_health_mobility_care_actual_city_floor']['value']={'income':120000};negatives.append({'injection':'invented_income','detected':'unsupported_private_context_added' in role_errors(q,f,w)});q=copy.deepcopy(p);q['public_role_material']['event_energy_change_kWh']=.72;negatives.append({'injection':'numeric_answer_leakage','detected':'numeric_oracle_leaked_to_actor' in role_errors(q,f,w)})
 sample=next(r for r in events['runs'] if r['kind']=='water_heater');q=copy.deepcopy(sample['thermal_energy_balance_series']);next(x for x in q if x['variable']=='Water Heater Electricity Energy')['values'][0][-1]+=100.;negatives.append({'injection':'energy_term_corrupted100J','detected':energy_balance(q)[0]>99.});assert all(x['detected'] for x in negatives)
 save(OUT/'INDEPENDENT_COMPLETION_VERIFICATION.json',{'component_run_SQL_readbacks_checked':len(events['runs']),'paired_tasks_checked':len(results),'tank_energy_balances_checked':340,'maximum_step_heat_balance_residual_J':max_balance,
  'ground_case_final_perturbation_checks':61,'ground_run_input_SQL_hashes_checked':len(ground['runs'])+len(ext['runs']),'manufacturer_vector_lines_checked':lines,'role_review_packets_checked':len(bindings),
  'role_failures':fail,'negative_controls':negatives,'empirical_wholehome_energy_or_human_validity_not_inferred':True})
 save(OUT/'PAIRED_ENERGY_ACCOUNTING.json',{'cases':results,'physics_authority':'EnergyPlus24.1 IO1.24.2.2.2 and2.28;raw/WaterThermalTanks_v24_1.cc signedloss/use and netheat equation',
  'change_in_stored_energy_reported_separately_from_electricity_and_delivered_heat':True,'model_thermodynamic_ledger_not_measured_product_or_human_response':True})
 print({'paired_tasks':len(results),'ground_cases':61,'role_review_packets':1000,'max_step_energy_residual_J':max_balance,'negative_controls':len(negatives)})
if __name__=='__main__':main()
