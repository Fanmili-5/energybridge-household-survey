"""Quantify native delivery convergence without inventing a comfort tolerance."""
import csv
from collections import defaultdict

from national_idf.common import ROOT, read, require, save
from scripts.analyze_multicountry_life_numerics import PAIRS

OUT=ROOT/'reports/multicountry_joint_review_20261108'
NUM=ROOT/'reports/multicountry_life_20261108/numerics_life'


def native_grid(folder):
    domain=read(folder.parent/'DOMAIN.json');step=domain['solver_step_min']
    width=read(ROOT/'configs/study_protocol.json')['comparison_grid_min'];bins=defaultdict(lambda:[0.,0.,0.,0.])
    with (folder/'LIFE_SYSTEM.csv').open() as stream:
        for row in csv.DictReader(stream):
            mass=float(row['EB_WATER_dhw fixtures:total_kg_s'])*float(row['seconds'])
            volume=float(row['EB_WATER_dhw fixtures:total_m3'])*1000
            target=float(row['EB_WATER_dhw fixtures:target_C']);temperature=float(row['EB_WATER_dhw fixtures:mixed_C'])
            item=bins[int(row['frame_index'])*step//width]
            item[0]+=mass;item[1]+=mass*temperature;item[2]+=mass*max(target-temperature,0);item[3]+=volume
    return {k:{'kg':v[0],'delivery_C':v[1]/v[0] if v[0]>0 else None,
               'temperature_shortfall_K_kg':v[2],'L':v[3]} for k,v in bins.items()}


def execute(label):
    tag=label+'_normalized_draw_stress';comparisons={}
    def path(args,arm):
        step,warmup,days=args
        return NUM/f'{tag}_s{step}_w{warmup}_d{days}_{arm}'/'run'
    for name,left,right in PAIRS:
        data={};effects=[]
        for args in (left,right):
            service=[read(path(args,arm)/'WATER_SERVICE.json')['uses']['EB_WATER_dhw fixtures']['temperature_shortfall_K_kg']
                     for arm in ('baseline','intervention')]
            effects.append(service[1]-service[0])
        for arm in ('baseline','intervention'):
            a,b=[native_grid(path(args,arm)) for args in (left,right)]
            common=set(a)&set(b)
            require(common,'WATER_CONVERGENCE_NO_COMMON_GRID')
            active=[k for k in common if a[k]['kg']>0 and b[k]['kg']>0]
            require(active,'WATER_CONVERGENCE_NO_ACTIVE_DEMAND')
            errors=[abs(a[k]['delivery_C']-b[k]['delivery_C']) for k in active]
            data[arm]={'active_10min_bins':len(active),'delivery_MAE_C':sum(errors)/len(errors),
                'delivery_max_difference_C':max(errors),'common_volume_difference_L':sum(a[k]['L']-b[k]['L'] for k in common),
                'common_temperature_shortfall_difference_K_kg':sum(a[k]['temperature_shortfall_K_kg']-b[k]['temperature_shortfall_K_kg'] for k in common)}
        comparisons[name]={'arms':data,'paired_shortfall_effect_K_kg':effects,
            'paired_shortfall_sign_changed':effects[0]*effects[1]<0,
            'service_comfort_tolerance_C':None,'new_accuracy_threshold_added':False}
    save(OUT/(label+'_fixture_normalization')/'WATER_CONVERGENCE.json',{
        'schema':'national_idf.native_water_delivery_convergence.v1','comparisons':comparisons,
        'bath_or_personal_service_success_claimed':False,'formal_admitted':False})
    print(label,'water delivery and requested-target shortfall convergence quantified',flush=True)


if __name__=='__main__':
    for label in ('ES','US_apartment'):execute(label)
