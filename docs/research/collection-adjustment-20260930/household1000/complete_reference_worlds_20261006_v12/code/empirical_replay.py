"""Replay all148 completely observed14-channel days through electrical ports.
This validates units/time/integration transport,not newhousehold predictions,
HVAC/cycle mechanics,or wholehome/China calibration. No jointvalid day is
selected for high activity. Missing data never becomes0.
"""
import pandas as pd,collections,concurrent.futures,re,sqlite3,subprocess
from common import *
ENGINE=Path('/Applications/EnergyPlus-24-1-0/energyplus')
def run(task):
 day,frame,base,weather=task;name=str(day.date());folder=OUT/'empirical_replay'/name;folder.mkdir(parents=True,exist_ok=True);csv=folder/'power.csv';frame.to_csv(csv,index=False);z=parse(V10/base['IDF_path']);z=[x for x in z if x[0] not in ['RunPeriod','Output:Variable','Output:Meter']]
 for x in z:
  if x[0]=='Timestep':x[1]=60
 z += [obj('RunPeriod',{'name':'observed_power_day_'+name,'begin_month':day.month,'begin_day_of_month':day.day,'begin_year':day.year,'end_month':day.month,'end_day_of_month':day.day,'end_year':day.year,'day_of_week_for_start_day':day.day_name(),'treat_weather_as_actual':'No'}),['ScheduleTypeLimits','v12_replay_W',0,'','Continuous','Power'],obj('OutputControl:Files',{'output_eso':'No','output_mtr':'No','output_csv':'No'})]
 zone=next(x[1] for x in z if x[0]=='Zone');objects=[]
 for j,c in enumerate(frame.columns):
  schedule='observed_channel_'+str(j);port='metered_port_'+str(j);points=[]
  for minute,power in enumerate(frame[c].to_numpy(),1):points.extend([f'Until:{minute//60:02d}:{minute%60:02d}',float(power)])
  z.append(['Schedule:Compact',schedule,'v12_replay_W','Through:12/31','For:AllDays','Interpolate:No',*points]);z.append(obj('ElectricEquipment',{'name':port,'zone_or_zonelist_or_space_or_spacelist_name':zone,'schedule_name':schedule,'design_level_calculation_method':'EquipmentLevel','design_level':1,'fraction_latent':0,'fraction_radiant':0,'fraction_lost':1,'end_use_subcategory':'measured_replay_not_household_installedhardware'}));z.append(['Output:Variable',port,'Electric Equipment Electricity Energy','Timestep']);objects.append({'channel':c,'port':port,'source_day_energy_kWh':float(frame[c].sum()/60000)})
 z += [['Output:Meter','Electricity:Facility','Timestep']];idf=folder/'input.idf';idf.write_text('! 14measuredpowerchannels electrical-onlycalorimeter;not sourcehousegeometry/HVACtruth.\n'+dump(z));runfolder=folder/'run';runfolder.mkdir(exist_ok=True);x=subprocess.run([str(ENGINE),'-w',weather['path'],'-d',str(runfolder),str(idf)],capture_output=True,text=True,timeout=300);(runfolder/'console.txt').write_text(x.stdout+'\n'+x.stderr);err=(runfolder/'eplusout.err').read_text();sf=re.findall(r'\*\*\s*(?:Severe|Fatal)\s*\*\*([^\n]*)',err);assert x.returncode==0 and not sf,err
 db=sqlite3.connect(runfolder/'eplusout.sql');raw=db.execute('SELECT d.KeyValue,t.Hour,t.Minute,r.Value FROM ReportData r JOIN ReportDataDictionary d USING(ReportDataDictionaryIndex) JOIN Time t USING(TimeIndex) WHERE d.Name="Electric Equipment Electricity Energy" AND d.ReportingFrequency="Zone Timestep" AND COALESCE(t.WarmupFlag,0)=0 ORDER BY d.KeyValue,t.TimeIndex').fetchall();meter=db.execute('SELECT sum(r.VariableValue) FROM ReportMeterData r JOIN ReportMeterDataDictionary d USING(ReportMeterDataDictionaryIndex) JOIN Time t USING(TimeIndex) WHERE d.VariableName="Electricity:Facility" AND d.ReportingFrequency="Zone Timestep" AND COALESCE(t.WarmupFlag,0)=0').fetchone()[0]/3.6e6;db.close();series=collections.defaultdict(list)
 for key,h,m,v in raw:series[key].append([h,m,v])
 maxstep=0.
 for o in objects:
  vals=series[o['port'].upper()];assert len(vals)==1440;assert all(h*60+m==i+1 for i,(h,m,v) in enumerate(vals));expected=frame[o['channel']].to_numpy();error=max(abs(v-float(p)*60) for (h,m,v),p in zip(vals,expected));assert error<1e-7;maxstep=max(maxstep,error);o['engine_energy_kWh']=sum(v for h,m,v in vals)/3.6e6;assert abs(o['engine_energy_kWh']-o['source_day_energy_kWh'])<1e-9
 total=sum(o['source_day_energy_kWh'] for o in objects);assert abs(meter-total)<1e-9
 return {'source_date':name,'source_timezone':'UTC+08','ports':objects,'source14device_sum_kWh':total,'engine_facility_sum_kWh':meter,'max_step_integral_error_J':maxstep,'watts_not_kW_and_minute_interval_end_verified':True,'missing_samples_filled':0,'observed_source_wholehome_meter':None,'reference_geometry_only_calorimeter_not_source172_73m2duplex':True,'status':'accounting_transport_pass_not_simulated_household_prediction_validation','IDF_path':str(idf.relative_to(OUT)),'IDF_sha256':sha(idf),'SQL_path':str((runfolder/'eplusout.sql').relative_to(OUT)),'SQL_sha256':sha(runfolder/'eplusout.sql'),'source_csv_path':str(csv.relative_to(OUT)),'source_csv_sha256':sha(csv),'weather':weather,'engine_sha256':sha(ENGINE),'severe_fatal':0,'warnings':re.findall(r'\*\*\s*Warning\s*\*\*([^\n]*)',err)}
def main():
 guard();p=OUT/'raw/CN_OBEE/The CN-OBEE dataset/Power.csv';a=pd.read_csv(p,index_col='time',parse_dates=True);valid=a.notna().all(axis=1);d=valid.groupby(a.index.normalize()).agg(['sum','count']);days=list(d[(d['sum']==1440)&(d['count']==1440)].index);assert len(days)==148;source=read(V10/'JOINT_WORLD_BINDINGS.json')['records'][0];tasks=[(day,a.loc[day:day+pd.Timedelta(days=1)-pd.Timedelta(minutes=1)].copy(),source,source['weather']) for day in days];selected=tasks[:1] if '--first1' in sys.argv else tasks;res=[]
 with concurrent.futures.ThreadPoolExecutor(4) as pool:
  for i,r in enumerate(pool.map(run,selected)):
   res.append(r)
   if (i+1)%25==0:print({'observed_days_electrical_replayed':i+1,'planned':len(selected)},flush=True)
 save(OUT/('EMPIRICAL_REPLAY_FIRST1.json' if '--first1' in sys.argv else 'EMPIRICAL_REPLAY148.json'),{'observed_households':1,'days':len(res),'ports_per_day':14,'runs':res,'all_jointvalid_days_retained':True,'no_claim_of_original_geometry_thermalresponse_or_newhousehold_calibration':True});print({'days':len(res),'source_meter_day_cases':14*len(res),'max_error_J':max(r['max_step_integral_error_J'] for r in res)},flush=True)
if __name__=='__main__':main()
