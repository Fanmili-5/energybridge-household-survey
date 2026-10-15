"""Explicit temperature-flat nominal control, not fitted manufacturer data.

Keep original EB nominal capacity,COP,fan,flow/part-load functions and common
world/pairs. Change only the two temperature modifiers for a declared model
structure sensitivity in the fixed original50 summer cases. Native is retained.
"""
import copy,concurrent.futures,argparse
from common import *
from compile_inputs import get,put
from physics import run_all,read_all
FIELDS=['total_cooling_capacity_function_of_temperature_curve_name','energy_input_ratio_function_of_temperature_curve_name']

def prepare(c):
    d=copy.deepcopy(c);d['variant']='temperature_flat7';d['model_form']='given nominal temperature-flat modifier sensitivity; not empirical performance'
    for side in ('A','B'):
        b=d[side];rows=parse(OUT/b['IDF_path']);curves={r[1]:r for r in rows if r[0].startswith('Curve:')};mapping={}
        for coil in [r for r in rows if r[0]=='Coil:Cooling:DX:SingleSpeed']:
            for field in FIELDS:
                old=get(coil,field)
                if old not in mapping:
                    original=curves[old];r=copy.deepcopy(original);r[1]='v20_given_flat_'+old
                    for i,key in enumerate(['coefficient1_constant','coefficient2_x','coefficient3_x_2','coefficient4_y','coefficient5_y_2','coefficient6_x_y']):put(r,key,1 if i==0 else 0)
                    for key in ('minimum_value_of_x','minimum_value_of_y'):put(r,key,-100)
                    for key in ('maximum_value_of_x','maximum_value_of_y'):put(r,key,100)
                    rows.append(r);mapping[old]=r[1]
                put(coil,field,mapping[old])
        for row in rows:
            if row[0]=='Output:Variable':row[1]=mapping.get(row[1],row[1])
        path=OUT/'idfs/temperature_flat7'/c['household_id']/f'{c["round_index"]:02d}_{side}.idf';path.parent.mkdir(parents=True,exist_ok=True)
        atomic_text(path,'! Explicit nominal temperature-flat sensitivity;original EB functions are retained separately.\n'+dump(rows))
        if b.get('curve_observation_meta'):
            for m in b['curve_observation_meta']:
                m['curve']=mapping.get(m['curve'],m['curve']);m['bounds']=[[-100,100],[-100,100]];m['diagnostic']='declared unit temperature modifiers; not manufacturer fit data'
        b.update(IDF_path=str(path.relative_to(OUT)),IDF_sha256=sha(path),physical_variant='temperature_flat7',
            AC_temperature_modifiers='given unit modifiers; original coefficient rows unchanged and retained;no fitted-domain claim')
    return d

def compile_models():
    school_guard();rows=read(OUT/'COMPILED50.json')['records'];sel=read(OUT/'SELECTION50.json')['records'];summer={h['household_id']:next(r['round_index'] for r in h['rounds'] if 7<=int(r['date'][5:7])<=9) for h in sel}
    cs=[c for c in rows if c['variant']=='base7' and c['round_index']==summer[c['household_id']]]
    save(OUT/'MODEL_FORM_INPUTS.json',{'records':[prepare(c) for c in cs],'households':50,'IDFs':100,'EP_started':0,'native_replaced':False})
def summarize():
    results=[]
    for d in read(OUT/'MODEL_FORM_INPUTS.json')['records']:
        result=read(OUT/'readback/temperature_flat7'/d['household_id']/f'{d["round_index"]:02d}.json')
        native=read(OUT/'readback/base7'/d['household_id']/f'{d["round_index"]:02d}.json')
        results.append({'household_id':d['household_id'],'round_index':d['round_index'],
            'living_day_A_minus_B_difference_to_native_kWh':result['energy']['living_day']['A_minus_B_kWh']-native['energy']['living_day']['A_minus_B_kWh'],
            'same_pair_sha256':d['pair_sha256']})
    save(OUT/'MODEL_FORM_SENSITIVITY.json',{'schema':'eb.nominal_temperature_modifier_sensitivity.v2','households':50,'verified_runs':100,'records':results,
        'native_original_EB_reference_replaced':False,'only_temperature_modifiers_changed':True,
        'nominal_parameters_and_flow_partload_functions_preserved':True,
        'maximum_A_minus_B_difference_to_native_kWh':max(abs(r['living_day_A_minus_B_difference_to_native_kWh']) for r in results),
        'ranges_are_assumption_sensitivity_not_confidence_intervals':True,'no_favorable_model_selected':True,'other950_executed':False,'human_answers':0})
    print({k:v for k,v in read(OUT/'MODEL_FORM_SENSITIVITY.json').items() if k!='records'},flush=True)
def main():
    school_guard();p=argparse.ArgumentParser();p.add_argument('phase',choices=['compile','run','readback']);a=p.parse_args()
    if a.phase=='compile':compile_models()
    elif a.phase=='run':run_all(16,'model_form')
    else:read_all('model_form',16);summarize()
if __name__=='__main__':main()
