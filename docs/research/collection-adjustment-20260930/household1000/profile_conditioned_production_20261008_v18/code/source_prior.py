"""Private local CHFS extraction, aggregate output only; no donor reassignment."""
import collections, sys
from pathlib import Path
from common import BASE, OUT, read, save, sha
sys.path.insert(0,str(BASE/'production_route_v6_20261004/code'))
import joint_motifs as jm
from bridge_rules import integer
sys.path.insert(0,str(BASE/'repair_execution_20261008_v1/code'))
from employment_semantics import decode_current_work

def band(age):
    return '0-17' if age<18 else '18-34' if age<35 else '35-54' if age<55 else '55-69' if age<70 else '70-79' if age<80 else '80+'

def main():
    records,qc=jm.load_source(); accepted={r['_private_id']:r for r in records}
    people=jm.rb.read('ind',['hhid','a2000c','a2005','a3100a','a3132b','a3131a'])
    counts=collections.Counter(); weighted=collections.Counter(); n=0
    for p in people.to_dict('records'):
        r=accepted.get(p['hhid'])
        if not r or integer(p['a2000c']) not in (1,2):continue
        age=r['visit_year']-integer(p['a2005']); proxy=integer(p['a3100a'])
        e=decode_current_work(proxy,integer(p['a3132b']),integer(p['a3131a']))
        key=(band(age),str(proxy),e['missing_kind'],e['current_work_evidence'])
        counts[key]+=1;weighted[key]+=r['weight'];n+=1
    src=next(jm.rb.PACKAGE.glob('chfs2021_ind_pub_*.dta'))
    result={'schema':'eb.CHFS_employment_aggregate.v1','source_years':[2021,2022],
        'source_file_sha256':sha(src),'frame_qc':qc,'co_resident_members':n,
        'scope':'same admitted city co-residence proxy frame as original whole-household motif; not census-identical or observed synthetic-role employment',
        'columns':['a3100a','a3132b','a3131a'],'raw_rows_or_ids_exported':0,
        'aggregate_prior_not_individual_skip_identification':True,
        'synthetic_members_reassigned_to_donors':False,
        'cells':[{'age_band':k[0],'A3100a':k[1],'missing_kind':k[2],
                  'current_work_evidence':k[3],'count':counts[k],'sum_household_weights':weighted[k]}
                 for k in sorted(counts)],
        'coding':{'1':'has work same main job','2':'has work changed main job','3':'no current work',
                  'null':'unknown; aggregate skip prevalence does not identify an individual skip'}}
    save(OUT/'SOURCE_EMPLOYMENT_AGGREGATES.json',result)
    print({'admitted_households':len(records),'co_resident_members':n,'aggregate_cells':len(counts),'raw_rows_exported':0})
if __name__=='__main__':main()
