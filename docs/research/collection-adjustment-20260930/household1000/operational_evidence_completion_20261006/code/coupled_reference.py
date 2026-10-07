"""Source-qualified aggregate net-Q / active total-set-P thermal surrogate.
This is a transparent controlled emulator, not an OEM DX/refrigerant model.
No invented compressor curve, auto-inverter law, off-state power or airflow
performance is smuggled in. ISO latent split is explicitly held as a design
assumption outside ISO; graph/domain coverage is reported, never clamped.
"""
import collections,concurrent.futures,re,sqlite3,subprocess
from common import *
from hvac_source_kernel import evaluate
ENGINE=Path('/Applications/EnergyPlus-24-1-0/energyplus')
PAIRS={'MUZ-AP25VG':('MSZ-AP25VG',684,19,.3),'MUZ-AP35VG':('MSZ-AP35VG',684,19,.6),'MUZ-AP42VG':('MSZ-AP42VG',684,19,1.4),'MUZ-AP50VG':('MSZ-AP50VG',756,24,1.9)}
def append_model(r,candidate,variant):
 refined='--refine-failed' in sys.argv or '--uniform-minute' in sys.argv;uniform='--uniform-minute' in sys.argv
 data=read(OUT/'HVAC_SOURCE_KERNEL.json');model=candidate['reference_performance_model'];indoor,flow,fan,dehum=PAIRS[model];spec=data['models'][model];shr=1-dehum*2500/3.6/spec['capacity_W'];assert 0<shr<1
 z=parse(OUT/r['IDF_path']);
 for b in z:
  if b[0]=='Building':b[SCHEMA['properties']['Building']['legacy_idd']['fields'].index('maximum_number_of_warmup_days')+1]=100
  if b[0]=='Timestep' and refined:b[1]=60
 if uniform:z.append(obj('OutputControl:Files',{'output_eso':'No','output_mtr':'No','output_csv':'No'}))
 rid=r['members'][0]['room_id'];hid=r['household_id'];cool=hid+'_aggregate_net_cooling';power=hid+'_active_package_power';z+=[obj('OtherEquipment',{'name':cool,'fuel_type':'None','zone_or_zonelist_or_space_or_spacelist_name':rid,'schedule_name':'eb_allhome','design_level_calculation_method':'EquipmentLevel','design_level':-spec['capacity_W'],'fraction_latent':1-shr,'fraction_radiant':0,'fraction_lost':0,'end_use_subcategory':'declared_aggregate_reference_cooling'}),
  obj('ElectricEquipment',{'name':power,'zone_or_zonelist_or_space_or_spacelist_name':rid,'schedule_name':'eb_allhome','design_level_calculation_method':'EquipmentLevel','design_level':spec['total_set_input_W'],'fraction_latent':0,'fraction_radiant':0,'fraction_lost':1,'end_use_subcategory':'active_package_power_no_unknown_offstate'})]
 for name,key,var in [('eb_T',rid,'Zone Mean Air Temperature'),('eb_W',rid,'Zone Air Humidity Ratio'),('eb_O','Environment','Site Outdoor Air Drybulb Temperature'),('eb_Pb','Environment','Site Outdoor Air Barometric Pressure')]:z.append(['EnergyManagementSystem:Sensor',name,key,var])
 z += [['EnergyManagementSystem:Actuator','eb_remove',cool,'OtherEquipment','Power Level'],['EnergyManagementSystem:Actuator','eb_electric',power,'ElectricEquipment','Electricity Rate'],['EnergyManagementSystem:GlobalVariable','eb_on']]
 lines=['SET eb_SP = 26']
 if variant=='shifted':lines+=['IF DayOfMonth == 2 && Hour >= 19 && Hour < 20','SET eb_SP = 28','ENDIF']
 lines += ['IF eb_T > eb_SP + 0.25','SET eb_on = 1','ELSEIF eb_T < eb_SP - 0.25','SET eb_on = 0','ENDIF','SET eb_remove = 0','SET eb_electric = 0','SET eb_bad = 0','SET eb_WB = @TwbFnTdbWPb eb_T eb_W eb_Pb','IF eb_on == 1','SET eb_valid = 0']
 # The common traced support of the two bracketing manufacturer lines is
 # frozen; no hidden input/output curve clamping or generic extrapolation.
 for j in range(4):
  lo=18+2*j;hi=lo+2;lines += [('IF' if j==0 else 'ELSEIF')+f' eb_WB >= {lo} && eb_WB <= {hi}']
  supports=[]
  for kind in ['capacity_factor','total_input_factor']:
   a,b=data[kind]['curves'][j:j+2];supports += [a['temperature_factor_endpoints'],b['temperature_factor_endpoints']]
  low=max(x[0][0] for x in supports);high=min(x[1][0] for x in supports);lines += [f'IF eb_O >= {low:.12g} && eb_O <= {high:.12g}','SET eb_valid = 1']
  for kind,symbol in [('capacity_factor','Q'),('total_input_factor','P')]:
   a,b=data[kind]['curves'][j:j+2]
   for letter,c in [('L',a),('H',b)]:
    (x0,y0),(x1,y1)=c['temperature_factor_endpoints'];m=(y1-y0)/(x1-x0);intercept=y0-m*x0;lines += [f'SET eb_{symbol}{letter} = {intercept:.12g} + {m:.12g} * eb_O']
   n=data[kind]['normalization_at19WB35DB'];lines += [f'SET eb_{symbol}F = (eb_{symbol}L + (eb_{symbol}H - eb_{symbol}L) * (eb_WB - {lo}) / 2) / {n:.12g}']
  lines += ['ENDIF']
 lines += ['ENDIF','IF eb_valid == 1',f'SET eb_remove = -{spec["capacity_W"]} * eb_QF',f'SET eb_electric = {spec["total_set_input_W"]} * eb_PF','ELSE','SET eb_bad = 1','ENDIF','ENDIF']
 z += [['EnergyManagementSystem:Program','eb_rated_frequency_controller',*lines],['EnergyManagementSystem:ProgramCallingManager','eb_apply_aggregate','BeginZoneTimestepBeforeInitHeatBalance','eb_rated_frequency_controller']]
 for name,symbol,unit in [('Reference Requested Cooling','eb_on',''),('Reference Outside Source Domain','eb_bad',''),('Reference WB','eb_WB','C'),('Reference Outdoor DB','eb_O','C'),('Reference Package Active Power','eb_electric','W'),('Reference Net Cooling Rate','eb_remove','W')]:
  z += [['EnergyManagementSystem:OutputVariable',name,symbol,'Averaged','ZoneTimestep','eb_rated_frequency_controller',unit],['Output:Variable','*',name,'Timestep']]
 z += [['Output:Variable',power,'Electric Equipment Electricity Energy','Timestep'],['Output:Variable',cool,'Other Equipment Total Heating Energy','Timestep'],['Output:Variable',cool,'Other Equipment Convective Heating Energy','Timestep'],['Output:Variable',cool,'Other Equipment Latent Gain Energy','Timestep'],['Output:Variable',cool,'Other Equipment Radiant Heating Energy','Timestep']]
 folder=OUT/('coupled_uniform_minute_idfs' if uniform else 'coupled_minute_idfs' if refined else 'coupled_idfs')/variant;folder.mkdir(parents=True,exist_ok=True);p=folder/(hid+'.idf');p.write_text('! Aggregate nominal-frequency reference emulator;not actual OEM auto control or field-calibrated home HVAC.\n'+dump(z))
 return {'household_id':hid,'variant':variant,'IDF_path':str(p.relative_to(OUT)),'IDF_sha256':sha(p),'weather':r['weather'],'model':model,'paired_indoor_reference':indoor,'indoor_superhigh_flow_m3h':flow,'indoor_rated_input_W':fan,'ISO_dehumidification_Lh':dehum,'ISO_inferred_SHR_held_as_design':shr,
  'room_id':rid,'historical_report_reference_id':candidate['report_reference_id'],'capacity_match_not_observed_hardware_identity':True,
  'controller':'declared nominal-frequency duty hysteresis26C±0.25C,shift28C19to20July2;not original inverter governor','latent_split_outside_ISO_is_design_not_observed_function':True,
  'meter_scope':'active total-set electrical input;unknown standby/offstate explicitly excluded;indoor fan not double-added','fan_input_is_included_in_total_set_P_not_assumed_zero':True,
  'indoor_airflow_reported_but_not_modelled_refrigerant_airside_network':True,'other_household_ACs_not_assumed_absent':True,'technical_controller_context_not_actual_household_permission_or_willingness':True,'timestep_minutes':1 if refined else 15,'uniform_one_minute_execution':uniform}
def run(r):
 folder=OUT/('coupled_uniform_minute_runs' if r.get('uniform_one_minute_execution') else 'coupled_minute_runs' if r['timestep_minutes']==1 else 'coupled_runs')/(r['household_id']+'_'+r['variant']);folder.mkdir(parents=True,exist_ok=True);p=OUT/r['IDF_path'];s=subprocess.run([str(ENGINE),'-w',r['weather']['path'],'-d',str(folder),str(p)],capture_output=True,text=True,timeout=300);(folder/'console.txt').write_text(s.stdout+'\n'+s.stderr);err=(folder/'eplusout.err').read_text();sf=re.findall(r'\*\*\s*(?:Severe|Fatal)\s*\*\*([^\n]*)',err);res={**r,'returncode':s.returncode,'severe_fatal':sf,'warnings':re.findall(r'\*\*\s*Warning\s*\*\*([^\n]*)',err),'engine_sha256':sha(ENGINE),'weather_sha256':sha(r['weather']['path'])}
 if s.returncode or sf:return res
 sql=folder/'eplusout.sql';db=sqlite3.connect(sql);rows=db.execute('SELECT d.KeyValue,d.Name,d.Units,t.TimeIndex,t.Month,t.Day,t.Hour,t.Minute,r.Value FROM ReportData r JOIN ReportDataDictionary d USING(ReportDataDictionaryIndex) JOIN Time t USING(TimeIndex) WHERE COALESCE(t.WarmupFlag,0)=0 ORDER BY t.TimeIndex').fetchall();db.close();series=collections.defaultdict(dict)
 for key,n,u,i,m,d,h,mi,v in rows:series[n,key][i]=[m,d,h,mi,v]
 def get(n):return next(v for (nn,k),v in series.items() if nn==n)
 E=get('Electric Equipment Electricity Energy') if r['household_id'].upper()+'_ACTIVE_PACKAGE_POWER' not in [k for n,k in series if n=='Electric Equipment Electricity Energy'] else series['Electric Equipment Electricity Energy',r['household_id'].upper()+'_ACTIVE_PACKAGE_POWER'];P=get('Reference Package Active Power');Q=get('Reference Net Cooling Rate');WB=get('Reference WB');O=get('Reference Outdoor DB');bad=get('Reference Outside Source Domain');demand=get('Reference Requested Cooling');cool=get('Other Equipment Total Heating Energy');assert set(E)==set(P)==set(Q)==set(bad)
 data=read(OUT/'HVAC_SOURCE_KERNEL.json');checks=[]
 for i,x in P.items():
  dt=60*r['timestep_minutes'];assert abs(E[i][-1]-x[-1]*dt)<1e-6 and abs(cool[i][-1]-Q[i][-1]*dt)<1e-6
  if x[-1]>0:
   e=evaluate(data,r['model'],WB[i][-1],O[i][-1]);checks.append(max(abs(x[-1]-e['total_set_electric_input_W_reference']),abs(Q[i][-1]+e['cooling_capacity_W_reference'])))
 full=[i for i,v in E.items() if v[:2]==[7,2]];event=[i for i in full if 19*60<E[i][2]*60+E[i][3]<=20*60];outside=sum(bad[i][-1]>0 for i in full);demandn=sum(demand[i][-1]>0 for i in full);active=sum(P[i][-1]>0 for i in full)
 # Same pre-intervention thermal/source-control history, including actual
 # source-domain failures, must be equal before the first command divergence.
 states={str((n,k)):[v for i,v in vals.items() if v[:2]==[7,2] and v[2]*60+v[3]<=19*60] for (n,k),vals in series.items() if n in ['Zone Mean Air Temperature','Zone Air Humidity Ratio','Reference Package Active Power','Reference WB','Reference Outside Source Domain']}
 state_hash=hashlib.sha256(json.dumps(states,sort_keys=True,separators=(',',':'),allow_nan=False).encode()).hexdigest()
 res.update({'SQL_path':str(sql.relative_to(OUT)),'SQL_sha256':sha(sql),'all_active_kernel_power_checks':len(checks),'max_absolute_source_kernel_check_error_W':max(checks,default=0.),'active_steps_July2':active,'demand_steps_July2':demandn,'unsupported_demand_steps_July2':outside,
  'day_active_energy_kWh':sum(E[i][-1] for i in full)/3.6e6,'event_active_energy_kWh':sum(E[i][-1] for i in event)/3.6e6,'source_domain_complete_for_requested_day':outside==0,'at_least_one_active_step':active>0,'pre_intervention_states':state_hash,'prehistory_digest_definition':'canonical sorted JSON of every named pre-intervention state series;raw SQL retained',
  'not_measured_hardware_or_latent_curve_or_auto_controller_validated':True});assert res['max_absolute_source_kernel_check_error_W']<1e-6
 return res
def main():
 guard();records={r['household_id']:r for r in read(OUT/'OCCUPIED_REFERENCE_BINDINGS1000.json')['records']};candidates=read(OUT/'ADDITIONAL_HVAC_PARAMETER_CANDIDATES1000.json')['records'];tasks=[]
 refined='--refine-failed' in sys.argv;uniform='--uniform-minute' in sys.argv;failed_ids={r['household_id'] for r in read(OUT/'COUPLED_RUNTIME_RESULTS.json')['failures']} if refined else None
 for c in candidates:
  if not c['supported_reference_parameter_candidates']:continue
  if refined and c['household_id'] not in failed_ids:continue
  candidate=c['supported_reference_parameter_candidates'][0]
  tasks.extend(append_model(records[c['household_id']],candidate,v) for v in ['baseline','shifted'])
 save(OUT/('COUPLED_UNIFORM_MINUTE_BINDINGS.json' if uniform else 'COUPLED_REFINED_BINDINGS.json' if refined else 'COUPLED_REFERENCE_BINDINGS.json'),{'records':tasks,'reference_households':len(tasks)//2,'selected_one_parameter_port_per_supported_role_before_outputs':True,'primary_indoor_source':'raw/Mitsubishi_OBH788.pdfp4,p12','primary_outdoor_source':'raw/Mitsubishi_OBH789.pdfp6,p15–16','refrigerant_or_airside_network_model':False,'refinement_if_any_selected_all_original_numerical_failures':refined,'uniform_one_minute_all437':uniform})
 selected=tasks
 if '--pilot4' in sys.argv:
  ids={}
  for r in tasks:ids.setdefault(r['model'],r['household_id'])
  selected=[r for r in tasks if r['household_id'] in ids.values()];assert len(selected)==8
 res=[]
 with concurrent.futures.ThreadPoolExecutor(4) as pool:
  for i,r in enumerate(pool.map(run,selected)):
   res.append(r)
   if (i+1)%100==0:print({'coupled_runs_completed':i+1,'planned':len(selected)},flush=True)
 grouped=collections.defaultdict(dict);pairs=[]
 for r in res:grouped[r['household_id']][r['variant']]=r
 for hid,g in grouped.items():
  a,b=g['baseline'],g['shifted']
  if a['returncode'] or b['returncode'] or a['severe_fatal'] or b['severe_fatal']:continue
  assert a['pre_intervention_states']==b['pre_intervention_states'],'coupled_pair_history_not_equal:'+hid
  supported=a['source_domain_complete_for_requested_day'] and b['source_domain_complete_for_requested_day'];active=a['at_least_one_active_step'] or b['at_least_one_active_step']
  pairs.append({'household_id':hid,'pre_intervention_history_equal':True,'source_domain_complete_both_variants':supported,'at_least_one_active_step':active,'active_package_event_change_kWh':a['event_active_energy_kWh']-b['event_active_energy_kWh'],
   'physical_source_QP_label_admitted_for_this_declared_emulator':supported and active,'out_of_domain_or_inactive_cases_retained':True,'comfort_adequacy_or_actor_consent_label':None})
 save(OUT/('COUPLED_UNIFORM_MINUTE_RESULTS.json' if uniform else 'COUPLED_REFINED_RESULTS.json' if refined else 'COUPLED_FIRST4_DEVELOPMENT.json' if '--pilot4' in sys.argv else 'COUPLED_RUNTIME_RESULTS.json'),{'runs':res,'pairs':pairs,'inputs_run':len(res),'failures':[r for r in res if r['returncode'] or r['severe_fatal']],'source_domain_complete_and_active_pairs':sum(p['physical_source_QP_label_admitted_for_this_declared_emulator'] for p in pairs),'full_OEM_HVAC_or_national_real_energy_validation':False,'timestep_refinement_of_all_failed_profiles_not_threshold_relaxation':refined,'uniform_one_minute_all437':uniform})
 print({'run':len(res),'failures':sum(bool(r['returncode'] or r['severe_fatal']) for r in res),'pairs':len(pairs),'admitted_bounded_QP_pairs':sum(p['physical_source_QP_label_admitted_for_this_declared_emulator'] for p in pairs)},flush=True)
if __name__=='__main__':main()
