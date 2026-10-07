"""Actual pinned EB command acceptance;stdlib appliance API only, never EP."""
import collections, importlib.util
from common import *
source=UP/'energybridge/simulation/appliance_sim.py'
spec=importlib.util.spec_from_file_location('v16_pinned_appliance_kernel',source)
kernel=importlib.util.module_from_spec(spec);sys.modules[spec.name]=kernel;spec.loader.exec_module(kernel)
def main():
    school_guard();counts=collections.Counter();failures=[]
    for b in read(OUT/'WORLD_BINDINGS1000.json')['records']:
        w=read(OUT/b['world_path']);cfgs={k:dict(a['config']) for k,a in w['assets'].items()};cfgs['refrigerator']={'present':False}
        for index in range(1,11):
            p=read(OUT/'pairs'/w['household_id']/f'{index:02d}.json')
            for side in ['A','B']:
                suite=kernel.ApplianceSuite(cfgs,sim_days=3,explicit_only=True)
                suite._vpp_events=[]  # Only saved explicit A/B controls;no hidden DR response.
                for t in p[side]['tasks']:
                    ok=suite.shift_appliance(t['kind'],t['start_min']//1440,t['start_min']/60)
                    counts['shift_commands']+=1
                    if not ok:failures.append([p['case_id'],side,t['kind'],'native_shift_rejected'])
                for c in p[side]['controls']:
                    day=c['start_min']//1440;s=c['start_min']%1440/60;e=c['end_min']%1440/60
                    if e==0:e=24.
                    if c['kind']=='tank_setpoint':ok=suite.set_ewh_preheat_schedule(day,s,e,c['value_C']);counts['tank_commands']+=1
                    elif c['kind']=='ev_charge_window':ok=suite.set_ev_charge_window(day,s,e);counts['EV_commands']+=1
                    else:continue
                    if not ok:failures.append([p['case_id'],side,c['kind'],'native_control_rejected'])
                counts['plans_checked']+=1
    save(OUT/'NATIVE_INTERFACE_REVIEW.json',{'host':'school Linux','counts':dict(counts),'failures':failures,
        'kernel_sha256':sha(source),'EP_started':0,'model_API_calls':0,
        'scope':'actual EB appliance command methods invoked with saved canonical configs;no thermal or adoption inference',
        'AC_interface':'typed IDF schedule/thermostat mapping checked by saved-artifact schema and reference review',
        'WH_proxy_not_thermal_truth':True,'physical_combo_exclusion_enforced_by_joint_validator':True})
    print({'native_command_plans':counts['plans_checked'],'failures':len(failures)},flush=True)
    if failures:raise RuntimeError(str(failures[:10]))
if __name__=='__main__':main()
