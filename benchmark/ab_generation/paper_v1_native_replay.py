"""Execution of the frozen paper-v1 appliance consumer, followed by native service traces."""
from copy import deepcopy
import contextlib,io,math
from .eb_primary import native_module
from .eb_agent_contract import complete_appliance_payload
from .paper_v1_clock import apply_appliance_actions,replay_clock,cooling_rows

def replay(problem,context,plan,native_path):
    native=native_module(native_path)
    suite=native.ApplianceSuite(deepcopy(problem['native_appliance_configuration']),sim_days=2,explicit_only=True)
    payload=complete_appliance_payload(plan)
    # Dated queue is a benchmark encoding. It invokes the same unchanged V1
    # consumer for the future-day part; it is not a new appliance action.
    with contextlib.redirect_stdout(io.StringIO()):
        apply_appliance_actions(suite,payload,context['decision_min']/60)
        if any(r['kind']=='ev_charge_window' and r['end_min']>1440 for r in plan['controls']):
            apply_appliance_actions(suite,{k:v for k,v in payload.items() if k.startswith('ev_')},24)
    tasks=[]
    for t in plan['tasks']:
        app=suite._shiftable[t['kind']]
        if app._days[0].scheduled_abs_h is None or abs(app._days[0].scheduled_abs_h*60-t['start_min'])>1e-7:
            raise ValueError('PAPER_V1_PROGRAMME_START_CHANGED')
        powers=[]
        for minute in range(0,1440,10):
            power=app.step(math.nextafter(minute/60,math.inf),1/6,False)
            if power>1e-10:powers.append([minute,minute+10,power])
        if not app._days[0].completed:raise ValueError('PAPER_V1_PROGRAMME_INCOMPLETE')
        if powers[0][0]!=t['start_min'] or powers[-1][1]!=t['end_min']:raise ValueError('PROGRAMME_EXECUTION_INTERVAL_DIFFERS')
        tasks.append(dict(kind=t['kind'],start_min=t['start_min'],end_min=t['end_min'],energy_kWh=sum(x[2]/6 for x in powers)))
    wh=next((r for r in plan['controls'] if r['kind']=='tank_setpoint' and r['start_min']<1440),None)
    if wh:
        state=suite._water_heater._days[0]
        if any(abs(state[k]-v)>1e-7 for k,v in [('preheat_start_h',wh['start_min']/60),('preheat_end_h',wh['end_min']/60),('preheat_temp_c',wh['value_C'])]):
            raise ValueError('PAPER_V1_WH_COMMAND_CHANGED')
    ev=[]
    if problem['EV']['connections']:
        conn=problem['EV']['connections'][0];cfg=problem['native_appliance_configuration']['ev']
        for minute in range(conn['start_min'],conn['end_min'],10):
            power=suite._ev.step(math.nextafter(minute/60,math.inf),1/6,False)
            if power>1e-10:ev.append([minute,minute+10,power])
        if suite._ev._soc<cfg['target_soc']-1e-7:raise ValueError('PAPER_V1_EV_TARGET_UNMET')
        if any(a[1]!=b[0] for a,b in zip(ev,ev[1:])):raise ValueError('PAPER_V1_EV_CHARGE_FRAGMENTED')
        expected=(cfg['target_soc']-cfg['initial_soc'])*cfg['capacity_kwh']/cfg['efficiency']
        if abs(sum(x[2]/6 for x in ev)-expected)>1e-6:raise ValueError('PAPER_V1_EV_ENERGY_CHANGED')
    clocks={asset:replay_clock(rows,context) for asset,rows in cooling_rows(plan).items()}
    if any(v['mismatches'] for v in clocks.values()):raise ValueError('PAPER_V1_AC_CLOCK_CHANGED_LITERAL_PLAN')
    return dict(passed=True,programmes=tasks,EV_positive_power_intervals=ev,AC_clock=clocks,
        WH_literal_window_accepted=bool(wh),original_paper_v1_consumer=True,
        preference_policy_or_acceptance_filter_applied=False,
        scope='literal native commands and traces;not full consent/LLM/occupancy/thermal simulation')
