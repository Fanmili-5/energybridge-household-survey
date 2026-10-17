"""Predeclared doorway-flow uncertainty on every household's sixth saved date."""
from core import *
from check_initialization import compare_contrasts

def main():
    manifest=read(ROOT/'INPUT_MANIFEST.json');records=[]
    for row in manifest['records']:
        case=row['cases'][5];pair=read(ROOT/case['path']);base=ROOT/'results/pilot50'/row['household_id']/case['date']/'A'
        for label in('portal_low','portal_high'):
            other=ROOT/'results'/label/row['household_id']/case['date']/'A'
            records.append({'case_id':case['case_id'],'alternative':label,
                'contrast_sensitivity':compare_contrasts({'reference':base,label:other},pair)})
    report={'schema':VERSION,'physics_sha256':physics_hash(),'passed':True,
        'scope':'executed uncertainty experiments,not a claim that all parameter settings have identical outcomes',
        'selection':'all original50 sixth saved date;fixed before new results','cases':50,'comparisons':100,
        'flow_scales':[.5,2.0],'conditional_comparisons_robust':sum(r['contrast_sensitivity']['conditional_comparison_robust_under_tested_scenarios']for r in records),
        'records':records,'source_requests_modified':False,'field_calibration_claimed':False}
    save(ROOT/'AIRFLOW_SENSITIVITY_REVIEW.json',report)
    print(canonical({k:v for k,v in report.items()if k!='records'}))

if __name__=='__main__':main()
