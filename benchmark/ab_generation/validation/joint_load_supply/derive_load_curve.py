"""Reproduce the selected laboratory curve shape and its out-of-condition error."""
import argparse
import csv
from pathlib import Path
from benchmark.ab_generation.common import read, save, sha


def derive(out):
    folder=Path(__file__).parent; out=Path(out);out.mkdir(parents=True,exist_ok=False)
    rows=list(csv.DictReader((folder/'LARCO_KUBO2_COTTON40.csv').open()))
    train=sorted((float(r['target_load']),float(r['total_energy_consumed_wh'])/1000) for r in rows if r['ambient_temp']=='16')
    test=sorted((float(r['target_load']),float(r['total_energy_consumed_wh'])/1000) for r in rows if r['ambient_temp']=='32')
    points=[[m/5,e/train[-1][1]] for m,e in train]
    model=read(folder.parents[1]/'LAUNDRY_MODEL.json')
    if points!=model['curves']['washer']['points']:
        raise ValueError('EMPIRICAL_CURVE_SHAPE_MISMATCH')
    observed=dict(test); predictions=[{'target_mass_kg':m,'training_16C_kWh':e,'heldout_32C_kWh':observed[m],
        'absolute_error_kWh':abs(e-observed[m])}for m,e in train]
    result={'schema':'eb.laundry_shape_validation.v1','source_csv_sha256':sha(folder/'LARCO_KUBO2_COTTON40.csv'),
        'shape_reproduced':True,'training_records':len(train),'heldout_records':len(test),'normalized_points':points,
        'out_of_condition_MAE_kWh':sum(r['absolute_error_kWh']for r in predictions)/len(predictions),
        'out_of_condition_records':predictions,'empirical_monotonicity_assumed':False,
        'benchmark_absolute_scale_or_cycle_duration_validated_by_this_fit':False,
        'scope':'one laboratory appliance/program;different ambient condition exposes transfer error;not household calibration'}
    save(out/'LOAD_SHAPE.json',result);return result


if __name__=='__main__':
    p=argparse.ArgumentParser(__doc__);p.add_argument('--out',required=True);a=p.parse_args();print(derive(a.out))
