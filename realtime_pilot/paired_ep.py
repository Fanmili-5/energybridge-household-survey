"""Native EnergyPlus execution of frozen schedules, with common warmup and sizing."""
import json
import os
import re
import sqlite3
import subprocess
import time
from pathlib import Path
from common import UPSTREAM, file_hash, write_json
from proposal_contract import executable
from paired_contract import TASKS, validate
from eb_execution import replay, upstream
from survey_time import ac_available

EP = Path(os.environ.get('EPLUS_ROOT', '/Applications/EnergyPlus-24-1-0')) / 'energyplus'
TEMPLATE = UPSTREAM/'experiments/models/family_home/family_simple_3day.idf'
WEATHER = UPSTREAM/'experiments/weather/epw/CHN_TJ_Tianjin.545270_CSWD.epw'

def objects(text):
    return [[f.strip() for f in chunk.split(',')] for chunk in re.sub(r'!.*','',text).split(';') if chunk.strip()]

def schedule(name, before, after, design):
    def day(values):
        fields=['For: SummerDesignDay WinterDesignDay','Until: 24:00',str(design),'For: AllOtherDays']
        for i,val in enumerate(values):
            if i==143 or val!=values[i+1]:
                mins=(i+1)*10
                fields += [f'Until: {mins//60:02d}:{mins%60:02d}',str(val)]
        return fields
    return ['Schedule:Compact',name,'Temperature' if name in {'PilotCooling','PilotHeating'} else 'fraction','Through: 7/3',*day(before),'Through: 12/31',*day(after)]

def build_idf(folder, original, plan, scenario, profile, execution, *, horizon=96):
    from paired_contract import value
    import math
    days=math.ceil(horizon/24);steps=days*144
    runner, _ = upstream()
    obs=objects(TEMPLATE.read_text()); extra=[]
    ordinary=executable(original); ac=original['devices'].get('ac',{})
    cutoff=72+scenario['decision_h']
    def full_schedule(name, values, kind='fraction', design=0):
        fields=['Schedule:Compact',name,kind]
        # Identical design-day values and conditioning days for paired runs.
        for day in range(days):
            fields += ['Through: '+(f'7/{day+1}' if day<days-1 else '12/31'),
                       'For: SummerDesignDay WinterDesignDay','Until: 24:00',str(design),'For: AllOtherDays']
            vals=values[day*144:(day+1)*144]
            for i,val in enumerate(vals):
                if i==143 or val!=vals[i+1]:
                    minutes=(i+1)*10
                    fields += [f'Until: {minutes//60:02d}:{minutes%60:02d}',str(val)]
        extra.append(fields)
    availability=[int(ac_available(ac,i/6)) for i in range(steps)]
    cooling=[(plan['setpoint'] if i/6>=cutoff else ordinary['setpoint']) if availability[i] else runner.AC_OFF_FALLBACK_COOLING_SETPOINT for i in range(steps)]
    full_schedule('PilotACAvailability',availability,design=int(bool(ac.get('active'))))
    full_schedule('PilotCooling',cooling,'Temperature',24)
    full_schedule('PilotHeating',[runner.HTG_SP]*steps,'Temperature',runner.HTG_SP)
    from household_config import occupancy_schedule
    schedule=occupancy_schedule(profile);count=schedule['occupant_count']
    occupancy=[schedule['hourly_fraction'][int(i/6)%24] for i in range(steps)]
    full_schedule('PilotOccupancy',occupancy,design=1)
    config=original['eb_appliance_config']
    # Preserve the native EV and stratified water-heater models. EB's own
    # actuator writer supplies fractions/setpoints; there is no fixed 1h/2h proxy.
    for device in ('washer','dishwasher','dryer','ev','water_heater'):
        default=40 if device=='water_heater' else 0
        values=[r['actuators'].get(device,default) for r in execution['rows']]
        full_schedule('EB_'+device,values,'Temperature' if device=='water_heater' else 'fraction',default)
    for o in obs:
        kind=o[0].lower()
        if kind=='runperiod': o[2:9]=['7','1','','7',str(days),'','Monday']
        if kind=='thermostatsetpoint:dualsetpoint': o[2:4]=['PilotHeating','PilotCooling']
        if kind=='people': o[3]='PilotOccupancy';o[5]=str(count)
        if kind=='electricequipment' and o[1]=='EV_Charger': o[3]='EB_ev'
        if kind=='airloophvac:unitaryheatpump:airtoair': o[2]='PilotACAvailability'
        if kind=='waterheater:stratified':
            o[9]=o[13]='EB_water_heater'
            if not config['water_heater']['present']: o[11]=o[15]='0'
        if kind=='wateruse:equipment' and not config['water_heater']['present']: o[3]='0';o[5]=''
    # Pinned IDF lacks the three shiftable ports expected by EB's writer.
    # Add only electrical ports at EB's design levels. Heat fractions inherit
    # the existing EV electrical-only model and are disclosed as an adapter
    # assumption, not as upstream thermal validation or measured home data.
    for d in TASKS:
        if config[d]['present']:
            extra.append(['ElectricEquipment','EB_'+d+'_Equipment','living_unit1','EB_'+d,'EquipmentLevel',str(runner._APPL_DESIGN_W[d]),'','','0','0','1','EBTaskAdapter'])
    extra += [['Output:SQLite','SimpleAndTabular'],
              ['Output:Variable','living_unit1','Zone Mean Air Temperature','Timestep'],
              ['Output:Variable','*','Electric Equipment Electricity Energy','Timestep'],
              ['Output:Variable','Environment','Site Outdoor Air Drybulb Temperature','Timestep'],
              *[['Output:Variable','*',name,'Timestep'] for name in ('Water Use Equipment Total Mass Flow Rate','Water Use Equipment Mixed Water Temperature','Water Use Equipment Target Water Temperature')]]
    obs=[o for o in obs if o[0].lower()!='output:sqlite']
    path=folder/'input.idf';folder.mkdir(parents=True,exist_ok=True)
    path.write_text('\n\n'.join(',\n  '.join(o)+';' for o in obs+extra))
    return path

def read_series(folder, horizon=96, start_date='2007-07-01'):
    from datetime import date
    start=date.fromisoformat(start_date)
    conn=sqlite3.connect(folder/'eplusout.sql')
    rows=conn.execute('''SELECT t.Month,t.Day,t.Hour,t.Minute,t.Interval,d.Name,d.KeyValue,d.Units,r.Value
      FROM ReportData r JOIN ReportDataDictionary d USING(ReportDataDictionaryIndex)
      JOIN Time t USING(TimeIndex) JOIN EnvironmentPeriods e USING(EnvironmentPeriodIndex)
      WHERE t.WarmupFlag=0 AND e.EnvironmentType=3 AND d.ReportingFrequency IN ('Zone Timestep','HVAC System Timestep')
      ORDER BY t.TimeIndex''').fetchall()
    conn.close(); traces={}
    for month,day,hour,minute,interval,name,key,unit,val in rows:
        end=(date(start.year,month,day)-start).days*24+hour+minute/60
        if not 0<end<=horizon: continue
        namekey=name+'|'+(key or '')
        traces.setdefault(namekey,[]).append({'end_h':end,'start_h':end-interval/60,'value':val,'unit':unit})
    return traces

def find(traces,name,key=None, *, horizon=96, unit=None):
    matches=[v for k,v in traces.items() if k.split('|')[0].lower()==name.lower() and (key is None or k.split('|')[1].lower()==key.lower())]
    if len(matches)!=1: raise ValueError('Missing or ambiguous EP output '+name+' '+str(key))
    # Duplicate output requests are normally deduplicated by EP. Do not silently sum duplicate rows.
    series=matches[0]
    expected_unit=unit or ('J' if 'Electric' in name else 'C')
    if any(r['unit']!=expected_unit for r in series): raise ValueError('Unexpected EP output units '+name)
    if len(series)!=round(horizon*6) or any(abs(r['end_h']-(i+1)/6)>1e-6 for i,r in enumerate(series)):
        raise ValueError('Incomplete or duplicated EP timeline '+name)
    return series

def run(folder,original,plan,scenario,profile,*,is_proposal=False):
    validate(original,plan,scenario)
    started=time.perf_counter();execution=replay(original,plan,scenario,proposal=is_proposal)
    idf=build_idf(folder,original,plan,scenario,profile,execution)
    write_json(folder/'eb_execution.json',execution)
    with (folder/'console.log').open('w') as log:
        result=subprocess.run([str(EP),'-w',str(WEATHER),'-d',str(folder),str(idf)],stdout=log,stderr=subprocess.STDOUT,timeout=90)
    err=(folder/'eplusout.err').read_text() if (folder/'eplusout.err').exists() else ''
    if result.returncode or '** Severe **' in err or '**  Fatal  **' in err:
        raise ValueError('EnergyPlus failed; see retained eplusout.err')
    traces=read_series(folder)
    meter=find(traces,'Electricity:Facility');temp=find(traces,'Zone Mean Air Temperature','living_unit1');weather=find(traces,'Site Outdoor Air Drybulb Temperature','Environment')
    checks={};runner,_=upstream()
    for d in ('washer','dishwasher','dryer','ev'):
        if original['eb_appliance_config'][d]['present']:
            key='EV_Charger' if d=='ev' else 'EB_'+d+'_Equipment'
            series=find(traces,'Electric Equipment Electricity Energy',key)
            actual=sum(x['value'] for x in series if x['end_h']>72)/3600000
            expected=sum(r['actuators'].get(d,0)*runner._APPL_DESIGN_W[d]/1000/6 for r in execution['rows'] if r['sim_h']>=72)
            if abs(actual-expected)>1e-7: raise ValueError('EB actuator/EP meter mismatch '+d)
            checks[d]={'actuator_expected_kwh':expected,'metered_kwh':actual,
                       'event_metered_kwh':sum(x['value'] for x in series if 72+scenario['event']['trigger_h']<x['end_h']<=72+scenario['event']['end_h'])/3600000}
    out={'electricity':[{'start_h':r['start_h'],'end_h':r['end_h'],'kwh':r['value']/3600000} for r in meter],
         'temperature':[{'end_h':r['end_h'],'c':r['value']} for r in temp],
         'weather':[{'end_h':r['end_h'],'c':r['value']} for r in weather],
         'execution':{'applications':execution['applications'],'source':execution['source'],'services':execution['services']},'task_energy_checks':checks,'seconds':round(time.perf_counter()-started,3),
         'warning_count':int(re.search(r'Completed Successfully--\s*(\d+) Warning',err).group(1)), 'warning_message_count':err.count('** Warning **'),'idf_sha256':file_hash(idf),'weather_sha256':file_hash(WEATHER),'template_sha256':file_hash(TEMPLATE)}
    write_json(folder/'trace.json',out);return out

def pair_metrics(baseline,proposal,scenario):
    cutoff=72+scenario['decision_h']; event=scenario['event'];lo=72+event['trigger_h'];hi=72+event['end_h']
    prefix_energy=max(abs(a['kwh']-b['kwh']) for a,b in zip(baseline['electricity'],proposal['electricity']) if a['end_h']<=cutoff)
    prefix_temp=max(abs(a['c']-b['c']) for a,b in zip(baseline['temperature'],proposal['temperature']) if a['end_h']<=cutoff)
    if prefix_energy>1e-7 or prefix_temp>1e-6: raise ValueError('Paired runs do not share identical pre-event history')
    def summarize(run):
        daily=sum(x['kwh'] for x in run['electricity'] if 72<x['end_h']<=96)
        total=sum(x['kwh'] for x in run['electricity'] if x['end_h']>72)
        event_kwh=sum(x['kwh'] for x in run['electricity'] if lo<x['end_h']<=hi)
        temps=[x['c'] for x in run['temperature'] if lo<x['end_h']<=hi]
        return {'comparison_kwh':total,'comparison_cost_cny':total*.6,'next_day_kwh':total-daily,'daily_kwh':daily,'daily_cost_cny':daily*.6,'event_kwh':event_kwh,'event_mean_kw':event_kwh/(hi-lo),
                'event_temp_min_c':min(temps),'event_temp_max_c':max(temps)}
    a,b=summarize(baseline),summarize(proposal)
    return {'status':'paired_energyplus_complete','original':a,'proposal':b,
            'daily_saving_cny':a['daily_cost_cny']-b['daily_cost_cny'],'event_reduction_kwh':a['event_kwh']-b['event_kwh'],
            'prefix_check':{'passed':True,'until_simulation_h':cutoff,'max_kwh_difference':prefix_energy,'max_temperature_difference_c':prefix_temp},
            'comparison_window':scenario.get('evaluation_window',{'end_sim_h':96,'end_label':'24:00'}),
            'scope':'Same evaluation window in both branches, with native daily routines; prototype prediction, not measured home or equal-service savings'}
