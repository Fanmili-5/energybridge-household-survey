"""Versioned physical bindings on generated assets; pinned EB stays immutable."""
import re
import sqlite3
from pathlib import Path
from common import file_hash, UPSTREAM

BINDING_VERSION = 'eb.appliance_ep_binding.v1'
DEVICE_BINDINGS = {
    'washer': ('ClothesWasher', 'clotheswasher1'),
    'dishwasher': ('Dishwasher', 'dishwasher1'),
    'dryer': ('ClothesDryer', 'electric_dryer1'),
    'refrigerator': ('Refrigerator', 'refrigerator1'),
}

def idf_objects(body):
    return [[v.strip() for v in raw.split(',')]
            for raw in re.sub(r'!.*', '', body).split(';') if raw.strip()]

def bind_native_appliances(idf, design):
    """Connect EB's existing four power ports, with original Tianjin heat fractions.

    No scheduler changes. Both no_dr and agent receive these same zero-default
    loads. Existing conflicting equipment is an error, never silently doubled.
    """
    path = Path(idf)
    before = file_hash(path)
    body = path.read_text()
    records = idf_objects(body)
    if not any(r[0].lower() == 'zone' and r[1].lower() == 'living_unit1' for r in records):
        raise ValueError('Unsupported physical zone for native appliance bindings')
    reference = UPSTREAM/'experiments/models/family_home/original_model.idf'
    sources = {r[1].lower(): r for r in idf_objects(reference.read_text())
               if r[0].lower() == 'electricequipment'}
    additions, bindings = [], {}
    for device, (prefix, original_name) in DEVICE_BINDINGS.items():
        schedule, equipment = prefix+'_Power_Frac', prefix+'_Appliance'
        source = sources[original_name]
        expected = [
            ['Schedule:Constant', schedule, '', '0'],
            ['ElectricEquipment', equipment, 'living_unit1', schedule,
             'EquipmentLevel', f'{design[device]:g}', '', '', *source[8:12]],
        ]
        existing = [r for r in records if len(r)>1 and
                    r[1].lower() in {schedule.lower(),equipment.lower(),original_name}]
        if existing:
            if sorted([[x.lower() for x in r] for r in existing]) != sorted([[x.lower() for x in r] for r in expected]):
                raise ValueError('Conflicting native appliance binding: '+device)
        else:
            additions.extend(','.join(row)+';' for row in expected)
        bindings[device] = {'schedule':schedule, 'equipment':equipment,
                            'design_w':design[device], 'heat_fractions':source[8:11]}
    if additions:
        path.write_text(body+'\n! '+BINDING_VERSION+'; native writer ports, original Tianjin heat fractions\n'+'\n'.join(additions)+'\n')
    return {'version':BINDING_VERSION,'before_sha256':before,'after_sha256':file_hash(path),
            'added_objects':len(additions),'bindings':bindings,
            'thermal_reference':'experiments/models/family_home/original_model.idf',
            'thermal_reference_sha256':file_hash(reference),
            'scope':'Tianjin research prototype; not household calibration',
            'controller_changed':False}


def reporting_assets(idf):
    path=Path(idf)
    before=file_hash(path)
    # Original templates already request facility energy and zone temperature.
    # The physical binding is a separate explicit preparation step.
    body=path.read_text()
    clean=re.sub(r'!.*','',body)
    added=not re.search(r'(?i)\bOutput:SQLite\s*,',clean)
    if added:path.write_text(body+'\nOutput:SQLite,SimpleAndTabular;\n')
    return {'prepared_idf_sha256':before,'reporting_idf_sha256':file_hash(path),
            'reporting_only_additions':['Output:SQLite'] if added else [],
            'equipment_or_control_changes':False,
            'source':'original run_persona_json._prepare_run_assets',
            'scope':'native research building, including its fixed background loads'}


def read_series(folder, *, horizon, start_date):
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
        sample_date=date(start.year,month,day)
        if sample_date<start:sample_date=date(start.year+1,month,day)
        end=(sample_date-start).days*24+hour+minute/60
        if not 0<end<=horizon: continue
        namekey=name+'|'+(key or '')
        traces.setdefault(namekey,[]).append({'end_h':end,'start_h':end-interval/60,'value':val,'unit':unit})
    return traces

def find(traces,name,key=None, *, horizon, unit=None):
    matches=[v for k,v in traces.items() if k.split('|')[0].lower()==name.lower() and (key is None or k.split('|')[1].lower()==key.lower())]
    if len(matches)!=1: raise ValueError('Missing or ambiguous EP output '+name+' '+str(key))
    # Duplicate output requests are normally deduplicated by EP. Do not silently sum duplicate rows.
    series=matches[0]
    expected_unit=unit or ('J' if 'Electric' in name else 'C')
    if any(r['unit']!=expected_unit for r in series): raise ValueError('Unexpected EP output units '+name)
    if len(series)!=round(horizon*6) or any(abs(r['end_h']-(i+1)/6)>1e-6 for i,r in enumerate(series)):
        raise ValueError('Incomplete or duplicated EP timeline '+name)
    return series
