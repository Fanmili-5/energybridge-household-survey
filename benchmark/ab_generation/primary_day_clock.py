
"""Actual primary-method start_h clock, separate from programme completion."""
NATIVE_SOURCE_SHA256='be072673de26228a286e5ab9223d160a2a71084fa7b6c9146dbc5d024a879de9'

def attach_windows(context,problem):
    bindings={}
    for job in problem['jobs']:
        bindings.setdefault(job['asset_id'],{})[job['kind']]={
            'earliest_h':job['policy'].get('native_earliest_h',0.0),'latest_h':job['policy'].get('native_latest_h',24+job['policy']['duration_min']/60),
            'duration_h':job['policy']['duration_min']/60,
            'native_source_sha256':NATIVE_SOURCE_SHA256,
            'basis':'reference_programme_execution_envelope;not_a_new_human_availability_window'}
    context['native_execution_contract']['primary_programme_windows']=bindings
    if problem.get('native_appliance_configuration',{}).get('water_heater',{}).get('present'):
        context['native_execution_contract']['primary_water_heater_configuration']=dict(problem['native_appliance_configuration']['water_heater'])
    return context

def start_supported(context,before,after):
    if before is not None and all(before.get(k)==after.get(k) for k in ('start_min','end_min')):return True
    if context.get('question_unit')!='one_dated_household_day':return True
    spec=context.get('native_execution_contract',{}).get('primary_programme_windows',{}).get(after['asset_id'],{}).get(after['kind'])
    if not spec or spec.get('native_source_sha256')!=NATIVE_SOURCE_SHA256:return False
    start=after['start_min']/60;duration=(after['end_min']-after['start_min'])/60
    if abs(duration-spec['duration_h'])>1e-8 or start<context['decision_min']/60-1e-8:return False
    hod=start%24;earliest=spec['earliest_h'];latest=spec['latest_h'];overnight=latest<earliest
    # This is exactly how the public primary applier maps a start_h command.
    native_start=hod+(24 if overnight and hod<earliest else 0)
    native_end=(24+latest) if overnight else latest
    return 0<=hod<24 and abs(native_start-start)<1e-8 and earliest<=start<=native_end-duration+1e-8
