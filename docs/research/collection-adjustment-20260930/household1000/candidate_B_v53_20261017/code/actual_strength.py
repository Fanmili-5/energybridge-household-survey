"""Binning of observed executable magnitudes, never draft grade or human utility."""
from common import *
def band(value,thresholds):
    if abs(value)<1e-8:return 'none'
    return next((LEVELS[i]for i,t in enumerate(thresholds)if value<=t+1e-8),'extreme')
def annotate(observed,request):
    family=observed['device_family'];params=request['parameters'];controls=observed['control_segments']
    shifted=max([abs(x['start_shift_minutes'])for x in observed['program_changes']]+[0]);handled=max([abs(x['start_shift_minutes'])for x in observed['manual_operation_changes']]+[0])
    if family in('washer','dishwasher'):
        duration=params['program_duration_min'];thresholds=[__import__('math').ceil(duration*f/10-1e-9)*10 for f in(.25,.5,1.,2.)]
        axes={'program_shift_min':{'value':shifted,'grade':band(shifted,thresholds)},'manual_shift_min':{'value':handled,'grade':band(handled,thresholds)}};primary=axes['program_shift_min']if shifted else axes['manual_shift_min']
    elif family=='ev':
        metrics=observed['EV_window_metrics'];removed=max([1-(x['B_window_min'][1]-x['B_window_min'][0])/(x['A_window_min'][1]-x['A_window_min'][0])for x in metrics]+[0])
        shortage=max([max(0,-x['B_window_slack_minutes'])/x['constant_power_full_charge_minutes']for x in metrics]+[0]);delay=max([x['delay_minutes']for x in metrics]+[0])
        axes={'window_fraction_removed':{'value':removed,'grade':band(removed,[.25,.5,.75,1.])},'start_delay_min':{'value':delay,'grade':band(delay,[30,60,120,240])},'required_energy_shortfall_fraction':{'value':shortage,'grade':band(shortage,[.05,.15,.3,1.])}};primary=axes['window_fraction_removed']
    else:
        keys=['heating_setpoint_C','cooling_setpoint_C']if family=='ac'else['value_C']
        delta=max([abs(x['B'][k]-x['A'][k])for x in controls if x['A']and x['B']for k in keys]+[0])
        durations=[]
        for aid in observed['asset_ids']:
            rows=sorted([x for x in controls if x['asset_id']==aid],key=lambda x:x['start_min']);blocks=[]
            for x in rows:
                if blocks and blocks[-1][1]==x['start_min']:blocks[-1][1]=x['end_min']
                else:blocks.append([x['start_min'],x['end_min']])
            durations.extend(b-a for a,b in blocks)
        duration=max(durations+[0]);axes={'setpoint_delta_C':{'value':delta,'grade':band(delta,[.5,1,1.5,2]if family=='ac'else[1,2,3,5])},'continuous_command_change_min':{'value':duration,'grade':band(duration,[20,30,60,90])}};primary=axes['setpoint_delta_C']if delta else axes['continuous_command_change_min']
    observed.update(actual_strength_axes=axes,actual_primary_grade=primary['grade'],actual_primary_value=primary['value'],actual_grade_derived_from_raw_commands=True,grade_is_not_human_burden_or_physical_success=True,draft_grade_is_not_actual_grade=True)
    return observed
