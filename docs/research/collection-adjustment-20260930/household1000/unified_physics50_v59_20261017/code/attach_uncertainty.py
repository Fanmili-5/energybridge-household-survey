"""Attach actual diagnostic results without changing requests or physical traces."""
from core import *

def main():
    review=read(ROOT/'results/pilot50/REVIEW.json')
    histories={r['case_id']:r['contrast_sensitivity']for r in read(ROOT/'INITIALIZATION_REVIEW.json')['records']}
    air={}
    for r in read(ROOT/'AIRFLOW_SENSITIVITY_REVIEW.json')['records']:
        air.setdefault(r['case_id'],[]).append({'alternative':r['alternative'],**r['contrast_sensitivity']})
    for record in review['records']:
        path=ROOT/record['path'];summary=read(path);cid=record['case_id']
        summary['simulation_uncertainty']={'scope':'conditional reference outcomes;not observed household predictions',
            'history_individually_tested':cid in histories,'history_contrast_sensitivity':histories.get(cid),
            'portal_flow_individually_tested':cid in air,'portal_flow_contrast_sensitivity':air.get(cid),
            'untested_cases_not_assumed_individually_robust':True,'sensitivity_does_not_create_acceptance_labels':True}
        save(path,summary);record['sha256']=sha(path)
    review['uncertainty_reports']={name:sha(ROOT/name)for name in('INITIALIZATION_REVIEW.json','AIRFLOW_SENSITIVITY_REVIEW.json')}
    save(ROOT/'results/pilot50/REVIEW.json',review)
    print(canonical({'attached_cases':len(review['records']),'history_cases':len(histories),'airflow_cases':len(air),'source_schedules_modified':False}))

if __name__=='__main__':main()
