"""Fixed six-case Mac/Linux check, without choosing cases by observed response."""
import argparse
from core import *
from analyze import energy,total

def main():
    p=argparse.ArgumentParser();p.add_argument('--local',default='pilot50');p.add_argument('--server',default='linux_probe28');args=p.parse_args()
    server=read(ROOT/'results'/args.server/'RUN_BINDINGS.json');rows=[]
    for r in server['records']:
        hid,date=r['case_id'].split('__')
        for side in ('A','B'):
            local=ROOT/'results'/args.local/hid/date/side;remote=ROOT/'results'/args.server/hid/date/side
            aa=read(local/'TRACE.json.gz');bb=read(remote/'TRACE.json.gz');delta=0.
            for key,seq in aa['channels'].items():
                if key.startswith(('Zone Mean Air Temperature|','Zone Mean Radiant Temperature|','Water Heater Final Temperature Node ')):
                    delta=max(delta,max(abs(a[1]-b[1])for a,b in zip(seq[48:192],bb['channels'][key][48:192])))
            ea=total(energy(aa,'Electricity:Facility'),480,1920);eb=total(energy(bb,'Electricity:Facility'),480,1920)
            bound=max(.01,.001*max(ea,eb))
            rows.append({'case_id':r['case_id'],'side':side,'primary_max_temperature_delta_C':delta,
                         'local_primary_kWh':ea,'server_primary_kWh':eb,'energy_delta_kWh':eb-ea,
                         'energy_bound_kWh':bound,'within_predeclared_bounds':delta<=.01 and abs(eb-ea)<=bound,
                         'local_engine_sha256':read(local/'RESULT.json')['engine_sha256'],
                         'server_engine_sha256':read(remote/'RESULT.json')['engine_sha256']})
    report={'schema':VERSION,'passed':all(r['within_predeclared_bounds']for r in rows),'case_count':len(server['records']),'side_count':len(rows),
            'selection':'first six original same-master subset50 households,first saved date;before seeing Linux outcomes',
            'criteria':{'primary_max_temperature_delta_C':.01,'primary_facility_energy_delta':'max(0.01kWh,0.1%)'},
            'records':rows,'production_engine':'official EnergyPlus24.1 Linux Ubuntu22.04 x86_64'}
    save(ROOT/'CROSS_PLATFORM_REVIEW.json',report);print(canonical({'passed':report['passed'],'sides':len(rows),'max_temperature_delta_C':max(r['primary_max_temperature_delta_C']for r in rows),'max_energy_delta_kWh':max(abs(r['energy_delta_kWh'])for r in rows)}))
    if not report['passed']:raise SystemExit(2)

if __name__=='__main__':main()
