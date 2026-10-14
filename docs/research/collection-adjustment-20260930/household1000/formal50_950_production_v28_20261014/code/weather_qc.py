"""Versioned EPW schema repair; raw weather, dates and households are immutable.

Only RH outside the EnergyPlus 24.1 dictionary [0,110] is treated as invalid.
The reference repair materializes the engine's documented last-good-value
replacement. Linear interpolation is a separately registered sensitivity,
never a replacement chosen after comparing favorable outputs. Neither is an
observed weather value. Original dew point and all other fields are retained.
"""
import copy,datetime as dt,shutil
from common import *

SOURCES=[
 'https://energyplus.net/assets/nrel_custom/pdfs/pdfs_v24.1.0/AuxiliaryPrograms.pdf',
 'https://bigladdersoftware.com/epx/docs/24-1/auxiliary-programs/missing-weather-file-data.html',
 'https://bigladdersoftware.com/epx/docs/24-1/auxiliary-programs/data-sources-uncertainty.html',
 'https://github.com/NREL/EnergyPlus/blob/v24.1.0/src/EnergyPlus/WeatherManager.cc']

def process(path):
    lines=path.read_text().splitlines();rows=[r.split(',')for r in lines[8:]]
    assert len(rows)==8760 and all(len(r)==35 for r in rows)
    values=[float(r[8])for r in rows];bad=[i for i,v in enumerate(values)if not 0<=v<=110]
    if not bad:return None
    badset=set(bad);last=50.;carry=copy.deepcopy(rows);linear=copy.deepcopy(rows);ledger=[]
    assert 0 not in badset and len(rows)-1 not in badset,'Endpoint repair requires a new explicit policy'
    for i,row in enumerate(rows):
        if i not in badset:last=values[i];continue
        left=i-1;right=i+1
        while left in badset:left-=1
        while right in badset:right+=1
        interp=values[left]+(values[right]-values[left])*(i-left)/(right-left)
        assert right-left-1<=7 and 0<=last<=110 and 0<=interp<=110
        for target,value,flag in [(carry,last,'E9'),(linear,interp,'B9')]:
            target[i][8]=format(value,'.8g');flags=target[i][5];assert len(flags)>=6
            target[i][5]=flags[:4]+flag+flags[6:]
            assert all(target[i][j]==row[j]for j in range(35)if j not in(5,8))
        ledger.append({'row_1based':i+9,'month':int(row[1]),'day':int(row[2]),'hour':int(row[3]),
            'original_RH':values[i],'reference_RH':last,'linear_RH':interp,'gap_hours':right-left-1,
            'left_row_1based':left+9,'right_row_1based':right+9,'original_flags':row[5],
            'reason':'outside_EP24.1_schema_0_to_110','not_observed':True})
    out={}
    for name,data in [('previous_good',carry),('linear',linear)]:
        content='\n'.join(lines[:8]+[','.join(r)for r in data])+'\n';key=hashlib.sha256(content.encode()).hexdigest();p=OUT/'weather_qc'/name/(key+'.epw')
        p.parent.mkdir(parents=True,exist_ok=True);p.write_text(content);out[name]={'path':str(p),'sha256':sha(p)}
        assert p.read_text().splitlines()[:8]==lines[:8]
    return {'original_path':str(path),'original_sha256':sha(path),'changed_rows':len(bad),'ledger':ledger,**out}

def main():
    school_guard();archive=OUT/'development/before_weather_qc';assert not archive.exists()
    archive.mkdir(parents=True)
    for name in ['SELECTION1000.json','WORLD_BINDINGS1000.json','COMPILED1000.json','COMPILED_SENSITIVITY50.json','IDF_BINDINGS1000.json','PHYSICS_original50_REVIEW.json','PHYSICS_other950_REVIEW.json','EP_original50_RUNS.json','EP_other950_RUNS.json','PRE_EP_original50.json','PRE_EP_other950.json']:
        if(OUT/name).exists():shutil.copy2(OUT/name,archive/name)
    selected=read(OUT/'SELECTION1000.json')['records'];unique={h['weather']['path']for h in selected}
    fixes={p:x for p in sorted(unique)if(x:=process(Path(p)))is not None}
    affected={h['household_id']for h in selected if h['weather']['path']in fixes}
    for name in ['SELECTION1000.json','WORLD_BINDINGS1000.json','COMPILED1000.json','COMPILED_SENSITIVITY50.json','IDF_BINDINGS1000.json']:
        data=read(OUT/name)
        def transform(x):
            if isinstance(x,list):return [transform(v)for v in x]
            if isinstance(x,dict):
                if 'weather'in x and x['weather']['path']in fixes:
                    original=x['weather'];fix=fixes[original['path']]
                    x['weather']={**original,**fix['previous_good'],'raw_weather_path':original['path'],'raw_weather_sha256':original['sha256'],
                        'quality_control':'EP24.1_previous_good_RH_only','repair_is_estimated_not_observed':True}
                return {k:transform(v)for k,v in x.items()}
            return x
        save(OUT/name,transform(data))
    # All baseline IDF bytes are unchanged: weather headers, dry bulb, annual
    # inlet statistics, location and original date boundaries are unchanged.
    old=read(archive/'COMPILED1000.json')['records'];current=read(OUT/'COMPILED1000.json')['records']
    assert all(a[s]==b[s]for a,b in zip(old,current)for s in('A','B'))
    extras=[]
    for c in current:
        if c['household_id']not in affected:continue
        alt=copy.deepcopy(c);fix=fixes[c['weather']['raw_weather_path']];alt['variant']='weather_linear7'
        alt['weather']={**c['weather'],**fix['linear'],'quality_control':'RH_linear_sensitivity_not_observed'};extras.append(alt)
    save(OUT/'COMPILED_WEATHER_SENSITIVITY.json',{'records':extras,'pairs':len(extras),'selection':'all 10 original dates of every household whose weather file required schema repair'})
    original50=set(read(OUT/'PARTITIONS.json')['formal50'])
    save(OUT/'WEATHER_QC_REVIEW.json',{'status':'pass','source_urls':SOURCES,'raw_files_checked':len(unique),'repaired_files':len(fixes),
        'changed_RH_hourly_rows':sum(f['changed_rows']for f in fixes.values()),'affected_households':len(affected),
        'affected_original50':len(affected&original50),'maximum_gap_hours':max(r['gap_hours']for f in fixes.values()for r in f['ledger']),
        'raw_weather_untouched':True,'only_RH_and_its_uncertainty_flags_changed':True,'all_headers_drybulb_other_fields_IDFs_dates_households_types_unchanged':True,
        'reference_method':'explicit previous-good RH, EnergyPlus missing-value policy; E9 estimated/unknown uncertainty',
        'sensitivity_method':'bounded linear interpolation of same invalid cells; B9 interpolated/unknown uncertainty',
        'these_methods_are_research_reference_assumptions_not_weather_observation_validation':True,'records':list(fixes.values())})
    print({'weather_QC':'pass','files':len(unique),'repaired':len(fixes),'households':len(affected),'alternative_pairs':len(extras)},flush=True)

if __name__=='__main__':main()
