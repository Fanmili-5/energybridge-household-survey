"""Explicit empty-domain and evidence-missing admission boundary checks."""
import argparse
import copy
from pathlib import Path
from unittest.mock import patch
from benchmark.ab_generation.common import read,save
from benchmark.ab_generation.unified.candidates import generate_day
from benchmark.ab_generation.unified.contract import config


def run(out):
    c=read(Path(__file__).parents[1]/'ab_generation/examples/control.json')
    c['reference']['thermal']={};c['reference']['information_set']['mode']='offline_unexecuted_A_plan'
    grammar=dict(values=[],descriptors=[],domains=[],engineering_diagnostics=[],gaps=[],raw_count=0,
        unmodified=0,support_domain=[],scope='controlled_empty_domain_test')
    c['devices']=[];c['needs']=[];c['A']=dict(tasks=[],operations=[],controls=[])
    c['reference']['ev_charging_steps']=[]
    records=[]
    for missing in (False,True):
        g=copy.deepcopy(grammar)
        if missing:g['gaps']=[dict(reason='controlled_missing_evidence')]
        with patch('benchmark.ab_generation.unified.candidates.catalogue_domains',return_value=g):
            r=generate_day(c,config())
        expected='search_unresolved' if missing else 'candidate_catalogue'
        records.append(dict(missing_evidence=missing,status=r['status'],rows=len(r['rows']),
            passed=r['status']==expected and len(r['rows'])==(0 if missing else 1),
            no_opportunity_reasons=[x.get('no_opportunity_reason') for x in r['rows']]))
    result=dict(passed=all(x['passed'] for x in records),records=records,scope='controlled boundary tests;not household opportunity evidence')
    save(Path(out)/'EMPTY_DOMAIN_CHECK.json',result);return result


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--out',required=True);a=p.parse_args();print(run(a.out))
