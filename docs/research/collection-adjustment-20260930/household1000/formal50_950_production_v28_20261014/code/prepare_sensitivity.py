"""Repeat the declared original50 history/inlet/model-form checks with current inputs."""
import concurrent.futures,copy,datetime as dt
from common import *
from physics import compile_job
from model_form_diagnostic import prepare

def main():
    school_guard();selected=read(OUT/'SELECTION1000.json')['records'];ids=set(read(OUT/'PARTITIONS.json')['formal50']);sel=[h for h in selected if h['household_id']in ids]
    assert len(sel)==50 and read(OUT/'STATIC_PRODUCTION_COMPLETE.json')['passed']
    jobs=[];summer={}
    for h in sel:
        c=next(r for r in h['rounds']if 7<=int(r['date'][5:7])<=9);summer[h['household_id']]=c['round_index']
        jobs.extend((h,c,v)for v in('prior14','seasonal7','seasonal14'))
    with concurrent.futures.ProcessPoolExecutor(max_workers=24)as pool:rows=list(pool.map(compile_job,jobs))
    bases=[c for c in read(OUT/'COMPILED1000.json')['records']if c['household_id']in ids and c['round_index']==summer[c['household_id']]]
    flat=[prepare(c)for c in bases];assert len(rows)==150 and len(flat)==50
    # Check model-form changes independently by reversing only the declared two
    # modifier substitutions and removing only their additional curve rows.
    failures=[]
    for c,changed in zip(bases,flat):
        for side in('A','B'):
            old=parse(OUT/c[side]['IDF_path']);new=parse(OUT/changed[side]['IDF_path']);reverse={r[1]:r[1].removeprefix('v20_given_flat_')for r in new if r[0].startswith('Curve:')and r[1].startswith('v20_given_flat_')}
            restored=[[reverse.get(x,x)for x in row]for row in new if not(row[0].startswith('Curve:')and row[1]in reverse)]
            if restored!=old:failures.append([c['household_id'],side,'MODEL_FORM_ALTERS_OTHER_INPUT'])
    save(OUT/'COMPILED_SENSITIVITY50.json',{'records':rows+flat,'paired_variants':200,'IDFs':400,'summer_rounds':summer,'EP_started':0})
    save(OUT/'SENSITIVITY_INPUT_AUDIT.json',{'status':'pass'if not failures else'fail','failures':failures,'history_inlet_pairs':150,'model_form_pairs':50,
        'fixed_original50_summer_dates':True,'same_EB_hardware_and_given_worlds':True,'only_declared_temperature_modifier_changes':not failures,'EP_started':0})
    if failures:raise RuntimeError(str(failures[:5]))
    print({'current_original50_sensitivity_pairs':200,'input_audit':'pass','EP_started':0},flush=True)
if __name__=='__main__':main()
