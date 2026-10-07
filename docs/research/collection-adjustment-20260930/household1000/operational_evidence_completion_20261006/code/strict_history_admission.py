"""Stricter scientific mask requires Q/P support over both reported days.
Do not rewrite original evaluation-day masks or simulated energy outcomes.
"""
import sqlite3,collections
from common import *
def main():
 guard();c=read(OUT/'COUPLED_UNIFORM_MINUTE_RESULTS.json');history={};raw=[]
 for r in c['runs']:
  db=sqlite3.connect(OUT/r['SQL_path']);idx=db.execute('SELECT ReportDataDictionaryIndex FROM ReportDataDictionary WHERE Name="Reference Outside Source Domain"').fetchone()[0];bad=db.execute('SELECT count(*) FROM ReportData r JOIN Time t USING(TimeIndex) WHERE r.ReportDataDictionaryIndex=? AND COALESCE(t.WarmupFlag,0)=0 AND r.Value>0',(idx,)).fetchone()[0];db.close();history[r['household_id'],r['variant']]=bad==0;raw.append({'household_id':r['household_id'],'variant':r['variant'],'reported_history_unsupported_steps':bad})
 rows=[]
 for p in c['pairs']:
  hid=p['household_id'];both=history[hid,'baseline'] and history[hid,'shifted'];strict=both and p['at_least_one_active_step'];rows.append({'household_id':hid,'all437_numerically_clean':True,'evaluation_day_QP_active_mask':p['physical_source_QP_label_admitted_for_this_declared_emulator'],'both_reported_history_days_QP_supported':both,'at_least_one_evaluation_day_active_step':p['at_least_one_active_step'],'strict_source_history_QP_label_admitted':strict,'reference_event_change_kWh':p['active_package_event_change_kWh'],'full_OEM_latent_auto_control_or_measured_initialstate_not_validated':True})
 strictn=sum(r['strict_source_history_QP_label_admitted'] for r in rows);assert strictn==read(OUT/'INDEPENDENT_UNIFORM_MINUTE_VERIFICATION.json')['admitted_pairs_source_supported_for_both_reported_history_days']==133
 save(OUT/'STRICT_HVAC_HISTORY_ADMISSION437.json',{'records':rows,'run_source_gap_counts':raw,'attempted_households':437,'evaluation_day_active_supported':141,'both_reported_history_days_and_active_strict_admitted':strictn,'evaluation_day_only8_not_promoted_to_full_history_source_valid':141-strictn,'strict_admitted_zero_event_changes_retained':sum(r['strict_source_history_QP_label_admitted'] and abs(r['reference_event_change_kWh'])<1e-9 for r in rows),'numerical_warmup_not_measured_source_history':True,'source_QP_validation_not_full_HVAC_or_humanvalidity':True})
 print({'attempted':437,'eventday_mask':141,'strict_history_mask':strictn,'historyunsupported_eventday8_retained':8},flush=True)
if __name__=='__main__':main()
