"""Fail-closed cache keys for the physical validation tool."""
from pathlib import Path
import hashlib,json

def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()

def context(root,ep):
    root=Path(root);ep=Path(ep)
    names=['scripts/verify_regional_resources.py','scripts/validation_cache.py',
           'scripts/audit_upstream_appliance_binding.py','scripts/audit_device_interface_controls.py',
           'realtime_pilot/simulation_environment.py','realtime_pilot/native_assets.py',
           'upstream_2b17ae6/energybridge/data/day_ahead.py',
           'upstream_2b17ae6/experiments/benchmark/family_runner.py']
    engines=[p for p in ep.iterdir() if p.is_file() and (p.name in {'energyplus','energyplus.exe','Energy+.idd'} or 'energyplusapi' in p.name)]
    if not engines or not (ep/'Energy+.idd').is_file():raise ValueError('Incomplete EnergyPlus installation')
    files={n:sha(root/n) for n in names}
    files.update({'engine/'+p.name:sha(p) for p in engines})
    files.update({'engine/'+str(p.relative_to(ep)):sha(p) for p in (ep/'pyenergyplus').glob('*.py')})
    return {'version':'eb.validation_context.v1','files':files,'sha256':hashlib.sha256(json.dumps(files,sort_keys=True).encode()).hexdigest()}

def reusable(row,model,weather,old_context,new_context):
    return bool(row and row.get('passed') and old_context and old_context==new_context
        and row.get('model_sha256')==model['sha256']
        and row.get('weather_sha256')==weather['epw_sha256']
        and row.get('localization',{}).get('design_days_sha256')==weather['ddy_sha256'])
