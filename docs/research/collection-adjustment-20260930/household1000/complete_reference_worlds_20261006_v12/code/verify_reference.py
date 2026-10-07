"""Independent geometry/SQL/accounting/role/scope checks,not realworldproof."""
import collections,copy,csv,sqlite3,math
from common import *
def packet_issues(p,profile):
 issues=[];f=p['public']['role_facts'];family=profile['family'];n=family['resident_count']
 if f['resident_count']!=n or f['generation_count']!=family['generation_count']:issues.append('N_G_changed')
 if len(f['public_members'])!=n:issues.append('member_count')
 if p['human_answers'] is not None or p['human_review_complete']:issues.append('invented_human_data')
 if p['complete_actual_lifeworld']:issues.append('reference_as_actual_lifeworld')
 if any(k in str(p['public']) for k in ['event_cooling_demand_change_kWh','reference_air_service_met','engine_energy_kWh']):issues.append('postevent_oracle_leak')
 c=p['public']['given_reference_context'];adult={m['local_member_id'] for m in f['public_members'] if m['age_reference']>=18}
 if c['operator_local_member_id'] is not None and c['operator_local_member_id'] not in adult:issues.append('operator_not_adult')
 return issues
def read_sql(p):
 db=sqlite3.connect(p);a=db.execute('SELECT d.KeyValue,d.Name,t.TimeIndex,t.Month,t.Day,t.Hour,t.Minute,r.Value FROM ReportData r JOIN ReportDataDictionary d USING(ReportDataDictionaryIndex) JOIN Time t USING(TimeIndex) WHERE COALESCE(t.WarmupFlag,0)=0 ORDER BY t.TimeIndex').fetchall();meter=db.execute('SELECT sum(r.VariableValue) FROM ReportMeterData r JOIN ReportMeterDataDictionary d USING(ReportMeterDataDictionaryIndex) JOIN Time t USING(TimeIndex) WHERE COALESCE(t.WarmupFlag,0)=0 AND t.Month=7 AND t.Day=20 AND d.VariableName="Electricity:Facility" AND d.ReportingFrequency="Zone Timestep"').fetchone()[0];db.close();s=collections.defaultdict(dict)
 for k,n,i,m,d,h,mi,v in a:s[n,k][i]=[m,d,h,mi,v]
 return s,meter
def before(s):return {str(k):[v for i,v in d.items() if v[:2]==[7,20] and v[2]*60+v[3]<=1140] for k,d in s.items() if k[0] in ['Zone Mean Air Temperature','Zone Air Relative Humidity','Zone People Occupant Count','Zone Ideal Loads Supply Air Total Cooling Energy','Zone Ideal Loads Supply Air Total Heating Energy']}
def cooling(s):return sum(v[-1] for (n,k),d in s.items() if n=='Zone Ideal Loads Supply Air Total Cooling Energy' for v in d.values() if v[:2]==[7,20] and 1140<v[2]*60+v[3]<=1200)/3.6e6
def main():
 guard();profiles={p['slot_id']:p for p in read(V7/'HOUSEHOLDS1000_JOINT_GEOMETRY_CANDIDATE.json')['profiles']};models=read(OUT/'BACKGROUND_MODEL_BINDINGS1000.json')['records'];base={r['household_id']:r for r in read(OUT/'BACKGROUND_RUNTIME1000.json')['runs']};shift={r['household_id']:r for r in read(OUT/'THERMAL_PAIR_RESULTS1000.json')['runs']};pairs={r['household_id']:r for r in read(OUT/'THERMAL_PAIR_RESULTS1000.json')['pairs']};assert len(models)==len(base)==len(shift)==len(pairs)==1000;areaerr=0.;metererr=0.;count=0
 for j,r in enumerate(models):
  hid=r['household_id'];a,b=base[hid],shift[hid];assert not a['severe_fatal'] and not b['severe_fatal'];z=parse(OUT/r['IDF_path']);pp=[x for x in z if x[0]=='People'];assert len(pp)==profiles[hid]['family']['resident_count'] and all(x[4]=='People' and float(x[5])==1 for x in pp);count+=len(pp);zones={x[1] for x in z if x[0]=='Zone'};lights=[x for x in z if x[0]=='Lights'];eq=[x for x in z if x[0]=='ElectricEquipment'];assert len(lights)==len(eq)==len(zones) and not any(x[0]=='WaterHeater:Mixed' for x in z);geometry={}
  fs=SCHEMA['properties']['BuildingSurface:Detailed']['legacy_idd']['fields'];zi=fs.index('zone_name')+1;vi=fs.index('number_of_vertices')+1
  for row in z:
   if row[0]!='BuildingSurface:Detailed' or row[2]!='Floor':continue
   vals=[float(x) for x in row[vi+1:]];xy=[vals[i:i+3] for i in range(0,len(vals),3)];assert len(xy)==int(row[vi]);ar=abs(sum(xy[i][0]*xy[(i+1)%len(xy)][1]-xy[(i+1)%len(xy)][0]*xy[i][1] for i in range(len(xy))))/2;geometry[row[zi]]=geometry.get(row[zi],0.)+ar
  for c in r['components']:areaerr=max(areaerr,abs(geometry[c['room_id']]-c['input_floor_area_m2']));assert abs(geometry[c['room_id']]-c['input_floor_area_m2'])<1e-6
  for rec in [a,b]:assert sha(OUT/rec['IDF_path'])==rec['IDF_sha256'] and sha(OUT/rec['SQL_path'])==rec['SQL_sha256']
  sa,ma=read_sql(OUT/a['SQL_path']);sb,mb=read_sql(OUT/b['SQL_path']);assert before(sa)==before(sb);assert abs(cooling(sa)-cooling(sb)-pairs[hid]['event_cooling_demand_change_kWh_thermal'])<1e-9 and pairs[hid]['event_electricity_change_kWh'] is None
  expected=0.;buckets=collections.defaultdict(float)
  for c in r['components']:
   # Recompute from actual IDF power levels,not the builder's expectedvalues.
   l=next(x for x in lights if x[1]==c['Light_name']);e=next(x for x in eq if x[1]==c['aggregate_plug_name']);watts=float(l[5])+float(e[5]);El=watts*4/1000;expected+=El;buckets[c['energy_scope_bucket']]+=El
   for s in [sa,sb]:
    actual=sum(v[-1] for (n,k),d in s.items() if (n=='Lights Electricity Energy' and k==l[1].upper()) or (n=='Electric Equipment Electricity Energy' and k==e[1].upper()) for v in d.values() if v[:2]==[7,20])/3.6e6;assert abs(actual-El)<1e-8
  metererr=max(metererr,abs(ma/3.6e6-expected),abs(mb/3.6e6-expected));assert metererr<1e-8 and abs(sum(buckets.values())-expected)<1e-8
  if not b['enabled']:assert abs(pairs[hid]['event_cooling_demand_change_kWh_thermal'])<1e-9
  if (j+1)%250==0:print({'independent_background_pairs_checked':j+1},flush=True)
 assert count==2524
 bindings=read(OUT/'COLLECTION_BINDINGS1000.json')['records'];fail=[]
 for r in bindings:
  hid=r['household_id']
  for pk,hk in [('packet_path','packet_sha256'),('card_path','card_sha256'),('questionnaire_path','questionnaire_sha256'),('private_labels_path','private_labels_sha256'),('provenance_path','provenance_sha256')]:assert sha(OUT/r[pk])==r[hk]
  p=read(OUT/r['packet_path']);errs=packet_issues(p,profiles[hid]);assert not errs;qs=read(OUT/r['questionnaire_path']);assert len(qs['questions'])==7 and all(v is None for v in qs['answer_template'].values());priv=read(OUT/r['private_labels_path']);assert priv['human_answer'] is None and priv['actor_preference'] is None and priv['model_labels']==pairs[hid];assert len(p['public']['given_reference_context']['member_room_bindings'])==profiles[hid]['family']['resident_count'];assert '成员关系' in (OUT/r['card_path']).read_text()
 projected=read(OUT/'MODEL_INPUT_PROJECTION1000.json')['records'];assert len(projected)==1000
 for r in projected:
  assert r['role_id_linkage_only'] not in str(r['model_input']) and r['numeric_outcome_or_humananswer'] is None;f=r['model_input']['role_facts'];assert len(f['public_members'])==f['resident_count']
 first=bindings[0];p=read(OUT/first['packet_path']);q=copy.deepcopy(p);q['human_answers']={'decision':'accept'};negative=[{'injection':'fakehumananswer','detected':'invented_human_data' in packet_issues(q,profiles[first['household_id']])}];q=copy.deepcopy(p);q['public']['event_cooling_demand_change_kWh']=3.;negative.append({'injection':'thermaloracleleak','detected':'postevent_oracle_leak' in packet_issues(q,profiles[first['household_id']])});q=copy.deepcopy(p);q['complete_actual_lifeworld']=True;negative.append({'injection':'referenceasactuallifeworld','detected':'reference_as_actual_lifeworld' in packet_issues(q,profiles[first['household_id']])});q=copy.deepcopy(p);q['public']['role_facts']['resident_count']+=1;negative.append({'injection':'Nchangedfordensity','detected':'N_G_changed' in packet_issues(q,profiles[first['household_id']])});assert all(x['detected'] for x in negative)
 save(OUT/'INDEPENDENT_REFERENCE_VERIFICATION.json',{'background_IDF_SQLs_checked':1000,'shifted_IDF_SQLs_checked':1000,'paired_states_thermal_unit_and_private_manual_gate_checked':1000,'fixed_roster_people_conserved':count,'maximum_floor_polygon_area_difference_m2':areaerr,'maximum_model_electricity_ledger_residual_kWh':metererr,'role_packet_questionnaire_private_ledger_groups_checked':1000,'identityfree_model_inputs_checked':1000,'negative_controls':negative,'verification_failures':fail,'actual_national_wholehome_orhumanvalidity_not_inferred':True});print({'background_and_shifted_SQLs':2000,'people':count,'packets':1000,'maxareaerror':areaerr,'maxmeterresidual_kWh':metererr,'negative_controls':len(negative)},flush=True)
if __name__=='__main__':main()
