#!/usr/bin/env python3
"""Catch circular production gates and identify the exact incomplete layer."""
import copy
import json
from pathlib import Path

HERE=Path(__file__).resolve().parent
def errors(d):
    result=[];layers=d['layers'];byid={x['id']:x for x in layers}
    if len(byid)!=len(layers):result.append('duplicate_layer')
    visiting=set();visited=set()
    def visit(k):
        if k in visiting:result.append('readiness_dependency_cycle:'+k);return
        if k in visited:return
        if k not in byid:result.append('unknown_dependency:'+k);return
        visiting.add(k)
        for parent in byid[k]['depends_on']:visit(parent)
        visiting.remove(k);visited.add(k)
    for k in byid:visit(k)
    for k in ['statistical_candidate','conditional_IDF']:
        if 'observed_human_answers' in byid[k]['required']:result.append('human_answers_required_before_generation_or_IDF:'+k)
        if 'gold_and_training' in byid[k]['depends_on']:result.append('later_answers_gate_used_as_generation_prerequisite:'+k)
    return result

def main():
    d=json.loads((HERE/'LAYERED_READINESS.json').read_text());probes=[]
    for name,mutate in [
        ('source_depends_on_its_generated_households',lambda x:x['layers'][0]['depends_on'].append('statistical_candidate')),
        ('generation_requires_future_human_answers',lambda x:x['layers'][1]['required'].append('observed_human_answers')),
        ('IDF_requires_training_completion',lambda x:x['layers'][2]['depends_on'].append('gold_and_training'))]:
        m=copy.deepcopy(d);mutate(m);probes.append({'mutation':name,'detected':bool(errors(m))})
    result={'schema':'eb.layered_readiness_verification.v1','pass':not errors(d) and all(x['detected'] for x in probes),
        'errors':errors(d),'negative_controls':probes,'layers':[{'id':x['id'],'status':x['status']} for x in d['layers']],
        'scope':'readiness dependency logic; neither source/model validity nor release approved'}
    (HERE/'LAYER_VERIFICATION.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n')
    print(json.dumps({'pass':result['pass'],'layers':len(d['layers']),'negative_controls':len(probes)}))
    if not result['pass']:raise SystemExit(1)

if __name__=='__main__':main()
