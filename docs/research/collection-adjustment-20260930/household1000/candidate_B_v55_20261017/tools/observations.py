"""Summarize actual input-vector equivalence and directly referenced50-household rows."""
import sys,collections
from pathlib import Path
STAGE=Path(__file__).resolve().parents[1];sys.path.insert(0,str(STAGE/'code'))
from common import *

def main():
    b=read(OUT/'PAIR_BINDINGS10000.json');counts=collections.Counter();zero=[]
    for row in b['records']:
        for rr in row['rounds']:
            p=read(OUT/rr['path']);q=p['proposal'];counts['distinct_doses_'+str(q['actual_unique_dose_count'])]+=1
            for a in q['actual_device_strengths']:
                if not(a['program_changes']or a['manual_operation_changes']or a['control_segments']):
                    zero.append({'case_id':p['case_id'],'controller_key':a['controller_key'],'requested_grade':a['requested_grade']})
    for row in read(OUT/'SUBSET50.json')['records']:
        for r in row['rounds']:counts['subset_'+r['comparison_group']]+=1
    report={'counts':dict(counts),'requested_controllers_without_actual_change':zero,'clipped_or_equivalent_requests_are_not_relabelled_as_actual_grade':True}
    save(OUT/'review/截断与子集核查.json',report);print(canonical(report))

if __name__=='__main__':main()
