"""Re-read1000 master families at existing EB household-resource granularity."""
import json,sys,hashlib,collections
from pathlib import Path
STAGE=Path(__file__).resolve().parents[1];MASTER=STAGE.parent/'household_master_v33_20261016';BASE=MASTER.parent
sys.path.insert(0,str(MASTER/'code'))
from common import read,sha,parse
from independent_review import errors

def main():
    rows=read(MASTER/'WORLD_BINDINGS1000.json')['records'];parents={r['household_id']:r for r in read(BASE/'substantive_repair_v30_20261015/SELECTION1000.json')['records']}
    bad=[];support=shared=people=0;classes=collections.Counter();examples=[]
    for r in rows:
        w=read(MASTER/r['world_path']);old=read(BASE/'substantive_repair_v30_20261015'/parents[r['household_id']]['world_path']);rowsidf=parse(MASTER/r['background_IDF_path'])
        e=errors(w,old,rowsidf)
        if sha(MASTER/r['world_path'])!=r['world_sha256']:e.append('WORLD_FILE_CHANGED')
        if sha(MASTER/r['background_IDF_path'])!=r['background_IDF_sha256']:e.append('SHELL_FILE_CHANGED')
        people+=w['N'];support+=bool(w['background_context']['nonresident_guardian']);shared+=bool(w['shared_context']['households'])
        classes[len({t for d in w['parameter_pack']['devices']for t in d['types']})]+=1
        if e:bad.append({'household_id':r['household_id'],'errors':sorted(set(e))})
        if r['household_id']in ['ordinary-v6-0139','ordinary-v6-0031','ordinary-v6-0003']:examples.append({'household_id':r['household_id'],'background':w['background_context']['living_arrangement'],'support':w['background_context']['daily_support_explanation'],'resource_conditions_are_given_not_observed':True})
    report={'accepted_at_EB_scenario_granularity':not bad,'households':len(rows),'target_residents':people,'guardian_supported_families':support,'shared_families':shared,'functional_class_counts':dict(classes),'errors':bad,
      'basis':'EB fixed household:members,calendars,shared devices,declared support and controllable resource conditions;no requirement for income/biography/parking market estimates',
      'scope':'logical and spatial consistency of declared synthetic reference households,not empirical population validation','example_reviews':examples,
      'master_bindings_sha256':sha(MASTER/'WORLD_BINDINGS1000.json'),'checker_sha256':sha(MASTER/'code/independent_review.py'),'review_tool_sha256':sha(__file__),'household_generator_or_data_changed':False}
    (STAGE/'FAMILY_EB_REVIEW.json').write_text(json.dumps(report,ensure_ascii=False,sort_keys=True)+'\n');print({k:v for k,v in report.items()if k not in('example_reviews','basis')})
    if bad:raise SystemExit(2)
if __name__=='__main__':main()
