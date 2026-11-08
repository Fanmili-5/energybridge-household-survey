"""Create wholly invented normalized records; never copy real survey households."""
from pathlib import Path
import hashlib,json
COUNTRIES=('CN','US','GB','ES','IN','MX','AU','DE')
def fact(value,fields=(),status='benchmark_assigned',**kw):return {'value':value,'fields':list(fields),'status':'unknown' if value is None else status,**kw}
def make_pool(out,records_per_country=40):
    out=Path(out)
    if out.exists():raise ValueError('OUTPUT_EXISTS; choose a fresh directory')
    out.mkdir(parents=True);rows=[]
    for co in COUNTRIES:
        for i in range(records_per_country):
            key=f'PUBLIC-SYNTHETIC-{co}-{i:04d}';counts=[1,1,0,0,2,0];fields=[f'S1{s}c{a}' for s in 'AB' for a in (1,2,3)]
            names=('washer_available','dryer_available','dishwasher_available','space_ac_available','water_heater_available','home_vehicle_charging')
            devices={name:fact(True if name=='washer_available' else None) for name in names}
            rows.append({'source':{'dataset':'SYNTHETIC','household_key':key,'country':co,'survey_year':None,'survey_reference_year':None,
                  'release':'public invented reference fixture v1; not survey microdata','fieldwork_year':None,'adapter_schema':'ENABLE_EU_layout_only'},
              'synthetic_fixture':True,'household_size':fact(4),
              'dwelling':{'observed_type':fact(None),'reference_type':fact('reference_apartment'),
                'size':fact('reference66_to90m2',code=3,measure='dwelling_area_band')},
              'devices':devices,'additional_devices':{'fridge_available':fact(True)},
              'source_person':{'age':fact(None),'employment':fact(None),'source_person':'invented_reference_anchor',
                 'teleworking_household':fact(None),'commute_frequency':fact(None)},
              'respondent_demographics':{'sex':fact('female'),'birth_year':fact(None)},
              'members_summary':fact([{'label':('Women' if j<3 else 'Men')+'_'+str(j%3),**fact(n,[fields[j]])} for j,n in enumerate(counts)],fields,scope='original_sex_and_age_bins'),
              'known_presence':fact(None),'source_technology_presence':{'standalone_electric_water_heater':fact(None)},
              'geography':fact(None),'anchors':{},'pool_id':'SYNTHETIC:'+key,'block':[co,'invented_apartment',4,3]})
    path=out/'candidate_pool.jsonl';path.write_text(''.join(json.dumps(r,ensure_ascii=False,sort_keys=True)+'\n' for r in rows))
    report={'schema':'eb.household.normalized_source_pool.v1','synthetic_fixture_only':True,'records':len(rows),'country_candidates':{co:records_per_country for co in COUNTRIES},
      'pool_sha256':hashlib.sha256(path.read_bytes()).hexdigest(),'source_data_claim':False,'real_survey_records':0}
    (out/'SOURCE_POOL.json').write_text(json.dumps(report,indent=2,sort_keys=True)+'\n')
    print(json.dumps(report),flush=True)
    return report
