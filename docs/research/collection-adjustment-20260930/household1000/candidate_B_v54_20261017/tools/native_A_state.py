"""Actual-shell indoor-feedback functional probe; not complete benchmark physics."""
import argparse,collections,re,subprocess,sqlite3,sys,gzip
from pathlib import Path
DEST=Path(__file__).resolve().parents[1]
STAGE=DEST.parent/'normal_A_v46_20261017';sys.path.insert(0,str(STAGE/'code'))
from common import *
from hvac import obj,ROWS
from activity_model import resident_slot
from functools import lru_cache
read=lru_cache(maxsize=6)(read)
A_ROWS={r["household_id"]:r for r in read(STAGE/"A_BINDINGS10000.json")["records"]}
M_ROWS={r["household_id"]:r for r in read(MASTER/"WORLD_BINDINGS1000.json")["records"]}

def compact(name,days,default=0):
    days={dt.date(2025,d.month,d.day):values for d,values in days.items()};row=['Schedule:Compact',name,'probe_any'];first=min(days);last=max(days)
    def sequence(values):
        r=[]
        for i,v in enumerate(values):
            if i==len(values)-1 or v!=values[i+1]:
                end=(i+1)*10;r.extend([f'Until: {end//60:02d}:{end%60:02d}',v])
        return r
    if first>dt.date(first.year,1,1):
        pre=first-dt.timedelta(days=1);row +=[f'Through: {pre.month}/{pre.day}','For: AllDays','Until: 24:00',default]
    for date,values in sorted(days.items()):row +=[f'Through: {date.month}/{date.day}','For: AllDays']+sequence(values)
    if last<dt.date(last.year,12,31):row +=['Through: 12/31','For: AllDays','Until: 24:00',default]
    return row

def build(hid,date):
    a=A_ROWS[hid]
    m=M_ROWS[hid]
    w=read(STAGE/a['A_world_path']);y=read(STAGE/a['annual_A_path']);packages=read(STAGE/a['HVAC_components_path'])
    start=date-dt.timedelta(days=7);end=date+dt.timedelta(days=2);dates_=[start+dt.timedelta(days=i)for i in range(10)]
    shell=MASTER/m['background_IDF_path'];rows=[[x.strip()for x in s.split(',')]for s in re.sub(r'!.*','',shell.read_text()).split(';')if s.strip()]
    rows=[r for r in rows if r[0]not in('RunPeriod','Timestep','SimulationControl')and not r[0].startswith('Output:')]
    rows +=[['Timestep',6],['SimulationControl','No','No','No','No','Yes'],['RunPeriod','indoor_feedback_functional_probe',start.month,start.day,start.year,end.month,end.day,end.year,start.strftime('%A'),'No','No','No','Yes','Yes']]
    rows +=[['ScheduleTypeLimits','probe_any','','','Continuous'],['Schedule:Constant','probe_dual','probe_any',4],['Schedule:Constant','probe_activity','probe_any',117.28]]
    zones=collections.defaultdict(list)
    for package in packages:
        zones[package['room_id']].append(package);rows.extend(package['rows']);names=package['schedule_names']
        for channel in names:
            series={}
            for day in dates_:
                offset=origin(day);commands=[c for c in y['days'][str(day)]['controls']if c['kind']=='ac_setpoint'and c['asset_id']==package['asset_id']]
                values=[]
                for t in range(offset,offset+1440,10):
                    c=next((c for c in commands if c['start_min']<=t<c['end_min']),None)
                    values.append(int(c is not None)if channel=='available'else c.get('fan_operating_mode',0)if c and channel=='fan_mode'else 0 if channel=='fan_mode'else c['heating_setpoint_C']if c and channel=='heat_sp'else 5 if channel=='heat_sp'else c['cooling_setpoint_C']if c else 50)
                series[day]=values
            rows.append(compact(names[channel],series,5 if channel=='heat_sp'else 50 if channel=='cool_sp'else 0))
    for room,ps in zones.items():
        prefix='probe_'+room
        rows +=[['NodeList',prefix+'_supply']+[p['zone_supply_node']for p in ps],['NodeList',prefix+'_return']+[p['zone_return_node']for p in ps]]
        equipment=['ZoneHVAC:EquipmentList',prefix+'_equipment','SequentialLoad']
        for i,p in enumerate(ps,1):equipment+=['ZoneHVAC:PackagedTerminalHeatPump',p['equipment_name'],i,i,'','']
        rows +=[equipment,['ZoneHVAC:EquipmentConnections',room,prefix+'_equipment',prefix+'_supply',prefix+'_return',prefix+'_air',''],
          ['ThermostatSetpoint:DualSetpoint',prefix+'_setpoint',ps[0]['schedule_names']['heat_sp'],ps[0]['schedule_names']['cool_sp']],
          ['ZoneControl:Thermostat',prefix+'_thermostat',room,'probe_dual','ThermostatSetpoint:DualSetpoint',prefix+'_setpoint']]
    # Calendar headcounts, with actual handling locations overriding resident calendar.
    # Fixed native activity level is a functional reference, not person-specific metabolism.
    for room in (r['room_id']for r in w['layout']['rooms']):
        series={}
        for day in dates_:
            d=y['days'][str(day)];offset=origin(day);ops=[{**o,'start_min':o['start_min']-offset,'end_min':o['end_min']-offset}for o in y['operations']if overlap((o['start_min'],o['end_min']),(offset,offset+1440))]
            daytasks=[task for task in y["tasks"]if overlap((task["start_min"],task["end_min"]),(offset,offset+1440))]
            values=[]
            for t in range(0,1440,10):
                count=0
                for member in w['members']:
                    item=resident_slot(w,d['activity'],member['member_id'],t//10,ops,daytasks)
                    if item['location']=='home'and item.get('room_id')==room:count+=1
                count+=sum(any(x['start_min']<=t<x['end_min']and x.get('room_id')==room and x.get('location')=='home'for x in cal)for cal in d['shared']['member_calendars'].values())
                values.append(count)
            series[day]=values
        name='probe_people_'+room;rows.append(compact(name,series))
        rows.append(obj('People',{'name':name,'zone_or_zonelist_or_space_or_spacelist_name':room,'number_of_people_schedule_name':name,'number_of_people_calculation_method':'People','number_of_people':1,'fraction_radiant':0,'sensible_heat_fraction':'autocalculate','activity_level_schedule_name':'probe_activity','enable_ashrae_55_comfort_warnings':'No'}))
    # Retain EB stratified tank, plant and water draw semantics; fixed 15 C inlet.
    native=REPO/'upstream_2b17ae6/experiments/models/family_home/family_simple_3day.idf'
    nr=[[x.strip()for x in part.split(',')]for part in re.sub(r'!.*','',native.read_text()).split(';')if part.strip()]
    from hvac import SCHEMA
    def put(row,key,value):
        idx=SCHEMA[row[0]]['legacy_idd']['fields'].index(key)+1;row.extend(['']*max(0,idx+1-len(row)));row[idx]=value
    tank=next((x for x in w['parameter_pack']['devices']if 'water_heater'in x['types']),None)
    if tank:
        series={};flows={}
        for day in dates_:
            off=origin(day);cs=y['days'][str(day)]['controls'];needs=y['days'][str(day)]['needs']
            series[day]=[next((c['value_C']for c in cs if c['kind']=='tank_setpoint'and c['asset_id']==tank['asset_id']and c['start_min']<=t<c['end_min']),10.)for t in range(off,off+1440,10)]
            flows[day]=[sum(n['quantity']/((n['deadline_min']-n['release_min'])*60)/1000/.000141975 for n in needs if n['kind']=='water_heater'and n['release_min']<=t<n['deadline_min'])for t in range(off,off+1440,10)]
        rows +=[compact('probe_tank_target',series,10),compact('probe_draw',flows),['Schedule:Constant','v16_all','probe_any',1],['Schedule:Constant','v16_zero','probe_any',0],['Schedule:Constant','v16_mixedtemp','probe_any',40.5555555555556],['Schedule:Constant','v16_inlet15','probe_any',15]]
        types={'Branch','BranchList','Connector:Splitter','Connector:Mixer','ConnectorList','Pipe:Adiabatic','Pump:VariableSpeed','PlantLoop','PlantEquipmentList','PlantEquipmentOperation:HeatingLoad','PlantEquipmentOperationSchemes','SetpointManager:Scheduled','WaterUse:Equipment','WaterUse:Connections','WaterHeater:Stratified'}
        mapping={'EWH_Setpoint_Control':'probe_tank_target','EWH_Availability_Control':'v16_all','BA_shower_sch':'probe_draw','BA_sink_sch':'v16_zero','BA_bath_sch':'v16_zero','SSBWaterTempSchedule':'v16_mixedtemp'}
        for source in nr:
            if source[0]not in types or source[1].startswith('Air Loop'):continue
            r=[mapping.get(x,x.replace('_unit1','_v16'))for x in source]
            if r[0]=='WaterHeater:Stratified':
                for k,v in {'ambient_temperature_zone_name':tank['room_id'],'end_use_subcategory':'target_electric_hot_water','tank_volume':tank['parameters']['volume_m3'],'heater_1_capacity':tank['parameters']['heater_capacity_W'],'maximum_temperature_limit':tank['parameters']['maximum_C']}.items():put(r,k,v)
            if r[0]=='WaterUse:Equipment':
                for k,v in {'zone_name':tank['room_id'],'target_temperature_schedule_name':'v16_mixedtemp','cold_water_supply_temperature_schedule_name':'v16_inlet15','sensible_fraction_schedule_name':'v16_zero','latent_fraction_schedule_name':'v16_zero'}.items():put(r,k,v)
            if r[0]=='WaterUse:Connections':put(r,'cold_water_supply_temperature_schedule_name','v16_inlet15')
            rows.append(r)
        rows.append(['Site:WaterMainsTemperature','Schedule','v16_inlet15'])
    rows +=[['Output:SQLite','SimpleAndTabular']]
    for variable in ('Zone Mean Air Temperature','Zone Thermostat Heating Setpoint Temperature','Zone Thermostat Cooling Setpoint Temperature','Heating Coil Electricity Energy','Cooling Coil Electricity Energy','Fan Electricity Energy','Zone People Occupant Count','Water Heater Tank Temperature','Water Heater Heating Rate','Water Heater Electricity Energy'):
        rows.append(['Output:Variable','*',variable,'Timestep'])
    weather=w['layout']['source_parameter_reference']['weather'][0];epw=Path(weather['path'])
    if sha(epw)!=weather['sha256']:raise ValueError('WEATHER_BYTES_CHANGED')
    folder=DEST/'state_reference'/digest({'hid':hid,'date':str(date),'rows':rows,'compiler':sha(__file__)})[:16];folder.mkdir(parents=True,exist_ok=True)
    idf=folder/'probe.idf';idf.write_text('\n\n'.join(',\n  '.join(str(v)for v in r)+';'for r in rows))
    save(folder/'INPUT.json',{'household_id':hid,'date':str(date),'A_world_sha256':a['A_world_sha256'],'annual_A_sha256':a['annual_A_sha256'],'shell_sha256':sha(shell),'HVAC_components_sha256':a['HVAC_components_sha256'],'epw_sha256':sha(epw),'idf_sha256':sha(idf),'compiler_sha256':sha(__file__),
      'scope':'actual shell + native HVAC + dated resident/shared people; indoor-feedback functional probe only',
      'omitted_or_unvalidated':['appliance cooking and lighting thermal gains','lighting and cooking gains','full B rollout','airflow/door interactions','physical service and comfort acceptance','continuous annual thermal initialization'],
      'history_days':7,'run_days':10,'not_10000_pair_physical_acceptance':True})
    return folder,epw

def run_one(hid,date):
    import time
    started=time.monotonic();folder,epw=build(hid,dt.date.fromisoformat(date))
    result=subprocess.run(['/Applications/EnergyPlus-24-1-0/energyplus','-w',str(epw),'-d',str(folder/'out'),str(folder/'probe.idf')],capture_output=True,text=True)
    (folder/'stdout.txt').write_text(result.stdout+'\n'+result.stderr)
    err=(folder/'out/eplusout.err').read_text()if(folder/'out/eplusout.err').exists()else result.stderr
    report={'household_id':hid,'date':date,'passed':result.returncode==0 and 'EnergyPlus Completed Successfully'in err,'returncode':result.returncode,'elapsed_seconds':time.monotonic()-started,'folder':str(folder.relative_to(DEST)),'full_AB_physical_acceptance':False,'inputs_sha256':sha(folder/'INPUT.json'),'errors':[s for s in err.splitlines()if '** Severe **'in s or '**  Fatal  **'in s]}
    if report['passed']:
        dbpath=folder/'out/eplusout.sql';db=sqlite3.connect(dbpath);channels={};chosen=dt.date.fromisoformat(date)
        for key,var,month,day,hour,minute,value in db.execute('SELECT d.KeyValue,d.Name,t.Month,t.Day,t.Hour,t.Minute,r.Value FROM ReportData r JOIN ReportDataDictionary d ON r.ReportDataDictionaryIndex=d.ReportDataDictionaryIndex JOIN Time t ON r.TimeIndex=t.TimeIndex WHERE t.WarmupFlag=0'):
            day_date=min((dt.date(year,month,day)for year in(chosen.year-1,chosen.year,chosen.year+1)),key=lambda d:abs((d-chosen).days));end=(day_date-chosen).days*1440+hour*60+minute
            if -1440<end<=4320:channels.setdefault(key+'|'+var,[]).append([end-10,value])
        db.close();a=A_ROWS[hid];w=read(STAGE/a['A_world_path']);packages=read(STAGE/a['HVAC_components_path'])
        mapping={}
        for d in w['parameter_pack']['devices']:
            if 'ac'in d['types']:
                pp=next(p for p in packages if p['asset_id']==d['asset_id']);mapping[d['asset_id']]={'room_key':d['room_id'].upper(),'energy_keys':{r[0]:r[1].upper()for r in pp['rows']if r[0]in('Coil:Cooling:DX:SingleSpeed','Coil:Heating:DX:SingleSpeed','Coil:Heating:Electric','Fan:OnOff')}}
            if 'water_heater'in d['types']:mapping[d['asset_id']]={'tank_key':next((k.split('|')[0]for k in channels if k.endswith('|Water Heater Tank Temperature')),None)}
        state={'schema':'eb.native_A_event_state.v54','household_id':hid,'date':date,'passed':True,'channels':channels,'asset_mapping':mapping,'reference_scope':'EnergyPlus24.1 actual A46 shell/native HVAC and stratified tank;7 preceding days;fixed15C inlet;missing appliance lighting cooking gains;not full B response or comfort validation','SQL_sha256':sha(dbpath),'compiler_sha256':sha(__file__),'inputs_sha256':sha(folder/'INPUT.json'),'full_AB_physical_acceptance':False}
        path=folder/'STATE.json.gz';path.write_bytes(gzip.compress((canonical(state)+'\n').encode(),mtime=0));report['state_path']=str(path.relative_to(DEST));report['state_sha256']=sha(path);report['channel_count']=len(channels)
        # Keep reproducible raw SQL bytes, compressed; remove only newly produced
        # duplicate engine exports. No historical input or failed attempt removed.
        (folder/'out/eplusout.sql.gz').write_bytes(gzip.compress(dbpath.read_bytes(),mtime=0));dbpath.unlink()
        for name in ('eplusout.eso','eplusout.mtr','eplusout.shd'):
            f=folder/'out'/name
            if f.exists():f.unlink()
    save(folder/'RESULT.json',report)
    return report
def main():
    from concurrent.futures import ProcessPoolExecutor
    p=argparse.ArgumentParser();p.add_argument('--household');p.add_argument('--date');p.add_argument('--workers',type=int,default=8);p.add_argument('--limit',type=int,default=1000);args=p.parse_args()
    if args.household:print(canonical(run_one(args.household,args.date)));return
    jobs=[(r['household_id'],c['date'])for r in list(A_ROWS.values())[:args.limit]for c in r['cases']];records=[]
    with ProcessPoolExecutor(max_workers=args.workers)as pool:
        for result in pool.map(run_job,jobs):
            records.append(result)
            if len(records)%100==0:print(canonical({'native_A_states':len(records),'errors':sum(not r['passed']for r in records)}),flush=True)
    report={'schema':'eb.A_event_state_bindings.v54','records':records,'cases':len(records),'passed':all(r['passed']for r in records),'compiler_sha256':sha(__file__),'A_bindings_sha256':sha(STAGE/'A_BINDINGS10000.json'),'A_seal_sha256':sha(STAGE/'FINAL_SEAL.json'),'full_AB_physical_acceptance':False}
    save(DEST/'STATE_BINDINGS.json',report)
def run_job(job):
    try:return run_one(*job)
    except Exception as e:return {'household_id':job[0],'date':job[1],'passed':False,'error':str(e)}
if __name__=='__main__':main()
