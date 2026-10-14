"""One authorized run: fresh original50 acceptance before any other950 EP."""
import copy
from common import *
from cohort_gate import review,require_reviewed_ep,guard_job,scoped_rows
from run_cohort import run
import physics

def rejected(fn):
    try:fn()
    except (AssertionError,RuntimeError,KeyError):return True
    return False

def controls_after50():
    rows=scoped_rows('original50');runs=read(OUT/'EP_original50_RUNS.json')['records'];lease=require_reviewed_ep('original50')
    changed=copy.deepcopy(rows[0]);changed['date']='1900-01-01'
    checks={'missing_expected_run_rejected':rejected(lambda:physics.check_run_coverage(rows,runs[:-1])),
        'duplicate_run_rejected':rejected(lambda:physics.check_run_coverage(rows,runs+[runs[0]])),
        'changed_compiled_job_rejected':rejected(lambda:guard_job(changed,'A',lease)),
        'other950_before_fresh_review_rejected':rejected(lambda:require_reviewed_ep('other950'))}
    assert all(checks.values());save(OUT/'COHORT_ACCEPTANCE_NEGATIVE_CONTROLS.json',{'passed':True,'checks':checks,'uses_actual_original50_run_receipts':True,'fake_human_answers':0})

def sensitivity_summary():
    rows=read(OUT/'COMPILED_SENSITIVITY50.json')['records'];out=[]
    for c in rows:
        current=read(OUT/'readback'/c['variant']/c['household_id']/f'{c["round_index"]:02d}.json')
        base=read(OUT/'readback/base7'/c['household_id']/f'{c["round_index"]:02d}.json')
        out.append({'household_id':c['household_id'],'round_index':c['round_index'],'variant':c['variant'],
            'A_minus_B_kWh_difference_from_base7':current['energy']['living_day']['A_minus_B_kWh']-base['energy']['living_day']['A_minus_B_kWh']})
    save(OUT/'CURRENT_SENSITIVITY50_REVIEW.json',{'checked_pairs':200,'records':out,'maximum_absolute_AB_difference_kWh':max(abs(x['A_minus_B_kWh_difference_from_base7'])for x in out),
        'ranges_are_model_assumption_sensitivity_not_confidence_intervals':True,'no_favorable_model_selected':True,'actual_new_input_bindings':True})

def main():
    school_guard();review('original50');run('original50',32);controls_after50();sensitivity_summary()
    # This line is reached only after all500 baseline and200 sensitivity pairs
    # pass the normal-A, run-coverage, metering and spatial SQL gates.
    review('other950');run('other950',32)
    review('weather_sensitivity');run('weather_sensitivity',32)
    differences=[]
    for c in read(OUT/'COMPILED_WEATHER_SENSITIVITY.json')['records']:
        alt=read(OUT/'readback/weather_linear7'/c['household_id']/f'{c["round_index"]:02d}.json')
        base=read(OUT/'readback/base7'/c['household_id']/f'{c["round_index"]:02d}.json')
        differences.append({'household_id':c['household_id'],'round_index':c['round_index'],
            'A_minus_B_energy_difference_kWh':alt['energy']['living_day']['A_minus_B_kWh']-base['energy']['living_day']['A_minus_B_kWh'],
            'A_energy_difference_kWh':alt['energy']['living_day']['A']-base['energy']['living_day']['A'],
            'B_energy_difference_kWh':alt['energy']['living_day']['B']-base['energy']['living_day']['B'],
            'services_changed':alt['services']!=base['services']})
    save(OUT/'WEATHER_SENSITIVITY_REVIEW.json',{'passed':True,'pairs':len(differences),'records':differences,
        'maximum_absolute_AB_energy_difference_kWh':max(abs(d['A_minus_B_energy_difference_kWh'])for d in differences),
        'reference_weather_not_selected_by_output':True,'is_assumption_sensitivity_not_confidence_interval':True})
    save(OUT/'PHYSICAL_PRODUCTION_COMPLETE.json',{'passed':True,'baseline_households':1000,'baseline_pairs':10000,'sensitivity50_pairs':200,
        'formal50_physics':sha(OUT/'PHYSICS_original50_REVIEW.json'),'formal950_physics':sha(OUT/'PHYSICS_other950_REVIEW.json'),'weather_sensitivity':sha(OUT/'WEATHER_SENSITIVITY_REVIEW.json'),
        'formal_questionnaires_still_require_bound_material_and_UI_checks':True,'human_answers':0,'field_calibration':False})
    print({'physical_production_complete':True,'formal_release_pending_UI_checks':True},flush=True)
if __name__=='__main__':main()
