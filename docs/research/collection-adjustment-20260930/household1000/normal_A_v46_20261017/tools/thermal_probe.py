"""Actual-shell indoor-feedback functional probe; not complete benchmark physics."""
import argparse,collections,re,subprocess,sqlite3,sys
from pathlib import Path
STAGE=Path(__file__).resolve().parents[1];sys.path.insert(0,str(STAGE/'code'))
from common import *
from hvac import obj,ROWS
from activity_model import resident_slot

def compact(name,days,default=0):
    row=['Schedule:Compact',name,'probe_any'];first=min(days);last=max(days)
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
    a=next(r for r in read(STAGE/'A_BINDINGS10000.json')['records']if r['household_id']==hid)
    m=next(r for r in read(MASTER/'WORLD_BINDINGS1000.json')['records']if r['household_id']==hid)
    w=read(STAGE/a['A_world_path']);y=read(STAGE/a['annual_A_path']);packages=read(STAGE/a['HVAC_components_path'])
    start=date-dt.timedelta(days=7);end=date+dt.timedelta(days=2);dates_=[start+dt.timedelta(days=i)for i in range(10)]
    shell=MASTER/m['background_IDF_path'];rows=[[x.strip()for x in s.split(',')]for s in re.sub(r'!.*','',shell.read_text()).split(';')if s.strip()]
    rows=[r for r in rows if r[0]not in('RunPeriod','Timestep','SimulationControl')and not r[0].startswith('Output:')]
    rows +=[['Timestep',6],['SimulationControl','No','No','No','No','Yes'],['RunPeriod','indoor_feedback_functional_probe',start.month,start.day,2025,end.month,end.day,2025,start.strftime('%A'),'No','No','No','Yes','Yes']]
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
            values=[]
            for t in range(0,1440,10):
                count=0
                for member in w['members']:
                    item=resident_slot(w,d['activity'],member['member_id'],t//10,ops,[t for t in y['tasks']if overlap((t['start_min'],t['end_min']),(offset,offset+1440))])
                    if item['location']=='home'and item.get('room_id')==room:count+=1
                count+=sum(any(x['start_min']<=t<x['end_min']and x.get('room_id')==room and x.get('location')=='home'for x in cal)for cal in d['shared']['member_calendars'].values())
                values.append(count)
            series[day]=values
        name='probe_people_'+room;rows.append(compact(name,series))
        rows.append(obj('People',{'name':name,'zone_or_zonelist_or_space_or_spacelist_name':room,'number_of_people_schedule_name':name,'number_of_people_calculation_method':'People','number_of_people':1,'fraction_radiant':0,'sensible_heat_fraction':'autocalculate','activity_level_schedule_name':'probe_activity','enable_ashrae_55_comfort_warnings':'No'}))
    rows +=[['Output:SQLite','SimpleAndTabular']]
    for variable in ('Zone Mean Air Temperature','Zone Thermostat Heating Setpoint Temperature','Zone Thermostat Cooling Setpoint Temperature','Heating Coil Electricity Energy','Cooling Coil Electricity Energy','Fan Electricity Energy','Zone People Occupant Count'):
        rows.append(['Output:Variable','*',variable,'Timestep'])
    weather=w['layout']['source_parameter_reference']['weather'][0];epw=Path(weather['path'])
    if sha(epw)!=weather['sha256']:raise ValueError('WEATHER_BYTES_CHANGED')
    folder=STAGE/'thermal_probe'/digest({'hid':hid,'date':str(date),'rows':rows})[:16];folder.mkdir(parents=True,exist_ok=True)
    idf=folder/'probe.idf';idf.write_text('\n\n'.join(',\n  '.join(str(v)for v in r)+';'for r in rows))
    save(folder/'INPUT.json',{'household_id':hid,'date':str(date),'A_world_sha256':a['A_world_sha256'],'annual_A_sha256':a['annual_A_sha256'],'shell_sha256':sha(shell),'HVAC_components_sha256':a['HVAC_components_sha256'],'epw_sha256':sha(epw),'idf_sha256':sha(idf),'compiler_sha256':sha(__file__),
      'scope':'actual shell + native HVAC + dated resident/shared people; indoor-feedback functional probe only',
      'omitted_or_unvalidated':['appliance and hot-water thermal gains','lighting and cooking gains','full B rollout','airflow/door interactions','physical service and comfort acceptance','continuous annual thermal initialization'],
      'history_days':7,'run_days':10,'not_10000_pair_physical_acceptance':True})
    return folder,epw

def main():
    p=argparse.ArgumentParser();p.add_argument('--household',default='ordinary-v6-0001');p.add_argument('--date',default='2025-10-12');a=p.parse_args();folder,epw=build(a.household,dt.date.fromisoformat(a.date))
    result=subprocess.run(['/Applications/EnergyPlus-24-1-0/energyplus','-w',str(epw),'-d',str(folder/'out'),str(folder/'probe.idf')],capture_output=True,text=True)
    (folder/'stdout.txt').write_text(result.stdout+'\n'+result.stderr)
    err=(folder/'out/eplusout.err').read_text()if(folder/'out/eplusout.err').exists()else result.stderr
    passed=result.returncode==0 and 'EnergyPlus Completed Successfully'in err
    report={'passed':passed,'returncode':result.returncode,'folder':str(folder.relative_to(STAGE)),'scope':'thermal-control functional probe only','full_physical_acceptance':False,
       'severe_lines':[line for line in err.splitlines()if re.search(r'\*\*\s+(Severe|Fatal)\s+\*\*',line)],
       'warning_count':err.count('** Warning **'),'inputs_sha256':sha(folder/'INPUT.json')}
    if passed:
        db=sqlite3.connect(folder/'out/eplusout.sql');report['readback']={}
        for var in ('Zone Mean Air Temperature','Heating Coil Electricity Energy','Cooling Coil Electricity Energy','Fan Electricity Energy'):
            values=db.execute('SELECT MIN(r.Value),MAX(r.Value),SUM(r.Value),COUNT(*) FROM ReportData r JOIN ReportDataDictionary d ON r.ReportDataDictionaryIndex=d.ReportDataDictionaryIndex JOIN Time t ON r.TimeIndex=t.TimeIndex WHERE d.Name=? AND t.WarmupFlag=0',(var,)).fetchone()
            report['readback'][var]=values
        primary={}
        chosen=dt.date.fromisoformat(a.date)
        for var in ('Zone Mean Air Temperature','Heating Coil Electricity Energy','Cooling Coil Electricity Energy','Fan Electricity Energy'):
            records=db.execute('SELECT t.Month,t.Day,t.Hour,t.Minute,r.Value FROM ReportData r JOIN ReportDataDictionary d ON r.ReportDataDictionaryIndex=d.ReportDataDictionaryIndex JOIN Time t ON r.TimeIndex=t.TimeIndex WHERE d.Name=? AND t.WarmupFlag=0',(var,)).fetchall()
            values=[v for month,day,hour,minute,v in records if 480 < (dt.date(2025,month,day)-chosen).days*1440+hour*60+minute <= 1920]
            primary[var]={'minimum':min(values)if values else None,'maximum':max(values)if values else None,'sum':sum(values),'samples':len(values)}
        report['primary08_to_next08']=primary
        db.close()
    save(folder/'RESULT.json',report);print(canonical(report))
    if not passed:raise SystemExit(2)
if __name__=='__main__':main()
