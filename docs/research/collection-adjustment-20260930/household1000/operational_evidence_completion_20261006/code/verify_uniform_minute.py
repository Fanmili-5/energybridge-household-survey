"""Independent raw SQL check of final uniform-minute emulators and masks."""
import collections,hashlib,sqlite3
from common import *
from verify_occupied_coupled import source_factor
def step_issues(p,q,e,net,wb,out,bad,spec,kernel):
 issues=[]
 if abs(p*60-e)>1e-6 or abs(q*60-net)>1e-6:issues.append('same_step_energy_ledger')
 if bad>0 and (p!=0 or q!=0):issues.append('outside_domain_still_actuated')
 if p>0:
  try:
   if not 18<=wb<=26:raise ValueError('WB outside')
   qp=spec['capacity_W']*source_factor(kernel['capacity_factor'],wb,out);pp=spec['total_set_input_W']*source_factor(kernel['total_input_factor'],wb,out)
   if abs(pp-p)>1e-6 or abs(qp+q)>1e-6:issues.append('source_kernel_power')
  except (AssertionError,ValueError,StopIteration):issues.append('source_domain')
 return issues
def main():
 guard();c=read(OUT/'COUPLED_UNIFORM_MINUTE_RESULTS.json');assert len(c['runs'])==874 and len(c['pairs'])==437 and not c['failures'];kernel=read(OUT/'HVAC_SOURCE_KERNEL.json');grouped=collections.defaultdict(dict);active=0;maxerr=0.;residual=0.;coverage=collections.Counter();historyoutside=0;sample=None
 for r in c['runs']:
  assert r['timestep_minutes']==1 and r['uniform_one_minute_execution'] and sha(OUT/r['IDF_path'])==r['IDF_sha256'] and sha(OUT/r['SQL_path'])==r['SQL_sha256']
  db=sqlite3.connect(OUT/r['SQL_path']);raw=db.execute('SELECT d.Name,d.KeyValue,t.TimeIndex,t.Month,t.Day,t.Hour,t.Minute,r.Value FROM ReportData r JOIN ReportDataDictionary d USING(ReportDataDictionaryIndex) JOIN Time t USING(TimeIndex) WHERE COALESCE(t.WarmupFlag,0)=0 ORDER BY t.TimeIndex').fetchall();db.close();series=collections.defaultdict(dict)
  for n,k,i,m,d,h,mi,x in raw:series[n,k][i]=[m,d,h,mi,x]
  def get(n,key=None):return series[n,key] if key else next(v for (nn,k),v in series.items() if nn==n)
  P=get('Reference Package Active Power');Q=get('Reference Net Cooling Rate');WB=get('Reference WB');O=get('Reference Outdoor DB');bad=get('Reference Outside Source Domain');E=get('Electric Equipment Electricity Energy',r['household_id'].upper()+'_ACTIVE_PACKAGE_POWER');total=get('Other Equipment Total Heating Energy');conv=get('Other Equipment Convective Heating Energy');rad=get('Other Equipment Radiant Heating Energy');latent=get('Other Equipment Latent Gain Energy');spec=kernel['models'][r['model']];assert len(P)==2880 and set(P)==set(E)==set(Q)
  for i,x in P.items():
   assert not step_issues(x[-1],Q[i][-1],E[i][-1],total[i][-1],WB[i][-1],O[i][-1],bad[i][-1],spec,kernel)
   residual=max(residual,abs(x[-1]*60-E[i][-1]),abs(Q[i][-1]*60-total[i][-1]),abs(conv[i][-1]+rad[i][-1]+latent[i][-1]-total[i][-1]));assert residual<1e-6
   if bad[i][-1]>0:assert x[-1]==0 and Q[i][-1]==0
   if x[-1]>0:
    if sample is None:sample=[x[-1],Q[i][-1],E[i][-1],total[i][-1],WB[i][-1],O[i][-1],bad[i][-1],spec,kernel]
    assert bad[i][-1]==0 and 18<=WB[i][-1]<=26
    maxerr=max(maxerr,abs(x[-1]-spec['total_set_input_W']*source_factor(kernel['total_input_factor'],WB[i][-1],O[i][-1])),abs(Q[i][-1]+spec['capacity_W']*source_factor(kernel['capacity_factor'],WB[i][-1],O[i][-1])));active+=1
  ids=[i for i,x in E.items() if x[:2]==[7,2]];evt=sum(E[i][-1] for i in ids if 1140<E[i][2]*60+E[i][3]<=1200)/3.6e6;assert abs(evt-r['event_active_energy_kWh'])<1e-10
  states={str((n,k)):[v for i,v in vals.items() if v[:2]==[7,2] and v[2]*60+v[3]<=1140] for (n,k),vals in series.items() if n in ['Zone Mean Air Temperature','Zone Air Humidity Ratio','Reference Package Active Power','Reference WB','Reference Outside Source Domain']};h=hashlib.sha256(json.dumps(states,sort_keys=True,separators=(',',':'),allow_nan=False).encode()).hexdigest();assert h==r['pre_intervention_states']
  supported=all(bad[i][-1]==0 for i in ids);on=any(P[i][-1]>0 for i in ids);assert r['source_domain_complete_for_requested_day']==supported and r['at_least_one_active_step']==on
  historyoutside+=any(x[-1]>0 for x in bad.values());grouped[r['household_id']][r['variant']]={'pre':h,'event':evt,'supported':supported,'active':on,'history_supported':all(x[-1]==0 for x in bad.values())}
 for p in c['pairs']:
  a,b=grouped[p['household_id']]['baseline'],grouped[p['household_id']]['shifted'];assert a['pre']==b['pre'];expected=a['supported'] and b['supported'] and (a['active'] or b['active']);assert p['physical_source_QP_label_admitted_for_this_declared_emulator']==expected and abs(p['active_package_event_change_kWh']-a['event']+b['event'])<1e-10
  label='source_supported_active' if expected else 'source_supported_inactive' if a['supported'] and b['supported'] else 'outside_source_domain';coverage[label]+=1
 assert maxerr<1e-6
 # Eligibility is not positive-response filtering: zero and negative labels
 # remain in the admitted denominator. Wholehistory support is separately
 # reported, since only the declared evaluation day is used for admission.
 admitted=[p for p in c['pairs'] if p['physical_source_QP_label_admitted_for_this_declared_emulator']];hist=sum(grouped[p['household_id']]['baseline']['history_supported'] and grouped[p['household_id']]['shifted']['history_supported'] for p in admitted)
 assert sample is not None and not step_issues(*sample);neg=[];v=list(sample);v[0]+=19;v[2]=v[0]*60;neg.append({'injection':'indoor_fan_double_added_to_totalset_P_with_internally_consistent_meter','detected':'source_kernel_power' in step_issues(*v)});v=list(sample);v[6]=1;neg.append({'injection':'outside_domain_label_still_actuated','detected':'outside_domain_still_actuated' in step_issues(*v)});v=list(sample);v[2]=0;neg.append({'injection':'actual_meter_not_same_step_as_EMS','detected':'same_step_energy_ledger' in step_issues(*v)});assert all(x['detected'] for x in neg)
 save(OUT/'INDEPENDENT_UNIFORM_MINUTE_VERIFICATION.json',{'uniform_minutes':1,'IDF_SQLs_re_read':874,'paired_prehistories_independently_checked':437,'active_source_QP_step_checks':active,'maximum_source_QP_error_W':maxerr,'maximum_step_energy_residual_J':residual,'source_QP_coverage':dict(coverage),'admitted_zero_event_deltas_retained':sum(abs(p['active_package_event_change_kWh'])<=1e-9 for p in admitted),'admitted_negative_event_deltas_retained':sum(p['active_package_event_change_kWh']<-1e-9 for p in admitted),'admitted_pairs_source_supported_for_both_reported_history_days':hist,'source_admission_is_evaluation_day_only_not_empirical_historical_state_calibration':True,'runs_with_any_reported_history_source_gap':historyoutside,'negative_controls':neg,'verification_failures':[],'physical_latent_map_control_or_empirical_Chinaenergy_not_validated':True})
 print({'uniform_IDF_SQLs':874,'pairs':437,'coverage':dict(coverage),'history_supported_admitted':hist,'QP_error_W':maxerr,'ledger_residual_J':residual,'active_checks':active},flush=True)
if __name__=='__main__':main()
