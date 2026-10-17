"""Export only the pinned simulation inputs, without changing any A/B record."""
import argparse
import collections
import shutil
from concurrent.futures import ProcessPoolExecutor
from core import *

A = BASE/'normal_A_v46_20261017'
B = BASE/'candidate_B_v57_20261017'
M = BASE/'household_master_v33_20261016'

def export_household(job):
    ar, mr, br = job
    hid = ar['household_id']
    for stage, row, keys in [(A, ar, ['A_world','annual_A','HVAC_components']), (M, mr, ['background_IDF'])]:
        for key in keys:
            if sha(stage/row[key+'_path']) != row[key+'_sha256']:
                raise ValueError('SOURCE_HASH:'+hid+':'+key)
    world = read(A/ar['A_world_path'])
    annual = read(A/ar['annual_A_path'])
    days = {}
    for date, day in annual['days'].items():
        activity = day['activity']
        days[date] = {
            'calendars': activity['member_calendars'],
            'operator_windows': activity['operator_windows_min'],
            'family': activity['family_context'],
            'external_visits': activity.get('external_visits', []),
            'shared': day['shared'],
            'controls': day['controls'],
            'water_needs': [n for n in day['needs'] if n['kind']=='water_heater'],
        }
    weather = world['layout']['source_parameter_reference']['weather'][0]
    epw = Path(weather['path'])
    if sha(epw) != weather['sha256']:
        raise ValueError('WEATHER_HASH:'+hid)
    dst = ROOT/'inputs/weather'/f"{weather['sha256']}.epw"
    if not dst.exists():
        dst.parent.mkdir(parents=True,exist_ok=True)
        shutil.copyfile(epw, dst)
    pack = {
        'household_id': hid, 'type': ar['type'], 'world': world,
        'shell_rows': parse_idf((M/mr['background_IDF_path']).read_text()),
        'HVAC': read(A/ar['HVAC_components_path']),
        'weather': str(dst.relative_to(ROOT)), 'weather_sha256': weather['sha256'],
        'anchor': annual['anchor'], 'end_exclusive': annual['end_exclusive'],
        'days': days, 'tasks': annual['tasks'], 'operations': annual['operations'],
        'EV_battery_energy_events': annual['EV_battery_energy_events'],
        'journeys': annual['journeys'],
        'source_A_world_sha256': ar['A_world_sha256'],
        'source_annual_A_sha256': ar['annual_A_sha256'],
        'source_shell_sha256': mr['background_IDF_sha256'],
    }
    path = ROOT/'inputs/households'/f'{hid}.json.gz'
    save(path,pack)
    cases = []
    for r in br['rounds']:
        source = B/r['path']
        if sha(source)!=r['sha256']:
            raise ValueError('PAIR_HASH:'+r['case_id'])
        p = read(source)
        keep = ['case_id','household_id','date','A','B','needs_A','needs_B','VPP_events',
                'EV_continuous_reference','assessment_A','assessment_B','primary_evaluation_min',
                'service_tail_end_min','decision_min']
        q = {k:p[k] for k in keep}
        q['source_pair_sha256']=r['sha256']
        q['source_pair_path']=str(source.relative_to(REPO))
        q['schedule_hashes']={side:digest({k:p[side][k] for k in ('tasks','operations','controls')}) for side in ('A','B')}
        cp = ROOT/'inputs/pairs'/hid/f"{p['date']}.json.gz"
        save(cp,q)
        cases.append({'case_id':p['case_id'],'date':p['date'],'path':str(cp.relative_to(ROOT)),
                      'sha256':sha(cp),'source_pair_sha256':r['sha256'],'schedule_hashes':q['schedule_hashes']})
    return {'household_id':hid,'type':ar['type'],'path':str(path.relative_to(ROOT)),
            'sha256':sha(path),'cases':cases}

def main():
    parser=argparse.ArgumentParser();parser.add_argument('--workers',type=int,default=4)
    args=parser.parse_args()
    aa=read(A/'A_BINDINGS10000.json')['records'];mm={r['household_id']:r for r in read(M/'WORLD_BINDINGS1000.json')['records']}
    bb={r['household_id']:r for r in read(B/'PAIR_BINDINGS10000.json')['records']}
    subset=read(B/'SUBSET50.json');ids=[r['household_id']for r in subset['records']]
    native=REPO/'upstream_2b17ae6/experiments/models/family_home'
    schema=Path('/Applications/EnergyPlus-24-1-0/Energy+.schema.epJSON')
    (ROOT/'inputs').mkdir(exist_ok=True)
    save(ROOT/'inputs/schema_fields.json.gz',{k:v['legacy_idd']['fields']for k,v in read(schema)['properties'].items()if 'legacy_idd'in v})
    save(ROOT/'inputs/native_rows.json.gz',{'tank':parse_idf((native/'family_simple_3day.idf').read_text()),
                                          'gains':parse_idf((native/'original_model.idf').read_text())})
    rows=[]
    with ProcessPoolExecutor(max_workers=args.workers)as pool:
        for r in pool.map(export_household,[(ar,mm[ar['household_id']],bb[ar['household_id']])for ar in aa]):
            rows.append(r)
            if len(rows)%100==0:print(canonical({'exported_households':len(rows)}),flush=True)
    source_files=[A/'A_BINDINGS10000.json',A/'FINAL_SEAL.json',B/'PAIR_BINDINGS10000.json',B/'FINAL_SEAL.json',B/'SUBSET50.json',M/'WORLD_BINDINGS1000.json',M/'FINAL_SEAL.json',schema]
    manifest={'schema':VERSION,'households':1000,'pairs':10000,'records':rows,'subset50_ids':ids,
              'subset50_types':dict(collections.Counter(r['type']for r in rows if r['household_id']in ids)),
              'source_files':{str(p.relative_to(REPO))if REPO in p.parents else str(p):sha(p)for p in source_files},
              'fixed_inputs':{str(p.relative_to(ROOT)):sha(p)for p in (ROOT/'inputs').glob('*.gz')},
              'weather':{str(p.relative_to(ROOT)):sha(p)for p in sorted((ROOT/'inputs/weather').glob('*'))},
              'credentials_included':False,'schedules_modified':False,'one_dataset':True}
    save(ROOT/'INPUT_MANIFEST.json',manifest)
    print(canonical({'households':len(rows),'pairs':sum(len(r['cases'])for r in rows),'subset':manifest['subset50_types']}))

if __name__=='__main__':main()
