"""One isolated compiler process per explicitly bound pair."""
import json
import os
import sys
from pathlib import Path


def main():
    job = json.loads(Path(sys.argv[1]).read_text())
    os.environ['EB_HOUSING_INPUT_ROOT'] = job['resource_root']
    os.environ['EB_REFERENCE_ACH'] = str(job['settings']['reference_ach'])
    os.environ['EB_PORTAL_FLOW_SCALE'] = str(job['settings']['portal_flow_scale'])
    for key in ('people_scale','lighting_scale','misc_scale','simulation_timestep_min','airflow_model'):
        os.environ['EB_'+key.upper()]=str(job['settings'][key])
    from .kernel.compiler import compile_model
    from .kernel.core import read
    pack, pair = read(job['household_path']), read(job['pair_path'])
    for side in ('A', 'B'):
        compile_model(pack, pair, side, Path(job['output']) / side,
                      job['settings']['history_days'], job['settings']['tail_days'])


if __name__ == '__main__':
    main()
