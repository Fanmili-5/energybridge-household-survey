#!/usr/bin/env python3
"""Independent quadrature of released predictive bins; no generator import."""
import argparse
import copy
import hashlib
import json
import math
from pathlib import Path
from scipy.integrate import quad

HERE=Path(__file__).resolve().parent
def read(path):return json.loads(Path(path).read_text())
def sha(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()
def save(path,body):Path(path).write_text(json.dumps(body,ensure_ascii=False,indent=2,allow_nan=False)+'\n')


def integrate(bins,theta):
    # Integrate a uniform density within each bin after shifting its maximum.
    # Only finite bin mass ratios are used; individual source rows are absent.
    logs=[];means=[]
    for b in bins:
        lo,hi=b['lower_m2'],b['upper_m2'];width=hi-lo
        if width==0:
            logs.append(math.log(b['probability'])+theta*lo);means.append(lo)
            continue
        peak=hi if theta>=0 else lo
        density=lambda u:math.exp(theta*(lo+width*u-peak))
        z=quad(density,0,1,epsabs=1e-12,epsrel=1e-11,limit=100)[0]
        first=quad(lambda u:(lo+width*u)*density(u),0,1,epsabs=1e-10,epsrel=1e-11,limit=100)[0]
        if z<=0:raise ValueError('quadrature_bin_normalizer_underflow')
        logs.append(math.log(b['probability'])+theta*peak+math.log(z))
        means.append(first/z)
    peak=max(logs);weights=[math.exp(v-peak) for v in logs];total=sum(weights);p=[v/total for v in weights]
    mean=sum(v*m for v,m in zip(p,means))
    square=sum(b['source_weight_square_sum']*(v/b['probability'])**2 for b,v in zip(bins,p))
    maximum=max(b['maximum_source_weight']*v/b['probability'] for b,v in zip(bins,p))
    return {'expected_area_m2':mean,'posterior_source_ESS':1/square,
        'posterior_maximum_source_weight':maximum,'bin_probability_ESS':1/sum(v*v for v in p),
        'maximum_bin_probability':max(p)}


def verify(body):
    errors=[];maximum={k:0 for k in ['expected_area_m2','posterior_source_ESS','posterior_maximum_source_weight','bin_probability_ESS','maximum_bin_probability']}
    count=0
    for profile in body['profiles']:
        h=profile['housing']
        if not h['H5_is_ordinary_model_assigned']:continue
        got=integrate(h['H6_predictive_support_bins'],h['area_policy']['theta_per_m2']);count+=1
        for field,value in got.items():
            difference=abs(value-h['area_policy'][field]);maximum[field]=max(maximum[field],difference)
            if difference>1e-7*max(1,abs(value)):
                errors.append({'slot_id':profile['slot_id'],'field':field,'absolute_difference':difference})
    return {'pass':not errors,'ordinary_profiles_numerically_checked':count,'maximum_absolute_difference_by_field':maximum,'errors':errors}


def main():
    ap=argparse.ArgumentParser();ap.add_argument('--batch',default='final_tilt_tau20');ap.add_argument('--report');args=ap.parse_args()
    file=HERE/args.batch/'FAMILY_HOUSING_CANDIDATES.json';body=read(file)
    result=verify(body)
    controls=[]
    for field in ['expected_area_m2','posterior_source_ESS','posterior_maximum_source_weight']:
        mutant=copy.deepcopy(body);h=next(p['housing'] for p in mutant['profiles'] if p['housing']['H5_is_ordinary_model_assigned'])
        h['area_policy'][field]+=1
        checked=verify(mutant)
        controls.append({'mutation':field,'detected':not checked['pass'] and any(e['field']==field for e in checked['errors'])})
    result.update(schema='eb.generation_area_quadrature_QC.v1',batch=args.batch,profile_sha256=sha(file),
        code_sha256=sha(__file__),generator_imported=False,source_microdata_read=False,negative_controls=controls)
    result['pass']=result['pass'] and all(c['detected'] for c in controls)
    save(HERE/(args.report or 'AREA_QUADRATURE_QC.json'),result)
    print(json.dumps({k:v for k,v in result.items() if k not in ['errors']},ensure_ascii=False))
    if not result['pass']:raise SystemExit(1)


if __name__=='__main__':main()
