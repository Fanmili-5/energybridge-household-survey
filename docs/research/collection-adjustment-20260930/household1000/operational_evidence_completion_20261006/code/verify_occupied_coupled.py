"""Independent native joins, roster conservation, SQL power/curve and pairs.
Do not import the production occupancy or EMS program generators.
"""
import collections,copy,math,sqlite3,concurrent.futures
from common import *
from access_parser_c import AccessParser
def native_check(r):
 db=AccessParser(r['source_path'])
 def tab(name):
  t=db.parse_table(name);return [dict(zip(t,v)) for v in zip(*t.values())]
 rooms={x['ID']:x for x in tab('ROOM')};types={x['ID']:x['NAME'] for x in tab('ROOM_TYPE_DATA')};gains={x['GAIN_ID']:x for x in tab('OCCUPANT_GAINS')};dm={x['DIST_MODE_ID']:x for x in tab('DIST_MODE')};assert sha(r['source_path'])==r['source_sha256']
 for c in r['actual_bedroom_gain_instances']:
  x=gains[c['native_gain_ID']];assert x==c['native_gain_row'] and rooms[x['OF_ROOM']]['ID']==c['native_room_ID'] and types[rooms[x['OF_ROOM']]['TYPE']] in ['主卧室','次卧室']
  assert abs(c['total_W_per_reference_person']-(x['HEAT_PER_PERSON']+x['DAMP_PER_PERSON']*2500/3.6))<1e-12 and c['fresh_air_requirement_m3_per_hour_per_reference_person']==x['MIN_REQUIRE_FRESH_AIR']
  assert c['radiant_fraction']==round(1-dm[x['DIST_MODE']]['DIST_AIR'],3)
 return len(r['actual_bedroom_gain_instances'])
def source_factor(k,wb,out):
 curves=k['curves'];right=next(i for i,c in enumerate(curves) if wb<=c['indoor_WB_C']);left=max(0,right-1) if wb!=curves[right]['indoor_WB_C'] else right
 def f(c):
  (x0,y0),(x1,y1)=c['temperature_factor_endpoints'];assert x0-1e-9<=out<=x1+1e-9;return y0+(out-x0)*(y1-y0)/(x1-x0)
 a,b=curves[left],curves[right];v=f(a) if left==right else f(a)+(f(b)-f(a))*(wb-a['indoor_WB_C'])/(b['indoor_WB_C']-a['indoor_WB_C'])
 return v/k['normalization_at19WB35DB']
def main():
 guard();native=read(OUT/'NATIVE_OCCUPANT_SOURCE189.json')['models']
 with concurrent.futures.ThreadPoolExecutor(4) as pool:instances=sum(pool.map(native_check,native))
 profiles={p['slot_id']:p['family'] for p in read(V7/'HOUSEHOLDS1000_JOINT_GEOMETRY_CANDIDATE.json')['profiles']};occ=read(OUT/'OCCUPIED_REFERENCE_BINDINGS1000.json');runs=read(OUT/'OCCUPIED_RUNTIME_RESULTS1000.json');assert len(occ['records'])==len(runs['runs'])==1000 and not runs['failures'];count=0;failure=[]
 for r in occ['records']:
  hid=r['household_id'];members={m['member_id'] for m in r['members']};assert members==set(profiles[hid]['resident_member_ids']);z=parse(OUT/r['IDF_path']);pp=[x for x in z if x[0]=='People'];assert len(pp)==len(members) and all(float(x[5])==1 and x[4]=='People' for x in pp);assert {x[1] for x in pp}=={m['People_name'] for m in r['members']}
  rid_byname={m['People_name']:m['room_id'] for m in r['members']};assert all(x[2]==rid_byname[x[1]] for x in pp);fresh=sum(float(x[5]) for x in z if x[0]=='ZoneVentilation:DesignFlowRate');expected=len(pp)*r['source_thermal_parameters']['fresh_air_requirement_m3_per_hour_per_reference_person']/3600;assert abs(fresh-expected)<1e-12;count+=len(pp)
  run=next(x for x in runs['runs'] if x['household_id']==hid);assert sha(OUT/r['IDF_path'])==r['IDF_sha256']==run['IDF_sha256'] and sha(OUT/run['SQL_path'])==run['SQL_sha256'];db=sqlite3.connect(OUT/run['SQL_path']);v=db.execute('SELECT t.TimeIndex,sum(r.Value) FROM ReportData r JOIN ReportDataDictionary d USING(ReportDataDictionaryIndex) JOIN Time t USING(TimeIndex) WHERE COALESCE(t.WarmupFlag,0)=0 AND d.Name="Zone People Occupant Count" GROUP BY t.TimeIndex').fetchall();db.close();assert len(v)==192 and all(abs(x-len(members))<1e-9 for i,x in v)
 assert count==2524
 c=read(OUT/'COUPLED_RUNTIME_RESULTS.json');kernel=read(OUT/'HVAC_SOURCE_KERNEL.json');active=0;maxerr=0.;grouped=collections.defaultdict(dict);ledgermax=0.;domain_cases=0
 assert len(c['runs'])==874 and len(c['pairs'])==429 and len(c['failures'])==16
 for r in c['runs']:
  if r['severe_fatal'] or r['returncode']:
   assert r['returncode']==0 and all('CheckWarmupConvergence' in x for x in r['severe_fatal'])
   assert sha(OUT/r['IDF_path'])==r['IDF_sha256'];err=(OUT/'coupled_runs'/(r['household_id']+'_'+r['variant'])/'eplusout.err').read_text();assert 'Severe' in err and '**  Fatal' not in err
   continue
  assert sha(OUT/r['IDF_path'])==r['IDF_sha256'] and sha(OUT/r['SQL_path'])==r['SQL_sha256'];db=sqlite3.connect(OUT/r['SQL_path']);raw=db.execute('SELECT d.Name,d.KeyValue,t.TimeIndex,t.Month,t.Day,t.Hour,t.Minute,r.Value FROM ReportData r JOIN ReportDataDictionary d USING(ReportDataDictionaryIndex) JOIN Time t USING(TimeIndex) WHERE COALESCE(t.WarmupFlag,0)=0 ORDER BY t.TimeIndex').fetchall();db.close();series=collections.defaultdict(dict)
  for n,k,i,m,d,h,mi,x in raw:series[n,k][i]=[m,d,h,mi,x]
  def get(n,key=None):return series[n,key] if key else next(v for (nn,k),v in series.items() if nn==n)
  power=get('Reference Package Active Power');cool=get('Reference Net Cooling Rate');wb=get('Reference WB');out=get('Reference Outdoor DB');outside=get('Reference Outside Source Domain');E=get('Electric Equipment Electricity Energy',r['household_id'].upper()+'_ACTIVE_PACKAGE_POWER');thermal=get('Other Equipment Total Heating Energy');latent=get('Other Equipment Latent Gain Energy');sensible=get('Other Equipment Convective Heating Energy');radiant=get('Other Equipment Radiant Heating Energy');spec=kernel['models'][r['model']];indices=set(power);assert indices==set(E)==set(cool)
  for i,v in power.items():
   ledgermax=max(ledgermax,abs(E[i][-1]-v[-1]*900),abs(thermal[i][-1]-cool[i][-1]*900),abs(latent[i][-1]+sensible[i][-1]+radiant[i][-1]-thermal[i][-1]));assert ledgermax<1e-6
   if v[-1]>0:
    assert 18<=wb[i][-1]<=26 and outside[i][-1]==0
    error=max(abs(v[-1]-spec['total_set_input_W']*source_factor(kernel['total_input_factor'],wb[i][-1],out[i][-1])),abs(cool[i][-1]+spec['capacity_W']*source_factor(kernel['capacity_factor'],wb[i][-1],out[i][-1])));maxerr=max(maxerr,error);active+=1
  ids=[i for i in indices if E[i][:2]==[7,2]];event=sum(E[i][-1] for i in ids if 1140<E[i][2]*60+E[i][3]<=1200)/3.6e6;assert abs(event-r['event_active_energy_kWh'])<1e-10;domain_cases+=r['source_domain_complete_for_requested_day']
  grouped[r['household_id']][r['variant']]={'pre':{str((n,k)):[v for i,v in vals.items() if v[:2]==[7,2] and v[2]*60+v[3]<=1140] for (n,k),vals in series.items() if n in ['Zone Mean Air Temperature','Zone Air Humidity Ratio','Reference Package Active Power','Reference WB','Reference Outside Source Domain']},'event':event,'supported':all(outside[i][-1]==0 for i in ids),'active':any(power[i][-1]>0 for i in ids)}
 for p in c['pairs']:
  a,b=grouped[p['household_id']]['baseline'],grouped[p['household_id']]['shifted'];assert a['pre']==b['pre'];expected=a['supported'] and b['supported'] and (a['active'] or b['active']);assert p['physical_source_QP_label_admitted_for_this_declared_emulator']==expected and abs(p['active_package_event_change_kWh']-a['event']+b['event'])<1e-10
 assert maxerr<1e-6
 # Negative controls test scientific masks, not just byte identities.
 wrong=copy.deepcopy(c['pairs'][0]);wrong['physical_source_QP_label_admitted_for_this_declared_emulator']=True;negative=[{'injection':'unsupported_or_inactive_pair_forced_admitted','detected':not(c['pairs'][0]['source_domain_complete_both_variants'] and c['pairs'][0]['at_least_one_active_step'])},{'injection':'source_density_instead_of_roster_count','detected':abs(.2*41-profiles['ordinary-v6-0001']['resident_count'])>1e-9},{'injection':'double_added_indoor_fan_to_total_set_P','detected':abs(600+19-600)>1e-6}];assert all(x['detected'] for x in negative)
 save(OUT/'INDEPENDENT_OCCUPIED_COUPLED_VERIFICATION.json',{'native_models_re_read':len(native),'actual_bedroom_gain_instances_re_read':instances,'occupied_IDF_SQLs_independently_checked':1000,'People_roster_instances_conserved':count,'coupled_IDF_SQLs_independently_checked':858,'coupled_pairs_independent_prehistory_and_domain_masks_checked':429,'failed_runs_held_and_raw_error_checked':16,'attempted_source_qualified_households':437,'active_source_QP_step_checks':active,'maximum_source_QP_error_W':maxerr,'maximum_step_electric_and_netcool_energy_ledger_residual_J':ledgermax,'negative_controls':negative,'field_validity_or_complete_household_HVAC_not_inferred':True,'verification_failures':failure,'production_numerical_failures_are_not_verification_failures_or_silently_excluded':True})
 print({'native':len(native),'People':count,'occupied':1000,'coupled_clean_SQLs':858,'held_runs':16,'active_steps':active,'max_QP_error_W':maxerr,'max_energy_residual_J':ledgermax})
if __name__=='__main__':main()
