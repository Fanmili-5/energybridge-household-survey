"""Bind the original 60 date slots to new A; no B or physical execution."""
import argparse
from pathlib import Path
from benchmark.ab_generation.common import read,save,digest
from benchmark.ab_generation.unified.pipeline import fresh_context
from benchmark.ab_generation.unified.contract import config


def export(review, original_inputs):
    review=Path(review);protocol=read(review/'PROTOCOL.json')
    sources={r['household_id']:r for r in protocol['inputs']};records=[]
    for r in read(original_inputs)['records']:
        h,date=r['household_id'],r['date'];source=sources[h]
        p=read(source['problem_path']);portrait=read(source['portrait_path']);a=read(review/h/'A.json.gz')
        if a['status']!='feasible':raise ValueError('NEW_A_NOT_FEASIBLE;KEEP_SLOT_DIAGNOSTIC')
        c=fresh_context(p,a,date,portrait,config({'A_target_context_mode':'life_conditional_v1'}))
        if c['source']['conditional_target_context_sha256']!=a['conditional_target_context']['sha256']:
            raise ValueError('TARGET_CONTEXT_BINDING_MISMATCH')
        if c['baseline_target_context']['rows']!=[x for x in a['conditional_target_context']['rows'] if x['source_date']==date]:
            raise ValueError('TARGET_ROWS_LOST')
        path=review/h/'contexts'/(date+'.json.gz');save(path,c)
        records.append(dict(household_id=h,date=date,context_path=str(path.resolve()),
                            portrait_path=source['portrait_path']))
    save(review/'NEW_A_B_INPUTS.json',dict(schema='eb.unified.inputs.v1',mode='fresh_generation',records=records))
    save(review/'CONTEXT_EXPORT.json',dict(selected_date_slots=len(records),
        original_date_slots_sha256=digest([(r['household_id'],r['date']) for r in read(original_inputs)['records']]),
        additional_lookahead_contexts_are_not_questionnaire_slots=True,B_generated=False,physical_runs=0))
    return len(records)


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--review',required=True);p.add_argument('--original-inputs',required=True)
    a=p.parse_args();print(export(a.review,a.original_inputs))
