"""Local review preview showing each actual axis, with no aggregate intensity."""
import sys,html
from pathlib import Path
STAGE=Path(__file__).resolve().parents[1];sys.path.insert(0,str(STAGE/'code'))
from common import *
def main():
    rows=[]
    for household in read(OUT/'PAIR_BINDINGS10000.json')['records']:
        for ref in household['rounds']:
            p=read(OUT/ref['path']);rows.append({'case':p['case_id'],'events':p['VPP_events'],'same':p['proposal']['same_command_as_A'],'devices':[{'device':x['controller_key'],'family':x['device_family'],'axes':x['strength_presentation']['axes'],'program':x['program_changes'],'handling':x['manual_operation_changes'],'EV':x['EV_window_metrics'],'thermal':x['strength_presentation']['thermal_intervals']}for x in p['proposal']['actual_device_strengths']],'pair_path':ref['path'],'EV_continuity':{k:p['EV_continuous_reference'].get(k)for k in('status','recovery_status','common_SOC_restored_after_request_min','interval_min','changed_need_ids')},'thermal_phases':p['B'].get('thermal_phase_requests',[]),'program_plans':p['B'].get('program_request_plans',[]),'impact_summary':p['VPP_response_reference'],'conflicts':p['assessment_B']['constraint_flags'],'human_acceptance':None})
    save(OUT/'review/多轴强度展示数据.json',{'schema':'eb.multiaxis_display.v57','bindings_sha256':sha(OUT/'PAIR_BINDINGS10000.json'),'cases':rows,'no_overall_grade':True})
    data=canonical(rows).replace('<','\\u003c');body=(OUT/'tools/multiaxis_preview_template.html').read_text().replace('__DATA__',data)
    (OUT/'review/多轴强度预览.html').write_text(body);print({'preview_cases':len(rows),'overall_grade':None})
if __name__=='__main__':main()
