"""No API; deterministic native EP pair and appliance conservation check."""
from pathlib import Path
from common import ROOT,normalize_answers,write_json
from paired_contract import QUESTIONS,LOOKUP,prepare
from proposal_contract import executable
from paired_ep import run,pair_metrics

def answers():
    return {'M_MEMBERS':[{'routine':'out_regular','comfort':'normal_comfort','task':'semi_rigid','participation':None} for _ in range(3)],'B02':'3','B04':'mostly_absent','B05':['ac','washer','dishwasher','dryer','electric_water_heater','home_ev'],
      'F_EVENING':'mostly_home','F_REGULARITY':'regular','F_LATE_USE':'rarely',
      'H_ac':'afternoon','H_ac_temp':'25','H_washer':'evening','D_washer':'22',
      'H_dishwasher':'evening','D_dishwasher':'22','H_dryer':'night','D_dryer':'24','E_washer':'8','E_dishwasher':'8','E_dryer':'8','T_washer':'2.0','T_dishwasher':'1.5','T_dryer':'1.5',
      'D_electric_water_heater':'23','D_home_ev':'8',
      'H_electric_water_heater':'night','H_home_ev':'late','P_COMFORT':'4','P_COST':'4','P_GRID':'3','P_NOTICE':'1','P_AC_RANGE':'24_26','P_AC_CHANGE':'1','P_EV_TARGET':'0.8','P_EV_RESERVE':'0.2','P_HOT_WATER':'21','P_PREHEAT':'confirm','A_EB_CONTROL':'confirm_required'}

def main():
    profile=normalize_answers(answers(),list(LOOKUP),LOOKUP)
    original,scenario=prepare(profile,'physics_probe_v1')
    # Force a known legal treatment in this physics-only test, independent of random-event sampler tests.
    scenario.update(decision_h=17,event={'trigger_h':18,'end_h':19,'day':4,'id':'physics_test'})
    p0=executable(original);p1=executable(original);p1['setpoint']=27;p1['appliances']['washer_start_h']=19;p1['appliances']['dishwasher_start_h']=19
    folder=ROOT/'data/paired_physics_v1_2';a=run(folder/'baseline',original,p0,scenario,profile);b=run(folder/'proposal',original,p1,scenario,profile,is_proposal=True)
    result=pair_metrics(a,b,scenario);write_json(folder/'verification.json',result);print(result)
if __name__=='__main__':main()
